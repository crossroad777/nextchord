"""
string_optimizer.py -- Advanced Viterbi DP string/fret assignment
=================================================================
Optimally assign (string, fret) pairs to a sequence of MIDI notes
using multi-attribute cost functions and dynamic programming.

Algorithm foundation (ported from SoloTab's string_assigner.py):
  - Viterbi DP: Global optimal path search across the full phrase
  - Multi-attribute cost: position / transition / ergonomic / timbre
  - Position-dependent fret span: low=3, mid=4, high=5 fret max span
  - Chord/polyphonic processing: combinatorial (string, fret) scoring
  - Minimax post-processing: minimize the MAXIMUM single-transition cost
  - IOI constraint: limit fret movement speed to ~12 frets/sec
  - 40+ tuning presets for alternate tunings

Guitar fretboard theory:
  - 1 position = 4-fret width (index to pinky finger)
  - Fret span > position-dependent max is physically unplayable
  - String 2-3 interval is 4 semitones (others are 5 semitones)
  - Sweet spot: frets 0-9
  - Multiple positions for same pitch -> Viterbi DP picks global optimum

NextChord note format: {start, end, pitch, string, fret, velocity,
                        confidence, technique}
Backward compatible: also accepts {midi_pitch, start_time, end_time, ...}
"""

from typing import List, Dict, Optional, Tuple, Union
from itertools import product as iter_product
from collections import Counter
import math

# =========================================================================
# Tuning Definitions (40+ presets)
# =========================================================================
# Each tuning: [6th_string, 5th, 4th, 3rd, 2nd, 1st] as MIDI note numbers
# Standard: E2=40, A2=45, D3=50, G3=55, B3=59, E4=64

STANDARD_TUNING: List[int] = [40, 45, 50, 55, 59, 64]

TUNINGS: Dict[str, List[int]] = {
    # --- Standard family ---
    "standard":       [40, 45, 50, 55, 59, 64],  # E A D G B E
    "half_down":      [39, 44, 49, 54, 58, 63],  # Eb Ab Db Gb Bb Eb
    "full_step_down": [38, 43, 48, 53, 57, 62],  # D G C F A D
    "1half_down":     [37, 42, 47, 52, 56, 61],  # Db Gb B E Ab Db

    # --- Drop tunings ---
    "drop_d":         [38, 45, 50, 55, 59, 64],  # D A D G B E
    "drop_c_sharp":   [37, 44, 49, 54, 58, 63],  # C# Ab Db Gb Bb Eb
    "drop_c":         [36, 43, 48, 53, 57, 62],  # C G C F A D
    "drop_b":         [35, 42, 47, 52, 56, 61],  # B Gb B E Ab Db
    "double_drop_d":  [38, 45, 50, 55, 59, 62],  # D A D G B D

    # --- DADGAD family (Celtic / Oshio Kotaro) ---
    "dadgad":         [38, 45, 50, 55, 57, 62],  # D A D G A D
    "dadgac":         [38, 45, 50, 55, 57, 60],  # D A D G A C
    "dadgae":         [38, 45, 50, 55, 57, 64],  # D A D G A E
    "dadead":         [38, 45, 50, 52, 57, 62],  # D A D E A D
    "cgdgad":         [36, 43, 50, 55, 57, 62],  # C G D G A D
    "cgdgbd":         [36, 43, 50, 55, 59, 62],  # C G D G B D
    "dadfad":         [38, 45, 50, 54, 57, 62],  # D A D F# A D (Open D variant)
    "daddad":         [38, 45, 50, 50, 57, 62],  # D A D D A D

    # --- Open Major tunings ---
    "open_d":         [38, 45, 50, 54, 57, 62],  # D A D F# A D
    "open_e":         [40, 47, 52, 56, 59, 64],  # E B E G# B E
    "open_g":         [38, 43, 50, 55, 59, 62],  # D G D G B D
    "open_a":         [40, 45, 52, 57, 61, 64],  # E A E A C# E
    "open_c":         [36, 43, 48, 55, 60, 64],  # C G C G C E
    "open_c6":        [36, 45, 48, 55, 60, 64],  # C A C G C E

    # --- Open Minor tunings ---
    "open_dm":        [38, 45, 50, 53, 57, 62],  # D A D F A D
    "open_em":        [40, 47, 52, 55, 59, 64],  # E B E G B E
    "open_gm":        [38, 43, 50, 55, 58, 62],  # D G D G Bb D
    "open_am":        [40, 45, 52, 57, 60, 64],  # E A E A C E
    "open_cm":        [36, 43, 48, 55, 60, 63],  # C G C G C Eb

    # --- Nashville / New Standard ---
    "nashville":      [52, 57, 62, 67, 71, 76],  # E3 A3 D4 G4 B4 E5
    "new_standard":   [36, 43, 50, 57, 62, 67],  # C G D A E B (Fripp)

    # --- Oshio Kotaro specials ---
    "oshio_wind":     [38, 45, 50, 55, 57, 62],  # DADGAD (Wind Song etc.)
    "oshio_fight":    [38, 43, 50, 55, 59, 62],  # DGDGBD = Open G
    "oshio_landscape":[36, 43, 50, 55, 57, 62],  # CGDGAD

    # --- Andy McKee / Antoine Dufour / Michael Hedges ---
    "cgcgce":         [36, 43, 48, 55, 60, 64],  # C G C G C E = Open C
    "cgcgcg":         [36, 43, 48, 55, 60, 67],  # C G C G C G
    "bebebe":         [35, 40, 47, 52, 59, 64],  # B E B E B E
    "dadaad":         [38, 45, 50, 57, 57, 62],  # D A D A A D
    "cgdgbe":         [36, 43, 50, 55, 59, 64],  # C G D G B E

    # --- Eb family (half-step-down variants) ---
    "eb_drop_db":     [37, 44, 49, 54, 58, 63],  # Db Ab Db Gb Bb Eb
}


