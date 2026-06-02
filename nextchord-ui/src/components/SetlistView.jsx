import React, { useState, useEffect } from 'react';
import { ChevronLeft, Printer, Music, Guitar } from 'lucide-react';
import { ChordProView } from './ChordProView';

export function SetlistView({ setlistName, setlistData, onClose, onPrint }) {
  const [globalCapo, setGlobalCapo] = useState({});
  const [globalTranspose, setGlobalTranspose] = useState({});

  // Initialize capos from localStorage song-settings
  useEffect(() => {
    const settings = JSON.parse(localStorage.getItem('nextchord-song-settings') || '{}');
    const initialCapo = {};
    const initialTranspose = {};
    setlistData.forEach((song) => {
      if (settings[song.id]) {
        if (settings[song.id].capo !== undefined) initialCapo[song.id] = settings[song.id].capo;
        if (settings[song.id].transpose !== undefined) initialTranspose[song.id] = settings[song.id].transpose;
      } else {
        initialCapo[song.id] = 0;
        initialTranspose[song.id] = 0;
      }
    });
    setGlobalCapo(initialCapo);
    setGlobalTranspose(initialTranspose);
  }, [setlistData]);

  const handleCapoChange = (id, newCapo) => {
    setGlobalCapo(prev => ({ ...prev, [id]: newCapo }));
  };

  return (
    <div className="flex flex-col h-full bg-[var(--nc-bg)]">
      {/* Header (Hidden in print) */}
      <header className="px-8 py-4 bg-[var(--nc-surface)] border-b border-[var(--nc-border)] flex items-center justify-between shadow-sm z-10 print:hidden">
        <div className="flex items-center gap-4">
          <button 
            onClick={onClose}
            className="w-10 h-10 flex items-center justify-center rounded-xl hover:bg-[var(--nc-surface-2)] transition-colors text-[var(--nc-text-ghost)] hover:text-[var(--nc-text)]"
          >
            <ChevronLeft size={24} />
          </button>
          <div>
            <h1 className="text-xl font-black text-[var(--nc-text)] tracking-tight">
              セットリスト: {setlistName}
            </h1>
            <p className="text-[11px] font-bold text-[var(--nc-text-muted)] mt-0.5">
              {setlistData.length}曲
            </p>
          </div>
        </div>
        <button 
          onClick={() => window.print()}
          className="nc-btn-primary flex items-center gap-2 px-5 py-2.5 rounded-xl shadow-lg"
        >
          <Printer size={16} />
          セットリストを印刷 / PDF化
        </button>
      </header>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-8 py-10 print:p-0 print:overflow-visible">
        <div className="max-w-4xl mx-auto flex flex-col gap-12 print:gap-8">
          
          {/* Print title page / header */}
          <div className="hidden print:block text-center mb-8 border-b-2 border-black pb-4">
            <h1 className="text-4xl font-black mb-2">{setlistName}</h1>
            <p className="text-xl text-gray-600">Setlist - {setlistData.length} Songs</p>
          </div>

          {setlistData.map((song, index) => {
            const capo = globalCapo[song.id] || 0;
            const transpose = globalTranspose[song.id] || 0;

            // Generate chordpro line timings (dummy if missing)
            let timings = null;
            if (song.result.chordpro_line_timings) {
              timings = song.result.chordpro_line_timings.map(t => ({ startTime: t }));
            }

            return (
              <div 
                key={song.id} 
                className="bg-[var(--nc-surface)] border border-[var(--nc-border)] rounded-2xl overflow-hidden print:border-none print:shadow-none print:bg-transparent"
                style={{ pageBreakAfter: 'always' }}
              >
                {/* Song Header */}
                <div className="px-8 py-4 bg-[var(--nc-surface-2)] border-b border-[var(--nc-border)] flex items-center justify-between print:bg-transparent print:border-b-2 print:border-black print:px-0">
                  <div>
                    <div className="text-[10px] font-bold text-[var(--nc-primary)] uppercase tracking-widest mb-1 print:text-black">
                      Song {index + 1}
                    </div>
                    <h2 className="text-2xl font-black text-[var(--nc-text)] print:text-black">
                      {song.filename || song.result.title || "Untitled"}
                    </h2>
                    {song.artist && (
                      <p className="text-sm font-bold text-[var(--nc-text-muted)] mt-1 print:text-gray-700">
                        {song.artist}
                      </p>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-2 print:flex-row print:items-center">
                    <div className="flex items-center gap-2">
                      <span className="px-3 py-1.5 bg-[var(--nc-bg)] rounded-lg text-[11px] font-black text-[var(--nc-text)] border border-[var(--nc-border)] print:border-gray-400 print:text-black">
                        Key: {song.result.key || '--'} {capo > 0 ? `(Capo ${capo})` : ''}
                      </span>
                      <span className="px-3 py-1.5 bg-[var(--nc-bg)] rounded-lg text-[11px] font-black text-[var(--nc-amber)] border border-[var(--nc-border)] print:border-gray-400 print:text-black">
                        ♩ {song.result.bpm ? Math.round(song.result.bpm) : '--'}
                      </span>
                    </div>
                    {/* Inline Capo controller for Setlist Mode (hidden in print) */}
                    <div className="flex items-center gap-1 bg-[var(--nc-bg)] px-2 py-1 rounded-lg border border-[var(--nc-border)] print:hidden">
                      <span className="text-[10px] font-bold text-[var(--nc-text-muted)] mr-1">Capo</span>
                      <button onClick={() => handleCapoChange(song.id, Math.max(0, capo - 1))} className="text-[var(--nc-text-ghost)] hover:text-[var(--nc-text)]"><ChevronLeft size={14}/></button>
                      <span className="text-xs font-black w-4 text-center">{capo}</span>
                      <button onClick={() => handleCapoChange(song.id, Math.min(12, capo + 1))} className="text-[var(--nc-text-ghost)] hover:text-[var(--nc-text)]"><ChevronLeft size={14} className="rotate-180"/></button>
                    </div>
                  </div>
                </div>

                {/* Song Content */}
                <div className="p-8 print:p-0 print:pt-4">
                  {song.result.chordpro_text ? (
                    <ChordProView
                      chordproText={song.result.chordpro_text}
                      currentTime={0}
                      onSeek={() => {}}
                      transpose={transpose - capo}
                      title={song.filename}
                      artist={song.artist}
                      lineTimings={timings}
                    />
                  ) : (
                    <div className="text-center py-10 text-[var(--nc-text-muted)]">
                      この曲は新しいChordProフォーマットに対応していません。再度解析してください。
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
