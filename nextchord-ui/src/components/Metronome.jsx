import React, { useState, useEffect, useRef, useCallback } from 'react';

const MetronomeIcon = ({ size = 16, className = "" }) => (
  <svg 
    viewBox="0 0 24 24" 
    width={size} 
    height={size} 
    stroke="currentColor" 
    strokeWidth="2.5" 
    fill="none" 
    strokeLinecap="round" 
    strokeLinejoin="round"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
  >
    <path d="M12 2L5 22h14L12 2z" />
    <path d="M12 5v12" />
    <circle cx="12" cy="17" r="1.5" fill="currentColor" />
    <path d="M12 17l4-9" />
    <circle cx="16" cy="8" r="1" fill="currentColor" />
  </svg>
);

/**
 * Metronome — Web Audio APIベースの高精度メトロノーム
 * 
 * BPMに合わせてクリック音を生成。
 * 1拍目は高い音で強調、2-4拍目は低い音。
 */

export function Metronome({ bpm = 120, beatsPerBar = 4, isPlaying = false, audioRef, structuredData }) {
    const [active, setActive] = useState(false);
    const [currentBeat, setCurrentBeat] = useState(0);
    const [metronomeVolume, setMetronomeVolume] = useState(() =>
        parseFloat(localStorage.getItem('nc-metronome-vol') || '0.5')
    );
    const handleVolumeChange = useCallback((v) => {
        setMetronomeVolume(v);
        localStorage.setItem('nc-metronome-vol', v.toString());
    }, []);
    const audioCtxRef = useRef(null);
    const timerRef = useRef(null);
    const beatRef = useRef(0);
    const nextNoteTimeRef = useRef(0);

    const getAudioContext = useCallback(() => {
        if (!audioCtxRef.current) {
            audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
        }
        return audioCtxRef.current;
    }, []);

    const playClick = useCallback((time, isAccent) => {
        const ctx = getAudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.connect(gain);
        gain.connect(ctx.destination);

        // アクセント(1拍目)は高い音・大きめ、それ以外は低い音・小さめ
        osc.frequency.value = isAccent ? 1000 : 700;
        osc.type = 'sine';

        const vol = metronomeVolume * (isAccent ? 1.0 : 0.6);
        gain.gain.setValueAtTime(vol, time);
        gain.gain.exponentialRampToValueAtTime(0.001, time + 0.05);

        osc.start(time);
        osc.stop(time + 0.05);
    }, [getAudioContext, metronomeVolume]);

    const scheduleBeats = useCallback(() => {
        const ctx = getAudioContext();
        const interval = 60.0 / bpm;

        // スケジュール先読み: 100ms先まで
        while (nextNoteTimeRef.current < ctx.currentTime + 0.1) {
            const isAccent = beatRef.current === 0;
            playClick(nextNoteTimeRef.current, isAccent);
            setCurrentBeat(beatRef.current);
            beatRef.current = (beatRef.current + 1) % beatsPerBar;
            nextNoteTimeRef.current += interval;
        }
    }, [bpm, beatsPerBar, playClick, getAudioContext]);

    // Active ref for requestAnimationFrame loop
    const activeRef = useRef(active);
    useEffect(() => {
        activeRef.current = active;
    }, [active]);

    const lastAudioTimeRef = useRef(0);
    const lastCheckedBeatIdxRef = useRef(-1);

    // Audio Playback-locked metronome loop (when playing)
    useEffect(() => {
        if (!active || !isPlaying || !audioRef?.current || !structuredData?.length) {
            return;
        }

        const audio = audioRef.current;
        const ctx = getAudioContext();
        if (ctx.state === 'suspended') ctx.resume();

        // Initialize / Reset tracking on play
        lastAudioTimeRef.current = audio.currentTime;
        
        let initialIdx = -1;
        for (let i = 0; i < structuredData.length; i++) {
            if (structuredData[i].time <= audio.currentTime) {
                initialIdx = i;
            } else {
                break;
            }
        }
        lastCheckedBeatIdxRef.current = initialIdx;

        let frameId = null;

        const loop = () => {
            if (!activeRef.current) return;

            const audioCurrentTime = audio.currentTime;
            const delta = audioCurrentTime - lastAudioTimeRef.current;

            // Handle seeks or loops
            if (Math.abs(delta) > 0.5) {
                let bestIdx = -1;
                for (let i = 0; i < structuredData.length; i++) {
                    if (structuredData[i].time <= audioCurrentTime) {
                        bestIdx = i;
                    } else {
                        break;
                    }
                }
                lastCheckedBeatIdxRef.current = bestIdx;
            } else if (delta > 0) {
                // Audio is playing forward
                let idx = lastCheckedBeatIdxRef.current + 1;
                while (idx < structuredData.length && structuredData[idx].time <= audioCurrentTime) {
                    const beatObj = structuredData[idx];
                    
                    if (beatObj.time > lastAudioTimeRef.current) {
                        const isAccent = beatObj.beat === 1;
                        playClick(ctx.currentTime, isAccent);
                        setCurrentBeat(beatObj.beat - 1);
                    }
                    
                    lastCheckedBeatIdxRef.current = idx;
                    idx++;
                }
            }

            lastAudioTimeRef.current = audioCurrentTime;
            frameId = requestAnimationFrame(loop);
        };

        frameId = requestAnimationFrame(loop);

        return () => {
            if (frameId) cancelAnimationFrame(frameId);
        };
    }, [active, isPlaying, audioRef, structuredData, playClick, getAudioContext]);

    // Steady BPM metronome loop (when paused or stopped)
    useEffect(() => {
        if (active && (!isPlaying || !audioRef?.current || !structuredData?.length)) {
            const ctx = getAudioContext();
            if (ctx.state === 'suspended') ctx.resume();
            beatRef.current = 0;
            nextNoteTimeRef.current = ctx.currentTime + 0.05;
            timerRef.current = setInterval(scheduleBeats, 25);
        } else {
            if (timerRef.current) {
                clearInterval(timerRef.current);
                timerRef.current = null;
            }
            if (!active) {
                setCurrentBeat(0);
            }
        }
        return () => {
            if (timerRef.current) clearInterval(timerRef.current);
        };
    }, [active, isPlaying, audioRef, structuredData, scheduleBeats, getAudioContext]);

    // Restart timer when BPM changes in paused state
    useEffect(() => {
        if (active && timerRef.current && (!isPlaying || !audioRef?.current || !structuredData?.length)) {
            clearInterval(timerRef.current);
            const ctx = getAudioContext();
            nextNoteTimeRef.current = ctx.currentTime + 0.05;
            beatRef.current = 0;
            timerRef.current = setInterval(scheduleBeats, 25);
        }
    }, [bpm, active, isPlaying, audioRef, structuredData, scheduleBeats, getAudioContext]);

    const toggle = () => setActive(a => !a);

    return (
        <div className="metronome-container">
            <button
                className={`metronome-btn ${active ? 'metronome-active' : ''}`}
                onClick={toggle}
                title={active ? 'メトロノーム停止' : 'メトロノーム開始'}
            >
                <span className="metronome-icon" style={{ display: 'flex', alignItems: 'center' }}>
                    <MetronomeIcon size={16} />
                </span>
                <span className="metronome-label">
                    {active ? 'ON' : 'OFF'}
                </span>
            </button>
            <div className="metronome-display">
                <div className="metronome-beats">
                    {Array.from({ length: beatsPerBar }, (_, i) => (
                        <span
                            key={i}
                            className={`metronome-dot ${active && i === currentBeat ? 'metronome-dot-active' : ''} ${i === 0 ? 'metronome-dot-accent' : ''}`}
                        />
                    ))}
                </div>
                <input
                    type="range"
                    className="metronome-volume"
                    min="0"
                    max="1"
                    step="0.1"
                    value={metronomeVolume}
                    onChange={e => handleVolumeChange(parseFloat(e.target.value))}
                    title={`音量: ${Math.round(metronomeVolume * 100)}%`}
                />
            </div>
        </div>
    );
}

export default Metronome;
