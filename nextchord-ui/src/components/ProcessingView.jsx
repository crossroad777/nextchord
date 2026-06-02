import React, { useState, useEffect, useRef } from "react";

export function ProcessingView({ session, stepsDone }) {
  const steps = [
    { key: 'chords', label: 'コード解析', icon: '🎸', avgSec: 3 },
    { key: 'whisper', label: '歌詞検出', icon: '🎤', avgSec: 8 },
    { key: 'key', label: 'キー検出', icon: '🎵', avgSec: 10 },
    { key: 'beats', label: 'ビート検出', icon: '🥁', avgSec: 15 },
    { key: 'postprocess', label: 'スコア生成', icon: '📄', avgSec: 5 },
  ];
  const totalAvgSec = steps.reduce((a, s) => a + s.avgSec, 0);
  const doneCount = stepsDone;

  // Compute cumulative time for each step boundary
  const cumTime = [0];
  steps.forEach((s, i) => { cumTime.push(cumTime[i] + s.avgSec); });

  // Track elapsed since analysis started (step 0)
  const startTimeRef = useRef(Date.now());
  const [elapsedSec, setElapsedSec] = useState(0);

  // Reset start time only when starting fresh (doneCount goes to 0)
  useEffect(() => {
    if (doneCount === 0) startTimeRef.current = Date.now();
  }, [doneCount]);

  // Smooth tick
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsedSec((Date.now() - startTimeRef.current) / 1000);
    }, 100);
    return () => clearInterval(timer);
  }, []);

  // Calculate percentage from two sources: actual steps done + time-based interpolation
  const stepBasedPct = (doneCount / steps.length) * 100;
  
  // Time-based: where we "should" be based on elapsed time and average durations
  const timeBasedPct = Math.min(95, (elapsedSec / totalAvgSec) * 100);
  
  // Use the HIGHER of the two, but never exceed 95% until truly done
  const rawPct = doneCount >= steps.length ? 100 : Math.max(stepBasedPct, timeBasedPct);
  const pct = Math.min(doneCount >= steps.length ? 100 : 95, Math.round(rawPct));

  // ETA from elapsed
  const etaSec = Math.max(0, Math.round(totalAvgSec - elapsedSec));

  const formatEta = (seconds) => {
    if (!seconds || seconds <= 0) return '';
    if (seconds < 60) return `残り約${seconds}秒`;
    const min = Math.floor(seconds / 60);
    const sec = seconds % 60;
    return `残り約${min}分${sec}秒`;
  };

  return (
    <div
      className="h-full flex flex-col items-center justify-center p-12 text-center animate-in fade-in duration-700"
      role="status"
      aria-label={`解析中。ステップ ${doneCount + 1} / ${steps.length}`}
    >
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[500px] h-[300px] pointer-events-none" style={{ background: 'radial-gradient(ellipse, rgba(99, 102, 241, 0.06) 0%, transparent 65%)' }} />

      {/* Song info */}
      {(session?.fileName || session?.artist) && (
        <div className="mb-8 animate-in slide-in-from-bottom duration-500">
          <p className="text-lg font-bold text-[var(--nc-text)] truncate max-w-sm" style={{ fontFamily: "'Outfit', sans-serif" }}>
            {session.fileName}
          </p>
          {session.artist && (
            <p className="text-sm text-[var(--nc-text-secondary)] mt-1">{session.artist}</p>
          )}
        </div>
      )}

      {/* Circular progress */}
      <div className="relative mb-8">
        <svg width="120" height="120" viewBox="0 0 120 120" className="absolute -inset-[10px]" aria-hidden="true">
          <circle cx="60" cy="60" r="56" fill="none" stroke="rgba(99, 102, 241, 0.08)" strokeWidth="2" strokeDasharray="8 6" className="nc-processing-ring" />
        </svg>
        <svg width="100" height="100" viewBox="0 0 100 100" role="progressbar" aria-valuenow={pct} aria-valuemin="0" aria-valuemax="100">
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--nc-surface-3)" strokeWidth="6" />
          <circle cx="50" cy="50" r="42" fill="none" stroke="url(#progressGradient)" strokeWidth="6"
            strokeLinecap="round" strokeDasharray={`${2 * Math.PI * 42}`}
            strokeDashoffset={`${2 * Math.PI * 42 * (1 - pct / 100)}`}
            transform="rotate(-90 50 50)"
            style={{ transition: 'stroke-dashoffset 0.5s ease-out' }}
          />
          <defs>
            <linearGradient id="progressGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#6366f1" />
              <stop offset="100%" stopColor="#8b5cf6" />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xl font-black text-[var(--nc-text)]" style={{ fontFamily: "'Outfit', sans-serif" }}>{pct}%</span>
        </div>
      </div>

      {/* Step checklist */}
      <div className="w-full max-w-xs space-y-2 mb-6" role="list" aria-label="解析ステップ">
        {steps.map((step, i) => {
          const isDone = i < doneCount;
          const isCurrent = i === doneCount;
          return (
            <div key={step.key}
              className={`flex items-center gap-3 px-4 py-2.5 rounded-xl transition-all duration-500 ${isDone ? 'bg-[rgba(99,102,241,0.08)]' : isCurrent ? 'bg-[var(--nc-surface)] nc-step-active' : 'opacity-40'
                }`}
              style={isCurrent ? { border: '1px solid rgba(99,102,241,0.2)' } : {}}
              role="listitem"
              aria-current={isCurrent ? 'step' : undefined}
            >
              <span className="text-lg w-7 text-center flex-shrink-0" aria-hidden="true">
                {isDone ? '✅' : isCurrent ? step.icon : '⬜'}
              </span>
              <span className={`text-sm font-medium flex-1 text-left ${isDone ? 'text-[var(--nc-text)]' : isCurrent ? 'text-[var(--nc-primary)]' : 'text-[var(--nc-text-muted)]'
                }`}>
                <span className="text-[10px] font-mono opacity-50 mr-1.5">{i + 1}/{steps.length}</span>
                {step.label}
              </span>
              {isCurrent && (
                <div className="w-4 h-4 rounded-full border-2 border-[var(--nc-primary)] border-t-transparent animate-spin" aria-hidden="true" />
              )}
              {isDone && (
                <span className="text-[10px] text-[var(--nc-text-muted)] font-mono">完了</span>
              )}
            </div>
          );
        })}
      </div>

      {/* ETA */}
      {pct < 100 && etaSec > 0 && (
        <p className="text-[var(--nc-text-muted)] text-xs font-medium mb-3 animate-in fade-in duration-300">
          {formatEta(etaSec)}
        </p>
      )}

      <p className="text-[var(--nc-text-ghost)] text-[10px] font-medium uppercase tracking-[0.2em]">
        AI解析中
      </p>
    </div>
  );
}
