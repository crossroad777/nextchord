import React, { useMemo, useRef, useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import GuitarChord from './GuitarChord';
import { Maximize, Minimize } from 'lucide-react';
import { chordproToPlainText, plainTextToChordpro } from '../utils/plainTextConverter';

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
    tuning = 'standard',
}) {
    const containerRef = useRef(null);
    const activeLineRef = useRef(null);
    const [editMode, setEditMode] = useState(false);
    const [editText, setEditText] = useState('');
    const [fontSize, setFontSize] = useState(16);
    const [splitMode, setSplitMode] = useState(false);
    // scrollMode: 'off' | 'follow' | 'constant'
    const [scrollMode, setScrollMode] = useState('follow');
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
    }, [scrollMode, scrollSpeed]);

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
                        // 行分割モード中は無視
                        if (splitMode) return;
                        // テキスト選択時は無視
                        if (window.getSelection().toString().length > 0) return;
                        
                        // 自動スクロール（一定速度）のON/OFFを切り替え
                        setScrollMode(m => m === 'constant' ? 'off' : 'constant');
                    }}
                >
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
                                return null;
                            case 'chord-only':
                                return (
                                    <div 
                                        key={i} 
                                        ref={isActive ? activeLineRef : null}
                                        className={`cp-line cp-chord-only ${isActive ? 'cp-line-active' : ''}`}
                                        onClick={() => onSeek && lineTimings?.[currentTimingIdx] && 
                                            onSeek(lineTimings[currentTimingIdx].startTime)}
                                    >
                                        <div className="cp-chord-row" style={{ display: 'flex', width: '100%', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                                            {(line.measures || []).map((measureChords, mi) => (
                                                <div key={mi} className="cp-measure">
                                                    {measureChords.map((c, ci) => {
                                                        if (c === '|') return null;
                                                        const transposed = transposeChord(c, transpose);
                                                        return (
                                                            <span key={ci} className="cp-chord" translate="no">
                                                                <span className="cp-chord-name">{transposed}</span>
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
                            case 'chord-lyric':
                                return (
                                    <div 
                                        key={i} 
                                        ref={isActive ? activeLineRef : null}
                                        className={`cp-line cp-has-lyrics ${isActive ? 'cp-line-active' : ''} ${splitMode ? 'cp-split-mode' : ''}`}
                                        onClick={() => !splitMode && onSeek && lineTimings?.[currentTimingIdx] && 
                                            onSeek(lineTimings[currentTimingIdx].startTime)}
                                    >
                                        <div style={{ display: 'flex', width: '100%', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                                            {(line.measures || []).map((measure, mi) => (
                                                <div key={mi} className="cp-measure">
                                                    {measure.map((seg, si) => {
                                                        const isBarLine = seg.chord === '|';
                                                        if (isBarLine && !seg.lyrics) return null;
                                                        
                                                        return (
                                                            <React.Fragment key={si}>
                                                                <span className="cp-segment">
                                                                    {seg.chord && !isBarLine ? (
                                                                        <span className="cp-chord" translate="no">
                                                                            <span className="cp-chord-name">{transposeChord(seg.chord, transpose)}</span>
                                                                            <div className={`cp-diagram-wrapper ${showDiagrams ? 'inline-mode' : 'hover-mode'}`}>
                                                                                <GuitarChord chordName={transposeChord(seg.chord, transpose)} tuning={tuning} />
                                                                            </div>
                                                                        </span>
                                                                    ) : (
                                                                        <span className="cp-chord cp-chord-placeholder" style={{ visibility: 'hidden' }}>{"\u00A0"}</span>
                                                                    )}
                                                                    <span className="cp-lyrics">{seg.lyrics}</span>
                                                                </span>
                                                                {/* 分割ボタン */}
                                                                {splitMode && !isBarLine && (
                                                                    <button
                                                                        className="cp-split-btn"
                                                                        onClick={e => {
                                                                            e.stopPropagation();
                                                                            // Note: Split line logic might need updates for measures
                                                                        }}
                                                                        title={`ここで改行`}
                                                                    >
                                                                        ✂
                                                                    </button>
                                                                )}
                                                            </React.Fragment>
                                                        );
                                                    })}
                                                </div>
                                            ))}
                                        </div>
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
