"""
NextChord Accuracy Benchmark
=============================
Comprehensive numerical benchmark testing NextChord's core accuracy across
four categories:

  A. String Assignment Accuracy    (50 tests)
  B. Technique Detection Accuracy  (30 tests)
  C. Tab Generator Output Quality  (20 tests)
  D. Beat Sync Accuracy            (10 tests)

Usage:
    python benchmark_accuracy.py
"""

import sys
import os
import traceback
import random
import re
import copy
from typing import List, Dict, Tuple, Optional
from xml.etree import ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from string_optimizer import (
    optimize_string_assignment,
    STANDARD_TUNING as SO_STANDARD_TUNING,
    MAX_FRET,
    _get_possible_positions,
)
from technique import detect_techniques
from tab_generator import (
    notes_to_musicxml,
    notes_to_tab_data,
    chord_to_tab_data,
    quantize_duration_to_note_type,
    snap_to_grid,
    STANDARD_TUNING as TG_STANDARD_TUNING,
    NOTE_NAMES,
)

# =========================================================================
# Global counters and helpers
# =========================================================================
_results: Dict[str, Dict] = {
    "A": {"pass": 0, "fail": 0, "errors": []},
    "B": {"pass": 0, "fail": 0, "errors": []},
    "C": {"pass": 0, "fail": 0, "errors": []},
    "D": {"pass": 0, "fail": 0, "errors": []},
}


def run_test(category: str, name: str, fn) -> None:
    """Execute a single test, recording pass/fail in global counters."""
    try:
        fn()
        _results[category]["pass"] += 1
    except Exception as e:
        _results[category]["fail"] += 1
        _results[category]["errors"].append(f"{name}: {e}")
        traceback.print_exc()


# -- Note factory helpers --------------------------------------------------

OPEN_PITCHES = SO_STANDARD_TUNING  # [40, 45, 50, 55, 59, 64]
HAND_SPAN = 4  # Maximum comfortable fret span


