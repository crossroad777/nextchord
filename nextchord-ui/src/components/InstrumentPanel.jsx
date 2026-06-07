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

    // dim
    "Cdim": { name: "Cdim", frets: [-1, 3, 4, 5, 4, -1] },
    "C#dim": { name: "C♯dim", frets: [-1, 4, 5, 6, 5, -1] },
    "Dbdim": { name: "D♭dim", frets: [-1, 4, 5, 6, 5, -1] },
    "Ddim": { name: "Ddim", frets: [-1, -1, 0, 1, 3, 1] },
    "D#dim": { name: "D♯dim", frets: [-1, -1, 1, 2, 4, 2] },
    "Ebdim": { name: "E♭dim", frets: [-1, -1, 1, 2, 4, 2] },
    "Edim": { name: "Edim", frets: [-1, -1, 2, 3, 5, 3] },
    "Fdim": { name: "Fdim", frets: [-1, -1, 3, 4, 6, 4] },
    "F#dim": { name: "F♯dim", frets: [2, -1, 0, 2, 1, 2] },
    "Gbdim": { name: "G♭dim", frets: [2, -1, 0, 2, 1, 2] },
    "Gdim": { name: "Gdim", frets: [-1, -1, 5, 6, 8, 6] },
    "G#dim": { name: "G♯dim", frets: [-1, -1, 6, 7, 9, 7] },
    "Abdim": { name: "A♭dim", frets: [-1, -1, 6, 7, 9, 7] },
    "Adim": { name: "Adim", frets: [-1, 0, 1, 2, 1, -1] },
    "A#dim": { name: "A♯dim", frets: [-1, 1, 2, 3, 2, -1] },
    "Bbdim": { name: "B♭dim", frets: [-1, 1, 2, 3, 2, -1] },
    "Bdim": { name: "Bdim", frets: [-1, 2, 3, 4, 3, -1] },

    // dim7
    "Cdim7": { name: "Cdim7", frets: [-1, 3, 4, 2, 4, -1] },
    "C#dim7": { name: "C♯dim7", frets: [-1, 4, 5, 3, 5, -1] },
    "Dbdim7": { name: "D♭dim7", frets: [-1, 4, 5, 3, 5, -1] },
    "Ddim7": { name: "Ddim7", frets: [-1, -1, 0, 1, 0, 1] },
    "D#dim7": { name: "D♯dim7", frets: [-1, -1, 1, 2, 1, 2] },
    "Ebdim7": { name: "E♭dim7", frets: [-1, -1, 1, 2, 1, 2] },
    "Edim7": { name: "Edim7", frets: [-1, -1, 2, 3, 2, 3] },
    "Fdim7": { name: "Fdim7", frets: [-1, -1, 3, 4, 3, 4] },
    "F#dim7": { name: "F♯dim7", frets: [2, -1, 1, 2, 1, -1] },
    "Gbdim7": { name: "G♭dim7", frets: [2, -1, 1, 2, 1, -1] },
    "Gdim7": { name: "Gdim7", frets: [3, -1, 2, 3, 2, -1] },
    "G#dim7": { name: "G♯dim7", frets: [4, -1, 3, 4, 3, -1] },
    "Abdim7": { name: "A♭dim7", frets: [4, -1, 3, 4, 3, -1] },
    "Adim7": { name: "Adim7", frets: [-1, 0, 1, 0, 1, -1] },
    "A#dim7": { name: "A♯dim7", frets: [-1, 1, 2, 0, 2, -1] },
    "Bbdim7": { name: "B♭dim7", frets: [-1, 1, 2, 0, 2, -1] },
    "Bdim7": { name: "Bdim7", frets: [-1, 2, 3, 1, 3, -1] },

    // aug
    "Caug": { name: "Caug", frets: [-1, 3, 2, 1, 1, 0] },
    "C#aug": { name: "C♯aug", frets: [-1, 4, 3, 2, 2, -1] },
    "Dbaug": { name: "D♭aug", frets: [-1, 4, 3, 2, 2, -1] },
    "Daug": { name: "Daug", frets: [-1, -1, 0, 3, 3, 2] },
    "D#aug": { name: "D♯aug", frets: [-1, -1, 1, 0, 0, 3] },
    "Ebaug": { name: "E♭aug", frets: [-1, -1, 1, 0, 0, 3] },
    "Eaug": { name: "Eaug", frets: [0, 3, 2, 1, 1, 0] },
    "Faug": { name: "Faug", frets: [-1, -1, 3, 2, 2, 1] },
    "F#aug": { name: "F♯aug", frets: [-1, -1, 4, 3, 3, 2] },
    "Gbaug": { name: "G♭aug", frets: [-1, -1, 4, 3, 3, 2] },
    "Gaug": { name: "Gaug", frets: [3, 2, 1, 0, 0, 3] },
    "G#aug": { name: "G♯aug", frets: [-1, -1, 6, 5, 5, 4] },
    "Abaug": { name: "A♭aug", frets: [-1, -1, 6, 5, 5, 4] },
    "Aaug": { name: "Aaug", frets: [-1, 0, 3, 2, 2, 1] },
    "A#aug": { name: "A♯aug", frets: [-1, 1, 4, 3, 3, 2] },
    "Bbaug": { name: "B♭aug", frets: [-1, 1, 4, 3, 3, 2] },
    "Baug": { name: "Baug", frets: [-1, 2, 5, 4, 4, 3] },

    // m6
    "Cm6": { name: "Cm6", frets: [-1, 3, 1, 2, 1, 3] },
    "C#m6": { name: "C♯m6", frets: [-1, 4, 2, 3, 2, 4] },
    "Dbm6": { name: "D♭m6", frets: [-1, 4, 2, 3, 2, 4] },
    "Dm6": { name: "Dm6", frets: [-1, -1, 0, 2, 0, 1] },
    "D#m6": { name: "D♯m6", frets: [-1, -1, 1, 3, 1, 2] },
    "Ebm6": { name: "E♭m6", frets: [-1, -1, 1, 3, 1, 2] },
    "Em6": { name: "Em6", frets: [0, 2, 2, 0, 2, 0] },
    "Fm6": { name: "Fm6", frets: [1, -1, 0, 1, 1, 1] },
    "F#m6": { name: "F♯m6", frets: [2, -1, 1, 2, 2, 2] },
    "Gbm6": { name: "G♭m6", frets: [2, -1, 1, 2, 2, 2] },
    "Gm6": { name: "Gm6", frets: [3, -1, 2, 3, 3, 3] },
    "G#m6": { name: "G♯m6", frets: [4, -1, 3, 4, 4, 4] },
    "Abm6": { name: "A♭m6", frets: [4, -1, 3, 4, 4, 4] },
    "Am6": { name: "Am6", frets: [-1, 0, 2, 2, 1, 2] },
    "A#m6": { name: "A♯m6", frets: [-1, 1, 3, 0, 2, 1] },
    "Bbm6": { name: "B♭m6", frets: [-1, 1, 3, 0, 2, 1] },
    "Bm6": { name: "Bm6", frets: [-1, 2, 0, 1, 0, 2] },

    // 6
    "C6": { name: "C6", frets: [-1, 3, 2, 2, 1, 0] },
    "C#6": { name: "C♯6", frets: [-1, 4, 3, 3, 2, 4] },
    "Db6": { name: "D♭6", frets: [-1, 4, 3, 3, 2, 4] },
    "D6": { name: "D6", frets: [-1, -1, 0, 2, 0, 2] },
    "D#6": { name: "D♯6", frets: [-1, -1, 1, 3, 1, 3] },
    "Eb6": { name: "E♭6", frets: [-1, -1, 1, 3, 1, 3] },
    "E6": { name: "E6", frets: [0, 2, 2, 1, 2, 0] },
    "F6": { name: "F6", frets: [1, -1, 0, 2, 1, 1] },
    "F#6": { name: "F♯6", frets: [2, -1, 1, 3, 2, 2] },
    "Gb6": { name: "G♭6", frets: [2, -1, 1, 3, 2, 2] },
    "G6": { name: "G6", frets: [3, 2, 0, 0, 0, 0] },
    "G#6": { name: "G♯6", frets: [4, -1, 3, 5, 4, 4] },
    "Ab6": { name: "A♭6", frets: [4, -1, 3, 5, 4, 4] },
    "A6": { name: "A6", frets: [-1, 0, 2, 2, 2, 2] },
    "A#6": { name: "A♯6", frets: [-1, 1, 3, 3, 3, 3] },
    "Bb6": { name: "B♭6", frets: [-1, 1, 3, 3, 3, 3] },
    "B6": { name: "B6", frets: [-1, 2, 4, 4, 4, 4] },

    // m7b5
    "Cm7b5": { name: "Cm7(♭5)", frets: [-1, 3, 4, 3, 4, -1] },
    "C#m7b5": { name: "C♯m7(♭5)", frets: [-1, 4, 5, 4, 5, -1] },
    "Dbm7b5": { name: "D♭m7(♭5)", frets: [-1, 4, 5, 4, 5, -1] },
    "Dm7b5": { name: "Dm7(♭5)", frets: [-1, 5, 6, 5, 6, -1] },
    "D#m7b5": { name: "D♯m7(♭5)", frets: [-1, 6, 7, 6, 7, -1] },
    "Ebm7b5": { name: "E♭m7(♭5)", frets: [-1, 6, 7, 6, 7, -1] },
    "Em7b5": { name: "Em7(♭5)", frets: [-1, 7, 8, 7, 8, -1] },
    "Fm7b5": { name: "Fm7(♭5)", frets: [-1, 8, 9, 8, 9, -1] },
    "F#m7b5": { name: "F♯m7(♭5)", frets: [2, -1, 2, 2, 1, -1] },
    "Gbm7b5": { name: "G♭m7(♭5)", frets: [2, -1, 2, 2, 1, -1] },
    "Gm7b5": { name: "Gm7(♭5)", frets: [3, -1, 3, 3, 2, -1] },
    "G#m7b5": { name: "G♯m7(♭5)", frets: [4, -1, 4, 4, 3, -1] },
    "Abm7b5": { name: "A♭m7(♭5)", frets: [4, -1, 4, 4, 3, -1] },
    "Am7b5": { name: "Am7(♭5)", frets: [5, -1, 5, 5, 4, -1] },
    "A#m7b5": { name: "A♯m7(♭5)", frets: [-1, 1, 2, 1, 2, -1] },
    "Bbm7b5": { name: "B♭m7(♭5)", frets: [-1, 1, 2, 1, 2, -1] },
    "Bm7b5": { name: "Bm7(♭5)", frets: [-1, 2, 3, 2, 3, -1] },
};

