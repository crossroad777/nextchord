import React, { useState, useCallback } from "react";
import {
  Play, Pause, Share2, Heart, MoreHorizontal,
  ChevronRight, ChevronLeft, Clock, Square,
  Repeat, Guitar, Music, Layout, FileCode, AlignLeft,
  Download, RefreshCw, ChevronDown, Zap, Disc, FileText,
  Volume2, VolumeX
} from 'lucide-react';
import { Metronome } from './Metronome';

const TUNINGS = [
  { value: 'standard', label: 'Standard' },
  { value: 'half_down', label: 'Half Down' },
  { value: 'drop_d', label: 'Drop D' },
  { value: 'open_g', label: 'Open G' },
  { value: 'open_d', label: 'Open D' },
  { value: 'dadgad', label: 'DADGAD' },
];

/** 音量コントロール */
function VolumeControl({ audioRef }) {
    const [volume, setVolume] = useState(1);
    const [muted, setMuted] = useState(false);

    const handleVolumeChange = useCallback((e) => {
        const v = parseFloat(e.target.value);
        setVolume(v);
        setMuted(v === 0);
        if (audioRef.current) audioRef.current.volume = v;
    }, [audioRef]);

    const toggleMute = useCallback(() => {
        const newMuted = !muted;
        setMuted(newMuted);
        if (audioRef.current) audioRef.current.volume = newMuted ? 0 : volume || 1;
    }, [muted, volume, audioRef]);

    const displayVol = muted ? 0 : Math.round(volume * 100);
    const Icon = muted || volume === 0 ? VolumeX : Volume2;

    return (
        <div className="w-[120px] flex-shrink-0 flex flex-col justify-center gap-1">
            <div className="flex items-center justify-between">
                <button
                    onClick={toggleMute}
                    className="text-[8px] font-black text-[var(--gf-text-dim)] uppercase tracking-wider flex items-center gap-1 hover:text-[var(--gf-text)] transition-colors"
                    aria-label={muted ? 'Unmute' : 'Mute'}
                >
                    <Icon size={10} /> Volume
                </button>
                <span className="text-[9px] font-mono font-black text-[var(--gf-primary)]">{displayVol}%</span>
            </div>
            <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={muted ? 0 : volume}
                onChange={handleVolumeChange}
                className="w-full h-1 bg-[var(--gf-surface-3)] rounded-lg appearance-none cursor-pointer accent-[var(--gf-primary)]"
            />
        </div>
    );
}