MAX_FRET: int = 19  # Practical fret range for acoustic guitar

POSITION_WIDTH: int = 4  # One hand position spans 4 frets


# =========================================================================
# Cost Weights
# =========================================================================
WEIGHTS: Dict[str, float] = {
    # --- Position costs ---
    "w_fret_height":          0.05,   # Per-fret height cost
    "w_high_fret_extra":      4.5,    # Extra cost above fret 9
    "w_low_string_high_fret": 1.5,    # Multiplier for low strings at high frets
    "w_sweet_spot_bonus":    -1.0,    # Bonus for frets 0-9
    "w_low_fret_bonus":      -3.0,    # Extra bonus for frets 1-4

    # --- Transition costs ---
    "w_movement":             8.0,    # Fret movement cost (proportional to distance)
    "w_position_shift":      50.0,    # Extra cost for crossing position boundary (>4f)
    "w_string_switch":        2.0,    # String switch cost (proportional to distance)
    "w_same_string_repeat":   5.5,    # Same-string consecutive penalty (PIMA constraint)

    # --- Ergonomic costs ---
    "w_fret_span":          100.0,    # Chord fret span cost
    "w_unplayable":       10000.0,    # Physically impossible fingering
    "w_adjacent_stretch":    30.0,    # Adjacent string stretch penalty (>3f gap)
    "w_too_many_fingers":  5000.0,    # >4 simultaneous fretted notes (no barre)

    # --- Timbre costs ---
    "w_open_string_bonus":  -15.0,    # Open string bonus
    "w_open_match_bonus":    -5.0,    # Bonus for pitches only playable as open string
    "w_barre_bonus":         -5.0,    # Barre chord bonus (per extra string)

    # --- Fingerstyle voice separation ---
    "w_bass_low_string":    -20.0,    # Bass on low strings (4-6) bonus
    "w_melody_high_string": -15.0,    # Melody on high strings (1-3) bonus
    "w_bass_wrong_string":   25.0,    # Bass on high strings penalty
}


# =========================================================================
# Position-dependent span constraints
# =========================================================================

def _get_max_span(fret: int) -> int:
    """Return the maximum fret span a hand can cover at a given position.

    At low frets the physical distance between frets is wider, so the
    reachable span is smaller.  At high frets the spacing narrows,
    allowing a wider span.

    Returns
    -------
    int
        3 for frets 0-3, 4 for frets 4-9, 5 for frets 10+.
    """
    if fret <= 3:
        return 3
    elif fret <= 9:
        return 4
    else:
        return 5


# =========================================================================
# Candidate enumeration
# =========================================================================

def _get_possible_positions(
    pitch: int,
    tuning: List[int],
    max_fret: int = MAX_FRET,
) -> List[Tuple[int, int]]:
    """Return all (string, fret) candidates for a MIDI pitch.

    Parameters
    ----------
    pitch : int
        MIDI note number.
    tuning : list[int]
        Open-string MIDI pitches [6th, 5th, 4th, 3rd, 2nd, 1st].
    max_fret : int
        Maximum fret number.

    Returns
    -------
    list of (string_number, fret_number)
        string_number: 1-6 (1 = highest string, 6 = lowest string).
    """
    positions: List[Tuple[int, int]] = []
    for i, open_pitch in enumerate(tuning):
        fret = pitch - open_pitch
        if 0 <= fret <= max_fret:
            string_num = 6 - i  # index 0 -> string 6
            positions.append((string_num, fret))
    return positions


