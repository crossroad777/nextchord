import React, { useMemo, useRef, useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import GuitarChord from './GuitarChord';
import { Maximize, Minimize } from 'lucide-react';
import { chordproToPlainText, plainTextToChordpro } from '../utils/plainTextConverter';

const isRhythmText = (text) => {
    if (!text) return true;
    const clean = text.replace(/[ \-\=>|≧○o0~^vVx×\(\)\.\*\/_]/g, '');
    return clean.length === 0;
};

const isRhythmLine = (line) => {
    if (line.type !== 'chord-lyric') return false;
    const segments = (line.measures || []).flat();
    if (segments.length === 0) return false;
    return segments.every(seg => isRhythmText(seg.lyrics));
};

/**
 * ChordProView — ChordWiki風のコード譜表示コンポーネント
 *
 * ChordPro形式テキスト `[C]歌詞` をパースし、
 * コード名を歌詞の上に配置して表示する。
 */

const NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const NOTES_FLAT = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];

function transposeChord(chord, semitones) {
    if (!chord || chord === 'N.C.' || semitones === 0) return chord;
    if (chord.includes('/')) {
        const [main, bass] = chord.split('/');
        return transposeChord(main, semitones) + '/' + transposeChord(bass, semitones);
    }
    return chord.replace(/^([A-G][#b]?)/, (_, root) => {
        let idx = NOTES.indexOf(root);
        if (idx < 0) idx = NOTES_FLAT.indexOf(root);
        if (idx < 0) return root;
        return NOTES[(idx + semitones + 120) % 12];
    });
}

/**
 * ChordPro テキストをパースして行配列に変換
 */
function parseChordPro(text) {
    if (!text) return [];
    const lines = text.split('\n');
    const result = [];

    for (let rawLineIdx = 0; rawLineIdx < lines.length; rawLineIdx++) {
        const line = lines[rawLineIdx];
        const trimmed = line.trim();

        if (!trimmed) {
            result.push({ type: 'empty', rawLineIdx });
            continue;
        }

        if (trimmed.startsWith('#')) continue;

        const tagMatch = trimmed.match(/^\{(\w+)(?::(.+?))?\}$/);
        if (tagMatch) {
            const [, tag, value] = tagMatch;
            switch (tag.toLowerCase()) {
                case 't':
                case 'title':
                    result.push({ type: 'title', text: value || '', rawLineIdx });
                    break;
                case 'st':
                case 'subtitle':
                    result.push({ type: 'subtitle', text: value || '', rawLineIdx });
                    break;
                case 'c':
                case 'comment':
                    result.push({ type: 'section', text: value || '', rawLineIdx });
                    break;
                case 'ci':
                case 'comment_italic':
                    result.push({ type: 'section', text: value || '', italic: true, rawLineIdx });
                    break;
                case 'key':
                    break;
                default:
                    break;
            }
            continue;
        }

        // コード付き行をパース（修正版: 無限ループ防止）
        const segments = parseChordLine(trimmed);
        
        const hasLyrics = segments.some(s => s.lyrics && s.lyrics.length > 0);
        
        if (hasLyrics) {
            // Group segments by `|` to form measures
            const measures = [];
            let currentMeasure = [];
            for (const seg of segments) {
                if (seg.chord === '|') {
                    if (currentMeasure.length > 0) measures.push(currentMeasure);
                    currentMeasure = [seg];
                } else {
                    currentMeasure.push(seg);
                }
            }
            if (currentMeasure.length > 0) measures.push(currentMeasure);
            result.push({ type: 'chord-lyric', measures, rawLineIdx });
        } else {
            // For chord-only lines, we can also group by `|`
            const measures = [];
            let currentMeasure = [];
            for (const seg of segments) {
                if (seg.chord === '|') {
                    if (currentMeasure.length > 0) measures.push(currentMeasure);
                    currentMeasure = [seg.chord];
                } else if (seg.chord) {
                    currentMeasure.push(seg.chord);
                }
            }
            if (currentMeasure.length > 0) measures.push(currentMeasure);
            if (measures.length > 0 && measures.some(m => m.length > 0)) {
                result.push({ type: 'chord-only', measures, rawLineIdx });
            }
        }
    }

    return result;
}

/**
 * 1行のChordProテキストをセグメント配列にパース
 * "[C]君を忘れ[G]ない" → [{chord:'C', lyrics:'君を忘れ'}, {chord:'G', lyrics:'ない'}]
 * 
 * 修正: regex.exec の二重呼び出し + rewind パターンを逆転。
 * 代わりに全マッチを先に取得してからセグメントを構築。
 */
function parseChordLine(line) {
    const segments = [];
    const regex = /\[([^\]]+)\]/g;
    
    // 全マッチを先に取得（無限ループ防止）
    const matches = [];
    let m;
    while ((m = regex.exec(line)) !== null) {
        matches.push({ chord: m[1], index: m.index, end: m.index + m[0].length });
    }
    
    if (matches.length === 0) {
        // コードなし — テキスト行として返す
        if (line.trim()) {
            segments.push({ chord: '', lyrics: line });
        }
        return segments;
    }
    
    // 先頭にコードがない場合のテキスト
    if (matches[0].index > 0) {
        segments.push({ chord: '', lyrics: line.substring(0, matches[0].index) });
    }
    
    // 各マッチからセグメント構築
    for (let i = 0; i < matches.length; i++) {
        const chord = matches[i].chord;
        const lyricsStart = matches[i].end;
        const lyricsEnd = (i + 1 < matches.length) ? matches[i + 1].index : line.length;
        const lyrics = line.substring(lyricsStart, lyricsEnd);
        segments.push({ chord, lyrics });
    }
    
    return segments;
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
                <span className="cp-chord-name" translate="no" style={{ cursor: 'pointer', borderBottom: '1px dotted var(--gf-text-dim)', opacity: 0.3 }}>{chord}</span>
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
        <span className="cp-chord-name cp-chord-interactive" translate="no"
            onClick={e => { e.stopPropagation(); setEditing(true); }}
            onMouseEnter={() => onChordHover?.(chord)}
            onMouseLeave={() => onChordHover?.(null)}
            title="クリックして編集"
            style={{ cursor: 'pointer' }}
        >{chord}</span>
    );
}

