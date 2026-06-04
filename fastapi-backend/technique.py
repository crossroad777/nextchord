"""
technique.py -- NextChord 演奏テクニック検出モジュール
=====================================================
SoloTab の technique_detector.py を参考に、NextChord のノート形式に合わせて再実装。

検出テクニック (ルールベース):
  h   -- ハンマリング・オン  (上行レガート)
  p   -- プルオフ            (下行レガート)
  /   -- スライドアップ      (線形F0上昇)
  \\   -- スライドダウン      (線形F0下降)
  b   -- ベンド              (F0上昇->ピーク)

検出テクニック (F0解析 -- オプショナル):
  ~   -- ビブラート          (4-8Hz F0振動)
  b   -- ベンド              (F0軌跡から高精度検出)

ガード:
  - fret=0 (開放弦) はベンド不可
  - fret<3 (ローフレット) はベンド不可
  - ノート数 < 2 でも安全に動作

入力ノート形式 (NextChord):
  {
    "start_time": float,   # 秒
    "end_time":   float,   # 秒
    "midi_pitch": int,     # MIDI番号
    "string":     int,     # 弦番号 (1=1弦 … 6=6弦)
    "fret":       int,     # フレット番号
    "velocity":   int,     # 0-127
    ...
  }

参考文献:
  [1] Abesser et al. (2014) "Automatic Transcription of Guitar Tones
      and Playing Techniques", ISMIR 2014.
"""

from __future__ import annotations
import numpy as np
from typing import List, Dict, Optional, Tuple


# =============================================================================
# 閾値定数
# =============================================================================
HP_MAX_IOI      = 0.25    # H/P 最大 IOI（秒）
SLIDE_MAX_IOI   = 0.40    # スライド 最大 IOI
SLIDE_MIN_FRET  = 2       # スライド 最小フレット差
SLIDE_MAX_FRET  = 12      # スライド 最大フレット差
GLISS_MIN_FRET  = 5       # グリッサンド 最小フレット差
BEND_MAX_IOI    = 0.25    # ベンド 最大 IOI
VIBRATO_MIN_DUR = 0.25    # ビブラート 最短持続時間

# F0解析用
F0_SR           = 22050   # 内部リサンプリングSR
HOP_LENGTH      = 256     # PYIN hopサイズ
PYIN_FMIN       = 60      # F0最小Hz
PYIN_FMAX       = 1400    # F0最大Hz


# =============================================================================
# メイン API
# =============================================================================

