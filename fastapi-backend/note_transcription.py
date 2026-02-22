"""
Note Transcription Module — Solo Guitar Optimized
===================================================
Demucs でギタートラックを分離後、強化版 librosa で音符検出する。
basic-pitch がインストールされている場合はそちらを優先使用。
ソロギターの繊細なフレーズを正確に捕捉するため、閾値とフィルタリングを最適化。

出力: List[NoteEvent]
  NoteEvent = {
      "start_time": float,   # 秒
      "end_time": float,      # 秒
      "midi_pitch": int,      # MIDI番号 (60=C4)
      "velocity": int,        # 0-127
      "confidence": float,    # 検出信頼度
      "note_name": str,       # "C4", "A#3" など
      "frequency": float      # Hz
  }
"""

import numpy as np
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# MIDI番号 → 音名変換テーブル
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# ギターの音域 (標準チューニング)
GUITAR_RANGE_MIN = 40   # E2 (6弦開放)
GUITAR_RANGE_MAX = 88   # E6 (1弦24フレット付近)


# =========================================================================
# Demucs 連携 — ギタートラック分離
# =========================================================================

def separate_guitar_track(wav_path: str, output_dir: str = None) -> str:
    """
    Demucs を使用してギタートラック（other.wav）を分離する。
    分離済みファイルが既に存在する場合はスキップ（キャッシュ）。
    
    Parameters
    ----------
    wav_path : str
        入力WAVファイルのパス
    output_dir : str, optional
        分離結果の出力先。指定しない場合はwav_pathと同じディレクトリ
    
    Returns
    -------
    str
        分離されたギタートラック（other.wav）のパス。
        分離に失敗した場合は元のwav_pathを返す。
    """
    wav_p = Path(wav_path)
    if output_dir is None:
        output_dir = str(wav_p.parent)
    out_dir = Path(output_dir)
    
    # Demucs の出力構造: output_dir/htdemucs/songname/{bass,drums,other,vocals}.wav
    song_name = wav_p.stem
    stems_dir = out_dir / "htdemucs" / song_name
    guitar_path = stems_dir / "other.wav"
    
    # キャッシュチェック: 分離済みファイルが存在すればスキップ
    if guitar_path.exists():
        print(f"[NoteTranscription/Demucs] Using cached guitar track: {guitar_path}")
        return str(guitar_path)
    
    # 空のキャッシュディレクトリがあれば削除（前回の失敗した分離の残骸）
    if stems_dir.exists() and not any(stems_dir.iterdir()):
        import shutil
        shutil.rmtree(stems_dir, ignore_errors=True)
        print(f"[NoteTranscription/Demucs] Cleaned up empty cache dir: {stems_dir}")
    
    print(f"[NoteTranscription/Demucs] Separating guitar track from: {wav_path}")
    print(f"[NoteTranscription/Demucs] Output dir: {out_dir}, expected: {guitar_path}")
    try:
        cmd = [
            sys.executable, "-m", "demucs.separate",
            "-o", str(out_dir),
            "-n", "htdemucs",
            str(wav_path)
        ]
        print(f"[NoteTranscription/Demucs] Running command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True,
            env={"PYTHONIOENCODING": "utf-8", **os.environ}
        )
        if result.stdout:
            print(f"[NoteTranscription/Demucs] stdout: {result.stdout[:500]}")
        if result.stderr:
            print(f"[NoteTranscription/Demucs] stderr: {result.stderr[:500]}")
        
        # 出力ディレクトリの確認
        if not stems_dir.exists():
            # Demucs がファイル名をエスケープする場合のフォールバック
            htdemucs_dir = out_dir / "htdemucs"
            if htdemucs_dir.exists():
                candidates = [d for d in htdemucs_dir.iterdir() if d.is_dir()]
                print(f"[NoteTranscription/Demucs] Looking for stems in: {htdemucs_dir}, found dirs: {[d.name for d in candidates]}")
                if candidates:
                    stems_dir = candidates[-1]  # 最新のディレクトリ
                    guitar_path = stems_dir / "other.wav"
        
        if guitar_path.exists():
            print(f"[NoteTranscription/Demucs] ✅ Guitar track separated: {guitar_path}")
            return str(guitar_path)
        else:
            # 全stemsディレクトリを走査
            htdemucs_dir = out_dir / "htdemucs"
            if htdemucs_dir.exists():
                for d in htdemucs_dir.iterdir():
                    if d.is_dir():
                        files = list(d.iterdir())
                        print(f"[NoteTranscription/Demucs] Dir {d.name}: {[f.name for f in files]}")
            print(f"[NoteTranscription/Demucs] ❌ other.wav not found in {stems_dir}")
            return wav_path
            
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[NoteTranscription/Demucs] ❌ Separation failed: {e}")
        if hasattr(e, 'stderr') and e.stderr:
            print(f"[NoteTranscription/Demucs] stderr: {e.stderr[:500]}")
        print(f"[NoteTranscription/Demucs] Falling back to original audio")
        return wav_path


