"""
NextChord Pipeline
==================
コード抽出パイプラインの実装。
main.py から分離された run_pipeline() 関数を含む。

依存関係:
    - chord_processing (セクション分析、コード処理、キー推定)
    - note_transcription (ノート検出)
    - tab_generator (TAB/MusicXML生成)
    - lyrics_postprocess (歌詞後処理)
    - phrase_processor (フレーズ分割)
"""

import time
import json
import csv
import threading
import concurrent.futures
from pathlib import Path

import numpy as np
import gc
import librosa

from chord_processing import (
    analyze_sections,
    standardize_chord,
    _smooth_chord_segments,
    _beat_majority_chords,
    _normalize_chords_to_key,
    estimate_key_from_audio,
    detect_song_type,
    key_consensus,
)
from btc_engine import get_btc_engine
try:
    from chordmini_engine import get_chordmini_engine
    _HAS_CHORDMINI = True
except ImportError:
    _HAS_CHORDMINI = False

# GPU排他ロック: Whisper/Demucs等のGPUモデルを同時実行しないための排他制御
_gpu_lock = threading.Lock()


import re as _re

# =============================================================================
# Whisper ハルシネーション検出
# =============================================================================
_HANGUL_RE = _re.compile(r'[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]')
_EMOJI_RE = _re.compile(
    r'[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\U00002702-\U000027B0'
    r'\U0000FE00-\U0000FE0F\U0001F000-\U0001F02F]'
)
_KNOWN_HALLUCINATIONS = [
    'soundhodori', 'sound hodori', '사운드호돌이',
    'thank you for watching', 'thanks for watching',
    'please subscribe', 'like and subscribe',
    'music by', 'subtitles by',
    '視聴してくださって', '視聴ありがとう', 'ご視聴ありがとう',
    'チャンネル登録', 'グッドボタン', '高評価',
    '歌唱', '作詞', '作曲', '編曲', '何', '歌・',
]

def _is_hallucination(text: str) -> bool:
    """Whisperのハルシネーション（韓国語・絵文字・繰り返し）を検出"""
    if not text or len(text.strip()) == 0:
        return True
    t = text.strip()
    
    # 韓国語（ハングル）が含まれている
    if _HANGUL_RE.search(t):
        return True
    
    # 絵文字が多い（テキストの30%以上が絵文字）
    emoji_count = len(_EMOJI_RE.findall(t))
    if emoji_count > 0 and emoji_count / max(1, len(t)) > 0.3:
        return True
    
    # 既知のハルシネーション文字列
    t_lower = t.lower()
    for h in _KNOWN_HALLUCINATIONS:
        if h in t_lower:
            return True
    
    # 同じ文字の繰り返し（例: "ああああああ" "歌 歌 歌 歌"）
    stripped = t.replace(' ', '').replace('・', '').replace('、', '')
    if len(stripped) >= 4:
        unique_chars = set(stripped)
        if len(unique_chars) <= 2:
            return True
    
    # 同じ単語が3回以上繰り返される（例: "歌 歌 歌 歌 歌"）
    words = t.split()
    if len(words) >= 3:
        from collections import Counter as _Counter
        word_counts = _Counter(words)
        most_common_count = word_counts.most_common(1)[0][1]
        if most_common_count >= 3 and most_common_count / len(words) > 0.5:
            return True
    
    return False


def _estimate_time_signature(beat_times, bpm, wav_path=None):
    """
    ビート配列とBPMから拍子(time signature)を推定する。

    SoloTabのbeat_detector.pyのアクセントパターン解析を参考に、
    NextChordのデータ構造に合わせて再実装。

    方法:
      1. librosaのonset strengthを各ビート位置でサンプリング
      2. 3拍子グループと4拍子グループのアクセントスコアを比較
      3. BPMの自然さスコアも加味して総合判定

    Parameters
    ----------
    beat_times : array-like
        ビート時刻の配列(秒)
    bpm : float
        推定BPM
    wav_path : str or Path, optional
        音声ファイルパス。指定時はonset strengthベースの推定を行う。
        未指定時はデフォルト4/4を返す。

    Returns
    -------
    str
        "3/4" or "4/4"
    """
    beat_times = np.asarray(beat_times, dtype=float)

    if len(beat_times) < 8:
        return "4/4"

    # --- onset strengthベースのアクセントパターン解析 ---
    if wav_path is not None:
        try:
            y, sr = librosa.load(str(wav_path), sr=22050, mono=True)
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            times = librosa.times_like(onset_env, sr=sr)

            # 各ビート時刻でのonset strengthを取得
            beat_strengths = np.array([
                onset_env[min(np.argmin(np.abs(times - bt)), len(onset_env) - 1)]
                for bt in beat_times
            ])
            if beat_strengths.max() > 0:
                beat_strengths = beat_strengths / beat_strengths.max()

            # 3拍子 vs 4拍子のアクセントスコア
            score_3 = _compute_accent_score(beat_strengths, 3)
            score_4 = _compute_accent_score(beat_strengths, 4)

            # BPM自然さスコア
            # 3/4の場合BPMが高めに出る傾向を補正して評価
            bpm_if_3 = bpm * 2.0 / 3.0 if bpm > 100 else bpm
            nat_3 = _bpm_naturalness_score(bpm_if_3)
            nat_4 = _bpm_naturalness_score(bpm)

            # 総合スコア: アクセント60% + BPM自然さ40%
            combined_3 = score_3 * 0.6 + nat_3 * 0.4
            combined_4 = score_4 * 0.6 + nat_4 * 0.4

            print(f"[time_sig] Accent scores: 3/4={score_3:.3f}, 4/4={score_4:.3f}")
            print(f"[time_sig] Combined: 3/4={combined_3:.3f} (bpm~{bpm_if_3:.0f}), "
                  f"4/4={combined_4:.3f} (bpm~{bpm:.0f})")

            # 4/4が圧倒的に一般的。3/4が勝つには明確なマージンが必要。
            MARGIN = 0.15
            if combined_3 > combined_4 + MARGIN:
                print(f"[time_sig] -> Estimated 3/4")
                return "3/4"
            else:
                print(f"[time_sig] -> Estimated 4/4")
                return "4/4"

        except Exception as e:
            print(f"[time_sig] Accent analysis failed ({e}), defaulting to 4/4")

    return "4/4"


def _compute_accent_score(beat_strengths, beats_per_bar):
    """
    指定された拍子でグループ化した時のアクセントパターンスコアを計算。
    1拍目が強く、他が弱いほどスコアが高い。
    """
    n = len(beat_strengths)
    if n < beats_per_bar * 2:
        return 0.0

    full_bars = n // beats_per_bar
    if full_bars < 2:
        return 0.0

    truncated = beat_strengths[:full_bars * beats_per_bar]
    reshaped = truncated.reshape(full_bars, beats_per_bar)

    # 各拍位置の平均accent strength
    avg_by_position = reshaped.mean(axis=0)
    if avg_by_position.sum() == 0:
        return 0.0

    # 1拍目の相対的な強さ
    downbeat_strength = avg_by_position[0]
    other_avg = avg_by_position[1:].mean()

    if other_avg > 0:
        ratio = downbeat_strength / other_avg
    else:
        ratio = 2.0

    # 分散の逆数で一貫性を評価
    variances = reshaped.var(axis=0)
    consistency = 1.0 / (1.0 + variances.mean())

    return min(ratio * consistency * 0.5, 1.0)


def _bpm_naturalness_score(bpm):
    """
    BPMが音楽的に自然な範囲にあるかのスコア。
    60-120 BPMが最も自然（アコギ曲の典型的テンポ範囲）。
    """
    if 60 <= bpm <= 120:
        return 1.0
    elif 50 <= bpm < 60 or 120 < bpm <= 135:
        return 0.6
    elif 45 <= bpm < 50 or 135 < bpm <= 160:
        return 0.3
    else:
        return 0.1



def _fast_beat_detect(wav_path):
    """librosaベースの高速ビート検出（madmom RNNBeatProcessorの代替）
    
    madmom RNNBeatProcessor (~45s) を librosa beat_track (~5s) で置き換え。
    戻り値: beat_times (1D array) - 直接ビート時刻を返す（act変換不要）
    """
    import librosa
    import numpy as np
    import time as _time
    t0 = _time.time()
    try:
        y, sr = librosa.load(str(wav_path), sr=22050, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units='frames')
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        print(f"[BEATS] librosa beat_track: {len(beat_times)} beats, tempo={float(tempo) if hasattr(tempo,'__float__') else tempo}, {_time.time()-t0:.1f}s")
        return beat_times
    except Exception as e:
        print(f"[BEATS] librosa beat_track failed: {e}, returning empty")
        return np.array([])


