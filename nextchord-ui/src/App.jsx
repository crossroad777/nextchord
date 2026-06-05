import React, { useEffect, useCallback, useState, useMemo } from "react";
import {
  Music, Check, X, UploadCloud, AlertTriangle, FileText,
  Sun, Moon, Settings
} from 'lucide-react';
import { InstrumentPanel } from "./components/InstrumentPanel";
import { ChordLyricsView } from "./components/ChordLyricsView";
import { ChordProView } from "./components/ChordProView";
import { UploadView } from "./components/UploadView";
import { ProcessingView } from "./components/ProcessingView";
import { ResultHeader } from "./components/ResultHeader";
import { SetlistView } from "./components/SetlistView";
import { useNextChord, STATUS, getApiBase } from "./hooks/useNextChord";

const getTuningOffset = (tuning) => tuning === 'half_down' ? -1 : 0;

export default function NextChordApp() {
  const app = useNextChord();
  const [showSettings, setShowSettings] = useState(false);
  const [tempApiUrl, setTempApiUrl] = useState(() => localStorage.getItem('nextchord-api-base') || "");
  const [tempYtCookies, setTempYtCookies] = useState(() => localStorage.getItem('nextchord-yt-cookies') || "");

  // ChordPro行タイミング: バックエンドで計算済みのデータを優先使用
  const chordproLineTimings = useMemo(() => {
    const r = app.session?.result;
    if (!r) return null;

    // バックエンド計算済みタイミングがあればそのまま使用
    if (r.chordpro_line_timings && r.chordpro_line_timings.length > 0) {
      return r.chordpro_line_timings.map(t => ({ startTime: t }));
    }

    // フォールバック: structured_data から推定（既存セッション用）
    if (!r.structured_data || !r.chordpro_text) return null;
    const sd = r.structured_data;
    const cc = [];
    let prev = null;
    for (let i = 0; i < sd.length; i++) {
      if (sd[i].chord !== 'N.C.' && sd[i].chord !== prev) {
        cc.push(sd[i].time);
        prev = sd[i].chord;
      } else if (sd[i].chord === 'N.C.') { prev = null; }
    }
    const lines = r.chordpro_text.split('\n');
    const re = /\[([A-G][^\]]*?)\]/g;
    const timings = [];
    let ci = 0;
    for (const line of lines) {
      const m = line.match(re);
      if (m && m.length > 0) {
        timings.push({ startTime: cc[ci] || 0 });
        ci += m.length;
      }
    }
    return timings;
  }, [app.session?.result]);

  // Keyboard shortcuts for export actions
  useEffect(() => {
    const handleKeyboard = (e) => {
      if (!e.ctrlKey || !e.shiftKey) return;
      const key = e.key.toUpperCase();
      if (key === 'M') { e.preventDefault(); app.handleExportMIDI(); }
      else if (key === 'X') { e.preventDefault(); app.handleExportMusicXML(); }
      else if (key === 'T') { e.preventDefault(); app.handleExportText(); }
      else if (key === 'G') { e.preventDefault(); app.handleExportGP5(); }
    };
    window.addEventListener('keydown', handleKeyboard);
    return () => window.removeEventListener('keydown', handleKeyboard);
  }, [app.handleExportMIDI, app.handleExportMusicXML, app.handleExportText, app.handleExportGP5]);

  // Track favorite bounce animation
  const [favBounce, setFavBounce] = useState(false);
  // ホバー中のコード（右パネルに優先表示）
  const [hoveredChord, setHoveredChord] = useState(null);
  // 明るさ調整（ライトモード用）
  const [brightness, setBrightness] = useState(() => {
    return parseInt(localStorage.getItem('nc-brightness') || '100', 10);
  });
  const wrappedToggleFavorite = useCallback(() => {
    app.toggleFavorite();
    setFavBounce(true);
    setTimeout(() => setFavBounce(false), 500);
  }, [app.toggleFavorite]);

  const renderResultView = () => {
    if (app.status === "setlist_view") {
      return (
        <SetlistView 
          setlistName={app.setlistName}
          setlistData={app.setlistData}
          onClose={app.resetSession}
        />
      );
    }

    if (app.status !== STATUS.COMPLETED || !app.session?.data) return null;

    return (
      <div className="flex h-full bg-[var(--gf-bg)] overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          <ResultHeader
            session={app.session}
            getTransposedKey={app.getTransposedKey}
            transpose={app.transpose}
            capo={app.capo}
            isFavorite={app.isFavorite}
            handleShare={app.handleShare}
            toggleFavorite={app.toggleFavorite}
            isPlaying={app.isPlaying}
            togglePlay={app.togglePlay}
            handleStop={app.handleStop}
            currentTime={app.currentTime}
            audioRef={app.audioRef}
            handleWaveformClick={app.handleWaveformClick}
            playbackRate={app.playbackRate}
            setPlaybackRate={app.setPlaybackRate}
            isLooping={app.isLooping}
            toggleLoop={app.toggleLoop}
            setCapo={app.setCapo}
            recommendedCapo={app.recommendedCapo}
            handleTranspose={app.handleTranspose}
            instrument={app.instrument}
            setInstrument={app.setInstrument}
            viewMode={app.viewMode}
            setViewMode={app.setViewMode}
            isRegenerating={app.isRegenerating}
            handleRegenerateScore={app.handleRegenerateScore}
            showMoreMenu={app.showMoreMenu}
            setShowMoreMenu={app.setShowMoreMenu}
            handleExportMIDI={app.handleExportMIDI}
            handleExportMusicXML={app.handleExportMusicXML}
            handleExportText={app.handleExportText}
            handleExportGP5={app.handleExportGP5}
            tuning={app.tuning}
            setTuning={app.setTuning}
            showTechniques={app.showTechniques}
            setShowTechniques={app.setShowTechniques}
            timelineProgressRef={app.timelineProgressRef}
            timelineHandleRef={app.timelineHandleRef}
          />
          <div className="flex-1 bg-[var(--gf-bg)] overflow-hidden">
            {app.session.result?.chordpro_text ? (
              <ChordProView
                chordproText={app.session.result.chordpro_text}
                currentTime={app.currentTime}
                onSeek={app.handleSeek}
                transpose={app.transpose - app.capo - getTuningOffset(app.tuning)}
                title={app.session.fileName}
                artist={app.session.artist}
                lineTimings={chordproLineTimings}
                tuning={app.tuning}
              />
            ) : (
              <div className="overflow-y-auto py-10 px-8 h-full">
                <div className="nc-view-enter">
                  <ChordLyricsView 
                    data={app.session.data} 
                    lyricsPhrases={app.session.lyricsPhrases} 
                    displayPhrases={app.session.displayPhrases} 
                    barPositions={app.session.barPositions} 
                    currentTime={app.currentTime} 
                    onSeek={app.handleSeek} 
                    onChordEdit={app.handleChordEditByTime} 
                    onLyricEdit={app.handleLyricEdit} 
                    onChordHover={setHoveredChord} 
                    transpose={app.transpose - app.capo - getTuningOffset(app.tuning)} 
                    title={app.session.fileName} 
                    artist={app.session.artist} 
                  />
                </div>
              </div>
            )}
          </div>
          {(app.instrument === 'guitar' || app.instrument === 'piano') && app.viewMode !== 'tab' && (
            <div className="nc-instrument-panel">
              <InstrumentPanel
                currentChord={hoveredChord ?? app.currentChord}
                transpose={app.transpose - app.capo - getTuningOffset(app.tuning)}
                instrument={app.instrument}
                tuning={app.tuning}
              />
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div
      className="flex flex-col h-screen bg-[var(--gf-bg)] text-[var(--gf-text)] font-sans relative"
      onDragOver={app.handleDragOver} onDragLeave={app.handleDragLeave} onDrop={app.handleDrop}
    >
      {/* Accessibility: Skip-link */}
      <a href="#nc-main-content" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:bg-indigo-600 focus:text-white focus:px-4 focus:py-2 focus:rounded">Skip to content</a>
      {/* Screen reader live region for state changes */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {app.status === 'processing' && 'Analysis in progress'}
        {app.status === 'completed' && 'Analysis complete'}
        {app.status === 'failed' && 'Analysis failed'}
      </div>
      <audio ref={app.audioRef} onEnded={() => app.setIsPlaying(false)} />

      {/* Drag & Drop Overlay */}
      {app.isDragging && (
        <div className="absolute inset-0 z-[100] flex flex-col items-center justify-center p-10 pointer-events-none m-4 rounded-3xl transition-all duration-300" style={{ background: 'rgba(99, 102, 241, 0.85)', backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)', border: '3px dashed rgba(255,255,255,0.3)' }}>
          <UploadCloud size={120} className="animate-bounce mb-8 text-white" />
          <h2 className="text-5xl font-black tracking-tighter mb-3 text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>Drop to analyze</h2>
          <p className="text-white/70 font-medium">音声ファイルまたはYouTubeリンク</p>
        </div>
      )}

      {/* Header */}
      <header className="h-20 nc-gradient-bg flex items-center justify-between px-8 text-[var(--nc-text)] shadow-xl z-30 flex-shrink-0 relative">
        <div className="flex items-center gap-8">
          <div className="font-black text-2xl tracking-tight cursor-pointer group flex items-center gap-2.5" style={{ fontFamily: "'Outfit', sans-serif" }} onClick={app.handleReset} role="button" tabIndex={0} aria-label="Go to home screen" onKeyDown={(e) => { if (e.key === 'Enter') app.handleReset(); }}>
            <div className="nc-header-logo-icon">
              <Music size={16} className="text-white" />
            </div>
            <span className="nc-logo-text group-hover:opacity-80 transition-opacity">NextChord</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Brightness Adjustment (Light Mode only) */}
          {app.theme === 'light' && (
            <div className="flex items-center gap-2 mr-2 bg-white/80 px-3 py-1.5 rounded-full border border-gray-200 shadow-sm" title="明るさを下げる（眩しさ防止）">
              <Sun size={14} className="text-amber-500" />
              <input
                type="range"
                min="40"
                max="100"
                value={brightness}
                onChange={(e) => {
                  setBrightness(e.target.value);
                  localStorage.setItem('nc-brightness', e.target.value);
                }}
                className="w-24 accent-amber-500 h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer"
              />
            </div>
          )}

          {/* Theme Toggle */}
          <button
            id="nc-theme-toggle"
            onClick={app.toggleTheme}
            className="w-9 h-9 rounded-lg flex items-center justify-center transition-all hover:bg-[var(--nc-surface-2)] group"
            title={app.theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label={app.theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            style={{ border: '1px solid var(--nc-border)' }}
          >
            {app.theme === 'dark'
              ? <Sun size={16} className="text-[var(--nc-text-secondary)] group-hover:text-amber-400 transition-colors" />
              : <Moon size={16} className="text-[var(--nc-text-secondary)] group-hover:text-indigo-400 transition-colors" />
            }
          </button>

          {/* Server Settings */}
          <button
            onClick={() => {
              setTempApiUrl(localStorage.getItem('nextchord-api-base') || "");
              setTempYtCookies(localStorage.getItem('nextchord-yt-cookies') || "");
              setShowSettings(true);
            }}
            className="w-9 h-9 rounded-lg flex items-center justify-center transition-all hover:bg-[var(--nc-surface-2)] group"
            title="サーバー設定"
            aria-label="Server Settings"
            style={{ border: '1px solid var(--nc-border)' }}
          >
            <Settings size={16} className="text-[var(--nc-text-secondary)] group-hover:text-indigo-400 transition-colors" />
          </button>
          <input ref={app.fileInputRef} id="nc-file-upload" name="audio-file" type="file" onChange={app.handleUpload} className="hidden" accept="audio/*" />
        </div>
      </header>

      {/* Main content */}
      <main id="nc-main-content" className="flex-1 flex overflow-hidden relative" role="main" style={{ filter: app.theme === 'light' ? `brightness(${brightness}%)` : 'none', transition: 'filter 0.3s ease' }}>
        <div className="flex-1 overflow-y-auto scroll-smooth custom-scrollbar relative">

          {/* Welcome/Empty State */}
          {app.status === STATUS.IDLE && (
            <UploadView
              fileInputRef={app.fileInputRef}
              ytUrl={app.ytUrl}
              setYtUrl={app.setYtUrl}
              handleYouTubeUpload={app.handleYouTubeUpload}
              history={app.history}
              restoreSession={app.restoreSession}
              favorites={app.favorites}
              getFolders={app.getFolders}
              getFavoritesByFolder={app.getFavoritesByFolder}
              createFolder={app.createFolder}
              deleteFolder={app.deleteFolder}
              moveToFolder={app.moveToFolder}
              exportSettings={app.exportSettings}
              importSettings={app.importSettings}
              startSetlist={app.startSetlist}
              showToast={app.showToast}
              onOpenSettings={() => {
                setTempApiUrl(localStorage.getItem('nextchord-api-base') || "");
                setTempYtCookies(localStorage.getItem('nextchord-yt-cookies') || "");
                setShowSettings(true);
              }}
            />
          )}

          {/* Processing state */}
          {app.status === STATUS.PROCESSING && (
            <ProcessingView
              stepsDone={app.stepsDone}
              progressMsg={app.progressMsg}
              onCancel={app.resetSession}
            />
          )}

          {/* Failed state */}
          {app.status === STATUS.FAILED && (
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
                  {app.progressMsg || "不明なエラー"}
                </div>
                <div className="nc-error-actions">
                  <button
                    onClick={() => app.fileInputRef.current.click()}
                    className="nc-btn-primary px-6 py-3 text-sm"
                  >
                    再アップロード
                  </button>
                  <button
                    onClick={app.handleGoHome}
                    className="nc-btn-secondary px-6 py-3 text-sm"
                  >
                    ホームに戻る
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Result view */}
          {renderResultView()}

        </div>
      </main>

      {/* Stacking Toast Notifications */}
      {app.toasts.length > 0 && (
        <div className="nc-toast-container" role="status" aria-live="polite">
          {app.toasts.map((t) => (
            <div
              key={t.id}
              className={`nc-toast ${
                t.type === 'error' ? 'nc-toast-error' : t.type === 'info' ? 'nc-toast-info' : 'nc-toast-success'
              }`}
              style={{ '--toast-duration': `${t.duration || 3000}ms` }}
              role="alert"
            >
              {t.type === 'error' ? <X size={16} /> : <Check size={16} />}
              <span>{t.message}</span>
              <button
                className="nc-toast-dismiss"
                onClick={() => app.dismissToast(t.id)}
                aria-label="Dismiss notification"
              >
                ×
              </button>
              <div className="nc-toast-progress" />
            </div>
          ))}
        </div>
      )}

      {/* Text View Modal */}
      {app.showTextModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="bg-[var(--gf-surface)] w-full max-w-3xl h-[80vh] rounded-3xl shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 border border-[var(--gf-border)]">
            <div className="p-6 border-b border-[var(--gf-border)] flex items-center justify-between bg-[var(--gf-surface-2)]">
              <h3 className="text-xl font-black text-[var(--gf-text)] flex items-center gap-2">
                <FileText size={20} className="text-[var(--gf-amber)]" />
                Text Score
              </h3>
              <div className="flex items-center gap-2">
                <button onClick={() => { navigator.clipboard.writeText(app.textContent); app.showToast('Copied to clipboard'); }} className="px-4 py-2 bg-[var(--gf-surface)] border border-[var(--gf-border)] rounded-xl text-sm font-bold text-[var(--gf-text-dim)] hover:bg-[var(--gf-amber-glow)] hover:text-[var(--gf-amber)] hover:border-[var(--gf-amber)]/30 transition-all">
                  Copy
                </button>
                <button onClick={() => app.setShowTextModal(false)} className="p-2 hover:bg-[var(--gf-surface-3)] rounded-full transition-all text-[var(--gf-text-dim)]">
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-auto p-8 bg-[var(--gf-surface)] font-mono text-sm leading-relaxed whitespace-pre overflow-x-auto text-[var(--gf-text)]">
              {app.textContent || "Loading..."}
            </div>
          </div>
        </div>
      )}

      {/* Settings Modal */}
      {showSettings && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in p-4">
          <div className="bg-[var(--nc-surface)] border border-[var(--nc-border)] p-6 rounded-2xl shadow-xl w-full max-w-md" onClick={e => e.stopPropagation()}>
            <h2 className="text-xl font-bold mb-4 flex items-center gap-2"><Settings className="text-[var(--nc-primary)]"/> サーバー設定</h2>
            <div className="mb-4">
              <label className="block text-sm font-bold text-[var(--nc-text-muted)] mb-2">API Base URL (Google Colab / Local)</label>
              <input 
                type="text" 
                value={tempApiUrl} 
                onChange={(e) => setTempApiUrl(e.target.value)} 
                className="w-full px-4 py-3 rounded-xl bg-[var(--nc-surface-2)] border border-[var(--nc-border)] text-[var(--nc-text)] focus:outline-none focus:border-[var(--nc-primary)] transition-all"
                placeholder="https://xxxxx.loca.lt"
              />
              <p className="text-xs text-[var(--nc-text-ghost)] mt-1.5 leading-relaxed">
                Google Colab等で発行されたバックエンドURLを入力してください。空欄にすると環境変数のURLが使われます。
              </p>
            </div>
            <div className="mb-6">
              <div className="flex justify-between items-center mb-2">
                <label className="block text-sm font-bold text-[var(--nc-text-muted)]">YouTube クッキー (Netscape形式)</label>
                <a 
                  href="/cookie_guide.html" 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  className="text-xs text-[var(--nc-primary)] hover:underline flex items-center gap-1"
                >
                  設定手順ガイド ↗
                </a>
              </div>
              <textarea 
                value={tempYtCookies} 
                onChange={(e) => setTempYtCookies(e.target.value)} 
                className="w-full h-28 px-4 py-3 rounded-xl bg-[var(--nc-surface-2)] border border-[var(--nc-border)] text-[var(--nc-text)] focus:outline-none focus:border-[var(--nc-primary)] transition-all font-mono text-xs custom-scrollbar"
                placeholder="# Netscape HTTP Cookie File&#10;.youtube.com&#9;TRUE&#9;/&#9;TRUE&#9;1780000000&#9;__Secure-3PSID&#9;xxx..."
                spellCheck={false}
              />
              <p className="text-xs text-[var(--nc-text-ghost)] mt-1.5 leading-relaxed">
                YouTubeでボット検出エラーになる場合、ブラウザ拡張等でクッキーを書き出し、貼り付けてください。シークレットウィンドウ経由での取得を推奨します。
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowSettings(false)} className="px-4 py-2 rounded-xl text-sm font-bold hover:bg-[var(--nc-surface-2)] text-[var(--nc-text-muted)] transition-all">キャンセル</button>
              <button 
                onClick={() => {
                  if (tempApiUrl.trim()) {
                    localStorage.setItem('nextchord-api-base', tempApiUrl.trim());
                  } else {
                    localStorage.removeItem('nextchord-api-base');
                  }
                  if (tempYtCookies.trim()) {
                    localStorage.setItem('nextchord-yt-cookies', tempYtCookies.trim());
                  } else {
                    localStorage.removeItem('nextchord-yt-cookies');
                  }
                  setShowSettings(false);
                  app.showToast("設定を保存しました");
                }} 
                className="px-4 py-2 rounded-xl text-sm font-bold bg-[var(--nc-primary)] text-[var(--nc-bg)] hover:bg-[var(--nc-primary-hover)] transition-all shadow-md shadow-indigo-500/20"
              >
                保存して適用
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