def midi_to_note_name(midi_pitch: int) -> str:
    """MIDI番号を音名に変換 (例: 60 → 'C4')"""
    octave = (midi_pitch // 12) - 1
    note = NOTE_NAMES[midi_pitch % 12]
    return f"{note}{octave}"


def midi_to_frequency(midi_pitch: int) -> float:
    """MIDI番号を周波数(Hz)に変換"""
    return 440.0 * (2.0 ** ((midi_pitch - 69) / 12.0))


def _remove_overlapping_notes(notes: List[Dict], max_polyphony: int = 6) -> List[Dict]:
    """
    同時発音数がギターの弦数(6)を超える場合、信頼度の低いノートを除去。
    また、同一ピッチの極端な重複を除去する。
    """
    if not notes:
        return notes

    # 同一ピッチで時間的に重複するノートを統合
    cleaned = []
    notes_by_pitch = {}
    for n in notes:
        p = n["midi_pitch"]
        if p not in notes_by_pitch:
            notes_by_pitch[p] = []
        notes_by_pitch[p].append(n)

    for pitch, pitch_notes in notes_by_pitch.items():
        pitch_notes.sort(key=lambda x: x["start_time"])
        merged = [pitch_notes[0].copy()]
        for n in pitch_notes[1:]:
            prev = merged[-1]
            # 前のノートと重複 or ほぼ連続 (30ms以内) → 統合
            if n["start_time"] <= prev["end_time"] + 0.03:
                prev["end_time"] = max(prev["end_time"], n["end_time"])
                prev["velocity"] = max(prev["velocity"], n["velocity"])
                prev["confidence"] = max(prev["confidence"], n["confidence"])
            else:
                merged.append(n.copy())
        cleaned.extend(merged)

    cleaned.sort(key=lambda n: (n["start_time"], n["midi_pitch"]))

    # 同時発音数チェック（タイムスライスごと）
    result = []
    for n in cleaned:
        concurrent = [
            r for r in result
            if r["start_time"] < n["end_time"] and r["end_time"] > n["start_time"]
        ]
        if len(concurrent) < max_polyphony:
            result.append(n)
        else:
            # 信頼度で比較し、最低のものと入れ替え
            min_conf = min(concurrent, key=lambda x: x["confidence"])
            if n["confidence"] > min_conf["confidence"]:
                result.remove(min_conf)
                result.append(n)

    result.sort(key=lambda n: (n["start_time"], n["midi_pitch"]))
    return result


def _apply_velocity_dynamics(notes: List[Dict]) -> List[Dict]:
    """
    ベロシティを正規化。ソロギターでは微弱な音も重要なため、
    最低ベロシティを保証しつつダイナミクスを保持する。
    """
    if not notes:
        return notes

    velocities = [n["velocity"] for n in notes]
    max_vel = max(velocities) if velocities else 127
    min_vel = min(velocities) if velocities else 0

    for n in notes:
        if max_vel > min_vel:
            # 40-120 の範囲にマッピング（繊細な弱音を保持）
            normalized = 40 + int((n["velocity"] - min_vel) / (max_vel - min_vel) * 80)
            n["velocity"] = min(127, max(40, normalized))
        else:
            n["velocity"] = 80

    return notes


# =========================================================================
# バンドスコア品質フィルタリング
# =========================================================================
# プロの採譜者が行うルールをコードで再現:
# 1. 人間が認識・演奏できない極短ノートを除去
# 2. ノイズレベルの低ベロシティ音を除去
# 3. 人間が弾けない速度の急速連打を間引き
# 4. 曲のキーに基づく調性フィルタ（スケール外の音に低信頼度を付与）

# 各キーのスケール音（半音番号 0-11）
SCALE_NOTES = {
    # メジャースケール
    "C":  {0, 2, 4, 5, 7, 9, 11},
    "Db": {1, 3, 5, 6, 8, 10, 0},
    "D":  {2, 4, 6, 7, 9, 11, 1},
    "Eb": {3, 5, 7, 8, 10, 0, 2},
    "E":  {4, 6, 8, 9, 11, 1, 3},
    "F":  {5, 7, 9, 10, 0, 2, 4},
    "F#": {6, 8, 10, 11, 1, 3, 5},
    "Gb": {6, 8, 10, 11, 1, 3, 5},
    "G":  {7, 9, 11, 0, 2, 4, 6},
    "Ab": {8, 10, 0, 1, 3, 5, 7},
    "A":  {9, 11, 1, 2, 4, 6, 8},
    "Bb": {10, 0, 2, 3, 5, 7, 9},
    "B":  {11, 1, 3, 4, 6, 8, 10},
    # マイナースケール（自然的短音階）
    "Cm":  {0, 2, 3, 5, 7, 8, 10},
    "C#m": {1, 3, 4, 6, 8, 9, 11},
    "Dm":  {2, 4, 5, 7, 9, 10, 0},
    "Ebm": {3, 5, 6, 8, 10, 11, 1},
    "Em":  {4, 6, 7, 9, 11, 0, 2},
    "Fm":  {5, 7, 8, 10, 0, 1, 3},
    "F#m": {6, 8, 9, 11, 1, 2, 4},
    "Gm":  {7, 9, 10, 0, 2, 3, 5},
    "G#m": {8, 10, 11, 1, 3, 4, 6},
    "Am":  {9, 11, 0, 2, 4, 5, 7},
    "Bbm": {10, 0, 1, 3, 5, 6, 8},
    "Bm":  {11, 1, 2, 4, 6, 7, 9},
}


def _band_score_filter(notes: List[Dict], key: str = "C", bpm: float = 120.0,
                       solo_guitar: bool = False) -> List[Dict]:
    """
    バンドスコアのプロ採譜ルールに基づくフィルタリング。
    人間が認識・演奏できる音だけを残し、読みやすいTAB譜を生成する。

    Parameters
    ----------
    notes : List[Dict]
        raw note events
    key : str
        曲の調（例: "C", "Am", "G"）
    bpm : float
        曲のBPM
    solo_guitar : bool
        True の場合、ソロギター向けに閾値を緩和する。
        装飾音・弱音・速いパッセージを保持しやすくなる。
    """
    if not notes:
        return notes

    # --- ソロギター vs バンド でパラメータを切り替え ---
    if solo_guitar:
        MIN_DURATION_SEC = 0.04       # 40ms: グレースノート(30-50ms)保持
        VEL_NOISE_RATIO = 0.20        # pp音を保持（ソロギターはダイナミクスが広い）
        VEL_NOISE_FLOOR = 20          # 最低ベロシティ閾値
        SCALE_PENALTY = 0.7           # スケール外の減衰を緩和（ブルーノート保持）
        CONFIDENCE_THRESHOLD = 0.15   # 信頼度閾値を緩和
        MAX_NOTES_PER_MEASURE = 32    # 速いパッセージ(32分音符)対応
        mode_label = "SoloGuitar"
    else:
        MIN_DURATION_SEC = 0.08       # 80ms: バンドスコアでは短い音は不要
        VEL_NOISE_RATIO = 0.30        # ノイズ除去を強めに
        VEL_NOISE_FLOOR = 30          # 最低ベロシティ閾値
        SCALE_PENALTY = 0.5           # スケール外は強めにペナルティ
        CONFIDENCE_THRESHOLD = 0.25   # 信頼度閾値
        MAX_NOTES_PER_MEASURE = 16    # バンドスコアは適度な密度に
        mode_label = "Band"

    original_count = len(notes)
    beat_duration = 60.0 / bpm  # 1拍の秒数
    print(f"[BandScoreFilter] Mode={mode_label}, BPM={bpm:.0f}, Key={key}")

    # === STEP 1: 極短ノート除去 ===
    notes = [n for n in notes if (n["end_time"] - n["start_time"]) >= MIN_DURATION_SEC]
    print(f"[BandScoreFilter] After min duration ({MIN_DURATION_SEC*1000:.0f}ms): {len(notes)} notes (removed {original_count - len(notes)})")

    # === STEP 2: 低ベロシティ (ノイズ) 除去 ===
    if notes:
        avg_vel = sum(n["velocity"] for n in notes) / len(notes)
        noise_threshold = max(VEL_NOISE_FLOOR, avg_vel * VEL_NOISE_RATIO)
        before = len(notes)
        notes = [n for n in notes if n["velocity"] >= noise_threshold]
        print(f"[BandScoreFilter] After velocity filter (>{noise_threshold:.0f}): {len(notes)} notes (removed {before - len(notes)})")

    # === STEP 3: 急速連打の間引き ===
    # 同一ピッチで極端に近い音を間引く
    min_interval = beat_duration / 8 if solo_guitar else beat_duration / 6
    if notes:
        before = len(notes)
        filtered = [notes[0]]
        for n in notes[1:]:
            prev = filtered[-1]
            if (n["midi_pitch"] == prev["midi_pitch"] and
                    n["start_time"] - prev["start_time"] < min_interval):
                if (n["end_time"] - n["start_time"]) > (prev["end_time"] - prev["start_time"]):
                    filtered[-1] = n
                continue
            filtered.append(n)
        notes = filtered
        print(f"[BandScoreFilter] After rapid repeat filter ({min_interval*1000:.0f}ms): {len(notes)} notes (removed {before - len(notes)})")

    # === STEP 4: 調性フィルタ ===
    # スケール外の音の信頼度を下げる（完全除去はしない）
    # キー文字列を SCALE_NOTES のキーに変換 ("A minor" → "Am", "C major" → "C")
    scale_key = key
    if " minor" in key:
        scale_key = key.replace(" minor", "").strip() + "m"
    elif " major" in key:
        scale_key = key.replace(" major", "").strip()
    scale = SCALE_NOTES.get(scale_key, None)
    if scale and notes:
        off_scale_count = 0
        for n in notes:
            pitch_class = n["midi_pitch"] % 12
            if pitch_class not in scale:
                n["confidence"] = n.get("confidence", 0.8) * SCALE_PENALTY
                off_scale_count += 1
        print(f"[BandScoreFilter] Key={key}: {off_scale_count} off-scale notes confidence × {SCALE_PENALTY}")

    # === STEP 5: 信頼度ベースの最終フィルタ ===
    if notes:
        before = len(notes)
        notes = [n for n in notes if n.get("confidence", 0.8) >= CONFIDENCE_THRESHOLD]
        print(f"[BandScoreFilter] After confidence filter (>{CONFIDENCE_THRESHOLD}): {len(notes)} notes (removed {before - len(notes)})")

    # === STEP 6: 密度制限 ===
    measure_duration = beat_duration * 4  # 4/4拍子
    if notes:
        before = len(notes)
        final_notes = []
        if notes:
            song_start = notes[0]["start_time"]
            for n in notes:
                measure_idx = int((n["start_time"] - song_start) / measure_duration)
                measure_start = song_start + measure_idx * measure_duration
                measure_end = measure_start + measure_duration
                notes_in_measure = sum(
                    1 for fn in final_notes
                    if measure_start <= fn["start_time"] < measure_end
                )
                if notes_in_measure < MAX_NOTES_PER_MEASURE:
                    final_notes.append(n)
        notes = final_notes
        print(f"[BandScoreFilter] After density limit ({MAX_NOTES_PER_MEASURE}/measure): {len(notes)} notes (removed {before - len(notes)})")

    print(f"[BandScoreFilter] Final: {original_count} → {len(notes)} notes ({original_count - len(notes)} removed)")
    return notes


def _enhanced_librosa_transcribe(
    wav_path: str,
    onset_threshold: float = 0.15,
    frame_threshold: float = 0.10,
    minimum_note_length: float = 20.0,
    minimum_frequency=None,
    maximum_frequency=None,
):
    """
    強化版 librosa 音符検出。
    CQT ベースのポリフォニック検出 + 改善されたオンセット検出 + 精密ピッチ推定。
    basic-pitch が利用できない環境で、Demucs 分離後のギター音声に対して使用。
    """
    import librosa

    print("[NoteTranscription/Enhanced] Loading audio...")
    y, sr = librosa.load(wav_path, sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    # ギター音域
    fmin = minimum_frequency or librosa.note_to_hz('E2')
    fmax = maximum_frequency or librosa.note_to_hz('E6')

    # =========================================================================
    # 1. 強化版オンセット検出（複数特徴量のアンサンブル）
    # =========================================================================
    hop_length = 512
    
    # Spectral Flux（メルスペクトログラムベース）
    onset_env_mel = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=hop_length,
        aggregate=np.median, fmin=fmin, fmax=fmax,
        n_mels=128
    )
    # Spectral Flux（CQTベース — 低音域の解像度が高い）
    C = np.abs(librosa.cqt(y=y, sr=sr, hop_length=hop_length,
                           fmin=fmin, n_bins=60, bins_per_octave=12))
    onset_env_cqt = librosa.onset.onset_strength(
        sr=sr, hop_length=hop_length,
        S=librosa.amplitude_to_db(C, ref=np.max)
    )
    # アンサンブル: 両方の検出結果を組み合わせ
    min_len = min(len(onset_env_mel), len(onset_env_cqt))
    onset_env_combined = (
        onset_env_mel[:min_len] * 0.6 +
        onset_env_cqt[:min_len] * 0.4
    )
    
    # オンセット検出: delta を低めにしてより多くのアタックを検出
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, onset_envelope=onset_env_combined,
        hop_length=hop_length,
        delta=onset_threshold * 0.25,
        backtrack=True,
        wait=int(minimum_note_length / 1000.0 * sr / hop_length),  # 最小ノート長を待機
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)
    print(f"[NoteTranscription/Enhanced] Detected {len(onset_times)} onsets (ensemble)")

    # =========================================================================
    # 2. 高精度ピッチ検出 (pyin — 最適化パラメータ)
    # =========================================================================
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=fmin, fmax=fmax, sr=sr,
        frame_length=2048,
        hop_length=hop_length,
        fill_na=None,        # NaN を保持して voiced 判定に使用
        center=True,
        win_length=1024,     # より短い窓で時間分解能向上
        resolution=0.05,     # ピッチ解像度を向上 (5セント)
    )
    pitch_times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop_length)
    print(f"[NoteTranscription/Enhanced] Pitch frames: {len(f0)}, voiced: {np.sum(voiced_flag)}")

    # =========================================================================
    # 3. CQT ベースのポリフォニック補助検出
    # =========================================================================
    # CQT のピーク検出で pyin の単音検出を補完
    cqt_notes = _detect_polyphonic_from_cqt(
        C, sr, hop_length, fmin, onset_times, minimum_note_length / 1000.0
    )
    print(f"[NoteTranscription/Enhanced] CQT polyphonic candidates: {len(cqt_notes)}")

    # =========================================================================
    # 4. pyin ベースのメインノート検出
    # =========================================================================
    min_note_sec = minimum_note_length / 1000.0
    note_events = []

    for idx, onset_t in enumerate(onset_times):
        # 次のオンセットまでがノートの最大長
        if idx + 1 < len(onset_times):
            max_end = onset_times[idx + 1]
        else:
            max_end = duration

        # onset 付近のピッチを取得
        pitch_idx = np.searchsorted(pitch_times, onset_t)
        if pitch_idx >= len(f0):
            continue

        # onset から先の voiced フレームでピッチを決定
        pitches_in_region = []
        end_t = onset_t
        max_frames = min(pitch_idx + 80, len(f0))  # より広い範囲を探索
        for pi in range(pitch_idx, max_frames):
            t = pitch_times[pi]
            if t >= max_end:
                break
            if voiced_flag[pi] and f0[pi] is not None and not np.isnan(f0[pi]):
                pitches_in_region.append(f0[pi])
                end_t = t
            elif len(pitches_in_region) > 3:
                # 十分な voiced フレームが集まった後に途切れたらノート終了
                break
            elif len(pitches_in_region) > 0 and (t - onset_t) > 0.05:
                # 短い voiced 区間で途切れた場合もノート終了
                break

        if not pitches_in_region:
            continue

        # 安定区間のピッチ（四分位処理で外れ値を除去）
        freqs = np.array(pitches_in_region)
        if len(freqs) >= 4:
            q1, q3 = np.percentile(freqs, [25, 75])
            iqr = q3 - q1
            mask = (freqs >= q1 - 1.5 * iqr) & (freqs <= q3 + 1.5 * iqr)
            freqs = freqs[mask] if np.any(mask) else freqs
        
        median_freq = float(np.median(freqs))
        midi_pitch = int(round(librosa.hz_to_midi(median_freq)))

        note_end = max(end_t, onset_t + min_note_sec)
        if note_end > max_end:
            note_end = max_end
        if note_end - onset_t < min_note_sec:
            continue

        # confidence は voiced_prob の平均（重み付き）
        conf_idx_start = pitch_idx
        conf_idx_end = min(pitch_idx + len(pitches_in_region), len(voiced_prob))
        conf_values = voiced_prob[conf_idx_start:conf_idx_end]
        if len(conf_values) > 0:
            # 後半のフレームにより低い重みを指定（onset 付近の信頼度を重視）
            weights = np.linspace(1.0, 0.5, len(conf_values))
            confidence = float(np.average(conf_values, weights=weights))
        else:
            confidence = 0.5

        # velocity は onset_strength から推定（強化版）
        onset_frame = librosa.time_to_frames(onset_t, sr=sr, hop_length=hop_length)
        if onset_frame < len(onset_env_combined):
            vel_raw = onset_env_combined[onset_frame]
            max_env = np.max(onset_env_combined) + 1e-8
            # RMS エネルギーも考慮
            rms_frame_start = max(0, int(onset_t * sr))
            rms_frame_end = min(len(y), int((onset_t + 0.05) * sr))
            if rms_frame_end > rms_frame_start:
                rms_local = float(np.sqrt(np.mean(y[rms_frame_start:rms_frame_end] ** 2)))
                rms_global = float(np.sqrt(np.mean(y ** 2))) + 1e-8
                rms_factor = min(rms_local / rms_global, 2.0)
            else:
                rms_factor = 1.0
            velocity = int(np.clip(
                vel_raw / max_env * 100 * rms_factor + 20,
                30, 127
            ))
        else:
            velocity = 80

        note_events.append((
            round(onset_t, 4),
            round(note_end, 4),
            midi_pitch,
            velocity,
            round(confidence, 4),
        ))

    # =========================================================================
    # 5. CQT ポリフォニック結果をマージ
    # =========================================================================
    note_events = _merge_polyphonic_notes(note_events, cqt_notes, min_note_sec)

    print(f"[NoteTranscription/Enhanced] Produced {len(note_events)} note events")
    return note_events


