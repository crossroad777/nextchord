import React from "react";
import { transposeChord } from "../utils/musicUtils";

// ─── Chord Shapes Database (Guitar) ───
// String order: E A D G B e
// -1 = mute, 0 = open, >0 = fret
const CHORD_SHAPES = {
    // Major
    "C": { name: "C", frets: [-1, 3, 2, 0, 1, 0] },
    "D": { name: "D", frets: [-1, -1, 0, 2, 3, 2] },
    "E": { name: "E", frets: [0, 2, 2, 1, 0, 0] },
    "F": { name: "F", frets: [1, 3, 3, 2, 1, 1], barre: 1 },
    "G": { name: "G", frets: [3, 2, 0, 0, 0, 3] },
    "A": { name: "A", frets: [-1, 0, 2, 2, 2, 0] },
    "B": { name: "B", frets: [-1, 2, 4, 4, 4, 2], barre: 2 },
    "C#": { name: "C♯", frets: [-1, 4, 6, 6, 6, 4], barre: 4 },
    "Db": { name: "D♭", frets: [-1, 4, 6, 6, 6, 4], barre: 4 },
    "D#": { name: "D♯", frets: [-1, -1, 1, 3, 4, 3], barre: 1 },
    "Eb": { name: "E♭", frets: [-1, -1, 1, 3, 4, 3], barre: 1 },
    "F#": { name: "F♯", frets: [2, 4, 4, 3, 2, 2], barre: 2 },
    "Gb": { name: "G♭", frets: [2, 4, 4, 3, 2, 2], barre: 2 },
    "G#": { name: "G♯", frets: [4, 6, 6, 5, 4, 4], barre: 4 },
    "Ab": { name: "A♭", frets: [4, 6, 6, 5, 4, 4], barre: 4 },
    "A#": { name: "A♯", frets: [-1, 1, 3, 3, 3, 1], barre: 1 },
    "Bb": { name: "B♭", frets: [-1, 1, 3, 3, 3, 1], barre: 1 },

    // Minor
    "Cm": { name: "Cm", frets: [-1, 3, 5, 5, 4, 3], barre: 3 },
    "Dm": { name: "Dm", frets: [-1, -1, 0, 2, 3, 1] },
    "Em": { name: "Em", frets: [0, 2, 2, 0, 0, 0] },
    "Fm": { name: "Fm", frets: [1, 3, 3, 1, 1, 1], barre: 1 },
    "Gm": { name: "Gm", frets: [3, 5, 5, 3, 3, 3], barre: 3 },
    "Am": { name: "Am", frets: [-1, 0, 2, 2, 1, 0] },
    "Bm": { name: "Bm", frets: [-1, 2, 4, 4, 3, 2], barre: 2 },
    "C#m": { name: "C♯m", frets: [-1, 4, 6, 6, 5, 4], barre: 4 },
    "Dbm": { name: "D♭m", frets: [-1, 4, 6, 6, 5, 4], barre: 4 },
    "D#m": { name: "D♯m", frets: [-1, -1, 1, 3, 4, 2] },
    "Ebm": { name: "E♭m", frets: [-1, -1, 1, 3, 4, 2] },
    "F#m": { name: "F♯m", frets: [2, 4, 4, 2, 2, 2], barre: 2 },
    "Gbm": { name: "G♭m", frets: [2, 4, 4, 2, 2, 2], barre: 2 },
    "G#m": { name: "G♯m", frets: [4, 6, 6, 4, 4, 4], barre: 4 },
    "Abm": { name: "A♭m", frets: [4, 6, 6, 4, 4, 4], barre: 4 },
    "A#m": { name: "A♯m", frets: [-1, 1, 3, 3, 2, 1], barre: 1 },
    "Bbm": { name: "B♭m", frets: [-1, 1, 3, 3, 2, 1], barre: 1 },

    // 7th
    "C7": { name: "C7", frets: [-1, 3, 2, 3, 1, 0] },
    "D7": { name: "D7", frets: [-1, -1, 0, 2, 1, 2] },
    "E7": { name: "E7", frets: [0, 2, 0, 1, 0, 0] },
    "F7": { name: "F7", frets: [1, 3, 1, 2, 1, 1], barre: 1 },
    "G7": { name: "G7", frets: [3, 2, 0, 0, 0, 1] },
    "A7": { name: "A7", frets: [-1, 0, 2, 0, 2, 0] },
    "B7": { name: "B7", frets: [-1, 2, 1, 2, 0, 2] },
    "F#7": { name: "F♯7", frets: [2, 4, 2, 3, 2, 2], barre: 2 },
    "Bb7": { name: "B♭7", frets: [-1, 1, 3, 1, 3, 1], barre: 1 },
    "Eb7": { name: "E♭7", frets: [-1, -1, 1, 3, 2, 3] },

    // Maj7
    "Cmaj7": { name: "Cmaj7", frets: [-1, 3, 2, 0, 0, 0] },
    "Dmaj7": { name: "Dmaj7", frets: [-1, -1, 0, 2, 2, 2] },
    "Emaj7": { name: "Emaj7", frets: [0, 2, 1, 1, 0, 0] },
    "Fmaj7": { name: "Fmaj7", frets: [-1, -1, 3, 2, 1, 0] },
    "Gmaj7": { name: "Gmaj7", frets: [3, 2, 0, 0, 0, 2] },
    "Amaj7": { name: "Amaj7", frets: [-1, 0, 2, 1, 2, 0] },
    "Bbmaj7": { name: "B♭maj7", frets: [-1, 1, 3, 2, 3, 1], barre: 1 },

    // min7
    "Am7": { name: "Am7", frets: [-1, 0, 2, 0, 1, 0] },
    "Bm7": { name: "Bm7", frets: [-1, 2, 4, 2, 3, 2], barre: 2 },
    "Cm7": { name: "Cm7", frets: [-1, 3, 5, 3, 4, 3], barre: 3 },
    "Dm7": { name: "Dm7", frets: [-1, -1, 0, 2, 1, 1] },
    "Em7": { name: "Em7", frets: [0, 2, 0, 0, 0, 0] },
    "Fm7": { name: "Fm7", frets: [1, 3, 1, 1, 1, 1], barre: 1 },
    "F#m7": { name: "F♯m7", frets: [2, 4, 2, 2, 2, 2], barre: 2 },
    "Gm7": { name: "Gm7", frets: [3, 5, 3, 3, 3, 3], barre: 3 },
    "G#m7": { name: "G♯m7", frets: [4, 6, 4, 4, 4, 4], barre: 4 },
    "Bbm7": { name: "B♭m7", frets: [-1, 1, 3, 1, 2, 1], barre: 1 },
    "C#m7": { name: "C♯m7", frets: [-1, 4, 6, 4, 5, 4], barre: 4 },

    // sus
    "Csus4": { name: "Csus4", frets: [-1, 3, 3, 0, 1, 1] },
    "Dsus4": { name: "Dsus4", frets: [-1, -1, 0, 2, 3, 3] },
    "Esus4": { name: "Esus4", frets: [0, 2, 2, 2, 0, 0] },
    "Gsus4": { name: "Gsus4", frets: [3, 5, 5, 5, 3, 3], barre: 3 },
    "Asus4": { name: "Asus4", frets: [-1, 0, 2, 2, 3, 0] },
    "Dsus2": { name: "Dsus2", frets: [-1, -1, 0, 2, 3, 0] },
    "Asus2": { name: "Asus2", frets: [-1, 0, 2, 2, 0, 0] },

    // add9
    "Cadd9": { name: "Cadd9", frets: [-1, 3, 2, 0, 3, 0] },
    "Gadd9": { name: "Gadd9", frets: [3, 2, 0, 2, 0, 3] },
    "Eadd9": { name: "Eadd9", frets: [0, 2, 2, 1, 0, 2] },

    // dim / aug
    "Bdim": { name: "Bdim", frets: [-1, 2, 3, 4, 3, -1] },
    "Cdim": { name: "Cdim", frets: [-1, 3, 4, 5, 4, -1] },
    "Caug": { name: "Caug", frets: [-1, 3, 2, 1, 1, 0] },
    "Eaug": { name: "Eaug", frets: [0, 3, 2, 1, 1, 0] },
};