export function ResultHeader({
  session,
  // Song info
  getTransposedKey,
  transpose,
  capo,
  isFavorite,
  // Actions
  handleShare,
  toggleFavorite,
  // Playback
  isPlaying,
  togglePlay,
  handleStop,
  currentTime,
  audioRef,
  handleWaveformClick,
  // Latency
  latency,
  setLatency,
  // Ribbon: Speed
  playbackRate,
  setPlaybackRate,
  // Ribbon: Loop
  isLooping,
  toggleLoop,
  // Ribbon: Capo
  setCapo,
  // Ribbon: Transpose
  handleTranspose,
  // Ribbon: Instrument
  instrument,
  setInstrument,
  // Ribbon: View Mode
  viewMode,
  setViewMode,
  // Ribbon: Regenerate
  isRegenerating,
  handleRegenerateScore,
  // Ribbon: Export
  showMoreMenu,
  setShowMoreMenu,
  handleExportMIDI,
  handleExportMusicXML,
  handleExportText,
  handleExportGP5,
  // Ribbon: Tuning
  tuning,
  setTuning,
  // Ribbon: Technique
  showTechniques,
  setShowTechniques,
  // Direct DOM refs for smooth 60fps progress
  timelineProgressRef,
  timelineHandleRef,
}) {
  // 安全な時間フォーマット関数
  const formatTime = (seconds) => {
    if (isNaN(seconds) || seconds === Infinity || seconds === -Infinity) return "00:00";
    return new Date(seconds * 1000).toISOString().substr(14, 5);
  };

  const duration = audioRef.current?.duration || 0;
  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <>
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
          <Metronome bpm={Math.round((session?.result?.bpm || 120) * (playbackRate || 1))} />
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-4">
          <button onClick={handleShare} className="p-2.5 bg-[var(--gf-surface-2)] text-[var(--gf-text-dim)] hover:text-[var(--gf-amber)] rounded-xl transition-all border border-[var(--gf-border)]" aria-label="Share link"><Share2 size={18} /></button>
          <button onClick={toggleFavorite} className={`p-2.5 rounded-xl transition-all border ${isFavorite ? 'bg-pink-900/30 border-pink-800 text-pink-400 nc-fav-bounce' : 'bg-[var(--gf-surface-2)] border-[var(--gf-border)] text-[var(--gf-text-dim)] hover:text-pink-400'}`} aria-label={isFavorite ? 'Remove from favorites' : 'Add to favorites'}>
            <Heart size={18} fill={isFavorite ? 'currentColor' : 'none'} />
          </button>
          <button className="p-2.5 bg-[var(--gf-surface-2)] text-[var(--gf-text-dim)] hover:text-[var(--gf-amber)] rounded-xl transition-all border border-[var(--gf-border)]" aria-label="More options"><MoreHorizontal size={18} /></button>
        </div>
      </header>

      {/* 2. Playback Controller Section + Latency */}
      <div className="px-6 py-3 bg-[var(--gf-surface)] border-b border-[var(--gf-border)]">
        <div className="flex items-stretch gap-4">
          {/* 再生コントロール + タイムライン */}
          <div className="flex-1 flex items-center gap-4">
            <div className="flex items-center gap-2">
              <button onClick={togglePlay} className={`nc-large-play-btn ${isPlaying ? 'nc-playing' : ''}`} aria-label={isPlaying ? 'Pause playback' : 'Start playback'}>
                {isPlaying ? <Pause size={28} fill="currentColor" /> : <Play size={28} className="ml-1" fill="currentColor" />}
              </button>
              <button onClick={handleStop} title="Stop" aria-label="Stop playback" className="w-9 h-9 flex items-center justify-center rounded-xl bg-[var(--gf-surface-2)] text-[var(--gf-text-dim)] hover:text-[var(--gf-text)] border border-[var(--gf-border)] transition-all active:scale-95">
                <Square size={16} fill="currentColor" />
              </button>
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1 text-[9px] font-black text-[var(--gf-text-dim)] uppercase tracking-widest">
                <span>{formatTime(currentTime)}</span>
                <span>{formatTime(duration)}</span>
              </div>
              <div className="nc-timeline-container" onClick={handleWaveformClick}>
                <div ref={timelineProgressRef} className="nc-timeline-progress" style={{ width: `${progress}%` }} />
                <div ref={timelineHandleRef} className="nc-timeline-handle" style={{ left: `${progress}%` }} />
              </div>
            </div>
          </div>

          {/* VOLUME (コンパクト) */}
          <VolumeControl audioRef={audioRef} />

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
      <div className="nc-ribbon scrollbar-hide" role="toolbar" aria-label="Playback and display options">
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
        <button onClick={toggleLoop} className={`nc-ribbon-item ${isLooping ? 'bg-[var(--gf-amber-glow)]' : ''}`} aria-label="Toggle loop" aria-pressed={isLooping}>
          <Repeat className={`nc-ribbon-icon ${isLooping ? 'text-[var(--gf-amber)]' : ''}`} size={20} />
          <span className="nc-ribbon-label">ループ</span>
        </button>

        {/* Tuning Dropdown */}
        <div className="nc-ribbon-item">
          <select
            value={tuning || 'standard'}
            onChange={(e) => setTuning(e.target.value)}
            className="text-[11px] font-black text-[var(--gf-text)] bg-[var(--gf-surface-2)] border border-[var(--gf-border)] rounded-lg px-2 py-1 mb-1 cursor-pointer focus:outline-none focus:border-[var(--gf-amber)] appearance-none"
            style={{ minWidth: '90px' }}
          >
            {TUNINGS.map(t => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <span className="nc-ribbon-label">チューニング</span>
        </div>

        {/* Capo */}
        <div className="nc-ribbon-item">
          <div className="flex items-center gap-1 mb-1">
            <button onClick={() => setCapo(Math.max(0, capo - 1))}><ChevronLeft size={14} /></button>
            <span className="text-sm font-black italic text-[var(--gf-text)] w-8 text-center">{capo}</span>
            <button onClick={() => setCapo(Math.min(12, capo + 1))}><ChevronRight size={14} /></button>
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
        <button onClick={() => setInstrument('guitar')} className={`nc-ribbon-item ${instrument === 'guitar' ? 'active' : ''}`} aria-label="Guitar" aria-pressed={instrument === 'guitar'}>
          <Guitar className="nc-ribbon-icon" size={20} />
          <span className="nc-ribbon-label">ギター</span>
        </button>
        <button onClick={() => setInstrument('piano')} className={`nc-ribbon-item ${instrument === 'piano' ? 'active' : ''}`} aria-label="Piano" aria-pressed={instrument === 'piano'}>
          <Music className="nc-ribbon-icon" size={20} />
          <span className="nc-ribbon-label">ピアノ</span>
        </button>
        <div className="nc-ribbon-divider" />

        {/* View Mode Buttons */}
        <button onClick={() => setViewMode('text')} className={`nc-ribbon-item ${viewMode === 'text' ? 'active' : ''}`} aria-label="Text view" aria-pressed={viewMode === 'text'}>
          <AlignLeft className="nc-ribbon-icon" size={20} />
          <span className="nc-ribbon-label">テキスト</span>
        </button>


        <div style={{ flex: 1 }} />

        {/* Export */}
        <button onClick={() => setShowMoreMenu(!showMoreMenu)} className="nc-ribbon-item relative" aria-label="Export" aria-expanded={showMoreMenu} aria-haspopup="true">
          <Download className="nc-ribbon-icon" size={20} />
          <span className="nc-ribbon-label">書き出し</span>
          {showMoreMenu && (
            <div className="nc-export-menu" onClick={(e) => e.stopPropagation()} role="menu" aria-label="Export formats">
              <div role="menuitem" tabIndex={0} onClick={(e) => { e.stopPropagation(); handleExportMIDI(); setShowMoreMenu(false); }} onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); handleExportMIDI(); setShowMoreMenu(false); } }} className="nc-export-item">
                <div className="nc-export-item-icon"><Disc size={14} /></div>
                <span>MIDI</span>
                <span className="nc-export-shortcut">⌃⇧M</span>
              </div>
              <div role="menuitem" tabIndex={0} onClick={(e) => { e.stopPropagation(); handleExportMusicXML(); setShowMoreMenu(false); }} onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); handleExportMusicXML(); setShowMoreMenu(false); } }} className="nc-export-item">
                <div className="nc-export-item-icon"><FileCode size={14} /></div>
                <span>MusicXML</span>
                <span className="nc-export-shortcut">⌃⇧X</span>
              </div>
              <div role="menuitem" tabIndex={0} onClick={(e) => { e.stopPropagation(); handleExportText(); setShowMoreMenu(false); }} onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); handleExportText(); setShowMoreMenu(false); } }} className="nc-export-item">
                <div className="nc-export-item-icon"><FileText size={14} /></div>
                <span>Text</span>
                <span className="nc-export-shortcut">⌃⇧T</span>
              </div>
              <div role="menuitem" tabIndex={0} onClick={(e) => { e.stopPropagation(); handleExportGP5(); setShowMoreMenu(false); }} onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); handleExportGP5(); setShowMoreMenu(false); } }} className="nc-export-item">
                <div className="nc-export-item-icon"><Guitar size={14} /></div>
                <span>Guitar Pro 5</span>
                <span className="nc-export-shortcut">⌃⇧G</span>
              </div>
            </div>
          )}
        </button>
      </div>
    </>
  );
}
