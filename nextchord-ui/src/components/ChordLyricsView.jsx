import React, { useMemo, useRef, useEffect, useState } from 'react';

/**
 * ChordLyricsView — U-FRETスタイルのコード付き歌詞表示
 *
 * セグメントベースの2行表示:
 *   コード名の真下に対応する歌詞文字列を配置
 *   各セグメントは inline-block で、コード名の幅以上を確保
 */

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
    return text.replace(/\s+/g, '').trim();
}

/** インライン編集可能なコードラベル */
function EditableChord({ chord, time, onChordEdit }) {
    const [editing, setEditing] = useState(false);
    const [value, setValue] = useState(chord);
    const inputRef = useRef(null);

    useEffect(() => { setValue(chord); }, [chord]);
    useEffect(() => { if (editing && inputRef.current) inputRef.current.focus(); }, [editing]);

    const handleCommit = () => {
        setEditing(false);
        if (value !== chord && onChordEdit) onChordEdit(time, value);
    };

    if (editing) {
        return (
            <input
                ref={inputRef}
                className="chord-edit-input"
                value={value}
                onChange={e => setValue(e.target.value)}
                onBlur={handleCommit}
                onKeyDown={e => {
                    if (e.key === 'Enter') handleCommit();
                    if (e.key === 'Escape') { setValue(chord); setEditing(false); }
                }}
            />
        );
    }
    return (
        <span
            className="cl-chord-text"
            onClick={e => { e.stopPropagation(); setEditing(true); }}
            title="クリックして編集"
        >{chord}</span>
    );
}

/** インライン編集可能な歌詞行 */
function EditableLyric({ text, startTime, onLyricEdit }) {
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

    const handleCommit = () => {
        setEditing(false);
        if (value !== text && onLyricEdit) onLyricEdit(startTime, value);
    };

    if (editing) {
        return (
            <input
                ref={inputRef}
                className="lyric-edit-input"
                value={value}
                onChange={e => setValue(e.target.value)}
                onBlur={handleCommit}
                onClick={e => e.stopPropagation()}
                onKeyDown={e => {
                    if (e.key === 'Enter') handleCommit();
                    if (e.key === 'Escape') { setValue(text); setEditing(false); }
                }}
            />
        );
    }
    return (
        <span
            className="cl-lyric-editable"
            onClick={e => { e.stopPropagation(); setEditing(true); }}
            title="クリックして歌詞を編集"
        >{text}</span>
    );
}

/**
 * 日本語の自然な分割位置を探す
 */
function findSplitPoint(text, idealPos) {
    const searchRange = 8;
    const start = Math.max(0, idealPos - searchRange);
    const end = Math.min(text.length, idealPos + searchRange);

    const patterns = [
        /[。！？\n]/,
        /[てでしりくがはをにへもとの](?=[ぁ-ん]|[ァ-ヶ]|[一-龥]|[A-Za-z])/,
        /[ァ-ヶー](?=[ぁ-ん]|[一-龥])/,
    ];

    let bestPos = -1;
    let bestDist = Infinity;

    for (const pattern of patterns) {
        for (let i = start; i < end; i++) {
            const sub = text.substring(i, i + 2);
            if (pattern.test(sub)) {
                const splitAt = i + 1;
                const dist = Math.abs(splitAt - idealPos);
                if (dist < bestDist) {
                    bestDist = dist;
                    bestPos = splitAt;
                }
            }
        }
        if (bestPos >= 0) break;
    }

    return bestPos >= 0 ? bestPos : idealPos;
}

/**
 * lyrics_phrasesを処理:
 * 1. gap < 1sの連続フレーズをまず全て結合（ブロック化）
 * 2. 長すぎるブロックを自然な位置で再分割
 */
function processPhrasesForDisplay(phrases, targetChars = 25) {
    if (!phrases || phrases.length === 0) return [];

    const blocks = [];
    let cur = {
        start: phrases[0].start,
        end: phrases[0].end,
        text: cleanJapaneseText(phrases[0].text),
    };

    for (let i = 1; i < phrases.length; i++) {
        const p = phrases[i];
        const pText = cleanJapaneseText(p.text);
        const gap = p.start - cur.end;

        if (gap < 1.0) {
            cur.end = p.end;
            cur.text += pText;
        } else {
            blocks.push(cur);
            cur = { start: p.start, end: p.end, text: pText };
        }
    }
    blocks.push(cur);

    const result = [];
    for (const block of blocks) {
        const text = block.text;
        if (text.length <= targetChars + 5) {
            result.push(block);
            continue;
        }

        const totalDuration = block.end - block.start;
        let pos = 0;
        while (pos < text.length) {
            const remaining = text.length - pos;
            if (remaining <= targetChars + 5) {
                const ratio1 = pos / text.length;
                result.push({
                    start: block.start + totalDuration * ratio1,
                    end: block.end,
                    text: text.substring(pos),
                });
                break;
            }

            const splitPos = findSplitPoint(text, pos + targetChars);
            const chunk = text.substring(pos, splitPos);
            const ratio1 = pos / text.length;
            const ratio2 = splitPos / text.length;
            result.push({
                start: block.start + totalDuration * ratio1,
                end: block.start + totalDuration * ratio2,
                text: chunk,
            });
            pos = splitPos;
        }
    }

    return result;
}

