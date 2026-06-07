import React, { useMemo, useRef, useEffect, useLayoutEffect, useState } from 'react';
import TinySegmenter from 'tiny-segmenter';
import { initTokenizer, isTokenizerReady, resegmentWords, computeBreaks } from '../utils/kuromojiTokenizer';

const _seg = new TinySegmenter();

const isRhythmText = (text) => {
    if (!text) return true;
    const clean = text.replace(/[ \-\=>|≧○o0~^vVx×\(\)\.\*\/_]/g, '');
    return clean.length === 0;
};

const NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const NOTES_FLAT = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];

function transposeChord(chord, semitones) {
    if (!chord || chord === 'N.C.' || semitones === 0) return chord;
    return chord.replace(/^([A-G][#b]?)/, (_, root) => {
        let idx = NOTES.indexOf(root);
        if (idx < 0) idx = NOTES_FLAT.indexOf(root);
        if (idx < 0) return root;
        return NOTES[(idx + semitones + 120) % 12];
    });
}

function cleanJapaneseText(text) {
    if (!text) return '';
    return text.replace(/[\r\n\t]/g, '').replace(/ {2,}/g, ' ').trim();
}

import { GuitarDiagram, findChordShape } from './InstrumentPanel';

// ── Word-timestamp based chord assignment ─────────────────────────────────
// Rule: chord change → assign to the first word that STARTS at or after the chord time
const MAX_CHORDS_PER_LINE = 4;

/**
 * Collect all chord changes relevant to a phrase, then assign each to a word.
 * - First chord: the chord playing at phrase start → goes to word 0
 * - Subsequent chords: each assigned to the first word starting >= chord change time
 * - Conflict: if two chords map to the same word, second one moves to next word
 */
function assignChordsToWords(phraseStart, phraseEnd, words, chordTimeline) {
    if (!words?.length || !chordTimeline?.length) return [];

    // 1. Collect relevant chords with REAL times
    let startChord = null;
    for (const c of chordTimeline) {
        if (c.time <= phraseStart) startChord = c;
        else break;
    }
    const changes = [];
    for (const c of chordTimeline) {
        if (c.time > phraseStart && c.time <= phraseEnd) {
            changes.push(c);
        }
    }

    // Build all chords list (deduped consecutive same chord)
    const allChords = [];
    if (startChord) allChords.push(startChord);
    for (const ch of changes) {
        if (!allChords.length || allChords[allChords.length - 1].chord !== ch.chord) {
            allChords.push(ch);
        }
    }
    if (allChords.length === 0) return [];

    // 2. Try timestamp-based assignment first
    const assignments = [];
    let nextChordQueue = []; // chords that couldn't be placed by time

    // First chord → word 0
    assignments.push({ wordIdx: 0, chord: allChords[0].chord, time: allChords[0].time });

    for (let ci = 1; ci < allChords.length; ci++) {
        const ch = allChords[ci];
        let targetIdx = -1;
        for (let wi = 0; wi < words.length; wi++) {
            const ws = words[wi].start ?? words[wi].s;
            if (ws >= ch.time) {
                targetIdx = wi;
                break;
            }
        }

        if (targetIdx < 0) {
            // No word starts at/after chord time → timestamps collapsed
            nextChordQueue.push(ch);
            continue;
        }

        // Conflict: push forward
        const lastIdx = assignments.length > 0 ? assignments[assignments.length - 1].wordIdx : -1;
        if (targetIdx <= lastIdx) targetIdx = lastIdx + 1;

        if (targetIdx < words.length) {
            assignments.push({ wordIdx: targetIdx, chord: ch.chord, time: ch.time });
        } else {
            nextChordQueue.push(ch);
        }
    }

    // 3. Distribute unplaced chords proportionally by chord timing
    if (nextChordQueue.length > 0) {
        const lastPlacedIdx = assignments.length > 0 ? assignments[assignments.length - 1].wordIdx : -1;
        const lastPlacedTime = assignments.length > 0 ? assignments[assignments.length - 1].time : phraseStart;
        const remainingWords = words.length - lastPlacedIdx - 1;
        const lastChordTime = nextChordQueue[nextChordQueue.length - 1].time;
        const timeSpan = lastChordTime - lastPlacedTime;
        
        if (remainingWords > 0 && timeSpan > 0) {
            for (const ch of nextChordQueue) {
                const ratio = (ch.time - lastPlacedTime) / timeSpan;
                let pos = lastPlacedIdx + 1 + Math.floor(ratio * (remainingWords - 1));
                // Ensure monotonic increase
                const prevIdx = assignments[assignments.length - 1].wordIdx;
                if (pos <= prevIdx) pos = prevIdx + 1;
                if (pos < words.length) {
                    assignments.push({ wordIdx: pos, chord: ch.chord, time: ch.time });
                }
            }
        }
    }

    return assignments;
}

/**
 * Split a phrase into display lines — one line per 4 bars.
 * Core principle: BAR (小節) is the fundamental unit.
 * - Each chord = 1 bar
 * - 4 bars = 1 line
 * - Word times are estimated from BPM when timestamps collapse
 * - Bar boundaries (chord times) determine where lyrics split
 *
 * When barPositions is provided, uses actual detected bar boundaries
 * instead of BPM-calculated grid for much more accurate alignment.
 */
const BARS_PER_LINE = 4;

function splitPhraseWithWords(phraseText, phraseWords, phraseStart, phraseEnd, chordAssignments, barDur, phraseBreaks, barPositions) {
    if (!phraseText || chordAssignments.length === 0) return [];

    // Dedup consecutive same-chord
    const chords = [];
    for (const a of chordAssignments) {
        if (!chords.length || chords[chords.length - 1].chord !== a.chord) {
            chords.push(a);
        }
    }

    // ── Estimate word times ──
    // Use real timestamps where available; interpolate collapsed ones
    const totalWords = phraseWords.length;
    const lastChordTime = chords[chords.length - 1].time;
    const singingEnd = lastChordTime + barDur; // last chord lasts 1 bar

    // Find last word with a real (non-collapsed) timestamp
    let lastRealIdx = 0;
    for (let i = 1; i < totalWords; i++) {
        const t = phraseWords[i].start ?? phraseWords[i].s;
        const prev = phraseWords[i - 1].start ?? phraseWords[i - 1].s;
        if (t > prev + 0.05) lastRealIdx = i;
    }

    const wordTimes = [];
    // Real timestamps
    for (let i = 0; i <= lastRealIdx; i++) {
        wordTimes[i] = phraseWords[i].start ?? phraseWords[i].s;
    }
    // Interpolate collapsed words from lastRealIdx to singingEnd
    if (lastRealIdx < totalWords - 1) {
        const tStart = wordTimes[lastRealIdx];
        const tEnd = singingEnd;
        const count = totalWords - lastRealIdx; // includes lastRealIdx as anchor
        for (let i = lastRealIdx + 1; i < totalWords; i++) {
            wordTimes[i] = tStart + ((i - lastRealIdx) / count) * (tEnd - tStart);
        }
    }

    // Check for timestamp regressions (regression means abnormal matched words, e.g. duplicate match)
    let hasTimeRegression = false;
    for (let i = 1; i < wordTimes.length; i++) {
        if (wordTimes[i] < wordTimes[i - 1] - 0.01) {
            hasTimeRegression = true;
            break;
        }
    }
    if (hasTimeRegression) {
        return splitPhraseByRatio(phraseText, phraseStart, phraseEnd, chords);
    }

    // ── Build word character positions ──
    const wordPositions = [];
    let cp = 0;
    for (const w of phraseWords) {
        const t = w.word ?? w.w ?? '';
        wordPositions.push({ start: cp, end: cp + t.length });
        cp += t.length;
    }

    // ── TIME-BASED LINE SPLITTING ──
    // When barPositions is available, use actual detected bar boundaries.
    // Otherwise fall back to BPM-calculated grid.
    const firstChordTime = chords[0].time;

    // Build line time boundaries from actual bar positions or BPM grid
    let lineRanges = [];
    if (barPositions?.length > 1) {
        // Find the bar index closest to the first chord
        let startBarIdx = 0;
        for (let i = 0; i < barPositions.length; i++) {
            if (barPositions[i] <= firstChordTime + 0.05) startBarIdx = i;
            else break;
        }
        // Build 4-bar groups from actual bar positions
        for (let i = startBarIdx; i < barPositions.length; i += BARS_PER_LINE) {
            const ls = barPositions[i];
            const le = (i + BARS_PER_LINE < barPositions.length)
                ? barPositions[i + BARS_PER_LINE]
                : (barPositions[barPositions.length - 1] + barDur * BARS_PER_LINE);
            if (ls >= singingEnd) break;
            lineRanges.push([ls, le]);
        }
    }
    // Fallback: BPM-calculated grid
    if (lineRanges.length === 0) {
        const lineDur = barDur * BARS_PER_LINE;
        const barNumber = Math.floor(firstChordTime / barDur);
        const gridStart = barNumber * barDur;
        const numLines = Math.max(1, Math.ceil((singingEnd - gridStart) / lineDur));
        for (let g = 0; g < numLines; g++) {
            lineRanges.push([gridStart + g * lineDur, gridStart + (g + 1) * lineDur]);
        }
    }
    // If phrase is only slightly longer than BARS_PER_LINE bars, 
    // don't split — keep as single line to avoid tiny trailing fragments like 'たよ'
    const phraseDur = singingEnd - firstChordTime;
    const maxSingleLineDur = barDur * (BARS_PER_LINE + 1.5); // up to 5.5 bars = 1 line
    if (lineRanges.length === 2 && phraseDur <= maxSingleLineDur) {
        lineRanges = [[ lineRanges[0][0], lineRanges[lineRanges.length - 1][1] ]];
    }

    const numLines = lineRanges.length;
    const result = [];
    let prevEndWi = 0;

    for (let g = 0; g < numLines; g++) {
        const [lineStart, lineEnd] = lineRanges[g];

        // Collect chords within this time window
        const groupChords = [];
        // Include the chord playing at lineStart (sustaining from previous window)
        let sustainedChord = null;
        for (const c of chords) {
            if (c.time <= lineStart) sustainedChord = c;
            else break;
        }
        for (const c of chords) {
            if (c.time >= lineStart && c.time < lineEnd) groupChords.push(c);
        }
        // If no chord starts in this window, use the sustained chord
        if (groupChords.length === 0 && sustainedChord) {
            groupChords.push({ ...sustainedChord, time: lineStart });
        }
        if (groupChords.length === 0) continue;

        // Find words within this time window
        let startWi = prevEndWi;
        let endWi = totalWords;
        for (let wi = startWi; wi < totalWords; wi++) {
            if (wordTimes[wi] >= lineEnd) { endWi = wi; break; }
        }
        if (g === 0) startWi = 0;

        // Snap to nearest natural phrase break (from morphological words)
        // Japanese phrasing: prefer splitting at natural word boundaries
        if (phraseBreaks?.length > 0 && g < numLines - 1) {
            let bestBreak = -1;
            let bestDist = Infinity;
            for (const br of phraseBreaks) {
                if (br <= startWi) continue;
                const dist = Math.abs(br - endWi);
                if (dist < bestDist) {
                    bestDist = dist;
                    bestBreak = br;
                }
            }
            if (bestBreak > 0) endWi = bestBreak;
        }

        // If the last line would have very few words, absorb it
        if (g === numLines - 2) {
            const remaining = totalWords - endWi;
            if (remaining > 0 && remaining <= 4) endWi = totalWords;
        }

        const wordsInGroup = endWi - startWi;
        if (wordsInGroup <= 0) continue;

        const startChar = wordPositions[startWi].start;
        const endChar = (endWi < wordPositions.length) ? wordPositions[endWi].start : phraseText.length;
        const lineText = phraseText.slice(startChar, endChar);

        // ── Build segments: assign each chord to words within this group ──
        const beatDur = barDur / 4;
        const segments = [];
        for (let ci = 0; ci < groupChords.length; ci++) {
            let segWi = 0;
            if (ci === 0) {
                segWi = 0; // First chord starts at line beginning
            } else {
                const matchTime = groupChords[ci].time + beatDur;
                for (let wi = startWi; wi < endWi; wi++) {
                    if (wordTimes[wi] >= matchTime) { segWi = wi - startWi; break; }
                }
            }
            if (segments.length > 0 && segWi <= segments[segments.length - 1]._wi) {
                segWi = segments[segments.length - 1]._wi + 1;
            }
            if (segWi >= wordsInGroup) segWi = wordsInGroup - 1;

            const segCharStart = wordPositions[startWi + segWi].start - startChar;
            segments.push({
                chord: groupChords[ci].chord,
                time: groupChords[ci].time,
                text: '',
                _wi: segWi,
                _cs: segCharStart,
            });
        }

        // Fill segment text
        for (let ci = 0; ci < segments.length; ci++) {
            const nextCS = (ci + 1 < segments.length) ? segments[ci + 1]._cs : lineText.length;
            segments[ci].text = lineText.slice(segments[ci]._cs, nextCS) || ' ';
            delete segments[ci]._wi;
            delete segments[ci]._cs;
        }

        // Post-process: merge very short trailing segments (≤ 1 char) text into previous
        // Preserves chord display but prevents unnatural text splits
        for (let ci = segments.length - 1; ci > 0; ci--) {
            if (segments[ci].text.trim().length <= 1 && segments[ci - 1].text.length > 0) {
                segments[ci - 1].text += segments[ci].text;
                segments[ci].text = ''; // Keep segment for chord display, clear text
            }
        }

        result.push({
            text: lineText,
            chords: groupChords.map(c => ({ chord: c.chord, time: c.time })),
            segments,
            startTime: groupChords[0].time,
            endTime: lineEnd,
        });

        prevEndWi = endWi;
    }

    return result;
}

// Fallback: TinySegmenter-based splitting (when word timestamps unavailable)
function splitPhraseByRatio(text, phraseStart, phraseEnd, chordsInPhrase) {
    if (!text || chordsInPhrase.length === 0) return [];
    if (chordsInPhrase.length <= MAX_CHORDS_PER_LINE) {
        return [{ text, chords: chordsInPhrase, startTime: phraseStart, endTime: phraseEnd }];
    }
    const dur = phraseEnd - phraseStart;
    const words = _seg.segment(text);
    const bounds = [0];
    let pos = 0;
    for (const w of words) { pos += w.length; bounds.push(pos); }

    const result = [];
    let prevCharPos = 0;
    for (let i = 0; i < chordsInPhrase.length; i += MAX_CHORDS_PER_LINE) {
        const isLast = i + MAX_CHORDS_PER_LINE >= chordsInPhrase.length;
        const chunk = chordsInPhrase.slice(i, i + MAX_CHORDS_PER_LINE);
        if (isLast) {
            const rem = text.slice(prevCharPos);
            if (rem.length > 0) result.push({ text: rem, chords: chunk, startTime: chunk[0].time, endTime: phraseEnd });
        } else {
            const nextTime = chordsInPhrase[i + MAX_CHORDS_PER_LINE].time;
            const ratio = dur > 0 ? (nextTime - phraseStart) / dur : 0.5;
            const ideal = Math.round(ratio * text.length);
            let best = ideal, bestD = Infinity;
            for (const b of bounds) { if (b > prevCharPos && Math.abs(b - ideal) < bestD) { bestD = Math.abs(b - ideal); best = b; } }
            const slice = text.slice(prevCharPos, best);
            if (slice.length > 0) result.push({ text: slice, chords: chunk, startTime: chunk[0].time, endTime: nextTime });
            prevCharPos = best;
        }
    }
    return result;
}

const DIATONIC_CHORDS = {
  // Major keys
  'C':  ['C', 'Dm', 'Em', 'F', 'G', 'Am', 'Bdim'],
  'C#': ['C#', 'D#m', 'E#m', 'F#', 'G#', 'A#m', 'B#dim'],
  'Db': ['Db', 'Ebm', 'Fm', 'Gb', 'Ab', 'Bbm', 'Cdim'],
  'D':  ['D', 'Em', 'F#m', 'G', 'A', 'Bm', 'C#dim'],
  'D#': ['D#', 'E#m', 'F##m', 'G#', 'A#', 'B#m', 'C##dim'],
  'Eb': ['Eb', 'Fm', 'Gm', 'Ab', 'Bb', 'Cm', 'Ddim'],
  'E':  ['E', 'F#m', 'G#m', 'A', 'B', 'C#m', 'D#dim'],
  'F':  ['F', 'Gm', 'Am', 'Bb', 'C', 'Dm', 'Edim'],
  'F#': ['F#', 'G#m', 'A#m', 'B', 'C#', 'D#m', 'E#dim'],
  'Gb': ['Gb', 'Abm', 'Bbm', 'Cb', 'Db', 'Ebm', 'Fdim'],
  'G':  ['G', 'Am', 'Bm', 'C', 'D', 'Em', 'F#dim'],
  'G#': ['G#', 'A#m', 'B#m', 'C#', 'D#', 'E#m', 'F##dim'],
  'Ab': ['Ab', 'Bbm', 'Cm', 'Db', 'Eb', 'Fm', 'Gdim'],
  'A':  ['A', 'Bm', 'C#m', 'D', 'E', 'F#m', 'G#dim'],
  'A#': ['A#', 'B##m', 'C##m', 'D#', 'E#', 'F##m', 'G##dim'],
  'Bb': ['Bb', 'Cm', 'Dm', 'Eb', 'F', 'Gm', 'Adim'],
  'B':  ['B', 'C#m', 'D#m', 'E', 'F#', 'G#m', 'A#dim'],

  // Minor keys
  'Am':  ['Am', 'Bdim', 'C', 'Dm', 'Em', 'F', 'G', 'E', 'G#dim', 'Am7', 'Dm7', 'G7', 'Cmaj7', 'Fmaj7', 'Bm7b5', 'E7'],
  'A#m': ['A#m', 'B#dim', 'C#', 'D#m', 'E#m', 'F#', 'G#', 'E#', 'G##dim', 'A#m7', 'D#m7', 'G#7', 'C#maj7', 'F#maj7', 'B#m7b5', 'E#7'],
  'Bbm': ['Bbm', 'Cdim', 'Db', 'Ebm', 'Fm', 'Gb', 'Ab', 'F', 'Adim', 'Bbm7', 'Ebm7', 'Ab7', 'Dbmaj7', 'Gbmaj7', 'Cm7b5', 'F7'],
  'Bm':  ['Bm', 'C#dim', 'D', 'Em', 'F#m', 'G', 'A', 'F#', 'A#dim', 'Bm7', 'Em7', 'A7', 'Dmaj7', 'Gmaj7', 'C#m7b5', 'F#7'],
  'Cm':  ['Cm', 'Ddim', 'Eb', 'Fm', 'Gm', 'Ab', 'Bb', 'G', 'Bdim', 'Cm7', 'Fm7', 'Bb7', 'Ebmaj7', 'Abmaj7', 'Dm7b5', 'G7'],
  'C#m': ['C#m', 'D#dim', 'E', 'F#m', 'G#m', 'A', 'B', 'G#', 'B#dim', 'C#m7', 'F#m7', 'B7', 'Emaj7', 'Amaj7', 'D#m7b5', 'G#7'],
  'Dm':  ['Dm', 'Edim', 'F', 'Gm', 'Am', 'Bb', 'C', 'A', 'C#dim', 'Dm7', 'Gm7', 'C7', 'Fmaj7', 'Bbmaj7', 'Em7b5', 'A7'],
  'D#m': ['D#m', 'E#dim', 'F#', 'G#m', 'A#m', 'B', 'C#', 'A#', 'C##dim', 'D#m7', 'G#m7', 'C#7', 'F#maj7', 'Bmaj7', 'E#m7b5', 'A#7'],
  'Ebm': ['Ebm', 'Fdim', 'Gb', 'Abm', 'Bbm', 'Cb', 'Db', 'Bb', 'Ddim', 'Ebm7', 'Abm7', 'Db7', 'Gbmaj7', 'Cbmaj7', 'Fm7b5', 'Bb7'],
  'Em':  ['Em', 'F#dim', 'G', 'Am', 'Bm', 'C', 'D', 'B', 'D#dim', 'Em7', 'Am7', 'D7', 'Gmaj7', 'Cmaj7', 'F#m7b5', 'B7'],
  'Fm':  ['Fm', 'Gdim', 'Ab', 'Bbm', 'Cm', 'Db', 'Eb', 'C', 'Edim', 'Fm7', 'Bbm7', 'Eb7', 'Abmaj7', 'Dbmaj7', 'Gm7b5', 'C7'],
  'F#m': ['F#m', 'G#dim', 'A', 'Bm', 'C#m', 'D', 'E', 'C#', 'E#dim', 'F#m7', 'Bm7', 'E7', 'Amaj7', 'Dmaj7', 'G#m7b5', 'C#7'],
  'Gm':  ['Gm', 'Adim', 'Bb', 'Cm', 'Dm', 'Eb', 'F', 'D', 'F#dim', 'Gm7', 'Cm7', 'F7', 'Bbmaj7', 'Ebmaj7', 'Am7b5', 'D7'],
  'G#m': ['G#m', 'A#dim', 'B', 'C#m', 'D#m', 'E', 'F#', 'D#', 'F##dim', 'G#m7', 'C#m7', 'F#7', 'Bmaj7', 'Emaj7', 'A#m7b5', 'D#7'],
};

// ── Editable chord label ──────────────────────────────────────────────────
function EditableChord({ chord, time, onChordEdit, onChordHover, songKey, onEditingStateChange }) {
    const [editing, setEditing] = useState(false);
    const [value, setValue] = useState(chord);
    const inputRef = useRef(null);
    const containerRef = useRef(null);

    useEffect(() => { setValue(chord); }, [chord]);
    useEffect(() => { if (editing && inputRef.current) inputRef.current.focus(); }, [editing]);

    useEffect(() => {
        if (onEditingStateChange) onEditingStateChange(editing);
        return () => {
            if (onEditingStateChange) onEditingStateChange(false);
        };
    }, [editing, onEditingStateChange]);

    useEffect(() => {
        if (!editing) return;
        const handleClickOutside = (e) => {
            if (containerRef.current && !containerRef.current.contains(e.target)) {
                commit();
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [editing, value]);

    const commit = (val = value) => {
        setEditing(false);
        if (val !== chord && onChordEdit) onChordEdit(time, val);
    };

    const { diatonic, common } = useMemo(() => {
        let diatonicList = [];
        if (songKey) {
            const cleanKey = songKey.replace(' major', '').replace(' minor', 'm');
            diatonicList = DIATONIC_CHORDS[cleanKey] || [];
        }
        const defaults = ['C', 'D', 'E', 'F', 'G', 'A', 'B', 'Cm', 'Dm', 'Em', 'Fm', 'Gm', 'Am', 'Bm'];
        const commonList = defaults.filter(c => !diatonicList.includes(c));
        return { diatonic: diatonicList, common: commonList };
    }, [songKey]);

    const renderCandidateButton = (cand, isDiatonic) => {
        const isSelected = value === cand;
        return (
            <button
                key={cand}
                onClick={(e) => {
                    e.stopPropagation();
                    setValue(cand);
                    commit(cand);
                }}
                style={{
                    padding: '6px 4px',
                    background: isSelected 
                        ? 'linear-gradient(135deg, var(--gf-primary, #6366f1) 0%, #4f46e5 100%)'
                        : isDiatonic 
                            ? 'rgba(16, 185, 129, 0.06)' 
                            : 'rgba(255,255,255,0.02)',
                    border: isSelected 
                        ? '1px solid var(--gf-primary, #6366f1)' 
                        : isDiatonic 
                            ? '1px solid rgba(16, 185, 129, 0.2)' 
                            : '1px solid rgba(255,255,255,0.06)',
                    borderRadius: '6px',
                    color: isSelected 
                        ? '#fff' 
                        : isDiatonic 
                            ? '#34d399' 
                            : 'rgba(255,255,255,0.7)',
                    fontSize: '11px',
                    fontWeight: isDiatonic ? '600' : 'normal',
                    cursor: 'pointer',
                    textAlign: 'center',
                    boxShadow: isSelected ? '0 4px 12px rgba(99, 102, 241, 0.35)' : 'none',
                    transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                }}
                onMouseEnter={e => {
                    if (!isSelected) {
                        e.currentTarget.style.background = isDiatonic 
                            ? 'rgba(16, 185, 129, 0.14)' 
                            : 'rgba(255,255,255,0.08)';
                        e.currentTarget.style.borderColor = isDiatonic 
                            ? 'rgba(16, 185, 129, 0.35)' 
                            : 'rgba(255,255,255,0.15)';
                        e.currentTarget.style.color = isDiatonic ? '#34d399' : '#fff';
                        e.currentTarget.style.transform = 'translateY(-1px)';
                        e.currentTarget.style.boxShadow = isDiatonic
                            ? '0 4px 12px rgba(16, 185, 129, 0.15)'
                            : '0 4px 12px rgba(255,255,255,0.05)';
                    }
                }}
                onMouseLeave={e => {
                    if (!isSelected) {
                        e.currentTarget.style.background = isDiatonic 
                            ? 'rgba(16, 185, 129, 0.06)' 
                            : 'rgba(255,255,255,0.02)';
                        e.currentTarget.style.borderColor = isDiatonic 
                            ? 'rgba(16, 185, 129, 0.2)' 
                            : 'rgba(255,255,255,0.06)';
                        e.currentTarget.style.color = isDiatonic ? '#34d399' : 'rgba(255,255,255,0.7)';
                        e.currentTarget.style.transform = 'none';
                        e.currentTarget.style.boxShadow = 'none';
                    }
                }}
            >
                {cand}
            </button>
        );
    };

    if (editing) {
        return (
            <div ref={containerRef} className="chord-edit-container" onClick={e => e.stopPropagation()} style={{ position: 'relative', display: 'inline-block', zIndex: 100 }}>
                <span className="cl-chord-text" translate="no" style={{ cursor: 'pointer', borderBottom: '1px dotted var(--gf-text-dim)', opacity: 0.3 }}>{chord}</span>
                <div className="chord-suggestions" style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    background: 'rgba(20, 20, 23, 0.85)',
                    backdropFilter: 'blur(20px)',
                    WebkitBackdropFilter: 'blur(20px)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '14px',
                    boxShadow: '0 20px 40px -10px rgba(0, 0, 0, 0.7), 0 10px 15px -5px rgba(0, 0, 0, 0.5), inset 0 1px 1px rgba(255, 255, 255, 0.05)',
                    padding: '12px',
                    marginTop: '6px',
                    width: '240px',
                    maxHeight: '320px',
                    overflowY: 'auto',
                    zIndex: 9999,
                }}>
                    <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                        <input ref={inputRef} className="chord-edit-input" value={value}
                            onChange={e => setValue(e.target.value)}
                            onKeyDown={e => {
                                if (e.key === 'Enter') commit();
                                if (e.key === 'Escape') { setValue(chord); setEditing(false); }
                            }}
                            placeholder="直接入力..."
                            style={{
                                flex: 1,
                                background: 'rgba(255,255,255,0.04)',
                                color: '#fff',
                                border: '1px solid rgba(255,255,255,0.1)',
                                borderRadius: '8px',
                                padding: '6px 10px',
                                fontSize: '12px',
                                outline: 'none',
                                fontFamily: 'inherit',
                                transition: 'all 0.2s',
                            }}
                            onFocus={e => {
                                e.target.style.borderColor = 'var(--gf-primary, #6366f1)';
                                e.target.style.boxShadow = '0 0 0 2px rgba(99, 102, 241, 0.2)';
                            }}
                            onBlur={e => {
                                e.target.style.borderColor = 'rgba(255,255,255,0.1)';
                                e.target.style.boxShadow = 'none';
                            }}
                        />
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                setValue('N.C.');
                                commit('N.C.');
                            }}
                            style={{
                                background: 'rgba(239, 68, 68, 0.08)',
                                border: '1px solid rgba(239, 68, 68, 0.2)',
                                borderRadius: '8px',
                                color: '#ef4444',
                                padding: '6px 12px',
                                fontSize: '11px',
                                cursor: 'pointer',
                                fontWeight: '600',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                transition: 'all 0.2s',
                            }}
                            onMouseEnter={e => {
                                e.currentTarget.style.background = 'rgba(239, 68, 68, 0.16)';
                                e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                                e.currentTarget.style.transform = 'translateY(-1px)';
                            }}
                            onMouseLeave={e => {
                                e.currentTarget.style.background = 'rgba(239, 68, 68, 0.08)';
                                e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.2)';
                                e.currentTarget.style.transform = 'none';
                            }}
                            title="コードを削除 (No Chord)"
                        >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                <line x1="10" y1="11" x2="10" y2="17"></line>
                                <line x1="14" y1="11" x2="14" y2="17"></line>
                            </svg>
                            <span>削除</span>
                        </button>
                    </div>

                    {diatonic.length > 0 && (
                        <div style={{ marginBottom: '12px' }}>
                            <div style={{
                                fontSize: '10px',
                                color: 'rgba(255,255,255,0.4)',
                                fontWeight: '600',
                                textTransform: 'uppercase',
                                letterSpacing: '0.05em',
                                marginBottom: '6px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '5px',
                            }}>
                                <span style={{ display: 'inline-block', width: '5px', height: '5px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 6px #10b981' }}></span>
                                ダイアトニック ({songKey ? songKey.replace(' major', '').replace(' minor', 'm') : ''})
                            </div>
                            <div style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(4, 1fr)',
                                gap: '6px',
                            }}>
                                {diatonic.map(cand => renderCandidateButton(cand, true))}
                            </div>
                        </div>
                    )}

                    {common.length > 0 && (
                        <div>
                            <div style={{
                                fontSize: '10px',
                                color: 'rgba(255,255,255,0.4)',
                                fontWeight: '600',
                                textTransform: 'uppercase',
                                letterSpacing: '0.05em',
                                marginBottom: '6px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '5px',
                            }}>
                                <span style={{ display: 'inline-block', width: '5px', height: '5px', borderRadius: '50%', background: 'rgba(255,255,255,0.2)' }}></span>
                                その他
                            </div>
                            <div style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(4, 1fr)',
                                gap: '6px',
                            }}>
                                {common.map(cand => renderCandidateButton(cand, false))}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        );
    }
    return (
        <span className="cl-chord-text cl-chord-interactive" translate="no"
            onClick={e => { e.stopPropagation(); setEditing(true); }}
            onMouseEnter={() => onChordHover?.(chord)}
            onMouseLeave={() => onChordHover?.(null)}
            title="クリックして編集"
            style={{ cursor: 'pointer' }}
        >{chord}</span>
    );
}