def detect_techniques(
    notes:    List[dict],
    wav_path: Optional[str] = None,
    beats:    Optional[List[float]] = None,
    bpm:      float = 120.0,
    song_type: str = 'band',
) -> List[dict]:
    """
    NextChord ノートリストにテクニック情報を付与する。

    Parameters
    ----------
    notes    : start_time / end_time / midi_pitch / string / fret を持つノートリスト
    wav_path : 音声ファイルパス (F0解析に使用、省略可)
    beats    : ビート位置リスト (未使用、将来拡張用)
    bpm      : テンポ (IOI閾値スケーリングに使用)
    song_type: 'band' or 'solo' -- band mode skips F0 analysis (pyin) for performance

    Returns
    -------
    notes に ``technique`` フィールド (str) を追加して返す。
    テクニック未検出のノートには ``technique`` は付与しない。
    """
    if len(notes) < 2:
        # 0〜1ノートではペア比較不可 -- そのまま返す
        return notes

    # ── テンポ補正 ──
    tempo_scale = min(1.6, max(0.6, 120.0 / max(bpm, 60.0)))
    hp_max    = HP_MAX_IOI    * tempo_scale
    slide_max = SLIDE_MAX_IOI * tempo_scale
    bend_max  = BEND_MAX_IOI  * tempo_scale

    # ── F0解析 (オプショナル) ──
    audio      = None
    audio_sr   = None
    global_f0  = None

    if wav_path and song_type != 'band':
        # Solo mode: load audio + run pyin for F0-based technique detection
        try:
            from waveform_utils import load_audio_cached
            audio, audio_sr = load_audio_cached(wav_path, sr=F0_SR, mono=True)
            print(f"[Technique] Audio loaded: {len(audio)/audio_sr:.1f}s @ {audio_sr}Hz")
            global_f0, voiced, _ = librosa.pyin(
                audio,
                fmin=PYIN_FMIN,
                fmax=PYIN_FMAX,
                sr=audio_sr,
                hop_length=HOP_LENGTH,
                fill_na=None,
            )
            global_f0 = np.where(voiced, global_f0, np.nan)
            print(f"[Technique] Global F0 computed: {len(global_f0)} frames")
        except Exception as e:
            print(f"[Technique] Audio load failed: {e}, falling back to rule-based")
    elif wav_path and song_type == 'band':
        # Band mode: skip pyin entirely, audio loaded lazily below for palm mute / dead note
        print(f"[Technique] Band mode: skipping F0 analysis (pyin)")

    # ── ブラッシング/ミュート検出 ──
    # Moved to the end of the function: called once either in the audio-based
    # branch (_detect_dead_notes) or in the no-audio fallback (_detect_brushing).
    # Removed redundant call here to avoid double detection (BUG T-1).

    # ── 弦ごとに分離して処理 ──
    string_groups: Dict[int, List[int]] = {}
    for i, note in enumerate(notes):
        s = note.get("string")
        if s is not None:
            string_groups.setdefault(s, []).append(i)

    for _string_num, indices in string_groups.items():
        indices_sorted = sorted(indices, key=lambda i: notes[i]["start_time"])

        for pos in range(len(indices_sorted)):
            curr_idx = indices_sorted[pos]
            curr     = notes[curr_idx]

            # 既に付与済みならスキップ
            if curr.get("technique") and curr["technique"] != "normal":
                continue

            if pos == 0:
                # 先頭ノート -- ビブラートのみチェック
                if global_f0 is not None:
                    _try_vibrato(curr, audio, audio_sr, global_f0)
                continue

            prev_idx = indices_sorted[pos - 1]
            prev     = notes[prev_idx]

            # 前ノートが既にテクニック付与済み -> currにビブラートだけチェック
            if prev.get("technique") and prev["technique"] != "normal":
                if global_f0 is not None:
                    _try_vibrato(curr, audio, audio_sr, global_f0)
                continue

            ioi = curr["start_time"] - prev["start_time"]
            if ioi <= 0:
                continue

            pitch_diff = curr["midi_pitch"] - prev["midi_pitch"]
            abs_pitch  = abs(pitch_diff)
            fret_diff  = abs(curr.get("fret", 0) - prev.get("fret", 0))

            # ── F0軌跡解析 (音声がある場合は優先) ──
            if global_f0 is not None and ioi <= max(slide_max, hp_max):
                tech = _classify_from_f0(
                    prev, curr, audio, audio_sr,
                    pitch_diff, fret_diff,
                    hp_max, slide_max, bend_max,
                    global_f0=global_f0,
                )
                if tech:
                    prev["technique"] = tech
                    continue

            # ── ルールベースフォールバック ──
            tech = _rule_based(
                ioi, pitch_diff, abs_pitch, fret_diff,
                hp_max, slide_max, bend_max,
                curr_fret=curr.get("fret", 0),
                prev_fret=prev.get("fret", 0),
            )
            if tech:
                prev["technique"] = tech
                continue

            # ── ビブラート (単独ノート) ──
            if global_f0 is not None:
                _try_vibrato(curr, audio, audio_sr, global_f0)

    # --- ナチュラルハーモニクス（フレット位置+弦照合）---
    for note in notes:
        if not note.get("technique") or note["technique"] == "normal":
            if note.get("fret") in NH_FRETS:
                _check_harmonic(note)

    # --- Band mode: lazy-load audio for palm mute / dead note detection ---
    if audio is None and wav_path and song_type == 'band':
        try:
            from waveform_utils import load_audio_cached
            audio, audio_sr = load_audio_cached(wav_path, sr=F0_SR, mono=True)
            print(f"[Technique] Band mode: audio loaded for spectral analysis: {len(audio)/audio_sr:.1f}s")
        except Exception as e:
            print(f"[Technique] Band mode: audio load failed: {e}")

    # --- パームミュート（スペクトル重心ベース）---
    if audio is not None:
        _detect_palm_mute_batch(notes, audio, audio_sr)

    # --- ブラッシング/デッドノート（音響ベース: voiced_ratio + spectral_flatness）---
    if audio is not None:
        _detect_dead_notes(notes, audio, audio_sr, global_f0)
    else:
        # 音声なしフォールバック: 時間ベースのブラッシング検出
        _detect_brushing(notes, bpm)

    # --- トリル後処理（H/P 4連続以上→tr）---
    _convert_hp_chain_to_trill(notes)

    return notes