def _fallback_position(pitch: int, tuning: List[int]) -> Tuple[int, int]:
    """Return a best-effort position for an out-of-range pitch.

    Clamps fret to [0, MAX_FRET] on the closest string.
    """
    best = (1, 0)
    best_dist = float("inf")
    for i, open_pitch in enumerate(tuning):
        string_num = 6 - i
        fret = pitch - open_pitch
        clamped = max(0, min(fret, MAX_FRET))
        dist = abs(fret - clamped)
        if dist < best_dist:
            best_dist = dist
            best = (string_num, clamped)
    return best


# =========================================================================
# Cost Functions
# =========================================================================

def _position_cost(s: int, f: int) -> float:
    """Evaluate how comfortable a (string, fret) position is.

    Higher frets cost more.  The sweet spot (frets 0-9) gets a bonus.
    Open strings and very low frets also receive bonuses.
    """
    cost = 0.0

    # Fret height cost
    cost += f * WEIGHTS["w_fret_height"]

    # Extra cost above fret 9
    if f > 9:
        extra = (f - 9) * WEIGHTS["w_high_fret_extra"]
        # Low strings at high frets are even more awkward
        if s >= 4:
            extra *= WEIGHTS["w_low_string_high_fret"]
        cost += extra

    # Sweet spot bonus (frets 0-9)
    if 0 <= f <= 9:
        cost += WEIGHTS["w_sweet_spot_bonus"]

    # Extra bonus for very low frets (1-4)
    if 0 < f <= 4:
        cost += WEIGHTS["w_low_fret_bonus"]

    # Open string bonus
    if f == 0:
        cost += WEIGHTS["w_open_string_bonus"]

    return cost


def _timbre_cost(s: int, f: int, tuning: List[int]) -> float:
    """Evaluate timbre-related preference for a position.

    Open strings that produce a pitch unavailable elsewhere get a bonus.
    """
    cost = 0.0
    if f == 0:
        # Already counted in _position_cost, but check for unique pitch
        string_idx = 6 - s
        if 0 <= string_idx < len(tuning):
            pitch = tuning[string_idx]
            alt_count = sum(
                1 for i, op in enumerate(tuning)
                if i != string_idx and 0 < pitch - op <= MAX_FRET
            )
            if alt_count == 0:
                cost += WEIGHTS["w_open_match_bonus"]
    return cost


def _transition_cost(
    s: int, f: int,
    prev_s: int, prev_f: int,
) -> float:
    """Evaluate the movement cost from previous to current position.

    Considers fret jump distance, position-boundary crossing, and
    string switching.
    """
    cost = 0.0

    # --- Fret movement cost ---
    if f == 0:
        # Moving to open string = just lift fingers -> small fixed cost
        cost += WEIGHTS["w_movement"] * 0.15
    elif prev_f == 0:
        # From open string -> take a new position, but hand may be nearby
        cost += f * WEIGHTS["w_movement"] * 0.2
    else:
        fret_diff = abs(f - prev_f)
        cost += fret_diff * WEIGHTS["w_movement"]
        # Position boundary penalty (jump > 4 frets)
        if fret_diff > POSITION_WIDTH:
            cost += (fret_diff - POSITION_WIDTH) * WEIGHTS["w_position_shift"]

    # --- String switch cost ---
    string_dist = abs(s - prev_s)
    if string_dist > 0:
        cost += string_dist * WEIGHTS["w_string_switch"]
    else:
        # Same-string repeat: right-hand PIMA constraint
        cost += WEIGHTS["w_same_string_repeat"]

    return cost