def _detect_polyphonic_from_cqt(
    C: np.ndarray, sr: int, hop_length: int,
    fmin: float, onset_times: np.ndarray, min_note_sec: float
) -> List[Tuple]:
    """
    CQT スペクトログラムからポリフォニック成分をピーク検出で抽出。
    pyin の単音検出を補完するために使用。
    """
    import librosa
    
    # CQT の周波数軸
    cqt_freqs = librosa.cqt_frequencies(n_bins=C.shape[0], fmin=fmin, bins_per_octave=12)
    
    # dB 変換
    C_db = librosa.amplitude_to_db(C, ref=np.max)
    
    # 閾値: ピークは -30dB 以上
    threshold_db = -30.0
    
    polyphonic_notes = []
    
    for onset_t in onset_times:
        frame_idx = int(onset_t * sr / hop_length)
        if frame_idx >= C_db.shape[1]:
            continue
        
        # onset 周辺の数フレームの平均スペクトル
        frame_end = min(frame_idx + 3, C_db.shape[1])
        spectrum = np.mean(C_db[:, frame_idx:frame_end], axis=1)
        
        # ピーク検出（局所最大値）
        peaks = []
        for i in range(1, len(spectrum) - 1):
            if (spectrum[i] > spectrum[i-1] and 
                spectrum[i] > spectrum[i+1] and
                spectrum[i] > threshold_db):
                peaks.append((i, spectrum[i]))
        
        # 上位6つまで（ギターの弦数）
        peaks.sort(key=lambda x: x[1], reverse=True)
        for peak_bin, peak_db in peaks[:6]:
            freq = cqt_freqs[peak_bin]
            midi = int(round(librosa.hz_to_midi(freq)))
            
            # ギター音域チェック
            if midi < GUITAR_RANGE_MIN or midi > GUITAR_RANGE_MAX:
                continue
            
            # confidence は dB レベルから推定
            confidence = float(np.clip((peak_db + 40) / 40, 0.3, 0.95))
            
            # ノート長の推定（CQT エネルギーが閾値を下回るまで）
            end_frame = frame_idx + 1
            while end_frame < C_db.shape[1]:
                if C_db[peak_bin, end_frame] < threshold_db - 10:
                    break
                end_frame += 1
            end_t = end_frame * hop_length / sr
            
            note_dur = end_t - onset_t
            if note_dur < min_note_sec:
                continue
            
            polyphonic_notes.append((
                round(onset_t, 4),
                round(end_t, 4),
                midi,
                70,  # デフォルト velocity
                round(confidence, 4),
            ))
    
    return polyphonic_notes