/**
 * ★ コアアルゴリズム: フレーズ内のコードと歌詞をセグメントに分割
 * 
 * 各セグメント = { chord: string, lyrics: string, time: number }
 * コード変化点で歌詞を区切り、各セグメントが対応する歌詞を持つ
 */
function buildChordLyricSegments(chords, phraseText, startTime, endTime, data) {
    const lyricText = phraseText || '';
    const textLen = lyricText.length;

    // 1. 各文字の発音時刻を推定
    const charTimes = new Array(textLen);

    if (data && Array.isArray(data)) {
        const phraseEntries = data.filter(d =>
            d.lyric && d.lyric.trim() &&
            d.time >= startTime - 0.3 && d.time < endTime + 0.3
        );

        let pos = 0;
        for (const entry of phraseEntries) {
            const lyricClean = (entry.lyric || '').replace(/\s+/g, '');
            if (!lyricClean) continue;

            const idx = lyricText.indexOf(lyricClean, pos);
            if (idx >= 0) {
                const lyricDuration = entry.lyric_duration || entry.duration || 0.5;
                for (let c = 0; c < lyricClean.length; c++) {
                    const charTime = entry.time + (lyricDuration * c / Math.max(1, lyricClean.length));
                    charTimes[idx + c] = charTime;
                }
                pos = idx + lyricClean.length;
            }
        }
    }

    // 未設定の文字を補間
    if (textLen > 0 && charTimes[0] === undefined) {
        charTimes[0] = startTime;
    }
    for (let i = 1; i < textLen; i++) {
        if (charTimes[i] === undefined) {
            charTimes[i] = charTimes[i - 1] !== undefined
                ? charTimes[i - 1] + 0.05
                : startTime + (endTime - startTime) * (i / textLen);
        }
    }
    if (textLen === 0) {
        // 歌詞なし（イントロ・間奏）→ コードのみ
        return chords.map(c => ({
            chord: c.chord,
            lyrics: '',
            time: c.time,
        }));
    }

    if (chords.length === 0) {
        // コード変化なし → 歌詞のみ
        return [{ chord: '', lyrics: lyricText, time: startTime }];
    }

    // 2. 各コードの文字位置を計算
    const chordCharIdx = [];
    for (const c of chords) {
        let bestIdx = 0;
        let bestDiff = Infinity;
        for (let i = 0; i < textLen; i++) {
            const diff = Math.abs((charTimes[i] || startTime) - c.time);
            if (diff < bestDiff) {
                bestDiff = diff;
                bestIdx = i;
            }
        }
        chordCharIdx.push({ chord: c.chord, time: c.time, charIdx: bestIdx });
    }

    // 重複するcharIdxを解消（次のコードは最低1文字先に）
    for (let i = 1; i < chordCharIdx.length; i++) {
        if (chordCharIdx[i].charIdx <= chordCharIdx[i - 1].charIdx) {
            chordCharIdx[i].charIdx = Math.min(chordCharIdx[i - 1].charIdx + 1, textLen - 1);
        }
    }

    // 3. セグメント構築
    const segments = [];

    // 最初のコードより前に歌詞がある場合
    if (chordCharIdx[0].charIdx > 0) {
        segments.push({
            chord: '',
            lyrics: lyricText.substring(0, chordCharIdx[0].charIdx),
            time: startTime,
        });
    }

    for (let i = 0; i < chordCharIdx.length; i++) {
        const startIdx = chordCharIdx[i].charIdx;
        const endIdx = (i + 1 < chordCharIdx.length) ? chordCharIdx[i + 1].charIdx : textLen;
        segments.push({
            chord: chordCharIdx[i].chord,
            lyrics: lyricText.substring(startIdx, endIdx),
            time: chordCharIdx[i].time,
        });
    }

    return segments;
}

