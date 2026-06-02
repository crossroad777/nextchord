// format: frets: [lowE, A, D, G, B, highE]. 
// -1 means muted (x), 0 means open string (o). 
// baseFret: starting fret number (default 1).
// barre: { fret, from, to }

export const CHORD_DICTIONARY = {
  "C": { frets: [-1, 3, 2, 0, 1, 0] },
  "C7": { frets: [-1, 3, 2, 3, 1, 0] },
  "CM7": { frets: [-1, 3, 2, 0, 0, 0] },
  "Cm": { frets: [-1, 3, 5, 5, 4, 3], baseFret: 3, barre: { fret: 3, from: 1, to: 5 } },
  "Cm7": { frets: [-1, 3, 5, 3, 4, 3], baseFret: 3, barre: { fret: 3, from: 1, to: 5 } },
  "Csus4": { frets: [-1, 3, 3, 0, 1, 0] },

  "C#": { frets: [-1, 4, 6, 6, 6, 4], baseFret: 4, barre: { fret: 4, from: 1, to: 5 } },
  "C#m": { frets: [-1, 4, 6, 6, 5, 4], baseFret: 4, barre: { fret: 4, from: 1, to: 5 } },
  "C#m7": { frets: [-1, 4, 6, 4, 5, 4], baseFret: 4, barre: { fret: 4, from: 1, to: 5 } },
  
  "D": { frets: [-1, -1, 0, 2, 3, 2] },
  "D7": { frets: [-1, -1, 0, 2, 1, 2] },
  "DM7": { frets: [-1, -1, 0, 2, 2, 2] },
  "Dm": { frets: [-1, -1, 0, 2, 3, 1] },
  "Dm7": { frets: [-1, -1, 0, 2, 1, 1] },
  "Dsus4": { frets: [-1, -1, 0, 2, 3, 3] },

  "D#": { frets: [-1, 6, 8, 8, 8, 6], baseFret: 6, barre: { fret: 6, from: 1, to: 5 } },
  "Eb": { frets: [-1, 6, 8, 8, 8, 6], baseFret: 6, barre: { fret: 6, from: 1, to: 5 } },

  "E": { frets: [0, 2, 2, 1, 0, 0] },
  "E7": { frets: [0, 2, 0, 1, 0, 0] },
  "EM7": { frets: [0, 2, 1, 1, 0, 0] },
  "Em": { frets: [0, 2, 2, 0, 0, 0] },
  "Em7": { frets: [0, 2, 0, 0, 0, 0] },
  "Esus4": { frets: [0, 2, 2, 2, 0, 0] },

  "F": { frets: [1, 3, 3, 2, 1, 1], barre: { fret: 1, from: 0, to: 5 } },
  "F7": { frets: [1, 3, 1, 2, 1, 1], barre: { fret: 1, from: 0, to: 5 } },
  "FM7": { frets: [-1, -1, 3, 2, 1, 0] },
  "Fm": { frets: [1, 3, 3, 1, 1, 1], barre: { fret: 1, from: 0, to: 5 } },
  "Fm7": { frets: [1, 3, 1, 1, 1, 1], barre: { fret: 1, from: 0, to: 5 } },
  
  "F#": { frets: [2, 4, 4, 3, 2, 2], barre: { fret: 2, from: 0, to: 5 } },
  "F#m": { frets: [2, 4, 4, 2, 2, 2], barre: { fret: 2, from: 0, to: 5 } },
  "F#m7": { frets: [2, 4, 2, 2, 2, 2], barre: { fret: 2, from: 0, to: 5 } },
  "Gb": { frets: [2, 4, 4, 3, 2, 2], barre: { fret: 2, from: 0, to: 5 } },

  "G": { frets: [3, 2, 0, 0, 0, 3] },
  "G7": { frets: [3, 2, 0, 0, 0, 1] },
  "GM7": { frets: [3, 2, 0, 0, 0, 2] },
  "Gm": { frets: [3, 5, 5, 3, 3, 3], baseFret: 3, barre: { fret: 3, from: 0, to: 5 } },
  "Gm7": { frets: [3, 5, 3, 3, 3, 3], baseFret: 3, barre: { fret: 3, from: 0, to: 5 } },
  "Gsus4": { frets: [3, 3, 0, 0, 1, 3] }, // optional, or 3 x 0 0 1 3

  "G#": { frets: [4, 6, 6, 5, 4, 4], baseFret: 4, barre: { fret: 4, from: 0, to: 5 } },
  "Ab": { frets: [4, 6, 6, 5, 4, 4], baseFret: 4, barre: { fret: 4, from: 0, to: 5 } },
  "G#m": { frets: [4, 6, 6, 4, 4, 4], baseFret: 4, barre: { fret: 4, from: 0, to: 5 } },
  
  "A": { frets: [-1, 0, 2, 2, 2, 0] },
  "A7": { frets: [-1, 0, 2, 0, 2, 0] },
  "AM7": { frets: [-1, 0, 2, 1, 2, 0] },
  "Am": { frets: [-1, 0, 2, 2, 1, 0] },
  "Am7": { frets: [-1, 0, 2, 0, 1, 0] },
  "Asus4": { frets: [-1, 0, 2, 2, 3, 0] },
  
  "A#": { frets: [-1, 1, 3, 3, 3, 1], barre: { fret: 1, from: 1, to: 5 } },
  "Bb": { frets: [-1, 1, 3, 3, 3, 1], barre: { fret: 1, from: 1, to: 5 } },
  "Bbm": { frets: [-1, 1, 3, 3, 2, 1], barre: { fret: 1, from: 1, to: 5 } },
  
  "B": { frets: [-1, 2, 4, 4, 4, 2], barre: { fret: 2, from: 1, to: 5 } },
  "B7": { frets: [-1, 2, 1, 2, 0, 2] },
  "BM7": { frets: [-1, 2, 4, 3, 4, 2] },
  "Bm": { frets: [-1, 2, 4, 4, 3, 2], barre: { fret: 2, from: 1, to: 5 } },
  "Bm7": { frets: [-1, 2, 0, 2, 0, 2] },
  "Bm7b5": { frets: [-1, 2, 3, 2, 3, -1] }
};

export function getChordFingering(chordName) {
    if (!chordName) return null;
    
    // Normalize simple things if needed, but for now exact match
    let key = chordName;
    if (CHORD_DICTIONARY[key]) {
        return CHORD_DICTIONARY[key];
    }
    
    // Handle bass chords e.g. C/E or C/G
    if (key.includes('/')) {
        const root = key.split('/')[0];
        if (CHORD_DICTIONARY[root]) {
            // Return root chord for now, as drawing bass chords exactly is hard
            return CHORD_DICTIONARY[root];
        }
    }
    
    // Fallback: strip 'add9', 'sus4', 'dim', 'aug' if not found
    const simplified = key.replace(/(add9|dim|aug|sus4|\(\d+\))/g, '');
    if (simplified !== key && CHORD_DICTIONARY[simplified]) {
        return CHORD_DICTIONARY[simplified];
    }
    
    // Final fallback to major/minor
    const match = key.match(/^([A-G][#b]?m?)/);
    if (match && CHORD_DICTIONARY[match[1]]) {
        return CHORD_DICTIONARY[match[1]];
    }

    return null;
}