def _merge_polyphonic_notes(
    main_notes: List[Tuple], poly_notes: List[Tuple], min_note_sec: float
) -> List[Tuple]:
    """
    pyin メインノートと CQT ポリフォニックノートをマージ。
    メインノートと重複しないポリフォニックノートのみ追加。
    """
    if not poly_notes:
        return main_notes
    
    merged = list(main_notes)
    
    for pn in poly_notes:
        pn_start, pn_end, pn_midi = pn[0], pn[1], pn[2]
        
        # 既存ノートとの重複チェック
        is_duplicate = False
        for mn in main_notes:
            mn_start, mn_end, mn_midi = mn[0], mn[1], mn[2]
            # 同一ピッチで時間的に重複している場合はスキップ
            if (mn_midi == pn_midi and
                abs(mn_start - pn_start) < 0.05):
                is_duplicate = True
                break
            # 近いピッチ（1半音以内）で同時刻の場合もスキップ
            if (abs(mn_midi - pn_midi) <= 1 and
                abs(mn_start - pn_start) < 0.03):
                is_duplicate = True
                break
        
        if not is_duplicate:
            merged.append(pn)
    
    # 時間順にソート
    merged.sort(key=lambda x: (x[0], x[2]))
    return merged


# 後方互換性のためのエイリアス
def _librosa_fallback_transcribe(
    wav_path: str,
    onset_threshold: float = 0.15,
    frame_threshold: float = 0.10,
    minimum_note_length: float = 20.0,
    minimum_frequency=None,
    maximum_frequency=None,
):
    """後方互換性のためのエイリアス。強化版を呼び出す。"""
    return _enhanced_librosa_transcribe(
        wav_path, onset_threshold, frame_threshold,
        minimum_note_length, minimum_frequency, maximum_frequency
    )