# =============================================================================
# F0 解析コア
# =============================================================================

def _extract_f0(
    audio:     np.ndarray,
    sr:        int,
    t_start:   float,
    t_end:     float,
    global_f0: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """指定区間のF0軌跡を取得する。"""
    try:
        if global_f0 is not None:
            fps = sr / HOP_LENGTH
            s = max(0, int(t_start * fps))
            e = min(len(global_f0), int(t_end * fps) + 1)
            if e - s < 2:
                return np.array([]), np.array([])
            f0_slice = global_f0[s:e]
            return f0_slice, ~np.isnan(f0_slice)

        # フォールバック: 個別 pyin
        import librosa
        s_sample = max(0, int(t_start * sr) - HOP_LENGTH)
        e_sample = min(len(audio), int(t_end * sr) + HOP_LENGTH)
        segment  = audio[s_sample:e_sample]
        if len(segment) < HOP_LENGTH * 4:
            return np.array([]), np.array([])

        f0, voiced, _ = librosa.pyin(
            segment, fmin=PYIN_FMIN, fmax=PYIN_FMAX,
            sr=sr, hop_length=HOP_LENGTH, fill_na=None,
        )
        return np.where(voiced, f0, np.nan), voiced
    except Exception:
        return np.array([]), np.array([])


def _midi_to_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _classify_from_f0(
    prev:       dict,
    curr:       dict,
    audio:      np.ndarray,
    sr:         int,
    pitch_diff: int,
    fret_diff:  int,
    hp_max:     float,
    slide_max:  float,
    bend_max:   float,
    **kwargs,
) -> Optional[str]:
    """
    F0軌跡を解析してテクニックを分類する (Abesser 2014 準拠)。
    """
    ioi = curr["start_time"] - prev["start_time"]
    _global_f0 = kwargs.get("global_f0", None)

    t_a = prev["start_time"]
    t_b = curr["start_time"] + min(0.08, curr["end_time"] - curr["start_time"])
    f0, voiced = _extract_f0(audio, sr, t_a, t_b, global_f0=_global_f0)

    if len(f0) < 6:
        return None

    valid = f0[~np.isnan(f0)]
    if len(valid) < 4:
        return None

    n     = len(f0)
    t_arr = np.arange(n) / (sr / HOP_LENGTH)

    ioi_frames = min(n, max(2, int(ioi * sr / HOP_LENGTH)))

    # ── 線形回帰 (傾き・R2) ──
    valid_mask = ~np.isnan(f0[:ioi_frames])
    if valid_mask.sum() < 4:
        return None
    t_v = t_arr[:ioi_frames][valid_mask]
    f_v = f0[:ioi_frames][valid_mask]

    slope, intercept = np.polyfit(t_v, f_v, 1) if len(t_v) >= 2 else (0, f_v[0])
    f_pred = np.polyval([slope, intercept], t_v)
    ss_res = np.sum((f_v - f_pred) ** 2)
    ss_tot = np.sum((f_v - np.mean(f_v)) ** 2)
    r2     = 1 - ss_res / ss_tot if ss_tot > 1e-6 else 0.0

    # ── ジャンプ (最初20% vs 最後20%) ──
    q = max(1, ioi_frames // 5)
    f0_start_region = f0[:q]
    f0_end_region   = f0[ioi_frames - q : ioi_frames]
    mean_start = np.nanmean(f0_start_region) if not np.all(np.isnan(f0_start_region)) else None
    mean_end   = np.nanmean(f0_end_region)   if not np.all(np.isnan(f0_end_region))   else None

    if mean_start is None or mean_end is None:
        return None

    jump_semi = 12 * np.log2(mean_end / mean_start) if mean_start > 0 and mean_end > 0 else 0.0

    # ── ピーク検出 (ベンド用) ──
    f0_ioi   = f0[:ioi_frames]
    peak_idx = np.nanargmax(f0_ioi) if not np.all(np.isnan(f0_ioi)) else None
    if peak_idx is not None:
        peak_hz    = f0_ioi[peak_idx]
        peak_ratio = peak_idx / max(1, ioi_frames)
        peak_rise  = 12 * np.log2(peak_hz / mean_start) if mean_start > 0 and peak_hz > 0 else 0.0
    else:
        peak_ratio = 0.5
        peak_rise  = 0.0

    abs_jump = abs(jump_semi)
    abs_diff = abs(pitch_diff)

    # ── ベンド: fret>=3 ガード (開放弦・ローフレットはベンド不可) ──
    prev_fret = prev.get("fret", 0)
    curr_fret = curr.get("fret", 0)
    if (ioi <= bend_max + 0.05
            and peak_rise >= 0.8
            and peak_ratio < 0.85
            and pitch_diff == 0
            and fret_diff == 0
            and prev_fret >= 3
            and curr_fret >= 3):
        return "b"

    # ── H / P: 急峻なジャンプ ──
    if ioi <= hp_max and abs_diff >= 1 and abs_diff <= 6:
        if r2 < 0.65 or abs_jump >= 0.8 * abs_diff:
            if jump_semi > 0.3:
                return "h"
            elif jump_semi < -0.3:
                return "p"

    # ── スライド: 線形F0遷移 ──
    if ioi <= slide_max and SLIDE_MIN_FRET <= fret_diff:
        if r2 >= 0.55 and abs_jump >= 0.5:
            if jump_semi > 0:
                return "/"
            elif jump_semi < 0:
                return "\\"

    # ── グリッサンド ──
    if ioi <= slide_max and fret_diff >= GLISS_MIN_FRET:
        if pitch_diff > 0:
            return "gliss_up"
        elif pitch_diff < 0:
            return "gliss_down"

    return None


# =============================================================================
# ビブラート検出
# =============================================================================

def _try_vibrato(
    note:      dict,
    audio:     Optional[np.ndarray],
    sr:        Optional[int],
    global_f0: Optional[np.ndarray],
) -> None:
    """ノートのビブラートを検出し、該当すれば technique='~' を付与する。"""
    if audio is None or sr is None or global_f0 is None:
        return
    dur = note["end_time"] - note["start_time"]
    if dur < VIBRATO_MIN_DUR:
        return
    if note.get("fret", 0) == 0:
        return  # 開放弦はビブラート不可

    try:
        f0, voiced = _extract_f0(
            audio, sr,
            note["start_time"] + 0.05,
            note["end_time"]   - 0.02,
            global_f0=global_f0,
        )
        valid = f0[~np.isnan(f0)]
        if len(valid) < 20:
            return

        f0_std_cents = 1200 * np.std(valid) / np.mean(valid) if np.mean(valid) > 0 else 0
        if f0_std_cents < 25:
            return

        fps   = sr / HOP_LENGTH
        freqs = np.fft.rfftfreq(len(valid), d=1.0 / fps)
        power = np.abs(np.fft.rfft(valid - np.mean(valid))) ** 2

        vib_mask    = (freqs >= 3.5) & (freqs <= 9.0)
        total_power = power.sum()
        vib_power   = power[vib_mask].sum()

        if total_power > 0 and vib_power / total_power > 0.45:
            note["technique"] = "~"
    except Exception:
        pass


# =============================================================================
# ルールベース フォールバック
# =============================================================================

def _rule_based(
    ioi:        float,
    pitch_diff: int,
    abs_pitch:  int,
    fret_diff:  int,
    hp_max:     float,
    slide_max:  float,
    bend_max:   float,
    curr_fret:  int = -1,
    prev_fret:  int = -1,
) -> Optional[str]:
    """F0解析なしのルールベース分類。"""

    # ベンド (同フレット・ピッチ上昇 -- H/Pより優先)
    # fret>=3 ガード: 開放弦・ローフレットはベンド不可
    if curr_fret >= 3 and prev_fret >= 3:
        if 0 < ioi <= bend_max and fret_diff == 0 and pitch_diff >= 1:
            if pitch_diff == 1:
                return "b_half"
            elif pitch_diff == 2:
                return "b"
            elif pitch_diff == 3:
                return "b_1half"
            elif pitch_diff >= 4:
                return "b_2"

    # H / P (フレット移動がある場合のみ -- 同フレットはベンド)
    if 0 < ioi <= hp_max and 0 < abs_pitch <= 6 and fret_diff > 0:
        return "h" if pitch_diff > 0 else "p"

    # H / P フォールバック (fret情報がない場合: fret_diff==0 だが fret<0 等)
    if 0 < ioi <= hp_max and 0 < abs_pitch <= 6 and curr_fret < 0:
        return "h" if pitch_diff > 0 else "p"

    # スライド
    if 0 < ioi <= slide_max and SLIDE_MIN_FRET <= fret_diff <= SLIDE_MAX_FRET:
        if fret_diff <= 5:
            if pitch_diff > 0:
                return "/"
            elif pitch_diff < 0:
                return "\\"

    # グリッサンド
    if 0 < ioi <= slide_max * 1.2 and fret_diff >= GLISS_MIN_FRET:
        return "gliss_up" if pitch_diff > 0 else "gliss_down"

    return None


# =============================================================================
# ナチュラルハーモニクス (SoloTab移植)
# =============================================================================

NH_FRETS = {5, 7, 12}
HARMONIC_FRETS_MAP = {12: 12, 7: 19, 5: 24}
DEFAULT_OPEN_STRINGS = [40, 45, 50, 55, 59, 64]

def _check_harmonic(note: dict) -> None:
    """ナチュラルハーモニクス判定（フレット位置+弦照合）。"""
    fret = note.get("fret", -1)
    pitch = note.get("midi_pitch", 0)
    string_num = note.get("string", -1)
    if fret not in HARMONIC_FRETS_MAP:
        return
    expected_offset = HARMONIC_FRETS_MAP[fret]
    open_pitch = pitch - expected_offset
    if open_pitch not in DEFAULT_OPEN_STRINGS:
        return
    if 1 <= string_num <= 6:
        string_idx = 6 - string_num
        actual_open = DEFAULT_OPEN_STRINGS[string_idx]
        if open_pitch != actual_open:
            return
    note["technique"] = "harmonic"


# =============================================================================
# パームミュート (SoloTab移植 - スペクトル重心ベース)
# =============================================================================

PM_CENTROID_RATIO = 0.45

def _detect_palm_mute_batch(
    notes: List[dict], audio: np.ndarray, sr: int
) -> None:
    """スペクトル重心が中央値の45%以下 + 短duration -> パームミュート。"""
    try:
        import librosa
        # Batch compute spectral centroid over the full audio (single call)
        full_centroid = librosa.feature.spectral_centroid(y=audio, sr=sr, hop_length=512)[0]
        centroid_fps = sr / 512  # frames per second for hop_length=512

        centroids = []
        for note in notes:
            if note.get("technique") and note["technique"] not in ("normal", ""):
                continue
            dur = note["end_time"] - note["start_time"]
            if dur < 0.05:
                continue
            # Look up centroid value at the corresponding frame index
            start_frame = max(0, int(note["start_time"] * centroid_fps))
            end_frame = min(len(full_centroid), int(note["end_time"] * centroid_fps) + 1)
            if end_frame <= start_frame:
                continue
            sc = float(np.mean(full_centroid[start_frame:end_frame]))
            centroids.append((note, sc))
        if not centroids:
            return
        median_centroid = np.median([c for _, c in centroids])
        pm_count = 0
        for note, sc in centroids:
            if sc < median_centroid * PM_CENTROID_RATIO:
                dur = note["end_time"] - note["start_time"]
                if dur < 0.18:
                    if not note.get("technique") or note["technique"] in ("normal", ""):
                        note["technique"] = "pm"
                        pm_count += 1
        if pm_count > 0:
            print(f"[Technique] Palm mute detected: {pm_count} notes")
    except Exception as e:
        print(f"[Technique] Palm mute detection error: {e}")


# =============================================================================
# デッドノート / ブラッシング (SoloTab移植 - 音響ベース)
# =============================================================================

def _detect_dead_notes(
    notes: List[dict], audio: np.ndarray, sr: int,
    global_f0: Optional[np.ndarray]
) -> None:
    """
    音響ベースのデッドノート/ブラッシング検出。
    voiced_ratio < 0.35 + spectral_flatness > 0.30 -> 'x' (デッドノート)
    """
    try:
        import librosa
        # Batch compute spectral flatness over the full audio (single call)
        full_flatness = librosa.feature.spectral_flatness(y=audio, hop_length=512)[0]
        flatness_fps = sr / 512  # frames per second for hop_length=512

        fps = sr / HOP_LENGTH
        # voiced detection: use global_f0 if available, otherwise fall back to flatness-only
        if global_f0 is not None:
            global_voiced = ~np.isnan(global_f0)
        else:
            global_voiced = None
        dead_count = 0
        for note in notes:
            if note.get("technique") and note["technique"] not in ("normal", ""):
                continue
            dur = note["end_time"] - note["start_time"]
            if dur < 0.02:
                continue
            # Voiced ratio from global F0 (if available)
            if global_voiced is not None:
                start_frame = max(0, int(note["start_time"] * fps))
                end_frame = min(len(global_voiced), int((note["start_time"] + min(dur, 0.15)) * fps))
                if end_frame > start_frame:
                    voiced_ratio = float(np.mean(global_voiced[start_frame:end_frame]))
                else:
                    voiced_ratio = 1.0
            else:
                # No F0 data (band mode): use a heuristic -- assume unvoiced if flatness is high
                voiced_ratio = 0.5  # neutral default; rely on flatness check below
            # Look up flatness value at the corresponding frame index
            flat_start = max(0, int(note["start_time"] * flatness_fps))
            flat_end = min(len(full_flatness), int((note["start_time"] + min(dur, 0.15)) * flatness_fps) + 1)
            if flat_end <= flat_start:
                continue
            flatness = float(np.mean(full_flatness[flat_start:flat_end]))
            is_unvoiced = voiced_ratio < 0.35
            is_noisy = flatness > 0.30
            is_very_short = dur < 0.08
            if global_voiced is not None:
                # Solo mode: original logic with voiced_ratio
                if (is_unvoiced and is_noisy) or (is_unvoiced and is_very_short):
                    note["technique"] = "x"
                    dead_count += 1
            else:
                # Band mode: rely on flatness + short duration heuristic
                if (is_noisy and is_very_short) or flatness > 0.50:
                    note["technique"] = "x"
                    dead_count += 1
        if dead_count > 0:
            print(f"[Technique] Dead notes detected: {dead_count} notes")
    except Exception as e:
        print(f"[Technique] Dead note detection error: {e}")


# =============================================================================
# トリル後処理 (SoloTab移植)
# =============================================================================

def _convert_hp_chain_to_trill(notes: List[dict]) -> None:
    """H/P が4音以上連続する場合、トリルに変換。"""
    if len(notes) < 4:
        return
    TRILL_MIN_CHAIN = 4
    string_groups: Dict[int, List[int]] = {}
    for i, note in enumerate(notes):
        s = note.get("string")
        if s is not None:
            string_groups.setdefault(s, []).append(i)
    trill_count = 0
    for _sn, indices in string_groups.items():
        indices_sorted = sorted(indices, key=lambda i: notes[i]["start_time"])
        chain = []
        for idx in indices_sorted:
            tech = notes[idx].get("technique")
            if tech in ("h", "p"):
                chain.append(idx)
            else:
                if len(chain) >= TRILL_MIN_CHAIN:
                    for ci in chain:
                        notes[ci]["technique"] = "tr"
                        trill_count += 1
                chain = []
        if len(chain) >= TRILL_MIN_CHAIN:
            for ci in chain:
                notes[ci]["technique"] = "tr"
                trill_count += 1
    if trill_count > 0:
        print(f"[Technique] Trill chains converted: {trill_count} notes")


# =============================================================================
# ブラッシング/ミュート検出
# =============================================================================

BRUSH_ONSET_TOL   = 0.05   # 同時発音の許容誤差（秒）
BRUSH_MIN_STRINGS = 3      # ブラッシング最小弦数（3弦から検出）
BRUSH_MAX_DUR     = 0.15   # ブラッシングの最大ノート長（秒）
BRUSH_LOW_VEL     = 70     # ブラッシング判定のvelocity閾値上限


def _detect_brushing(notes: List[dict], bpm: float = 120.0) -> None:
    """
    ブラッシング/ミュートストローク検出。
    
    条件:
    1. 同時に4弦以上がヒット（onset_tolerance以内）
    2. 全ノートのdurationが短い（< BRUSH_MAX_DUR）
    3. velocityが低め（< BRUSH_LOW_VEL）※ オプショナル
    
    該当ノートに technique='mute_brush' を付与。
    """
    if len(notes) < BRUSH_MIN_STRINGS:
        return
    
    # テンポ補正
    tempo_scale = min(1.6, max(0.6, 120.0 / max(bpm, 60.0)))
    max_dur = BRUSH_MAX_DUR * tempo_scale
    onset_tol = BRUSH_ONSET_TOL * tempo_scale
    
    # ノートを開始時間でソート
    sorted_indices = sorted(range(len(notes)), key=lambda i: notes[i]["start_time"])
    
    i = 0
    brush_count = 0
    while i < len(sorted_indices):
        # グループ: onset_tol以内に開始する連続ノートを収集
        group_start = i
        t0 = notes[sorted_indices[i]]["start_time"]
        while i < len(sorted_indices) and notes[sorted_indices[i]]["start_time"] - t0 <= onset_tol:
            i += 1
        group_end = i
        group_size = group_end - group_start
        
        if group_size < BRUSH_MIN_STRINGS:
            continue
        
        # グループ内の弦の多様性チェック
        group_indices = sorted_indices[group_start:group_end]
        strings_used = set(notes[idx].get("string", 0) for idx in group_indices)
        
        if len(strings_used) < BRUSH_MIN_STRINGS:
            continue
        
        # 全ノートが短いdurationかチェック
        all_short = all(
            (notes[idx]["end_time"] - notes[idx]["start_time"]) <= max_dur
            for idx in group_indices
        )
        
        # velocity平均チェック（オプショナル -- 低velocityならより確実）
        avg_vel = np.mean([notes[idx].get("velocity", 80) for idx in group_indices])
        
        # 判定: 短duration OR 低velocity のいずれかでブラッシング
        if all_short or avg_vel < BRUSH_LOW_VEL:
            for idx in group_indices:
                if not notes[idx].get("technique"):
                    notes[idx]["technique"] = "mute_brush"
            brush_count += len(group_indices)
    
    if brush_count > 0:
        print(f"[Technique] Brushing detected: {brush_count} notes marked as mute_brush")
