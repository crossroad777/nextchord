import React, { useState, useEffect, useRef } from "react";
import {
  Search, History, Star, Share2, Download, Music, List, Play, Pause, SkipForward, SkipBack,
  Volume2, RotateCcw, Save, Trash2, Edit, Check, X, ChevronRight, ChevronLeft, MessageSquare, Plus, ExternalLink,
  Info, Settings, Sliders, Repeat, Clock, UploadCloud, MicOff, Heart, FileText, FileCode, Zap, Minus, AlertTriangle,
  MoreHorizontal, Layout, Layers, VideoOff, ChevronDown, Guitar, Square, AlignLeft,
  Sun, Moon
} from 'lucide-react';
import { BeatGrid } from "./components/BeatGrid";
import { InstrumentPanel } from "./components/InstrumentPanel";
import { TabView } from "./components/TabView";
import { ChordLyricsView } from "./components/ChordLyricsView";
import { transposeChord } from "./utils/musicUtils";

const API_BASE = import.meta.env.VITE_API_URL !== undefined ? import.meta.env.VITE_API_URL : "http://localhost:8000";

const STATUS = { IDLE: "idle", UPLOADING: "uploading", PROCESSING: "processing", COMPLETED: "completed", FAILED: "failed" };

export default function NextChordApp() {
  const [status, setStatus] = useState(STATUS.IDLE);
  const [progressMsg, setProgressMsg] = useState("Preparing...");
  const [session, setSession] = useState(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [currentChord, setCurrentChord] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const [viewMode, setViewMode] = useState("tab"); // "chords", "tab", or "text"

  // Premium Controls State
  const [transpose, setTranspose] = useState(0);
  const [latency, setLatency] = useState(-250); // デフォルト
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [volume, setVolume] = useState(100);
  const [vocalCancel, setVocalCancel] = useState(false);
  const [isLooping, setIsLooping] = useState(false);
  const [loopRegion, setLoopRegion] = useState({ start: null, end: null });
  const [isSeparating, setIsSeparating] = useState(false);
  const [separationProgress, setSeparationProgress] = useState("");
  const [hasCleanAudio, setHasCleanAudio] = useState(false);
  const [waveform, setWaveform] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [instrument, setInstrument] = useState("guitar");
  const [capo, setCapo] = useState(0);
  const [history, setHistory] = useState([]);

  // テーマ切替
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('nextchord-theme') || 'dark'; } catch { return 'dark'; }
  });
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('nextchord-theme', theme);
  }, [theme]);
  const toggleTheme = () => {
    document.documentElement.setAttribute('data-theme-transitioning', '');
    setTheme(t => t === 'dark' ? 'light' : 'dark');
    setTimeout(() => document.documentElement.removeAttribute('data-theme-transitioning'), 400);
  };

  // セッション切り替え時に楽曲ごとの補正値を読み込む
  useEffect(() => {
    if (session?.id) {
      try {
        const latencyMap = JSON.parse(localStorage.getItem('nextchord-latency-map') || '{}');
        const savedLatency = latencyMap[session.id];
        if (savedLatency !== undefined) {
          setLatency(savedLatency);
        } else {
          const globalDefault = parseInt(localStorage.getItem('nextchord-latency') || '-250');
          setLatency(globalDefault);
        }
      } catch (e) {
        console.error("Latency load error:", e);
      }
    }
  }, [session?.id]);

  // 補正値が変更されたら保存する
  useEffect(() => {
    try {
      localStorage.setItem('nextchord-latency', latency.toString());
      if (session?.id) {
        const latencyMap = JSON.parse(localStorage.getItem('nextchord-latency-map') || '{}');
        latencyMap[session.id] = latency;
        localStorage.setItem('nextchord-latency-map', JSON.stringify(latencyMap));
      }
    } catch (e) {
      console.error("Latency save error:", e);
    }
  }, [latency, session?.id]);

  // Feature states
  const [favorites, setFavorites] = useState(() => {
    try { return JSON.parse(localStorage.getItem('nextchord-favorites') || '[]'); } catch { return []; }
  });
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [toast, setToast] = useState(null);

  const audioRef = useRef(null);
  const canvasRef = useRef(null);
  const fileInputRef = useRef(null);
  const pollInterval = useRef(null);
  const sseRef = useRef(null);

  // 書き出しメニュー外クリックで閉じる
  useEffect(() => {
    if (!showMoreMenu) return;
    const handleClickOutside = () => setShowMoreMenu(false);
    // 次のイベントループで追加（現在のクリックをキャプチャしないため）
    const timer = setTimeout(() => document.addEventListener('click', handleClickOutside), 0);
    return () => { clearTimeout(timer); document.removeEventListener('click', handleClickOutside); };
  }, [showMoreMenu]);

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${API_BASE}/sessions`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data);
      }
    } catch (e) { console.error("History fetch error:", e); }
  };

  // アプリ起動時: 前回のセッションを自動復元
  useEffect(() => {
    const lastSid = localStorage.getItem('nextchord-last-session');
    if (lastSid && status === STATUS.IDLE) {
      restoreSession(lastSid);
    } else if (status === STATUS.IDLE) {
      fetchHistory();
    }
  }, []);

  // セッション完了時にIDをlocalStorageに保存
  useEffect(() => {
    if (status === STATUS.COMPLETED && session?.id) {
      localStorage.setItem('nextchord-last-session', session.id);
    }
  }, [status, session?.id]);

  useEffect(() => {
    if (status === STATUS.IDLE) {
      fetchHistory();
    }
  }, [status]);

  const restoreSession = async (sid) => {
    setStatus(STATUS.PROCESSING);
    setProgressMsg("セッションを復元中...");
    try {
      const res = await fetch(`${API_BASE}/result/${sid}`);
      if (!res.ok) throw new Error("Session not found");
      const result = await res.json();
      setSession({
        id: sid,
        fileName: result.filename || "Restored Session",
        artist: result.artist || "",
        result,
        data: result.structured_data,
        lyricsPhrases: result.lyrics_phrases || [],
        displayPhrases: result.display_phrases || [],
        audioUrl: `${API_BASE}/files/${sid}/converted.wav`,
        hasNotes: result.has_notes
      });
      // Load waveform
      try {
        const wRes = await fetch(`${API_BASE}/result/${sid}/waveform`);
        const wData = await wRes.json();
        setWaveform(wData.peaks || []);
      } catch { }
      setStatus(STATUS.COMPLETED);
    } catch (err) {
      setStatus(STATUS.FAILED);
      setProgressMsg("セッションの復元に失敗しました。サーバーがリロードされた可能性があります。");
    }
  };

  // Audio Sync Loop
  useEffect(() => {
    let anim;
    let i = 0;
    const tick = () => {
      if (audioRef.current) {
        const time = audioRef.current.currentTime;
        if (isLooping && loopRegion.start !== null && loopRegion.end !== null) {
          if (time >= loopRegion.end) {
            audioRef.current.currentTime = loopRegion.start;
            setCurrentTime(loopRegion.start);
            anim = requestAnimationFrame(tick);
            return;
          }
        }
        if (i++ % 60 === 0) console.log(`[App] tick: time=${time.toFixed(3)}s, isPlaying=${isPlaying}`);
        setCurrentTime(time);

        const adjustedTime = time - (latency / 1000); // 補正後の時間
        if (session?.result?.structured_data) {
          const beat = session.result.structured_data.find((b, i, arr) => {
            const next = arr[i + 1];
            return adjustedTime >= b.time && (next ? adjustedTime < next.time : adjustedTime < b.time + b.duration);
          });
          if (beat && beat.chord) setCurrentChord(beat.chord);
        }



        anim = requestAnimationFrame(tick);
      }
    };
    if (isPlaying) anim = requestAnimationFrame(tick);
    else cancelAnimationFrame(anim);
    return () => cancelAnimationFrame(anim);
  }, [isPlaying, isLooping, loopRegion, session, latency]);

  // 再生中でなくてもcurrentTimeに基づいてcurrentChordを更新
  useEffect(() => {
    if (!session?.result?.structured_data) return;
    const adjustedTime = currentTime - (latency / 1000);
    const beat = session.result.structured_data.find((b, i, arr) => {
      const next = arr[i + 1];
      return adjustedTime >= b.time && (next ? adjustedTime < next.time : adjustedTime < b.time + b.duration);
    });
    if (beat && beat.chord) setCurrentChord(beat.chord);
    else if (currentTime === 0 && session.result.structured_data.length > 0) {
      // 初期状態: 最初のコードを表示
      const first = session.result.structured_data.find(b => b.chord && b.chord !== 'N.C.');
      if (first) setCurrentChord(first.chord);
    }
  }, [currentTime, session?.result?.structured_data, latency]);

  // Reactive Waveform Drawing (Handles stop/seek/playback)
  useEffect(() => {
    if (waveform.length > 0 && canvasRef.current && audioRef.current) {
      drawWaveform(canvasRef.current, waveform, currentTime, audioRef.current.duration);
    }
  }, [currentTime, waveform]);

  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = playbackRate; }, [playbackRate]);
  useEffect(() => { if (audioRef.current) audioRef.current.volume = volume / 100; }, [volume]);

  useEffect(() => {
    if (session?.audioUrl && audioRef.current) {
      const src = vocalCancel && hasCleanAudio ? session.audioUrl.replace('converted.wav', 'clean.wav') : session.audioUrl;
      if (audioRef.current.src !== src) {
        const t = audioRef.current.currentTime;
        audioRef.current.src = src;
        audioRef.current.currentTime = t;
        if (isPlaying) audioRef.current.play();
      }
    }
  }, [vocalCancel, hasCleanAudio, session]);

  const drawWaveform = (canvas, data, currTime, duration) => {
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    const g = ctx.createLinearGradient(0, 0, w, 0);
    g.addColorStop(0, "#16a085"); g.addColorStop(1, "#3498db");
    ctx.fillStyle = g;
    const step = Math.ceil(data.length / w);
    for (let i = 0; i < w; i++) {
      const idx = Math.floor(i * step);
      const val = data[idx] !== undefined ? data[idx] : 0.5;
      const barH = Math.max(4, val * h * 0.8);
      ctx.globalAlpha = i / w <= currTime / duration ? 1 : 0.3;
      ctx.fillRect(i, (h - barH) / 2, 1, barH);
    }
    ctx.globalAlpha = 1;
  };

  // --- SSE-based status streaming (replaces polling) ---
  const handleStatusCompleted = async (sid) => {
    try {
      const resData = await fetch(`${API_BASE}/result/${sid}`);
      const result = await resData.json();
      setSession(prev => ({
        ...prev,
        result,
        data: result.structured_data,
        lyricsPhrases: result.lyrics_phrases || [],
        displayPhrases: result.display_phrases || [],
        audioUrl: prev?.audioUrl || `${API_BASE}/files/${sid}/converted.wav`,
        hasNotes: result.has_notes,
        fileName: result.filename || prev?.fileName,
        artist: result.artist || prev?.artist
      }));
      setStatus(STATUS.COMPLETED);
      try {
        const wRes = await fetch(`${API_BASE}/result/${sid}/waveform`);
        const wData = await wRes.json();
        setWaveform(wData.peaks || []);
      } catch { }
    } catch (err) {
      console.error("[SSE] Failed to fetch result:", err);
      setStatus(STATUS.FAILED);
      setProgressMsg("結果の取得に失敗しました。");
    }
  };

  const startStatusStream = (sid) => {
    // Close previous SSE if any
    if (sseRef.current) { sseRef.current.close(); sseRef.current = null; }
    if (pollInterval.current) { clearInterval(pollInterval.current); pollInterval.current = null; }

    const es = new EventSource(`${API_BASE}/status/${sid}/stream`);
    sseRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setProgressMsg(data.progress || "Analyzing...");
        if (data.filename || data.artist) {
          setSession(prev => prev ? {
            ...prev,
            ...(data.filename && { fileName: data.filename }),
            ...(data.artist && { artist: data.artist })
          } : prev);
        }
        if (data.status === "completed") {
          es.close(); sseRef.current = null;
          handleStatusCompleted(sid);
        } else if (data.status === "failed" || data.status === "not_found") {
          es.close(); sseRef.current = null;
          setProgressMsg(data.error || "分析に失敗しました");
          setStatus(STATUS.FAILED);
        }
      } catch (e) { console.error("[SSE] Parse error:", e); }
    };

    es.onerror = () => {
      console.warn("[SSE] Connection lost, falling back to polling");
      es.close(); sseRef.current = null;
      // Fallback to legacy polling
      pollInterval.current = setInterval(() => checkStatusLegacy(sid), 2000);
    };
  };

  // Legacy polling fallback (in case SSE fails)
  const pollErrorCount = useRef(0);
  const checkStatusLegacy = async (sid) => {
    try {
      const res = await fetch(`${API_BASE}/status/${sid}`);
      if (res.status === 404) {
        clearInterval(pollInterval.current);
        setProgressMsg("セッションが見つかりません。再度アップロードしてください。");
        setStatus(STATUS.FAILED);
        return;
      }
      if (!res.ok) { pollErrorCount.current++; if (pollErrorCount.current >= 5) { clearInterval(pollInterval.current); setStatus(STATUS.FAILED); } return; }
      pollErrorCount.current = 0;
      const data = await res.json();
      setProgressMsg(data.progress || "Analyzing...");
      if (data.filename || data.artist) {
        setSession(prev => prev ? { ...prev, ...(data.filename && { fileName: data.filename }), ...(data.artist && { artist: data.artist }) } : prev);
      }
      if (data.status === "completed") { clearInterval(pollInterval.current); handleStatusCompleted(sid); }
      else if (data.status === "failed") { clearInterval(pollInterval.current); setProgressMsg(data.error || "分析に失敗しました"); setStatus(STATUS.FAILED); }
    } catch { pollErrorCount.current++; if (pollErrorCount.current >= 5) { clearInterval(pollInterval.current); setStatus(STATUS.FAILED); } }
  };

  const checkSeparationStatus = async (sid) => {
    try {
      const res = await fetch(`${API_BASE}/status/separation/${sid}`);
      const data = await res.json();
      setSeparationProgress(data.progress);
      if (data.has_clean_audio) { setHasCleanAudio(true); setIsSeparating(false); }
      else if (data.error) { setIsSeparating(false); }
    } catch { }
  };

  const handleSeparate = async () => {
    if (!session?.id) return;
    setIsSeparating(true);
    try {
      await fetch(`${API_BASE}/separate/${session.id}`, { method: "POST" });
      const sepPoll = setInterval(() => {
        checkSeparationStatus(session.id);
        if (hasCleanAudio || !isSeparating) clearInterval(sepPoll);
      }, 2000);
    } catch { setIsSeparating(false); }
  };

  const togglePlay = () => {
    if (!audioRef.current || !session?.audioUrl) return;
    if (isPlaying) { audioRef.current.pause(); setIsPlaying(false); }
    else { audioRef.current.play(); setIsPlaying(true); }
  };

  const handleStop = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setIsPlaying(false);
    setCurrentTime(0);
  };

  const handleSeek = (time) => { if (audioRef.current) audioRef.current.currentTime = time; setCurrentTime(time); };
  const toggleLoop = () => {
    if (!isLooping && audioRef.current) setLoopRegion({ start: currentTime, end: Math.min(currentTime + 10, audioRef.current.duration) });
    setIsLooping(!isLooping);
  };

  const handleUpload = async (ev) => {
    // Highly defensive extraction of the File object
    let file = null;
    if (ev?.target?.files?.[0]) {
      file = ev.target.files[0];
    } else if (ev instanceof File) {
      file = ev;
    } else if (ev?.name && (ev?.size !== undefined)) {
      // Duck typing fallback
      file = ev;
    }

    if (!file || typeof file.name !== 'string') {
      console.warn("[handleUpload] No valid file found in event:", ev);
      return;
    }

    const isAudio = file.name.match(/\.(mp3|wav|m4a|flac)$/i);

    // If it's not a recognized audio file, try to treat it as a potential shortcut/link file
    if (!isAudio) {
      if (file.size > 256000) { // Don't try to read huge files as text
        setStatus(STATUS.FAILED);
        setProgressMsg("サポートされていない形式です (MP3, WAV, M4A, FLAC対応)。");
        return;
      }

      const reader = new FileReader();
      reader.onload = (ev) => {
        const content = ev.target.result;
        // Search for any YouTube URL pattern in the file content
        const ytMatch = content.match(/(https?:\/\/(?:www\.|music\.|m\.)?youtube\.com\/watch\?v=[^\s"']+(?:&[^\s"']+)?)|(https?:\/\/youtu\.be\/[^\s?]+(?:\?[^\s"']+)?)|(https?:\/\/(?:www\.|music\.)?youtube\.com\/shorts\/[^\s"']+)/i);
        if (ytMatch) {
          handleYouTubeUpload(ytMatch[0].trim());
        } else {
          setStatus(STATUS.FAILED);
          setProgressMsg("サポートされていない形式です。音声ファイルまたはYouTubeリンクをドロップしてください。");
        }
      };
      reader.readAsText(file);
      return;
    }

    // Prohibit uploading known non-audio even if large
    setStatus(STATUS.UPLOADING);
    setProgressMsg("Uploading...");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: formData });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Upload failed");
      }
      const data = await res.json();
      setSession({ id: data.session_id, fileName: file.name, audioUrl: `${API_BASE}${data.audio_url}` });
      setHasCleanAudio(false);
      setIsSeparating(false);
      setStatus(STATUS.PROCESSING);
      startStatusStream(data.session_id);
    } catch (err) {
      setStatus(STATUS.FAILED);
      setProgressMsg(err.message || "アップロードに失敗しました");
    }
  };

  const [ytUrl, setYtUrl] = useState("");
  const handleYouTubeUpload = async (urlToUse = ytUrl) => {
    if (!urlToUse) return;
    setStatus(STATUS.PROCESSING);
    setProgressMsg("YouTube音声を解析中...");
    try {
      const res = await fetch(`${API_BASE}/upload/youtube`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlToUse })
      });
      if (!res.ok) throw new Error("YouTube upload failed");
      const data = await res.json();
      setSession({
        id: data.session_id,
        fileName: "YouTube Video",
        audioUrl: null // Will be set after completion
      });
      setHasCleanAudio(false);
      setIsSeparating(false);
      startStatusStream(data.session_id);
    } catch (err) {
      setStatus(STATUS.FAILED);
      setProgressMsg("YouTube解析に失敗しました。URLを確認してください。");
    }
  };

  const handleDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e) => { e.preventDefault(); setIsDragging(false); };
  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);

    // 1. Check for browser text/links (Direct drag from address bar or link element)
    const dt = e.dataTransfer;
    let droppedText = dt.getData("text/plain") || dt.getData("text/uri-list") || dt.getData("text");

    // Some browsers provide multi-line uri-list, take the first one
    if (droppedText && droppedText.includes("\n")) droppedText = droppedText.split("\n")[0].trim();

    if (droppedText && (droppedText.includes("youtube.com") || droppedText.includes("youtu.be"))) {
      handleYouTubeUpload(droppedText.trim());
      return;
    }

    // 2. Check for files (Local shortcuts or audio files)
    const files = dt.files;
    if (files?.[0]) {
      handleUpload(files[0]);
      return;
    }
  };

  const showToast = (message, type = 'success') => { setToast({ message, type }); setTimeout(() => setToast(null), 3000); };

  const isFavorite = session?.id && favorites.includes(session.id);
  const toggleFavorite = () => {
    let f = isFavorite ? favorites.filter(x => x !== session.id) : [...favorites, session.id];
    setFavorites(f);
    localStorage.setItem('nextchord-favorites', JSON.stringify(f));
  };

  const handleShare = async () => {
    if (!session?.id) return;
    try { await navigator.clipboard.writeText(window.location.origin + "?session=" + session.id); showToast('Link copied!'); }
    catch { showToast('Share failed', 'error'); }
  };

  const handleExportPDF = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${API_BASE}/export/${session.id}/pdf`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `nextchord_${session.id}.pdf`; a.click();
    } catch { showToast('PDF export failed', 'error'); }
  };

  const handleExportMIDI = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${API_BASE}/export/${session.id}/midi`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `nextchord_${session.id}.mid`; a.click();
    } catch { showToast('MIDI export failed', 'error'); }
  };

  const handleExportMusicXML = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${API_BASE}/export/${session.id}/musicxml`);
      if (!res.ok) throw new Error("No MusicXML");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `nextchord_${session.id}.musicxml`; a.click();
    } catch { showToast('MusicXML export failed', 'error'); }
  };

  const handleExportText = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${API_BASE}/result/${session.id}/text`);
      if (!res.ok) throw new Error("No Text");
      const text = await res.text();
      const blob = new Blob([text], { type: 'text/plain; charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `${session.fileName || 'nextchord'}.txt`; a.click();
    } catch { showToast('テキスト書き出しに失敗しました', 'error'); }
  };

  const [showTextModal, setShowTextModal] = useState(false);
  const [textContent, setTextContent] = useState("");

  const handleViewText = async () => {
    if (!session?.id) return;
    setShowTextModal(true);
    setTextContent("Loading...");
    try {
      const res = await fetch(`${API_BASE}/result/${session.id}/text`);
      if (!res.ok) throw new Error("Failed");
      const text = await res.text();
      setTextContent(text);
    } catch {
      setTextContent("Error loading text score.");
    }
  };

  const handleWaveformClick = (e) => {
    if (!audioRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    handleSeek((x / rect.width) * audioRef.current.duration);
  };

  // コード編集ハンドラ

  const handleTranspose = (delta) => {
    const newVal = Math.max(-12, Math.min(12, transpose + delta));
    setTranspose(newVal);
    showToast(`転調を ${newVal > 0 ? '+' : ''}${newVal} に設定しました`);
  };

  const handleChordEdit = (index, newChord) => {
    if (!session?.data) return;
    const newData = [...session.data];
    if (newChord === '' || newChord === 'N.C.') {
      // コード削除
      newData[index] = { ...newData[index], chord: 'N.C.', _edited: true };
      showToast('コードを削除しました');
    } else {
      newData[index] = { ...newData[index], chord: newChord, _edited: true };
      showToast(`コードを "${newChord}" に変更しました`);
    }
    setSession(prev => ({ ...prev, data: newData }));
    saveChordEdits(newData);
  };

  // timeベースのコード変更（ChordLyricsViewから使用）
  const handleChordEditByTime = (time, newChord) => {
    if (!session?.data) return;
    // 最も近いエントリを見つける
    let bestIdx = -1;
    let bestDist = Infinity;
    for (let i = 0; i < session.data.length; i++) {
      const dist = Math.abs(session.data[i].time - time);
      if (dist < bestDist) {
        bestDist = dist;
        bestIdx = i;
      }
    }
    if (bestIdx >= 0) {
      handleChordEdit(bestIdx, newChord);
    }
  };

  // バックエンドにコード編集を保存
  const saveChordEdits = async (newData) => {
    if (!session?.id) return;
    try {
      await fetch(`${API_BASE}/result/${session.id}/chords`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          edits: newData
            .map((d, i) => d._edited ? { index: i, chord: d.chord } : null)
            .filter(Boolean)
        })
      });
    } catch (e) {
      console.warn('Chord save failed:', e);
    }
  };

  // 歌詞編集ハンドラ（startTimeで対応フレーズを特定して更新）
  const handleLyricEdit = (startTime, newText) => {
    if (!session?.displayPhrases) return;
    const newPhrases = session.displayPhrases.map(p => {
      if (Math.abs(p.start - startTime) < 0.2) {
        return { ...p, text: newText };
      }
      return p;
    });
    setSession(prev => ({ ...prev, displayPhrases: newPhrases }));
    showToast('歌詞を更新しました');
    saveLyricEdits(newPhrases);
  };

  // バックエンドに歌詞編集を保存
  const saveLyricEdits = async (phrases) => {
    if (!session?.id) return;
    try {
      await fetch(`${API_BASE}/result/${session.id}/lyrics`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_phrases: phrases })
      });
    } catch (e) {
      console.warn('Lyric save failed:', e);
    }
  };
  // 移調されたキーを計算する
  const getTransposedKey = (originalKey, semitones) => {
    if (!originalKey) return "Unknown";
    const [root, mode] = originalKey.split(" ");
    return transposeChord(root, semitones) + (mode ? " " + mode : "");
  };

  // YouTube Embed URL 取得ユーティリティ
  const getYouTubeEmbedUrl = (url) => {
    if (!url) return null;
    let videoId = null;
    if (url.includes('v=')) videoId = url.split('v=')[1].split('&')[0];
    else if (url.includes('youtu.be/')) videoId = url.split('youtu.be/')[1].split('?')[0];
    if (videoId) return `https://www.youtube.com/embed/${videoId}`;
    return null;
  };



  // -------------------------------------------------------------
  // REFACTORED: ResultView (Moved outside or properly stable)
  // -------------------------------------------------------------
  const renderResultView = () => {
    if (status !== STATUS.COMPLETED || !session?.data) return null;

    const embedUrl = getYouTubeEmbedUrl((session.audioUrl && session.audioUrl.includes('youtube')) ? session.audioUrl : (session.result?.youtube_url || null));

    // 安全な時間フォーマット関数
    const formatTime = (seconds) => {
      if (isNaN(seconds) || seconds === Infinity || seconds === -Infinity) return "00:00";
      return new Date(seconds * 1000).toISOString().substr(14, 5);
    };

    const duration = audioRef.current?.duration || 0;
    const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

    // 解析データからユニークなコードを抽出
    const uniqueChords = session.data
      ? Array.from(new Set(session.data.map(b => b.chord))).filter(c => c && c !== 'N').slice(0, 5)
      : ['D', 'Bm', 'G', 'A'];

    return (
      <div className="flex h-full bg-[var(--gf-bg)] overflow-hidden">
        {/* Main Content Column */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* 1. Song Header + 曲情報バッジ */}
          <header className="px-8 py-4 bg-[var(--gf-surface)] border-b border-[var(--gf-border)] flex items-center justify-between">
            <div className="flex items-center gap-6 min-w-0 flex-1">
              <div className="min-w-0 flex-1">
                <h1 className="text-xl font-black text-[var(--gf-text)] tracking-tight leading-tight truncate">
                  {session.fileName || "Untitled Track"}
                </h1>
                {session.artist && (
                  <p className="text-[11px] font-bold text-[var(--gf-text-dim)] mt-0.5 truncate">
                    {session.artist}
                  </p>
                )}
              </div>
            </div>
            {/* 曲情報バッジ — 右寄せ */}
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="px-3 py-1.5 bg-[var(--gf-surface-2)] rounded-lg text-[11px] font-black text-[var(--gf-text)] border border-[var(--gf-border)]">
                Key: {getTransposedKey(session.result?.key, transpose - capo) || '--'}{capo > 0 ? ` (Capo ${capo})` : ''}
              </span>
              <span className="px-3 py-1.5 bg-[var(--gf-surface-2)] rounded-lg text-[11px] font-black text-[var(--gf-amber)] border border-[var(--gf-border)]">
                ♩ {session.result?.bpm ? Math.round(session.result.bpm) : '--'} BPM
              </span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0 ml-4">
              <button onClick={handleShare} className="p-2.5 bg-[var(--gf-surface-2)] text-[var(--gf-text-dim)] hover:text-[var(--gf-amber)] rounded-xl transition-all border border-[var(--gf-border)]"><Share2 size={18} /></button>
              <button onClick={toggleFavorite} className={`p-2.5 rounded-xl transition-all border ${isFavorite ? 'bg-pink-900/30 border-pink-800 text-pink-400' : 'bg-[var(--gf-surface-2)] border-[var(--gf-border)] text-[var(--gf-text-dim)] hover:text-pink-400'}`}>
                <Heart size={18} fill={isFavorite ? 'currentColor' : 'none'} />
              </button>
              <button className="p-2.5 bg-[var(--gf-surface-2)] text-[var(--gf-text-dim)] hover:text-[var(--gf-amber)] rounded-xl transition-all border border-[var(--gf-border)]"><MoreHorizontal size={18} /></button>
            </div>
          </header>

          {/* 2. Playback Controller Section + Video + Latency (コンパクト統合) */}
          <div className="px-6 py-3 bg-[var(--gf-surface)] border-b border-[var(--gf-border)]">
            <div className="flex items-stretch gap-4">
              {/* 再生コントロール + タイムライン */}
              <div className="flex-1 flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <button onClick={togglePlay} className="nc-large-play-btn">
                    {isPlaying ? <Pause size={28} fill="currentColor" /> : <Play size={28} className="ml-1" fill="currentColor" />}
                  </button>
                  <button onClick={handleStop} title="Stop" className="w-9 h-9 flex items-center justify-center rounded-xl bg-[var(--gf-surface-2)] text-[var(--gf-text-dim)] hover:text-[var(--gf-text)] border border-[var(--gf-border)] transition-all active:scale-95">
                    <Square size={16} fill="currentColor" />
                  </button>
                </div>
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1 text-[9px] font-black text-[var(--gf-text-dim)] uppercase tracking-widest">
                    <span>{formatTime(currentTime)}</span>
                    <span>{formatTime(duration)}</span>
                  </div>
                  <div className="nc-timeline-container" onClick={handleWaveformClick}>
                    <div className="nc-timeline-progress" style={{ width: `${progress}%` }} />
                    <div className="nc-timeline-handle" style={{ left: `${progress}%` }} />
                  </div>
                </div>
              </div>



              {/* LATENCY (コンパクト) */}
              <div className="w-[140px] flex-shrink-0 flex flex-col justify-center gap-1">
                <div className="flex items-center justify-between">
                  <span className="text-[8px] font-black text-[var(--gf-text-dim)] uppercase tracking-wider flex items-center gap-1">
                    <Clock size={10} /> Latency
                  </span>
                  <span className="text-[9px] font-mono font-black text-[var(--gf-amber)]">{latency}ms</span>
                </div>
                <input
                  type="range"
                  min="-500"
                  max="500"
                  step="10"
                  value={latency}
                  onChange={(e) => setLatency(parseInt(e.target.value))}
                  className="w-full h-1 bg-[var(--gf-surface-3)] rounded-lg appearance-none cursor-pointer accent-[var(--gf-amber)]"
                />
              </div>
            </div>
          </div>

          {/* 3. Feature Ribbon */}
          <div className="nc-ribbon scrollbar-hide">
            {/* Speed */}
            <div className="nc-ribbon-item">
              <div className="flex items-center gap-1 mb-1">
                <button onClick={() => setPlaybackRate(r => Math.max(0.5, Math.round((r - 0.05) * 100) / 100))}><ChevronLeft size={14} /></button>
                <span className="text-sm font-black italic text-[var(--gf-text)] w-10 text-center">{Math.round(playbackRate * 100)}%</span>
                <button onClick={() => setPlaybackRate(r => Math.min(2.0, Math.round((r + 0.05) * 100) / 100))}><ChevronRight size={14} /></button>
              </div>
              <span className="nc-ribbon-label">{Math.round((session?.result?.bpm || 120) * playbackRate)} BPM</span>
            </div>

            {/* Loop */}
            <div onClick={toggleLoop} className={`nc-ribbon-item ${isLooping ? 'bg-[var(--gf-amber-glow)]' : ''}`}>
              <Repeat className={`nc-ribbon-icon ${isLooping ? 'text-[var(--gf-amber)]' : ''}`} size={20} />
              <span className="nc-ribbon-label">ループ</span>
            </div>

            {/* Capo */}
            <div className="nc-ribbon-item">
              <div className="flex items-center gap-1 mb-1">
                <button onClick={() => setCapo(c => Math.max(0, c - 1))}><ChevronLeft size={14} /></button>
                <span className="text-sm font-black italic text-[var(--gf-text)] w-8 text-center">{capo}</span>
                <button onClick={() => setCapo(c => Math.min(9, c + 1))}><ChevronRight size={14} /></button>
              </div>
              <span className="nc-ribbon-label">カポ</span>
            </div>

            {/* Transpose */}
            <div className="nc-ribbon-item">
              <div className="flex items-center gap-1 mb-1">
                <button onClick={() => handleTranspose(-1)}><ChevronLeft size={14} /></button>
                <span className="text-sm font-black italic text-[var(--gf-text)] w-8 text-center">{transpose > 0 ? `+${transpose}` : transpose}</span>
                <button onClick={() => handleTranspose(1)}><ChevronRight size={14} /></button>
              </div>
              <span className="nc-ribbon-label">転調</span>
            </div>

            {/* Instrument Toggle */}
            <div className="nc-ribbon-divider" />
            <div onClick={() => setInstrument('guitar')} className={`nc-ribbon-item ${instrument === 'guitar' ? 'active' : ''}`}>
              <Guitar className="nc-ribbon-icon" size={20} />
              <span className="nc-ribbon-label">ギター</span>
            </div>
            <div onClick={() => setInstrument('piano')} className={`nc-ribbon-item ${instrument === 'piano' ? 'active' : ''}`}>
              <Music className="nc-ribbon-icon" size={20} />
              <span className="nc-ribbon-label">ピアノ</span>
            </div>
            <div className="nc-ribbon-divider" />

            {/* View Mode Buttons */}
            <div onClick={() => setViewMode('chords')} className={`nc-ribbon-item ${viewMode === 'chords' ? 'active' : ''}`}>
              <Layout className="nc-ribbon-icon" size={20} />
              <span className="nc-ribbon-label">グリッド</span>
            </div>
            <div onClick={() => setViewMode('tab')} className={`nc-ribbon-item ${viewMode === 'tab' ? 'active' : ''}`}>
              <FileCode className="nc-ribbon-icon" size={20} />
              <span className="nc-ribbon-label">スコア</span>
            </div>
            <div onClick={() => setViewMode('text')} className={`nc-ribbon-item ${viewMode === 'text' ? 'active' : ''}`}>
              <AlignLeft className="nc-ribbon-icon" size={20} />
              <span className="nc-ribbon-label">テキスト</span>
            </div>

            {/* Export */}
            <div onClick={() => setShowMoreMenu(!showMoreMenu)} className="nc-ribbon-item relative">
              <Download className="nc-ribbon-icon" size={20} />
              <span className="nc-ribbon-label">書き出し</span>
              {showMoreMenu && (
                <div className="absolute top-full left-0 mt-2 bg-[var(--gf-surface-2)] shadow-2xl rounded-2xl border border-[var(--gf-border)] py-2 w-48 z-50" onClick={(e) => e.stopPropagation()}>
                  <div role="button" onClick={(e) => { e.stopPropagation(); handleExportMIDI(); setShowMoreMenu(false); }} className="px-5 py-3 hover:bg-[var(--gf-surface-3)] text-sm font-bold text-[var(--gf-text-dim)] flex items-center gap-3 transition-colors cursor-pointer"><Music size={16} /> MIDI</div>
                  <div role="button" onClick={(e) => { e.stopPropagation(); handleExportMusicXML(); setShowMoreMenu(false); }} className="px-5 py-3 hover:bg-[var(--gf-surface-3)] text-sm font-bold text-[var(--gf-text-dim)] flex items-center gap-3 transition-colors cursor-pointer"><FileCode size={16} /> MusicXML</div>
                  <div role="button" onClick={(e) => { e.stopPropagation(); handleExportText(); setShowMoreMenu(false); }} className="px-5 py-3 hover:bg-[var(--gf-surface-3)] text-sm font-bold text-[var(--gf-text-dim)] flex items-center gap-3 transition-colors cursor-pointer"><AlignLeft size={16} /> テキスト</div>
                </div>
              )}
            </div>
          </div>

          {/* 4. Main Grid content */}
          <div className={`flex-1 bg-[var(--gf-bg)] overflow-hidden ${viewMode === 'tab' ? '' : 'overflow-y-auto py-10 px-8'}`}>
            {viewMode === "chords" ? (
              <BeatGrid data={session.data} currentTime={currentTime - (latency / 1000)} onSeek={handleSeek} transpose={transpose - capo} onChordEdit={handleChordEdit} />
            ) : viewMode === "text" ? (
              <ChordLyricsView data={session.data} lyricsPhrases={session.lyricsPhrases} displayPhrases={session.displayPhrases} currentTime={currentTime - (latency / 1000)} onSeek={handleSeek} onChordEdit={handleChordEditByTime} onLyricEdit={handleLyricEdit} transpose={transpose - capo} title={session.fileName} artist={session.artist} />
            ) : (
              <TabView
                sessionId={session.id}
                currentTime={currentTime - (latency / 1000)}
                isPlaying={isPlaying}
                onSeek={handleSeek}
                isLooping={isLooping}
                loopRegion={loopRegion}
                transpose={transpose}
                capo={capo}
                playbackRate={playbackRate}
              />
            )}
          </div>
        </div>

        {/* Right Sidebar: Instrument Panel */}
        <div className="w-[280px] flex-shrink-0 border-l border-[var(--gf-border)] bg-[var(--gf-surface)] overflow-y-auto flex flex-col items-center py-6">
          <InstrumentPanel currentChord={currentChord} transpose={transpose - capo} instrument={instrument} />
        </div>

      </div>
    );
  };

  return (
    <div
      className="flex flex-col h-screen bg-[var(--gf-bg)] text-[var(--gf-text)] font-sans relative"
      onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}
    >
      <audio ref={audioRef} onEnded={() => setIsPlaying(false)} />

      {/* Drag & Drop Overlay */}
      {isDragging && (
        <div className="absolute inset-0 z-[100] flex flex-col items-center justify-center p-10 pointer-events-none m-4 rounded-3xl transition-all duration-300" style={{ background: 'rgba(99, 102, 241, 0.85)', backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)', border: '3px dashed rgba(255,255,255,0.3)' }}>
          <UploadCloud size={120} className="animate-bounce mb-8 text-white" />
          <h2 className="text-5xl font-black tracking-tighter mb-3 text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>Drop to analyze</h2>
          <p className="text-white/70 font-medium">音声ファイルまたはYouTubeリンク</p>
        </div>
      )}

      {/* Header */}
      <header className="h-20 nc-gradient-bg flex items-center justify-between px-8 text-[var(--nc-text)] shadow-xl z-30 flex-shrink-0 relative">
        <div className="flex items-center gap-8">
          <div className="font-black text-2xl tracking-tight cursor-pointer group flex items-center gap-2.5" style={{ fontFamily: "'Outfit', sans-serif" }} onClick={() => {
            if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ''; }
            clearInterval(pollInterval.current);
            if (sseRef.current) { sseRef.current.close(); sseRef.current = null; }
            setIsPlaying(false); setSession(null); setStatus(STATUS.IDLE);
            localStorage.removeItem('nextchord-last-session');
            setCurrentTime(0); setCurrentChord(''); setWaveform([]);
            setProgressMsg('Preparing...'); setTranspose(0); setViewMode('chords');
          }}>
            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'var(--nc-gradient-brand)' }}>
              <Music size={16} className="text-white" />
            </div>
            <span className="nc-logo-text group-hover:opacity-80 transition-opacity">NextChord</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Theme Toggle */}
          <button
            id="nc-theme-toggle"
            onClick={toggleTheme}
            className="w-9 h-9 rounded-lg flex items-center justify-center transition-all hover:bg-[var(--nc-surface-2)] group"
            title={theme === 'dark' ? 'ライトモードに切替' : 'ダークモードに切替'}
            style={{ border: '1px solid var(--nc-border)' }}
          >
            {theme === 'dark'
              ? <Sun size={16} className="text-[var(--nc-text-secondary)] group-hover:text-amber-400 transition-colors" />
              : <Moon size={16} className="text-[var(--nc-text-secondary)] group-hover:text-indigo-400 transition-colors" />
            }
          </button>
          <input ref={fileInputRef} id="nc-file-upload" name="audio-file" type="file" onChange={handleUpload} className="hidden" accept="audio/*" />
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 flex overflow-hidden relative">
        <div className="flex-1 overflow-y-auto scroll-smooth custom-scrollbar relative">

          {/* Welcome/Empty State */}
          {status === STATUS.IDLE && (
            <div className="h-full flex flex-col items-center justify-center p-12 text-center max-w-4xl mx-auto animate-in fade-in duration-1000 relative">
              {/* Subtle ambient glow */}
              <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[300px] pointer-events-none" style={{ background: 'radial-gradient(ellipse, rgba(99, 102, 241, 0.06) 0%, transparent 70%)' }} />

              {/* Hero Logo */}
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center mb-8 animate-brand-glow" style={{ background: 'var(--nc-gradient-brand)' }}>
                <Music size={32} className="text-white" />
              </div>
              <h1 className="text-7xl font-black nc-logo-text-hero tracking-tighter mb-6" style={{ fontFamily: "'Outfit', sans-serif" }}>NextChord</h1>
              <p className="text-[var(--nc-text-secondary)] font-medium mb-16 text-lg leading-relaxed max-w-lg">
                音楽を構造で捉える。AIが楽曲を瞬時に解析。 <br />
                <span className="text-[var(--nc-text-muted)]">コード譜・TAB・五線譜・音源分離</span>
              </p>

              <div className="w-full max-w-md relative z-10">
                <div
                  onClick={() => fileInputRef.current.click()}
                  className="p-10 nc-card hover:border-[rgba(99,102,241,0.3)] transition-all cursor-pointer group text-center"
                >
                  <div className="p-4 rounded-2xl w-fit mx-auto mb-5 group-hover:scale-110 transition-transform" style={{ background: 'var(--nc-primary-soft)', border: '1px solid rgba(99,102,241,0.12)' }}>
                    <UploadCloud size={40} className="text-[var(--nc-primary)]" />
                  </div>
                  <h4 className="font-bold text-[var(--nc-text)] text-xl mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>音源をドラッグ＆ドロップ</h4>
                  <p className="text-sm text-[var(--nc-text-muted)] mb-6">MP3, WAV, M4A または YouTubeリンク</p>
                  <div className="nc-btn-primary inline-flex text-[11px] uppercase tracking-[0.15em] px-5 py-2.5">
                    ファイルを選択
                  </div>
                </div>


                {/* Recent History Section */}
                {history.length > 0 && (
                  <div className="mt-14 text-left">
                    <h3 className="text-[10px] font-bold uppercase tracking-widest text-[var(--nc-text-muted)] mb-5 flex items-center gap-2">
                      <History size={12} /> 最近の解析
                    </h3>
                    <div className="grid grid-cols-1 gap-2">
                      {history.slice(0, 5).map((h) => (
                        <div
                          key={h.session_id}
                          onClick={() => restoreSession(h.session_id)}
                          className="flex items-center justify-between p-3.5 bg-[var(--nc-surface)] border border-[var(--nc-border)] rounded-xl hover:border-[rgba(99,102,241,0.2)] hover:bg-[var(--nc-surface-2)] transition-all cursor-pointer group"
                        >
                          <div className="flex items-center gap-3">
                            <div className="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-[11px] uppercase" style={{ background: 'var(--nc-primary-soft)', color: 'var(--nc-primary)' }}>
                              {h.key ? h.key.split(' ')[0] : 'N/A'}
                            </div>
                            <div>
                              <div className="font-semibold text-[var(--nc-text)] text-sm truncate max-w-[200px]">{h.filename}</div>
                              <div className="text-[10px] text-[var(--nc-text-ghost)] font-medium">{h.created_at || h.session_id}</div>
                            </div>
                          </div>
                          <ChevronRight size={16} className="text-[var(--nc-text-ghost)] group-hover:text-[var(--nc-primary)] group-hover:translate-x-0.5 transition-all" />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Processing state */}
          {(status === STATUS.PROCESSING || status === STATUS.UPLOADING) && (() => {
            const elapsed = Math.floor((Date.now() - (session?._startTime || Date.now())) / 1000);
            return (
              <div className="h-full flex flex-col items-center justify-center p-12 text-center animate-in fade-in duration-700">
                <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[400px] h-[400px] pointer-events-none" style={{ background: 'radial-gradient(ellipse, rgba(99, 102, 241, 0.08) 0%, transparent 60%)' }} />
                <div className="relative mb-10">
                  <div className="w-28 h-28 border-4 border-[var(--nc-surface-3)] rounded-full"></div>
                  <div className="w-28 h-28 rounded-full animate-spin absolute top-0 left-0" style={{ border: '4px solid transparent', borderTopColor: 'var(--nc-primary)', borderRightColor: 'var(--nc-secondary)', boxShadow: '0 0 20px rgba(99, 102, 241, 0.15)' }}></div>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Zap size={28} className="text-[var(--nc-primary)] animate-pulse" />
                  </div>
                </div>
                <h2 className="text-3xl font-black text-[var(--nc-text)] tracking-tight mb-3" style={{ fontFamily: "'Outfit', sans-serif" }}>解析中...</h2>
                <p className="text-[var(--nc-primary)] font-semibold text-sm mb-2 min-h-[1.5em] transition-all">{progressMsg}</p>
                <p className="text-[var(--nc-text-ghost)] text-[10px] font-medium uppercase tracking-[0.2em]">AIが楽曲を並列解析しています</p>
              </div>
            );
          })()}

          {/* Failed state — Redesigned */}
          {status === STATUS.FAILED && (
            <div className="h-full flex items-center justify-center p-12 animate-in fade-in duration-500">
              <div className="nc-error-screen">
                <div className="nc-error-icon-container">
                  <div className="nc-error-icon-bg" />
                  <div className="nc-error-icon">
                    <AlertTriangle size={32} />
                  </div>
                </div>
                <h2 className="nc-error-title">解析に失敗しました</h2>
                <p className="nc-error-message">
                  処理中に問題が発生しました。<br />ファイル形式やネットワーク接続を確認してください。
                </p>
                <div className="nc-error-detail">
                  {progressMsg || "不明なエラー"}
                </div>
                <div className="nc-error-actions">
                  <button
                    onClick={() => fileInputRef.current.click()}
                    className="nc-btn-primary px-6 py-3 text-sm"
                  >
                    再アップロード
                  </button>
                  <button
                    onClick={() => {
                      if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ''; }
                      setSession(null); setStatus(STATUS.IDLE); setProgressMsg('Preparing...');
                      localStorage.removeItem('nextchord-last-session');
                    }}
                    className="nc-btn-secondary px-6 py-3 text-sm"
                  >
                    ホームに戻る
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Result view */}
          {
            renderResultView()
          }

        </div>
      </main >

      {/* Toast */}
      {
        toast && (
          <div className={`nc-toast ${toast.type === 'error' ? 'nc-toast-error' : 'nc-toast-success'}`}>
            {toast.type === 'error' ? <X size={18} /> : <Check size={18} />}
            {toast.message}
          </div>
        )
      }

      {/* Text View Modal */}
      {
        showTextModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in">
            <div className="bg-[var(--gf-surface)] w-full max-w-3xl h-[80vh] rounded-3xl shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 border border-[var(--gf-border)]">
              <div className="p-6 border-b border-[var(--gf-border)] flex items-center justify-between bg-[var(--gf-surface-2)]">
                <h3 className="text-xl font-black text-[var(--gf-text)] flex items-center gap-2">
                  <FileText size={20} className="text-[var(--gf-amber)]" />
                  Text Score
                </h3>
                <div className="flex items-center gap-2">
                  <button onClick={() => { navigator.clipboard.writeText(textContent); showToast('Copied to clipboard'); }} className="px-4 py-2 bg-[var(--gf-surface)] border border-[var(--gf-border)] rounded-xl text-sm font-bold text-[var(--gf-text-dim)] hover:bg-[var(--gf-amber-glow)] hover:text-[var(--gf-amber)] hover:border-[var(--gf-amber)]/30 transition-all">
                    Copy
                  </button>
                  <button onClick={() => setShowTextModal(false)} className="p-2 hover:bg-[var(--gf-surface-3)] rounded-full transition-all text-[var(--gf-text-dim)]">
                    <X size={20} />
                  </button>
                </div>
              </div>
              <div className="flex-1 overflow-auto p-8 bg-[var(--gf-surface)] font-mono text-sm leading-relaxed whitespace-pre overflow-x-auto text-[var(--gf-text)]">
                {textContent || "Loading..."}
              </div>
            </div>
          </div>
        )
      }
    </div >
  );
}