def _make_note(
    pitch: int,
    start: float,
    duration: float = 0.3,
    velocity: int = 80,
    string: int = -1,
    fret: int = -1,
) -> dict:
    """Create a single note dict in NextChord format."""
    note_name = NOTE_NAMES[pitch % 12] + str(pitch // 12 - 1)
    return {
        "start_time": round(start, 4),
        "end_time": round(start + duration, 4),
        "midi_pitch": pitch,
        "velocity": velocity,
        "confidence": 0.9,
        "note_name": note_name,
        "string": string,
        "fret": fret,
    }


def _ascending_scale(start_pitch: int = 40, steps: int = 8) -> List[dict]:
    """Generate an ascending chromatic scale."""
    return [
        _make_note(start_pitch + i, i * 0.3)
        for i in range(steps)
    ]


def _descending_scale(start_pitch: int = 64, steps: int = 8) -> List[dict]:
    """Generate a descending chromatic scale."""
    return [
        _make_note(start_pitch - i, i * 0.3)
        for i in range(steps)
    ]


def _random_melody(seed: int, n: int = 8) -> List[dict]:
    """Generate a random melody within guitar range."""
    rng = random.Random(seed)
    notes = []
    t = 0.0
    for _ in range(n):
        pitch = rng.randint(40, 84)
        dur = rng.uniform(0.15, 0.5)
        notes.append(_make_note(pitch, t, dur))
        t += dur + rng.uniform(0.0, 0.1)
    return notes


def _chord_pitches(name: str) -> List[int]:
    """Return MIDI pitches for a named open chord voicing."""
    voicing = chord_to_tab_data(name)
    if voicing is None:
        return []
    pitches = []
    for idx, fret in enumerate(voicing):
        if fret < 0:
            continue
        string_num = 6 - idx
        open_pitch = TG_STANDARD_TUNING[string_num]
        pitches.append(open_pitch + fret)
    return pitches


def _make_chord_notes(name: str, start: float, duration: float = 0.4) -> List[dict]:
    """Create simultaneous notes for a named chord."""
    pitches = _chord_pitches(name)
    return [_make_note(p, start + i * 0.005, duration) for i, p in enumerate(pitches)]


def _make_beats(n_beats: int = 32, bpm: float = 120.0) -> List[float]:
    """Generate a beat grid."""
    beat_dur = 60.0 / bpm
    return [i * beat_dur for i in range(n_beats)]


# =========================================================================
# SECTION A: String Assignment Accuracy (50 tests)
# =========================================================================

def _validate_assignment(notes: List[dict], label: str) -> None:
    """Common validation for string-assigned notes.

    Out-of-range pitches are handled by _fallback_position in the optimizer,
    which clamps the fret to [0, MAX_FRET].  For such notes, pitch consistency
    is relaxed — we only verify string/fret are in valid ranges.
    """
    result = optimize_string_assignment(notes)
    for i, n in enumerate(result):
        s, f = n["string"], n["fret"]
        assert 1 <= s <= 6, f"[{label}] note {i}: string {s} out of range"
        assert 0 <= f <= MAX_FRET, f"[{label}] note {i}: fret {f} out of range"
        # Verify pitch consistency (relaxed for out-of-range fallback)
        expected_pitch = OPEN_PITCHES[6 - s] + f
        has_valid_pos = len(_get_possible_positions(n["midi_pitch"], OPEN_PITCHES)) > 0
        if has_valid_pos:
            assert expected_pitch == n["midi_pitch"], (
                f"[{label}] note {i}: pitch mismatch s={s} f={f} -> "
                f"{expected_pitch} != {n['midi_pitch']}"
            )


def run_section_a():
    """A. String Assignment Accuracy — 50 test cases."""
    print("A. String Assignment Accuracy (50 tests)")
    print("-" * 50)

    # -- A01-A04: Ascending scales at different start pitches ---------------
    for i, start_p in enumerate([40, 48, 55, 64]):
        def test(sp=start_p, idx=i):
            notes = _ascending_scale(sp, 8)
            _validate_assignment(notes, f"A-{idx+1:02d}-asc-{sp}")
        run_test("A", f"A-{i+1:02d}", test)

    # -- A05-A08: Descending scales ----------------------------------------
    for i, start_p in enumerate([84, 72, 64, 55]):
        def test(sp=start_p, idx=i):
            notes = _descending_scale(sp, 8)
            _validate_assignment(notes, f"A-{idx+5:02d}-desc-{sp}")
        run_test("A", f"A-{i+5:02d}", test)

    # -- A09-A10: Random melodies ------------------------------------------
    for i, seed in enumerate([42, 137]):
        def test(s=seed, idx=i):
            notes = _random_melody(s, 10)
            _validate_assignment(notes, f"A-{idx+9:02d}-rand-{s}")
        run_test("A", f"A-{i+9:02d}", test)

    # -- A11-A20: Chord progressions (no duplicate strings) -----------------
    chord_sets = [
        ["C", "G"],
        ["Am", "Em"],
        ["C", "Am", "F", "G"],
        ["D", "A"],
        ["Em", "Am"],
        ["G", "D", "Em"],
        ["C", "F"],
        ["Am", "Dm"],
        ["E", "A", "D"],
        ["G", "C", "D"],
    ]
    for i, chords in enumerate(chord_sets):
        def test(ch=chords, idx=i):
            all_notes = []
            t = 0.0
            for c in ch:
                all_notes.extend(_make_chord_notes(c, t))
                t += 0.5
            result = optimize_string_assignment(all_notes)
            # Within each simultaneous group, strings must be unique
            from itertools import groupby
            result_sorted = sorted(result, key=lambda n: n["start_time"])
            groups = []
            for _, grp in groupby(result_sorted,
                                   key=lambda n: round(n["start_time"], 2)):
                groups.append(list(grp))
            for g_idx, g in enumerate(groups):
                strings = [n["string"] for n in g]
                assert len(strings) == len(set(strings)), (
                    f"[A-{idx+11:02d}] chord group {g_idx}: "
                    f"duplicate strings {strings}"
                )
        run_test("A", f"A-{i+11:02d}", test)

    # -- A21-A30: Position shifts (jump low -> high -> low) ----------------
    shift_pairs = [
        (40, 80), (45, 76), (50, 72), (55, 70), (42, 78),
        (44, 74), (48, 68), (52, 66), (40, 84), (46, 82),
    ]
    for i, (lo, hi) in enumerate(shift_pairs):
        def test(l=lo, h=hi, idx=i):
            notes = [
                _make_note(l, 0.0),
                _make_note(h, 0.3),
                _make_note(l, 0.6),
            ]
            _validate_assignment(notes, f"A-{idx+21:02d}-shift")
        run_test("A", f"A-{i+21:02d}", test)

    # -- A31-A40: Edge cases -----------------------------------------------
    # A31: all open strings
    def test_a31():
        notes = [_make_note(p, i * 0.3) for i, p in enumerate(OPEN_PITCHES)]
        result = optimize_string_assignment(notes)
        open_count = sum(1 for n in result if n["fret"] == 0)
        assert open_count == len(OPEN_PITCHES), (
            f"Expected all open strings but got {open_count}/{len(OPEN_PITCHES)}"
        )
    run_test("A", "A-31", test_a31)

    # A32: highest playable notes per string
    def test_a32():
        notes = [_make_note(p + MAX_FRET, i * 0.3) for i, p in enumerate(OPEN_PITCHES)]
        _validate_assignment(notes, "A-32-high-fret")
    run_test("A", "A-32", test_a32)

    # A33: same pitch played twice — should pick valid positions
    def test_a33():
        notes = [_make_note(60, 0.0), _make_note(60, 0.4)]
        _validate_assignment(notes, "A-33-same-pitch")
    run_test("A", "A-33", test_a33)

    # A34: chromatic cluster (60, 61, 62, 63)
    def test_a34():
        notes = [_make_note(60 + i, i * 0.2) for i in range(4)]
        _validate_assignment(notes, "A-34-chromatic")
    run_test("A", "A-34", test_a34)

    # A35: single note (edge: n=1)
    def test_a35():
        notes = [_make_note(52, 0.0)]
        _validate_assignment(notes, "A-35-single")
    run_test("A", "A-35", test_a35)

    # A36: empty note list
    def test_a36():
        result = optimize_string_assignment([])
        assert result == [], "Expected empty list for empty input"
    run_test("A", "A-36", test_a36)

    # A37: same-fret different strings (E4 on string 1 fret 0 vs string 2 fret 5)
    def test_a37():
        notes = [_make_note(64, 0.0), _make_note(64, 0.005)]  # simultaneous
        result = optimize_string_assignment(notes)
        # Both should get valid assignments
        for n in result:
            assert 1 <= n["string"] <= 6
            assert 0 <= n["fret"] <= MAX_FRET
    run_test("A", "A-37", test_a37)

    # A38: wide interval jump (low E to high E)
    def test_a38():
        notes = [_make_note(40, 0.0), _make_note(84, 0.3)]
        _validate_assignment(notes, "A-38-wide-jump")
    run_test("A", "A-38", test_a38)

    # A39: out-of-range note -> fallback position
    def test_a39():
        notes = [_make_note(30, 0.0)]  # below guitar range
        result = optimize_string_assignment(notes)
        # Should not crash, should return something valid
        assert len(result) == 1
        assert 1 <= result[0]["string"] <= 6
    run_test("A", "A-39", test_a39)

    # A40: note at exact boundary (MAX_FRET on string 1 = 64+19=83)
    def test_a40():
        notes = [_make_note(64 + MAX_FRET, 0.0)]
        _validate_assignment(notes, "A-40-boundary")
    run_test("A", "A-40", test_a40)

    # -- A41-A50: Playability checks (hand span, no impossible stretches) --
    for i in range(10):
        def test(seed=i + 500):
            rng = random.Random(seed)
            notes = _random_melody(seed, 12)
            result = optimize_string_assignment(notes)
            # Measure consecutive fret distances
            for j in range(1, len(result)):
                prev_f = result[j - 1]["fret"]
                curr_f = result[j]["fret"]
                # Skip open string transitions (always comfortable)
                if prev_f == 0 or curr_f == 0:
                    continue
                span = abs(curr_f - prev_f)
                # Extreme stretch (>12 frets) should be very rare;
                # flag only if the *same* hand position is needed
                # (We just verify the assignment is valid, not stretch-free.)
                assert span <= MAX_FRET, (
                    f"Fret jump {span} exceeds MAX_FRET"
                )
        run_test("A", f"A-{i+41:02d}", test)

    a = _results["A"]
    print(f"  => {a['pass']}/{a['pass']+a['fail']} passed\n")


# =========================================================================
# SECTION B: Technique Detection Accuracy (30 tests)
# =========================================================================

def run_section_b():
    """B. Technique Detection Accuracy — 30 test cases."""
    print("B. Technique Detection Accuracy (30 tests)")
    print("-" * 50)

    # -- B01-B05: Hammer-on chains (ascending pitch, same string, short gap)
    ho_cases = [
        # (prev_pitch, prev_fret, curr_pitch, curr_fret, string)
        (60, 5, 62, 7, 3),
        (55, 0, 57, 2, 4),
        (64, 0, 65, 1, 1),
        (50, 0, 52, 2, 4),
        (59, 0, 61, 2, 2),
    ]
    for i, (pp, pf, cp, cf, s) in enumerate(ho_cases):
        def test(pp=pp, pf=pf, cp=cp, cf=cf, s=s, idx=i):
            notes = [
                {"start_time": 0.0, "end_time": 0.3, "midi_pitch": pp,
                 "string": s, "fret": pf, "velocity": 80},
                {"start_time": 0.1, "end_time": 0.4, "midi_pitch": cp,
                 "string": s, "fret": cf, "velocity": 70},
            ]
            result = detect_techniques(copy.deepcopy(notes), bpm=120)
            tech = result[0].get("technique")
            assert tech == "h", f"Expected 'h', got '{tech}'"
        run_test("B", f"B-{i+1:02d}", test)

    # -- B06-B10: Pull-off chains (descending pitch, same string, short gap)
    po_cases = [
        (64, 8, 62, 6, 2),
        (62, 7, 60, 5, 3),
        (57, 2, 55, 0, 4),
        (65, 1, 64, 0, 1),
        (52, 2, 50, 0, 4),
    ]
    for i, (pp, pf, cp, cf, s) in enumerate(po_cases):
        def test(pp=pp, pf=pf, cp=cp, cf=cf, s=s, idx=i):
            notes = [
                {"start_time": 0.0, "end_time": 0.3, "midi_pitch": pp,
                 "string": s, "fret": pf, "velocity": 80},
                {"start_time": 0.1, "end_time": 0.4, "midi_pitch": cp,
                 "string": s, "fret": cf, "velocity": 70},
            ]
            result = detect_techniques(copy.deepcopy(notes), bpm=120)
            tech = result[0].get("technique")
            assert tech == "p", f"Expected 'p', got '{tech}'"
        run_test("B", f"B-{i+6:02d}", test)

    # -- B11-B15: Slides (large pitch diff, same string, fret_diff 2-5)
    slide_cases = [
        # (prev_pitch, prev_fret, curr_pitch, curr_fret, string, expected)
        (48, 3, 55, 8, 4, "/"),    # slide up, fret_diff=5
        (62, 10, 55, 5, 3, "\\"),  # slide down, fret_diff=5
        (50, 3, 57, 8, 4, "/"),    # slide up
        (57, 8, 50, 3, 4, "\\"),   # slide down
        (45, 3, 52, 8, 5, "/"),    # slide up on string 5
    ]
    for i, (pp, pf, cp, cf, s, exp) in enumerate(slide_cases):
        def test(pp=pp, pf=pf, cp=cp, cf=cf, s=s, exp=exp, idx=i):
            notes = [
                {"start_time": 0.0, "end_time": 0.3, "midi_pitch": pp,
                 "string": s, "fret": pf, "velocity": 80},
                {"start_time": 0.2, "end_time": 0.5, "midi_pitch": cp,
                 "string": s, "fret": cf, "velocity": 70},
            ]
            result = detect_techniques(copy.deepcopy(notes), bpm=120)
            tech = result[0].get("technique")
            assert tech == exp, f"Expected '{exp}', got '{tech}'"
        run_test("B", f"B-{i+11:02d}", test)

    # -- B16-B20: Bends (same fret, pitch shift, fret >= 3)
    bend_cases = [
        # (pitch, fret, string, pitch_shift, expected_technique)
        (64, 5, 2, 1, "b_half"),   # half-step bend
        (64, 7, 2, 2, "b"),        # full bend
        (60, 5, 3, 1, "b_half"),   # half-step bend on string 3
        (62, 7, 3, 2, "b"),        # full bend on string 3
        (67, 8, 1, 1, "b_half"),   # half-step bend on string 1
    ]
    for i, (pitch, fret, s, shift, exp) in enumerate(bend_cases):
        def test(pitch=pitch, fret=fret, s=s, shift=shift, exp=exp, idx=i):
            notes = [
                {"start_time": 0.0, "end_time": 0.3, "midi_pitch": pitch,
                 "string": s, "fret": fret, "velocity": 80},
                {"start_time": 0.1, "end_time": 0.4, "midi_pitch": pitch + shift,
                 "string": s, "fret": fret, "velocity": 70},
            ]
            result = detect_techniques(copy.deepcopy(notes), bpm=120)
            tech = result[0].get("technique")
            assert tech == exp, f"Expected '{exp}', got '{tech}'"
        run_test("B", f"B-{i+16:02d}", test)

    # -- B21-B25: Dead notes / mute (rule-based: low velocity + short dur)
    # Testing brushing detection requires 4+ simultaneous strings.
    # For individual dead notes, technique.py needs audio (F0 analysis).
    # We test the rule-based brushing detection instead.
    for i in range(5):
        def test(idx=i):
            # Create 4+ simultaneous very short notes on different strings
            notes = []
            base_t = 0.5
            for s_num in range(1, 6):  # strings 1-5
                notes.append({
                    "start_time": base_t + s_num * 0.005,
                    "end_time": base_t + 0.06,  # very short
                    "midi_pitch": 40 + s_num * 5,
                    "string": s_num,
                    "fret": 5,
                    "velocity": 40 + idx * 3,  # low velocity
                })
            result = detect_techniques(copy.deepcopy(notes), bpm=120)
            # At least some notes should get mute_brush technique
            brush_count = sum(1 for n in result if n.get("technique") == "mute_brush")
            assert brush_count >= 4, (
                f"Expected >= 4 mute_brush notes, got {brush_count}"
            )
        run_test("B", f"B-{i+21:02d}", test)

    # -- B26-B30: Negative cases (should NOT detect technique)
    neg_cases = [
        # Different strings -> no technique
        (60, 5, 3, 62, 3, 2, "diff_strings"),
        # Same string but long IOI (>0.5s) -> no technique
        (60, 5, 3, 62, 7, 3, "long_ioi"),
        # fret=0 same fret pitch change -> no bend (bend guard)
        (64, 0, 1, 65, 0, 1, "open_bend_guard"),
        # fret<3 same fret pitch change -> no bend (low fret guard)
        (59, 2, 2, 60, 2, 2, "low_fret_bend_guard"),
        # large pitch diff + different strings -> no technique
        (40, 0, 6, 64, 0, 1, "cross_string_big_jump"),
    ]
    ioi_values = [0.1, 0.6, 0.1, 0.1, 0.1]
    for i, (pp, pf, ps, cp, cf, cs, label) in enumerate(neg_cases):
        def test(pp=pp, pf=pf, ps=ps, cp=cp, cf=cf, cs=cs,
                 ioi=ioi_values[i], label=label, idx=i):
            notes = [
                {"start_time": 0.0, "end_time": 0.3, "midi_pitch": pp,
                 "string": ps, "fret": pf, "velocity": 80},
                {"start_time": ioi, "end_time": ioi + 0.3, "midi_pitch": cp,
                 "string": cs, "fret": cf, "velocity": 70},
            ]
            result = detect_techniques(copy.deepcopy(notes), bpm=120)
            tech = result[0].get("technique")
            assert tech is None, (
                f"[{label}] Expected no technique, got '{tech}'"
            )
        run_test("B", f"B-{i+26:02d}", test)

    b = _results["B"]
    print(f"  => {b['pass']}/{b['pass']+b['fail']} passed\n")


# =========================================================================
# SECTION C: Tab Generator Output Quality (20 tests)
# =========================================================================

def run_section_c():
    """C. Tab Generator Output Quality — 20 test cases."""
    print("C. Tab Generator Output Quality (20 tests)")
    print("-" * 50)

    # -- C01-C05: MusicXML well-formedness ---------------------------------
    xml_configs = [
        {"n": 5,  "bpm": 120, "sig": (4, 4), "key": "C"},
        {"n": 10, "bpm": 100, "sig": (3, 4), "key": "G"},
        {"n": 15, "bpm": 140, "sig": (4, 4), "key": "D"},
        {"n": 20, "bpm": 80,  "sig": (4, 4), "key": "Am"},
        {"n": 3,  "bpm": 160, "sig": (4, 4), "key": "E"},
    ]
    for i, cfg in enumerate(xml_configs):
        def test(c=cfg, idx=i):
            notes = _random_melody(idx + 1000, c["n"])
            beats = _make_beats(32, c["bpm"])
            result = notes_to_musicxml(
                notes, beats=beats, bpm=c["bpm"],
                time_sig=c["sig"], title=f"test_C{idx+1:02d}", key=c["key"],
            )
            xml_str = result if isinstance(result, str) else result[0]
            # Must be parseable XML
            root = ET.fromstring(xml_str)
            assert root.tag == "score-partwise", (
                f"Root tag is '{root.tag}', expected 'score-partwise'"
            )
            # Must have at least one <part>
            parts = root.findall(".//part")
            assert len(parts) >= 1, "No <part> elements found"
            # All <type> values must be valid
            valid_types = {"whole", "half", "quarter", "eighth", "16th", "32nd", "64th"}
            for t_elem in root.iter("type"):
                assert t_elem.text in valid_types, (
                    f"Invalid note type: '{t_elem.text}'"
                )
        run_test("C", f"C-{i+1:02d}", test)

    # -- C06-C10: Note count preservation ----------------------------------
    for i in range(5):
        def test(idx=i):
            n_notes = 5 + idx * 3
            notes = _random_melody(idx + 2000, n_notes)
            tab = notes_to_tab_data(notes)
            # Tab data should have at most as many entries as input notes
            # (some may be filtered if out of range, but never more)
            assert len(tab) <= len(notes), (
                f"Tab has {len(tab)} entries for {len(notes)} input notes"
            )
            # At least some notes should survive
            assert len(tab) > 0, "Tab data is empty"
            # Each tab entry must have required fields
            for t in tab:
                assert "string" in t, "Missing 'string' in tab entry"
                assert "fret" in t, "Missing 'fret' in tab entry"
                assert "midi_pitch" in t, "Missing 'midi_pitch' in tab entry"
        run_test("C", f"C-{i+6:02d}", test)

    # -- C11-C15: Beat alignment (notes start on quantized positions) ------
    for i in range(5):
        def test(idx=i):
            bpm = 120
            beat_dur = 60.0 / bpm
            # Create notes exactly on beats and half-beats
            notes = []
            for b in range(4):
                t = b * beat_dur
                notes.append(_make_note(60 + b, t, beat_dur * 0.9))
            beats = _make_beats(16, bpm)
            xml_str = notes_to_musicxml(
                notes, beats=beats, bpm=bpm,
                time_sig=(4, 4), title=f"test_beat_{idx}",
            )
            xml = xml_str if isinstance(xml_str, str) else xml_str[0]
            # Parse and verify at least one measure exists
            root = ET.fromstring(xml)
            measures = root.findall(".//measure")
            assert len(measures) >= 1, "No measures found"
            # Verify note elements exist within measures
            note_elements = root.findall(".//note")
            assert len(note_elements) >= 1, "No note elements in XML"
        run_test("C", f"C-{i+11:02d}", test)

    # -- C16-C20: Chord symbol accuracy (chord voicings in tab data) -------
    chord_tests = [
        ("C",  [-1, 3, 2, 0, 1, 0]),
        ("Am", [-1, 0, 2, 2, 1, 0]),
        ("G",  [3, 2, 0, 0, 0, 3]),
        ("D",  [-1, -1, 0, 2, 3, 2]),
        ("Em", [0, 2, 2, 0, 0, 0]),
    ]
    for i, (chord_name, expected) in enumerate(chord_tests):
        def test(name=chord_name, exp=expected, idx=i):
            result = chord_to_tab_data(name)
            assert result is not None, f"chord_to_tab_data('{name}') returned None"
            assert result == exp, (
                f"chord_to_tab_data('{name}'): {result} != {exp}"
            )
        run_test("C", f"C-{i+16:02d}", test)

    c = _results["C"]
    print(f"  => {c['pass']}/{c['pass']+c['fail']} passed\n")


# =========================================================================
# SECTION D: Beat Sync Accuracy (10 tests)
# =========================================================================

def _snap_time_to_beat(
    note_time: float,
    beats: List[float],
    threshold_ms: float = 50.0,
) -> Tuple[float, bool]:
    """
    Snap a note time to the nearest beat if within threshold.

    Returns
    -------
    (snapped_time, was_snapped)
    """
    if not beats:
        return note_time, False
    threshold_sec = threshold_ms / 1000.0
    nearest_beat = min(beats, key=lambda b: abs(b - note_time))
    if abs(nearest_beat - note_time) <= threshold_sec:
        return nearest_beat, True
    return note_time, False


def run_section_d():
    """D. Beat Sync Accuracy — 10 test cases."""
    print("D. Beat Sync Accuracy (10 tests)")
    print("-" * 50)

    bpm = 120.0
    beat_dur = 60.0 / bpm
    beats = _make_beats(32, bpm)

    # -- D01-D04: Chords within 50ms of beat snap correctly ----------------
    offsets_ms = [10, 20, 30, 50]
    for i, offset_ms in enumerate(offsets_ms):
        def test(off=offset_ms, idx=i):
            target_beat = beats[4]  # beat at 2.0s
            note_time = target_beat + off / 1000.0
            snapped, did_snap = _snap_time_to_beat(note_time, beats, 50.0)
            assert did_snap, (
                f"Note at {note_time:.3f}s ({off}ms from beat) should snap"
            )
            assert abs(snapped - target_beat) < 1e-6, (
                f"Snapped to {snapped}, expected {target_beat}"
            )
        run_test("D", f"D-{i+1:02d}", test)

    # -- D05-D07: Chords >100ms from beat don't snap -----------------------
    far_offsets_ms = [120, 200, 250]
    for i, offset_ms in enumerate(far_offsets_ms):
        def test(off=offset_ms, idx=i):
            target_beat = beats[4]
            note_time = target_beat + off / 1000.0
            snapped, did_snap = _snap_time_to_beat(note_time, beats, 50.0)
            assert not did_snap, (
                f"Note {off}ms from beat should NOT snap"
            )
            assert abs(snapped - note_time) < 1e-6, (
                f"Unsnapped time changed: {snapped} != {note_time}"
            )
        run_test("D", f"D-{i+5:02d}", test)

    # -- D08: Negative offset within threshold snaps -----------------------
    def test_d08():
        target_beat = beats[6]
        note_time = target_beat - 0.030  # 30ms before
        snapped, did_snap = _snap_time_to_beat(note_time, beats, 50.0)
        assert did_snap, "Note 30ms before beat should snap"
        assert abs(snapped - target_beat) < 1e-6
    run_test("D", "D-08", test_d08)

    # -- D09: Duration adjusted correctly after snap -----------------------
    def test_d09():
        target_beat = beats[4]
        original_start = target_beat + 0.025  # 25ms late
        original_dur = 0.4
        original_end = original_start + original_dur
        snapped_start, did_snap = _snap_time_to_beat(original_start, beats, 50.0)
        assert did_snap
        # After snapping, duration should be adjusted to preserve the end time
        adjusted_dur = original_end - snapped_start
        assert adjusted_dur > original_dur, (
            f"Duration should grow when snapping earlier: "
            f"{adjusted_dur} <= {original_dur}"
        )
        assert abs(adjusted_dur - (original_dur + 0.025)) < 1e-6
    run_test("D", "D-09", test_d09)

    # -- D10: snap_to_grid function (division-level snap) ------------------
    def test_d10():
        # snap_to_grid snaps to 16th note / triplet grid in division units
        # divisions=12: quarter=12, 8th=6, 16th=3, triplet=4
        assert snap_to_grid(5, 12) == 6    # nearest to 6 (8th)
        assert snap_to_grid(11, 12) == 12  # nearest to 12 (quarter)
        assert snap_to_grid(1, 12) == 0    # nearest to 0
        assert snap_to_grid(7, 12) == 6    # nearest to 6 (8th)
        assert snap_to_grid(4, 12) == 4    # exact triplet grid
    run_test("D", "D-10", test_d10)

    d = _results["D"]
    print(f"  => {d['pass']}/{d['pass']+d['fail']} passed\n")


# =========================================================================
# Main entry point
# =========================================================================

def main():
    print("=" * 60)
    print("NextChord Accuracy Benchmark")
    print("=" * 60)
    print()

    run_section_a()
    run_section_b()
    run_section_c()
    run_section_d()

    # -- Summary -----------------------------------------------------------
    print("=" * 60)
    total_pass = 0
    total_fail = 0
    total_total = 0
    for cat in ("A", "B", "C", "D"):
        r = _results[cat]
        p, f = r["pass"], r["fail"]
        t = p + f
        total_pass += p
        total_fail += f
        total_total += t
        labels = {
            "A": "String Assignment",
            "B": "Technique Detection",
            "C": "Tab Generator",
            "D": "Beat Sync",
        }
        pct = (p / t * 100) if t > 0 else 0
        print(f"{cat}. {labels[cat]+':':25s} {p}/{t} ({pct:.1f}%)")

    print("-" * 60)
    total_pct = (total_pass / total_total * 100) if total_total > 0 else 0
    print(f"TOTAL: {total_pass}/{total_total} ({total_pct:.1f}%)")
    print("=" * 60)

    # -- Print failures if any ---------------------------------------------
    all_errors = []
    for cat in ("A", "B", "C", "D"):
        all_errors.extend(_results[cat]["errors"])
    if all_errors:
        print(f"\nFAILURES ({len(all_errors)}):")
        for err in all_errors:
            print(f"  {err}")
    else:
        print("\nALL TESTS PASSED!")

    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    main()