function EditableLyricSegment({ text, onBlur }) {
    const [editing, setEditing] = useState(false);
    const [value, setValue] = useState(text);
    const inputRef = useRef(null);

    useEffect(() => { setValue(text); }, [text]);
    useEffect(() => {
        if (editing && inputRef.current) {
            inputRef.current.focus();
            inputRef.current.select();
        }
    }, [editing]);

    const commit = () => {
        setEditing(false);
        if (value !== text && onBlur) onBlur(value);
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
                    if (e.key === 'Enter') commit();
                    if (e.key === 'Escape') { setValue(text); setEditing(false); }
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
            className="cp-lyrics"
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

/**
 * ChordProView メインコンポーネント
 */
export function ChordProView({ 
    chordproText, 
    currentTime = 0, 
    onSeek, 
    transpose = 0,
    title = '',
    artist = '',
    lineTimings = null,
    onChordproChange = null,
    tuning = 'standard',
    onChordEdit = null,
    onLyricEdit = null,
    onChordHover = null,
    songKey = '',
    session = null,
}) {
    const containerRef = useRef(null);
    const activeLineRef = useRef(null);

    // フルスクリーン制御
    const [isFullscreen, setIsFullscreen] = useState(false);
    useEffect(() => {
        const handleFsChange = () => {
            setIsFullscreen(!!document.fullscreenElement);
        };
        document.addEventListener('fullscreenchange', handleFsChange);
        return () => document.removeEventListener('fullscreenchange', handleFsChange);
    }, []);

    const toggleFullscreen = () => {
        if (!document.fullscreenElement) {
            if (containerRef.current) {
                containerRef.current.requestFullscreen().catch(err => {
                    console.warn("Fullscreen failed", err);
                });
            }
        } else {
            document.exitFullscreen();
        }
    };

    // マウスホイール一時停止: ホイール操作で3秒間スクロールを停止
    const userScrollingRef = useRef(false);
    const userScrollTimerRef = useRef(null);
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;
        const handleWheel = () => {
            userScrollingRef.current = true;
            if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
            userScrollTimerRef.current = setTimeout(() => {
                userScrollingRef.current = false;
            }, 3000);
        };
        container.addEventListener('wheel', handleWheel, { passive: true });
        return () => {
            container.removeEventListener('wheel', handleWheel);
            if (userScrollTimerRef.current) clearTimeout(userScrollTimerRef.current);
        };
    }, []);

    const [editMode, setEditMode] = useState(false);
    const [editText, setEditText] = useState('');
    const [fontSize, setFontSize] = useState(16);
    // scrollMode: 'off' | 'follow' | 'constant'
    const [scrollMode, setScrollMode] = useState('follow');
    const [isChordEditing, setIsChordEditing] = useState(false);
    // 速度（バー）: 0.1 〜 3.0
    const [scrollSpeed, setScrollSpeed] = useState(() => {
        const saved = parseFloat(localStorage.getItem('nc-cp-scroll-speed'));
        return isNaN(saved) ? 1.0 : saved;
    });
    const handleSpeedChange = (e) => {
        const val = parseFloat(e.target.value);
        setScrollSpeed(val);
        localStorage.setItem('nc-cp-scroll-speed', val);
    };

    // コード表示ON/OFF状態
    const [showChords, setShowChords] = useState(() => {
        return localStorage.getItem('nc-cp-show-chords') !== 'false';
    });
    // 押さえ方（ダイヤグラム）表示ON/OFF
    const [showDiagrams, setShowDiagrams] = useState(() => {
        return localStorage.getItem('nc-cp-show-diagrams') === 'true';
    });
    // ローカルテキスト：propから初期化、局所編集を保持
    const [localText, setLocalText] = useState(chordproText || '');

    // prop変更時（新セッション）にリセット
    useEffect(() => {
        setLocalText(chordproText || '');
    }, [chordproText]);

    // パース（localTextを使用）
    const parsed = useMemo(() => parseChordPro(localText), [localText]);

    const isMetaComment = useCallback((text) => {
        return /bpm=|key=|拍子|音符|アクセント|shuffle/i.test(text);
    }, []);

    const groupedSections = useMemo(() => {
        const sections = [];
        let currentSection = {
            type: 'song-section',
            header: null,
            lines: []
        };

        const flushCurrentSection = () => {
            if (currentSection.header || currentSection.lines.length > 0) {
                sections.push(currentSection);
                currentSection = {
                    type: 'song-section',
                    header: null,
                    lines: []
                };
            }
        };

        for (const line of parsed) {
            if (line.type === 'title' || line.type === 'subtitle') {
                flushCurrentSection();
                sections.push({ type: 'header-directive', line });
                continue;
            }

            if (line.type === 'section') {
                if (isMetaComment(line.text)) {
                    flushCurrentSection();
                    sections.push({ type: 'meta-banner', line });
                } else {
                    flushCurrentSection();
                    currentSection = {
                        type: 'song-section',
                        header: line,
                        lines: []
                    };
                }
            } else {
                currentSection.lines.push(line);
            }
        }
        flushCurrentSection();
        return sections;
    }, [parsed, isMetaComment]);

    const chordTimeline = useMemo(() => {
        if (!session?.data) return [];
        const out = [];
        let last = '';
        for (const e of session.data) {
            const c = transposeChord(e.chord || '', transpose);
            if (c !== last) {
                out.push({ time: e.time, chord: c });
                last = c;
            }
        }
        return out;
    }, [session?.data, transpose]);

    // アクティブ行の検出
    const activeIdx = useMemo(() => {
        if (!lineTimings || !lineTimings.length) return -1;
        for (let i = lineTimings.length - 1; i >= 0; i--) {
            if (currentTime >= lineTimings[i].startTime) return i;
        }
        return -1;
    }, [currentTime, lineTimings]);

    // ① コード追従モード: アクティブ行へスクロール
    useEffect(() => {
        if (scrollMode !== 'follow' || isChordEditing) return;
        if (userScrollingRef.current) return; // ホイール操作中はスキップ
        if (activeLineRef.current) {
            activeLineRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, [activeIdx, scrollMode, isChordEditing]);

    // ② 定速スクロールモード
    useEffect(() => {
        if (scrollMode !== 'constant' || !containerRef.current || isChordEditing) return;
        let id;
        let startMs = performance.now();
        let startScroll = containerRef.current.scrollTop;

        const step = now => {
            if (!containerRef.current) return;

            const currentScroll = containerRef.current.scrollTop;
            const elapsed = now - startMs;
            const targetScroll = startScroll + elapsed * scrollSpeed * 0.03;

            // ユーザーが手動でスクロールしたか、一番下に到達してtargetScrollだけが進んだ場合、
            // 基準点（startMs, startScroll）を現在位置にリセットする
            if (userScrollingRef.current || Math.abs(currentScroll - targetScroll) > 2) {
                startMs = now;
                startScroll = currentScroll;
            } else {
                containerRef.current.scrollTop = targetScroll;
            }

            id = requestAnimationFrame(step);
        };
        id = requestAnimationFrame(step);
        return () => cancelAnimationFrame(id);
    }, [scrollMode, scrollSpeed, isChordEditing]);

    // 編集モード切替（局所テキストを保存）
    const toggleEdit = useCallback(() => {
        if (editMode) {
            // 編集終了時に2行形式プレーンテキストからChordPro形式に戻して保存
            const newChordPro = plainTextToChordpro(editText);
            setLocalText(newChordPro);
            if (onChordproChange) onChordproChange(newChordPro);
            setEditMode(false);
        } else {
            // 編集開始時にChordPro形式を2行形式のプレーンテキストに変換
            setEditText(chordproToPlainText(localText || ''));
            setEditMode(true);
        }
    }, [editMode, localText, editText, onChordproChange]);

    // レンダリング用の行インデックスカウンター（タイミング行のみカウント）
    let timingIdx = 0;

    const [portalTarget, setPortalTarget] = useState(null);
    useEffect(() => {
        // Find the portal target after initial render
        const target = document.getElementById('cp-portal-target');
        if (target) setPortalTarget(target);
    }, []);

    const scrollControls = (
        <div className="cp-scroll-controls" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <button
                className={`cp-scroll-btn ${scrollMode === 'constant' ? 'cl-btn-active' : ''}`}
                onClick={() => setScrollMode(m => m === 'constant' ? 'off' : 'constant')}
                title="一定速度で自動スクロール"
            >自動</button>
            
            <div className={`flex items-center gap-2 mx-1 ${scrollMode !== 'constant' ? 'opacity-50' : ''}`}>
                <span className="text-[10px] text-[var(--gf-text)]">遅</span>
                <input 
                    type="range" 
                    min="0.1" 
                    max="3.0" 
                    step="0.1" 
                    value={scrollSpeed} 
                    onChange={handleSpeedChange}
                    className="w-20 accent-[var(--nc-primary)]"
                />
                <span className="text-[10px] text-[var(--gf-text)]">速</span>
            </div>

            <button
                className={`cp-scroll-btn ${scrollMode === 'follow' ? 'cl-btn-active' : ''}`}
                onClick={() => setScrollMode(m => m === 'follow' ? 'off' : 'follow')}
                title="再生中のコードに合わせて自動スクロール"
            >追従</button>
        </div>
    );

    const controls = (
        <div className="cp-controls" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {/* スクロール制御 */}
            {scrollControls}
            
            <div className="nc-ribbon-divider" style={{ height: '24px' }} />

            <div className="flex items-center gap-1 mx-1">
                <span className="text-[10px] text-[var(--gf-text)] font-bold">A</span>
                <input 
                    type="range" 
                    min="12" 
                    max="32" 
                    step="1" 
                    value={fontSize} 
                    onChange={(e) => {
                        const val = parseInt(e.target.value, 10);
                        setFontSize(val);
                        localStorage.setItem('nc-cp-fontsize', val.toString());
                    }}
                    className="w-20 accent-[var(--nc-primary)]"
                    title={`文字サイズ: ${fontSize}px`}
                />
                <span className="text-sm text-[var(--gf-text)] font-bold">A</span>
            </div>
            
            <div className="nc-ribbon-divider" style={{ height: '24px' }} />
            
            <button
                className={`cp-scroll-btn ${showChords ? 'cl-btn-active' : ''}`}
                onClick={() => {
                    setShowChords(p => {
                        const v = !p;
                        localStorage.setItem('nc-cp-show-chords', v.toString());
                        return v;
                    });
                }}
                title="コードの表示/非表示を切り替え"
            >
                {showChords ? 'コード表示' : 'コード非表示'}
            </button>
            
            <button
                className={`cp-scroll-btn ${showDiagrams ? 'cl-btn-active' : ''}`}
                onClick={() => {
                    setShowDiagrams(p => {
                        const v = !p;
                        localStorage.setItem('nc-cp-show-diagrams', v.toString());
                        return v;
                    });
                }}
                disabled={!showChords}
                title="ギター押さえ方（ダイヤグラム）の表示"
            >
                押さえ方
            </button>

            <div className="nc-ribbon-divider" style={{ height: '24px' }} />

            <button
                className={`cp-edit-btn ${editMode ? 'active' : ''}`}
                onClick={toggleEdit}
                title="ChordPro編集"
            >
                {editMode ? '✓ 完了' : '✎ 編集'}
            </button>

            <div className="nc-ribbon-divider" style={{ height: '24px' }} />

            <button
                className="cp-scroll-btn flex items-center justify-center gap-1 hover:text-[var(--gf-amber)]"
                onClick={toggleFullscreen}
                title="全画面表示"
            >
                <Maximize size={16} /> 全画面
            </button>
        </div>
    );

    return (
        <div className="chordpro-view" ref={containerRef} style={isFullscreen ? { backgroundColor: 'var(--gf-surface)', padding: '2rem', overflowY: 'auto' } : {}}>
            {portalTarget && createPortal(controls, portalTarget)}
            {isFullscreen && (
                <div className="fixed bottom-6 right-6 flex items-center gap-4 bg-[var(--gf-surface-2)] p-2 rounded-2xl shadow-2xl z-50 border border-[var(--gf-border)]" style={{ position: 'fixed' }}>
                    {scrollControls}
                    <div className="w-px h-6 bg-[var(--gf-border)]"></div>
                    <button
                        className="p-2 text-[var(--gf-text)] hover:text-[var(--gf-amber)] transition-all flex items-center justify-center rounded-full hover:bg-[var(--gf-surface)]"
                        onClick={toggleFullscreen}
                        title="全画面表示を終了"
                    >
                        <Minimize size={20} />
                    </button>
                </div>
            )}
            {/* 編集モード */}
            {editMode ? (
                <div className="cp-editor-container">
                    <textarea
                        className="cp-editor"
                        value={editText}
                        onChange={e => setEditText(e.target.value)}
                        style={{ fontSize: `${fontSize}px`, fontFamily: 'Consolas, Monaco, "Courier New", monospace', whiteSpace: 'pre', overflowX: 'auto' }}
                        spellCheck={false}
                    />
                    <div className="cp-editor-hint">
                        💡 2行スタイル編集中（上がコード、下が歌詞）。「✓ 完了」で自動変換して保存されます。
                    </div>
                </div>
            ) : (
                /* 表示モード */
                <div 
                    className={`cp-content ${!showChords ? 'cp-hide-chords' : ''}`} 
                    style={{ fontSize: `${fontSize}px` }}
                    onClick={(e) => {
                        // ボタンや入力欄のクリックは無視
                        if (e.target.closest('button') || e.target.closest('input')) return;
                        // テキスト選択時は無視
                        if (window.getSelection().toString().length > 0) return;
                        
                        // 自動スクロール（一定速度）のON/OFFを切り替え
                        setScrollMode(m => m === 'constant' ? 'off' : 'constant');
                    }}
                >
                    {groupedSections.map((section, si) => {
                        if (section.type === 'header-directive') {
                            return null;
                        }

                        if (section.type === 'meta-banner') {
                            return (
                                <div key={`meta-${si}`} className="cp-meta-banner">
                                    <svg className="w-4 h-4 text-emerald-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                                        <circle cx="12" cy="12" r="10"></circle>
                                        <line x1="12" y1="16" x2="12" y2="12"></line>
                                        <line x1="12" y1="8" x2="12.01" y2="8"></line>
                                    </svg>
                                    <span>{section.line.text}</span>
                                </div>
                            );
                        }

                        // section.type === 'song-section'
                        return (
                            <div key={`sec-${si}`} className="cp-section-block">
                                {section.header && (
                                    <div className="cp-section-title-badge">
                                        {section.header.text}
                                    </div>
                                )}
                                <div className="cp-section-body">
                                    {section.lines.map((line, li) => {
                                        const isTimingLine = line.type === 'chord-lyric' || line.type === 'chord-only';
                                        const currentTimingIdx = isTimingLine ? timingIdx++ : -1;
                                        const isActive = currentTimingIdx >= 0 && currentTimingIdx === activeIdx;

                                        switch (line.type) {
                                            case 'chord-only': {
                                                const lineStart = lineTimings?.[currentTimingIdx]?.startTime ?? 0;
                                                const nextTiming = lineTimings?.[currentTimingIdx + 1];
                                                const lineEnd = nextTiming ? nextTiming.startTime : lineStart + 15.0;
                                                let windowChords = chordTimeline.filter(c => c.time >= lineStart - 0.1 && c.time < lineEnd - 0.1);
                                                
                                                // Find sustained chord from previous lines
                                                const sustainedChordObj = [...chordTimeline]
                                                    .reverse()
                                                    .find(c => c.time < lineStart - 0.1);
                                                
                                                if (sustainedChordObj && sustainedChordObj.chord !== 'N.C.') {
                                                    const flatLineChords = (line.measures || []).flat().filter(c => c && c !== '|');
                                                    const firstLineChord = flatLineChords[0];
                                                    if (firstLineChord) {
                                                        const firstTransposed = transposeChord(firstLineChord, transpose);
                                                        if (firstTransposed === sustainedChordObj.chord) {
                                                            windowChords = [sustainedChordObj, ...windowChords];
                                                        }
                                                    }
                                                }
                                                
                                                let chordCounter = 0;

                                                return (
                                                    <div 
                                                        key={`line-${li}`} 
                                                        ref={isActive ? activeLineRef : null}
                                                        className={`cp-line cp-chord-only ${isActive ? 'cp-line-active' : ''}`}
                                                        onClick={() => onSeek && lineTimings?.[currentTimingIdx] && 
                                                            onSeek(lineTimings[currentTimingIdx].startTime)}
                                                    >
                                                        <div className="cp-chord-row" style={{ display: 'flex', width: '100%', alignItems: 'stretch', flexWrap: 'wrap' }}>
                                                            {(line.measures || []).map((measureChords, mi) => (
                                                                <div key={mi} className="cp-measure">
                                                                    {measureChords.map((c, ci) => {
                                                                        if (c === '|') return null;
                                                                        const transposed = transposeChord(c, transpose);
                                                                        const chordObj = windowChords[chordCounter];
                                                                        const chordTime = chordObj ? chordObj.time : (lineStart + chordCounter * 2.0);
                                                                        chordCounter++;

                                                                        return (
                                                                            <span key={ci} className="cp-chord" translate="no">
                                                                                {onChordEdit ? (
                                                                                    <EditableChord chord={transposed} time={chordTime}
                                                                                        onChordEdit={onChordEdit} onChordHover={onChordHover} songKey={songKey}
                                                                                        onEditingStateChange={setIsChordEditing} />
                                                                                ) : (
                                                                                    <span className="cp-chord-name">{transposed}</span>
                                                                                )}
                                                                                <div className={`cp-diagram-wrapper ${showDiagrams ? 'inline-mode' : 'hover-mode'}`}>
                                                                                    <GuitarChord chordName={transposed} tuning={tuning} />
                                                                                </div>
                                                                            </span>
                                                                        );
                                                                    })}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                );
                                            }
                                            case 'chord-lyric': {
                                                const lineStart = lineTimings?.[currentTimingIdx]?.startTime ?? 0;
                                                const nextTiming = lineTimings?.[currentTimingIdx + 1];
                                                const lineEnd = nextTiming ? nextTiming.startTime : lineStart + 15.0;
                                                let windowChords = chordTimeline.filter(c => c.time >= lineStart - 0.1 && c.time < lineEnd - 0.1);
                                                
                                                // Find sustained chord from previous lines
                                                const sustainedChordObj = [...chordTimeline]
                                                    .reverse()
                                                    .find(c => c.time < lineStart - 0.1);
                                                
                                                if (sustainedChordObj && sustainedChordObj.chord !== 'N.C.') {
                                                    const flatLineChords = (line.measures || []).flat().filter(s => s && s.chord && s.chord !== '|').map(s => s.chord);
                                                    const firstLineChord = flatLineChords[0];
                                                    if (firstLineChord) {
                                                        const firstTransposed = transposeChord(firstLineChord, transpose);
                                                        if (firstTransposed === sustainedChordObj.chord) {
                                                            windowChords = [sustainedChordObj, ...windowChords];
                                                        }
                                                    }
                                                }
                                                
                                                let chordCounter = 0;
                                                const isRhy = isRhythmLine(line);

                                                return (
                                                    <div 
                                                        key={`line-${li}`} 
                                                        ref={isActive ? activeLineRef : null}
                                                        className={`cp-line cp-has-lyrics ${isActive ? 'cp-line-active' : ''} ${isRhy ? 'cp-rhythm-line' : ''}`}
                                                        onClick={() => onSeek && lineTimings?.[currentTimingIdx] && 
                                                            onSeek(lineTimings[currentTimingIdx].startTime)}
                                                    >
                                                        <div style={{ display: 'flex', width: '100%', alignItems: 'stretch', flexWrap: 'wrap' }}>
                                                            {(line.measures || []).map((measure, mi) => (
                                                                <div key={mi} className="cp-measure">
                                                                    {measure.map((seg, si) => {
                                                                        const isBarLine = seg.chord === '|';
                                                                        if (isBarLine && !seg.lyrics) return null;

                                                                        let chordTime = lineStart;
                                                                        let transposed = '';
                                                                        if (seg.chord && !isBarLine) {
                                                                            transposed = transposeChord(seg.chord, transpose);
                                                                            const chordObj = windowChords[chordCounter];
                                                                            chordTime = chordObj ? chordObj.time : (lineStart + chordCounter * 2.0);
                                                                            chordCounter++;
                                                                        }

                                                                        return (
                                                                            <React.Fragment key={si}>
                                                                                <span className="cp-segment">
                                                                                    {seg.chord && !isBarLine ? (
                                                                                        <span className="cp-chord" translate="no">
                                                                                            {onChordEdit ? (
                                                                                                <EditableChord chord={transposed} time={chordTime}
                                                                                                    onChordEdit={onChordEdit} onChordHover={onChordHover} songKey={songKey}
                                                                                                    onEditingStateChange={setIsChordEditing} />
                                                                                            ) : (
                                                                                                <span className="cp-chord-name">{transposed}</span>
                                                                                            )}
                                                                                            <div className={`cp-diagram-wrapper ${showDiagrams ? 'inline-mode' : 'hover-mode'}`}>
                                                                                                <GuitarChord chordName={transposed} tuning={tuning} />
                                                                                            </div>
                                                                                        </span>
                                                                                    ) : (
                                                                                        <span className="cp-chord cp-chord-placeholder" style={{ visibility: 'hidden' }}>{"\u00A0"}</span>
                                                                                    )}
                                                                                    
                                                                                    {onLyricEdit ? (
                                                                                        <EditableLyricSegment 
                                                                                            text={seg.lyrics || ''}
                                                                                            onBlur={(newSegText) => {
                                                                                                const flatSegs = line.measures.flat();
                                                                                                const targetIdx = flatSegs.findIndex(s => s === seg);
                                                                                                const updatedSegs = flatSegs.map((s, idx) => idx === targetIdx ? newSegText : (s.lyrics || ''));
                                                                                                const newFullText = updatedSegs.join('');
                                                                                                onLyricEdit(lineStart, newFullText);
                                                                                            }}
                                                                                        />
                                                                                    ) : (
                                                                                        <span className="cp-lyrics">{(!seg.lyrics) ? "\u00A0" : seg.lyrics}</span>
                                                                                    )}
                                                                                </span>
                                                                            </React.Fragment>
                                                                        );
                                                                    })}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                );
                                            }
                                            case 'empty':
                                                return <div key={`line-${li}`} className="cp-empty-line" />;
                                            default:
                                                return null;
                                        }
                                    })}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

export default ChordProView;