// ─── Chord lookup with smart fallback ───
function findChordShape(chordName) {
    if (!chordName || chordName === "N.C.") return null;

    // Direct match
    if (CHORD_SHAPES[chordName]) return CHORD_SHAPES[chordName];

    // Enharmonic equivalents
    const enharmonic = {
        "C#": "Db", "Db": "C#", "D#": "Eb", "Eb": "D#",
        "F#": "Gb", "Gb": "F#", "G#": "Ab", "Ab": "G#",
        "A#": "Bb", "Bb": "A#",
    };

    // Extract root and quality
    const match = chordName.match(/^([A-G][#b]?)(.*)$/);
    if (!match) return null;
    const [, root, quality] = match;

    // Try enharmonic equivalent
    const altRoot = enharmonic[root];
    if (altRoot && CHORD_SHAPES[altRoot + quality]) {
        return CHORD_SHAPES[altRoot + quality];
    }

    // Fallback: strip modifiers progressively
    const fallbacks = [
        quality.replace("add9", ""),     // Cadd9 → C
        quality.replace("sus4", ""),     // Csus4 → C
        quality.replace("sus2", ""),     // Csus2 → C
        quality.replace("dim7", "dim"),  // Cdim7 → Cdim
        quality.replace("aug7", "aug"),  // Caug7 → Caug
        quality.replace("maj7", ""),     // Cmaj7 fallback → C
        quality.replace(/m7/, "m"),      // Cm7 → Cm
        quality.replace(/7/, ""),        // C7 → C
        quality.replace(/m/, ""),        // Cm → C (root only)
    ];

    for (const fb of fallbacks) {
        if (CHORD_SHAPES[root + fb]) return CHORD_SHAPES[root + fb];
        if (altRoot && CHORD_SHAPES[altRoot + fb]) return CHORD_SHAPES[altRoot + fb];
    }

    return null;
}

// ─── Piano Chord Note Generator ───
// Dynamically compute piano notes from root + chord formula
const NOTE_MAP = { "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11 };

const CHORD_INTERVALS = {
    "": [0, 4, 7],            // major
    "m": [0, 3, 7],           // minor
    "7": [0, 4, 7, 10],       // dominant 7th
    "m7": [0, 3, 7, 10],      // minor 7th
    "maj7": [0, 4, 7, 11],    // major 7th
    "dim": [0, 3, 6],         // diminished
    "dim7": [0, 3, 6, 9],     // diminished 7th
    "aug": [0, 4, 8],         // augmented
    "sus4": [0, 5, 7],        // suspended 4th
    "sus2": [0, 2, 7],        // suspended 2nd
    "add9": [0, 4, 7, 14],    // add 9
    "6": [0, 4, 7, 9],        // major 6th
    "m6": [0, 3, 7, 9],       // minor 6th
    "9": [0, 4, 7, 10, 14],   // dominant 9th
    "m9": [0, 3, 7, 10, 14],  // minor 9th
};

function getPianoNotes(chordName) {
    if (!chordName || chordName === "N.C.") return [];
    const match = chordName.match(/^([A-G][#b]?)(.*)$/);
    if (!match) return [];
    const [, root, quality] = match;
    const rootNote = NOTE_MAP[root];
    if (rootNote === undefined) return [];

    const intervals = CHORD_INTERVALS[quality] || CHORD_INTERVALS[""];
    return intervals.map(i => (rootNote + i) % 12);
}

// ─── Piano Keyboard Component ───
const PianoKeyboard = ({ activeNotes = [] }) => {
    const whiteNotes = [0, 2, 4, 5, 7, 9, 11]; // C D E F G A B
    const blackNotes = [1, 3, -1, 6, 8, 10];    // C# D# - F# G# A#
    const keyW = 22;
    const totalW = 7 * keyW;
    const whiteH = 72;
    const blackH = 44;

    return (
        <svg viewBox={`0 0 ${totalW} ${whiteH + 4}`} className="w-44 h-20 drop-shadow-md">
            {/* White keys */}
            {whiteNotes.map((note, i) => (
                <rect
                    key={`w-${note}`}
                    x={i * keyW + 0.5}
                    y={0}
                    width={keyW - 1}
                    height={whiteH}
                    rx={3}
                    fill={activeNotes.includes(note) ? "var(--nc-primary)" : "var(--nc-surface)"}
                    stroke="var(--nc-border)"
                    strokeWidth={0.8}
                />
            ))}
            {/* Active note labels on white keys */}
            {whiteNotes.map((note, i) => (
                activeNotes.includes(note) ? (
                    <circle key={`wd-${note}`} cx={i * keyW + keyW / 2} cy={whiteH - 10} r={4}
                        fill="rgba(255,255,255,0.9)" />
                ) : null
            ))}
            {/* Black keys */}
            {blackNotes.map((note, i) => {
                if (note < 0) return null;
                const xPos = (i + (i >= 3 ? 1 : 0)) * keyW + keyW * 0.65;
                return (
                    <g key={`b-${note}`}>
                        <rect
                            x={xPos}
                            y={0}
                            width={keyW * 0.6}
                            height={blackH}
                            rx={2}
                            fill={activeNotes.includes(note) ? "var(--nc-secondary)" : "var(--nc-surface-3)"}
                            stroke="var(--nc-border)"
                            strokeWidth={0.5}
                        />
                        {activeNotes.includes(note) && (
                            <circle cx={xPos + keyW * 0.3} cy={blackH - 8} r={3}
                                fill="rgba(255,255,255,0.9)" />
                        )}
                    </g>
                );
            })}
        </svg>
    );
};

// ─── Guitar Diagram Component (Horizontal Layout) ───
// Strings run horizontally (high e at top, low E at bottom)
// Frets run vertically (nut on left)
const GuitarDiagram = ({ shape, startFret, showNut }) => {
    const { frets, barre } = shape;
    const stringSpacing = 16;
    const fretSpacing = 22;
    const leftMargin = 30;
    const topMargin = 14;
    const numFrets = 5;
    const numStrings = 6;
    const diagramW = leftMargin + numFrets * fretSpacing + 20;
    const diagramH = topMargin + (numStrings - 1) * stringSpacing + 18;

    // Fret dot positions (standard guitar markers)
    const fretDots = [3, 5, 7, 9];
    const doubleDot = [12];

    // String index 0 = low E (bottom), 5 = high e (top)
    // Display: reversed so high e is at top
    const stringY = (idx) => topMargin + (numStrings - 1 - idx) * stringSpacing;

    return (
        <svg viewBox={`0 0 ${diagramW} ${diagramH}`} className="w-52 h-28 drop-shadow-md">
            {/* Start fret label */}
            {!showNut && (
                <text x={leftMargin + fretSpacing / 2} y={topMargin - 3}
                    fontSize="8" fontWeight="800" fill="var(--nc-text-muted)"
                    textAnchor="middle" fontFamily="'JetBrains Mono', monospace">
                    {startFret}fr
                </text>
            )}

            {/* Nut or thin line (left side) */}
            {showNut ? (
                <rect x={leftMargin - 3} y={topMargin - 3}
                    width="5" height={(numStrings - 1) * stringSpacing + 6}
                    fill="var(--nc-text)" rx="2" />
            ) : (
                <line x1={leftMargin} y1={topMargin - 3}
                    x2={leftMargin} y2={topMargin + (numStrings - 1) * stringSpacing + 3}
                    stroke="var(--nc-text-muted)" strokeWidth="2" />
            )}

            {/* Fret lines (vertical) */}
            {Array.from({ length: numFrets + 1 }, (_, i) => (
                <line key={`f-${i}`}
                    x1={leftMargin + i * fretSpacing} y1={topMargin - 3}
                    x2={leftMargin + i * fretSpacing} y2={topMargin + (numStrings - 1) * stringSpacing + 3}
                    stroke="var(--nc-border)" strokeWidth={i === 0 ? 0 : 1.2} />
            ))}

            {/* Fret position dots */}
            {Array.from({ length: numFrets }, (_, i) => {
                const actualFret = startFret + i;
                const cx = leftMargin + i * fretSpacing + fretSpacing / 2;
                const midY = topMargin + (numStrings - 1) * stringSpacing / 2;
                if (fretDots.includes(actualFret)) {
                    return <circle key={`fd-${i}`} cx={cx} cy={midY} r="2.5"
                        fill="var(--nc-border)" opacity={0.4} />;
                }
                if (doubleDot.includes(actualFret)) {
                    return (
                        <g key={`fd-${i}`}>
                            <circle cx={cx} cy={midY - stringSpacing * 1.25} r="2.5"
                                fill="var(--nc-border)" opacity={0.4} />
                            <circle cx={cx} cy={midY + stringSpacing * 1.25} r="2.5"
                                fill="var(--nc-border)" opacity={0.4} />
                        </g>
                    );
                }
                return null;
            })}

            {/* Strings (horizontal) — thicker for bass strings (bottom) */}
            {[0, 1, 2, 3, 4, 5].map(i => (
                <line key={`s-${i}`}
                    x1={leftMargin} y1={stringY(i)}
                    x2={leftMargin + numFrets * fretSpacing} y2={stringY(i)}
                    stroke="var(--nc-text-ghost)"
                    strokeWidth={i < 3 ? 1.6 - i * 0.2 : 0.8}
                    strokeLinecap="round" />
            ))}

            {/* Barre chord indicator */}
            {barre && (() => {
                const barreDisplayFret = barre - startFret;
                const barreStrings = frets.reduce((acc, f, idx) => {
                    if (f >= barre) acc.push(idx);
                    return acc;
                }, []);
                const firstStr = Math.min(...barreStrings);
                const lastStr = Math.max(...barreStrings);
                const barX = leftMargin + barreDisplayFret * fretSpacing + fretSpacing / 2;
                const y1 = stringY(lastStr);
                const y2 = stringY(firstStr);
                return (
                    <rect
                        x={barX - 5}
                        y={Math.min(y1, y2) - 3}
                        width="10"
                        height={Math.abs(y2 - y1) + 6}
                        rx="5"
                        fill="var(--nc-primary)"
                        opacity={0.85}
                    />
                );
            })()}

            {/* Finger positions */}
            {frets.map((fret, stringIdx) => {
                if (fret <= 0) return null;
                if (barre && fret === barre) return null;

                const displayFret = fret - startFret;
                return (
                    <circle
                        key={`dot-${stringIdx}`}
                        cx={leftMargin + displayFret * fretSpacing + fretSpacing / 2}
                        cy={stringY(stringIdx)}
                        r="5.5"
                        fill="var(--nc-accent)"
                        className="drop-shadow"
                    />
                );
            })}

            {/* Open / Mute indicators (left side) */}
            {frets.map((fret, stringIdx) => (
                <text
                    key={`ind-${stringIdx}`}
                    x={leftMargin - 10}
                    y={stringY(stringIdx) + 4}
                    textAnchor="middle"
                    fontSize="10"
                    fontWeight="900"
                    fill={fret === -1 ? "var(--nc-error)" : "var(--nc-accent)"}
                >
                    {fret === -1 ? "×" : (fret === 0 ? "○" : "")}
                </text>
            ))}
        </svg>
    );
};

// ─── Main InstrumentPanel ───
export const InstrumentPanel = ({ currentChord, transpose = 0, instrument = "guitar" }) => {
    // Apply transposition
    const transposed = transposeChord(currentChord, transpose);

    // Normalize chord name for lookup
    const cleanChord = (transposed || "").replace(/:maj7|:maj|:min7|:min|:m/g, (match) => {
        if (match === ":min" || match === ":m") return "m";
        if (match === ":min7") return "m7";
        if (match === ":maj7") return "maj7";
        return "";
    }).trim();

    // ─── Piano View ───
    if (instrument === "piano") {
        const pianoNotes = getPianoNotes(cleanChord);

        return (
            <div className="w-full flex flex-col items-center animate-in fade-in zoom-in duration-300">
                <div className="text-xl font-black text-[var(--nc-primary)] mb-4 tracking-tighter">
                    {cleanChord || "—"}
                </div>
                {pianoNotes.length > 0 ? (
                    <PianoKeyboard activeNotes={pianoNotes} />
                ) : (
                    <div className="p-4 rounded-lg text-[var(--nc-text-muted)] text-xs font-medium text-center"
                        style={{ background: 'var(--nc-surface-2)', border: '1px solid var(--nc-border)' }}>
                        No diagram
                    </div>
                )}
            </div>
        );
    }

    // ─── Guitar Diagram ───
    const shape = findChordShape(cleanChord);

    if (!shape) {
        return (
            <div className="w-full flex flex-col items-center">
                <div className="text-xl font-black text-[var(--nc-primary)] mb-4 tracking-tighter">
                    {cleanChord || "—"}
                </div>
                <div className="w-36 h-44 rounded-lg flex items-center justify-center text-[var(--nc-text-muted)] text-xs font-medium"
                    style={{ background: 'var(--nc-surface-2)', border: '1px solid var(--nc-border)' }}>
                    No Diagram
                </div>
            </div>
        );
    }

    const { frets } = shape;
    // Calculate start fret for display
    const nonZeroFrets = frets.filter(f => f > 0);
    const maxFret = nonZeroFrets.length > 0 ? Math.max(...nonZeroFrets) : 0;
    const minFret = nonZeroFrets.length > 0 ? Math.min(...nonZeroFrets) : 0;
    const startFret = maxFret > 5 ? minFret : 1;
    const showNut = startFret === 1;

    return (
        <div className="w-full flex flex-col items-center animate-in fade-in zoom-in duration-300">
            <div className="text-xl font-black text-[var(--nc-primary)] mb-4 tracking-tighter">
                {shape.name}
            </div>
            <GuitarDiagram shape={shape} startFret={startFret} showNut={showNut} />
        </div>
    );
};
