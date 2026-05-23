"""
tuning_estimator.py — Guitar Tuning Estimation from Detected Notes
===================================================================
Estimates the most likely guitar tuning based on the pitch distribution
of transcribed notes. Re-implemented for NextChord's architecture.

Algorithm overview:
    1. Extract MIDI pitches from note events
    2. Identify the lowest 5% of pitches (bass region)
    3. Score each candidate tuning by:
       a. How many low notes match open string pitches (±1 semitone)
       b. Whether the absolute minimum pitch matches the 6th string
       c. Whether all pitches fall within the tuning's playable range
    4. Return the best-matching tuning name

Reference:
    Adapted from SoloTab's string_assigner.guess_tuning(), with added
    percentile-based low-note extraction and fuzzy pitch matching.
"""

from typing import List, Dict, Optional, Tuple
import math


# =========================================================================
# Tuning Dictionary
# =========================================================================
# MIDI pitches for open strings: [6th, 5th, 4th, 3rd, 2nd, 1st] (low→high)
# Reference: E2=40, A2=45, D3=50, G3=55, B3=59, E4=64

TUNINGS: Dict[str, List[int]] = {
    # --- Standard family ---
    "standard":       [40, 45, 50, 55, 59, 64],  # E A D G B E
    "half_down":      [39, 44, 49, 54, 58, 63],  # Eb Ab Db Gb Bb Eb
    "full_down":      [38, 43, 48, 53, 57, 62],  # D G C F A D
    "1half_down":     [37, 42, 47, 52, 56, 61],  # Db Gb B E Ab Db

    # --- Drop tunings ---
    "drop_d":         [38, 45, 50, 55, 59, 64],  # D A D G B E
    "drop_c#":        [37, 44, 49, 54, 58, 63],  # C# Ab Db Gb Bb Eb
    "drop_c":         [36, 43, 48, 53, 57, 62],  # C G C F A D
    "drop_b":         [35, 42, 47, 52, 56, 61],  # B Gb B E Ab Db
    "double_drop_d":  [38, 45, 50, 55, 59, 62],  # D A D G B D

    # --- DADGAD family (celtic / fingerstyle) ---
    "dadgad":         [38, 45, 50, 55, 57, 62],  # D A D G A D
    "dadgac":         [38, 45, 50, 55, 57, 60],  # D A D G A C
    "dadgae":         [38, 45, 50, 55, 57, 64],  # D A D G A E
    "cgdgad":         [36, 43, 50, 55, 57, 62],  # C G D G A D

    # --- Open major tunings ---
    "open_d":         [38, 45, 50, 54, 57, 62],  # D A D F# A D
    "open_e":         [40, 47, 52, 56, 59, 64],  # E B E G# B E
    "open_g":         [38, 43, 50, 55, 59, 62],  # D G D G B D
    "open_a":         [40, 45, 52, 57, 61, 64],  # E A E A C# E
    "open_c":         [36, 43, 48, 55, 60, 64],  # C G C G C E

    # --- Open minor tunings ---
    "open_dm":        [38, 45, 50, 53, 57, 62],  # D A D F A D
    "open_em":        [40, 47, 52, 55, 59, 64],  # E B E G B E
    "open_gm":        [38, 43, 50, 55, 58, 62],  # D G D G Bb D
    "open_am":        [40, 45, 52, 57, 60, 64],  # E A E A C E

    # --- Other notable tunings ---
    "cgcgce":         [36, 43, 48, 55, 60, 64],  # C G C G C E (= Open C)
    "new_standard":   [36, 43, 50, 57, 62, 67],  # C G D A E B (Fripp)
    "nashville":      [52, 57, 62, 67, 71, 76],  # E3 A3 D4 G4 B4 E5
}