// ─── Custom Tuning Chord Databases ───
const DADGAD_CHORD_SHAPES = {
    // Major
    "C": { name: "C", frets: [-1, 3, 2, 0, 3, 2] },
    "D": { name: "D", frets: [0, 0, 0, 2, 0, 0] },
    "E": { name: "E", frets: [2, 2, 2, 1, 2, 2] },
    "F": { name: "F", frets: [3, 3, 3, 2, 0, 3] },
    "G": { name: "G", frets: [5, -1, 0, 0, 2, 0] },
    "A": { name: "A", frets: [-1, 0, 2, 2, 4, 2] },
    "B": { name: "B", frets: [-1, 2, 4, 4, 6, 4] },
    
    // Minor
    "Cm": { name: "Cm", frets: [-1, 3, 1, 0, 3, 1] },
    "Dm": { name: "Dm", frets: [0, 0, 0, 1, 0, 0] },
    "Em": { name: "Em", frets: [2, 2, 2, 0, 2, 2] },
    "Fm": { name: "Fm", frets: [3, 3, 3, 1, 3, 3] },
    "Gm": { name: "Gm", frets: [5, 5, 5, 3, 5, 5] },
    "Am": { name: "Am", frets: [-1, 0, 2, 2, 3, 2] },
    "Bm": { name: "Bm", frets: [-1, 2, 4, 4, 5, 4] },
    
    // 7th
    "C7": { name: "C7", frets: [-1, 3, 2, 3, 1, 2] },
    "D7": { name: "D7", frets: [0, 0, 0, 2, 3, 0] },
    "E7": { name: "E7", frets: [2, 2, 0, 1, 2, 0] },
    "F7": { name: "F7", frets: [3, 3, 1, 2, 3, 1] },
    "G7": { name: "G7", frets: [5, 5, 3, 4, 5, 3] },
    "A7": { name: "A7", frets: [-1, 0, 2, 0, 0, 2] },
    "B7": { name: "B7", frets: [-1, 2, 1, 2, 0, 1] },

    // Maj7 / Min7
    "Cmaj7": { name: "Cmaj7", frets: [-1, 3, 2, 0, 2, 2] },
    "Dmaj7": { name: "Dmaj7", frets: [0, 0, 0, 2, 4, 0] },
    "Fmaj7": { name: "Fmaj7", frets: [3, 3, 2, 2, 0, 0] },
    "Gmaj7": { name: "Gmaj7", frets: [5, 5, 4, 4, 0, 0] },
    "Amaj7": { name: "Amaj7", frets: [-1, 0, 2, 1, 0, 2] },
    "Am7": { name: "Am7", frets: [-1, 0, 2, 0, 3, 2] },
    "Bm7": { name: "Bm7", frets: [-1, 2, 0, 2, 0, 0] },
    "Cm7": { name: "Cm7", frets: [-1, 3, 1, 3, 1, 1] },
    "Dm7": { name: "Dm7", frets: [0, 0, 0, 2, 1, 0] },
    "Em7": { name: "Em7", frets: [2, 2, 0, 0, 2, 0] },
};