def run_pipeline(session_id: str, session_dir: Path, wav_path: Path, ctx: dict):
    """
    コード抽出パイプラインをバックグラウンドで実行（究極の並列化・インプロセス）
    
    並列実行するタスク:
      Group A: Beats, Key, Whisper, Notes (Demucs+basic-pitch)
      Group B: HPS -> Chroma -> Chord判定
    Group A と B は完全に並列で実行され、合流後に結果を統合する。
    
    Parameters
    ----------
    session_id : str
        セッションID
    session_dir : Path
        セッションディレクトリ
    wav_path : Path
        WAVファイルパス
    ctx : dict
        グローバルコンテキスト。以下のキーが必要:
        - sessions: セッション辞書
        - save_session: save_session関数
        - SessionStatus: SessionStatusクラス
        - beat_processor, beat_tracker: ビート検出モデル
        - key_processor: キー検出モデル
        - chroma_processor, chord_processor: コード検出モデル
        - whisper_model: Whisperモデル
        - transcribe_notes: ノート検出関数
        - notes_to_tab_data, notes_to_musicxml: TAB/MusicXML生成関数
        - estimate_key_from_chords, generate_chord_strum_notes: ユーティリティ
    """
    # コンテキストからグローバル変数を取得
    sessions = ctx["sessions"]
    save_session = ctx["save_session"]
    SessionStatus = ctx["SessionStatus"]
    beat_processor = ctx.get("beat_processor")
    beat_tracker = ctx.get("beat_tracker")
    key_processor = ctx.get("key_processor")
    chroma_processor = ctx.get("chroma_processor")
    chord_processor = ctx.get("chord_processor")
    whisper_model = ctx.get("whisper_model")
    transcribe_notes = ctx.get("transcribe_notes")
    notes_to_tab_data = ctx.get("notes_to_tab_data")
    notes_to_musicxml = ctx.get("notes_to_musicxml")
    estimate_key_from_chords_fn = ctx.get("estimate_key_from_chords")
    generate_chord_strum_notes = ctx.get("generate_chord_strum_notes")
    
    start_total = time.time()
    try:
        sessions[session_id]["status"] = SessionStatus.PROCESSING
        session_data = sessions[session_id]
        
        # --- BTC + Chroma + Chord を一括実行するヘルパー ---
        def _chroma_chords(wav_p, sess_dir, sid):
            """BTC (Bi-directional Transformer) -> Chord判定
            
            優先順位:
              1. Demucs 分離済み other.wav -> BTC (ボーカル除去済み)
              2. raw WAV -> BTC
              3. librosa template matching (フォールバック)
            """
            
            t_chr = time.time()
            seg_s, seg_l = None, None
            
            # 音声ロード（sections検出 + librosaフォールバック共用）
            # NOTE: このlibrosa.loadはThreadPoolExecutor内で実行されるため、
            # ビートフォールバック(L583付近)のlibrosa.loadとは共有しない。
            # 異なるスレッドでのndarray共有は競合リスクがあるため意図的に分離。
            y_full, sr_full = librosa.load(str(wav_p), sr=22050)
            
            # --- Demucs 分離済みステムを探す (ボーカル除去) ---
            # 優先: htdemucs_6s/guitar.wav > htdemucs/other.wav > raw WAV
            btc_input_path = wav_p  # デフォルト: raw WAV
            
            # 1st: htdemucs_6s の guitar.wav (ギター専用ステム)
            htdemucs_6s_dir = sess_dir / "htdemucs_6s"
            if htdemucs_6s_dir.exists():
                for cand in htdemucs_6s_dir.iterdir():
                    if cand.is_dir() and (cand / "guitar.wav").exists():
                        btc_input_path = cand / "guitar.wav"
                        print(f"[{sid}] [BTC] Using 6s guitar stem (guitar-dedicated)")
                        break
            
            # 2nd: htdemucs の other.wav (フォールバック)
            if btc_input_path == wav_p:
                htdemucs_dir = sess_dir / "htdemucs"
                if htdemucs_dir.exists():
                    for cand in htdemucs_dir.iterdir():
                        if cand.is_dir() and (cand / "other.wav").exists():
                            btc_input_path = cand / "other.wav"
                            print(f"[{sid}] [BTC] Using htdemucs other.wav (vocal-free)")
                            break
            
            if btc_input_path == wav_p:
                print(f"[{sid}] [BTC] Using raw WAV (no Demucs stems available)")
            
            # --- コード認識エンジン（ChordMini優先、BTCフォールバック） ---
            seg_s, seg_l = None, None
            chord_engine_used = None
            
            # 1st: ChordMini (BTC student + KD, +3-5% accuracy)
            if _HAS_CHORDMINI:
                try:
                    cm = get_chordmini_engine()
                    with _gpu_lock:
                        cm.load()
                        seg_s, seg_l = cm.detect_chords(btc_input_path)
                        cm.unload()  # VRAM解放
                    chord_engine_used = 'ChordMini'
                    from collections import Counter
                    label_counts = Counter(seg_l)
                    print(f"[{sid}] [ChordMini] Total segments: {len(seg_l)}, top: {label_counts.most_common(10)}")
                except Exception as e:
                    print(f"[{sid}] [ChordMini] Failed: {e}, falling back to BTC")
                    import traceback; traceback.print_exc()
            
            # 2nd: BTC fine-tuned (fallback)
            if seg_s is None:
                try:
                    btc = get_btc_engine()
                    with _gpu_lock:
                        btc.load()
                        seg_s, seg_l = btc.detect_chords(btc_input_path)
                        # BTC VRAM解放
                        try:
                            btc.model.cpu()
                        except Exception:
                            pass
                        gc.collect()
                        import torch as _t; _t.cuda.empty_cache() if _t.cuda.is_available() else None
                    chord_engine_used = 'BTC'
                    from collections import Counter
                    label_counts = Counter(seg_l)
                    print(f"[{sid}] [BTC] Total segments: {len(seg_l)}, top: {label_counts.most_common(10)}")
                except Exception as e:
                    print(f"[{sid}] [BTC] Failed: {e}, falling back to librosa")
                    import traceback; traceback.print_exc()
            
            # --- librosa フォールバック ---
            if seg_s is None or seg_l is None or len(seg_s) == 0:
                print(f"[{sid}] [DEBUG] Using librosa chroma fallback...")
                seg_s, seg_l = _librosa_chord_detection(y_full, sr_full, sid)
            
            # Section Detection (軽量: 固定ラベリング) -- y_fullを再利用
            secs = analyze_sections(y_full, sr_full)
            
            chr_sec = time.time() - t_chr
            print(f"[{sid}] [PERF] Chroma+Chord: {chr_sec:.1f}s")
            _update_step(session_data, "chords", f"[OK] コード解析 ({chr_sec:.0f}s)")
            
            return {
                'sections': secs,
                'seg_starts': seg_s,
                'seg_labels': seg_l,
            }
        
        def _librosa_chord_detection(y_harmonic, sr, sid):
            """librosaベースのコード検出（改良版: 8テンプレート + CQT/STFT統合 + メディアンフィルタ）"""
            # チューニング推定
            tuning = librosa.estimate_tuning(y=y_harmonic, sr=sr)
            
            # Chroma CQT + STFT を統合（単体より安定）
            hop_length = 2048
            chroma_cqt = librosa.feature.chroma_cqt(
                y=y_harmonic, sr=sr, hop_length=hop_length, n_chroma=12,
                tuning=tuning
            )
            chroma_stft = librosa.feature.chroma_stft(
                y=y_harmonic, sr=sr, hop_length=hop_length, n_chroma=12,
                tuning=tuning
            )
            # 50:50 統合
            chroma = (chroma_cqt + chroma_stft) / 2.0
            
            # コードテンプレート定義（8種類）
            chord_templates = {}
            note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            templates = {
                'maj':  np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], dtype=float),
                'min':  np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0], dtype=float),
                '7':    np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0], dtype=float),
                'min7': np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0], dtype=float),
                'maj7': np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1], dtype=float),
                'dim':  np.array([1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0], dtype=float),
                'sus4': np.array([1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0], dtype=float),
                'sus2': np.array([1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0], dtype=float),
            }
            
            for i, name in enumerate(note_names):
                for qual, tmpl in templates.items():
                    chord_templates[f"{name}:{qual}"] = np.roll(tmpl, i)
            
            # フレームごとにテンプレートマッチング
            n_frames = chroma.shape[1]
            frame_chords = []
            frame_scores = []
            
            for f in range(n_frames):
                frame = chroma[:, f]
                if np.sum(frame) < 0.01:
                    frame_chords.append("N")
                    frame_scores.append(0.0)
                    continue
                
                # 正規化
                frame_norm = frame / (np.linalg.norm(frame) + 1e-8)
                
                best_chord = "N"
                best_score = 0.3  # 最低閾値
                
                for chord_name, template in chord_templates.items():
                    template_norm = template / (np.linalg.norm(template) + 1e-8)
                    score = np.dot(frame_norm, template_norm)
                    if score > best_score:
                        best_score = score
                        best_chord = chord_name
                
                frame_chords.append(best_chord)
                frame_scores.append(best_score)
            
            # メディアンフィルタ: 3フレーム窓で短い揺らぎを除去
            if len(frame_chords) > 3:
                smoothed = list(frame_chords)
                for i in range(1, len(smoothed) - 1):
                    if smoothed[i] != smoothed[i-1] and smoothed[i] != smoothed[i+1] and smoothed[i-1] == smoothed[i+1]:
                        smoothed[i] = smoothed[i-1]
                frame_chords = smoothed
            
            # 隣接する同一コードをセグメントに統合
            if not frame_chords:
                return np.array([0.0]), np.array(['N'])
            
            seg_starts = []
            seg_labels = []
            prev_chord = None
            frame_duration = hop_length / sr
            
            for i, chord in enumerate(frame_chords):
                if chord != prev_chord:
                    seg_starts.append(i * frame_duration)
                    seg_labels.append(chord)
                    prev_chord = chord
            
            # 短すぎるセグメント（0.3秒未満）を前のセグメントにマージ
            merged_starts = [seg_starts[0]]
            merged_labels = [seg_labels[0]]
            min_duration = 0.3
            
            for i in range(1, len(seg_starts)):
                duration = seg_starts[i] - merged_starts[-1]
                if duration < min_duration and len(merged_starts) > 1:
                    continue
                merged_starts.append(seg_starts[i])
                merged_labels.append(seg_labels[i])
            
            seg_s = np.array(merged_starts)
            seg_l = np.array(merged_labels)
            
            n_unique = len(set(merged_labels) - {'N'})
            print(f"[{sid}] [LIBROSA] Detected {len(merged_labels)} chord segments ({n_unique} unique chords)")
            print(f"[{sid}] [LIBROSA] Tuning offset: {tuning:+.2f} semitones")
            
            return seg_s, seg_l
        
        # --- リアルタイム進捗追跡 ---
        def _update_step(sd, step_name, msg):
            """完了したステップを追跡し、プログレスメッセージを更新"""
            if "_steps" not in sd:
                sd["_steps"] = {}
            sd["_steps"][step_name] = msg
            # 完了ステップ数 / 全ステップ数 を計算
            total_steps = 4  # beats, key, whisper, chords+postprocess
            done = len(sd["_steps"])
            pct = int(done / total_steps * 100)
            # 最新の完了ステップを表示
            latest = list(sd["_steps"].values())[-1]
            sd["progress"] = f"解析中... ({done}/{total_steps}) {latest}"
            save_session(session_id)
        
        # === タスク実行（GPU競合回避のため順序最適化） ===
        # CPU系タスク: beats, key, HPS+Chroma -> 即座に並列開始
        # GPU系タスク: Whisper -> 完了後 -> Demucs + basic-pitch（VRAM 8GBで同時利用不可）
        futures = {}
        session_data["_steps"] = {}
        session_data["progress"] = "解析中... (0/4) [MUSIC] 解析開始"
        save_session(session_id)
        
        perf_log = []
        perf_log.append(f"=== NextChord Pipeline Log ===")
        perf_log.append(f"Session: {session_id}")
        perf_log.append(f"WAV: {wav_path}")
        perf_log.append(f"Models: beat_processor={'OK' if beat_processor else 'NONE'}, key_processor={'OK' if key_processor else 'NONE'}, whisper={'OK' if whisper_model else 'NONE'}, transcribe_notes={'OK' if transcribe_notes else 'NONE'}")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            print(f"[{session_id}] [PIPELINE] Starting all tasks...")
            
            # CPU系タスクを一気に投入
            # Optimization 1: librosa beat_track (~5s) instead of madmom RNNBeatProcessor (~45s)
            futures['act'] = executor.submit(_fast_beat_detect, wav_path)
            # Optimization 2: key_processor deferred - submit only if chroma/chord keys disagree
            futures['key_vec'] = None
            futures['chroma_chords'] = executor.submit(
                _chroma_chords, wav_path, session_dir, session_id
            )
            
            # Whisper (GPU) を先に実行
            # faster-whisper / openai-whisper 両対応
            try:
                from faster_whisper import WhisperModel as _FW
            except ImportError:
                _FW = None
            _is_faster = isinstance(whisper_model, _FW) if (whisper_model and _FW is not None) else False
            print(f"[{session_id}] [WHISPER] model type: {type(whisper_model).__name__}, _is_faster={_is_faster}", flush=True)
            perf_log.append(f"[DEBUG] Whisper model: {type(whisper_model).__name__}, _is_faster={_is_faster}")
            
            def _whisper_with_lock(model, wav, sid):
                """GPU排他ロック付きWhisper実行（faster-whisper / openai-whisper 両対応）"""
                debug_path = session_dir / "whisper_debug.txt"
                def _dbg(msg):
                    print(f"[{sid}] [WHISPER] {msg}", flush=True)
                    with open(debug_path, "a", encoding="utf-8") as f:
                        f.write(f"{msg}\n")
                
                _dbg(f"_is_faster={_is_faster}, model_type={type(model).__name__}")
                _dbg(f"Waiting for GPU lock...")
                with _gpu_lock:
                    print(f"[{sid}] [WHISPER] GPU lock acquired, starting transcription...", flush=True)
                    if _is_faster:
                        # faster-whisper API
                        try:
                            print(f"[{sid}] [WHISPER] faster-whisper transcribe starting...", flush=True)
                            segments_iter, info = model.transcribe(
                                str(wav),
                                language="ja",
                                word_timestamps=True,
                                condition_on_previous_text=False,
                                no_speech_threshold=0.3,
                                vad_filter=False,
                                beam_size=5,
                                temperature=0.0,
                            )
                            print(f"[{sid}] [WHISPER] transcribe() returned, lang={info.language}, prob={info.language_probability:.2f}, dur={info.duration:.1f}s", flush=True)
                            perf_log.append(f"[DEBUG] Whisper info: lang={info.language}, prob={info.language_probability:.2f}, dur={info.duration:.1f}s")
                            # openai-whisper互換形式に変換
                            segments = []
                            all_text = []
                            for seg in segments_iter:
                                text = seg.text.strip()
                                
                                # ハルシネーション判定（韓国語・絵文字・繰り返し）
                                is_halluc = _is_hallucination(text)
                                
                                # セグメント全体がハルシネーション確定 → 即スキップ
                                # ワードレベル救出はしない（1文字ワードで誤通過するため）
                                if is_halluc:
                                    try:
                                        print(f"[{sid}] [WHISPER] Filtered hallucination [{seg.start:.1f}s-{seg.end:.1f}s]: {text[:80]}")
                                    except Exception:
                                        print(f"[{sid}] [WHISPER] Filtered hallucination segment [{seg.start:.1f}s-{seg.end:.1f}s]")
                                    continue
                                
                                # ワードタイムスタンプがある場合: ワードレベルで部分的なハルシネーションを除去
                                # （セグメント自体はis_halluc=Falseだが、冒頭に「作詞・」等が混入している場合）
                                if seg.words:
                                    import re
                                    words_list = [
                                        {'start': w.start, 'end': w.end, 'word': w.word}
                                        for w in seg.words
                                    ]
                                    _hiragana_re = re.compile(r'[\u3040-\u309F]')
                                    _katakana_re = re.compile(r'[\u30A0-\u30FF]')
                                    _kanji_re = re.compile(r'[\u4E00-\u9FFF]')
                                    # 音楽クレジット系ハルシネーションキーワード
                                    _halluc_kw = {'作詞', '作曲', '編曲', '歌詞', '提供', '制作', '収録', '発売', '演奏', '何',
                                                  'Movie', 'movie', 'Music', 'music', 'Video', 'video',
                                                  'Subscribe', 'subscribe', 'Sound', 'sound'}
                                    _punct_re = re.compile(r'^[\s\u3000・、。\-―─…♪♫\u200b]+$')
                                    _hangul_re_local = re.compile(r'[\uAC00-\uD7AF\u1100-\u11FF]')
                                    
                                    clean_words = []
                                    found_real = False
                                    for w in words_list:
                                        word_text = w['word'].strip()
                                        if not word_text:
                                            continue
                                        # 韓国語ワード → 常にスキップ
                                        if _hangul_re_local.search(word_text):
                                            continue
                                        if not found_real:
                                            # ハルシネーションキーワードを含む → スキップ
                                            if any(kw in word_text for kw in _halluc_kw):
                                                continue
                                            # 中黒・スペースだけ → スキップ
                                            if _punct_re.match(word_text):
                                                continue
                                            # ひらがな/カタカナ/漢字を含む = 実際の歌詞開始
                                            if (_hiragana_re.search(word_text) or 
                                                _katakana_re.search(word_text) or
                                                _kanji_re.search(word_text)):
                                                found_real = True
                                            else:
                                                continue
                                        clean_words.append(w)
                                    
                                    if clean_words:
                                        words_list = clean_words
                                        cleaned_text = ''.join(w['word'] for w in clean_words).strip()
                                        removed_count = len(seg.words) - len(clean_words)
                                        if removed_count > 0:
                                            print(f"[{sid}] [WHISPER] Cleaned segment [{seg.start:.1f}s-{seg.end:.1f}s]: "
                                                  f"removed {removed_count} halluc words, kept: {cleaned_text[:60]}")
                                        seg_dict = {
                                            'id': seg.id,
                                            'start': clean_words[0]['start'],
                                            'end': clean_words[-1].get('end', seg.end),
                                            'text': cleaned_text,
                                            'words': words_list,
                                        }
                                        segments.append(seg_dict)
                                        all_text.append(cleaned_text)
                                        continue
                                    else:
                                        # 全ワードがハルシネーション
                                        print(f"[{sid}] [WHISPER] All words hallucination [{seg.start:.1f}s-{seg.end:.1f}s], skipping")
                                        continue
                                
                                # ワードタイムスタンプなし: セグメントレベルで判定
                                if is_halluc:
                                    try:
                                        print(f"[{sid}] [WHISPER] Filtered hallucination [{seg.start:.1f}s-{seg.end:.1f}s]: {text[:80]}")
                                    except Exception:
                                        print(f"[{sid}] [WHISPER] Filtered hallucination segment [{seg.start:.1f}s-{seg.end:.1f}s]")
                                    continue
                                
                                seg_dict = {
                                    'id': seg.id,
                                    'start': seg.start,
                                    'end': seg.end,
                                    'text': text,
                                }
                                segments.append(seg_dict)
                                all_text.append(text)
                            print(f"[{sid}] [WHISPER] faster-whisper done: {len(segments)} segments", flush=True)
                            # NOTE: initial_prompt は既に削除済み。
                            # 以前のprompt固有テキスト除去ロジックは廃止。
                            
                            # --- ハルシネーション除去で生じたギャップを再認識 ---
                            # ワードレベルフィルタで全ワード除去されたセグメントがあると、
                            # その時間帯の歌詞が消失する（例: 「君を忘れない」）。
                            # 消失区間を特定し、その部分だけ再度Whisperで認識する。
                            try:
                                import librosa
                                import soundfile as sf
                                import tempfile
                                
                                # 最初のセグメントの開始時刻が遅い場合、冒頭にギャップがある
                                first_seg_start = segments[0]['start'] if segments else 0
                                # 歌の冒頭で10秒以上のギャップがあれば再認識対象
                                if first_seg_start > 15.0 and segments:
                                    gap_start = max(0, first_seg_start - 10)  # 歌い出し直前の10秒に絞る
                                    gap_end = first_seg_start + 1  # 少し重複
                                    print(f"[{sid}] [WHISPER] Detected gap before first lyrics: {gap_start:.1f}s - {gap_end:.1f}s, re-transcribing...")
                                    
                                    # 部分音声を切り出して再認識
                                    y_full, sr_full = librosa.load(str(wav), sr=16000, mono=True)
                                    start_sample = int(gap_start * sr_full)
                                    end_sample = min(int(gap_end * sr_full), len(y_full))
                                    y_gap = y_full[start_sample:end_sample]
                                    
                                    # 一時ファイルに書き出し
                                    gap_wav = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                                    sf.write(gap_wav.name, y_gap, sr_full)
                                    gap_wav.close()
                                    
                                    try:
                                        # 既存modelの内部状態汚染を回避するため、
                                        # 小型の別インスタンスで再認識
                                        from faster_whisper import WhisperModel as _GapWM
                                        _gap_model = _GapWM("small", device="cuda", compute_type="float16")
                                        gap_segs, gap_info = _gap_model.transcribe(
                                            gap_wav.name,
                                            language="ja",
                                            word_timestamps=True,
                                            condition_on_previous_text=False,
                                            no_speech_threshold=0.1,
                                            vad_filter=False,
                                            beam_size=5,
                                            temperature=[0.0, 0.2, 0.4],
                                        )
                                        
                                        gap_results = []
                                        gap_seg_count = 0
                                        for gs in gap_segs:
                                            gt = gs.text.strip()
                                            gap_seg_count += 1
                                            is_gap_halluc = _is_hallucination(gt) if gt else True
                                            # cp932ログ化け防止: ファイルにUTF-8で書く
                                            try:
                                                gap_debug_path = session_dir / "gap_debug.txt" if 'session_dir' in dir() else None
                                                if gap_debug_path:
                                                    with open(gap_debug_path, 'a', encoding='utf-8') as gf:
                                                        gf.write(f"gap[{gap_seg_count}]: [{gs.start:.1f}s-{gs.end:.1f}s] halluc={is_gap_halluc} '{gt}'\n")
                                            except Exception:
                                                pass
                                            try:
                                                print(f"[{sid}] [WHISPER] Gap raw seg: [{gs.start:.1f}s-{gs.end:.1f}s] halluc={is_gap_halluc} len={len(gt)}")
                                            except Exception:
                                                print(f"[{sid}] [WHISPER] Gap raw seg: [{gs.start:.1f}s-{gs.end:.1f}s] halluc={is_gap_halluc} (text unprintable)")
                                            if not gt or is_gap_halluc:
                                                continue
                                            # 時刻をオリジナル音声の時刻に補正
                                            gap_words = []
                                            if gs.words:
                                                for gw in gs.words:
                                                    gap_words.append({
                                                        'start': gw.start + gap_start,
                                                        'end': gw.end + gap_start,
                                                        'word': gw.word,
                                                    })
                                            gap_seg_dict = {
                                                'id': -1,
                                                'start': gs.start + gap_start,
                                                'end': gs.end + gap_start,
                                                'text': gt,
                                                'words': gap_words if gap_words else None,
                                            }
                                            gap_results.append(gap_seg_dict)
                                        
                                        if gap_results:
                                            # ギャップセグメントを先頭に挿入
                                            for gr in gap_results:
                                                print(f"[{sid}] [WHISPER] Gap recovery: '{gr['text'][:50]}' at {gr['start']:.1f}s")
                                            segments = gap_results + segments
                                            print(f"[{sid}] [WHISPER] Recovered {len(gap_results)} segments from gap")
                                        else:
                                            print(f"[{sid}] [WHISPER] Gap re-transcription: no valid segments found (raw={gap_seg_count})")
                                    finally:
                                        import os
                                        os.unlink(gap_wav.name)
                                        # ギャップモデルのVRAM解放
                                        try:
                                            del _gap_model
                                            import torch
                                            if torch.cuda.is_available():
                                                torch.cuda.empty_cache()
                                        except Exception:
                                            pass
                                        
                            except Exception as gap_err:
                                print(f"[{sid}] [WHISPER] Gap recovery failed (non-fatal): {gap_err}")
                            
                            perf_log.append(f"[DEBUG] Whisper segments: {len(segments)}")
                            perf_log.append(f"[DEBUG] First segment: {segments[0].get('text','')[:80]}" if segments else "[DEBUG] No segments")
                            return {'segments': segments, 'text': ''.join(s.get('text','') for s in segments)}
                        except Exception as e:
                            print(f"[{sid}] [WHISPER] [ERROR] faster-whisper error: {type(e).__name__}: {e}")
                            import traceback
                            traceback.print_exc()
                            return {'segments': [], 'text': ''}
                        finally:
                            # Whisper完了後にVRAM解放
                            gc.collect()
                            import torch as _tc
                            if _tc.cuda.is_available():
                                _tc.cuda.empty_cache()
                                print(f"[{sid}] [WHISPER] VRAM cache cleared")
                    else:
                        # openai-whisper API
                        import torch as _torch
                        opts = dict(
                            language="ja",
                            word_timestamps=True,
                            initial_prompt="歌",
                            condition_on_previous_text=False,
                            no_speech_threshold=0.4,
                            fp16=_torch.cuda.is_available(),
                        )
                        try:
                            return model.transcribe(str(wav), **opts)
                        except RuntimeError as e:
                            print(f"[{sid}] [WHISPER] [WARN] RuntimeError: {e}, retrying...")
                            if _torch.cuda.is_available():
                                _torch.cuda.empty_cache()
                            return model.transcribe(str(wav), **opts)
                        finally:
                            # openai-whisper完了後にVRAM解放
                            gc.collect()
                            if _torch.cuda.is_available():
                                _torch.cuda.empty_cache()
                                print(f"[{sid}] [WHISPER] VRAM cache cleared")
            
            futures['whisper_res'] = executor.submit(_whisper_with_lock, whisper_model, wav_path, session_id) if whisper_model else None
            
            # --- 完了順に結果を回収（as_completed）---
            # 先に終わったタスクから順に進捗更新される
            act = None
            key_vec = None
            whisper_res = None
            hps_result = {}
            
            # future -> (step_name, label) のマッピング
            future_to_step = {}
            if futures.get('act'):
                future_to_step[futures['act']] = 'act'
            if futures.get('key_vec'):
                future_to_step[futures['key_vec']] = 'key_vec'
            if futures.get('whisper_res'):
                future_to_step[futures['whisper_res']] = 'whisper_res'
            if futures.get('chroma_chords'):
                future_to_step[futures['chroma_chords']] = 'chroma_chords'
            
            # スキップされたタスクのログ
            if not futures.get('act'):
                perf_log.append(f"[SKIP] Beats: beat_processor not available")
            if not futures.get('key_vec'):
                perf_log.append(f"[SKIP] Key: key_processor not available")
            if not futures.get('whisper_res'):
                perf_log.append(f"[SKIP] Whisper: whisper_model not available")
            
            # === Demucs htdemucs (4ステム) をバックグラウンドで起動 ===
            # HMM Viterbiクロマ検証でother.wavを使うため、初回解析でも実行
            # Notes (basic-pitch) は引き続きTABビュー時にオンデマンド
            import torch
            _has_gpu = torch.cuda.is_available()
            note_events = []
            guitar_wav_override = session_data.get("guitar_wav_path")
            is_deep_analysis = session_data.get("is_deep_analysis", False)
            
            def _run_demucs_htdemucs(wav_p, out_dir, sid):
                """Demucs htdemucs (4ステム) を実行してother.wavを生成"""
                import subprocess, sys, os
                out = Path(out_dir)
                # キャッシュチェック
                htdemucs_dir = out / "htdemucs"
                if htdemucs_dir.exists():
                    for d in htdemucs_dir.iterdir():
                        if d.is_dir() and (d / "other.wav").exists():
                            print(f"[{sid}] [DEMUCS] Using cached htdemucs: {d / 'other.wav'}")
                            return str(d / "other.wav")
                
                # GPU排他ロック（Whisper完了後に実行）
                print(f"[{sid}] [DEMUCS] Waiting for GPU lock...")
                with _gpu_lock:
                    print(f"[{sid}] [DEMUCS] GPU lock acquired, running htdemucs (4-stem)...")
                    try:
                        cmd = [
                            sys.executable, "-m", "demucs.separate",
                            "-o", str(out),
                            "-n", "htdemucs",
                            str(wav_p)
                        ]
                        result = subprocess.run(
                            cmd, check=True, capture_output=True, text=True,
                            env={"PYTHONIOENCODING": "utf-8", **os.environ}
                        )
                        # other.wav を探す
                        if htdemucs_dir.exists():
                            for d in htdemucs_dir.iterdir():
                                if d.is_dir() and (d / "other.wav").exists():
                                    print(f"[{sid}] [DEMUCS] [OK] other.wav: {d / 'other.wav'}")
                                    return str(d / "other.wav")
                        print(f"[{sid}] [DEMUCS] [WARN] htdemucs succeeded but other.wav not found")
                        return None
                    except Exception as e:
                        print(f"[{sid}] [DEMUCS] [ERR] htdemucs failed: {e}")
                        return None
                    finally:
                        # Demucs完了後にVRAM解放
                        gc.collect()
                        import torch as _td
                        if _td.cuda.is_available():
                            _td.cuda.empty_cache()
                            print(f"[{sid}] [DEMUCS] VRAM cache cleared")
            
            # Demucsは全並列タスク完了後に直列実行（HMM検証前）
            # GPU lockの競合を避けるため
            futures['demucs'] = None
            
            if is_deep_analysis and transcribe_notes:
                # Deep Analysis時のみノート検出即時実行
                if guitar_wav_override and Path(guitar_wav_override).exists():
                    print(f"[{session_id}] [PIPELINE] Deep Analysis: using pre-separated guitar")
                    futures['note_events'] = executor.submit(
                        transcribe_notes, str(wav_path),
                        guitar_wav_path=guitar_wav_override,
                        use_demucs=False, solo_guitar_mode=True, use_basic_pitch=True
                    )
                else:
                    futures['note_events'] = executor.submit(
                        transcribe_notes, str(wav_path),
                        use_demucs=_has_gpu, solo_guitar_mode=True, use_basic_pitch=True
                    )
            else:
                futures['note_events'] = None
                print(f"[{session_id}] [PIPELINE] Skipping notes (will run on-demand when TAB view requested)")
                perf_log.append(f"[SKIP] Notes: deferred to on-demand")
            
            for completed_future in concurrent.futures.as_completed(future_to_step.keys()):
                step_name = future_to_step[completed_future]
                
                if step_name == 'act':
                    try:
                        act = completed_future.result()
                        t_beats = time.time() - start_total
                        # act is now beat_times (1D array) from _fast_beat_detect
                        n_beats = len(act) if act is not None else 0
                        perf_log.append(f"[OK] Beats (librosa): {t_beats:.1f}s ({n_beats} beats)")
                        print(f"[{session_id}] [PERF] Beats done (librosa): {t_beats:.1f}s, {n_beats} beats")
                        _update_step(session_data, "beats", f"[OK] ビート検出 ({t_beats:.0f}s)")
                    except Exception as e:
                        perf_log.append(f"[FAIL] Beats: {type(e).__name__}: {e}")
                        print(f"[{session_id}] [ERROR] Beats failed: {e}")
                
                elif step_name == 'key_vec':
                    try:
                        key_vec = completed_future.result()
                        t_key = time.time() - start_total
                        perf_log.append(f"[OK] Key: {t_key:.1f}s (vec_len={len(key_vec) if key_vec is not None else 0})")
                        print(f"[{session_id}] [PERF] Key done: {t_key:.1f}s")
                        _update_step(session_data, "key", f"[OK] キー検出 ({t_key:.0f}s)")
                    except Exception as e:
                        perf_log.append(f"[FAIL] Key: {type(e).__name__}: {e}")
                        print(f"[{session_id}] [ERROR] Key failed: {e}")
                
                elif step_name == 'whisper_res':
                    try:
                        whisper_res = completed_future.result()
                        
                        # 日本語歌詞の後処理（誤認識修正・ハルシネーション除去）
                        from lyrics_postprocess import postprocess_whisper_segments
                        if whisper_res and whisper_res.get('segments'):
                            original_count = len(whisper_res['segments'])
                            whisper_res['segments'] = postprocess_whisper_segments(whisper_res['segments'])
                            # テキスト全体も再構築
                            whisper_res['text'] = ''.join(s['text'] for s in whisper_res['segments'])
                            post_count = len(whisper_res['segments'])
                            if original_count != post_count:
                                print(f"[{session_id}] [LYRICS] Post-process: {original_count} -> {post_count} segments")
                        
                        # === Whisper ハルシネーション検出（セグメント個別除去方式） ===
                        if whisper_res and whisper_res.get('segments'):
                            hallucination_markers = [
                                "歌詞を正確に書き起こしてください",
                                "ポップス、ロック、バラード",
                                "日本語の歌詞",
                            ]
                            
                            # マーカーを含むセグメントだけを除去（全体は削除しない）
                            clean_segments = []
                            removed_count = 0
                            for seg in whisper_res['segments']:
                                seg_text = seg.get('text', '')
                                is_hallu_seg = False
                                for marker in hallucination_markers:
                                    if marker in seg_text:
                                        is_hallu_seg = True
                                        print(f"[{session_id}] [LYRICS] [WARN] Removing hallucinated segment: '{seg_text[:50]}'")
                                        break
                                if not is_hallu_seg:
                                    clean_segments.append(seg)
                                else:
                                    removed_count += 1
                            
                            if removed_count > 0:
                                print(f"[{session_id}] [LYRICS] Removed {removed_count} hallucinated segments, {len(clean_segments)} remaining")
                                whisper_res['segments'] = clean_segments
                                whisper_res['text'] = ''.join(s['text'] for s in clean_segments)
                            
                            # 除去後にセグメントが全てなくなった場合のみNone化
                            if not clean_segments or not whisper_res['text'].strip():
                                print(f"[{session_id}] [LYRICS] [SKIP] All segments were hallucinations -- no lyrics")
                                whisper_res = None
                        
                        t_whisper = time.time() - start_total
                        n_segments = len(whisper_res.get('segments', [])) if whisper_res else 0
                        text_preview = whisper_res.get('text', '')[:100] if whisper_res else '(hallucination filtered)'
                        perf_log.append(f"[OK] Whisper: {t_whisper:.1f}s ({n_segments} segments)")
                        perf_log.append(f"     Whisper text: {text_preview}...")
                        print(f"[{session_id}] [PERF] Whisper done: {t_whisper:.1f}s ({n_segments} segments)")
                        _update_step(session_data, "whisper", f"[OK] 歌詞検出 ({t_whisper:.0f}s)")
                    except Exception as e:
                        perf_log.append(f"[FAIL] Whisper: {type(e).__name__}: {e}")
                        print(f"[{session_id}] [ERROR] Whisper failed: {e}")
                        import traceback
                        traceback.print_exc()
                
                elif step_name == 'chroma_chords':
                    try:
                        hps_result = completed_future.result()
                    except Exception as e:
                        perf_log.append(f"[FAIL] Chroma+Chord: {type(e).__name__}: {e}")
                        print(f"[{session_id}] [ERROR] Chroma+Chord failed: {e}")
                    
                    if hps_result:
                        t_chords = time.time() - start_total
                        _lbl = hps_result.get('seg_labels')
                        n_chords = len(_lbl) if _lbl is not None else 0
                        perf_log.append(f"[OK] Chroma+Chord: {t_chords:.1f}s ({n_chords} chord segments)")
                        print(f"[{session_id}] [PERF] Chroma+Chord done: {t_chords:.1f}s")
                        _update_step(session_data, "chords", f"[OK] コード解析 ({t_chords:.0f}s)")
            
            # Notes回収（Deep Analysis時のみ）
            if futures.get('note_events'):
                try:
                    note_events = futures['note_events'].result()
                    t_notes = time.time() - start_total
                    perf_log.append(f"[OK] Notes: {t_notes:.1f}s ({len(note_events)} notes)")
                    print(f"[{session_id}] [PERF] Notes done: {t_notes:.1f}s ({len(note_events)} notes)")
                except Exception as e:
                    perf_log.append(f"[FAIL] Notes: {type(e).__name__}: {e}")
                    print(f"[{session_id}] [ERROR] Notes failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Demucs回収（HMMクロマ検証用のother.wav）
            demucs_other_wav = None
            if futures.get('demucs'):
                try:
                    demucs_other_wav = futures['demucs'].result()
                    t_demucs = time.time() - start_total
                    if demucs_other_wav:
                        perf_log.append(f"[OK] Demucs: {t_demucs:.1f}s (other.wav ready)")
                        print(f"[{session_id}] [PERF] Demucs done: {t_demucs:.1f}s")
                    else:
                        perf_log.append(f"[WARN] Demucs: {t_demucs:.1f}s (no output)")
                except Exception as e:
                    perf_log.append(f"[FAIL] Demucs: {type(e).__name__}: {e}")
                    print(f"[{session_id}] [ERROR] Demucs failed: {e}")
            
            # === Tuning estimation from detected notes ===
            if note_events:
                try:
                    from tuning_estimator import estimate_tuning
                    estimated_tuning = estimate_tuning(note_events)
                    session_data['estimated_tuning'] = estimated_tuning
                    print(f'[{session_id}] Estimated tuning: {estimated_tuning}')
                    perf_log.append(f"Estimated tuning: {estimated_tuning}")
                except Exception as e:
                    print(f'[{session_id}] [WARN] Tuning estimation failed: {e}')
                    session_data['estimated_tuning'] = 'standard'
                    perf_log.append(f"Tuning estimation failed: {e}, defaulting to standard")

            # === Whisper補完: 2回目・3回目のWhisper実行は廃止 ===
            # 以前はvocals.wavと冒頭35秒で追加実行していたが、
            # 処理時間が大幅に増加する割に改善が限定的なためスキップ。
            # フルミックス1回のWhisper baseモデルで十分な精度が得られる。

        t_parallel = time.time() - start_total
        perf_log.append(f"")
        perf_log.append(f"Total parallel: {t_parallel:.1f}s")
        print(f"[{session_id}] [PERF] All parallel tasks done: {t_parallel:.1f}s")

        # === 楽曲タイプ自動判定 ===
        # Demucs 分離完了後、4ステムのエネルギー比で判定
        song_type = detect_song_type(session_dir, wav_path)
        is_solo_guitar = (song_type == "solo_guitar")
        session_data["song_type"] = song_type
        perf_log.append(f"Song type: {song_type} (solo_guitar={is_solo_guitar})")
        
        # ソロギターの場合、Whisperの歌詞は不要（ハルシネーション防止）
        if is_solo_guitar and whisper_res:
            print(f"[{session_id}] [LYRICS] [GUITAR] Solo guitar detected -- discarding Whisper lyrics")
            whisper_res = None

        # === Post-Processing (結果の統合) ===
        session_data["progress"] = f"解析中... (4/5) [BUILD] 譜面を生成中..."
        save_session(session_id)
        # 1. Beats
        # act is now beat_times (1D array) from _fast_beat_detect (librosa)
        # No need for beat_tracker(act) - beat_times are already computed
        if act is not None and len(act) > 0:
            beats_raw = act  # Already beat_times from _fast_beat_detect
            print(f"[{session_id}] [BEATS] Using librosa beat_times directly: {len(beats_raw)} beats")
        else:
            print(f"[{session_id}] [WARN] _fast_beat_detect returned empty, using inline librosa fallback")
            y_beat, sr_beat = librosa.load(str(wav_path), sr=22050)
            tempo, beat_frames = librosa.beat.beat_track(y=y_beat, sr=sr_beat)
            beats_raw = librosa.frames_to_time(beat_frames, sr=sr_beat)
        v_time = np.sort(np.array(beats_raw).astype(float))
        
        # 最初のビート位置を保存（フロントエンドのカーソル同期用）
        first_beat_time = float(v_time[0]) if len(v_time) > 0 else 0.0
        session_data["first_beat_time"] = first_beat_time
        session_data["beat_times"] = [float(t) for t in v_time]  # 全ビートタイムスタンプ
        print(f"[{session_id}] [SYNC] First beat at {first_beat_time:.3f}s, {len(v_time)} beats total")
        
        # HPS + Chroma + Chord 結果を展開
        sections = hps_result.get('sections', [])
        seg_starts = hps_result.get('seg_starts')
        seg_labels = hps_result.get('seg_labels')
        
        session_data["progress"] = "コードを判別中..."
        save_session(session_id)
        
        if seg_starts is None or seg_labels is None:
            print(f"[{session_id}] [WARN] chord_processor unavailable, using N.C. placeholders")
            seg_starts = v_time if len(v_time) > 0 else np.array([0.0])
            seg_labels = np.array(['N.C.'] * len(seg_starts))

        # 2. Key (deferred - madmom key_processor runs only if chroma/chord disagree)
        # key_vec is None here due to optimization 2; key is set during consensus below
        if key_vec is not None:
            idx = int(key_vec.argmax())
            KEYS = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'G#', 'A', 'Bb', 'B']
            root = KEYS[idx % 12]
            mode = "major" if (len(key_vec) == 12 or idx < 12) else "minor"
            session_data["key"] = f"{root} {mode}"
            
        # 3. Whisper (Lyrics) -- BPM倍取り補正後に配置する（後述）
        # ※ 歌詞マッピングはBPM倍取り補正でv_timeが変わった後に実行する必要がある
        lyrics_data = []

        # 4. Chords (Dense Mapping with Beat Majority Voting)
        structured = []
        bpm = 120.0
        if len(v_time) > 1:
            intervals = np.diff(v_time)
            avg_interval = np.mean(intervals)
            if avg_interval > 0:
                bpm = 60.0 / avg_interval
        
        # === BPM 倍取り補正 ===
        raw_bpm = bpm
        if bpm > 200 and len(v_time) > 4:
            half_bpm = bpm / 2
            half_beats = v_time[::2]
            half_intervals = np.diff(half_beats)
            cv_half = np.std(half_intervals) / np.mean(half_intervals) if np.mean(half_intervals) > 0 else 999
            cv_full = np.std(intervals) / np.mean(intervals) if np.mean(intervals) > 0 else 999
            
            if cv_half < 0.25 and 60 <= half_bpm <= 160 and cv_half <= cv_full * 1.5:
                print(f"[{session_id}] [BPM] Half-tempo correction: {raw_bpm:.1f} -> {half_bpm:.1f} BPM (CV: full={cv_full:.3f}, half={cv_half:.3f})")
                bpm = half_bpm
                v_time = np.array(half_beats)
                perf_log.append(f"BPM correction: {raw_bpm:.1f} -> {half_bpm:.1f} (half-tempo, beats: {len(v_time)})")
            else:
                print(f"[{session_id}] [BPM] No half-tempo correction needed: {raw_bpm:.1f} BPM (CV: full={cv_full:.3f}, half={cv_half:.3f})")
        else:
            if bpm > 160:
                print(f"[{session_id}] [BPM] Tempo {raw_bpm:.1f} BPM is in fingerpicking range (160-200), no correction applied")
        
        session_data["bpm"] = round(bpm, 1)
        if "key" not in session_data:
            session_data["key"] = "C major"

        # ============================================================
        # === Music21 コード再スコアリング ===
        # ⚠️ 無効化: このブロックはキー確定 (line ~1447) より前に実行されるため
        #    madmom の誤ったキー (例: Eb major) を使ってしまう。
        #    正しいキー確定後に Music21 を適用すべき。
        #    → ChordVerifier (line ~1480) が同等の役割を果たしている。
        # ============================================================
        perf_log.append("[Music21] Re-scoring skipped (runs after key consensus now)")


        # 拍子を推定（ビート配列 + onset strengthアクセントパターンから）

        time_sig = _estimate_time_signature(v_time, bpm, wav_path=wav_path)
        session_data["time_signature"] = time_sig
        print(f"[{session_id}] [TIME_SIG] Estimated: {time_sig}")
        perf_log.append(f"Time signature: {time_sig}")
        try:
            beats_per_bar = int(time_sig.split('/')[0])
        except Exception:
            beats_per_bar = 4

        # === Bar positions (downbeats) from actual beat times ===
        # Every beats_per_bar-th beat is a downbeat (bar start).
        # This provides precise bar boundaries for the frontend's 4-bar line splitting.
        beat_times_list = [float(t) for t in v_time]
        bar_positions = [float(v_time[i]) for i in range(0, len(v_time), beats_per_bar)]
        # Also compute downbeats (= bar_positions) and all beats
        downbeats = list(bar_positions)  # alias for clarity
        
        # Store in session for the result endpoint
        session_data["bar_positions"] = bar_positions
        session_data["downbeats"] = downbeats
        
        n_bars = len(bar_positions)
        print(f"[{session_id}] [BARS] {n_bars} bars from {len(v_time)} beats "
              f"({beats_per_bar} beats/bar), "
              f"first bar at {bar_positions[0]:.3f}s" if bar_positions else "no bars")
        perf_log.append(f"Bar positions: {n_bars} bars from {len(v_time)} beats")

        # 3. Whisper (Lyrics) -- 単語レベルで拍/小節に配置
        # ★ BPM倍取り補正後のv_timeを使って正しいbar/beatを計算する
        if whisper_res:
            segments = whisper_res.get('segments', [])
            perf_log.append(f"")
            perf_log.append(f"--- Lyrics mapping ---")
            perf_log.append(f"Whisper segments: {len(segments)}")

            # 単語レベルのタイムスタンプを抽出（高精度ビートスナップ）
            word_count = 0
            v_time_arr = np.array(v_time) if not isinstance(v_time, np.ndarray) else v_time
            beat_dur = np.median(np.diff(v_time_arr)) if len(v_time_arr) > 1 else 0.5
            
            # ★ 歌手の先行発声バイアス: ビートの少し前(~80ms)に歌い始めることが多い
            ANTICIPATION_MS = 0.08  # 80ms前方スナップバイアス
            
            # ★ 占有済みビートを追跡して同じビートに複数歌詞が重ならないようにする
            occupied_beats = set()  # (bar, beat) のセット
            
            for seg in segments:
                words = seg.get('words', [])
                if words:
                    for w in words:
                        t = w['start'] + ANTICIPATION_MS  # 先行発声補正
                        text = w.get('word', '').strip()
                        if not text:
                            continue
                        if len(v_time_arr) > 0:
                            # 最も近いビートにスナップ
                            idx = int(np.searchsorted(v_time_arr, t))
                            if idx >= len(v_time_arr):
                                beat_idx = len(v_time_arr) - 1
                            elif idx == 0:
                                beat_idx = 0
                            else:
                                # 前後のビートで近い方を選択
                                d_next = abs(v_time_arr[idx] - t)
                                d_prev = abs(v_time_arr[idx - 1] - t)
                                # ★ 次のビートが近い場合を優先（先行発声対応）
                                if d_next < d_prev * 1.2:  # 20%のバイアス
                                    beat_idx = idx
                                else:
                                    beat_idx = idx - 1
                            
                            bar = beat_idx // beats_per_bar
                            beat = beat_idx % beats_per_bar
                            
                            # ★ 同じ(bar, beat)に既に歌詞がある場合、次の空きビートに移動
                            while (bar, beat) in occupied_beats:
                                beat += 1
                                if beat >= beats_per_bar:
                                    beat = 0
                                    bar += 1
                                # 無限ループ防止
                                if bar * beats_per_bar + beat > len(v_time_arr) + 10:
                                    break
                            
                            occupied_beats.add((bar, beat))
                        else:
                            bar = 0
                            beat = 0
                        lyrics_data.append((bar, beat, round(w['start'], 3), round(w['end'], 3), text))
                        word_count += 1
                else:
                    t = seg['start'] + ANTICIPATION_MS
                    if len(v_time_arr) > 0:
                        idx = int(np.searchsorted(v_time_arr, t))
                        if idx >= len(v_time_arr):
                            beat_idx = len(v_time_arr) - 1
                        elif idx == 0:
                            beat_idx = 0
                        else:
                            d_next = abs(v_time_arr[idx] - t)
                            d_prev = abs(v_time_arr[idx - 1] - t)
                            if d_next < d_prev * 1.2:
                                beat_idx = idx
                            else:
                                beat_idx = idx - 1
                        bar = beat_idx // beats_per_bar
                        beat = beat_idx % beats_per_bar
                        while (bar, beat) in occupied_beats:
                            beat += 1
                            if beat >= beats_per_bar:
                                beat = 0
                                bar += 1
                            if bar * beats_per_bar + beat > len(v_time_arr) + 10:
                                break
                        occupied_beats.add((bar, beat))
                    else:
                        bar = 0
                        beat = 0
                    lyrics_data.append((bar, beat, round(seg['start'], 3), round(seg['end'], 3), seg['text'].strip()))
            
            perf_log.append(f"Lyrics mapped: {len(lyrics_data)} entries (words={word_count})")
            if lyrics_data:
                perf_log.append(f"First lyric: bar={lyrics_data[0][0]} beat={lyrics_data[0][1]} [{lyrics_data[0][4]}]")
        else:
            perf_log.append(f"")
            perf_log.append(f"--- Lyrics mapping ---")
            perf_log.append(f"[WARN] whisper_res is None -- no lyrics detected")

        if seg_starts is not None and len(v_time) > 0:
            # Step 1: セグメントの平滑化（短いセグメントをマージ）
            seg_starts, seg_labels = _smooth_chord_segments(
                seg_starts, seg_labels, min_duration=0.4
            )
            
            # Step 2: ビートごとに多数決でコードを決定
            beat_chords = _beat_majority_chords(v_time, seg_starts, seg_labels)
            
            n_unique_raw = len(set(beat_chords) - {"N.C."})
            perf_log.append(f"Beat chords (raw from detection): {n_unique_raw} unique")
            
            # デバッグ: 生のコード一覧（最初の40ビート）
            preview_raw = beat_chords[:40]
            print(f"[{session_id}] [CHORD] Raw detected (first 40): {preview_raw}")
            
            for i, b_time in enumerate(v_time):
                bar = i // beats_per_bar
                beat_in_bar = i % beats_per_bar
                
                next_b_time = v_time[i+1] if i < len(v_time) - 1 else b_time + 60.0 / bpm
                
                clean_chord = beat_chords[i]
                
                # 歌詞のマッピング
                matching_lyrics = []
                lyric_duration = 0.0
                for lyr in lyrics_data:
                    if lyr[0] == bar and lyr[1] == beat_in_bar:
                        matching_lyrics.append(lyr[4])
                        lyric_duration += (lyr[3] - lyr[2])
                
                # セグメントのマッピング
                section_label = ""
                for s_start, s_end, s_lbl in sections:
                    if s_start <= b_time < s_end:
                        section_label = s_lbl
                        break

                structured.append({
                    "bar": bar + 1, "beat": beat_in_bar + 1, "time": round(b_time, 3),
                    "duration": round(next_b_time - b_time, 3),
                    "chord": clean_chord or "N.C.",
                    "lyric": " ".join(matching_lyrics),
                    "lyric_duration": round(lyric_duration, 3),
                    "section": section_label
                })
        
        # --- Phase 0-2: ビート同期コード遷移スナップ ---
        # コード遷移タイミングをビート位置にスナップ (100ms以内)
        if v_time is not None and len(v_time) > 0:
            snap_count = 0
            v_time_arr = np.array(v_time)
            for entry in structured:
                idx = np.argmin(np.abs(v_time_arr - entry["time"]))
                nearest_beat = float(v_time_arr[idx])
                if abs(nearest_beat - entry["time"]) < 0.1:  # 100ms以内
                    old_time = entry["time"]
                    entry["time"] = round(nearest_beat, 3)
                    entry["duration"] = round(entry["duration"] + (old_time - nearest_beat), 3)
                    snap_count += 1
            if snap_count > 0:
                print(f"[{session_id}] [SNAP] Snapped {snap_count}/{len(structured)} chords to beat positions")
        
        # --- Write beats.txt, beats.json and chords.csv for /result endpoint ---
        beats_txt_path = session_dir / "beats.txt"
        np.savetxt(beats_txt_path, v_time, fmt="%.6f")
        
        # beats.json: ビート情報 + 拍子をJSON形式で保存
        beats_json_path = session_dir / "beats.json"
        v_time_list = [float(t) for t in v_time] if not isinstance(v_time, list) else v_time
        with open(beats_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "beats": v_time_list,
                "bpm": round(bpm, 1),
                "time_signature": session_data.get("time_signature", "4/4"),
                "beats_per_bar": beats_per_bar,
                "beat_count": len(v_time_list),
            }, f, indent=2)
        
        chords_csv_path = session_dir / "chords.csv"
        with chords_csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bar", "beat", "start", "end", "chords", "clean_chord"])
            for r in structured:
                w.writerow([r['bar'], r['beat'], r['time'], r['time']+r['duration'], r['chord'], r['chord']])
        
        # --- Write lyrics_split.csv ---
        lyrics_csv_path = session_dir / "lyrics_split.csv"
        with lyrics_csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bar", "beat", "start", "end", "lyrics"])
            for lyr in lyrics_data:
                w.writerow([lyr[0]+1, lyr[1]+1, lyr[2], lyr[3], lyr[4]])
        # Whisperのフレーズ単位セグメントを保存（ワードタイムスタンプ付き）
        lyrics_phrases = []
        if whisper_res:
            for seg in whisper_res.get('segments', []):
                text = seg.get('text', '').strip()
                if text:
                    phrase = {
                        "start": round(seg['start'], 3),
                        "end": round(seg['end'], 3),
                        "text": text
                    }
                    # ワードレベルタイムスタンプ（コード-歌詞位置の精密照合用）
                    if seg.get('words'):
                        phrase["words"] = [
                            {"start": round(w['start'], 3), "end": round(w['end'], 3), "word": w['word']}
                            for w in seg['words']
                        ]
                    lyrics_phrases.append(phrase)

        # Janome形態素解析で自然な日本語の分割を行った表示用フレーズを生成
        display_phrases = lyrics_phrases
        try:
            from phrase_processor import process_phrases_for_display
            from lyrics_postprocess import clean_hallucinated_endings
            # ハルシネーション除去 -> フレーズ分割
            cleaned_phrases = clean_hallucinated_endings(lyrics_phrases)
            display_phrases = process_phrases_for_display(
                cleaned_phrases, target_chars=30,
                bar_positions=bar_positions
            )
            perf_log.append(f"Display phrases: {len(display_phrases)} (from {len(lyrics_phrases)} raw, {len(cleaned_phrases)} after cleanup, bars={'yes' if bar_positions else 'no'})")
            # bar分割後のフレーズにも再度ハルシネーション除去
            display_phrases = clean_hallucinated_endings(display_phrases)
        except Exception as e:
            perf_log.append(f"Warning: phrase_processor failed: {e}, using raw phrases")

        # --- ChordPro形式テキストを生成 ---
        chordpro_text = ""
        try:
            from chordpro_converter import structured_to_chordpro
            song_title = session_data.get("title", "")
            song_artist = session_data.get("artist", "")
            song_key = sessions[session_id].get("key", "")
            chordpro_text = structured_to_chordpro(
                structured, lyrics_phrases=lyrics_phrases,
                display_phrases=display_phrases,
                title=song_title, artist=song_artist, key=song_key,
                beats_per_bar=beats_per_bar
            )
            perf_log.append(f"ChordPro text: {len(chordpro_text)} chars, {chordpro_text.count(chr(10))} lines")
        except Exception as e:
            perf_log.append(f"Warning: ChordPro conversion failed: {e}")
            import traceback; traceback.print_exc()

        session_data["result"] = {
            "session_id": session_id,
            "key": sessions[session_id].get("key", "Unknown"),
            "structured_data": structured,
            "lyrics_phrases": lyrics_phrases,
            "display_phrases": display_phrases,
            "chordpro_text": chordpro_text,
            "estimated_tuning": session_data.get("estimated_tuning", "standard"),
            "beat_times": beat_times_list,
            "downbeats": downbeats,
            "bar_positions": bar_positions,
            "beats_per_bar": beats_per_bar,
        }
        
        # --- Post-processing summary ---
        lyrics_in_structured = sum(1 for s in structured if s.get('lyric'))
        perf_log.append(f"")
        perf_log.append(f"--- Post-processing summary ---")
        perf_log.append(f"Beats: {len(v_time)}")
        perf_log.append(f"Key: {session_data.get('key', 'Unknown')}")
        perf_log.append(f"BPM: {session_data.get('bpm', '?')}")
        perf_log.append(f"Structured entries: {len(structured)}")
        perf_log.append(f"Lyrics in structured: {lyrics_in_structured}/{len(structured)}")
        perf_log.append(f"Note events: {len(note_events)}")
        perf_log.append(f"Sections: {len(sections)}")

        # 4.5 キー推定（Optimization 2: chroma+chord一致時はmadmomスキップ）
        if structured:
            # (1) 音声chromaベースのキー推定（最も信頼できる）
            chroma_key = estimate_key_from_audio(str(wav_path))
            
            # (2) コード進行からのキー推定
            chord_key = estimate_key_from_chords_fn(structured)
            
            # Optimization 2: chroma と chord が一致する場合、madmom key_processor をスキップ
            # 相対長短調（例: C major ≈ A minor）も一致とみなす
            madmom_key = session_data.get("key", "C major")  # default or previously set
            _chroma_chord_agree = False
            try:
                from chord_processing import _key_to_semi, _key_mode, _keys_near
                _cc_semi_c = _key_to_semi(chroma_key)
                _cc_semi_d = _key_to_semi(chord_key)
                _cc_mode_c = _key_mode(chroma_key)
                _cc_mode_d = _key_mode(chord_key)
                _chroma_chord_agree = _keys_near(_cc_semi_c, _cc_mode_c, _cc_semi_d, _cc_mode_d)
            except Exception as _e:
                print(f"[{session_id}] [KEY] Could not compare chroma/chord keys: {_e}")
                _chroma_chord_agree = (chroma_key == chord_key)
            
            if _chroma_chord_agree:
                # Chroma and chord agree → skip madmom (~30s saved)
                print(f"[{session_id}] [KEY] * chroma={chroma_key} ~= chord={chord_key} -> skipping madmom key_processor (~30s saved)")
                perf_log.append(f"[KEY] Skipped madmom: chroma={chroma_key} ~= chord={chord_key}")
                final_key = chroma_key
                method = "consensus-chroma+chord (madmom skipped)"
            else:
                # Chroma and chord disagree → run madmom as tiebreaker
                print(f"[{session_id}] [KEY] chroma={chroma_key} != chord={chord_key} -> running madmom key_processor as tiebreaker...")
                t_key_start = time.time()
                try:
                    if key_processor:
                        key_vec = key_processor(str(wav_path))
                        if key_vec is not None:
                            idx = int(key_vec.argmax())
                            KEYS = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'G#', 'A', 'Bb', 'B']
                            root = KEYS[idx % 12]
                            mode = "major" if (len(key_vec) == 12 or idx < 12) else "minor"
                            madmom_key = f"{root} {mode}"
                            print(f"[{session_id}] [KEY] madmom key_processor result: {madmom_key} ({time.time()-t_key_start:.1f}s)")
                        else:
                            print(f"[{session_id}] [KEY] madmom key_processor returned None")
                    else:
                        print(f"[{session_id}] [KEY] key_processor not available")
                except Exception as _ke:
                    print(f"[{session_id}] [KEY] madmom key_processor failed: {_ke}")
                t_key_elapsed = time.time() - t_key_start
                perf_log.append(f"[KEY] madmom fallback: {madmom_key} ({t_key_elapsed:.1f}s)")
                
                final_key, method = key_consensus(madmom_key, chroma_key, chord_key)
            
            # ログに推定結果を出力
            print(f"[{session_id}] Key estimates: madmom={madmom_key}, chroma={chroma_key}, chord={chord_key}")
            perf_log.append(f"Key estimates: madmom={madmom_key}, chroma={chroma_key}, chord={chord_key}")
            perf_log.append(f"Key selected: {final_key} ({method})")
            print(f"[{session_id}] Key selected: {final_key} ({method})")
            session_data["key"] = final_key
            
            # 推定キーで1回だけダイアトニック正規化
            raw_chords = [e["chord"] for e in structured]
            print(f"[{session_id}] [CHORD] Before normalize (first 40): {raw_chords[:40]}")
            
            normalized_chords = _normalize_chords_to_key(raw_chords, final_key)
            for i, entry in enumerate(structured):
                entry["chord"] = normalized_chords[i]
            
            n_unique_before = len(set(raw_chords) - {"N.C."})
            n_unique_after = len(set(normalized_chords) - {"N.C."})
            perf_log.append(f"Beat chords: {n_unique_before} raw -> {n_unique_after} after normalization (key={final_key})")
            print(f"[{session_id}] [CHORD] After normalize (first 40): {normalized_chords[:40]}")
            print(f"[{session_id}] Chord normalization: {n_unique_before} -> {n_unique_after} unique chords (key={final_key})")

            # 4.55 ★ クロマベースのコード検証
            # BTCの予測を音声クロマと照合し、スコアが低いビートを補正
            pre_verify_chords = [e["chord"] for e in structured]
            try:
                from chord_verifier import verify_and_correct_chords
                import time as _time
                t_verify = _time.time()
                verified_chords, verify_stats = verify_and_correct_chords(
                    pre_verify_chords,
                    v_time,
                    str(wav_path),
                    final_key,
                    correction_threshold=0.15,  # 0.25→0.15: 低スコアのみ補正対象
                    min_improvement=0.30,        # 0.15→0.30: 30%以上の改善がある場合のみ置換
                )
                # 補正をstructuredに反映
                for i, entry in enumerate(structured):
                    if i < len(verified_chords):
                        entry["chord"] = verified_chords[i]
                dt_verify = _time.time() - t_verify
                print(f"[{session_id}] [CHORD] Chroma verify: {verify_stats['corrections']} corrections, "
                      f"avg_score={verify_stats['avg_score']:.3f}, {dt_verify:.1f}s")
                perf_log.append(f"Chroma verify: {verify_stats['corrections']} corrections, "
                               f"avg_score={verify_stats['avg_score']:.3f}, {dt_verify:.1f}s")
            except Exception as e:
                print(f"[{session_id}] [CHORD] Chroma verify skipped: {e}")
                import traceback; traceback.print_exc()
                perf_log.append(f"Chroma verify: skipped ({e})")

            # 4.56 ★ ChatterFilter は廃止
            # BTC は正確に C G Am F を検出しており、フィルタで1拍コードを消すと
            # 「C G Am F C G Am F」が「C G Am F G F C G Am F」に崩れる。
            # → 何もしない（コードはそのまま維持）
            try:
                snap_corrections = 0
                changes_after_snap = sum(1 for i in range(1, len(structured))
                                         if structured[i]["chord"] != structured[i-1]["chord"])
                print(f"[{session_id}] [CHORD] ChatterFilter: disabled, changes -> {changes_after_snap}")
                perf_log.append(f"Bar-snap: 0 corrected, changes -> {changes_after_snap}")
            except Exception as e:
                pass




            # 4.56 HMM遷移確率補正 (現在無効: Beatlesベンチマークで-16.7%の回帰を確認)
            # 品質正規化でコード型情報が失われるため、改良が必要
            # TODO: コード名の完全保持版HMMを実装後に有効化
            # try:
            #     from chord_hmm import viterbi_chord_correction
            #     pre_hmm_chords = [e["chord"] for e in structured]
            #     hmm_chords = viterbi_chord_correction(pre_hmm_chords, final_key)
            #     hmm_corrections = sum(1 for a, b in zip(pre_hmm_chords, hmm_chords) if a != b)
            #     for i, entry in enumerate(structured):
            #         entry["chord"] = hmm_chords[i]
            #     n_hmm = len(set(hmm_chords) - {"N.C."})
            #     print(f"[{session_id}] [CHORD] After HMM: {n_hmm} unique, corrections={hmm_corrections}")
            #     perf_log.append(f"Chord HMM: {hmm_corrections} corrections")
            # except Exception as e:
            #     print(f"[{session_id}] [CHORD] HMM skipped: {e}")
            #     perf_log.append(f"Chord HMM: skipped ({e})")

        # 4.6 TABノート -- スコアビュー削除のため、初期パイプラインではスキップ
        # MusicXML/GP5は書き出し時にオンデマンド生成
        chord_strum_notes = []
        if is_solo_guitar:
            tab_source_notes = note_events if note_events else []
        else:
            if generate_chord_strum_notes:
                chord_strum_notes = generate_chord_strum_notes(structured, bpm=bpm)
            tab_source_notes = chord_strum_notes

        # Save notes.json (for later on-demand MusicXML/GP5 export)
        notes_json_path = session_dir / "notes.json"
        with open(notes_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "notes": note_events,
                "song_type": song_type,
                "tab_source": "detected_notes" if is_solo_guitar else "chord_strum",
                "tab_source_count": len(tab_source_notes),
            }, f, indent=2)

        perf_log.append(f"MusicXML: deferred (on-demand export)")
        session_data["has_notes"] = bool(note_events or chord_strum_notes)
        
        # 5. Build Chord Sheet
        sheet_lines = [f"# {session_id} - NextChord Sheet", f"Key: {session_data.get('key', 'Unknown')}\n"]
        all_bars = sorted(list(set([r['bar'] for r in structured])))
        for bar in all_bars:
            b_chords = [r for r in structured if r['bar'] == bar]
            b_lyrics = [l for l in lyrics_data if l[0] == bar]
            ch_str = " | ".join([c['chord'] for c in b_chords if c['chord'] != "N.C."])
            ly_str = "".join([l[4] for l in b_lyrics])
            if ch_str: sheet_lines.append(f"[{bar:03d}] {ch_str}")
            if ly_str: sheet_lines.append(f"      {ly_str}")
            sheet_lines.append("")
        session_data["chord_sheet"] = "\n".join(sheet_lines)
        
        t_total = time.time() - start_total
        perf_log.append(f"")
        perf_log.append(f"=== TOTAL PIPELINE TIME: {t_total:.1f}s ===")
        print(f"[{session_id}] ★ TOTAL PIPELINE TIME: {t_total:.1f}s")
        
        # PERFログをファイルに書き出し
        perf_path = session_dir / "perf.log"
        with open(perf_path, "w", encoding="utf-8") as f:
            f.write("\n".join(perf_log) + "\n")
        print(f"[{session_id}] ★ perf.log saved to {perf_path}")
        
        _update_step(session_data, "postprocess", f"[OK] 譜面生成 ({t_total:.0f}s)")
        
        # === MP3変換（ブラウザ再生用）===
        # WAV (44MB+) をそのままブラウザに送るとメモリ不足でクラッシュするため、
        # MP3 (~4MB) に変換してブラウザ再生用に提供する
        mp3_path = session_dir / "playback.mp3"
        if not mp3_path.exists():
            import subprocess, os
            ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
            try:
                subprocess.run(
                    [ffmpeg, "-y", "-i", str(wav_path), "-b:a", "192k", str(mp3_path)],
                    check=True, capture_output=True, timeout=60
                )
                print(f"[{session_id}] [MP3] Converted for browser playback: {mp3_path.stat().st_size // 1024}KB")
            except Exception as e:
                print(f"[{session_id}] [MP3] Conversion failed: {e} (browser will use WAV)")
        
        session_data["status"] = SessionStatus.COMPLETED
        session_data["progress"] = "完了"
        save_session(session_id)
        
    except Exception as e:
        print(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        sessions[session_id]["status"] = SessionStatus.FAILED
        sessions[session_id]["error"] = str(e)
        save_session(session_id)
        print(f"[{session_id}] Pipeline failed. Kept for user review.")
