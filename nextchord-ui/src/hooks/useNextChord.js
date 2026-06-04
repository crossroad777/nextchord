import { useState, useEffect, useRef, useCallback } from "react";
import { transposeChord, calculateBestCapo } from "../utils/musicUtils";

export const getApiBase = () => {
  return localStorage.getItem('nextchord-api-base') || (import.meta.env.VITE_API_URL !== undefined ? import.meta.env.VITE_API_URL : "http://localhost:8000");
};

export const STATUS = { IDLE: "idle", UPLOADING: "uploading", PROCESSING: "processing", COMPLETED: "completed", FAILED: "failed" };

export function useNextChord() {
  const [status, setStatus] = useState(STATUS.IDLE);
  const [progressMsg, setProgressMsg] = useState("Preparing...");
  const [stepsDone, setStepsDone] = useState(0);
  const [session, setSession] = useState(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [currentChord, setCurrentChord] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);

  const [viewMode, setViewMode] = useState("text");

  // Setlist State
  const [setlistData, setSetlistData] = useState([]);
  const [setlistName, setSetlistName] = useState("");


  // Premium Controls State
  const [transpose, setTranspose] = useState(0);
  const [latency, setLatency] = useState(-250);
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
  const [recommendedCapo, setRecommendedCapo] = useState(0);
  const [tuning, setTuning] = useState('standard');
  const [noiseGate, setNoiseGate] = useState(null);
  const [isRetuning, setIsRetuning] = useState(false);
  const [history, setHistory] = useState([]);
  const [scoreVersion, setScoreVersion] = useState(0);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [showTechniques, setShowTechniques] = useState(true);

  // --- Undo/Redo 履歴 ---
  const editHistoryRef = useRef([]);   // [{data, displayPhrases}]
  const editRedoRef = useRef([]);
  const MAX_UNDO = 50;

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

      // 曲別設定の復元 (カポ・転調・再生速度・音量)
      try {
        const songSettings = JSON.parse(localStorage.getItem('nextchord-song-settings') || '{}');
        const saved = songSettings[session.id];
        if (saved) {
          if (saved.capo !== undefined) setCapo(saved.capo);
          if (saved.transpose !== undefined) setTranspose(saved.transpose);
          if (saved.playbackRate !== undefined) setPlaybackRate(saved.playbackRate);
          if (saved.volume !== undefined) setVolume(saved.volume);
        } else {
          // 新しい曲: デフォルトにリセット
          setCapo(0);
          setTranspose(0);
          setPlaybackRate(1.0);
          setVolume(100);
        }
      } catch (e) {
        console.error('Song settings load error:', e);
      }
    }
  }, [session?.id]);

  // 曲別設定の自動保存 (デバウンス: 500ms)
  useEffect(() => {
    if (!session?.id) return;
    const timer = setTimeout(() => {
      try {
        const songSettings = JSON.parse(localStorage.getItem('nextchord-song-settings') || '{}');
        songSettings[session.id] = { capo, transpose, playbackRate, volume };
        // 古いエントリを制限 (最大100曲)
        const keys = Object.keys(songSettings);
        if (keys.length > 100) {
          keys.slice(0, keys.length - 100).forEach(k => delete songSettings[k]);
        }
        localStorage.setItem('nextchord-song-settings', JSON.stringify(songSettings));
      } catch (e) {
        console.error('Song settings save error:', e);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [session?.id, capo, transpose, playbackRate, volume]);

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
    try {
      const raw = JSON.parse(localStorage.getItem('nextchord-favorites') || '[]');
      // 後方互換: string[] → {id, folder}[] に変換
      if (Array.isArray(raw) && raw.length > 0 && typeof raw[0] === 'string') {
        const migrated = raw.map(id => ({ id, folder: '' }));
        localStorage.setItem('nextchord-favorites', JSON.stringify(migrated));
        return migrated;
      }
      return raw;
    } catch { return []; }
  });
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [toasts, setToasts] = useState([]);
  const toastIdRef = useRef(0);

  const showToast = (message, type = 'success', duration = 3000) => {
    const id = ++toastIdRef.current;
    setToasts(prev => [...prev.slice(-4), { id, message, type, duration }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, duration);
  };
  const dismissToast = (id) => { setToasts(prev => prev.filter(t => t.id !== id)); };

  const audioRef = useRef(null);
  const canvasRef = useRef(null);
  const fileInputRef = useRef(null);
  const pollInterval = useRef(null);
  const sseRef = useRef(null);
  const timelineProgressRef = useRef(null);
  const timelineHandleRef = useRef(null);
  const hasCleanAudioRef = useRef(false);
  const isSeparatingRef = useRef(false);

  // hasCleanAudio / isSeparating の最新値をrefに同期（setInterval内で参照するため）
  useEffect(() => { hasCleanAudioRef.current = hasCleanAudio; }, [hasCleanAudio]);
  useEffect(() => { isSeparatingRef.current = isSeparating; }, [isSeparating]);

  // 書き出しメニュー外クリックで閉じる
  useEffect(() => {
    if (!showMoreMenu) return;
    const handleClickOutside = () => setShowMoreMenu(false);
    const timer = setTimeout(() => document.addEventListener('click', handleClickOutside), 0);
    return () => { clearTimeout(timer); document.removeEventListener('click', handleClickOutside); };
  }, [showMoreMenu]);

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${getApiBase()}/sessions`);
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
    setStepsDone(0);
    setProgressMsg("セッションを復元中...");
    try {
      const res = await fetch(`${getApiBase()}/result/${sid}`);
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
        barPositions: result.bar_positions || null,
        audioUrl: null,  // OOM防止: 最初はnull
        hasNotes: result.has_notes
      });
      setStatus(STATUS.COMPLETED);
      try {
        const wRes = await fetch(`${getApiBase()}/result/${sid}/waveform`);
        const wData = await wRes.json();
        setWaveform(wData.peaks || []);
      } catch { }
      // 音声URLは500ms遅延でセット（レンダリング完了を待つ → OOM防止）
      setTimeout(() => {
        setSession(prev => prev ? {
          ...prev,
          audioUrl: prev.audioUrl || `${getApiBase()}/files/${sid}/playback.mp3`
        } : prev);
      }, 500);
    } catch (err) {
      setStatus(STATUS.FAILED);
      setProgressMsg("セッションの復元に失敗しました。サーバーがリロードされた可能性があります。");
    }
  };

  // Audio Sync Loop — 高速DOM更新 + 低速React更新
  useEffect(() => {
    let anim;
    let lastStateTime = 0;
    const tick = () => {
      if (audioRef.current) {
        const time = audioRef.current.currentTime;
        const duration = audioRef.current.duration || 1;
        if (isLooping && loopRegion.start !== null && loopRegion.end !== null) {
          if (time >= loopRegion.end) {
            audioRef.current.currentTime = loopRegion.start;
            lastStateTime = loopRegion.start;
            setCurrentTime(loopRegion.start);
            anim = requestAnimationFrame(tick);
            return;
          }
        }
        // 60fps: プログレスバーを直接DOM操作（Reactを通さない）
        const pct = (time / duration) * 100;
        if (timelineProgressRef.current) timelineProgressRef.current.style.width = `${pct}%`;
        if (timelineHandleRef.current) timelineHandleRef.current.style.left = `${pct}%`;
        // 60fps: 波形Canvasも直接更新
        if (canvasRef.current && waveform.length > 0) {
          drawWaveform(canvasRef.current, waveform, time, duration);
        }
        // 5Hz: React state更新（コードハイライト等）
        if (Math.abs(time - lastStateTime) > 0.15) {
          lastStateTime = time;
          setCurrentTime(time);
        }
        anim = requestAnimationFrame(tick);
      }
    };
    if (isPlaying) anim = requestAnimationFrame(tick);
    else cancelAnimationFrame(anim);
    return () => cancelAnimationFrame(anim);
  }, [isPlaying, isLooping, loopRegion, waveform]);

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
      const first = session.result.structured_data.find(b => b.chord && b.chord !== 'N.C.');
      if (first) setCurrentChord(first.chord);
    }
  }, [currentTime, session?.result?.structured_data, latency]);

  // Waveform: 停止中のみReact経由で描画（再生中はtick内で直接描画）
  useEffect(() => {
    if (!isPlaying && waveform.length > 0 && canvasRef.current && audioRef.current) {
      drawWaveform(canvasRef.current, waveform, currentTime, audioRef.current.duration);
    }
  }, [currentTime, waveform, isPlaying]);

  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = playbackRate; }, [playbackRate]);
  useEffect(() => { if (audioRef.current) audioRef.current.volume = volume / 100; }, [volume]);

  const sessionAudioUrl = session?.audioUrl;
  useEffect(() => {
    if (sessionAudioUrl && audioRef.current) {
      const src = vocalCancel && hasCleanAudio ? sessionAudioUrl.replace('playback.mp3', 'clean.wav').replace('converted.wav', 'clean.wav') : sessionAudioUrl;
      if (audioRef.current.src !== src) {
        const t = audioRef.current.currentTime;
        audioRef.current.src = src;
        audioRef.current.currentTime = t;
        if (isPlaying) audioRef.current.play();
      }
    }
  }, [vocalCancel, hasCleanAudio, sessionAudioUrl]);

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

  // --- SSE-based status streaming ---
  const handleStatusCompleted = async (sid) => {
    try {
      const resData = await fetch(`${getApiBase()}/result/${sid}`);
      const result = await resData.json();
      // まず結果データのみ設定（audioUrlはまだ設定しない → レンダリング優先）
      setSession(prev => ({
        ...prev,
        result,
        data: result.structured_data,
        lyricsPhrases: result.lyrics_phrases || [],
        displayPhrases: result.display_phrases || [],
        barPositions: result.bar_positions || null,
        audioUrl: null,  // 最初はnull（レンダリング後に遅延ロード）
        hasNotes: result.has_notes,
        fileName: result.filename || prev?.fileName,
        artist: result.artist || prev?.artist
      }));
      setStatus(STATUS.COMPLETED);
      // 波形データ取得
      try {
        const wRes = await fetch(`${getApiBase()}/result/${sid}/waveform`);
        const wData = await wRes.json();
        setWaveform(wData.peaks || []);
      } catch { }
      // 音声URLは500ms遅延でセット（レンダリング完了を待つ → OOM防止）
      setTimeout(() => {
        setSession(prev => prev ? {
          ...prev,
          audioUrl: prev.audioUrl || `${getApiBase()}/files/${sid}/playback.mp3`
        } : prev);
      }, 500);
    } catch (err) {
      console.error("[SSE] Failed to fetch result:", err);
      setStatus(STATUS.FAILED);
      setProgressMsg("結果の取得に失敗しました。");
    }
  };

  const startStatusStream = (sid) => {
    if (sseRef.current) { sseRef.current.close(); sseRef.current = null; }
    if (pollInterval.current) { clearInterval(pollInterval.current); pollInterval.current = null; }

    const es = new EventSource(`${getApiBase()}/status/${sid}/stream`);
    sseRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setProgressMsg(data.progress || "Analyzing...");
        if (typeof data.steps_done === 'number') setStepsDone(data.steps_done);
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
      pollInterval.current = setInterval(() => checkStatusLegacy(sid), 2000);
      // Try to reconnect SSE after 5 seconds
      setTimeout(() => {
        if (pollInterval.current && !sseRef.current) {
          clearInterval(pollInterval.current); pollInterval.current = null;
          console.log("[SSE] Attempting reconnect...");
          startStatusStream(sid);
        }
      }, 5000);
    };
  };

  // Legacy polling fallback
  const pollErrorCount = useRef(0);
  const checkStatusLegacy = async (sid) => {
    try {
      const res = await fetch(`${getApiBase()}/status/${sid}`);
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
      if (typeof data.steps_done === 'number') setStepsDone(data.steps_done);
      if (data.filename || data.artist) {
        setSession(prev => prev ? { ...prev, ...(data.filename && { fileName: data.filename }), ...(data.artist && { artist: data.artist }) } : prev);
      }
      if (data.status === "completed") { clearInterval(pollInterval.current); handleStatusCompleted(sid); }
      else if (data.status === "failed") { clearInterval(pollInterval.current); setProgressMsg(data.error || "分析に失敗しました"); setStatus(STATUS.FAILED); }
    } catch { pollErrorCount.current++; if (pollErrorCount.current >= 5) { clearInterval(pollInterval.current); setStatus(STATUS.FAILED); } }
  };

  const checkSeparationStatus = async (sid) => {
    try {
      const res = await fetch(`${getApiBase()}/status/separation/${sid}`);
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
      await fetch(`${getApiBase()}/separate/${session.id}`, { method: "POST" });
      const sepPoll = setInterval(() => {
        checkSeparationStatus(session.id);
        if (hasCleanAudioRef.current || !isSeparatingRef.current) clearInterval(sepPoll);
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
    let file = null;
    if (ev?.target?.files?.[0]) {
      file = ev.target.files[0];
    } else if (ev instanceof File) {
      file = ev;
    } else if (ev?.name && (ev?.size !== undefined)) {
      file = ev;
    }

    if (!file || typeof file.name !== 'string') {
      console.warn("[handleUpload] No valid file found in event:", ev);
      return;
    }

    const isAudio = file.name.match(/\.(mp3|wav|m4a|flac)$/i);

    if (!isAudio) {
      if (file.size > 256000) {
        setStatus(STATUS.FAILED);
        setProgressMsg("サポートされていない形式です (MP3, WAV, M4A, FLAC対応)。");
        return;
      }

      const reader = new FileReader();
      reader.onload = (ev) => {
        const content = ev.target.result;
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

    setStatus(STATUS.UPLOADING);
    setProgressMsg("Uploading...");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`${getApiBase()}/upload`, { method: "POST", body: formData });
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Upload failed");
      }
      const data = await res.json();
      setSession({ id: data.session_id, fileName: file.name, audioUrl: `${getApiBase()}${data.audio_url}` });
      setHasCleanAudio(false);
      setIsSeparating(false);
      setStatus(STATUS.PROCESSING);
      setStepsDone(0);
      pollInterval.current = setInterval(() => checkStatusLegacy(data.session_id), 1500);
    } catch (err) {
      setStatus(STATUS.FAILED);
      setProgressMsg(err.message || "アップロードに失敗しました");
    }
  };


  const startSetlist = async (folderName, items) => {
    if (!items || items.length === 0) return;
    setStatus(STATUS.PROCESSING);
    setProgressMsg(`セットリストを構築中...`);
    
    try {
      const results = await Promise.all(items.map(async (item) => {
        const res = await fetch(`${getApiBase()}/result/${item.id}`);
        if (!res.ok) throw new Error(`Failed to load ${item.id}`);
        const data = await res.json();
        const historyItem = history.find(h => h.session_id === item.id) || {};
        return {
          id: item.id,
          result: data,
          filename: historyItem.filename || "Unknown",
          artist: historyItem.artist || "",
        };
      }));
      setSetlistData(results);
      setSetlistName(folderName);
      setStatus("setlist_view");
    } catch (e) {
      console.error(e);
      setStatus(STATUS.FAILED);
      setProgressMsg("セットリストの読み込みに失敗しました");
    }
  };

  const [ytUrl, setYtUrl] = useState("");

  const handleYouTubeUpload = async (urlToUse = ytUrl) => {
    if (!urlToUse) return;
    setStatus(STATUS.PROCESSING);
    setStepsDone(0);
    setProgressMsg("YouTube音声を解析中...");
    try {
      const res = await fetch(`${getApiBase()}/upload/youtube`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlToUse })
      });
      if (!res.ok) throw new Error("YouTube upload failed");
      const data = await res.json();
      setSession({
        id: data.session_id,
        fileName: "YouTube Video",
        audioUrl: null
      });
      setHasCleanAudio(false);
      setIsSeparating(false);
      pollInterval.current = setInterval(() => checkStatusLegacy(data.session_id), 1500);
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

    const dt = e.dataTransfer;
    let droppedText = dt.getData("text/plain") || dt.getData("text/uri-list") || dt.getData("text");

    if (droppedText && droppedText.includes("\n")) droppedText = droppedText.split("\n")[0].trim();

    if (droppedText && (droppedText.includes("youtube.com") || droppedText.includes("youtu.be"))) {
      handleYouTubeUpload(droppedText.trim());
      return;
    }

    const files = dt.files;
    if (files?.[0]) {
      handleUpload(files[0]);
      return;
    }
  };



  const isFavorite = session?.id && favorites.some(x => x.id === session.id);
  const toggleFavorite = () => {
    let f = isFavorite
      ? favorites.filter(x => x.id !== session.id)
      : [...favorites, { id: session.id, folder: '' }];
    setFavorites(f);
    localStorage.setItem('nextchord-favorites', JSON.stringify(f));
  };

  // --- お気に入りフォルダ管理 ---
  const createFolder = (name) => {
    if (!name || !name.trim()) return;
    // フォルダは favorites 内の folder フィールドで管理
    // 空のフォルダを作るため、メタエントリを追加
    const trimmed = name.trim();
    const existing = favorites.some(x => x.id === `__folder__${trimmed}`);
    if (existing) return;
    const f = [...favorites, { id: `__folder__${trimmed}`, folder: trimmed }];
    setFavorites(f);
    localStorage.setItem('nextchord-favorites', JSON.stringify(f));
  };

  const deleteFolder = (name) => {
    // フォルダ内の曲を「未分類」に移動し、フォルダメタエントリを削除
    const f = favorites
      .map(x => x.folder === name && !x.id.startsWith('__folder__') ? { ...x, folder: '' } : x)
      .filter(x => x.id !== `__folder__${name}`);
    setFavorites(f);
    localStorage.setItem('nextchord-favorites', JSON.stringify(f));
  };

  const moveToFolder = (sessionId, folderName) => {
    const f = favorites.map(x => x.id === sessionId ? { ...x, folder: folderName } : x);
    setFavorites(f);
    localStorage.setItem('nextchord-favorites', JSON.stringify(f));
  };

  const getFolders = () => {
    const folderSet = new Set();
    favorites.forEach(x => {
      if (x.id.startsWith('__folder__')) folderSet.add(x.folder);
      else if (x.folder) folderSet.add(x.folder);
    });
    return Array.from(folderSet);
  };

  const getFavoritesByFolder = (folder) => {
    return favorites.filter(x => x.folder === folder && !x.id.startsWith('__folder__'));
  };

  // --- 設定エクスポート / インポート ---
  const exportSettings = () => {
    const settings = {};
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('nextchord-')) {
        try { settings[key] = JSON.parse(localStorage.getItem(key)); }
        catch { settings[key] = localStorage.getItem(key); }
      }
    }
    return JSON.stringify(settings, null, 2);
  };

  const importSettings = (jsonString) => {
    try {
      const settings = JSON.parse(jsonString);
      if (typeof settings !== 'object' || settings === null) throw new Error('Invalid format');
      Object.entries(settings).forEach(([key, value]) => {
        if (key.startsWith('nextchord-')) {
          localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
        }
      });
      // 復元: favorites
      if (settings['nextchord-favorites']) {
        const raw = settings['nextchord-favorites'];
        const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
        if (Array.isArray(parsed) && parsed.length > 0 && typeof parsed[0] === 'string') {
          setFavorites(parsed.map(id => ({ id, folder: '' })));
        } else {
          setFavorites(parsed);
        }
      }
      // 復元: テーマ
      if (settings['nextchord-theme']) {
        setTheme(settings['nextchord-theme']);
      }
      showToast('設定をインポートしました');
    } catch (e) {
      console.error('Import settings error:', e);
      showToast('設定のインポートに失敗しました', 'error');
    }
  };

  const handleShare = async () => {
    if (!session?.id) return;
    try { await navigator.clipboard.writeText(window.location.origin + "?session=" + session.id); showToast('Link copied!'); }
    catch { showToast('Share failed', 'error'); }
  };

  const handleExportPDF = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${getApiBase()}/export/${session.id}/pdf`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `nextchord_${session.id}.pdf`; a.click();
    } catch { showToast('PDF export failed', 'error'); }
  };

  const handleExportMIDI = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${getApiBase()}/export/${session.id}/midi`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `nextchord_${session.id}.mid`; a.click();
    } catch { showToast('MIDI export failed', 'error'); }
  };

  const handleExportMusicXML = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${getApiBase()}/export/${session.id}/musicxml`);
      if (!res.ok) throw new Error("No MusicXML");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `nextchord_${session.id}.musicxml`; a.click();
    } catch { showToast('MusicXML export failed', 'error'); }
  };

  const handleExportText = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${getApiBase()}/result/${session.id}/text`);
      if (!res.ok) throw new Error("No Text");
      const text = await res.text();
      const blob = new Blob([text], { type: 'text/plain; charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `${session.fileName || 'nextchord'}.txt`; a.click();
    } catch { showToast('Text export failed', 'error'); }
  };

  const handleExportGP5 = async () => {
    if (!session?.id) return;
    try {
      const res = await fetch(`${getApiBase()}/export/${session.id}/gp5`);
      if (!res.ok) throw new Error("No GP5");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `${session.fileName || 'nextchord'}.gp5`; a.click();
    } catch { showToast('GP5 export failed', 'error'); }
  };

  const [showTextModal, setShowTextModal] = useState(false);
  const [textContent, setTextContent] = useState("");

  const handleViewText = async () => {
    if (!session?.id) return;
    setShowTextModal(true);
    setTextContent("Loading...");
    try {
      const res = await fetch(`${getApiBase()}/result/${session.id}/text`);
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

  // --- Retune API ---
  const handleRetune = async (newTuning, newCapo, newNoiseGate) => {
    if (!session?.id) return;
    setIsRetuning(true);
    try {
      const body = {
        tuning: newTuning ?? tuning,
        capo: newCapo ?? capo,
      };
      if (newNoiseGate !== undefined && newNoiseGate !== null) {
        body.noise_gate = newNoiseGate;
      } else if (noiseGate !== null) {
        body.noise_gate = noiseGate;
      }
      const res = await fetch(`${getApiBase()}/result/${session.id}/retune`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Retune failed');
      // AlphaTabリロード
      setScoreVersion(prev => prev + 1);
      const tuningLabels = {
        standard: 'レギュラー',
        half_down: '半音下げ',
        drop_d: 'ドロップD',
        open_g: 'オープンG',
        open_d: 'オープンD',
        dadgad: 'DADGAD'
      };
      showToast(`🎸 リチューンしました (${tuningLabels[body.tuning] || body.tuning}, capo ${body.capo})`);
    } catch (e) {
      console.error('Retune error:', e);
      showToast('❌ リチューンに失敗しました', 'error');
    } finally {
      setIsRetuning(false);
    }
  };

  const handleTuningChange = (newTuning) => {
    setTuning(newTuning);
    handleRetune(newTuning, capo, noiseGate);
  };

  const handleCapoChange = (newCapo) => {
    setCapo(newCapo);
    handleRetune(tuning, newCapo, noiseGate);
    // カポ変更は曲別設定に自動保存される (useEffect経由)
  };

  const handleTranspose = (delta) => {
    const newVal = Math.max(-12, Math.min(12, transpose + delta));
    setTranspose(newVal);
    showToast(`転調を ${newVal > 0 ? '+' : ''}${newVal} に設定しました`);
  };

  // --- 編集前の状態をアンドゥ履歴に保存 ---
  const pushUndo = () => {
    if (!session) return;
    editHistoryRef.current.push({
      data: session.data ? JSON.parse(JSON.stringify(session.data)) : null,
      displayPhrases: session.displayPhrases ? JSON.parse(JSON.stringify(session.displayPhrases)) : null,
    });
    if (editHistoryRef.current.length > MAX_UNDO) editHistoryRef.current.shift();
    editRedoRef.current = []; // 新しい編集でredoをクリア
  };

  const handleUndo = useCallback(() => {
    if (editHistoryRef.current.length === 0) {
      showToast('これ以上アンドゥできません', 'info');
      return;
    }
    // 現在の状態をredoスタックに保存
    if (session) {
      editRedoRef.current.push({
        data: session.data ? JSON.parse(JSON.stringify(session.data)) : null,
        displayPhrases: session.displayPhrases ? JSON.parse(JSON.stringify(session.displayPhrases)) : null,
      });
    }
    const prev = editHistoryRef.current.pop();
    setSession(s => ({
      ...s,
      data: prev.data || s.data,
      displayPhrases: prev.displayPhrases || s.displayPhrases,
    }));
    showToast('↩ アンドゥしました');
    // サーバーにも反映
    if (prev.data) saveChordEdits(prev.data);
    if (prev.displayPhrases) saveLyricEdits(prev.displayPhrases);
  }, [session?.data, session?.displayPhrases]);

  const handleRedo = useCallback(() => {
    if (editRedoRef.current.length === 0) {
      showToast('リドゥできません', 'info');
      return;
    }
    // 現在の状態をundoスタックに保存
    if (session) {
      editHistoryRef.current.push({
        data: session.data ? JSON.parse(JSON.stringify(session.data)) : null,
        displayPhrases: session.displayPhrases ? JSON.parse(JSON.stringify(session.displayPhrases)) : null,
      });
    }
    const next = editRedoRef.current.pop();
    setSession(s => ({
      ...s,
      data: next.data || s.data,
      displayPhrases: next.displayPhrases || s.displayPhrases,
    }));
    showToast('↪ リドゥしました');
    if (next.data) saveChordEdits(next.data);
    if (next.displayPhrases) saveLyricEdits(next.displayPhrases);
  }, [session?.data, session?.displayPhrases]);

  // Ctrl+Z / Ctrl+Y キーボードショートカット
  useEffect(() => {
    const handleUndoKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
      } else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
        e.preventDefault();
        handleRedo();
      }
    };
    window.addEventListener('keydown', handleUndoKey);
    return () => window.removeEventListener('keydown', handleUndoKey);
  }, [handleUndo, handleRedo]);

  const handleChordEdit = (index, newChord) => {
    if (!session?.data) return;
    pushUndo();
    const newData = [...session.data];
    if (newChord === '' || newChord === 'N.C.') {
      newData[index] = { ...newData[index], chord: 'N.C.', _edited: true };
      showToast('コードを削除しました');
    } else {
      newData[index] = { ...newData[index], chord: newChord, _edited: true };
      showToast(`コードを "${newChord}" に変更しました`);
    }
    setSession(prev => ({ ...prev, data: newData }));
    saveChordEdits(newData);
  };

  const handleChordEditByTime = (time, newChord) => {
    if (!session?.data) return;
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

  const saveChordEdits = async (newData) => {
    if (!session?.id) return;
    try {
      await fetch(`${getApiBase()}/result/${session.id}/chords`, {
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

  const handleLyricEdit = (startTime, newText) => {
    if (!session?.displayPhrases) return;
    pushUndo();
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

  const saveLyricEdits = async (phrases) => {
    if (!session?.id) return;
    try {
      await fetch(`${getApiBase()}/result/${session.id}/lyrics`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_phrases: phrases })
      });
    } catch (e) {
      console.warn('Lyric save failed:', e);
    }
  };

  const handleRegenerateScore = async () => {
    if (!session?.id || isRegenerating) return;
    setIsRegenerating(true);
    try {
      const res = await fetch(`${getApiBase()}/result/${session.id}/regenerate-musicxml`, { method: 'POST' });
      if (!res.ok) throw new Error('MusicXML regeneration failed');
      setScoreVersion(prev => prev + 1);
      showToast('✅ 譜面を再生成しました');
    } catch (e) {
      console.error('Regenerate failed:', e);
      showToast('❌ 譜面の再生成に失敗しました');
    } finally {
      setIsRegenerating(false);
    }
  };

  const getTransposedKey = (originalKey, semitones) => {
    if (!originalKey) return "Unknown";
    const [root, mode] = originalKey.split(" ");
    return transposeChord(root, semitones) + (mode ? " " + mode : "");
  };

  const handleReset = () => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ''; }
    clearInterval(pollInterval.current);
    if (sseRef.current) { sseRef.current.close(); sseRef.current = null; }
    setIsPlaying(false); setSession(null); setStatus(STATUS.IDLE);
    localStorage.removeItem('nextchord-last-session');
    setCurrentTime(0); setCurrentChord(''); setWaveform([]);
    setProgressMsg('Preparing...'); setTranspose(0); setViewMode('text');
  };

  const handleGoHome = () => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ''; }
    setSession(null); setStatus(STATUS.IDLE); setProgressMsg('Preparing...');
    localStorage.removeItem('nextchord-last-session');
  };

  return {
    // Status
    status, progressMsg, stepsDone, session,
    // Playback
    currentTime, currentChord, isPlaying, setIsPlaying, audioRef,
    togglePlay, handleStop, handleSeek,
    // View
    viewMode, setViewMode,
    // Controls
    transpose, latency, setLatency,
    playbackRate, setPlaybackRate,
    volume, setVolume,
    vocalCancel, setVocalCancel,
    isLooping, loopRegion, toggleLoop,
    instrument, setInstrument,
    capo, setCapo: handleCapoChange, recommendedCapo,
    // Separation
    isSeparating, separationProgress, hasCleanAudio, handleSeparate,
    // Waveform
    waveform, canvasRef,
    // Drag & drop
    isDragging, handleDragOver, handleDragLeave, handleDrop,
    // History
    history, restoreSession,
    // Score
    scoreVersion, isRegenerating, handleRegenerateScore,
    // Theme
    theme, toggleTheme,
    // Favorites
    favorites, isFavorite, toggleFavorite,
    createFolder, deleteFolder, moveToFolder, getFolders, getFavoritesByFolder,
    // Settings export/import
    exportSettings, importSettings,
    setlistData, setlistName, startSetlist,
    // Menu
    showMoreMenu, setShowMoreMenu,
    // Toast (stacking)
    toasts, dismissToast,
    // Refs
    fileInputRef, timelineProgressRef, timelineHandleRef,
    // Upload
    handleUpload, ytUrl, setYtUrl, handleYouTubeUpload,
    // Export
    handleExportPDF, handleExportMIDI, handleExportMusicXML, handleExportText, handleExportGP5,
    // Share
    handleShare,
    // Text modal
    showTextModal, setShowTextModal, textContent, handleViewText,
    // Waveform click
    handleWaveformClick,
    // Transpose
    handleTranspose,
    // Chord / Lyric edits
    handleChordEdit, handleChordEditByTime, handleLyricEdit,
    // Key helper
    getTransposedKey,
    // Navigation
    handleReset, handleGoHome,
    // Polling ref (for cleanup)
    pollInterval, sseRef,
    // Tuning / Retune
    tuning, setTuning: handleTuningChange,
    isRetuning, noiseGate,
    handleCapoChange,
    // Show toast helper
    showToast,
    // Show techniques
    showTechniques, setShowTechniques,
  };
}