const OPENG_CHORD_SHAPES = {
    "G": { name: "G", frets: [0, 0, 0, 0, 0, 0] },
    "A": { name: "A", frets: [-1, 2, 2, 2, 2, 2], barre: 2 },
    "B": { name: "B", frets: [-1, 4, 4, 4, 4, 4], barre: 4 },
    "C": { name: "C", frets: [-1, 5, 5, 5, 5, 5], barre: 5 },
    "D": { name: "D", frets: [-1, 7, 7, 7, 7, 7], barre: 7 },
    "E": { name: "E", frets: [-1, 9, 9, 9, 9, 9], barre: 9 },
    "F": { name: "F", frets: [-1, 3, 3, 3, 3, 3], barre: 3 },
    "Em": { name: "Em", frets: [2, 0, 2, 0, 0, 2] },
    "Am": { name: "Am", frets: [-1, 2, 2, 2, 1, 2] },
    "Bm": { name: "Bm", frets: [-1, 4, 4, 4, 3, 4] },
};

const OPEND_CHORD_SHAPES = {
    "D": { name: "D", frets: [0, 0, 0, 0, 0, 0] },
    "E": { name: "E", frets: [2, 2, 2, 2, 2, 2], barre: 2 },
    "F": { name: "F", frets: [3, 3, 3, 3, 3, 3], barre: 3 },
    "F#": { name: "F#", frets: [4, 4, 4, 4, 4, 4], barre: 4 },
    "G": { name: "G", frets: [5, 5, 5, 5, 5, 5], barre: 5 },
    "A": { name: "A", frets: [7, 7, 7, 7, 7, 7], barre: 7 },
    "B": { name: "B", frets: [9, 9, 9, 9, 9, 9], barre: 9 },
    "C": { name: "C", frets: [10, 10, 10, 10, 10, 10], barre: 10 },
    "Em": { name: "Em", frets: [2, 2, 2, 1, 2, 2] },
    "F#m": { name: "F#m", frets: [4, 4, 4, 3, 4, 4] },
    "Gm": { name: "Gm", frets: [5, 5, 5, 4, 5, 5] },
    "Am": { name: "Am", frets: [7, 7, 7, 6, 7, 7] },
    "Bm": { name: "Bm", frets: [9, 9, 9, 8, 9, 9] },
    "C#m": { name: "C#m", frets: [11, 11, 11, 10, 11, 11] },
};

