"""
gp5_export.py -- NextChord 専用 Guitar Pro 5 (.gp5) エクスポート
================================================================
SoloTab の gp_renderer.py の技術を元に、NextChord のデータフォーマットに
合わせて再実装したGP5出力モジュール。

NextChord notes フォーマット:
    {start, end, pitch, string, fret, velocity, ...}

歌詞コード: 不要（MusicXML側で対応）
テクニック: 不要（Phase 2後半で追加）

Usage:
    from gp5_export import notes_to_gp5
    gp5_bytes = notes_to_gp5(notes, beats=beats, bpm=120)
"""
from __future__ import annotations
from typing import List, Optional
import io
import guitarpro as gp


# divisions per quarter note (triplet grid: 12 = LCM(4,3))
DIVISIONS = 12


# ===========================================================================
# メイン関数
# ===========================================================================

def notes_to_gp5(
    notes: List[dict],
    *,
    beats: List[float] | None = None,
    bpm: float = 120.0,
    title: str = "",
    tuning: list | None = None,
    time_signature: str = "4/4",
    noise_gate: float = 0.2,
    chords: list | None = None,
) -> bytes:
    """
    ノートデータから GP5 バイナリを生成する。

    Parameters
    ----------
    notes : list[dict]
        Keys: start, end, pitch, string, fret, velocity, ...
    beats : list[float] | None
        ビート時刻(秒)。量子化に使用。
    bpm : float
        テンポ (BPM)
    title : str
        曲名
    tuning : list[int] | None
        [6th->1st] のMIDIノート番号。None=標準チューニング
    time_signature : str
        "3/4", "4/4", "6/8" etc.
    noise_gate : float
        0.0-1.0  velocity下位パーセンタイルをカットする閾値
    chords : list | None
        将来用 (現在未使用)

    Returns
    -------
    bytes : GP5バイナリデータ
    """
    if tuning is None:
        tuning = [40, 45, 50, 55, 59, 64]  # E2 A2 D3 G3 B3 E4

    # Parse time signature
    beats_per_bar, beat_type = _parse_time_sig(time_signature)

    # Noise gate filter
    filtered = _filter_noise(notes, noise_gate)
    if not filtered:
        filtered = notes[:1] if notes else []

    # --- BPM refinement from beats ---
    if beats and len(beats) > 1:
        intervals = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval > 0:
            bpm = 60.0 / avg_interval

    beat_duration = 60.0 / bpm  # seconds per beat

    # --- Quantize notes to bar/beat_pos ---
    note_entries = _quantize_notes(filtered, beats, bpm, beats_per_bar, beat_type)

    # Calculate total bars
    total_bars = 1
    if note_entries:
        total_bars = max(int(e["bar"]) for e in note_entries) + 1
    elif beats:
        total_bars = max(1, len(beats) // beats_per_bar)
    total_bars = max(total_bars, 1)

    # --- Build GP5 Song ---
    song = gp.Song()
    song.title = title or "NextChord"
    song.artist = "NextChord"
    song.tempo = int(bpm)

    # Track setup
    track = song.tracks[0]
    track.name = "Guitar"
    track.channel.instrument = 25  # Acoustic Guitar (steel)
    track.strings = [
        gp.GuitarString(number=i + 1, value=tuning[5 - i])
        for i in range(6)
    ]  # GP format: string 1 = highest (E4), string 6 = lowest (E2)

    # Key signature -- Cメジャー固定（TABではフレット番号が主体）
    key_fifths = 0

    # --- Measure Headers ---
    mh0 = song.measureHeaders[0]
    mh0.timeSignature.numerator = beats_per_bar
    mh0.timeSignature.denominator.value = _beat_type_to_gp_dur(beat_type)
    mh0.keySignature = _fifths_to_gp_key(key_fifths)

    for bar_num in range(1, total_bars):
        mh = gp.MeasureHeader()
        mh.number = bar_num + 1
        mh.start = mh0.start + bar_num * _bar_length(beats_per_bar, beat_type)
        mh.timeSignature.numerator = beats_per_bar
        mh.timeSignature.denominator.value = _beat_type_to_gp_dur(beat_type)
        mh.keySignature = _fifths_to_gp_key(key_fifths)
        song.measureHeaders.append(mh)

    # --- Build Measures ---
    measures = [track.measures[0]]
    for bar_num in range(1, total_bars):
        m = gp.Measure(track, song.measureHeaders[bar_num])
        measures.append(m)
    track.measures = measures

    # --- Divisions per beat / bar ---
    # denom=4: each beat = quarter = DIVISIONS divs
    # denom=8: each beat = eighth = DIVISIONS//2 divs
    divs_per_beat = DIVISIONS if beat_type == 4 else DIVISIONS // 2
    bar_total_divs = beats_per_bar * divs_per_beat  # e.g. 48 for 4/4, 36 for 3/4, 36 for 6/8

    # --- Voice分離 (pitch ベース) ---
    SPLIT_PITCH = 52  # E3

    bars_data = []
    for bar_num in range(total_bars):
        bar_notes = [e for e in note_entries if e["bar"] == bar_num]
        melody = [n for n in bar_notes if not _is_bass(n, SPLIT_PITCH)]
        bass = [n for n in bar_notes if _is_bass(n, SPLIT_PITCH)]
        bars_data.append({"melody": melody, "bass": bass})

    # --- ベース音 pre-pass: snap + 補完 ---
    last_bass_template = None
    for bar_num in range(total_bars):
        bd = bars_data[bar_num]
        if bd["bass"]:
            seen_pitches = set()
            snapped = []
            for b in sorted(bd["bass"], key=lambda x: float(x.get("beat_pos", 0))):
                p = int(b.get("pitch", 60))
                if p not in seen_pitches:
                    seen_pitches.add(p)
                    snap = dict(b)
                    if float(snap.get("beat_pos", 0)) < divs_per_beat:
                        snap["beat_pos"] = 0
                    snapped.append(snap)
            bd["bass"] = snapped
            last_bass_template = snapped
        else:
            if last_bass_template and bd["melody"]:
                bd["bass"] = [dict(t) for t in last_bass_template]

    # --- Fill each measure ---
    for bar_num in range(total_bars):
        m = track.measures[bar_num]
        bd = bars_data[bar_num]
        melody = bd["melody"]
        bass = bd["bass"]

        if not melody and not bass:
            m.voices[0].beats = _divs_to_gp_beats_rest(bar_total_divs, m.voices[0])
            continue

        # Voice 1 (Melody)
        if melody:
            groups1 = _group_by_time(melody, threshold=0.1)
            m.voices[0].beats = _build_voice_beats(
                groups1, m.voices[0], bar_total_divs
            )
        else:
            m.voices[0].beats = _divs_to_gp_beats_rest(bar_total_divs, m.voices[0])

        # Voice 2 (Bass)
        if bass and len(m.voices) > 1:
            groups2 = _group_by_time(bass, threshold=0.1)
            m.voices[1].beats = _build_voice_beats(
                groups2, m.voices[1], bar_total_divs, force_legato=True
            )

    # --- Voice integrity check ---
    for m in track.measures:
        for v in m.voices:
            if not v.beats:
                v.beats = _divs_to_gp_beats_rest(bar_total_divs, v)

    # --- Write to bytes ---
    buf = io.BytesIO()
    gp.write(song, buf)
    return buf.getvalue()


# ===========================================================================
# 量子化: NextChordのnotesをbar/beat_posに変換
# ===========================================================================

def _quantize_notes(
    notes: list,
    beats: list | None,
    bpm: float,
    beats_per_bar: int,
    beat_type: int,
) -> list:
    """
    NextChord notes [{start, end, pitch, string, fret, velocity, ...}] を
    bar / beat_pos 付きエントリに変換する。

    beat_pos は小節先頭からの divisions 単位オフセット。
    """
    if not notes:
        return []

    beat_duration = 60.0 / bpm
    divs_per_beat = DIVISIONS if beat_type == 4 else DIVISIONS // 2
    bar_total_divs = beats_per_bar * divs_per_beat
    bar_duration = beat_duration * beats_per_bar

    # beats配列があればそれを基準にbeat indexを算出
    entries = []
    for n in notes:
        start = float(n.get("start", 0))
        end = float(n.get("end", start + 0.1))
        dur_sec = max(end - start, 0.01)

        # Bar number (0-indexed)
        bar = int(start / bar_duration) if bar_duration > 0 else 0

        # Beat position within bar (in seconds)
        bar_start_sec = bar * bar_duration
        pos_in_bar_sec = start - bar_start_sec

        # Convert to divisions
        if beat_duration > 0:
            beat_pos_divs = int(round(pos_in_bar_sec / beat_duration * DIVISIONS))
        else:
            beat_pos_divs = 0

        # Clamp to bar boundary
        beat_pos_divs = max(0, min(beat_pos_divs, bar_total_divs - 1))

        # Duration in divisions
        dur_divs = max(1, int(round(dur_sec / beat_duration * DIVISIONS)))
        dur_divs = min(dur_divs, bar_total_divs - beat_pos_divs)

        entries.append({
            "bar": bar,
            "beat_pos": beat_pos_divs,
            "duration_divs": dur_divs,
            "pitch": int(n.get("pitch", 60)),
            "string": int(n.get("string", 1)),
            "fret": int(n.get("fret", 0)),
            "velocity": float(n.get("velocity", 0.5)),
            "start": start,
        })

    return entries


# ===========================================================================
# Voice分離
# ===========================================================================

def _is_bass(n: dict, split_pitch: int = 52) -> bool:
    """弦情報があれば弦4-6をベース、なければpitch<=split_pitchでフォールバック"""
    s = int(n.get("string", 0))
    if s >= 4:
        return True
    if s >= 1:
        return False
    return int(n.get("pitch", 60)) <= split_pitch


# ===========================================================================
# 同時打弦グルーピング
# ===========================================================================

def _group_by_time(entries: list, threshold: float = 0.1) -> list:
    """
    同時に鳴っているノートをグループ化する。
    threshold: 秒単位の許容差（startベース）
    """
    if not entries:
        return []

    # start時刻でソート
    sorted_entries = sorted(entries, key=lambda e: float(e.get("start", e.get("beat_pos", 0))))

    groups = []
    current_group = [sorted_entries[0]]

    for i in range(1, len(sorted_entries)):
        t0 = float(current_group[0].get("start", current_group[0].get("beat_pos", 0)))
        t1 = float(sorted_entries[i].get("start", sorted_entries[i].get("beat_pos", 0)))
        if abs(t1 - t0) <= threshold:
            current_group.append(sorted_entries[i])
        else:
            groups.append(current_group)
            current_group = [sorted_entries[i]]

    groups.append(current_group)
    return groups


# ===========================================================================
# GP5 Beat/Note オブジェクト生成
# ===========================================================================

# Valid duration values for post-snap capping
NORMAL_DURS = [48, 36, 24, 18, 12, 9, 6, 3, 2, 1]


def _build_voice_beats(
    groups: list,
    voice,
    bar_total_divs: int,
    force_legato: bool = False,
) -> list:
    """グループ化されたノートから GP Beat リストを構築する。"""
    gp_beats = []
    current_pos = 0

    # 16分音符グリッド (straight)
    snap_grid = list(range(0, bar_total_divs + 1, 3))  # 0,3,6,9,12,...

    for group_idx, group in enumerate(groups):
        raw_pos = int(float(group[0].get("beat_pos", 0)))
        target_pos = min(snap_grid, key=lambda x: abs(x - raw_pos))

        # ── bar-end guard ──
        if current_pos >= bar_total_divs or target_pos >= bar_total_divs:
            break

        # Rest gap before this group
        gap = target_pos - current_pos
        if gap > 0:
            rest_beats = _divs_to_gp_beats_rest(gap, voice)
            gp_beats.extend(rest_beats)
            current_pos = target_pos
        elif gap < 0:
            target_pos = current_pos

        # Note duration
        min_dur = 3  # sixteenth note
        if group_idx + 1 < len(groups):
            next_raw = int(float(groups[group_idx + 1][0].get("beat_pos", 0)))
            next_target = min(snap_grid, key=lambda x: abs(x - next_raw))
            next_target = max(next_target, target_pos + min_dur)
        else:
            next_target = bar_total_divs
        gap_to_next = max(1, min(next_target - target_pos,
                                 bar_total_divs - target_pos))

        # Duration
        if force_legato:
            dur_divs = min(gap_to_next, bar_total_divs - target_pos)
            dur_divs = max(1, dur_divs)
        else:
            dur_divs = int(group[0].get("duration_divs", gap_to_next))
            dur_divs = min(dur_divs, gap_to_next, bar_total_divs - target_pos)
            dur_divs = max(1, dur_divs)

        # Snap to valid durations
        dur_divs = min(NORMAL_DURS, key=lambda x: abs(x - dur_divs))

        # ── Post-snap VALID_DURS cap ──
        remaining_in_bar = bar_total_divs - target_pos
        if dur_divs > remaining_in_bar:
            candidates = [d for d in NORMAL_DURS if d <= remaining_in_bar]
            dur_divs = max(candidates) if candidates else 1

        # ── bar-end guard: beat_pos + dur > bar_total ──
        if target_pos + dur_divs > bar_total_divs:
            dur_divs = bar_total_divs - target_pos
            if dur_divs <= 0:
                break
            candidates = [d for d in NORMAL_DURS if d <= dur_divs]
            dur_divs = max(candidates) if candidates else 1

        # Create beat with all notes in this chord group
        beat = gp.Beat(voice, status=gp.BeatStatus.normal)
        gp_dur, gp_dotted, gp_tuplet = _divs_to_gp_duration(dur_divs)
        beat.duration.value = gp_dur
        beat.duration.isDotted = gp_dotted
        # テクニック (Phase 2 で追加予定) -- 現在はスキップ

        for entry in group:
            string_num = int(entry.get("string", 1))
            fret = int(entry.get("fret", 0))
            note = gp.Note(beat)
            note.value = fret
            note.string = string_num
            note.velocity = _vel_to_gp(entry.get("velocity", 0.5))
            beat.notes.append(note)

        gp_beats.append(beat)

        # ── current_pos の bar_total_divs キャップ ──
        current_pos = target_pos + dur_divs
        current_pos = min(current_pos, bar_total_divs)

    # Trailing rest
    remaining = bar_total_divs - current_pos
    if remaining > 0:
        rest_beats = _divs_to_gp_beats_rest(remaining, voice)
        gp_beats.extend(rest_beats)

    return gp_beats if gp_beats else []


# ===========================================================================
# ヘルパー関数
# ===========================================================================

def _parse_time_sig(ts: str) -> tuple[int, int]:
    """拍子文字列をパースして (beats_per_bar, beat_type) を返す。"""
    if "/" in ts:
        parts = ts.split("/")
        try:
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            pass
    # Fallback defaults
    if ts == "3/4":
        return 3, 4
    elif ts == "6/8":
        return 6, 8
    return 4, 4


def _filter_noise(notes: list, gate: float) -> list:
    """
    velocity閾値による弱音フィルタ。
    gate=0.2 -> velocity 下位 20% のノートをカット。
    同時発音ノート (50ms以内) は保護する。
    """
    if gate <= 0:
        return notes.copy()
    if not notes:
        return []

    import random

    cut_count = int(len(notes) * gate)
    if cut_count >= len(notes):
        cut_count = len(notes) - 1
    if cut_count <= 0:
        return notes.copy()

    # 同時発音ノートをグループ化し、保護対象を特定
    SIMUL_THRESHOLD = 0.05  # 50ms
    sorted_by_time = sorted(
        enumerate(notes),
        key=lambda x: float(x[1].get("start", 0))
    )
    protected_indices = set()
    i = 0
    while i < len(sorted_by_time):
        group = [sorted_by_time[i]]
        j = i + 1
        while j < len(sorted_by_time):
            t_diff = abs(
                float(sorted_by_time[j][1].get("start", 0))
                - float(group[0][1].get("start", 0))
            )
            if t_diff <= SIMUL_THRESHOLD:
                group.append(sorted_by_time[j])
                j += 1
            else:
                break
        if len(group) >= 2:
            for idx, _ in group:
                protected_indices.add(idx)
        i = j

    # velocity でソート（同一velocity内はシャッフル）
    rng = random.Random(42)
    indexed = list(enumerate(notes))
    indexed.sort(key=lambda x: (float(x[1].get("velocity", 0.5)), rng.random()))

    cut_indices = set()
    for idx, _ in indexed:
        if len(cut_indices) >= cut_count:
            break
        if idx not in protected_indices:
            cut_indices.add(idx)

    filtered = [n for i, n in enumerate(notes) if i not in cut_indices]
    return filtered if filtered else [notes[0]]


def _divs_to_gp_duration(divs: int) -> tuple[int, bool, bool]:
    """
    divisions値 (DIVISIONS=12基準) を GP Duration value, isDotted, isTriplet に変換。

    Mapping:
      48 = whole, 24 = half, 12 = quarter, 6 = eighth, 3 = sixteenth
      Dotted: 36 = dotted-half, 18 = dotted-quarter, 9 = dotted-eighth
      Triplet: 8 = triplet-quarter, 4 = triplet-eighth
    """
    exact = {
        48: (gp.Duration.whole, False, False),
        36: (gp.Duration.half, True, False),        # dotted half
        24: (gp.Duration.half, False, False),
        18: (gp.Duration.quarter, True, False),     # dotted quarter
        12: (gp.Duration.quarter, False, False),
        9:  (gp.Duration.eighth, True, False),      # dotted eighth
        8:  (gp.Duration.quarter, False, True),     # triplet quarter
        6:  (gp.Duration.eighth, False, False),
        4:  (gp.Duration.eighth, False, True),      # triplet eighth
        3:  (gp.Duration.sixteenth, False, False),
        2:  (gp.Duration.thirtySecond, False, False),
        1:  (gp.Duration.sixtyFourth, False, False),
    }
    if divs in exact:
        return exact[divs]

    # Nearest match
    best_key = min(exact.keys(), key=lambda k: abs(k - divs))
    return exact[best_key]


def _divs_to_gp_beats_rest(divs: int, voice) -> list:
    """休符 duration を 1つ以上の GP rest beat に分解する。"""
    if divs <= 0:
        return []

    beats_out = []
    remaining = divs

    # Standard durations (largest first)
    std_durs = [48, 36, 24, 18, 12, 9, 6, 3, 2, 1]

    while remaining > 0:
        best = 1
        for d in std_durs:
            if d <= remaining:
                best = d
                break
        gp_dur, gp_dot, gp_trip = _divs_to_gp_duration(best)
        rb = gp.Beat(voice, status=gp.BeatStatus.rest)
        rb.duration.value = gp_dur
        rb.duration.isDotted = gp_dot
        if gp_trip:
            rb.duration.tuplet = gp.Tuplet(enters=3, times=2)
        beats_out.append(rb)
        remaining -= best

    return beats_out


def _vel_to_gp(v) -> int:
    """velocity (0-1 or 0-127) to GP velocity (1-127)."""
    v = float(v)
    if v <= 1.0:
        v = v * 127
    return max(1, min(127, int(v)))


def _beat_type_to_gp_dur(beat_type: int) -> int:
    """beat_type (分母) を GP Duration value に変換。"""
    return {
        1: gp.Duration.whole,
        2: gp.Duration.half,
        4: gp.Duration.quarter,
        8: gp.Duration.eighth,
        16: gp.Duration.sixteenth,
    }.get(beat_type, gp.Duration.quarter)


def _bar_length(beats_per_bar: int, beat_type: int) -> int:
    """GP internal tick length of one bar. Quarter note = 960 ticks."""
    quarter_ticks = 960
    beat_ticks = quarter_ticks * 4 // beat_type
    return beats_per_bar * beat_ticks


def _fifths_to_gp_key(fifths: int) -> gp.KeySignature:
    """fifths値から GP の KeySignature を返す。"""
    mapping = {
        -4: gp.KeySignature.AMajorFlat,
        -3: gp.KeySignature.EMajorFlat,
        -2: gp.KeySignature.BMajorFlat,
        -1: gp.KeySignature.FMajor,
        0: gp.KeySignature.CMajor,
        1: gp.KeySignature.GMajor,
        2: gp.KeySignature.DMajor,
        3: gp.KeySignature.AMajor,
        4: gp.KeySignature.EMajor,
        5: gp.KeySignature.BMajor,
    }
    return mapping.get(fifths, gp.KeySignature.CMajor)