# Display names for user-facing output
TUNING_DISPLAY_NAMES: Dict[str, str] = {
    "standard":       "Standard (EADGBE)",
    "half_down":      "Half Step Down (Eb)",
    "full_down":      "Full Step Down (D)",
    "drop_d":         "Drop D",
    "drop_c#":        "Drop C#",
    "drop_c":         "Drop C",
    "drop_b":         "Drop B",
    "double_drop_d":  "Double Drop D",
    "dadgad":         "DADGAD",
    "dadgac":         "DADGAC",
    "dadgae":         "DADGAE",
    "cgdgad":         "CGDGAD",
    "open_d":         "Open D",
    "open_e":         "Open E",
    "open_g":         "Open G",
    "open_a":         "Open A",
    "open_c":         "Open C",
    "open_dm":        "Open Dm",
    "open_em":        "Open Em",
    "open_gm":        "Open Gm",
    "open_am":        "Open Am",
    "cgcgce":         "CGCGCE",
    "new_standard":   "New Standard",
    "nashville":      "Nashville",
}


# =========================================================================
# Public API
# =========================================================================

def get_tuning_pitches(tuning_name: str) -> List[int]:
    """
    Return MIDI pitches for the open strings of a named tuning.

    Parameters
    ----------
    tuning_name : str
        Key into the TUNINGS dictionary (e.g., 'standard', 'drop_d').

    Returns
    -------
    list of int
        Six MIDI pitch values [6th, 5th, 4th, 3rd, 2nd, 1st].
        Falls back to standard tuning if the name is not recognized.
    """
    return list(TUNINGS.get(tuning_name, TUNINGS["standard"]))


def estimate_tuning(
    notes: list,
    *,
    candidates: Optional[List[str]] = None,
) -> str:
    """
    Estimate the guitar tuning from detected note pitches.

    Strategy:
        1. Find the lowest 5% of note pitches (bass region)
        2. Check if the minimum pitch is below standard tuning's E2 (40)
        3. Match against known tuning patterns by scoring how well each
           tuning's open-string pitches explain the observed low notes
        4. Apply tie-breaking heuristics (standard tuning preferred)

    Parameters
    ----------
    notes : list
        List of note dicts. Each dict should contain either a 'pitch'
        key or a 'midi_pitch' key with an integer MIDI note number.
    candidates : list of str, optional
        Tuning names to consider. If None, all tunings in the dictionary
        are evaluated.

    Returns
    -------
    str
        Tuning name (e.g., 'standard', 'drop_d', 'open_g').
    """
    # --- Extract MIDI pitches ---
    pitches = _extract_pitches(notes)
    if not pitches:
        return "standard"

    # --- Determine candidate tunings ---
    if candidates:
        tuning_pool = {
            name: TUNINGS[name]
            for name in candidates
            if name in TUNINGS
        }
        if not tuning_pool:
            tuning_pool = TUNINGS
    else:
        tuning_pool = TUNINGS

    # --- Identify the low-pitch region (lowest 5% of unique pitches) ---
    sorted_unique = sorted(set(pitches))
    n_low = max(1, math.ceil(len(sorted_unique) * 0.05))
    # Also cap at 10 to keep scoring focused on the true bass region
    n_low = min(n_low, 10)
    low_pitches = sorted_unique[:n_low]

    abs_min = sorted_unique[0]

    # --- Score each candidate tuning ---
    scores: List[Tuple[str, float]] = []
    for name, tuning in tuning_pool.items():
        score = _score_tuning(tuning, low_pitches, abs_min, sorted_unique)
        scores.append((name, score))

    # Sort descending by score; tie-break by preferring standard
    scores.sort(key=lambda x: (-x[1], x[0] != "standard"))

    best_name = scores[0][0] if scores else "standard"
    return best_name