export function ChordLyricsView({ data, lyricsPhrases, displayPhrases, currentTime, onSeek, onChordEdit, onLyricEdit, transpose = 0, title, artist }) {
    const activeRef = useRef(null);

    // コード変化タイムライン
    const chordTimeline = useMemo(() => {
        if (!data || !Array.isArray(data)) return [];
        const changes = [];
        let lastChord = '';
        for (const entry of data) {
            const chord = entry.chord || 'N.C.';
            if (chord !== 'N.C.' && chord !== lastChord) {
                changes.push({ time: entry.time, chord: transposeChord(chord, transpose) });
                lastChord = chord;
            }
        }
        return changes;
    }, [data, transpose]);

    // ライン構築
    const lines = useMemo(() => {
        if (!data || !Array.isArray(data) || data.length === 0) return [];

        let phraseRanges = [];

        const phrases = (displayPhrases && displayPhrases.length > 0)
            ? displayPhrases
            : (lyricsPhrases && lyricsPhrases.length > 0)
                ? processPhrasesForDisplay(lyricsPhrases, 25)
                : [];

        if (phrases.length > 0) {
            const merged = phrases;
            const songStart = data[0]?.time || 0;
            if (merged[0].start - songStart > 2.0) {
                phraseRanges.push({ startTime: songStart, endTime: merged[0].start, text: '', isInstrumental: true });
            }

            for (let i = 0; i < merged.length; i++) {
                const phrase = merged[i];
                const prevEnd = i > 0 ? merged[i - 1].end : songStart;

                if (i > 0 && phrase.start - prevEnd > 3.0) {
                    phraseRanges.push({ startTime: prevEnd, endTime: phrase.start, text: '', isInstrumental: true });
                }
                phraseRanges.push({ startTime: phrase.start, endTime: phrase.end, text: phrase.text, isInstrumental: false });
            }

            const lastEnd = merged[merged.length - 1].end;
            const lastDataTime = data[data.length - 1]?.time || lastEnd;
            if (lastDataTime - lastEnd > 3.0) {
                phraseRanges.push({ startTime: lastEnd, endTime: lastDataTime + 1, text: '', isInstrumental: true });
            }
        } else {
            const barInfo = {};
            for (const entry of data) {
                const bar = entry.bar;
                if (!barInfo[bar]) barInfo[bar] = { startTime: entry.time, endTime: entry.time + (entry.duration || 0.5) };
                const endT = entry.time + (entry.duration || 0.5);
                if (endT > barInfo[bar].endTime) barInfo[bar].endTime = endT;
            }
            const barNums = Object.keys(barInfo).map(Number).sort((a, b) => a - b);
            for (let i = 0; i < barNums.length; i += 4) {
                const groupBars = barNums.slice(i, i + 4);
                let text = '';
                for (const entry of data) {
                    if (entry.lyric && entry.time >= barInfo[groupBars[0]].startTime &&
                        entry.time < barInfo[groupBars[groupBars.length - 1]].endTime) {
                        text += entry.lyric;
                    }
                }
                phraseRanges.push({
                    startTime: barInfo[groupBars[0]].startTime,
                    endTime: barInfo[groupBars[groupBars.length - 1]].endTime,
                    text: cleanJapaneseText(text),
                    isInstrumental: false,
                });
            }
        }

        const result = [];
        for (const pr of phraseRanges) {
            const chords = chordTimeline.filter(c => c.time >= pr.startTime - 0.1 && c.time < pr.endTime + 0.1);
            if (chords.length === 0 && !pr.text) continue;

            const lyricText = pr.text || '';
            const segments = buildChordLyricSegments(chords, lyricText, pr.startTime, pr.endTime, data);

            result.push({
                startTime: pr.startTime, endTime: pr.endTime,
                segments,
                hasLyric: lyricText.length > 0, isInstrumental: pr.isInstrumental,
            });
        }
        return result;
    }, [data, lyricsPhrases, displayPhrases, chordTimeline, transpose]);

    // アクティブ行
    const activeIdx = lines.findIndex(l => currentTime >= l.startTime && currentTime < l.endTime);
    useEffect(() => {
        if (activeRef.current) {
            activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, [activeIdx]);

    return (
        <div className="chord-lyrics-view">
            {(title || artist) && (
                <div className="cl-header">
                    {title && <div className="cl-title">{title}</div>}
                    {artist && <div className="cl-artist">{artist}</div>}
                </div>
            )}

            {(onChordEdit || onLyricEdit) && (
                <div className="cl-edit-hint">💡 コード・歌詞をクリックして手動修正できます</div>
            )}

            {lines.map((line, li) => {
                const isActive = li === activeIdx;
                return (
                    <div
                        key={li}
                        ref={isActive ? activeRef : null}
                        className={`cl-line ${isActive ? 'cl-line-active' : ''}`}
                        onClick={() => onSeek && onSeek(line.startTime)}
                    >
                        {/* セグメントベースの2行表示: コードと歌詞が完全同期 */}
                        <div className="cl-segments-row">
                            {line.segments.map((seg, si) => (
                                <div key={si} className="cl-segment">
                                    <div className="cl-segment-chord">
                                        {seg.chord ? (
                                            onChordEdit ? (
                                                <EditableChord chord={seg.chord} time={seg.time} onChordEdit={onChordEdit} />
                                            ) : (
                                                <span className="cl-chord-text">{seg.chord}</span>
                                            )
                                        ) : (
                                            <span className="cl-chord-spacer">&nbsp;</span>
                                        )}
                                    </div>
                                    <div className="cl-segment-lyric">
                                        {seg.lyrics || '\u00A0'}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                );
            })}

            {lines.length === 0 && (
                <div style={{ textAlign: 'center', color: 'var(--nc-text-muted)', padding: '3rem' }}>
                    データを読み込み中...
                </div>
            )}
        </div>
    );
}

export default ChordLyricsView;
