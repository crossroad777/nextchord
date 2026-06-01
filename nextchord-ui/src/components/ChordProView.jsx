import React, { useMemo, useRef, useEffect, useState, useCallback } from 'react';

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
        
        const hasLyrics = segments.some(s => s.lyrics && s.lyrics.trim());
        
        if (hasLyrics) {
            result.push({ type: 'chord-lyric', segments, rawLineIdx });
        } else {
            const chords = segments
                .filter(s => s.chord)
                .map(s => s.chord);
            if (chords.length > 0) {
                result.push({ type: 'chord-only', chords, rawLineIdx });
            }
        }
    }

    return result;
}

/**
 * 1行のChordProテキストをセグメント配列にパース
 * "[C]君を忘れ[G]ない" → [{chord:'C', lyrics:'君を忘れ'}, {chord:'G', lyrics:'ない'}]
 * 
 * 修正: regex.exec の二重呼び出し + rewind パターンを廃止。
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
}) {
    const containerRef = useRef(null);
    const activeLineRef = useRef(null);
    const [editMode, setEditMode] = useState(false);
    const [editText, setEditText] = useState('');
    const [fontSize, setFontSize] = useState(16);
    const [splitMode, setSplitMode] = useState(false);
    // scrollMode: 'off' | 'follow' | 'constant'
    const [scrollMode, setScrollMode] = useState('follow');
    // 速度5段階: 0.5, 0.8, 1.0, 1.5, 2.0
    const SPEED_LEVELS = [0.5, 0.8, 1.0, 1.5, 2.0];
    const SPEED_LABELS = ['遅い', 'やや遅', '普通', 'やや速', '速い'];
    const [speedIdx, setSpeedIdx] = useState(() => {
        const saved = parseInt(localStorage.getItem('nc-cp-speed-idx') || '2');
        return Math.max(0, Math.min(SPEED_LEVELS.length - 1, saved));
    });
    const scrollSpeed = SPEED_LEVELS[speedIdx];
    const changeSpeed = d => setSpeedIdx(prev => {
        const v = Math.max(0, Math.min(SPEED_LEVELS.length - 1, prev + d));
        localStorage.setItem('nc-cp-speed-idx', v); return v;
    });
    // ローカルテキスト：propから初期化、局所編集を保持
    const [localText, setLocalText] = useState(chordproText || '');

    // prop変更時（新セッション）にリセット
    useEffect(() => {
        setLocalText(chordproText || '');
        setSplitMode(false);
    }, [chordproText]);

    // パース（localTextを使用）
    const parsed = useMemo(() => parseChordPro(localText), [localText]);

    // アクティブ行の検出
    const activeIdx = useMemo(() => {
        if (!lineTimings || !lineTimings.length) return -1;
        for (let i = lineTimings.length - 1; i >= 0; i--) {
            if (currentTime >= lineTimings[i].startTime) return i;
        }
        return -1;
    }, [currentTime, lineTimings]);

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

    // ① コード追従モード: アクティブ行へスクロール
    useEffect(() => {
        if (scrollMode !== 'follow') return;
        if (userScrollingRef.current) return; // ホイール操作中はスキップ
        if (activeLineRef.current) {
            activeLineRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, [activeIdx, scrollMode]);

    // ② 定速スクロールモード
    useEffect(() => {
        if (scrollMode !== 'constant' || !containerRef.current) return;
        let id, last = performance.now();
        const step = now => {
            const dt = now - last; last = now;
            if (!userScrollingRef.current && containerRef.current) {
                containerRef.current.scrollTop += scrollSpeed * dt * 0.03;
            }
            id = requestAnimationFrame(step);
        };
        id = requestAnimationFrame(step);
        return () => cancelAnimationFrame(id);
    }, [scrollMode, scrollSpeed]);

    // 編集モード切替（局所テキストを保存）
    const toggleEdit = useCallback(() => {
        if (editMode) {
            // 編集終了時に局所テキストを更新
            setLocalText(editText);
            if (onChordproChange) onChordproChange(editText);
            setEditMode(false);
        } else {
            setEditText(localText || '');
            setEditMode(true);
            setSplitMode(false);
        }
    }, [editMode, localText, editText, onChordproChange]);

    // 行分割ハンドラー
    // afterSegIdx: このセグメントの後ろで改行する
    const handleSplitLine = useCallback((parsedLine, afterSegIdx) => {
        const rawLines = localText.split('\n');
        const rawLineIdx = parsedLine.rawLineIdx;
        if (rawLineIdx === undefined || rawLineIdx >= rawLines.length) return;

        const segs = parsedLine.segments;
        // 分割点前後のChordProテキストを再構築
        const part1 = segs.slice(0, afterSegIdx + 1)
            .map(s => (s.chord ? `[${s.chord}]` : '') + s.lyrics)
            .join('').trimEnd();
        const part2 = segs.slice(afterSegIdx + 1)
            .map(s => (s.chord ? `[${s.chord}]` : '') + s.lyrics)
            .join('');

        if (!part2.trim()) return; // 後半が空なら分割不要

        rawLines[rawLineIdx] = part1 + '\n' + part2;
        const newText = rawLines.join('\n');
        setLocalText(newText);
        if (onChordproChange) onChordproChange(newText);
    }, [localText, onChordproChange]);

    // レンダリング用の行インデックスカウンター（タイミング行のみカウント）
    let timingIdx = 0;

    return (
        <div className="chordpro-view" ref={containerRef}>
            {/* ヘッダーバー */}
            <div className="cp-top-bar">
                <div className="cp-title-area">
                    {title && <span className="cp-title">{title}</span>}
                    {artist && <span className="cp-artist">{artist}</span>}
                </div>
                <div className="cp-controls">
                    {/* スクロール制御 */}
                    <div className="cp-scroll-controls">
                        <button
                            className={`cp-scroll-btn ${scrollMode === 'follow' ? 'cl-btn-active' : ''}`}
                            onClick={() => setScrollMode(m => m === 'follow' ? 'off' : 'follow')}
                            title="再生中のコードに合わせて自動スクロール"
                        >追従</button>
                        <button
                            className={`cp-scroll-btn ${scrollMode === 'constant' ? 'cl-btn-active' : ''}`}
                            onClick={() => setScrollMode(m => m === 'constant' ? 'off' : 'constant')}
                            title="一定速度で自動スクロール"
                        >自動</button>
                        {scrollMode === 'constant' && (<>
                            <button className="cp-zoom-btn" onClick={() => changeSpeed(-1)} disabled={speedIdx <= 0}>−</button>
                            <span className="cp-font-size">{SPEED_LABELS[speedIdx]}</span>
                            <button className="cp-zoom-btn" onClick={() => changeSpeed(1)} disabled={speedIdx >= SPEED_LEVELS.length - 1}>＋</button>
                        </>)}
                    </div>
                    <button 
                        className="cp-zoom-btn" 
                        onClick={() => setFontSize(s => Math.max(12, s - 2))}
                        title="文字を小さく"
                    >A-</button>
                    <span className="cp-font-size">{fontSize}px</span>
                    <button 
                        className="cp-zoom-btn" 
                        onClick={() => setFontSize(s => Math.min(28, s + 2))}
                        title="文字を大きく"
                    >A+</button>
                    <button
                        className={`cp-edit-btn ${splitMode ? 'active' : ''}`}
                        onClick={() => { setSplitMode(p => !p); setEditMode(false); }}
                        title="行分割モード"
                        disabled={editMode}
                    >
                        {splitMode ? '✂ 分割中' : '✂ 行分割'}
                    </button>
                    <button
                        className={`cp-edit-btn ${editMode ? 'active' : ''}`}
                        onClick={toggleEdit}
                        title="ChordPro編集"
                    >
                        {editMode ? '✓ 完了' : '✎ 編集'}
                    </button>
                </div>
            </div>

            {/* 編集モード */}
            {editMode ? (
                <div className="cp-editor-container">
                    <textarea
                        className="cp-editor"
                        value={editText}
                        onChange={e => setEditText(e.target.value)}
                        style={{ fontSize: `${fontSize}px` }}
                        spellCheck={false}
                    />
                    <div className="cp-editor-hint">
                        ✂ 「{`\\n`}」またはEnterで改行・」完了」で保存
                    </div>
                </div>
            ) : (
                /* 表示モード */
                <div className="cp-content" style={{ fontSize: `${fontSize}px` }}>
                    {parsed.map((line, i) => {
                        const isTimingLine = line.type === 'chord-lyric' || line.type === 'chord-only';
                        const currentTimingIdx = isTimingLine ? timingIdx++ : -1;
                        const isActive = currentTimingIdx >= 0 && currentTimingIdx === activeIdx;

                        switch (line.type) {
                            case 'title':
                                return null;
                            case 'subtitle':
                                return null;
                            case 'section':
                                return (
                                    <div key={i} className="cp-section">
                                        <span className="cp-section-label">
                                            🎸 {line.text}
                                        </span>
                                    </div>
                                );
                            case 'chord-only':
                                return (
                                    <div 
                                        key={i} 
                                        ref={isActive ? activeLineRef : null}
                                        className={`cp-line cp-chord-only ${isActive ? 'cp-line-active' : ''}`}
                                        onClick={() => onSeek && lineTimings?.[currentTimingIdx] && 
                                            onSeek(lineTimings[currentTimingIdx].startTime)}
                                    >
                                        <div className="cp-chord-row">
                                            {line.chords.map((c, ci) => (
                                                <span key={ci} className="cp-chord" translate="no">
                                                    {transposeChord(c, transpose)}
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                );
                            case 'chord-lyric':
                                return (
                                    <div 
                                        key={i} 
                                        ref={isActive ? activeLineRef : null}
                                        className={`cp-line cp-has-lyrics ${isActive ? 'cp-line-active' : ''} ${splitMode ? 'cp-split-mode' : ''}`}
                                        onClick={() => !splitMode && onSeek && lineTimings?.[currentTimingIdx] && 
                                            onSeek(lineTimings[currentTimingIdx].startTime)}
                                    >
                                        {line.segments.map((seg, si) => (
                                            <React.Fragment key={si}>
                                                <span className="cp-segment">
                                                    {seg.chord && (
                                                        <span className="cp-chord" translate="no">
                                                            {transposeChord(seg.chord, transpose)}
                                                        </span>
                                                    )}
                                                    <span className="cp-lyrics">{seg.lyrics}</span>
                                                </span>
                                                {/* 分割ボタン: 最後のセグメント以外、分割モード時のみ */}
                                                {splitMode && si < line.segments.length - 1 && (
                                                    <button
                                                        className="cp-split-btn"
                                                        onClick={e => {
                                                            e.stopPropagation();
                                                            handleSplitLine(line, si);
                                                        }}
                                                        title={`ここで改行（${seg.chord || ''}→${line.segments[si+1]?.chord || ''}）`}
                                                    >
                                                        ✂
                                                    </button>
                                                )}
                                            </React.Fragment>
                                        ))}
                                    </div>
                                );
                            case 'empty':
                                return <div key={i} className="cp-empty-line" />;
                            default:
                                return null;
                        }
                    })}
                    {splitMode && (
                        <div className="cp-split-hint">
                            ✂ 分割モード: コード間の ✂ をクリックして改行を挿入
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default ChordProView;
