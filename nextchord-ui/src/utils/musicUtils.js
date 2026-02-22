/**
 * Music Theory Utilities for NextChord
 */

const NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

// Map flats to sharps for standardized calculation
const NORMALIZE_MAP = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "Cb": "B", "E#": "F", "Fb": "E", "B#": "C"
};

/**
 * Transpose a chord string by n semitones.
 * @param {string} chord - The chord string (e.g., "Cm7", "F#", "Bb")
 * @param {number} semitones - Number of semitones to shift (-12 to 12)
 * @returns {string} Transposed chord
 */
export const transposeChord = (chord, semitones) => {
    if (!chord || chord === "N") return chord;
    if (semitones === 0) return chord;

    // Split root note from quality (m, 7, maj7, etc.)
    // Regex to match root note: [A-G] followed by optional # or b
    const match = chord.match(/^([A-G][b#]?)(.*)$/);
    if (!match) return chord;

    let root = match[1];
    const quality = match[2];

    // Normalize root to sharps
    if (NORMALIZE_MAP[root]) root = NORMALIZE_MAP[root];

    // Find index in NOTES
    let idx = NOTES.indexOf(root);
    if (idx === -1) return chord; // Should not happen if regex matched

    // Calculate new index
    let newIdx = (idx + semitones) % 12;
    if (newIdx < 0) newIdx += 12;

    return NOTES[newIdx] + quality;
};
