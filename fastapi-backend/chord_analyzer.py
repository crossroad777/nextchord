"""
chord_analyzer.py
Demucs 音源分離 + madmom CNN/CRF コード認識 + Basic Pitch ノート認識
の統合モジュール。

パイプライン:
  input.wav
    ↓ Demucs (htdemucs, 4-stem)
    ├── other.wav → madmom CNNChordFeatureProcessor + CRFChordRecognitionProcessor
    ├── other.wav → Basic Pitch (ノート認識 / タブ譜用)
    └── bass.wav  → ルート音補強
    ↓
  アンサンブル → 最終コードタイムライン
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import time
import warnings
from typing import List, Optional, Tuple, Dict

os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')
warnings.filterwarnings('ignore')

# ============================================================
# Demucs 音源分離
# ============================================================

def separate_audio(
    wav_path: str,
    output_dir: str,
    model: str = 'htdemucs',
    device: str = 'cuda',
) -> Dict[str, str]:
    """
    Demucs で4-stem分離を実行。

    Returns
    -------
    dict: {'vocals': path, 'drums': path, 'bass': path, 'other': path}
    """
    wav = pathlib.Path(wav_path)
    out = pathlib.Path(output_dir)
    stem_dir = out / model / wav.stem

    # すでに分離済みならスキップ
    stems = {}
    all_exist = True
    for stem_name in ('vocals', 'drums', 'bass', 'other'):
        p = stem_dir / f'{stem_name}.wav'
        if p.exists():
            stems[stem_name] = str(p)
        else:
            all_exist = False

    if all_exist and len(stems) == 4:
        print(f'[Demucs] Using cached separation: {stem_dir}')
        return stems

    print(f'[Demucs] Running {model} separation on {wav_path}...')
    cmd = [
        'python', '-m', 'demucs',
        '--model', model,
        '--device', device,
        '--out', str(out),
        str(wav_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            # CPU fallback
            print(f'[Demucs] GPU failed, trying CPU...')
            cmd[cmd.index(device)] = 'cpu'
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f'Demucs failed: {result.stderr[:500]}')
    except subprocess.TimeoutExpired:
        raise RuntimeError('Demucs timed out (>5min)')

    # 出力ファイルを収集
    stems = {}
    for stem_name in ('vocals', 'drums', 'bass', 'other'):
        p = stem_dir / f'{stem_name}.wav'
        if p.exists():
            stems[stem_name] = str(p)
    
    print(f'[Demucs] Done. Stems: {list(stems.keys())}')
    return stems


# ============================================================
# madmom CNN/CRF コード認識（BTCレベルの深層学習）
# ============================================================

_chord_processors = None

def _get_chord_processors():
    global _chord_processors
    if _chord_processors is None:
        from madmom.features.chords import (
            CNNChordFeatureProcessor,
            CRFChordRecognitionProcessor,
        )
        print('[madmom] Loading CNN chord feature processor...')
        cnn = CNNChordFeatureProcessor()
        print('[madmom] Loading CRF chord recognition processor...')
        crf = CRFChordRecognitionProcessor()
        _chord_processors = (cnn, crf)
        print('[madmom] Processors ready.')
    return _chord_processors


def analyze_chords_madmom(
    wav_path: str,
    beat_times: List[float],
) -> List[Tuple[float, str]]:
    """
    madmom CNN + CRF でコードを認識。
    BTCレベルの精度（~87% WCSR）。

    Returns
    -------
    list of (time, chord_name) — ビート同期済み
    """
    cnn, crf = _get_chord_processors()
    
    print(f'[madmom] Extracting CNN chord features from {wav_path}...')
    features = cnn([wav_path])
    
    print(f'[madmom] Running CRF chord recognition...')
    chord_segments = crf(features)
    # chord_segments: [(start, end, 'C:maj'), (start, end, 'A:min'), ...]

    print(f'[madmom] Detected {len(chord_segments)} chord segments')

    # madmom形式 → 汎用形式に変換
    # 'C:maj' → 'C', 'A:min' → 'Am', 'G:7' → 'G7' など
    def convert_label(label: str) -> str:
        if not label or label in ('N', 'X', 'N.C.'):
            return 'N.C.'
        parts = label.split(':')
        root = parts[0].replace('b', 'b')  # Cb, Db等はそのまま
        quality = parts[1] if len(parts) > 1 else 'maj'
        
        quality_map = {
            'maj':    '',
            'min':    'm',
            '7':      '7',
            'maj7':   'maj7',
            'min7':   'm7',
            'maj6':   '',    # 簡略化
            'min6':   'm',
            'dim':    'dim',
            'dim7':   'dim7',
            'aug':    'aug',
            'sus2':   'sus2',
            'sus4':   'sus4',
            'hdim7':  'm7b5',
            'minmaj7': 'm',  # 簡略化
            '9':      '7',   # 簡略化
            'maj9':   'maj7',
            'min9':   'm7',
            '11':     '7',
            '13':     '7',
        }
        suffix = quality_map.get(quality, '')
        return root + suffix

    # ビート単位でコードをスナップ
    timeline = []
    prev_chord = None
    for t in (beat_times or [0.0]):
        # この時刻に対応するセグメントを探す
        chord = 'N.C.'
        for seg in chord_segments:
            seg_start = float(seg[0])
            seg_end   = float(seg[1])
            if seg_start <= t < seg_end:
                chord = convert_label(str(seg[2]))
                break
        timeline.append((t, chord))
        prev_chord = chord

    return timeline


# ============================================================
# Bass ルート音補強
# ============================================================

def get_bass_roots(
    bass_wav: str,
    beat_times: List[float],
) -> Dict[float, str]:
    """
    bass.wav から各ビートのルート音を推定。
    コードのルートが曖昧な場合の補強に使用。
    
    Returns: {beat_time: root_note_name}
    """
    try:
        import librosa
        import numpy as np
        
        NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        y, sr = librosa.load(bass_wav, sr=22050, mono=True)
        roots = {}
        
        for i, t in enumerate(beat_times):
            t_end = beat_times[i + 1] if i + 1 < len(beat_times) else t + 0.6
            start_sample = int(t * sr)
            end_sample   = int(t_end * sr)
            segment = y[start_sample:end_sample]
            
            if len(segment) < 512:
                continue
            
            # 基音検出 (yin/pyin)
            f0, voiced, _ = librosa.pyin(
                segment, sr=sr,
                fmin=librosa.note_to_hz('B1'),  # ~61Hz
                fmax=librosa.note_to_hz('B3'),  # ~247Hz
            )
            valid_f0 = f0[voiced & ~np.isnan(f0)]
            if len(valid_f0) == 0:
                continue
            
            median_f0 = float(np.median(valid_f0))
            midi_num = int(round(librosa.hz_to_midi(median_f0)))
            root_pc = midi_num % 12
            roots[t] = NOTE_NAMES[root_pc]
        
        return roots
    except Exception as e:
        print(f'[Bass] Root detection failed: {e}')
        return {}


# ============================================================
# アンサンブル
# ============================================================

def ensemble_final(
    madmom_timeline: List[Tuple[float, str]],
    bp_timeline: Optional[List[Tuple[float, str]]],
    bass_roots: Dict[float, str],
    beat_times: List[float],
) -> List[Tuple[float, str]]:
    """
    madmom + Basic Pitch + Bass ルートを統合して最終コードを決定。

    優先順位:
    1. madmom (主力)
    2. Bass ルートとmadmomが矛盾する場合 → Basic Pitchで仲裁
    3. どちらも信頼できない場合 → madmomを採用
    """
    NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    def chord_root(c: str) -> str:
        if not c or c in ('N.C.', 'X', 'N'):
            return ''
        return c[:2] if len(c) > 1 and c[1] in '#b' else c[:1]

    def lookup(timeline, t):
        result = None
        for tt, c in timeline:
            if tt <= t:
                result = c
            else:
                break
        return result

    result = []
    prev = None

    for t in beat_times:
        mm_chord  = lookup(madmom_timeline, t) or 'N.C.'
        bp_chord  = lookup(bp_timeline, t) if bp_timeline else None
        bass_root = bass_roots.get(t)

        mm_root = chord_root(mm_chord)
        bp_root = chord_root(bp_chord) if bp_chord else None

        chosen = mm_chord  # デフォルトはmadmom

        if bass_root and mm_root and bass_root != mm_root:
            # Bass と madmom のルートが食い違う
            if bp_root == bass_root:
                # Basic Pitch が bass に同意 → madmom が間違いかも
                # Basic Pitchのコードを採用
                chosen = bp_chord
            elif bp_root == mm_root:
                # Basic Pitch が madmom に同意 → madmom採用
                chosen = mm_chord
            else:
                # 全て不一致 → madmomを信頼
                chosen = mm_chord

        if chosen != prev:
            result.append((t, chosen))
            prev = chosen

    return result


# ============================================================
# メインエントリポイント
# ============================================================

def run_full_chord_analysis(
    wav_path: str,
    session_dir: str,
    beat_times: List[float],
    key_str: str = 'C major',
    run_basic_pitch: bool = True,
) -> dict:
    """
    フルパイプライン実行:
      Demucs → madmom + Basic Pitch → アンサンブル

    Returns
    -------
    dict:
        'chord_timeline': [(time, chord), ...]  最終コード
        'note_events':    Basic Pitch の音符データ (タブ譜用)
        'stems':          分離された各ステムのパス
    """
    print(f'[ChordAnalyzer] Starting full analysis: {wav_path}')
    t0 = time.time()

    # Step 1: Demucs 音源分離
    stems = separate_audio(wav_path, session_dir)
    other_wav = stems.get('other', wav_path)
    bass_wav  = stems.get('bass')

    # Step 2: madmom CNN/CRF コード認識（other.wav）
    print(f'[ChordAnalyzer] madmom chord recognition...')
    madmom_tl = analyze_chords_madmom(other_wav, beat_times)

    # Step 3: Basic Pitch ノート認識（other.wav）
    bp_timeline = None
    note_events = []
    if run_basic_pitch:
        try:
            from note_to_chord import (
                run_basic_pitch as _run_bp,
                build_chord_timeline,
                key_name_to_root,
                smooth_chord_timeline,
            )
            key_root, key_type = key_name_to_root(key_str)
            print(f'[ChordAnalyzer] Basic Pitch note recognition...')
            note_events = _run_bp(other_wav)
            bp_raw = build_chord_timeline(note_events, beat_times, key_root, key_type)
            bp_timeline = smooth_chord_timeline(bp_raw, min_duration=1.0)
        except Exception as e:
            print(f'[ChordAnalyzer] Basic Pitch failed (non-fatal): {e}')

    # Step 4: Bass ルート音補強
    bass_roots = {}
    if bass_wav:
        try:
            bass_roots = get_bass_roots(bass_wav, beat_times)
        except Exception as e:
            print(f'[ChordAnalyzer] Bass root detection failed (non-fatal): {e}')

    # Step 5: アンサンブル
    print(f'[ChordAnalyzer] Ensembling results...')
    final_timeline = ensemble_final(madmom_tl, bp_timeline, bass_roots, beat_times)

    elapsed = time.time() - t0
    print(f'[ChordAnalyzer] Done in {elapsed:.1f}s. {len(final_timeline)} chord changes.')

    return {
        'chord_timeline': final_timeline,
        'note_events':    note_events,
        'stems':          stems,
        'madmom_timeline': madmom_tl,
        'bp_timeline':    bp_timeline,
    }
