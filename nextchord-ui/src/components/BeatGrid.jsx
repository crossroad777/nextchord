import React, { useMemo, useEffect, useRef, useState } from "react";
import { transposeChord } from "../utils/musicUtils";

export const BeatGrid = ({ data, currentTime, onSeek, transpose = 0, onChordEdit }) => {
    const activeRef = useRef(null);
    const [editingIndex, setEditingIndex] = useState(null);
    const [editValue, setEditValue] = useState("");

    // Use structured_data directly. it should be sorted by time.
    // Group by bar index.
    const bars = useMemo(() => {
        if (!data) return [];
        const grouped = {};
        data.forEach((item, idx) => {
            if (!grouped[item.bar]) grouped[item.bar] = [];
            grouped[item.bar].push({ ...item, _index: idx });
        });
        // Convert to sorted array
        return Object.keys(grouped).sort((a, b) => Number(a) - Number(b)).map(k => grouped[k]);
    }, [data]);

    // 統計ログ
    useEffect(() => {
        if (data && data.length > 0) {
            const first = data[0];
            const last = data[data.length - 1];
            console.log(`[BeatGrid] 📊 Data Statistics:`, {
                totalBeats: data.length,
                totalBars: bars.length,
                startTime: first.time,
                endTime: last.time + last.duration
            });
        }
    }, [data, bars.length]);

    // 自動スクロール: アクティブなビートが見えるようにスクロール
    useEffect(() => {
        if (activeRef.current) {
            activeRef.current.scrollIntoView({
                behavior: 'smooth',
                block: 'center',
                inline: 'nearest'
            });
        }
    }, [currentTime]);

    // コード編集開始
    const handleDoubleClick = (beat) => {
        setEditingIndex(beat._index);
        setEditValue(beat.chord || "");
    };

    // 編集確定
    const handleEditConfirm = () => {
        if (editingIndex !== null && onChordEdit) {
            onChordEdit(editingIndex, editValue);
        }
        setEditingIndex(null);
        setEditValue("");
    };

    // 編集キャンセル
    const handleEditCancel = () => {
        setEditingIndex(null);
        setEditValue("");
    };

    // キー入力ハンドラ
    const handleKeyDown = (e) => {
        if (e.key === "Enter") {
            handleEditConfirm();
        } else if (e.key === "Escape") {
            handleEditCancel();
        }
    };

    return (
        <div className="flex flex-col gap-1 w-full max-w-6xl mx-auto pb-24 px-4">
            {bars.map((beats, rowIdx) => {
                const barNum = beats[0]?.bar;

                const firstBeat = beats[0];
                const sectionLabel = firstBeat?.section;

                const getSectionColor = (label) => {
                    const defaultStyle = { bg: "bg-slate-50", border: "border-slate-100", text: "text-slate-400" };
                    if (!label) return defaultStyle;
                    const l = label.toLowerCase();
                    // 高級感のある音楽的なパレット
                    if (l.includes("chorus") || l.includes("サビ")) return { bg: "bg-rose-50", border: "border-rose-100", text: "text-rose-500" };
                    if (l.includes("verse") || l.includes("メロ")) return { bg: "bg-indigo-50", border: "border-indigo-100", text: "text-indigo-500" };
                    if (l.includes("intro")) return { bg: "bg-amber-50", border: "border-amber-100", text: "text-amber-600" };
                    if (l.includes("bridge") || l.includes("間奏")) return { bg: "bg-teal-50", border: "border-teal-100", text: "text-teal-600" };
                    if (l.includes("outro")) return { bg: "bg-slate-100", border: "border-slate-200", text: "text-slate-500" };
                    return defaultStyle;
                };

                const style = getSectionColor(sectionLabel);
                const isNewSection = rowIdx === 0 || (bars[rowIdx - 1]?.[0]?.section !== sectionLabel);

                return (
                    <div key={rowIdx} className="flex relative items-stretch mb-2">

                        {/* Left Label Gutter (Section Indicator) */}
                        <div className={`w-32 flex-shrink-0 flex flex-col justify-center items-end pr-6 relative border-r-2 ${style.border} transition-colors`}>
                            {isNewSection && sectionLabel && (
                                <div className={`px-2 py-0.5 text-[9px] font-black uppercase tracking-widest rounded-sm mb-1 ${style.bg} ${style.border} ${style.text}`}>
                                    {sectionLabel}
                                </div>
                            )}
                            <span className="text-[10px] font-black text-slate-300 italic">BAR {barNum}</span>
                        </div>

                        {/* Bar Container */}
                        <div className="flex-1 flex gap-2 min-h-[140px] pl-2">
                            {beats.map((beat, i) => {
                                const isActive = currentTime >= beat.time && currentTime < (beat.time + beat.duration);
                                const displayChord = transposeChord(beat.chord, transpose);
                                const isRest = !displayChord || displayChord === "N" || displayChord === "N.C.";
                                const isEditing = editingIndex === beat._index;
                                const isEdited = beat._edited;

                                // 同じコードが続く場合は表示を抑制（ただし1拍目は表示）
                                const prevBeat = i > 0 ? beats[i - 1] : null;
                                const isRepeated = prevBeat && prevBeat.chord === beat.chord;
                                const shouldShowChord = !isRepeated || i === 0 || isEditing || isEdited;

                                return (
                                    <div
                                        key={i}
                                        ref={isActive ? activeRef : null}
                                        onClick={() => onSeek(beat.time)}
                                        onDoubleClick={(e) => { e.stopPropagation(); handleDoubleClick(beat); }}
                                        className={`
                                            flex-1 rounded-2xl border-2 cursor-pointer transition-all relative overflow-hidden group
                                            flex flex-col p-5 shadow-sm
                                            ${isActive
                                                ? "bg-gradient-to-br from-[#0d9488] to-[#0f172a] border-[#0d9488] shadow-2xl scale-[1.02] z-10"
                                                : isEdited
                                                    ? "bg-amber-50 border-amber-200 hover:border-amber-300 hover:shadow-md"
                                                    : "bg-white border-slate-100 hover:border-indigo-200 hover:shadow-lg hover:shadow-indigo-500/5"
                                            }
                                        `}
                                    >
                                        {/* 編集モード */}
                                        {isEditing ? (
                                            <input
                                                type="text"
                                                value={editValue}
                                                onChange={(e) => setEditValue(e.target.value)}
                                                onKeyDown={handleKeyDown}
                                                onBlur={handleEditConfirm}
                                                autoFocus
                                                className="text-2xl font-black text-center bg-white border-2 border-indigo-500 rounded-xl px-2 py-1 outline-none shadow-xl"
                                                onClick={(e) => e.stopPropagation()}
                                            />
                                        ) : (
                                            <>
                                                {/* コード名 - 大きく目立つ */}
                                                <div className={`text-4xl font-black tracking-tighter leading-none ${isActive ? "text-white" : isEdited ? "text-amber-700" : "text-slate-900"}`}>
                                                    {shouldShowChord && !isRest ? displayChord : ""}
                                                    {!shouldShowChord && !isRest && (
                                                        <span className={`text-xl opacity-20 ${isActive ? "text-white" : "text-slate-200"}`}>・</span>
                                                    )}
                                                </div>

                                                {/* 編集済みマーク */}
                                                {isEdited && !isActive && (
                                                    <div className="absolute top-2 right-2 text-[8px] font-black text-amber-500 bg-amber-100/50 px-2 py-0.5 rounded-full uppercase tracking-widest">
                                                        Edited
                                                    </div>
                                                )}
                                            </>
                                        )}

                                        {/* 歌詞 - コードの直下に大きく表示 */}
                                        {beat.lyric && !isEditing && (
                                            <div className={`text-lg font-bold mt-3 leading-tight tracking-tight ${isActive ? "text-white/90" : "text-indigo-500/80"}`}>
                                                {beat.lyric}
                                            </div>
                                        )}

                                        {/* 休符記号 - コードも歌詞もない場合のみ表示 */}
                                        {isRest && !beat.lyric && !isEditing && (
                                            <div className={`flex items-center justify-center flex-1 ${isActive ? "text-white/30" : "text-slate-100"}`}>
                                                <span className="text-4xl font-light opacity-50">—</span>
                                            </div>
                                        )}

                                        {/* Beat Indicator */}
                                        {isActive && (
                                            <div className="absolute bottom-3 right-3">
                                                <div className="w-2.5 h-2.5 rounded-full bg-white shadow-lg animate-pulse" />
                                            </div>
                                        )}

                                        {/* ダブルクリックヒント */}
                                        {!isEditing && !isActive && (
                                            <div className="absolute bottom-2 left-3 text-[7px] font-black text-slate-300 opacity-0 group-hover:opacity-100 transition-all uppercase tracking-widest">
                                                Double click to edit
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                );
            })}
        </div>
    );
};