def transcribe_notes(
    wav_path: str,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    minimum_note_length: float = 58.0,
    filter_guitar_range: bool = True,
    minimum_frequency: Optional[float] = None,
    maximum_frequency: Optional[float] = None,
    solo_guitar_mode: bool = True,
    guitar_wav_path: Optional[str] = None,
    use_demucs: bool = True,
    use_basic_pitch: bool = True,
    key: str = "C",
    bpm: float = 120.0,
) -> List[Dict]:
    """
    オーディオファイルから音符を検出する。
    Demucs でギタートラックを分離してから検出可能。

    Parameters
    ----------
    wav_path : str
        WAVファイルのパス
    onset_threshold : float
        オンセット検出の閾値 (0-1)。
    frame_threshold : float
        フレームレベルの音符検出閾値 (0-1)。
    minimum_note_length : float
        最小ノート長（ミリ秒）。
    filter_guitar_range : bool
        ギターの音域 (E2-E6) でフィルタリングするか
    minimum_frequency : float, optional
        最低周波数 (Hz)。
    maximum_frequency : float, optional
        最高周波数 (Hz)。
    solo_guitar_mode : bool
        ソロギターモード。有効時は追加のフィルタリングと最適化を適用。
    guitar_wav_path : str, optional
        Demucs で分離済みのギタートラックのパス。
        指定された場合、Demucs 分離をスキップしてこのファイルを使用。
    use_demucs : bool
        True の場合、Demucs でギタートラックを分離してから検出する。
        guitar_wav_path が指定されている場合はこの設定に関わらず分離をスキップ。

    Returns
    -------
    List[Dict]
        NoteEventのリスト（start_time順にソート済み）
    """
    import time as _time
    _t0 = _time.time()
    print(f"[NoteTranscription] === START ===")
    print(f"[NoteTranscription] Input: {wav_path}")
    # ソロギターモード: デフォルトの高閾値 (onset=0.5, frame=0.3) をそのまま使用
    # ソロギターはバンドよりクリーンな音源なので、高い閾値で精度を優先
    # 緩めた閾値はノイズや倍音を拾いすぎて TAB が乱雑になる
    if solo_guitar_mode:
        minimum_note_length = max(minimum_note_length, 50.0)
    
    # BPM連動の最小ノート長調整
    # 高BPM (>160): 32分音符を許容するため短いノートも残す
    # 低BPM (<80): 長いノートが主体なので短いノイズを積極除去
    bpm_adjusted_min_note = minimum_note_length
    if bpm > 160:
        bpm_adjusted_min_note = max(30.0, minimum_note_length * 0.6)
    elif bpm < 80:
        bpm_adjusted_min_note = max(minimum_note_length, 80.0)
    minimum_note_length = bpm_adjusted_min_note
    
    print(f"[NoteTranscription] Params: onset={onset_threshold}, frame={frame_threshold}, "
          f"min_note_len={minimum_note_length:.0f}ms (BPM={bpm:.0f}), solo_guitar={solo_guitar_mode}, "
          f"use_demucs={use_demucs}, use_basic_pitch={use_basic_pitch}")

    # --- Demucs でギタートラック分離 ---
    detection_path = wav_path
    if guitar_wav_path and Path(guitar_wav_path).exists():
        detection_path = guitar_wav_path
        print(f"[NoteTranscription] Using provided guitar track: {detection_path}")
    elif use_demucs:
        try:
            _t_demucs = _time.time()
            detection_path = separate_guitar_track(wav_path)
            _dt_demucs = _time.time() - _t_demucs
            if detection_path != wav_path:
                print(f"[NoteTranscription] ✅ Demucs guitar track separated in {_dt_demucs:.1f}s")
            else:
                print(f"[NoteTranscription] ⚠️ Demucs returned original audio ({_dt_demucs:.1f}s)")
        except Exception as e:
            print(f"[NoteTranscription] ❌ Demucs failed: {type(e).__name__}: {e}")
            detection_path = wav_path

    note_events = None
    transcription_method = "unknown"

    # --- ギター音域の周波数範囲をデフォルト設定 ---
    if filter_guitar_range:
        if minimum_frequency is None:
            minimum_frequency = 82.0   # E2 (6弦開放)
        if maximum_frequency is None:
            maximum_frequency = 1319.0  # E6 (1弦24フレット付近)

    if use_basic_pitch:
        # --- Try basic-pitch (Spotify AI) --- (60秒タイムアウト)
        try:
            from basic_pitch.inference import predict
            from basic_pitch import ICASSP_2022_MODEL_PATH, FilenameSuffix, build_icassp_2022_model_path
            import concurrent.futures as cf

            # TF 2.20とbasic-pitch 0.4.0の非互換性回避: ONNXモデルを強制使用
            model_path = ICASSP_2022_MODEL_PATH
            onnx_path = build_icassp_2022_model_path(FilenameSuffix.onnx)
            if onnx_path.exists():
                model_path = onnx_path
                print(f"[NoteTranscription] 🧠 basic-pitch ONNX model: {onnx_path}")
            else:
                print(f"[NoteTranscription] 🧠 basic-pitch default model: {model_path}")

            print(f"[NoteTranscription] 🧠 basic-pitch AI で音符検出中... (file: {Path(detection_path).name})")
            
            def _run_basic_pitch():
                return predict(
                    audio_path=detection_path,
                    model_or_model_path=model_path,
                    onset_threshold=onset_threshold,
                    frame_threshold=frame_threshold,
                    minimum_note_length=minimum_note_length,
                    minimum_frequency=minimum_frequency,
                    maximum_frequency=maximum_frequency,
                )
            
            TIMEOUT_SEC = 120
            with cf.ThreadPoolExecutor(max_workers=1) as bp_executor:
                _t_bp = _time.time()
                bp_future = bp_executor.submit(_run_basic_pitch)
                try:
                    model_output, midi_data, note_events = bp_future.result(timeout=TIMEOUT_SEC)
                    _dt_bp = _time.time() - _t_bp
                    transcription_method = "basic-pitch-onnx"
                    print(f"[NoteTranscription] ✅ basic-pitch ONNX: {len(note_events)} notes in {_dt_bp:.1f}s")
                except cf.TimeoutError:
                    print(f"[NoteTranscription] ⏰ basic-pitch timed out after {TIMEOUT_SEC}s, switching to librosa")
                    note_events = _enhanced_librosa_transcribe(
                        detection_path, onset_threshold, frame_threshold,
                        minimum_note_length, minimum_frequency, maximum_frequency
                    )
                    transcription_method = "enhanced-librosa (timeout-fallback)"
        except ImportError:
            print("[NoteTranscription] ⚠️ basic-pitch not installed, using librosa")
            note_events = _enhanced_librosa_transcribe(
                detection_path, onset_threshold, frame_threshold,
                minimum_note_length, minimum_frequency, maximum_frequency
            )
            transcription_method = "enhanced-librosa"
        except Exception as e:
            print(f"[NoteTranscription] ⚠️ basic-pitch failed: {type(e).__name__}: {e}")
            note_events = _enhanced_librosa_transcribe(
                detection_path, onset_threshold, frame_threshold,
                minimum_note_length, minimum_frequency, maximum_frequency
            )
            transcription_method = "enhanced-librosa"
    else:
        # --- Librosa 高速検出（初回解析用） ---
        print(f"[NoteTranscription] ⚡ Librosa高速検出モード (file: {Path(detection_path).name})")
        note_events = _enhanced_librosa_transcribe(
            detection_path, onset_threshold, frame_threshold,
            minimum_note_length, minimum_frequency, maximum_frequency
        )
        transcription_method = "enhanced-librosa (fast)"

    _dt_total = _time.time() - _t0
    print(f"[NoteTranscription] === DONE: {len(note_events)} raw notes (method: {transcription_method}) in {_dt_total:.1f}s ===")

    # basic-pitch note_events format: List of (start_time_s, end_time_s, midi_pitch, amplitude, [pitch_bends])
    # amplitude は 0.0-1.0 の範囲で、音の強さを表す（velocity ではない）
    notes = []
    if note_events:
        first = note_events[0]
        print(f"[NoteTranscription] First note event raw: {first}")
        print(f"[NoteTranscription] Event length: {len(first)}, types: {[type(x).__name__ for x in first]}")

    for event in note_events:
        start_time = float(event[0])
        end_time = float(event[1])
        midi_pitch = int(event[2])
        
        # event[3] は amplitude (0.0-1.0) — velocity に変換
        amplitude = float(event[3]) if len(event) > 3 else 0.5
        velocity = max(20, min(127, int(amplitude * 127)))
        
        # amplitude をそのまま confidence として使用（高い amplitude = 高い信頼度）
        confidence = amplitude
        
        # event[4] はピッチベンド情報（basic-pitch固有）
        # ピッチベンドが大きいノートにはベンドフラグを付加
        has_pitch_bend = False
        pitch_bend_amount = 0.0
        if len(event) > 4 and event[4] is not None:
            try:
                bends = event[4]
                if hasattr(bends, '__len__') and len(bends) > 0:
                    bend_values = [float(b) for b in bends]
                    max_bend = max(abs(b) for b in bend_values) if bend_values else 0
                    if max_bend > 0.5:  # 半音以上のベンド
                        has_pitch_bend = True
                        pitch_bend_amount = max_bend
            except (TypeError, ValueError):
                pass

        # ギター音域フィルタリング
        if filter_guitar_range:
            if midi_pitch < GUITAR_RANGE_MIN or midi_pitch > GUITAR_RANGE_MAX:
                continue

        note_dict = {
            "start_time": round(start_time, 4),
            "end_time": round(end_time, 4),
            "midi_pitch": midi_pitch,
            "velocity": velocity,
            "confidence": round(confidence, 4),
            "note_name": midi_to_note_name(midi_pitch),
            "frequency": round(midi_to_frequency(midi_pitch), 2),
        }
        if has_pitch_bend:
            note_dict["pitch_bend"] = round(pitch_bend_amount, 2)
        notes.append(note_dict)

    # start_time でソート
    notes.sort(key=lambda n: (n["start_time"], n["midi_pitch"]))

    print(f"[NoteTranscription] After guitar range filter: {len(notes)} notes")

    # ソロギターモードの追加処理
    if solo_guitar_mode:
        notes = _remove_overlapping_notes(notes, max_polyphony=6)
        notes = _apply_velocity_dynamics(notes)
        
        # 倍音除去: 基音の1/2オクターブ上 + 完全5度上の偽ノートを除去
        harmonic_removed = 0
        keep = [True] * len(notes)
        # 検出対象の倍音間隔: 12=1オクターブ, 24=2オクターブ, 7=完全5度, 19=1オクターブ+5度
        HARMONIC_INTERVALS = {12, 24, 7, 19}
        
        for i, n in enumerate(notes):
            if not keep[i]:
                continue
            for j, m in enumerate(notes):
                if i == j or not keep[j]:
                    continue
                # 時間的に重複しているか
                if m["start_time"] > n["end_time"] or m["end_time"] < n["start_time"]:
                    continue
                pitch_diff = m["midi_pitch"] - n["midi_pitch"]
                # 上方倍音で、信頼度が低い方を除去
                if pitch_diff in HARMONIC_INTERVALS and m["confidence"] <= n["confidence"]:
                    keep[j] = False
                    harmonic_removed += 1
                elif -pitch_diff in HARMONIC_INTERVALS and n["confidence"] < m["confidence"]:
                    keep[i] = False
                    harmonic_removed += 1
                    break
        
        notes = [n for i, n in enumerate(notes) if keep[i]]
        if harmonic_removed > 0:
            print(f"[NoteTranscription] Harmonics removed: {harmonic_removed} (intervals: {HARMONIC_INTERVALS})")
        
        # ゴーストノート除去: 前後のノートと比較して極端に弱い音を除去
        ghost_removed = 0
        if len(notes) > 2:
            keep2 = [True] * len(notes)
            for i in range(1, len(notes) - 1):
                prev_vel = notes[i-1]["velocity"]
                next_vel = notes[i+1]["velocity"]
                curr_vel = notes[i]["velocity"]
                avg_neighbor = (prev_vel + next_vel) / 2
                # 周囲の平均の25%未満かつ、前後と時間的に近いノートを除去
                if (curr_vel < avg_neighbor * 0.25 and
                    notes[i]["start_time"] - notes[i-1]["start_time"] < 0.3):
                    keep2[i] = False
                    ghost_removed += 1
            notes = [n for i, n in enumerate(notes) if keep2[i]]
            if ghost_removed > 0:
                print(f"[NoteTranscription] Ghost notes removed: {ghost_removed}")
        
        print(f"[NoteTranscription] After solo guitar optimization: {len(notes)} notes")

    # バンドスコア品質フィルタリング（モードに応じて閾値を変更）
    notes = _band_score_filter(notes, key=key, bpm=bpm, solo_guitar=solo_guitar_mode)

    # テクニック検出（全モード共通）
    notes = detect_techniques(notes)
    tech_counts = {}
    for n in notes:
        for t in n.get("techniques", []):
            tname = t if isinstance(t, str) else t.get("type", "unknown")
            tech_counts[tname] = tech_counts.get(tname, 0) + 1
    if tech_counts:
        print(f"[NoteTranscription] Techniques detected: {tech_counts}")

    print(f"[NoteTranscription] Final: {len(notes)} notes")
    return notes