// ── Editable lyric segment ────────────────────────────────────────────────
function EditableLyricSegment({ text, onBlur }) {
    const [editing, setEditing] = useState(false);
    const [value, setValue] = useState(text);
    const inputRef = useRef(null);

    useEffect(() => {
        setValue(text);
    }, [text]);

    useEffect(() => {
        if (editing && inputRef.current) {
            inputRef.current.focus();
            inputRef.current.select();
        }
    }, [editing]);

    const commit = () => {
        setEditing(false);
        if (value !== text && onBlur) {
            onBlur(value);
        }
    };

    if (editing) {
        return (
            <input
                ref={inputRef}
                className="lyric-segment-edit-input"
                value={value}
                onChange={e => setValue(e.target.value)}
                onBlur={commit}
                onKeyDown={e => {
                    if (e.key === 'Enter') {
                        commit();
                    }
                    if (e.key === 'Escape') {
                        setValue(text);
                        setEditing(false);
                    }
                }}
                style={{
                    width: `${Math.max(value.length * 1.05 + 0.5, 1.5)}em`,
                    background: 'var(--gf-surface-3)',
                    color: 'var(--gf-text)',
                    border: '1px solid var(--gf-primary)',
                    borderRadius: '4px',
                    padding: '2px 4px',
                    fontSize: 'inherit',
                    fontFamily: 'inherit',
                    outline: 'none',
                    textAlign: 'center',
                }}
            />
        );
    }

    return (
        <span
            className="cl-lyric-text-segment"
            onClick={e => {
                e.stopPropagation();
                setEditing(true);
            }}
            title="クリックして編集"
            style={{
                cursor: 'pointer',
                borderBottom: '1px dashed var(--gf-text-dim)',
                paddingBottom: '1px',
            }}
        >
            {text || '\u00A0'}
        </span>
    );
}