def _fret_span_cost(combo: Tuple[Tuple[int, int], ...]) -> float:
    """Evaluate fret span ergonomics for a chord (multi-note combo).

    Checks position-dependent max span, barre detection, finger crossing,
    adjacent-string stretch, and finger count constraints.

    Returns
    -------
    float
        Cost value.  Returns WEIGHTS["w_unplayable"] if physically
        impossible.
    """
    cost = 0.0
    frets_nonzero = [f for _, f in combo if f > 0]

    if not frets_nonzero:
        return 0.0  # All open strings -> zero cost

    min_f = min(frets_nonzero)
    max_f = max(frets_nonzero)
    span = max_f - min_f

    # Position-dependent span constraint
    max_span = _get_max_span(min_f)
    if span > max_span:
        return WEIGHTS["w_unplayable"]

    # Span cost proportional to width
    cost += span * WEIGHTS["w_fret_span"]

    # --- Barre chord bonus ---
    fret_counts = Counter(frets_nonzero)
    for fret_val, count in fret_counts.items():
        if count > 1:
            cost += (count - 1) * WEIGHTS["w_barre_bonus"]

    # --- Finger crossing check ---
    sorted_by_string = sorted(combo, key=lambda x: x[0], reverse=True)
    for i in range(len(sorted_by_string) - 1):
        _, f1 = sorted_by_string[i]      # lower-pitched string
        _, f2 = sorted_by_string[i + 1]  # higher-pitched string
        if f1 > 0 and f2 > 0 and f1 > f2 + 2:
            cost += 50.0  # Fingers would cross

    # --- Adjacent-string stretch constraint ---
    for i in range(len(sorted_by_string) - 1):
        s1, f1 = sorted_by_string[i]
        s2, f2 = sorted_by_string[i + 1]
        if f1 > 0 and f2 > 0 and abs(s1 - s2) == 1:
            fret_gap = abs(f1 - f2)
            if fret_gap > 3:
                cost += (fret_gap - 3) * WEIGHTS["w_adjacent_stretch"]

    # --- Too many fingers constraint (no barre) ---
    if len(frets_nonzero) > 4:
        unique_positions = len(set(frets_nonzero))
        if unique_positions > 4:
            cost += WEIGHTS["w_too_many_fingers"]

    return cost


# =========================================================================
# Chord / Polyphonic Processing
# =========================================================================

def _group_simultaneous(
    notes: List[Dict],
    threshold: float = 0.03,
) -> List[List[Dict]]:
    """Group notes whose onsets are within *threshold* seconds.

    Parameters
    ----------
    notes : list[dict]
        Each note must have a start-time key (``start`` or ``start_time``).
    threshold : float
        Maximum onset difference to consider notes simultaneous.

    Returns
    -------
    list[list[dict]]
        Groups of simultaneous notes, sorted by onset then pitch.
    """
    if not notes:
        return []

    def _onset(n: Dict) -> float:
        return n.get("start", n.get("start_time", 0.0))

    def _pitch(n: Dict) -> int:
        return n.get("pitch", n.get("midi_pitch", 60))

    sorted_notes = sorted(notes, key=lambda n: (_onset(n), _pitch(n)))
    groups: List[List[Dict]] = [[sorted_notes[0]]]
    for n in sorted_notes[1:]:
        if abs(_onset(n) - _onset(groups[-1][0])) < threshold:
            groups[-1].append(n)
        else:
            groups.append([n])
    return groups


def _score_chord(
    combo: Tuple[Tuple[int, int], ...],
    prev_fingering: Optional[List[Tuple[int, int]]],
    tuning: List[int],
) -> float:
    """Score a chord fingering combination (higher = better).

    Integrates ergonomic cost, position cost, timbre cost, transition
    cost, and fingerstyle voice separation bonuses.

    Parameters
    ----------
    combo : tuple of (string, fret)
        Candidate fingering.
    prev_fingering : list of (string, fret) or None
        Previous chord/note fingering for transition cost.
    tuning : list[int]
        Open-string MIDI pitches.

    Returns
    -------
    float
        Score value (negative cost).
    """
    score = 0.0

    # 1. Ergonomic (fret span) cost
    ergo = _fret_span_cost(combo)
    if ergo >= WEIGHTS["w_unplayable"]:
        return -WEIGHTS["w_unplayable"]
    score -= ergo

    # 2. Position cost (sum over all notes)
    for s, f in combo:
        score -= _position_cost(s, f)

    # 3. Timbre cost
    for s, f in combo:
        score -= _timbre_cost(s, f, tuning)

    # 4. Transition cost (average position to average position)
    if prev_fingering and combo:
        prev_frets = [pf for _, pf in prev_fingering]
        avg_prev_f = sum(prev_frets) / len(prev_frets)
        cur_frets = [f for _, f in combo]
        avg_cur_f = sum(cur_frets) / len(cur_frets)

        prev_s_avg = sum(ps for ps, _ in prev_fingering) / len(prev_fingering)
        cur_s_avg = sum(s for s, _ in combo) / len(combo)

        score -= _transition_cost(
            int(round(cur_s_avg)), int(round(avg_cur_f)),
            int(round(prev_s_avg)), int(round(avg_prev_f)),
        )

    # 5. Fingerstyle voice separation
    if len(combo) >= 2:
        strings = [s for s, _ in combo]
        bass_string = max(strings)     # Largest string number = lowest pitch
        melody_string = min(strings)   # Smallest = highest pitch

        # Bass on low strings (4-6) gets a bonus
        if bass_string >= 4:
            score -= WEIGHTS["w_bass_low_string"]   # negative -> adds to score
        else:
            score -= WEIGHTS["w_bass_wrong_string"]  # positive -> subtracts

        # Melody on high strings (1-3) gets a bonus
        if melody_string <= 3:
            score -= WEIGHTS["w_melody_high_string"]

    return score