function findChordShape(chordName, tuning = "standard") {
    if (!chordName || chordName === "N.C.") return null;

    const normalizedName = chordName
        .replace(/(Maj7|M7|major7)/g, 'maj7')
        .replace(/min7/g, 'm7')
        .replace(/m7\(b5\)/g, 'm7b5')
        .replace(/m7\(♭5\)/g, 'm7b5')
        .replace(/m7♭5/g, 'm7b5');

    let shape = null;
    const tuningDb = tuning === "dadgad" ? DADGAD_CHORD_SHAPES : 
                     tuning === "open_g" ? OPENG_CHORD_SHAPES : 
                     tuning === "open_d" ? OPEND_CHORD_SHAPES : null;

    // Helper for direct lookup and fallbacks in a specific database
    const lookupInDb = (db) => {
        if (db[normalizedName]) return db[normalizedName];

        const enharmonic = {
            "C#": "Db", "Db": "C#", "D#": "Eb", "Eb": "D#",
            "F#": "Gb", "Gb": "F#", "G#": "Ab", "Ab": "G#",
            "A#": "Bb", "Bb": "A#",
        };

        const match = normalizedName.match(/^([A-G][#b]?)(.*)$/);
        if (!match) return null;
        const [, root, quality] = match;

        const altRoot = enharmonic[root];
        if (altRoot && db[altRoot + quality]) {
            return db[altRoot + quality];
        }

        const fallbacks = [
            quality.replace("add9", ""),
            quality.replace("sus4", ""),
            quality.replace("sus2", ""),
            quality.replace("dim7", "dim"),
            quality.replace("aug7", "aug"),
            quality.replace("maj7", ""),
            quality.replace(/m7/, "m"),
            quality.replace(/7/, ""),
            quality.replace(/m/, ""),
        ];

        for (const fb of fallbacks) {
            if (db[root + fb]) return db[root + fb];
            if (altRoot && db[altRoot + fb]) return db[altRoot + fb];
        }
        return null;
    };

    // 1. Try to find in tuning-specific database first
    if (tuningDb) {
        shape = lookupInDb(tuningDb);
    }

    // 2. Fallback to standard database if not found
    if (!shape) {
        shape = lookupInDb(CHORD_SHAPES);
    }

    // 3. Drop D specific dynamic adaptation for standard shapes
    if (tuning === "drop_d" && shape) {
        const fretsCopy = [...shape.frets];
        if (fretsCopy[0] >= 0) {
            fretsCopy[0] += 2;
            shape = { ...shape, frets: fretsCopy };
        }
    }

    return shape;
}

// ─── Piano Chord Note Generator ───
// Dynamically compute piano notes from root + chord formula
const NOTE_MAP = { "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11 };

const CHORD_INTERVALS = {
    "": [0, 4, 7],            // major
    "m": [0, 3, 7],           // minor
    "7": [0, 4, 7, 10],       // dominant 7th
    "m7": [0, 3, 7, 10],      // minor 7th
    "Maj7": [0, 4, 7, 11],    // major 7th
    "maj7": [0, 4, 7, 11],    // major 7th
    "dim": [0, 3, 6],         // diminished
    "dim7": [0, 3, 6, 9],     // diminished 7th
    "m7(b5)": [0, 3, 6, 10],  // half-diminished 7th
    "m7b5": [0, 3, 6, 10],    // half-diminished 7th
    "mMaj7": [0, 3, 7, 11],   // minor-major 7th
    "mM7": [0, 3, 7, 11],     // minor-major 7th
    "aug": [0, 4, 8],         // augmented
    "sus4": [0, 5, 7],        // suspended 4th
    "sus2": [0, 2, 7],        // suspended 2nd
    "6": [0, 4, 7, 9],        // major 6th
    "m6": [0, 3, 7, 9],       // minor 6th
    "add9": [0, 4, 7, 14],    // add 9
    "9": [0, 4, 7, 10, 14],   // dominant 9th
    "m9": [0, 3, 7, 10, 14],  // minor 9th
};

function normalizeChordNameForDisplay(chordName) {
    if (!chordName || chordName === "N.C.") return "N.C.";
    
    // If it contains a colon, it's a raw BTC label; standardize it
    if (chordName.includes(":")) {
        const parts = chordName.split(":");
        const root = parts[0];
        let quality = parts[1];
        let slash = "";
        if (quality.includes("/")) {
            const qParts = quality.split("/");
            quality = qParts[0];
            slash = "/" + qParts[1];
        }
        
        const qualityMap = {
            "maj": "",
            "min": "m",
            "dim": "dim",
            "aug": "aug",
            "min6": "m6",
            "maj6": "6",
            "min7": "m7",
            "minmaj7": "mMaj7",
            "maj7": "Maj7",
            "7": "7",
            "dim7": "dim7",
            "hdim7": "m7(b5)",
            "sus2": "sus2",
            "sus4": "sus4",
        };
        const suffix = qualityMap[quality] !== undefined ? qualityMap[quality] : quality;
        return `${root}${suffix}${slash}`;
    }
    
    return chordName;
}

function getPianoNotes(chordName) {
    if (!chordName || chordName === "N.C.") return [];
    
    // Normalize raw chord names
    const cleanName = normalizeChordNameForDisplay(chordName);
    
    const match = cleanName.match(/^([A-G][#b]?)(.*)$/);
    if (!match) return [];
    const [, root, quality] = match;
    const rootNote = NOTE_MAP[root];
    if (rootNote === undefined) return [];

    const intervals = CHORD_INTERVALS[quality] || CHORD_INTERVALS[""];
    
    // Base notes: root position starting at rootNote (0-11)
    let notes = intervals.map(i => rootNote + i);
    
    // Shift the whole chord down by an octave if any note exceeds 2-octave range (23)
    // and if doing so keeps all notes >= 0.
    if (notes.some(n => n >= 24)) {
        if (notes.every(n => n - 12 >= 0)) {
            notes = notes.map(n => n - 12);
        }
    }
    
    // Wrap any remaining out-of-bounds notes individually (safeguard)
    notes = notes.map(n => {
        if (n >= 24) return n % 12 + 12; // keep in upper octave if possible
        if (n < 0) return (n + 24) % 12;
        return n;
    });

    // Sort notes for consistent display
    notes = [...new Set(notes)].sort((a, b) => a - b);
    return notes;
}

// ─── Piano Keyboard Component ───
const PianoKeyboard = ({ activeNotes = [] }) => {
    // 2 Octaves white keys: C4 to B5 (0 to 23 semitones)
    const whiteKeys = [
        { note: 0, label: "C" }, { note: 2, label: "D" }, { note: 4, label: "E" },
        { note: 5, label: "F" }, { note: 7, label: "G" }, { note: 9, label: "A" }, { note: 11, label: "B" },
        { note: 12, label: "C" }, { note: 14, label: "D" }, { note: 16, label: "E" },
        { note: 17, label: "F" }, { note: 19, label: "G" }, { note: 21, label: "A" }, { note: 23, label: "B" }
    ];

    // Black keys with their note indices and precise w_idx boundaries
    const blackKeys = [
        { note: 1, boundary: 1, label: "C#" },
        { note: 3, boundary: 2, label: "D#" },
        { note: 6, boundary: 4, label: "F#" },
        { note: 8, boundary: 5, label: "G#" },
        { note: 10, boundary: 6, label: "A#" },
        
        { note: 13, boundary: 8, label: "C#" },
        { note: 15, boundary: 9, label: "D#" },
        { note: 18, boundary: 11, label: "F#" },
        { note: 20, boundary: 12, label: "G#" },
        { note: 22, boundary: 13, label: "A#" }
    ];

    const keyW = 20;
    const totalW = whiteKeys.length * keyW;
    const whiteH = 80;
    const blackW = 12;
    const blackH = 50;

    return (
        <svg viewBox={`0 0 ${totalW} ${whiteH + 15}`} className="w-full max-w-[320px] drop-shadow-lg" style={{ overflow: 'visible' }}>
            <defs>
                {/* Active gradients */}
                <linearGradient id="whiteActiveGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#60A5FA" />
                    <stop offset="100%" stopColor="#2563EB" />
                </linearGradient>
                <linearGradient id="blackActiveGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#34D399" />
                    <stop offset="100%" stopColor="#059669" />
                </linearGradient>
                {/* Regular gradients for 3D feel */}
                <linearGradient id="whiteKeyGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#F9FAFB" />
                    <stop offset="85%" stopColor="#F3F4F6" />
                    <stop offset="100%" stopColor="#E5E7EB" />
                </linearGradient>
                <linearGradient id="blackKeyGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#374151" />
                    <stop offset="100%" stopColor="#111827" />
                </linearGradient>
            </defs>

            {/* White keys */}
            {whiteKeys.map((keyObj, i) => {
                const isActive = activeNotes.includes(keyObj.note);
                return (
                    <g key={`w-${keyObj.note}`}>
                        <rect
                            x={i * keyW}
                            y={0}
                            width={keyW - 0.5}
                            height={whiteH}
                            rx={2}
                            fill={isActive ? "url(#whiteActiveGrad)" : "url(#whiteKeyGrad)"}
                            stroke="#D1D5DB"
                            strokeWidth={0.5}
                            style={{ transition: 'fill 0.1s ease' }}
                        />
                        {/* Note label at the bottom of white key */}
                        <text
                            x={i * keyW + keyW / 2}
                            y={whiteH + 11}
                            fontSize="8"
                            fontWeight="bold"
                            fill={isActive ? "#3B82F6" : "#9CA3AF"}
                            textAnchor="middle"
                            fontFamily="sans-serif"
                        >
                            {keyObj.label}
                        </text>
                    </g>
                );
            })}

            {/* Black keys */}
            {blackKeys.map((keyObj) => {
                const isActive = activeNotes.includes(keyObj.note);
                const xPos = keyObj.boundary * keyW - blackW / 2;
                return (
                    <rect
                        key={`b-${keyObj.note}`}
                        x={xPos}
                        y={0}
                        width={blackW}
                        height={blackH}
                        rx={1.5}
                        fill={isActive ? "url(#blackActiveGrad)" : "url(#blackKeyGrad)"}
                        stroke="#111827"
                        strokeWidth={0.5}
                        style={{ transition: 'fill 0.1s ease', zIndex: 10 }}
                    />
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
export const InstrumentPanel = ({ currentChord, transpose = 0, instrument = "guitar", tuning = "standard" }) => {
    // Apply transposition
    const transposed = transposeChord(currentChord, transpose);

    // Normalize chord name for lookup
    const cleanChord = normalizeChordNameForDisplay(transposed);

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
    const shape = findChordShape(cleanChord, tuning);

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

export { GuitarDiagram, findChordShape, PianoKeyboard, getPianoNotes };
