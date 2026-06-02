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

/**
 * コードのリストから一番弾きやすいカポ位置（推奨カポ）を算出する。
 * 各コードのルート音の難易度を重み付けしてスコア化し、最小スコアのカポ位置を返す。
 * @param {string[]} chords - 曲に含まれるコードの配列
 * @returns {number} 0〜7 の最適なカポ位置
 */
export const calculateBestCapo = (chords) => {
    if (!chords || chords.length === 0) return 0;

    const getDifficultyScore = (root) => {
        const scores = {
            "C": 0, "D": 0, "E": 0, "G": 0, "A": 0, // オープンコード（簡単）
            "F": 1, // よく使うバレーコード
            "B": 2, // Fより少し押さえにくいバレーコード
            "C#": 3, "Db": 3, "D#": 3, "Eb": 3, 
            "F#": 3, "Gb": 3, "G#": 3, "Ab": 3, 
            "A#": 3, "Bb": 3 // 黒鍵系の難しいコード
        };
        // Normalize flats to sharps for lookup just in case
        let norm = NORMALIZE_MAP[root] || root;
        return scores[norm] !== undefined ? scores[norm] : 3;
    };

    const rootCounts = {};
    chords.forEach(c => {
        if (!c || c === "N.C." || c === "N") return;
        const match = c.match(/^([A-G][b#]?)/);
        if (match) {
            const root = match[1];
            rootCounts[root] = (rootCounts[root] || 0) + 1;
        }
    });

    let bestCapo = 0;
    let minScore = Infinity;

    // 実用的なカポ位置として 0〜7 程度を探索
    for (let capo = 0; capo <= 7; capo++) {
        let currentScore = 0;
        
        for (const [root, count] of Object.entries(rootCounts)) {
            // カポをつける＝コードはマイナス方向に移調される
            const transposed = transposeChord(root, -capo);
            const trMatch = transposed.match(/^([A-G][b#]?)/);
            if (trMatch) {
                currentScore += getDifficultyScore(trMatch[1]) * count;
            }
        }
        
        // カポをつけること自体へのペナルティ（カポ0を優先させ、かつハイフレットすぎるカポを避けるため）
        const penalty = capo * 0.1;
        const totalScore = currentScore + penalty;

        if (totalScore < minScore) {
            minScore = totalScore;
            bestCapo = capo;
        }
    }

    return bestCapo;
};