// ── Word-like contentEditable lyric line ──────────────────────────────────
function LyricEditLine({ text, onRef, onKeyDown, onBlur }) {
    const domRef = useRef(null);
    useLayoutEffect(() => {
        const el = domRef.current;
        if (!el) return;
        if (document.activeElement !== el && el.textContent !== text) {
            el.textContent = text;
        }
    });
    return (
        <div ref={el => { domRef.current = el; onRef?.(el); }}
            className="cl-lyric-editable"
            contentEditable suppressContentEditableWarning spellCheck={false}
            onKeyDown={onKeyDown} onBlur={onBlur}
        />
    );
}

// ══════════════════════════════════════════════════════════════════════════
// Main Component
// ══════════════════════════════════════════════════════════════════════════
export function ChordLyricsView({
    data, lyricsPhrases, displayPhrases, barPositions, currentTime, onSeek,
    onChordEdit, onLyricEdit, onChordHover, transpose = 0, title, artist, songKey
}) {
    const activeRef = useRef(null);
    const scrollContainerRef = useRef(null);
    const [lyricLines, setLyricLines] = useState({});
    const pendingFocus = useRef(null);
    const lyricEls = useRef({});
    const [kuromojiReady, setKuromojiReady] = useState(isTokenizerReady());
    const [isChordEditing, setIsChordEditing] = useState(false);

    // Initialize kuromoji tokenizer once
    useEffect(() => {
        if (!kuromojiReady) {
            initTokenizer()
                .then(() => { setKuromojiReady(true); })
                .catch(err => { console.warn('[kuromoji] init failed, using fallback:', err); });
        }
    }, []);

    const [zoom, setZoom] = useState(() => parseFloat(localStorage.getItem('nc-lyrics-zoom') || '1'));
    const [autoScroll, setAutoScroll] = useState(false);
    const [scrollSpeed, setScrollSpeed] = useState(() => parseFloat(localStorage.getItem('nc-scroll-speed') || '1'));

    const changeZoom = d => setZoom(prev => {
        const v = Math.round(Math.max(0.8, Math.min(2.0, prev + d)) * 100) / 100;
        localStorage.setItem('nc-lyrics-zoom', v); return v;
    });
    const resetZoom = () => { setZoom(1); localStorage.setItem('nc-lyrics-zoom', '1'); };

    const getCursorPos = (el, range) => {
        const pre = range.cloneRange();
        pre.selectNodeContents(el);
        pre.setEnd(range.startContainer, range.startOffset);
        return pre.toString().length;
    };

    const handleLyricKeyDown = (e, li, subIdx) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const el = e.currentTarget;
            const sel = window.getSelection();
            if (!sel?.rangeCount) return;
            const pos = getCursorPos(el, sel.getRangeAt(0));
            const text = el.textContent || '';
            setLyricLines(prev => {
                const arr = prev[li] !== undefined ? [...prev[li]] : [lines[li]?.fullText ?? ''];
                arr.splice(subIdx, 1, text.slice(0, pos), text.slice(pos));
                return { ...prev, [li]: arr };
            });
            pendingFocus.current = { li, subIdx: subIdx + 1, pos: 0 };
        } else if (e.key === 'Backspace') {
            const el = e.currentTarget;
            const sel = window.getSelection();
            if (!sel?.rangeCount) return;
            const range = sel.getRangeAt(0);
            if (!range.collapsed || getCursorPos(el, range) !== 0) return;
            e.preventDefault();
            setLyricLines(prev => {
                const currArr = prev[li] !== undefined ? [...prev[li]] : [lines[li]?.fullText ?? ''];
                if (subIdx > 0) {
                    const pt = currArr[subIdx - 1] ?? '';
                    const ct = currArr[subIdx] ?? '';
                    currArr.splice(subIdx - 1, 2, pt + ct);
                    pendingFocus.current = { li, subIdx: subIdx - 1, pos: pt.length };
                    return { ...prev, [li]: currArr };
                } else {
                    let pli = li - 1;
                    while (pli >= 0 && prev[pli]?.length === 0) pli--;
                    if (pli < 0) return prev;
                    const pArr = prev[pli] !== undefined ? [...prev[pli]] : [lines[pli]?.fullText ?? ''];
                    const last = pArr.length - 1;
                    const pt = pArr[last] ?? '';
                    const ct = currArr[0] ?? '';
                    pArr.splice(last, 1, pt + ct, ...currArr.slice(1));
                    pendingFocus.current = { li: pli, subIdx: last, pos: pt.length };
                    return { ...prev, [pli]: pArr, [li]: [] };
                }
            });
        }
    };

    const changeSpeed = d => setScrollSpeed(prev => {
        const v = Math.round(Math.max(0.3, Math.min(3.0, prev + d)) * 10) / 10;
        localStorage.setItem('nc-scroll-speed', v); return v;
    });

    useEffect(() => {
        if (!autoScroll || !scrollContainerRef.current || isChordEditing) return;
        let id, last = performance.now();
        const step = now => {
            const dt = now - last; last = now;
            if (scrollContainerRef.current) scrollContainerRef.current.scrollTop += scrollSpeed * dt * 0.03;
            id = requestAnimationFrame(step);
        };
        id = requestAnimationFrame(step);
        return () => cancelAnimationFrame(id);
    }, [autoScroll, scrollSpeed, isChordEditing]);

    useEffect(() => {
        const t = pendingFocus.current;
        if (!t) return;
        pendingFocus.current = null;
        const el = lyricEls.current[`${t.li}_${t.subIdx}`];
        if (!el) return;
        el.focus();
        const tn = el.firstChild;
        if (tn?.nodeType === 3) {
            const p = Math.min(t.pos, tn.length);
            const r = document.createRange();
            r.setStart(tn, p); r.collapse(true);
            window.getSelection()?.removeAllRanges();
            window.getSelection()?.addRange(r);
        }
    }, [lyricLines]);

    // ── Chord timeline (deduplicated) ─────────────────────────────────────
    const chordTimeline = useMemo(() => {
        if (!data || !Array.isArray(data)) return [];
        const out = [];
        let last = '';
        for (const e of data) {
            const c = transposeChord(e.chord || '', transpose);
            if (c !== last) { out.push({ time: e.time, chord: c }); last = c; }
        }
        return out;
    }, [data, transpose]);

    // ══════════════════════════════════════════════════════════════════════
    // LINE GENERATION
    //
    // 1 line = 4 bars (measures). Split by BPM-derived time, not chord count.
    // Each line: chord names above their corresponding lyrics.
    // ══════════════════════════════════════════════════════════════════════
    const lines = useMemo(() => {
        if (!data || !Array.isArray(data) || chordTimeline.length === 0) return [];

        const bpm = (data.find(d => d.bpm) || { bpm: 120 }).bpm || 120;
        const barDur = (60 / bpm) * 4;
        const INSTR_GAP = barDur * 2;
        // Grid reference: first chord time ≈ bar 1 beat 1
        const gridRef = chordTimeline[0]?.time ?? 0;

        const getChordAt = t => {
            let res = null;
            for (const c of chordTimeline) {
                if (c.time <= t + 0.05) res = c;
                else break;
            }
            return res;
        };

        const getChordsFor = (start, end) => {
            const list = [];
            const sc = getChordAt(start);
            if (sc) list.push({ chord: sc.chord, time: start });
            for (const c of chordTimeline) {
                if (c.time > start + 0.05 && c.time < end - 0.05) {
                    if (!list.length || list[list.length - 1].chord !== c.chord)
                        list.push({ chord: c.chord, time: c.time });
                }
            }
            return list;
        };

        // ── Instrumental blocks (4 chords per row) ────────────────────────
        const instrLines = (blockStart, blockEnd, label) => {
            const gc = getChordsFor(blockStart, blockEnd);
            const out = [];
            const N = 4;
            for (let i = 0; i < gc.length; i += N) {
                const chunk = gc.slice(i, i + N);
                const cEnd = gc[i + N]?.time ?? blockEnd;
                out.push({
                    startTime: chunk[0].time, endTime: cEnd,
                    chords: chunk,
                    fullText: '', hasLyric: false, isInstrumental: true,
                    instrLabel: i === 0 ? label : null,
                });
            }
            return out;
        };

        // ── Lyric phrases ─────────────────────────────────────────────────
        // Use displayPhrases for text (hallucination-filtered, bar-split),
        // lyricsPhrases only for word timestamps
        const rawPhrases = displayPhrases || lyricsPhrases || [];
        const wordsLookup = {};
        if (lyricsPhrases) {
            for (const lp of lyricsPhrases) {
                const key = (lp.start ?? lp.startTime ?? 0).toFixed(2);
                if (lp.words?.length) wordsLookup[key] = lp.words;
            }
        }
        const phrases = rawPhrases
            .map(p => {
                const start = p.start ?? p.startTime ?? 0;
                // Fuzzy match words from lyricsPhrases (within 1s tolerance)
                let matchedWords = p.words || null;
                if (!matchedWords && lyricsPhrases) {
                    const pEnd = p.end ?? p.endTime ?? (start + 3);
                    for (const lp of lyricsPhrases) {
                        const lpStart = lp.start ?? lp.startTime ?? 0;
                        if (lp.words?.length && Math.abs(lpStart - start) < 1.0) {
                            // Filter words to this displayPhrase's time range
                            // to prevent duplication when lyricPhrase spans multiple displayPhrases
                            matchedWords = lp.words.filter(w => {
                                const ws = w.start ?? w.s ?? 0;
                                return ws >= start - 0.3 && ws < pEnd + 0.3;
                            });
                            if (matchedWords.length === 0) matchedWords = null;
                            break;
                        }
                    }
                    // If no exact start match, try overlap-based matching
                    if (!matchedWords) {
                        const pEnd = p.end ?? p.endTime ?? (start + 3);
                        for (const lp of lyricsPhrases) {
                            if (!lp.words?.length) continue;
                            const lpStart = lp.start ?? lp.startTime ?? 0;
                            const lpEnd = lp.end ?? lp.endTime ?? (lpStart + 3);
                            // Check if time ranges overlap
                            if (lpStart < pEnd + 0.3 && lpEnd > start - 0.3) {
                                matchedWords = lp.words.filter(w => {
                                    const ws = w.start ?? w.s ?? 0;
                                    return ws >= start - 0.3 && ws < pEnd + 0.3;
                                });
                                if (matchedWords.length > 0) break;
                                matchedWords = null;
                            }
                        }
                    }
                }

                // ── morphological re-segmentation ──
                // Merge Whisper character-level tokens into proper Japanese words (using Kuromoji or TinySegmenter fallback)
                if (matchedWords) {
                    matchedWords = resegmentWords(matchedWords);
                }

                // When words exist, rebuild text from them for exact character alignment
                const rawText = cleanJapaneseText(p.text ?? p.transcript ?? '');
                const phraseText = matchedWords
                    ? matchedWords.map(w => w.word ?? w.w ?? '').join('')
                    : rawText;

                // ── Compute line-break points ──
                // Use kuromoji POS-based breaks when available, fall back to TinySegmenter + space-based
                let breaks = [];
                if (matchedWords && kuromojiReady) {
                    breaks = computeBreaks(matchedWords);
                } else if (matchedWords) {
                    // Fallback: Use TinySegmenter to segment the phraseText and find word boundaries
                    const tsWords = _seg.segment(phraseText);
                    let cumChars = 0;
                    const wordBoundaries = [];
                    for (const w of tsWords) {
                        cumChars += w.length;
                        wordBoundaries.push(cumChars);
                    }
                    
                    // Map character boundaries to matchedWords indices
                    let cc = 0;
                    for (let wi = 0; wi < matchedWords.length; wi++) {
                        cc += (matchedWords[wi].word ?? matchedWords[wi].w ?? '').length;
                        if (wordBoundaries.includes(cc)) {
                            breaks.push(wi + 1);
                        }
                    }
                    
                    // Also include spaces in original text as fallback breaks
                    const origText = p.text ?? p.transcript ?? '';
                    const subPhrases = origText.split(/[\s\u3000]+/).filter(s => s.length > 0);
                    let cumSpaceChars = 0;
                    for (let sp = 0; sp < subPhrases.length - 1; sp++) {
                        cumSpaceChars += subPhrases[sp].length;
                        let charCount = 0;
                        for (let wi = 0; wi < matchedWords.length; wi++) {
                            charCount += (matchedWords[wi].word ?? matchedWords[wi].w ?? '').length;
                            if (charCount >= cumSpaceChars) {
                                if (!breaks.includes(wi + 1)) {
                                    breaks.push(wi + 1);
                                }
                                break;
                            }
                        }
                    }
                }

                return {
                    start,
                    end:   p.end   ?? p.endTime   ?? (start + 3),
                    text:  phraseText,
                    words: matchedWords,
                    breaks, // natural phrase break word indices
                };
            })
            .filter(p => p.text.length > 0)
            .sort((a, b) => a.start - b.start);

        if (phrases.length === 0) return [];

        // ── 4小節グリッドで短いフレーズを結合 ──
        // barPositionsから4小節窓を構築し、同じ窓内のフレーズを結合
        const mergedPhrases = [];
        if (barPositions?.length > 1) {
            // Build 4-bar windows
            const windows = [];
            for (let i = 0; i < barPositions.length; i += BARS_PER_LINE) {
                const ws = barPositions[i];
                const we = (i + BARS_PER_LINE < barPositions.length)
                    ? barPositions[i + BARS_PER_LINE]
                    : barPositions[barPositions.length - 1] + barDur * BARS_PER_LINE;
                windows.push([ws, we]);
            }

            // Assign each phrase to a 4-bar window
            let wi = 0;
            let cur = null;
            for (const p of phrases) {
                // Find the window this phrase starts in
                while (wi < windows.length - 1 && p.start >= windows[wi][1] - 0.05) wi++;
                
                if (!cur) {
                    cur = { ...p };
                } else if (wi < windows.length && p.start < windows[wi][1] - 0.05 
                           && cur.start >= windows[wi][0] - 0.05) {
                    // Same 4-bar window → merge
                    cur.end = p.end;
                    cur.text = cur.text + " " + p.text;
                    if (cur.words && p.words) {
                        const spaceWord = { word: ' ', w: ' ', start: p.start, s: p.start, end: p.start, e: p.start };
                        cur.words = [...cur.words, spaceWord, ...p.words];
                    } else {
                        cur.words = null; // Can't merge word timestamps
                    }
                    cur.breaks = []; // Reset breaks for merged phrase
                } else {
                    // Different window → push previous, start new
                    mergedPhrases.push(cur);
                    cur = { ...p };
                }
            }
            if (cur) mergedPhrases.push(cur);
        } else {
            mergedPhrases.push(...phrases);
        }

        const result = [];
        let prevEnd = 0;

        if (mergedPhrases[0].start > barDur) {
            result.push(...instrLines(0, mergedPhrases[0].start, 'intro'));
            prevEnd = mergedPhrases[0].start;
        }

        for (let pi = 0; pi < mergedPhrases.length; pi++) {
            const phrase = mergedPhrases[pi];
            const nextPhraseStart = (pi + 1 < mergedPhrases.length) ? mergedPhrases[pi + 1].start : null;

            if (phrase.start - prevEnd > INSTR_GAP) {
                result.push(...instrLines(prevEnd, phrase.start, 'interlude'));
            }

            // Effective end for chord collection:
            let effectiveEnd = phrase.end;
            if (nextPhraseStart) {
                const gap = nextPhraseStart - phrase.end;
                if (gap < 1.0) {
                    // Contiguous phrases: don't extend beyond next phrase start
                    // Each phrase should capture only its own chords (4-bar rule)
                    effectiveEnd = nextPhraseStart;
                } else if (gap < barDur * 2) {
                    // Small gap: extend to midpoint between phrases
                    effectiveEnd = phrase.end + gap / 2;
                } else {
                    // Large gap between phrases: use conservative formula
                    effectiveEnd = Math.max(phrase.end, nextPhraseStart - barDur);
                }
            }

            let subLines;

            // Use word timestamps if available (forward-shift rule)
            if (phrase.words?.length > 0) {
                // Collect chords up to next phrase start (covers timestamp collapse)
                const assignments = assignChordsToWords(
                    phrase.start, effectiveEnd, phrase.words, chordTimeline
                );
                subLines = splitPhraseWithWords(
                    phrase.text, phrase.words, phrase.start, effectiveEnd, assignments, barDur, phrase.breaks, barPositions
                );
            } else {
                // Fallback: old getChordsFor + TinySegmenter ratio-based splitting
                const chordsInPhrase = getChordsFor(phrase.start, effectiveEnd);
                subLines = splitPhraseByRatio(
                    phrase.text, phrase.start, phrase.end, chordsInPhrase
                );
            }

            for (const sl of subLines) {
                result.push({
                    startTime: sl.startTime,
                    endTime: sl.endTime,
                    chords: sl.chords,
                    segments: sl.segments || null,
                    fullText: sl.text,
                    hasLyric: true,
                    isInstrumental: false,
                });
            }

            prevEnd = effectiveEnd;
        }

        return result;
    }, [data, lyricsPhrases, displayPhrases, chordTimeline, transpose, barPositions, kuromojiReady]);

    const activeIdx = lines.findIndex(l => currentTime >= l.startTime && currentTime < l.endTime);

    const prevLinesLen = useRef(0);
    useEffect(() => {
        if (lines.length > 0 && lines.length !== prevLinesLen.current) {
            prevLinesLen.current = lines.length;
            if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0;
            setLyricLines({});
        }
    }, [lines.length]);

    useEffect(() => {
        if (!activeRef.current || autoScroll || isChordEditing) return;
        if (activeIdx <= 5) return;
        const rect = activeRef.current.getBoundingClientRect();
        const viewH = window.innerHeight;
        if (rect.bottom > viewH - 80 || rect.top < 80)
            activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, [activeIdx, autoScroll, isChordEditing]);

    // ══════════════════════════════════════════════════════════════════════
    // RENDER
    // ══════════════════════════════════════════════════════════════════════
    return (
        <div className="chord-lyrics-view" ref={scrollContainerRef}>
            <div className="cl-top-bar">
                {(title || artist) && (
                    <div className="cl-header">
                        {title && <div className="cl-title">{title}</div>}
                        {artist && <div className="cl-artist">{artist}</div>}
                    </div>
                )}
                <div className="cl-controls-row">
                    <div className="cl-autoscroll-controls">
                        <button className={`cl-zoom-btn ${autoScroll ? 'cl-btn-active' : ''}`}
                            onClick={() => setAutoScroll(p => !p)}
                        >{autoScroll ? '⏸' : '▶'}</button>
                        {autoScroll && (<>
                            <button className="cl-zoom-btn" onClick={() => changeSpeed(-0.2)} disabled={scrollSpeed <= 0.3}>🐢</button>
                            <span className="cl-zoom-label">×{scrollSpeed.toFixed(1)}</span>
                            <button className="cl-zoom-btn" onClick={() => changeSpeed(0.2)} disabled={scrollSpeed >= 3.0}>🐇</button>
                        </>)}
                    </div>
                    <div className="cl-zoom-controls">
                        <button className="cl-zoom-btn" onClick={() => changeZoom(-0.1)} disabled={zoom <= 0.8}>-</button>
                        <button className="cl-zoom-label" onClick={resetZoom}>{Math.round(zoom * 100)}%</button>
                        <button className="cl-zoom-btn" onClick={() => changeZoom(0.1)} disabled={zoom >= 2.0}>+</button>
                    </div>
                </div>
            </div>

            {(onChordEdit || onLyricEdit) && (
                <div className="cl-edit-hint">
                    💡 Click lyric to edit — <kbd>Enter</kbd> split / <kbd>Backspace</kbd> merge
                </div>
            )}

            <div style={{ fontSize: `${zoom}rem` }}>
            {lines.map((line, li) => {
                if (lyricLines[li]?.length === 0) return null;
                const isActive = li === activeIdx;

                const allChords = [...(line.chords || [])];
                for (let k = li + 1; k < lines.length && lyricLines[k]?.length === 0; k++) {
                    if (lines[k]?.chords) allChords.push(...lines[k].chords);
                }

                const textSubs = lyricLines[li] !== undefined
                    ? lyricLines[li]
                    : (line.fullText ? [line.fullText] : []);

                const isRhy = line.segments 
                    ? line.segments.every(seg => isRhythmText(seg.text)) 
                    : (line.fullText && isRhythmText(line.fullText));

                return (
                    <div key={li}
                        ref={isActive ? activeRef : null}
                        className={`cl-line ${isActive ? 'cl-line-active' : ''} ${isRhy ? 'cl-rhythm-line' : ''}`}
                        onClick={() => onSeek?.(line.startTime)}
                    >
                        {line.isInstrumental && line.instrLabel && (
                            <div className="cl-section-label">
                                {line.instrLabel === 'intro' ? '🎸 イントロ' : '🎸 間奏'}
                            </div>
                        )}

                        {/* Segment-based: chord above corresponding lyrics */}
                        {line.segments ? (
                            <div className="cl-chord-row cl-segment-row" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                                {line.segments.map((seg, i) => (
                                    <span key={i} className="cl-segment"
                                        style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-start', verticalAlign: 'bottom', paddingRight: '0.4em' }}>
                                        {seg.chord ? (
                                            onChordEdit ? (
                                                <EditableChord chord={seg.chord} time={seg.time}
                                                    onChordEdit={onChordEdit} onChordHover={onChordHover} songKey={songKey}
                                                    onEditingStateChange={setIsChordEditing} />
                                            ) : (
                                                <span className="cl-chord-text" translate="no"
                                                    onMouseEnter={() => onChordHover?.(seg.chord)}
                                                    onMouseLeave={() => onChordHover?.(null)}
                                                >{seg.chord}</span>
                                            )
                                        ) : (
                                            <span className="cl-chord-text cl-chord-placeholder" style={{ visibility: 'hidden' }}>{"\u00A0"}</span>
                                        )}
                                        <EditableLyricSegment 
                                            text={seg.text}
                                            onBlur={(newSegText) => {
                                                const updatedSegments = [...line.segments];
                                                updatedSegments[i] = { ...seg, text: newSegText };
                                                const newFullText = updatedSegments.map(s => s.text).join('');
                                                onLyricEdit?.(line.startTime, newFullText);
                                            }}
                                        />
                                    </span>
                                ))}
                            </div>
                        ) : (
                            <>
                                {/* Fallback: old chord row + lyric row */}
                                <div className="cl-chord-row">
                                    {allChords.map((c, i) => (
                                        onChordEdit ? (
                                            <EditableChord key={i} chord={c.chord} time={c.time}
                                                onChordEdit={onChordEdit} onChordHover={onChordHover} songKey={songKey}
                                                onEditingStateChange={setIsChordEditing} />
                                        ) : (
                                            <span key={i} className="cl-chord-text" translate="no"
                                                onMouseEnter={() => onChordHover?.(c.chord)}
                                                onMouseLeave={() => onChordHover?.(null)}
                                            >{c.chord}</span>
                                        )
                                    ))}
                                </div>
                                {!line.isInstrumental && textSubs.map((text, subIdx) => (
                                    <LyricEditLine key={subIdx} text={text}
                                        onRef={el => { if (el) lyricEls.current[`${li}_${subIdx}`] = el; }}
                                        onKeyDown={e => { e.stopPropagation(); handleLyricKeyDown(e, li, subIdx); }}
                                        onBlur={e => {
                                            const newText = e.currentTarget.textContent || '';
                                            if (newText !== text) {
                                                setLyricLines(prev => {
                                                    const arr = prev[li] !== undefined ? [...prev[li]] : [line.fullText ?? ''];
                                                    arr[subIdx] = newText;
                                                    return { ...prev, [li]: [...arr] };
                                                });
                                                onLyricEdit?.(line.startTime, newText);
                                            }
                                        }}
                                    />
                                ))}
                            </>
                        )}                    </div>
                );
            })}
            {lines.length === 0 && (
                <div style={{ textAlign: 'center', color: 'var(--nc-text-muted)', padding: '3rem' }}>
                    Loading...
                </div>
            )}
            </div>
        </div>
    );
}

export default ChordLyricsView;
