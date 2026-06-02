import React from 'react';
import { getChordFingering } from '../utils/chordDictionary';

export default function GuitarChord({ chordName, transpose = 0 }) {
    const fingering = getChordFingering(chordName);
    if (!fingering) return null;

    const baseFret = fingering.baseFret || 1;
    const { frets, barre } = fingering;

    // Dimensions
    const startX = 12;
    const spacingX = 12; // distance between frets
    const startY = 8;
    const spacingY = 6;  // distance between strings
    const numFrets = 4;

    const getStringY = (i) => startY + (5 - i) * spacingY;

    return (
        <svg 
            width="55" 
            height="40" 
            viewBox="-4 0 60 40" 
            className="text-[var(--gf-text)]"
            style={{ display: 'block', margin: '0 auto', overflow: 'visible' }}
        >
            {/* Base Fret Label */}
            {baseFret > 1 && (
                <text x={startX + 6} y={startY - 4} fontSize="8" fill="currentColor" textAnchor="middle">
                    {baseFret}fr
                </text>
            )}

            {/* Nut / Left Line */}
            <line 
                x1={startX} 
                y1={startY} 
                x2={startX} 
                y2={startY + 5 * spacingY} 
                stroke="currentColor" 
                strokeWidth={baseFret === 1 ? "3" : "1"} 
            />

            {/* Strings (Horizontal) */}
            {[0, 1, 2, 3, 4, 5].map(i => {
                const y = getStringY(i);
                return (
                    <line 
                        key={`string-${i}`}
                        x1={startX} 
                        y1={y} 
                        x2={startX + numFrets * spacingX} 
                        y2={y} 
                        stroke="currentColor" 
                        strokeWidth="0.8" 
                    />
                );
            })}

            {/* Frets (Vertical) */}
            {[1, 2, 3, 4].map(i => (
                <line 
                    key={`fret-${i}`}
                    x1={startX + i * spacingX} 
                    y1={startY} 
                    x2={startX + i * spacingX} 
                    y2={startY + 5 * spacingY} 
                    stroke="currentColor" 
                    strokeWidth="0.8" 
                />
            ))}

            {/* Barre */}
            {barre && (
                <line 
                    x1={startX + (barre.fret - baseFret) * spacingX + spacingX / 2}
                    y1={getStringY(barre.to)}
                    x2={startX + (barre.fret - baseFret) * spacingX + spacingX / 2}
                    y2={getStringY(barre.from)}
                    stroke="#ef4444"
                    strokeWidth="5"
                    strokeLinecap="round"
                />
            )}

            {/* Dots and open/muted labels */}
            {frets.map((fret, i) => {
                const y = getStringY(i);
                if (fret === -1) {
                    return (
                        <text 
                            key={`dot-${i}`}
                            x={startX - 6} 
                            y={y + 3} 
                            fontSize="8" 
                            fill="currentColor" 
                            textAnchor="middle"
                        >
                            ×
                        </text>
                    );
                }
                if (fret === 0) {
                    return (
                        <circle 
                            key={`dot-${i}`}
                            cx={startX - 6} 
                            cy={y} 
                            r="2" 
                            fill="none" 
                            stroke="currentColor" 
                            strokeWidth="1" 
                        />
                    );
                }
                
                // If this fret is covered by barre, don't draw a separate dot
                if (barre && fret === barre.fret && i >= barre.from && i <= barre.to) {
                    return null;
                }

                // Normal dot
                return (
                    <circle 
                        key={`dot-${i}`}
                        cx={startX + (fret - baseFret) * spacingX + spacingX / 2} 
                        cy={y} 
                        r="2.5" 
                        fill="#ef4444" 
                    />
                );
            })}
        </svg>
    );
}
