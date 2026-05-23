import React from "react";
import {
  Play, ChevronRight, History, UploadCloud, Music
} from 'lucide-react';

export function UploadView({
  fileInputRef,
  ytUrl,
  setYtUrl,
  handleYouTubeUpload,
  history,
  restoreSession,
}) {
  return (
    <div className="h-full flex flex-col items-center justify-start pt-16 p-12 text-center max-w-4xl mx-auto animate-in fade-in duration-1000 relative">
      {/* Subtle ambient glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[300px] pointer-events-none" style={{ background: 'radial-gradient(ellipse, rgba(99, 102, 241, 0.06) 0%, transparent 70%)' }} />

      {/* Hero Logo */}
      <div className="nc-hero-logo-icon">
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
          role="button"
          aria-label="Select audio file to analyze"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInputRef.current.click(); } }}
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

        {/* YouTube URL Input */}
        <div className="mt-6 flex items-center gap-3 text-[var(--nc-text-muted)]">
          <div className="flex-1 h-px bg-[var(--nc-border)]" />
          <span className="text-[10px] font-bold uppercase tracking-widest">または</span>
          <div className="flex-1 h-px bg-[var(--nc-border)]" />
        </div>
        <div className="mt-4 flex gap-2 items-center w-full">
          <div className="flex-1 relative">
            <input
              type="text"
              value={ytUrl}
              onChange={(e) => setYtUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && ytUrl.trim()) handleYouTubeUpload(ytUrl.trim()); }}
              placeholder="Paste YouTube URL"
              aria-label="YouTube URL input"
              className="w-full px-4 py-3 rounded-xl text-sm bg-[var(--nc-surface)] border border-[var(--nc-border)] text-[var(--nc-text)] placeholder-[var(--nc-text-muted)] focus:outline-none focus:border-[var(--nc-primary)] focus:ring-1 focus:ring-[var(--nc-primary)] transition-all"
              style={{ fontFamily: "'Inter', sans-serif" }}
            />
          </div>
          <button
            onClick={() => { if (ytUrl.trim()) handleYouTubeUpload(ytUrl.trim()); }}
            disabled={!ytUrl.trim()}
            className="px-5 py-3 rounded-xl text-sm font-bold transition-all flex items-center gap-2 flex-shrink-0"
            aria-label="Start YouTube analysis"
            style={{
              background: ytUrl.trim() ? 'linear-gradient(135deg, #ef4444, #dc2626)' : 'var(--nc-surface-2)',
              color: ytUrl.trim() ? '#fff' : 'var(--nc-text-muted)',
              border: ytUrl.trim() ? 'none' : '1px solid var(--nc-border)',
              cursor: ytUrl.trim() ? 'pointer' : 'not-allowed',
              opacity: ytUrl.trim() ? 1 : 0.6,
            }}
          >
            <Play size={14} fill="currentColor" />
            解析
          </button>
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
  );
}