def _assign_chord_strings(
    chord_notes: List[Dict],
    tuning: List[int],
    prev_fingering: Optional[List[Tuple[int, int]]] = None,
) -> List[Dict]:
    """Assign (string, fret) to a group of simultaneous notes (a chord).

    Generates all valid string combinations, ensures no two notes share
    the same string, and picks the combination minimizing total span +
    ergonomic cost.

    Parameters
    ----------
    chord_notes : list[dict]
        Notes to assign.  Each must have ``pitch`` or ``midi_pitch``.
    tuning : list[int]
        Open-string MIDI pitches.
    prev_fingering : list of (string, fret) or None
        Previous fingering for transition continuity.

    Returns
    -------
    list[dict]
        Input notes with ``string`` and ``fret`` fields set.
    """
    # Guitar can play at most 6 simultaneous notes
    if len(chord_notes) > 6:
        unique_pitches: set = set()
        filtered: List[Dict] = []
        for n in chord_notes:
            p = n.get("pitch", n.get("midi_pitch", 60))
            if p not in unique_pitches:
                unique_pitches.add(p)
                filtered.append(n)
        if len(filtered) > 6:
            # Keep bass + top 5 melody notes
            filtered.sort(key=lambda x: x.get("pitch", x.get("midi_pitch", 60)),
                          reverse=True)
            filtered = filtered[:5] + [filtered[-1]]
        chord_notes = filtered

    # Enumerate position candidates per note
    note_positions: List[List[Tuple[int, int]]] = []
    for note in chord_notes:
        pitch = note.get("pitch", note.get("midi_pitch", 60))
        positions = _get_possible_positions(pitch, tuning, MAX_FRET)
        if not positions:
            positions = [_fallback_position(pitch, tuning)]
        note_positions.append(positions)

    # Prune if combinatorial explosion
    total_combos = 1
    for p in note_positions:
        total_combos *= len(p)
    if total_combos > 5000:
        note_positions = [sorted(p, key=lambda x: x[1])[:3] for p in note_positions]

    best_combo: Optional[Tuple[Tuple[int, int], ...]] = None
    best_score = float("-inf")

    for combo in iter_product(*note_positions):
        # No two notes on the same string
        strings_used = [s for s, _ in combo]
        if len(set(strings_used)) != len(strings_used):
            continue

        score = _score_chord(combo, prev_fingering, tuning)
        if score > best_score:
            best_score = score
            best_combo = combo

    if best_combo:
        for i, note in enumerate(chord_notes):
            note["string"] = best_combo[i][0]
            note["fret"] = best_combo[i][1]
    else:
        # Greedy fallback
        used_strings: set = set()
        for i, note in enumerate(chord_notes):
            for s, f in note_positions[i]:
                if s not in used_strings:
                    note["string"] = s
                    note["fret"] = f
                    used_strings.add(s)
                    break
            else:
                note["string"] = note_positions[i][0][0]
                note["fret"] = note_positions[i][0][1]

    return chord_notes


# =========================================================================
# Resolve tuning from string key or list
# =========================================================================

def _resolve_tuning(tuning: Union[str, List[int], None]) -> List[int]:
    """Convert a tuning argument to a list of MIDI pitches.

    Parameters
    ----------
    tuning : str, list[int], or None
        If str, looked up in TUNINGS dict.
        If list, used directly.
        If None, defaults to standard tuning.

    Returns
    -------
    list[int]
        Open-string MIDI pitches [6th, 5th, 4th, 3rd, 2nd, 1st].
    """
    if tuning is None:
        return list(STANDARD_TUNING)
    if isinstance(tuning, str):
        key = tuning.lower().replace(" ", "_").replace("-", "_")
        return list(TUNINGS.get(key, STANDARD_TUNING))
    return list(tuning)


# =========================================================================
# Viterbi DP with chord-aware grouping
# =========================================================================

