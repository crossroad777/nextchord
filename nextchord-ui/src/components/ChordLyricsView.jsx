import React, { useMemo, useRef, useEffect, useState } from 'react';

/**
 * ChordLyricsView — U-FRETスタイルのコード付き歌詞表示
 *
 * 等幅フォントで2行表示:
 *   行1: コード行 (半角スペースで位置合わせ)
 *   行2: 歌詞行 (lyrics_phrasesのテキストをそのまま使用)
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

/** 文字の表示幅（全角=2, 半角=1） */
function charWidth(c) {
    const code = c.charCodeAt(0);
    if (code >= 0x3000) return 2;
    if (code >= 0xFF01 && code <= 0xFF5E) return 2;
    return 1;
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
 * 助詞・接続助詞・て形の後を優先
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

    // Pass 1: 連続フレーズをブロックに結合
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

    // Pass 2: 長いブロックを自然な位置で再分割
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
 * フレーズのテキスト内のコード位置を計算
 * structured_data のword-levelタイムスタンプを使って各文字の時刻を推定し、
 * コードのtimeと照合して正確な位置に配置する
 */
function calculateChordPositions(chords, phraseText, startTime, endTime, data) {
    if (chords.length === 0) return [];
    if (!phraseText || phraseText.length === 0) {
        return chords.map((c, i) => ({
            chord: c.chord, time: c.time, charIdx: i * 4, col: i * 5,
        }));
    }

    const textLen = phraseText.length;

    // structured_data から、このフレーズ範囲内の歌詞タイムスタンプを構築
    // 各文字に対応する発音時刻の配列を作る
    const charTimes = [];  // charTimes[i] = i文字目の発音開始時刻

    if (data && Array.isArray(data)) {
        // フレーズ内のエントリを抽出（歌詞があるもののみ）
        const phraseEntries = data.filter(d =>
            d.lyric && d.lyric.trim() &&
            d.time >= startTime - 0.3 && d.time < endTime + 0.3
        );

        // 各歌詞断片のテキストと時刻を並べる
        let pos = 0;
        for (const entry of phraseEntries) {
            const lyricClean = (entry.lyric || '').replace(/\s+/g, '');
            if (!lyricClean) continue;

            // phraseText 内でこの歌詞テキストがどこにあるか探す
            const idx = phraseText.indexOf(lyricClean, pos);
            if (idx >= 0) {
                // この歌詞の各文字に時刻を割り当て
                const lyricDuration = entry.lyric_duration || entry.duration || 0.5;
                for (let c = 0; c < lyricClean.length; c++) {
                    const charTime = entry.time + (lyricDuration * c / Math.max(1, lyricClean.length));
                    charTimes[idx + c] = charTime;
                }
                pos = idx + lyricClean.length;
            }
        }

        // 未設定の文字は前後から補間する
        // まず最初と最後を設定
        if (charTimes.length === 0 || charTimes[0] === undefined) {
            charTimes[0] = startTime;
        }
        // 前方から埋める
        for (let i = 1; i < textLen; i++) {
            if (charTimes[i] === undefined) {
                charTimes[i] = charTimes[i - 1] !== undefined
                    ? charTimes[i - 1] + 0.05  // 微小増分
                    : startTime + (endTime - startTime) * (i / textLen);
            }
        }
    }

    // charTimesが空の場合はフォールバック（線形補間）
    if (charTimes.length === 0) {
        for (let i = 0; i < textLen; i++) {
            charTimes[i] = startTime + (endTime - startTime) * (i / textLen);
        }
    }

    const entries = [];

    for (const c of chords) {
        // コードのtimeに最も近い文字位置を見つける
        let bestIdx = 0;
        let bestDiff = Infinity;
        for (let i = 0; i < textLen; i++) {
            const diff = Math.abs((charTimes[i] || startTime) - c.time);
            if (diff < bestDiff) {
                bestDiff = diff;
                bestIdx = i;
            }
        }

        let col = 0;
        for (let i = 0; i < bestIdx && i < phraseText.length; i++) {
            col += charWidth(phraseText[i]);
        }

        entries.push({ chord: c.chord, time: c.time, charIdx: bestIdx, col });
    }

    // コード同士の重なりを防ぐ
    for (let i = 1; i < entries.length; i++) {
        const prev = entries[i - 1];
        const minCol = prev.col + prev.chord.length + 1;
        if (entries[i].col < minCol) {
            entries[i].col = minCol;
        }
    }

    return entries;
}

/**
 * コード位置からコード行文字列を構築
 */
function buildChordString(chordPositions) {
    let line = '';
    let cursor = 0;
    for (const cp of chordPositions) {
        if (cp.col > cursor) {
            line += ' '.repeat(cp.col - cursor);
        }
        line += cp.chord;
        cursor = cp.col + cp.chord.length;
    }
    return line;
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

        // displayPhrases（サーバー側Janome処理済み）を優先、なければフロントエンド側で処理
        const phrases = (displayPhrases && displayPhrases.length > 0)
            ? displayPhrases
            : (lyricsPhrases && lyricsPhrases.length > 0)
                ? processPhrasesForDisplay(lyricsPhrases, 25)
                : [];

        if (phrases.length > 0) {
            const merged = phrases;

            for (let i = 0; i < merged.length; i++) {
                const phrase = merged[i];
                const prevEnd = i > 0 ? merged[i - 1].end : (data[0]?.time || 0);

                if (phrase.start - prevEnd > 3.0) {
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
            const chordPositions = calculateChordPositions(chords, lyricText, pr.startTime, pr.endTime, data);
            const chordLine = buildChordString(chordPositions);

            result.push({
                startTime: pr.startTime, endTime: pr.endTime,
                chordLine, lyricText, chordPositions,
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
                        <div className="cl-chord-line">
                            {onChordEdit ? (
                                line.chordPositions.map((ce, ci) => {
                                    const prevEnd = ci > 0
                                        ? line.chordPositions[ci - 1].col + line.chordPositions[ci - 1].chord.length
                                        : 0;
                                    const spaces = ce.col - prevEnd;
                                    return (
                                        <React.Fragment key={ci}>
                                            {spaces > 0 && <span>{' '.repeat(spaces)}</span>}
                                            <EditableChord chord={ce.chord} time={ce.time} onChordEdit={onChordEdit} />
                                        </React.Fragment>
                                    );
                                })
                            ) : (
                                <span>{line.chordLine}</span>
                            )}
                        </div>
                        {line.hasLyric && (
                            <div className="cl-lyric-line">
                                {onLyricEdit ? (
                                    <EditableLyric text={line.lyricText} startTime={line.startTime} onLyricEdit={onLyricEdit} />
                                ) : (
                                    line.lyricText
                                )}
                            </div>
                        )}
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