def estimate_tuning_top_n(
    notes: list,
    *,
    top_n: int = 3,
    candidates: Optional[List[str]] = None,
) -> List[Tuple[str, float]]:
    """
    Return the top-N tuning candidates with their scores.

    Useful for displaying multiple possibilities to the user or for
    downstream logic that needs confidence information.

    Parameters
    ----------
    notes : list
        List of note dicts (same format as estimate_tuning).
    top_n : int
        Number of top candidates to return.
    candidates : list of str, optional
        Tuning names to consider.

    Returns
    -------
    list of (str, float)
        Top-N tuning candidates as (name, score) pairs, sorted by
        descending score.
    """
    pitches = _extract_pitches(notes)
    if not pitches:
        return [("standard", 1.0)]

    if candidates:
        tuning_pool = {
            name: TUNINGS[name]
            for name in candidates
            if name in TUNINGS
        }
        if not tuning_pool:
            tuning_pool = TUNINGS
    else:
        tuning_pool = TUNINGS

    sorted_unique = sorted(set(pitches))
    n_low = max(1, math.ceil(len(sorted_unique) * 0.05))
    n_low = min(n_low, 10)
    low_pitches = sorted_unique[:n_low]
    abs_min = sorted_unique[0]

    scores: List[Tuple[str, float]] = []
    for name, tuning in tuning_pool.items():
        score = _score_tuning(tuning, low_pitches, abs_min, sorted_unique)
        scores.append((name, score))

    scores.sort(key=lambda x: (-x[1], x[0] != "standard"))
    return scores[:top_n]


# =========================================================================
# Internal Helpers
# =========================================================================

def _extract_pitches(notes: list) -> List[int]:
    """
    Extract integer MIDI pitches from a list of note dicts.

    Supports both 'pitch' and 'midi_pitch' keys. Silently skips
    notes that have neither key or have non-numeric values.

    Parameters
    ----------
    notes : list
        Note event dicts.

    Returns
    -------
    list of int
        Extracted MIDI pitch values.
    """
    pitches: List[int] = []
    for n in notes:
        p = n.get("pitch") or n.get("midi_pitch")
        if p is not None:
            try:
                pitches.append(int(p))
            except (ValueError, TypeError):
                continue
    return pitches


def _score_tuning(
    tuning: List[int],
    low_pitches: List[int],
    abs_min: int,
    all_sorted_unique: List[int],
) -> float:
    """
    Compute a match score for a single candidate tuning.

    Scoring criteria (all additive):
        1. Low-note open-string match (±1 semitone fuzzy matching)
        2. 6th-string minimum pitch match (strong bonus)
        3. Octave-up open-string match (weaker bonus)
        4. Playable range check (all pitches reachable on the tuning)

    Parameters
    ----------
    tuning : list of int
        Open string pitches [6th..1st].
    low_pitches : list of int
        The lowest 5% of detected unique pitches.
    abs_min : int
        The absolute minimum detected pitch.
    all_sorted_unique : list of int
        All unique detected pitches, sorted ascending.

    Returns
    -------
    float
        Non-negative score. Higher is better.
    """
    score = 0.0
    open_set = set(tuning)

    # --- Criterion 1: Low notes matching open strings (±1 semitone) ---
    for p in low_pitches:
        if p in open_set:
            # Exact match with an open string pitch
            score += 2.0
        elif (p - 1) in open_set or (p + 1) in open_set:
            # Within ±1 semitone of an open string
            score += 1.0
        elif (p - 12) in open_set:
            # Octave above an open string
            score += 0.5
        elif (p + 12) in open_set:
            # Octave below an open string (unusual but possible)
            score += 0.3

    # --- Criterion 2: 6th string matches absolute minimum pitch ---
    sixth_string = tuning[0]
    if abs_min == sixth_string:
        score += 5.0
    elif abs_min == sixth_string + 12:
        # Octave above the 6th string (no open 6th string was played)
        score += 2.0
    elif abs(abs_min - sixth_string) == 1:
        # Off by one semitone — could be a fretted note on open-ish string
        score += 1.5

    # --- Criterion 3: Range plausibility ---
    # All detected pitches should be reachable on this tuning (fret 0–19)
    min_tuning = min(tuning)
    max_tuning = max(tuning) + 19  # highest fret on 1st string
    if abs_min >= min_tuning:
        score += 1.0
    else:
        # Some notes are below the tuning's lowest open string
        deficit = min_tuning - abs_min
        score -= deficit * 0.5

    # Check if the highest note is reachable
    if all_sorted_unique:
        abs_max = all_sorted_unique[-1]
        if abs_max <= max_tuning:
            score += 0.5

    # --- Criterion 4: Standard tuning tiebreaker ---
    # A very slight bias toward standard tuning since it is by far the
    # most common. This only matters when scores are otherwise equal.
    if tuning == TUNINGS["standard"]:
        score += 0.1

    return score