def _viterbi_with_chords(
    groups: List[List[Dict]],
    tuning: List[int],
) -> List[Dict]:
    """Run Viterbi DP on grouped notes, handling chords and single notes.

    Chord groups (multiple simultaneous notes) are assigned first via
    combinatorial search, then single notes are optimized through
    Viterbi DP with IOI-based movement constraints.

    Parameters
    ----------
    groups : list[list[dict]]
        Groups of simultaneous notes (from _group_simultaneous).
    tuning : list[int]
        Open-string MIDI pitches.

    Returns
    -------
    list[dict]
        All notes with ``string`` and ``fret`` assigned.
    """
    if not groups:
        return []

    n_groups = len(groups)

    # Per-group candidates for Viterbi, and pre-assigned chord results
    group_candidates: List[Optional[List[Tuple[int, int]]]] = []
    chord_results: Dict[int, List[Dict]] = {}

    for gi, group in enumerate(groups):
        if len(group) == 1:
            note = group[0]
            pitch = note.get("pitch", note.get("midi_pitch", 60))
            positions = _get_possible_positions(pitch, tuning, MAX_FRET)
            if not positions:
                positions = [_fallback_position(pitch, tuning)]
            group_candidates.append(positions)
        else:
            group_candidates.append(None)  # Chord – handled separately

    # --- Assign chords first ---
    for gi, group in enumerate(groups):
        if len(group) > 1:
            prev_f: Optional[List[Tuple[int, int]]] = None
            for pgi in range(gi - 1, -1, -1):
                if pgi in chord_results:
                    prev_f = [(n["string"], n["fret"]) for n in chord_results[pgi]]
                    break
                elif group_candidates[pgi] is not None:
                    break

            chord_notes = [dict(n) for n in group]
            assigned = _assign_chord_strings(chord_notes, tuning, prev_f)
            chord_results[gi] = assigned
            # Use the first note's position as the Viterbi state for this group
            fingering = tuple((n["string"], n["fret"]) for n in assigned)
            group_candidates[gi] = [fingering[0]] if fingering else [(1, 0)]

    # --- Viterbi DP (single notes) ---
    trellis: List[Dict[Tuple[int, int], Tuple[float, Optional[Tuple[int, int]]]]] = [
        {} for _ in range(n_groups)
    ]

    # Initialization
    first_cands = group_candidates[0] or [(1, 0)]
    for s, f in first_cands:
        cost = _position_cost(s, f) + _timbre_cost(s, f, tuning)
        trellis[0][(s, f)] = (cost, None)

    # Forward pass
    for gi in range(1, n_groups):
        candidates = group_candidates[gi] or [(1, 0)]
        prev_trellis = trellis[gi - 1]

        if not prev_trellis:
            for s, f in candidates:
                cost = _position_cost(s, f) + _timbre_cost(s, f, tuning)
                trellis[gi][(s, f)] = (cost, None)
            continue

        # IOI constraint: limit physically impossible fret jumps
        def _onset(n: Dict) -> float:
            return n.get("start", n.get("start_time", 0.0))

        prev_time = _onset(groups[gi - 1][0])
        cur_time = _onset(groups[gi][0])
        ioi = max(0.01, cur_time - prev_time)
        # Human finger movement: ~12 frets/sec max
        max_fret_reach = min(MAX_FRET, max(2, int(ioi * 12)))

        for s, f in candidates:
            emission = _position_cost(s, f) + _timbre_cost(s, f, tuning)
            best_cost = float("inf")
            best_prev: Optional[Tuple[int, int]] = None

            for (prev_s, prev_f), (prev_cost, _) in prev_trellis.items():
                trans = _transition_cost(s, f, prev_s, prev_f)

                # IOI penalty for impossible jumps
                fret_jump = abs(f - prev_f) if (f > 0 and prev_f > 0) else 0
                if fret_jump > max_fret_reach:
                    trans += (fret_jump - max_fret_reach) * 15.0

                total = prev_cost + emission + trans
                if total < best_cost:
                    best_cost = total
                    best_prev = (prev_s, prev_f)

            trellis[gi][(s, f)] = (best_cost, best_prev)

    # --- Backtrack ---
    if not trellis[-1]:
        result: List[Dict] = []
        for group in groups:
            result.extend(group)
        return result

    best_final_state = min(trellis[-1], key=lambda k: trellis[-1][k][0])
    path: List[Optional[Tuple[int, int]]] = [None] * n_groups
    path[-1] = best_final_state

    for gi in range(n_groups - 2, -1, -1):
        next_state = path[gi + 1]
        if next_state and next_state in trellis[gi + 1]:
            _, backptr = trellis[gi + 1][next_state]
            path[gi] = backptr
        else:
            if trellis[gi]:
                path[gi] = min(trellis[gi], key=lambda k: trellis[gi][k][0])
            else:
                path[gi] = (group_candidates[gi] or [(1, 0)])[0]

    # --- Apply path to notes ---
    result: List[Dict] = []
    for gi, group in enumerate(groups):
        if gi in chord_results:
            result.extend(chord_results[gi])
        elif len(group) == 1:
            note = group[0]
            state = path[gi]
            if state:
                note["string"] = state[0]
                note["fret"] = state[1]
            else:
                fb = _fallback_position(
                    note.get("pitch", note.get("midi_pitch", 60)), tuning
                )
                note["string"] = fb[0]
                note["fret"] = fb[1]
            result.append(note)
        else:
            result.extend(group)

    return result