# =========================================================================
# ギター奏法テクニック検出エンジン
# =========================================================================

# ナチュラルハーモニクスの定位フレット（開放弦からの半音数）
HARMONIC_FRETS = {12, 7, 5, 4, 3, 9, 19, 24}  # 12=1倍音, 7=オクターブ上5度, 5=2オクターブ ...

def detect_techniques(notes: List[Dict]) -> List[Dict]:
    """
    ノートイベント列を分析し、各ノートに演奏テクニックを付与する。
    
    検出テクニック:
    - hammer_on: ハンマリングオン (H)
    - pull_off: プルオフ (P) 
    - slide_up / slide_down: スライド (S)
    - bend: ベンド (半音/全音/1.5音)
    - vibrato: ビブラート (~)
    - natural_harmonic: ナチュラルハーモニクス (N.H.)
    - tapping_harmonic: タッピング・ハーモニクス (T.H.)
    - palm_mute: パームミュート (P.M.)
    - palm_hit: パーム奏法 (P.H.) — ブリッジ付近を叩くバスドラム的低音
    - nail_attack: ネイルアタック (N.A.) — 爪で弦を叩くスネア的アクセント
    - attack_mute: アタックミュート (A.M.) — 叩きながらミュート
    - mute_brush: ブラッシング/ミュート (X)
    - ghost_note: ゴーストノート ((n))
    - let_ring: レットリング
    - accent: アクセント (>)
    - staccato: スタッカート (·)
    - tremolo: トレモロピッキング
    - tapping: タッピング (T)
    - slap: スラップ (S) — 親指で低音弦を叩く
    - arpeggio: アルペジオ
    - strumming: ストローク — ダイナミックに和音をかき鳴らす
    """
    if len(notes) < 1:
        return notes
    
    # 初期化: 全ノートに techniques リストを付与
    for n in notes:
        n["techniques"] = []
    
    # 全体統計（閾値の動的調整用）
    velocities = [n["velocity"] for n in notes]
    durations = [n["end_time"] - n["start_time"] for n in notes]
    avg_vel = np.mean(velocities) if velocities else 80
    std_vel = np.std(velocities) if len(velocities) > 1 else 10
    avg_dur = np.mean(durations) if durations else 0.3
    
    # --- Pass 1: 単一ノート特性分析 ---
    for i, note in enumerate(notes):
        dur = note["end_time"] - note["start_time"]
        vel = note["velocity"]
        conf = note["confidence"]
        midi = note["midi_pitch"]
        
        # ゴーストノート: 極めて低いベロシティ（強弱の文脈で判定）
        if vel < max(25, avg_vel * 0.35):
            note["techniques"].append("ghost_note")
        
        # ネイルアタック: 極高velocity + 極短duration + 高confidence（スネア的）
        elif vel > avg_vel + std_vel * 2.0 and dur < 0.10 and conf > 0.5:
            note["techniques"].append("nail_attack")
        
        # アクセント: 周囲に対して明確に強い
        elif vel > avg_vel + std_vel * 1.3 and vel > 90:
            note["techniques"].append("accent")
        
        # パーム奏法: 極低confidence + 極短duration + 低音域 + 高velocity
        # ブリッジ付近を掌底で叩き、バスドラム的な低音を出す打撃
        if conf < 0.30 and dur < 0.06 and midi < 55 and vel > 60:
            note["techniques"].append("palm_hit")
        
        # アタックミュート: 低confidence + 極短duration + 中〜高velocity
        # mute_brushより強い打撃的ミュート
        elif conf < 0.45 and dur < 0.06 and vel > 55:
            note["techniques"].append("attack_mute")
        
        # ブラッシング/ミュート: 低信頼度 + 極短Duration
        elif conf < 0.35 and dur < 0.08:
            note["techniques"].append("mute_brush")
        
        # パームミュート: やや低いconfidence + 短めDuration + 通常velocity
        elif conf < 0.55 and dur < 0.15 and vel > 40:
            note["techniques"].append("palm_mute")
        
        # スラップ: 低音域(6弦/5弦) + 極高velocity + 極短duration
        # 親指で低音弦を叩き、ベース的なアタック音
        if midi >= 40 and midi <= 52 and vel > avg_vel + std_vel * 1.5 and dur < 0.08:
            note["techniques"].append("slap")
        
        # スタッカート: 音価が平均の30%以下（極端に短い）
        if dur < avg_dur * 0.30 and dur < 0.12 and conf > 0.4:
            if "mute_brush" not in note["techniques"] and "attack_mute" not in note["techniques"]:
                note["techniques"].append("staccato")
        
        # レットリング: 音価が平均の2.5倍以上（極端に長い）
        if dur > avg_dur * 2.5 and dur > 0.8:
            note["techniques"].append("let_ring")
        
        # ナチュラルハーモニクス / タッピング・ハーモニクス
        # 開放弦からの半音数がハーモニクスフレットに一致するか
        for open_pitch in [40, 45, 50, 55, 59, 64]:  # E2, A2, D3, G3, B3, E4
            fret = midi - open_pitch
            if fret in HARMONIC_FRETS and 0 <= fret <= 24:
                # タッピング・ハーモニクス: ハーモニクスフレット + 高velocity + 短duration
                # 右手でフレットを瞬時に叩き、煌びやかな高音を響かせる
                if vel > avg_vel * 1.2 and dur < 0.25 and conf > 0.4:
                    note["techniques"].append({
                        "type": "tapping_harmonic",
                        "fret": fret
                    })
                # ナチュラルハーモニクス: 通常のハーモニクス（長めに響く）
                elif conf > 0.5 and dur > 0.3:
                    note["techniques"].append({
                        "type": "natural_harmonic",
                        "fret": fret
                    })
                break  # 1弦のみチェック
        
        # タッピング: 高フレット(12+) + 急激なアタック（高velocity + 短onset）
        for open_pitch in [40, 45, 50, 55, 59, 64]:
            fret = midi - open_pitch
            if 12 <= fret <= 24 and vel > avg_vel * 1.2:
                note["techniques"].append("tapping")
                break
    
    # --- Pass 2: 隣接ノートペア分析 (H/P/Slide/Bend) ---
    for i in range(len(notes) - 1):
        curr = notes[i]
        nxt = notes[i + 1]
        
        gap = nxt["start_time"] - curr["end_time"]
        pitch_diff = nxt["midi_pitch"] - curr["midi_pitch"]
        abs_diff = abs(pitch_diff)
        
        # 非常に近い2音間のテクニック（ギャップ < 30ms = レガート接続）
        if gap < 0.030 and gap > -0.05:  # わずかなオーバーラップも許容
            
            if abs_diff == 0:
                # 同一ピッチの高速反復 → 候補としてマーク
                pass
            elif 1 <= abs_diff <= 5:
                # 近い音程: H/P
                if pitch_diff > 0:
                    # 上行 → ハンマリングオン
                    curr["techniques"].append("hammer_on")
                    nxt["techniques"].append({"type": "hammer_on_target", "from_pitch": curr["midi_pitch"]})
                else:
                    # 下行 → プルオフ
                    curr["techniques"].append("pull_off")
                    nxt["techniques"].append({"type": "pull_off_target", "from_pitch": curr["midi_pitch"]})
            
            elif 5 < abs_diff <= 12:
                # やや離れた音程でレガート → スライド
                if pitch_diff > 0:
                    curr["techniques"].append("slide_up")
                    nxt["techniques"].append({"type": "slide_target", "direction": "up"})
                else:
                    curr["techniques"].append("slide_down")
                    nxt["techniques"].append({"type": "slide_target", "direction": "down"})
        
        # やや長いギャップでのスライド（ポルタメント的）
        elif 0.030 <= gap < 0.080 and 2 <= abs_diff <= 7:
            if pitch_diff > 0:
                curr["techniques"].append("slide_up")
            else:
                curr["techniques"].append("slide_down")
    
    # --- Pass 3: ベンド検出（ピッチの微妙なずれ）---
    # basic-pitchは半音単位なので、実際のベンドは隣接半音として現れる
    for i in range(len(notes) - 1):
        curr = notes[i]
        nxt = notes[i + 1]
        gap = nxt["start_time"] - curr["end_time"]
        pitch_diff = nxt["midi_pitch"] - curr["midi_pitch"]
        
        # ベンド: 同じタイミングで半音〜全音上がり、すぐ戻る
        if gap < 0.015 and pitch_diff in (1, 2, 3):
            # 次のノートが短ければ、ベンド+リリースの可能性
            nxt_dur = nxt["end_time"] - nxt["start_time"]
            curr_dur = curr["end_time"] - curr["start_time"]
            if nxt_dur < curr_dur * 0.5 or nxt_dur < 0.1:
                # ベンドアップ→リリース
                curr["techniques"].append({
                    "type": "bend",
                    "alter": pitch_diff * 0.5,  # 半音=0.5, 全音=1.0
                    "release": True
                })
            else:
                # 持続ベンド
                curr["techniques"].append({
                    "type": "bend",
                    "alter": pitch_diff * 0.5,
                    "release": False
                })
    
    # --- Pass 4: トレモロ検出（高速反復同一ピッチ） ---
    i = 0
    while i < len(notes) - 2:
        run_start = i
        midi_p = notes[i]["midi_pitch"]
        while i < len(notes) - 1:
            nxt = notes[i + 1]
            gap = nxt["start_time"] - notes[i]["end_time"]
            if nxt["midi_pitch"] == midi_p and gap < 0.05:
                i += 1
            else:
                break
        run_len = i - run_start + 1
        if run_len >= 4:  # 4回以上の高速反復
            # 個々の音符の duration が均一に短い
            avg_run_dur = np.mean([notes[j]["end_time"] - notes[j]["start_time"] for j in range(run_start, i + 1)])
            if avg_run_dur < 0.12:
                for j in range(run_start, i + 1):
                    notes[j]["techniques"].append("tremolo")
        i += 1
    
    # --- Pass 5: アルペジオ / ストローク検出（コード構成音の微小時差） ---
    i = 0
    while i < len(notes):
        # 80ms以内に始まる3音以上のグループ
        group = [i]
        j = i + 1
        while j < len(notes) and notes[j]["start_time"] - notes[i]["start_time"] < 0.08:
            group.append(j)
            j += 1
        
        if len(group) >= 3:
            # 各ノートの開始時間が微妙にずれている（完全同時でない）
            starts = [notes[g]["start_time"] for g in group]
            spread = max(starts) - min(starts)
            
            # ストローク: 4音以上 + 幅広いスプレッド + 均一なベロシティ
            # ダイナミックに和音をかき鳴らす奏法
            if len(group) >= 4 and 0.015 < spread < 0.080:
                group_vels = [notes[g]["velocity"] for g in group]
                vel_std = np.std(group_vels) if len(group_vels) > 1 else 0
                # ベロシティが均一（ストロークは全弦を均等に弾く）
                if vel_std < 20:
                    for g in group:
                        notes[g]["techniques"].append("strumming")
                else:
                    for g in group:
                        notes[g]["techniques"].append("arpeggio")
            elif 0.010 < spread < 0.050:  # 10-50msのスプレッド
                for g in group:
                    notes[g]["techniques"].append("arpeggio")
        
        i = j if j > i + 1 else i + 1
    
    # --- Pass 6: ビブラート検出（周期的ピッチ変動のパターン推定） ---
    # basic-pitch では微細なピッチ揺れは検出できないが、
    # 長いノートで confidence の変動がある場合にビブラートの可能性
    for note in notes:
        dur = note["end_time"] - note["start_time"]
        # 長めの音符 + 中〜高confidence → ビブラート候補
        if dur > 0.5 and note["confidence"] > 0.4 and note["velocity"] > 50:
            # ロングトーンでのビブラートは非常に一般的
            if "let_ring" not in note["techniques"]:
                note["techniques"].append("vibrato")
    
    # --- Final Pass: テクニック数の制限 ---
    # 1ノートに3個以上のテクニックは現実的でない。
    # 優先度順に最大2個まで保持。
    TECHNIQUE_PRIORITY = {
        "hammer_on": 10, "pull_off": 10,
        "hammer_on_target": 9, "pull_off_target": 9,
        "slide_up": 9, "slide_down": 9,
        "slide_target": 8,
        "bend": 8,
        "natural_harmonic": 7, "tapping_harmonic": 7,
        "vibrato": 6,
        "let_ring": 5,
        "palm_mute": 5,
        "staccato": 4,
        "accent": 4,
        "tapping": 3,
        "arpeggio": 3,
        "ghost_note": 3,
        "mute_brush": 2,
        "palm_hit": 2,
        "nail_attack": 2,
        "attack_mute": 2,
        "slap": 2,
        "tremolo": 2,
        "strumming": 1,
    }
    MAX_TECHNIQUES = 2
    
    for note in notes:
        techs = note["techniques"]
        if len(techs) > MAX_TECHNIQUES:
            # 優先度順にソートして上位のみ保持
            def tech_priority(t):
                name = t if isinstance(t, str) else t.get("type", "")
                return TECHNIQUE_PRIORITY.get(name, 0)
            techs.sort(key=tech_priority, reverse=True)
            note["techniques"] = techs[:MAX_TECHNIQUES]
    
    return notes


def notes_to_summary(notes: List[Dict]) -> Dict:
    """ノートイベントの要約統計を返す"""
    if not notes:
        return {"total_notes": 0}

    pitches = [n["midi_pitch"] for n in notes]
    durations = [n["end_time"] - n["start_time"] for n in notes]

    return {
        "total_notes": len(notes),
        "pitch_range": {
            "min": min(pitches),
            "max": max(pitches),
            "min_name": midi_to_note_name(min(pitches)),
            "max_name": midi_to_note_name(max(pitches)),
        },
        "duration_stats": {
            "min": round(min(durations), 4),
            "max": round(max(durations), 4),
            "mean": round(np.mean(durations), 4),
        },
        "time_span": {
            "start": notes[0]["start_time"],
            "end": notes[-1]["end_time"],
        },
    }
