import React, { useEffect, useRef, useState } from 'react';
import * as alphaTab from '@coderline/alphatab';

const API_BASE = (import.meta.env.VITE_API_URL !== undefined ? import.meta.env.VITE_API_URL : "http://localhost:8000").trim();

export const TabView = ({ sessionId, currentTime, isPlaying, capo = 0, transpose = 0 }) => {
    const containerRef = useRef(null);
    const wrapperRef = useRef(null);
    const apiRef = useRef(null);
    const cursorRef = useRef(null);
    const initializedSessionId = useRef(null);

    const [loading, setLoading] = useState(true);
    const [syncStatus, setSyncStatus] = useState('INIT');
    const [logs, setLogs] = useState([]);
    const [resetCounter, setResetCounter] = useState(0);

    const timeRef = useRef(0);
    const playingRef = useRef(false);
    const beatMapRef = useRef([]);
    const boundsReadyRef = useRef(false);
    const tabOffsetRef = useRef(0); // ms単位のタイミングオフセット
    const firstBeatRef = useRef(0); // 秒単位: オーディオ中の最初のビート位置
    const beatTimesRef = useRef(null); // 秒単位: 全ビートタイムスタンプ配列

    const [tabOffset, setTabOffset] = useState(0); // UI用（ms）
    const [sepStatus, setSepStatus] = useState({ processing: false, hasClean: false, deepProcessing: false, error: null });
    const [autoScroll, setAutoScroll] = useState(false); // ダブルクリックでトグル

    const addLog = (msg) => {
        const time = new Date().toLocaleTimeString();
        setLogs(prev => [`[${time}] ${msg}`, ...prev].slice(0, 40));
        console.log(`[TabView] ${msg}`);
    };

    // ============================================================
    // 音源分離 & 再解析 ハンドラ
    // ============================================================
    const handleSeparate = async () => {
        if (sepStatus.processing || sepStatus.hasClean) return;
        addLog('✨ 音源分離(Demucs)を開始...');
        setSepStatus(prev => ({ ...prev, processing: true, error: null }));
        try {
            const res = await fetch(`${API_BASE}/separate/${sessionId}`, { method: 'POST' });
            if (!res.ok) throw new Error('分離の開始に失敗しました');
            addLog('⌛ AIが音源を分離中... しばらくお待ちください');
        } catch (e) {
            setSepStatus(prev => ({ ...prev, processing: false, error: e.message }));
        }
    };

    const handleDeepAnalysis = async () => {
        if (loading || !sepStatus.hasClean) return;
        addLog('🎸 Deep Analysis (Guitar Isolation) を開始...');
        setSepStatus(prev => ({ ...prev, deepProcessing: true }));
        try {
            const res = await fetch(`${API_BASE}/reanalyze/${sessionId}`, { method: 'POST' });
            if (!res.ok) throw new Error('再解析の開始に失敗しました');
            addLog('⌛ ギター音のみを抽出して再転記中...');
            // status監視に切り替わる
            setResetCounter(c => c + 1); // 解析後にリロードさせるためにトリガー
        } catch (e) {
            setSepStatus(prev => ({ ...prev, deepProcessing: false, error: e.message }));
        }
    };

    // ★ TAB表示後にAI分離をバックグラウンドで遅延実行（初回表示を優先）
    const autoSeparateStarted = useRef(false);
    useEffect(() => {
        if (!sessionId) return;
        if (autoSeparateStarted.current) return;
        autoSeparateStarted.current = true;
        // TABが先に描画されるよう10秒後に分離を開始
        const timer = setTimeout(() => {
            addLog('🤖 バックグラウンドでギター分離を開始...');
            handleSeparate();
        }, 10000);
        return () => clearTimeout(timer);
    }, [sessionId]);

    // 分離ステータスの監視
    useEffect(() => {
        if (!sessionId || sepStatus.hasClean) return;
        let timer;
        let cancelled = false;
        const check = async () => {
            if (cancelled) return;
            try {
                const res = await fetch(`${API_BASE}/status/separation/${sessionId}`);
                const data = await res.json();
                if (data.has_clean_audio) {
                    setSepStatus(prev => ({ ...prev, processing: false, hasClean: true }));
                    addLog('✅ ギター音源の分離完了');
                    return;
                } else if (data.is_separating) {
                    setSepStatus(prev => ({ ...prev, processing: true }));
                } else if (data.error) {
                    setSepStatus(prev => ({ ...prev, processing: false, error: data.error }));
                    return;
                }
            } catch (e) { /* ignore */ }
            if (!cancelled) timer = setTimeout(check, 3000);
        };
        check();
        return () => { cancelled = true; clearTimeout(timer); };
    }, [sessionId, sepStatus.hasClean]);

    // ★ 分離完了後、5秒待ってからDeep Analysisを自動実行
    const autoDeepStarted = useRef(false);
    useEffect(() => {
        if (!sepStatus.hasClean || autoDeepStarted.current) return;
        autoDeepStarted.current = true;
        const timer = setTimeout(() => {
            addLog('🎸 バックグラウンドでDeep Analysis開始...');
            handleDeepAnalysis();
        }, 5000);
        return () => clearTimeout(timer);
    }, [sepStatus.hasClean]);


    useEffect(() => {
        timeRef.current = currentTime;
        playingRef.current = isPlaying;
    }, [currentTime, isPlaying]);

    useEffect(() => {
        tabOffsetRef.current = tabOffset;
    }, [tabOffset]);

    // ============================================================
    // AlphaTabオブジェクトからプロパティを安全に取得する
    // ============================================================
    const getAtProp = (obj, names) => {
        if (!obj || typeof obj !== 'object') return null;
        for (const n of names) {
            let val = obj[n];
            if (val === undefined || val === null) val = obj[`_${n}`];
            if (val !== undefined && val !== null) {
                try {
                    return (typeof val === 'function') ? val.call(obj) : val;
                } catch (e) { return val; }
            }
        }
        // 大文字小文字を無視して全プロパティをチェック
        try {
            const keys = Object.keys(obj);
            const lowerNames = names.map(n => n.toLowerCase());
            const key = keys.find(k => lowerNames.includes(k.toLowerCase()));
            if (key) {
                const val = obj[key];
                return (typeof val === 'function') ? val.call(obj) : val;
            }
        } catch (e) { /* ignore */ }
        return null;
    };

    // ============================================================
    // ビートマップ構築
    // ============================================================
    const buildBeatMap = (api) => {
        if (!api.score || !api.renderer?.boundsLookup) {
            addLog('⚠️ API準備中のためスキップ');
            return false;
        }

        const lookup = api.renderer.boundsLookup;
        const beatLookup = lookup._beatLookup;
        const beatLookupSize = beatLookup instanceof Map ? beatLookup.size :
            (beatLookup && typeof beatLookup === 'object' ? Object.keys(beatLookup).length : 0);

        if (!beatLookup || beatLookupSize === 0) {
            addLog('❌ _beatLookup が空');
            return false;
        }

        const TICKS_PER_BEAT = 960;
        const baseTempo = api.score.tempo || 120;
        const tempoSegments = [];

        // テンポマップ構築 — tick位置を数学的に計算
        // AlphaTabの内部プロパティに依存せず、拍子情報からtickを計算
        const masterBars = api.score.masterBars || api.score._masterBars;
        if (masterBars) {
            let accTick = 0, accMs = 0, prevTempo = baseTempo;
            let barIndex = 0;

            const eachMB = (list, cb) => {
                if (Array.isArray(list)) list.forEach(cb);
                else if (list.items) list.items.forEach(cb);
                else if (list.forEach) list.forEach(cb);
            };

            eachMB(masterBars, mb => {
                // テンポ変化を検出
                const tempo = (mb.tempoAutomation?.value) || prevTempo;

                // 拍子を取得（デフォルト4/4）
                let beatsPerBar = 4;
                const ts = mb.timeSignatureNumerator || getAtProp(mb, ['timeSignatureNumerator']);
                if (ts && ts > 0) beatsPerBar = ts;

                // この小節のtick数
                const barTicks = beatsPerBar * TICKS_PER_BEAT;

                // テンポセグメントを追加
                tempoSegments.push({
                    startTick: accTick,
                    startMs: accMs,
                    msPerTick: (60000 / tempo) / TICKS_PER_BEAT
                });

                // 累積を更新
                accMs += barTicks * ((60000 / tempo) / TICKS_PER_BEAT);
                accTick += barTicks;
                prevTempo = tempo;
                barIndex++;
            });

            addLog(`🎵 テンポマップ: ${tempoSegments.length} bars, totalTicks=${accTick}, totalMs=${(accMs / 1000).toFixed(1)}s`);
        } else {
            tempoSegments.push({ startTick: 0, startMs: 0, msPerTick: (60000 / baseTempo) / TICKS_PER_BEAT });
        }

        // tick → ms変換: beat_timesがあれば実際のオーディオ時間にマッピング
        const bt = beatTimesRef.current;
        const tickToMs = (tick) => {
            if (tick == null || isNaN(tick)) return NaN;

            // beat_timesが利用可能なら、ビートインデックスベースの正確なマッピング
            if (bt && bt.length > 1) {
                const beatIdx = tick / TICKS_PER_BEAT; // 浮動小数点のビートインデックス
                const lo = Math.floor(beatIdx);
                const frac = beatIdx - lo;

                if (lo < 0) return bt[0] * 1000;
                if (lo >= bt.length - 1) {
                    // 最後のビート以降 → 最後の間隔で外挿
                    const lastInterval = (bt[bt.length - 1] - bt[bt.length - 2]);
                    return (bt[bt.length - 1] + (lo - bt.length + 1 + frac) * lastInterval) * 1000;
                }
                // 線形補間
                return (bt[lo] + frac * (bt[lo + 1] - bt[lo])) * 1000;
            }

            // フォールバック: テンポベースの変換
            let lo2 = 0, hi2 = tempoSegments.length - 1;
            while (lo2 < hi2) {
                const mid = (lo2 + hi2 + 1) >> 1;
                tempoSegments[mid].startTick <= tick ? (lo2 = mid) : (hi2 = mid - 1);
            }
            const s = tempoSegments[lo2];
            return s.startMs + (tick - s.startTick) * s.msPerTick;
        };

        const idToInfo = new Map();
        const indexToInfo = new Map();
        const allBeatsArray = []; // 出現順での保持

        const each = (list, cb) => {
            if (!list) return 0;
            let items = list;
            if (list.items) items = list.items;
            else if (typeof list.toArray === 'function') items = list.toArray();
            if (Array.isArray(items)) { items.forEach(cb); return items.length; }
            if (typeof list.forEach === 'function') { let c = 0; list.forEach(v => { cb(v); c++; }); return c; }
            return 0;
        };

        const score = api.score;
        const tracksList = (score.tracks || score._tracks || []);

        let dumpFirstBeat = true;
        let beatTotal = 0;

        // ★ 全トラックを走査（_beatLookupのインデックスと一致させるため）
        // 各ビートにisTabフラグを付与し、後でTABのみフィルタ
        const tracksArr = [];
        each(tracksList, t => tracksArr.push(t));
        const lastTrackIdx = tracksArr.length - 1;

        tracksArr.forEach((track, trackIdx) => {
            const isTab = trackIdx === lastTrackIdx;
            const staves = (track.staves || track._staves || []);

            each(staves, staff => {
                let staffAccTick = 0; // ★ 各スタッフ開始時にリセット（同じトラック内の複数スタッフは同じ音楽）
                const bars = (staff.bars || staff._bars || []);
                each(bars, bar => {
                    const voices = (bar.voices || bar._voices || []);
                    each(voices, voice => {
                        const beats = (voice.beats || voice._beats || []);
                        each(beats, beat => {
                            const dur = getAtProp(beat, ['playbackDuration', 'displayDuration', 'duration']) ?? TICKS_PER_BEAT;
                            const idx = getAtProp(beat, ['index']);
                            const id = getAtProp(beat, ['id']);

                            // tick は累積計算で求める（playbackStartは信頼できない）
                            const tick = staffAccTick;

                            if (dumpFirstBeat) {
                                console.log('[TabView] 🔬 1st Beat:', { tick, dur, idx, id, isTab, trackIdx });
                                dumpFirstBeat = false;
                            }

                            const info = { tick, dur, beat, idx, id, isTab };
                            allBeatsArray.push(info);

                            if (idx !== null && idx !== undefined) indexToInfo.set(Number(idx), info);
                            if (id !== null && id !== undefined) idToInfo.set(String(id), info);

                            staffAccTick += dur;
                            beatTotal++;
                        });
                    });
                });
            });
        });
        addLog(`🔍 Traversal: Bt=${beatTotal}, idxMap=${indexToInfo.size}, idMap=${idToInfo.size}`);

        // ============================================================
        // _beatLookup を走査して BeatMap を構築
        // ============================================================
        const validBeats = [];
        let methodStats = { idx: 0, id: 0, seq: 0, prop: 0, ktick: 0 };

        const loopLookup = (lk, cb) => {
            if (lk instanceof Map) lk.forEach((v, k) => cb(v, k));
            else if (lk && typeof lk === 'object') Object.entries(lk).forEach(([k, v]) => cb(v, k));
        };

        loopLookup(beatLookup, (boundsArrayOrObj, key) => {
            const items = Array.isArray(boundsArrayOrObj) ? boundsArrayOrObj : [boundsArrayOrObj];
            const numKey = Number(key);

            for (const bb of items) {
                if (!bb) continue;


                let tick = null;
                let tickDuration = TICKS_PER_BEAT;
                let matchInfo = null;

                // --- 方法C優先: BeatBounds内部のbeatオブジェクトからtickを直接取得 ---
                // AlphaTabのBeatBoundsは beat.absoluteDisplayStart (or similar) を持つ
                const beatObj = getAtProp(bb, ['beat', 'Beat']);
                if (beatObj) {
                    const directTick = getAtProp(beatObj, [
                        'absoluteDisplayStart', 'absolutePlaybackStart',
                        'playbackStart', 'displayStart', 'start',
                        '_absoluteDisplayStart', '_playbackStart'
                    ]);
                    const directDur = getAtProp(beatObj, [
                        'playbackDuration', 'displayDuration', 'duration',
                        '_playbackDuration', '_duration'
                    ]);
                    if (directTick !== null && directTick !== undefined) {
                        tick = directTick;
                        tickDuration = directDur ?? TICKS_PER_BEAT;
                        // isTabを判定: beatのvoice.bar.staff.track が最後のトラックか
                        const voice = getAtProp(beatObj, ['voice', '_voice']);
                        const bar = voice ? getAtProp(voice, ['bar', '_bar']) : null;
                        const staff = bar ? getAtProp(bar, ['staff', '_staff']) : null;
                        const track = staff ? getAtProp(staff, ['track', '_track']) : null;
                        const trackIdx = track ? getAtProp(track, ['index', '_index']) : null;
                        matchInfo = { isTab: trackIdx !== null && trackIdx === lastTrackIdx, tick };
                        methodStats.prop++;
                    }
                }

                // --- 方法B: ID照合（フォールバック） ---
                if (tick === null) {
                    const info = idToInfo.get(String(key)) || idToInfo.get(numKey) ||
                        indexToInfo.get(numKey) || indexToInfo.get(String(key));
                    if (info && info.tick !== null) {
                        tick = info.tick;
                        tickDuration = info.dur;
                        matchInfo = info;
                        methodStats.idx++;
                    }
                }

                // --- 方法A: シーケンスベース（最終手段） ---
                if (tick === null && numKey >= 0 && numKey < allBeatsArray.length) {
                    const info = allBeatsArray[numKey];
                    if (info && info.tick !== null) {
                        tick = info.tick;
                        tickDuration = info.dur;
                        matchInfo = info;
                        methodStats.seq++;
                    }
                }

                // --- 方法D: Ticks直読み ---
                if (tick === null && !isNaN(numKey) && numKey > 500) {
                    tick = numKey;
                    methodStats.ktick++;
                }

                if (tick === null) continue;

                // 座標取得
                const vb = getAtProp(bb, ['visualBounds', 'bounds']) || bb;
                const x = getAtProp(vb, ['x']);
                const y = getAtProp(vb, ['y']);
                const w = getAtProp(vb, ['w']);
                const h = getAtProp(vb, ['h']);

                if (x === null || y === null) continue;

                const startMs = tickToMs(tick);
                const endMs = tickToMs(tick + Math.max(10, tickDuration));
                if (isNaN(startMs) || isNaN(endMs)) continue;

                validBeats.push({ startMs, endMs, vb: { x, y, w, h }, isTab: matchInfo?.isTab ?? false });
            }
        });

        addLog(`🗺️ 有効マッピング: ${validBeats.length}`);
        addLog(`📊 内訳: seq=${methodStats.seq}, idx=${methodStats.idx}, prop=${methodStats.prop}, ktick=${methodStats.ktick}`);

        // ★ TABビートのみフィルタ（isTab=trueのエントリだけ保持）
        let tabBeats = validBeats.filter(b => b.isTab);
        addLog(`🎸 TABフィルタ: ${validBeats.length} → ${tabBeats.length} beats (isTab=trueのみ)`);

        // フォールバック: isTabマッチがゼロなら同時刻グループからmax-Y選択
        if (tabBeats.length === 0 && validBeats.length > 0) {
            addLog(`⚠️ isTabフィルタでゼロ → max-Yフォールバック`);
            const timeGroups = new Map();
            for (const b of validBeats) {
                const key = Math.round(b.startMs * 2) / 2;
                const existing = timeGroups.get(key);
                if (!existing || b.vb.y > existing.vb.y) {
                    timeGroups.set(key, b);
                }
            }
            tabBeats = Array.from(timeGroups.values());
            addLog(`🎸 max-Yフォールバック: ${tabBeats.length} beats`);
        }

        // 重複除去 & ソート
        const deduped = tabBeats
            .filter((b, i, self) => i === self.findIndex(t =>
                Math.abs(t.startMs - b.startMs) < 1 && Math.abs(t.vb.x - b.vb.x) < 2 && Math.abs(t.vb.y - b.vb.y) < 2
            ))
            .sort((a, b) => a.startMs - b.startMs);

        if (deduped.length === 0) {
            addLog('❌ 有効なビートがゼロ');
            setSyncStatus('ERROR');
            return false;
        }

        // ★ 空小節対応: 最初のビートが0ms以降で始まる場合、
        // AlphaTabのstaveGroupsから最初の小節座標を取得し、time=0のダミービートを追加
        if (deduped[0].startMs > 500) {
            const staveGroups = lookup.staveGroups || [];
            if (staveGroups.length > 0) {
                const firstGroup = staveGroups[0];
                const firstBar = firstGroup.bars?.[0];
                if (firstBar) {
                    const barBounds = firstBar.bounds || firstBar;
                    const bx = getAtProp(barBounds, ['x']) ?? deduped[0].vb.x;
                    const by = getAtProp(barBounds, ['y']) ?? deduped[0].vb.y;
                    const bh = getAtProp(barBounds, ['h']) ?? deduped[0].vb.h;
                    // time=0 から最初の実ビートまでのダミービート
                    deduped.unshift({
                        startMs: 0,
                        endMs: deduped[0].startMs,
                        vb: { x: bx, y: by, w: 8, h: bh },
                        isTab: true
                    });
                    addLog(`📍 空小節ダミービート追加: x=${bx}, y=${by}, endMs=${deduped[1].startMs}`);
                }
            }
        }

        // バリデーション
        const totalDurationMs = deduped.at(-1).endMs - deduped[0].startMs;
        if (totalDurationMs < 2000 && beatTotal > 10) {
            addLog(`⚠️ 期間が異常に短い(${(totalDurationMs / 1000).toFixed(1)}s)`);
        }

        beatMapRef.current = deduped;
        addLog(`✅ BeatMap: ${deduped.length} beats, Dur: ${(totalDurationMs / 1000).toFixed(1)}s`);

        setSyncStatus('READY');
        return true;
    };




    // 二分探索
    const findBeat = (ms) => {
        const map = beatMapRef.current;
        if (!map || !map.length) return null;

        // 曲の開始前 → 最初のビートを返す
        if (ms < map[0].startMs) return map[0];
        // 曲の終了後 → 最後のビートを返す
        if (ms >= map.at(-1).endMs) return map.at(-1);

        let lo = 0, hi = map.length - 1;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            const b = map[mid];
            if (ms >= b.startMs && ms < b.endMs) return b;
            if (ms < b.startMs) hi = mid - 1;
            else lo = mid + 1;
        }
        // ギャップ内 → 最も近い前のビートを返す
        return lo > 0 ? map[lo - 1] : map[0];
    };

    // ============================================================
    // AlphaTab 初期化
    // ============================================================
    useEffect(() => {
        if (!wrapperRef.current || !sessionId || !containerRef.current) return;

        const key = `${sessionId}_${resetCounter}_${capo}_${transpose}`;
        if (initializedSessionId.current === key) return;
        initializedSessionId.current = key;

        let destroyed = false;
        boundsReadyRef.current = false;
        beatMapRef.current = [];

        const init = async () => {
            setLoading(true);
            setSyncStatus('INIT');
            addLog(`🚀 Boot: ${sessionId}`);

            try {
                // ステータスAPIから beat_times / first_beat_time を取得
                try {
                    const statusRes = await fetch(`${API_BASE}/status/${sessionId}`);
                    if (statusRes.ok) {
                        const statusData = await statusRes.json();
                        const fbt = statusData.first_beat_time ?? 0;
                        firstBeatRef.current = fbt;
                        const bt = statusData.beat_times;
                        if (Array.isArray(bt) && bt.length > 0) {
                            beatTimesRef.current = bt;
                            addLog(`🎯 Beat times: ${bt.length} beats, first=${fbt.toFixed(3)}s`);
                        } else {
                            addLog(`🎯 First beat offset: ${fbt.toFixed(3)}s (no beat array)`);
                        }
                    }
                } catch (e) {
                    addLog(`⚠️ beat_times取得失敗: ${e.message}`)
                }

                // MusicXMLの事前フェッチ
                const xmlUrl = `${API_BASE}/result/${sessionId}/musicxml`;
                addLog(`📥 MusicXML取得中: ${xmlUrl}`);
                let xmlData;
                try {
                    const preCheck = await fetch(xmlUrl);
                    if (!preCheck.ok) {
                        addLog(`❌ MusicXML取得失敗: HTTP ${preCheck.status}`);
                        setLoading(false);
                        setSyncStatus('ERROR');
                        return;
                    }
                    let xmlText = await preCheck.text();
                    addLog(`✅ MusicXML取得成功: ${xmlText.length} chars`);

                    // 転調・カポをMusicXMLのピッチに直接適用
                    const totalShift = transpose - capo; // 転調は上げ、カポは下げ
                    if (totalShift !== 0) {
                        const NOTES = ['C', 'C', 'D', 'D', 'E', 'F', 'F', 'G', 'G', 'A', 'A', 'B'];
                        const ALTERS = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0];
                        const NOTE_TO_MIDI = { 'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11 };

                        // <pitch>...</pitch> ブロックを正規表現で検出して書き換え
                        xmlText = xmlText.replace(
                            /<pitch>\s*<step>([A-G])<\/step>\s*(?:<alter>([-.\d]+)<\/alter>\s*)?<octave>(\d+)<\/octave>\s*<\/pitch>/g,
                            (match, step, alter, octave) => {
                                const a = alter ? parseInt(alter) : 0;
                                const midi = NOTE_TO_MIDI[step] + a + (parseInt(octave) + 1) * 12;
                                const newMidi = midi + totalShift;
                                const newPc = ((newMidi % 12) + 12) % 12;
                                const newOctave = Math.floor(newMidi / 12) - 1;
                                const newStep = NOTES[newPc];
                                const newAlter = ALTERS[newPc];
                                let result = `<pitch><step>${newStep}</step>`;
                                if (newAlter !== 0) result += `<alter>${newAlter}</alter>`;
                                result += `<octave>${newOctave}</octave></pitch>`;
                                return result;
                            }
                        );

                        // <harmony>内の<root-step>, <root-alter>も移調
                        xmlText = xmlText.replace(
                            /<root>\s*<root-step>([A-G])<\/root-step>\s*(?:<root-alter>([-.\d]+)<\/root-alter>\s*)?<\/root>/g,
                            (match, step, alter) => {
                                const a = alter ? parseInt(alter) : 0;
                                const pc = ((NOTE_TO_MIDI[step] + a + totalShift) % 12 + 12) % 12;
                                const newStep = NOTES[pc];
                                const newAlter = ALTERS[pc];
                                let result = `<root><root-step>${newStep}</root-step>`;
                                if (newAlter !== 0) result += `<root-alter>${newAlter}</root-alter>`;
                                result += `</root>`;
                                return result;
                            }
                        );

                        // 調号(<fifths>)も更新
                        xmlText = xmlText.replace(
                            /<fifths>(-?\d+)<\/fifths>/g,
                            (match, fifths) => {
                                // 五度圏でのシフト: 半音 → 五度圏位置のマッピング
                                const SEMI_TO_FIFTH = [0, -5, 2, -3, 4, -1, 6, 1, -4, 3, -2, 5];
                                const currentFifths = parseInt(fifths);
                                const shiftMod = ((totalShift % 12) + 12) % 12;
                                let newFifths = currentFifths + SEMI_TO_FIFTH[shiftMod];
                                // -7 ~ 7 の範囲に収める
                                while (newFifths > 7) newFifths -= 12;
                                while (newFifths < -7) newFifths += 12;
                                return `<fifths>${newFifths}</fifths>`;
                            }
                        );

                        // TABパートの<fret>値も書き換え（カポ・転調を反映）
                        xmlText = xmlText.replace(
                            /<fret>(\d+)<\/fret>/g,
                            (match, fret) => {
                                const newFret = Math.max(0, parseInt(fret) + totalShift);
                                return `<fret>${newFret}</fret>`;
                            }
                        );

                        addLog(`🎵 Score transposed by ${totalShift} semitones (transpose=${transpose}, capo=${capo})`);
                    }

                    // テキストをUint8Arrayに変換
                    const encoder = new TextEncoder();
                    xmlData = encoder.encode(xmlText);
                } catch (fetchErr) {
                    addLog(`❌ MusicXMLフェッチエラー: ${fetchErr.message}`);
                    setLoading(false);
                    setSyncStatus('ERROR');
                    return;
                }

                if (apiRef.current) { apiRef.current.destroy(); apiRef.current = null; }


                // 明示的な幅計算（auto-sizing無限待機を回避）
                const containerWidth = containerRef.current?.clientWidth || wrapperRef.current?.clientWidth || 800;
                addLog(`🔧 AlphaTab初期化中... (幅: ${containerWidth}px)`);
                const api = new alphaTab.AlphaTabApi(wrapperRef.current, {
                    core: { fontDirectory: '/font/', useWorkers: false },
                    display: {
                        layoutMode: 'page',
                        staveProfile: 'Default',
                        width: containerWidth - 80,
                        padding: [40, 40, 20, 40]
                    },
                    notation: {
                        notationMode: 0,  // default mode（歌詞を表示）
                        elements: {
                            scoreTitle: false,
                            scoreSubTitle: false,
                            scoreArtist: false,
                            scoreAlbum: false,
                            scoreWords: false,
                            scoreMusic: false,
                            scoreCopyright: false,
                            guitarTuning: false,
                            trackNames: false,
                        }
                    },
                    player: {
                        enablePlayer: true,
                        enableFretboard: true,
                        enableCursor: false,
                        soundFont: `${window.location.origin}/soundfont/sonivox.sf2`,
                        scrollElement: containerRef.current,
                        scrollMode: 0, // Off — スクロールはカスタム制御
                    },
                });
                apiRef.current = api;
                window.atApi = api;

                // ★ イベントハンドラを先に登録（api.load()が同期的にイベント発火する場合に対応）
                api.fretboard = document.getElementById('alphaTabFretboard');

                api.scoreLoaded.on((score) => {
                    if (apiRef.current !== api) return;
                    const mCount = score.masterBars?.length || 0;
                    const tracks = score.tracks?.items || score.tracks || [];
                    addLog(`📄 ${tracks.length} tracks, ${mCount} bars, ${score.tempo} BPM`);

                    // 全トラックを描画（P1五線譜+コード+歌詞 + P2 TAB）
                    if (tracks.length > 0) {
                        addLog(`🎵 全${tracks.length}トラックを描画`);
                        api.renderTracks(tracks);
                    }
                });

                api.renderFinished.on(() => {
                    if (apiRef.current !== api) return;
                    addLog('🎨 Render Finished');

                    // スコア先頭が見えるようにスクロール位置を0にリセット
                    if (containerRef.current) {
                        containerRef.current.scrollTop = 0;
                    }

                    // AlphaTabのカーソル/選択関連DOM要素を非表示
                    if (wrapperRef.current) {
                        const selectors = [
                            '.at-cursor-beat', '.at-cursor-bar',
                            '.at-selection', '.at-highlight',
                            '.at-cursor-bar-fill', '.at-cursor-beat-fill',
                        ];
                        const cursorEls = wrapperRef.current.parentElement.querySelectorAll(selectors.join(','));
                        cursorEls.forEach(el => { el.style.display = 'none'; });
                    }

                    const ok = buildBeatMap(api);
                    boundsReadyRef.current = ok;

                    if (!ok) {
                        const retryDelays = [500, 1000, 2000, 3000];
                        const tryRetry = (attempt) => {
                            if (attempt >= retryDelays.length || destroyed || boundsReadyRef.current) return;
                            setTimeout(() => {
                                if (destroyed || boundsReadyRef.current) return;
                                addLog(`🔁 Retry ${attempt + 1}/${retryDelays.length}...`);
                                const retryOk = buildBeatMap(api);
                                boundsReadyRef.current = retryOk;
                                if (!retryOk) tryRetry(attempt + 1);
                            }, retryDelays[attempt]);
                        };
                        tryRetry(0);
                    }

                    if (containerRef.current) {
                        containerRef.current.scrollTo({ top: 0, behavior: 'instant' });
                    }
                    setTimeout(() => {
                        // ビートマップ確認ログ
                        const map = beatMapRef.current;
                        if (map && map.length > 0) {
                            addLog(`✅ BeatMap ready: ${map.length} beats`);
                        }
                    }, 100);

                    setLoading(false);
                    setSyncStatus('READY');
                });

                api.error.on((e) => addLog(`❌ ${e?.message ?? e}`));

                // ★ ハンドラ登録完了後にデータをロード
                addLog(`📂 api.load() でMusicXMLデータをロード中...`);
                api.load(xmlData instanceof Uint8Array ? xmlData : new Uint8Array(xmlData));

                // ★ ロードオーバーレイを即座に解除（スコアは裏で描画される）
                addLog('✅ ロード完了 — スコア描画中');
                setLoading(false);

                // ★ scoreLoadedが発火しない場合のフォールバック: api.scoreをポーリングしてP2選択
                const trackSelectTimer = setInterval(() => {
                    if (apiRef.current !== api) { clearInterval(trackSelectTimer); return; }
                    const score = api.score;
                    if (!score) return;
                    clearInterval(trackSelectTimer);
                    const tracks = score.tracks?.items || score.tracks || [];
                    addLog(`📄 ポーリング検出: ${tracks.length} tracks, ${score.masterBars?.length || 0} bars, ${score.tempo} BPM`);
                    if (tracks.length > 0) {
                        addLog(`🎵 全${tracks.length}トラックを描画`);
                        api.renderTracks(tracks);
                    }
                }, 200);

                // 10秒で諦め
                setTimeout(() => clearInterval(trackSelectTimer), 10000);

                // 3秒後のフォールバック: renderFinished未発火でもsyncStatusをREADYに
                const fallbackTimer = setTimeout(() => {
                    if (apiRef.current !== api) return;
                    if (boundsReadyRef.current) return;
                    addLog('⏰ ビートマップ構築をリトライ中...');
                    const ok = buildBeatMap(api);
                    boundsReadyRef.current = ok;
                    if (ok) setSyncStatus('READY');
                }, 3000);
                api.renderFinished.on(() => clearTimeout(fallbackTimer));

            } catch (e) {
                addLog(`💥 Fatal: ${e.message}`);
                setSyncStatus('ERROR');
                setLoading(false);
            }
        };

        init();
        return () => {
            destroyed = true;
            boundsReadyRef.current = false;
            beatMapRef.current = [];
            apiRef.current?.destroy();
            apiRef.current = null;
        };
    }, [sessionId, resetCounter, capo, transpose]);

    // ============================================================
    // 同期ループ
    // ★ カスタムカーソル駆動 + オートスクロール
    // ★ ユーザー手動スクロール時は一時停止（3秒後に自動復帰）
    // ============================================================
    useEffect(() => {
        let lastScrollMs = 0;
        let animId;
        let wasPlaying = false;
        let userScrollPauseUntil = 0;  // ユーザー操作による一時停止の解除時刻

        const container = containerRef.current;

        // ユーザーの手動スクロールを検知するハンドラ
        const handleUserScroll = () => {
            if (autoScroll && playingRef.current) {
                userScrollPauseUntil = Date.now() + 3000; // 3秒間一時停止
            }
        };

        // wheel / touch でユーザー操作を検知
        if (container) {
            container.addEventListener('wheel', handleUserScroll, { passive: true });
            container.addEventListener('touchmove', handleUserScroll, { passive: true });
        }

        const sync = () => {
            const cursor = cursorRef.current;
            const ms = Math.max(0, timeRef.current * 1000 + tabOffsetRef.current);
            const nowPlaying = playingRef.current;

            // 再生開始時に先頭にスクロール
            if (nowPlaying && !wasPlaying) {
                if (container && ms < 1000) {
                    container.scrollTo({ top: 0, behavior: 'instant' });
                    userScrollPauseUntil = 0; // 再生開始時はリセット
                }
            }
            wasPlaying = nowPlaying;

            // カスタムカーソルの位置更新
            if (cursor && boundsReadyRef.current) {
                const beat = findBeat(ms);
                if (beat) {
                    const { x, y, w, h } = beat.vb;
                    if (!cursor._firstLog) {
                        console.log('[TabView] 🎯 Cursor first pos:', { ms: ms.toFixed(0), x, y, w, h });
                        cursor._firstLog = true;
                    }
                    cursor.style.display = 'block';
                    cursor.style.left = `${x}px`;
                    cursor.style.top = `${y}px`;
                    cursor.style.width = `${Math.max(w, 8)}px`;
                    cursor.style.height = `${h}px`;

                    // オートスクロール（ユーザー操作で一時停止中でなければ）
                    const now = Date.now();
                    const userPaused = now < userScrollPauseUntil;
                    if (autoScroll && nowPlaying && container && !userPaused) {
                        if (now - lastScrollMs > 500) {
                            const containerRect = container.getBoundingClientRect();
                            const cursorScreenY = y - container.scrollTop;
                            if (cursorScreenY < 0 || cursorScreenY > containerRect.height * 0.6) {
                                const scrollOffset = Math.max(300, containerRect.height * 0.4);
                                container.scrollTo({
                                    top: Math.max(0, y - scrollOffset),
                                    behavior: 'smooth',
                                });
                                lastScrollMs = now;
                            }
                        }
                    }
                } else {
                    cursor.style.display = 'none';
                }
            }

            animId = requestAnimationFrame(sync);
        };

        animId = requestAnimationFrame(sync);
        return () => {
            cancelAnimationFrame(animId);
            if (container) {
                container.removeEventListener('wheel', handleUserScroll);
                container.removeEventListener('touchmove', handleUserScroll);
            }
        };
    }, [autoScroll]);

    const statusColor = {
        INIT: 'bg-amber-400 animate-pulse',
        READY: 'bg-emerald-400 shadow-[0_0_10px_#10b981]',
        ERROR: 'bg-rose-500',
    }[syncStatus] ?? 'bg-slate-400';

    const statusLabel = {
        INIT: loading ? 'RENDERING' : 'BUILDING',
        READY: 'SYNC_ACTIVE',
        ERROR: 'SYNC_ERROR',
    }[syncStatus] ?? syncStatus;

    return (
        <div className="w-full h-[calc(100vh-140px)] flex flex-col bg-[#0f172a] overflow-hidden border-t border-slate-800 font-sans">

            {/* AI Processing Status Bar (自動処理の進捗を最小限表示) */}
            {(sepStatus.processing || sepStatus.deepProcessing) && (
                <div className="flex items-center gap-3 px-4 py-2 bg-indigo-900/40 border-b border-indigo-500/20 flex-shrink-0">
                    <div className="w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                    <span className="text-[11px] font-bold text-indigo-300">
                        {sepStatus.deepProcessing ? '🎸 AI Deep Analysis実行中...' : '🤖 ギタートラック分離中...'}
                    </span>
                </div>
            )}

            {/* Score View (全幅) */}
            <div className="flex-1 flex flex-col min-w-0 min-h-0">
                {/* Virtual Fretboard Container */}
                <div
                    id="alphaTabFretboard"
                    className="bg-slate-900 border-b border-white/5 overflow-hidden transition-all"
                    style={{ height: 'auto', maxHeight: '240px' }}
                />

                <div
                    ref={containerRef}
                    className="flex-1 overflow-y-auto bg-white relative pb-[500px]"
                    onDoubleClick={() => {
                        setAutoScroll(prev => {
                            const next = !prev;
                            if (next) {
                                // オンにしたとき、現在の再生位置にジャンプ
                                const ms = Math.max(0, timeRef.current * 1000 + tabOffsetRef.current);
                                const beat = findBeat(ms);
                                if (beat && containerRef.current) {
                                    containerRef.current.scrollTo({
                                        top: Math.max(0, beat.vb.y - 300),
                                        behavior: 'smooth',
                                    });
                                }
                                addLog('📌 オートスクロール ON');
                            } else {
                                addLog('✋ オートスクロール OFF');
                            }
                            return next;
                        });
                    }}
                >
                    {/* オートスクロール状態インジケーター */}
                    <div
                        className={`fixed bottom-6 right-6 z-50 px-4 py-2 rounded-full shadow-lg cursor-pointer select-none transition-all duration-300 ${autoScroll
                            ? 'bg-emerald-500 text-white'
                            : 'bg-slate-700/80 text-slate-300 hover:bg-slate-600'
                            }`}
                        onClick={() => {
                            setAutoScroll(prev => {
                                const next = !prev;
                                if (next) {
                                    const ms = Math.max(0, timeRef.current * 1000 + tabOffsetRef.current);
                                    const beat = findBeat(ms);
                                    if (beat && containerRef.current) {
                                        containerRef.current.scrollTo({
                                            top: Math.max(0, beat.vb.y - 300),
                                            behavior: 'smooth',
                                        });
                                    }
                                }
                                return next;
                            });
                        }}
                        title="ダブルクリックまたはここをクリックでオートスクロール切替"
                    >
                        <span className="text-sm font-bold">
                            {autoScroll ? '📌 AUTO SCROLL ON' : '✋ AUTO SCROLL OFF'}
                        </span>
                    </div>
                    {loading && (
                        <div className="absolute inset-0 bg-white/95 z-40 flex flex-col items-center justify-center gap-4">
                            <div className="w-16 h-16 border-[6px] border-slate-950 border-t-transparent rounded-full animate-spin" />
                            <div className="text-center space-y-2">
                                <p className="text-[14px] font-black text-slate-950 uppercase tracking-[0.4em]">Rendering Score...</p>
                                <p className="text-[10px] font-bold text-slate-400 uppercase">
                                    {sepStatus.deepProcessing ? 'Analyzing Guitar Nuances...' : 'Building sync coordinates'}
                                </p>
                            </div>
                            {/* デバッグログ表示 */}
                            <div className="mt-4 max-w-md w-full max-h-24 overflow-y-auto px-4">
                                {logs.slice(0, 5).map((l, i) => (
                                    <p key={i} className="text-[9px] text-slate-400 font-mono truncate">{l}</p>
                                ))}
                            </div>
                        </div>
                    )}
                    {syncStatus === 'ERROR' && !loading && (
                        <div className="absolute inset-0 bg-white/95 z-40 flex flex-col items-center justify-center gap-4">
                            <p className="text-lg font-bold text-red-600">⚠️ 楽譜の描画に失敗しました</p>
                            <div className="max-w-md w-full max-h-32 overflow-y-auto px-4 mb-4">
                                {logs.slice(0, 8).map((l, i) => (
                                    <p key={i} className="text-[10px] text-slate-500 font-mono truncate">{l}</p>
                                ))}
                            </div>
                            <button
                                onClick={() => setResetCounter(c => c + 1)}
                                className="px-6 py-3 bg-amber-500 text-black font-bold rounded-lg hover:bg-amber-400 transition"
                            >
                                再試行
                            </button>
                        </div>
                    )}

                    <div style={{ position: 'relative', padding: 0, margin: 0 }}>
                        <div
                            id="custom-cursor"
                            ref={cursorRef}
                            style={{
                                position: 'absolute',
                                display: 'none',
                                pointerEvents: 'none',
                                zIndex: 30,
                                top: 0,
                                left: 0,
                                background: 'rgba(59, 130, 246, 0.13)',
                                borderLeft: '2.5px solid rgba(59, 130, 246, 0.5)',
                                borderRadius: '2px',
                                transition: 'left 0.06s linear, top 0.04s ease-out',
                                willChange: 'left, top, width, height',
                            }}
                        />
                        <div ref={wrapperRef} style={{ width: '100%', minHeight: '100vh' }} />
                    </div>
                </div>
            </div>

            <style>{`
                .at-cursor-beat, .at-cursor-bar, .at-selection, .at-highlight { display: none !important; }
                .at-tablature { display: block !important; }
                .alphaTabSurface { position: static !important; }
            `}
            </style>
        </div>
    );
};

// --- エラーバウンダリ（HMR後の白画面防止） ---
class TabViewErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false };
    }
    static getDerivedStateFromError() {
        return { hasError: true };
    }
    componentDidCatch(err) {
        console.error('[TabView] Caught error:', err);
    }
    render() {
        if (this.state.hasError) {
            return (
                <div style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center',
                    justifyContent: 'center', height: '60vh', color: '#f59e0b', gap: 16,
                }}>
                    <p style={{ fontSize: 18 }}>⚠️ 楽譜の描画中にエラーが発生しました</p>
                    <button
                        onClick={() => this.setState({ hasError: false })}
                        style={{
                            padding: '10px 24px', borderRadius: 8,
                            background: '#f59e0b', color: '#000', fontWeight: 'bold',
                            border: 'none', cursor: 'pointer', fontSize: 14,
                        }}
                    >
                        再試行
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}

const TabViewWithBoundary = (props) => (
    <TabViewErrorBoundary>
        <TabView {...props} />
    </TabViewErrorBoundary>
);

export default TabViewWithBoundary;