# =========================================================================
# Minimax Post-Processing
# =========================================================================

def _minimax_postprocess(
    notes: List[Dict],
    tuning: List[int],
) -> List[Dict]:
    """Minimax Viterbi post-processing to eliminate extreme transitions.

    After the standard (sum-optimal) Viterbi pass, this runs a second
    Minimax DP that minimizes the MAXIMUM single-transition cost on the
    path.  If the minimax solution significantly reduces the worst-case
    transition, the path is updated.

    Based on Hori & Sagayama, ISMIR 2016 "Minimax Approach to Guitar
    Fingering".

    Parameters
    ----------
    notes : list[dict]
        Notes with ``string`` and ``fret`` already assigned.
    tuning : list[int]
        Open-string MIDI pitches.

    Returns
    -------
    list[dict]
        Notes with potentially improved assignments.
    """
    if len(notes) < 3:
        return notes

    n = len(notes)

    # Enumerate candidates per note
    candidates_list: List[List[Tuple[int, int]]] = []
    for note in notes:
        pitch = note.get("pitch", note.get("midi_pitch", 60))
        positions = _get_possible_positions(pitch, tuning, MAX_FRET)
        if not positions:
            positions = [(note.get("string", 1), note.get("fret", 0))]
        candidates_list.append(positions)

    # --- Minimax Viterbi DP ---
    # mm_trellis[i][(s,f)] = (max_step_on_path, sum_cost, backpointer)
    mm_trellis: List[Dict[Tuple[int, int], Tuple[float, float, Optional[Tuple[int, int]]]]] = [
        {} for _ in range(n)
    ]

    # Initialize first note
    for s, f in candidates_list[0]:
        step = _position_cost(s, f) + _timbre_cost(s, f, tuning)
        mm_trellis[0][(s, f)] = (step, step, None)

    # Forward pass
    for i in range(1, n):
        def _onset(note: Dict) -> float:
            return note.get("start", note.get("start_time", 0.0))

        prev_time = _onset(notes[i - 1])
        cur_time = _onset(notes[i])
        ioi = max(0.01, cur_time - prev_time)
        max_fret_reach = min(MAX_FRET, max(2, int(ioi * 12)))

        for s, f in candidates_list[i]:
            best_max_cost = float("inf")
            best_sum_cost = float("inf")
            best_prev: Optional[Tuple[int, int]] = None

            emission = _position_cost(s, f) + _timbre_cost(s, f, tuning)

            for (prev_s, prev_f), (prev_max, prev_sum, _) in mm_trellis[i - 1].items():
                trans = _transition_cost(s, f, prev_s, prev_f)

                # IOI constraint
                fret_jump = abs(f - prev_f) if (f > 0 and prev_f > 0) else 0
                if fret_jump > max_fret_reach:
                    trans += (fret_jump - max_fret_reach) * 15.0

                step_cost = emission + trans
                path_max = max(prev_max, step_cost)
                path_sum = prev_sum + step_cost

                # Tie-break with sum cost
                if (path_max < best_max_cost or
                        (path_max == best_max_cost and path_sum < best_sum_cost)):
                    best_max_cost = path_max
                    best_sum_cost = path_sum
                    best_prev = (prev_s, prev_f)

            if best_prev is not None:
                mm_trellis[i][(s, f)] = (best_max_cost, best_sum_cost, best_prev)

    if not mm_trellis[-1]:
        return notes

    # --- Backtrack minimax path ---
    best_final = min(mm_trellis[-1].items(), key=lambda x: x[1][0])
    mm_path: List[Optional[Tuple[int, int]]] = [None] * n
    current = best_final[0]
    mm_path[-1] = current

    for i in range(n - 1, 0, -1):
        entry = mm_trellis[i].get(current)
        if entry is None:
            break
        _, _, prev = entry
        if prev is None:
            break
        mm_path[i - 1] = prev
        current = prev

    # --- Compare sum-optimal vs minimax-optimal ---
    # Compute max step cost of the current (sum-optimal) path
    sum_max_step = 0.0
    for i in range(1, n):
        s = notes[i].get("string", 1)
        f = notes[i].get("fret", 0)
        ps = notes[i - 1].get("string", 1)
        pf = notes[i - 1].get("fret", 0)
        step = _transition_cost(s, f, ps, pf) + _position_cost(s, f)
        sum_max_step = max(sum_max_step, step)

    mm_max_step = best_final[1][0]

    # Conservative: only replace if sum-optimal has a clearly bad transition
    # and minimax improves it by at least 50%
    if sum_max_step > 100.0 and mm_max_step < sum_max_step * 0.5:
        replaced = 0
        for i in range(n):
            if mm_path[i] is None:
                continue
            new_s, new_f = mm_path[i]
            old_s = notes[i].get("string", 1)
            old_f = notes[i].get("fret", 0)
            if new_s != old_s or new_f != old_f:
                notes[i]["string"] = new_s
                notes[i]["fret"] = new_f
                replaced += 1
        if replaced > 0:
            print(f"[Minimax Viterbi] Improved {replaced} notes "
                  f"(max_step: {sum_max_step:.1f} -> {mm_max_step:.1f})")

    return notes


