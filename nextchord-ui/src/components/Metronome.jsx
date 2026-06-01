import React, { useState, useEffect, useRef, useCallback } from 'react';

/**
 * Metronome — Web Audio APIベースの高精度メトロノーム
 * 
 * BPMに合わせてクリック音を生成。
 * 1拍目は高い音で強調、2-4拍目は低い音。
 */
export function Metronome({ bpm = 120, beatsPerBar = 4, isPlaying = false }) {
    const [active, setActive] = useState(false);
    const [currentBeat, setCurrentBeat] = useState(0);
    const [metronomeVolume, setMetronomeVolume] = useState(() =>
        parseFloat(localStorage.getItem('nc-metronome-vol') || '0.5')
    );
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

    useEffect(() => {
        if (active) {
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
            setCurrentBeat(0);
        }
        return () => {
            if (timerRef.current) clearInterval(timerRef.current);
        };
    }, [active, scheduleBeats, getAudioContext]);

    // BPM変更時にリスタート
    useEffect(() => {
        if (active && timerRef.current) {
            clearInterval(timerRef.current);
            const ctx = getAudioContext();
            nextNoteTimeRef.current = ctx.currentTime + 0.05;
            beatRef.current = 0;
            timerRef.current = setInterval(scheduleBeats, 25);
        }
    }, [bpm]);

    const handleVolumeChange = (v) => {
        setMetronomeVolume(v);
        localStorage.setItem('nc-metronome-vol', v.toString());
    };

    const toggle = () => setActive(a => !a);

    return (
        <div className="metronome-container">
            <button
                className={`metronome-btn ${active ? 'metronome-active' : ''}`}
                onClick={toggle}
                title={active ? 'メトロノーム停止' : 'メトロノーム開始'}
            >
                <span className="metronome-icon">🎵</span>
                <span className="metronome-label">
                    {active ? 'ON' : 'OFF'}
                </span>
            </button>
            {active && (
                <div className="metronome-display">
                    <div className="metronome-beats">
                        {Array.from({ length: beatsPerBar }, (_, i) => (
                            <span
                                key={i}
                                className={`metronome-dot ${i === currentBeat ? 'metronome-dot-active' : ''} ${i === 0 ? 'metronome-dot-accent' : ''}`}
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
            )}
        </div>
    );
}

export default Metronome;