# =========================================================================
# Main Public API
# =========================================================================

def optimize_string_assignment(
    notes: List[Dict],
    tuning: Union[str, List[int], None] = None,
    capo: int = 0,
) -> List[Dict]:
    """Assign optimal (string, fret) to each note via Viterbi DP.

    This is the main entry point, backward-compatible with the original
    NextChord API.  It now supports:
      - Chord/polyphonic processing (simultaneous notes)
      - Position-dependent fret span constraints
      - Barre chord detection and bonus
      - Bass/melody voice separation
      - IOI-based movement constraints
      - Minimax post-processing
      - 40+ alternate tunings (pass tuning name as string)

    Parameters
    ----------
    notes : list[dict]
        Each note must have ``midi_pitch`` (int) or ``pitch`` (int).
        Optional keys: ``start`` / ``start_time``, ``end`` / ``end_time``,
        ``velocity``, ``confidence``, ``technique``.
        Result: ``string`` and ``fret`` will be added/updated.
    tuning : str, list[int], or None
        Tuning specification.  Can be:
          - A string key from TUNINGS (e.g. ``"drop_d"``, ``"dadgad"``).
          - A list of 6 MIDI pitch values ``[6th, 5th, ..., 1st]``.
          - ``None`` for standard tuning.
    capo : int
        Capo position (0 = no capo).  Shifts all open-string pitches up.

    Returns
    -------
    list[dict]
        Input notes with ``string`` and ``fret`` fields set.
    """
    if not notes:
        return notes

    # --- Resolve tuning ---
    tuning_list = _resolve_tuning(tuning)

    # Apply capo
    if capo > 0:
        tuning_list = [p + capo for p in tuning_list]

    # --- Normalize pitch key ---
    # Support both "pitch" and "midi_pitch" keys
    for note in notes:
        if "pitch" not in note and "midi_pitch" in note:
            note["pitch"] = note["midi_pitch"]
        elif "midi_pitch" not in note and "pitch" in note:
            note["midi_pitch"] = note["pitch"]

    # --- Group simultaneous notes ---
    groups = _group_simultaneous(notes, threshold=0.03)

    # --- Split into phrases (>0.5s gap = phrase boundary) ---
    phrases: List[List[List[Dict]]] = []
    current_phrase: List[List[Dict]] = [groups[0]]
    for gi in range(1, len(groups)):
        def _onset(n: Dict) -> float:
            return n.get("start", n.get("start_time", 0.0))

        prev_time = _onset(current_phrase[-1][0])
        cur_time = _onset(groups[gi][0])
        if cur_time - prev_time > 0.5:
            phrases.append(current_phrase)
            current_phrase = []
        current_phrase.append(groups[gi])
    if current_phrase:
        phrases.append(current_phrase)

    # --- Process each phrase ---
    result: List[Dict] = []
    for phrase in phrases:
        phrase_result = _viterbi_with_chords(phrase, tuning_list)
        result.extend(phrase_result)

    # --- Minimax post-processing ---
    result = _minimax_postprocess(result, tuning_list)

    return result


# =========================================================================
# Convenience alias for backward compatibility
# =========================================================================
assign_strings = optimize_string_assignment
"""Alias for :func:`optimize_string_assignment`."""
"""
Accepts the same parameters:
  assign_strings(notes, tuning='standard', capo=0)
"""
