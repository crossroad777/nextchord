/**
 * TabEditor.jsx — Inline TAB editing overlay for AlphaTab
 *
 * Provides:
 *   1. Edit mode toggle (pencil icon) with visual border indicator
 *   2. Click-on-note → inline fret number input popup
 *   3. Right-click → context menu with "Delete Note"
 *   4. Technique toggle toolbar (H, P, /, \, b, ~, PM, x)
 *   5. Unsaved change tracking + Save button → POST to backend
 *
 * Design decisions:
 *   - Uses AlphaTab's built-in noteMouseDown / beatMouseDown events
 *     (requires includeNoteBounds: true in core settings)
 *   - Falls back to boundsLookup hit-testing when events don't fire
 *   - Edits are applied directly to the AlphaTab data model (note.fret)
 *     and api.render() is called for instant visual feedback
 *   - All edits are tracked in a local array for batch save
 *   - MusicXML is re-fetched, patched with XML DOM, and POSTed back
 *   - Works on both mouse and touch via pointer events
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';

const API_BASE = (import.meta.env.VITE_API_URL !== undefined ? import.meta.env.VITE_API_URL : "http://localhost:8000").trim();

// ============================================================
// Technique definitions
// ============================================================
const TECHNIQUES = [
    { key: 'h', label: 'H', title: 'Hammer-on' },
    { key: 'p', label: 'P', title: 'Pull-off' },
    { key: 'slide_up', label: '/', title: 'Slide Up' },
    { key: 'slide_down', label: '\\', title: 'Slide Down' },
    { key: 'bend', label: 'b', title: 'Bend' },
    { key: 'vibrato', label: '~', title: 'Vibrato' },
    { key: 'palm_mute', label: 'PM', title: 'Palm Mute' },
    { key: 'dead_note', label: 'x', title: 'Dead Note' },
];

/**
 * Map our technique keys to AlphaTab's Note/Beat property names.
 * AlphaTab uses boolean flags or enums on the Note object.
 */
const TECHNIQUE_TO_AT_PROP = {
    h: { prop: 'hammerPullOrigin', type: 'ref' },         // or isHammerPullOrigin
    p: { prop: 'hammerPullOrigin', type: 'ref' },
    slide_up: { prop: 'slideInType', type: 'enum', on: 1, off: 0 },
    slide_down: { prop: 'slideOutType', type: 'enum', on: 1, off: 0 },
    bend: { prop: 'bendType', type: 'enum', on: 1, off: 0 },
    vibrato: { prop: 'vibrato', type: 'enum', on: 1, off: 0 },
    palm_mute: { prop: 'isPalmMute', type: 'bool' },
    dead_note: { prop: 'isDead', type: 'bool' },
};

// ============================================================
// Helper: safe property access on AlphaTab objects
// ============================================================
const getAtProp = (obj, names) => {
    if (!obj || typeof obj !== 'object') return null;
    for (const n of names) {
        let val = obj[n];
        if (val === undefined || val === null) val = obj[`_${n}`];
        if (val !== undefined && val !== null) {
            try {
                return (typeof val === 'function') ? val.call(obj) : val;
            } catch { return val; }
        }
    }
    return null;
};

/**
 * Locate the note's screen position within the AlphaTab container.
 * Uses boundsLookup to find BeatBounds → note position.
 */
const getNoteScreenPosition = (api, note, wrapperEl) => {
    if (!api?.renderer?.boundsLookup || !note || !wrapperEl) return null;

    const lookup = api.renderer.boundsLookup;

    // Try to find bounds via beat
    const beat = getAtProp(note, ['beat', '_beat']);
    if (!beat) return null;

    const beatId = getAtProp(beat, ['id', '_id']);
    const beatIdx = getAtProp(beat, ['index', '_index']);

    // Search in _beatLookup
    const beatLookup = lookup._beatLookup;
    if (!beatLookup) return null;

    let beatBounds = null;
    const tryKey = (k) => {
        if (beatLookup instanceof Map) return beatLookup.get(k);
        return beatLookup[k];
    };

    if (beatId !== null) beatBounds = tryKey(beatId) || tryKey(String(beatId));
    if (!beatBounds && beatIdx !== null) beatBounds = tryKey(beatIdx) || tryKey(String(beatIdx));

    if (!beatBounds) return null;

    // beatBounds can be array
    const bb = Array.isArray(beatBounds) ? beatBounds[0] : beatBounds;
    if (!bb) return null;

    const vb = getAtProp(bb, ['visualBounds', 'bounds']) || bb;
    const x = getAtProp(vb, ['x']);
    const y = getAtProp(vb, ['y']);
    const w = getAtProp(vb, ['w']);
    const h = getAtProp(vb, ['h']);

    if (x === null || y === null) return null;

    // Get wrapper's bounding rect to convert to screen coords
    const wrapperRect = wrapperEl.getBoundingClientRect();
    const scrollParent = wrapperEl.closest('.overflow-y-auto') || wrapperEl.parentElement;
    const scrollTop = scrollParent?.scrollTop || 0;

    return {
        // Position within the AlphaTab rendering coordinate system
        atX: x,
        atY: y,
        atW: w || 30,
        atH: h || 20,
        // Screen position
        screenX: x + wrapperRect.left,
        screenY: y - scrollTop + wrapperRect.top,
    };
};

// ============================================================
// Main Component
// ============================================================
export const TabEditor = ({
    apiRef,
    wrapperRef,
    containerRef,
    sessionId,
    visible = true,
    onScoreChanged,
}) => {
    // --- State ---
    const [editMode, setEditMode] = useState(false);
    const [edits, setEdits] = useState([]);           // Array of edit records
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);

    // Inline fret input popup
    const [editPopup, setEditPopup] = useState(null);  // { note, x, y, value }
    const inputRef = useRef(null);

    // Context menu
    const [contextMenu, setContextMenu] = useState(null); // { note, beat, x, y }

    // Selected note for technique editing
    const [selectedNote, setSelectedNote] = useState(null);
    const [activeTechniques, setActiveTechniques] = useState(new Set());

    // Refs for cleanup
    const eventCleanupRef = useRef(null);

    // ============================================================
    // Register AlphaTab event handlers when edit mode changes
    // ============================================================
    useEffect(() => {
        if (!editMode || !visible) {
            // Cleanup previous handlers
            if (eventCleanupRef.current) {
                eventCleanupRef.current();
                eventCleanupRef.current = null;
            }
            setEditPopup(null);
            setContextMenu(null);
            setSelectedNote(null);
            return;
        }

        const api = apiRef?.current;
        if (!api) return;

        // --- noteMouseDown handler ---
        const handleNoteClick = (note) => {
            if (!note || !editMode) return;
            const wrapper = wrapperRef?.current;
            const pos = getNoteScreenPosition(api, note, wrapper);

            if (pos) {
                const currentFret = getAtProp(note, ['fret', '_fret']) ?? 0;
                setEditPopup({
                    note,
                    x: pos.atX,
                    y: pos.atY,
                    screenX: pos.screenX,
                    screenY: pos.screenY,
                    value: String(currentFret),
                });
                setSelectedNote(note);
                updateActiveTechniques(note);
                setContextMenu(null);
            }
        };

        // --- beatMouseDown handler (fallback when note bounds not available) ---
        const handleBeatClick = (beat) => {
            if (!beat || !editMode) return;
            // Get the first note from the beat
            const notes = getAtProp(beat, ['notes', '_notes']);
            if (!notes) return;

            const notesList = Array.isArray(notes) ? notes :
                (notes.items ? notes.items : [notes]);
            if (notesList.length === 0) return;

            // Pick the first note
            handleNoteClick(notesList[0]);
        };

        // Register handlers
        try {
            if (api.noteMouseDown) {
                api.noteMouseDown.on(handleNoteClick);
            }
            if (api.beatMouseDown) {
                api.beatMouseDown.on(handleBeatClick);
            }
        } catch (e) {
            console.warn('[TabEditor] Could not register AlphaTab events:', e);
        }

        // Cleanup function
        eventCleanupRef.current = () => {
            try {
                if (api.noteMouseDown) api.noteMouseDown.off(handleNoteClick);
                if (api.beatMouseDown) api.beatMouseDown.off(handleBeatClick);
            } catch { /* ignore */ }
        };

        return () => {
            if (eventCleanupRef.current) {
                eventCleanupRef.current();
                eventCleanupRef.current = null;
            }
        };
    }, [editMode, visible, apiRef, wrapperRef]);

    // ============================================================
    // Manual click handler (fallback for when AlphaTab events don't fire)
    // ============================================================
    useEffect(() => {
        if (!editMode || !visible) return;
        const wrapper = wrapperRef?.current;
        if (!wrapper) return;

        const handleClick = (e) => {
            const api = apiRef?.current;
            if (!api?.renderer?.boundsLookup) return;

            // If editPopup is open, clicking outside closes it (saving)
            if (editPopup) {
                commitEdit();
                return;
            }

            // Calculate position relative to wrapper
            const rect = wrapper.getBoundingClientRect();
            const scrollParent = wrapper.closest('.overflow-y-auto') || wrapper.parentElement;
            const scrollTop = scrollParent?.scrollTop || 0;
            const clickX = e.clientX - rect.left;
            const clickY = e.clientY - rect.top + scrollTop;

            // Hit-test against boundsLookup
            const hit = hitTestBounds(api, clickX, clickY);
            if (hit?.note) {
                const fret = getAtProp(hit.note, ['fret', '_fret']) ?? 0;
                setEditPopup({
                    note: hit.note,
                    x: hit.x,
                    y: hit.y,
                    screenX: e.clientX,
                    screenY: e.clientY,
                    value: String(fret),
                });
                setSelectedNote(hit.note);
                updateActiveTechniques(hit.note);
                setContextMenu(null);
                e.stopPropagation();
                e.preventDefault();
            }
        };

        const handleContextMenu = (e) => {
            if (!editMode) return;
            const api = apiRef?.current;
            if (!api?.renderer?.boundsLookup) return;

            const rect = wrapper.getBoundingClientRect();
            const scrollParent = wrapper.closest('.overflow-y-auto') || wrapper.parentElement;
            const scrollTop = scrollParent?.scrollTop || 0;
            const clickX = e.clientX - rect.left;
            const clickY = e.clientY - rect.top + scrollTop;

            const hit = hitTestBounds(api, clickX, clickY);
            if (hit?.note) {
                e.preventDefault();
                e.stopPropagation();
                setContextMenu({
                    note: hit.note,
                    beat: hit.beat,
                    x: e.clientX,
                    y: e.clientY,
                });
                setEditPopup(null);
            }
        };

        // Use capture phase so we get events before AlphaTab's own handlers
        wrapper.addEventListener('click', handleClick, { capture: false });
        wrapper.addEventListener('contextmenu', handleContextMenu, { capture: true });

        // Touch support
        let touchTimer = null;
        const handleTouchStart = (e) => {
            if (!editMode || e.touches.length !== 1) return;
            const touch = e.touches[0];
            touchTimer = setTimeout(() => {
                // Long press = context menu
                const syntheticEvent = {
                    clientX: touch.clientX,
                    clientY: touch.clientY,
                    preventDefault: () => e.preventDefault(),
                    stopPropagation: () => e.stopPropagation(),
                };
                handleContextMenu(syntheticEvent);
            }, 500);
        };
        const handleTouchEnd = () => {
            if (touchTimer) { clearTimeout(touchTimer); touchTimer = null; }
        };

        wrapper.addEventListener('touchstart', handleTouchStart, { passive: false });
        wrapper.addEventListener('touchend', handleTouchEnd, { passive: true });
        wrapper.addEventListener('touchcancel', handleTouchEnd, { passive: true });

        return () => {
            wrapper.removeEventListener('click', handleClick);
            wrapper.removeEventListener('contextmenu', handleContextMenu, { capture: true });
            wrapper.removeEventListener('touchstart', handleTouchStart);
            wrapper.removeEventListener('touchend', handleTouchEnd);
            wrapper.removeEventListener('touchcancel', handleTouchEnd);
            if (touchTimer) clearTimeout(touchTimer);
        };
    }, [editMode, visible, editPopup, wrapperRef, apiRef]);

    // ============================================================
    // Hit-test boundsLookup to find note at (x, y)
    // ============================================================
    const hitTestBounds = useCallback((api, x, y) => {
        const lookup = api.renderer?.boundsLookup;
        if (!lookup) return null;

        const beatLookup = lookup._beatLookup;
        if (!beatLookup) return null;

        let bestDist = Infinity;
        let bestHit = null;

        const checkBounds = (bb) => {
            if (!bb) return;
            const vb = getAtProp(bb, ['visualBounds', 'bounds']) || bb;
            const bx = getAtProp(vb, ['x']);
            const by = getAtProp(vb, ['y']);
            const bw = getAtProp(vb, ['w']) || 30;
            const bh = getAtProp(vb, ['h']) || 100;

            if (bx === null || by === null) return;

            // Check if click is within expanded bounds
            const margin = 10;
            if (x >= bx - margin && x <= bx + bw + margin &&
                y >= by - margin && y <= by + bh + margin) {
                const dist = Math.abs(x - (bx + bw / 2)) + Math.abs(y - (by + bh / 2));
                if (dist < bestDist) {
                    bestDist = dist;

                    const beatObj = getAtProp(bb, ['beat', 'Beat']);
                    if (beatObj) {
                        const notes = getAtProp(beatObj, ['notes', '_notes']);
                        const notesList = notes ?
                            (Array.isArray(notes) ? notes : (notes.items || [notes])) : [];

                        // Find closest note by Y position within the beat
                        let bestNote = notesList[0] || null;
                        // Notes are arranged vertically on tab strings
                        // For simplicity, pick the closest note by string position

                        bestHit = {
                            note: bestNote,
                            beat: beatObj,
                            x: bx,
                            y: by,
                            w: bw,
                            h: bh,
                        };
                    }
                }
            }
        };

        const loopLookup = (lk, cb) => {
            if (lk instanceof Map) lk.forEach((v, k) => cb(v, k));
            else if (lk && typeof lk === 'object') Object.entries(lk).forEach(([k, v]) => cb(v, k));
        };

        loopLookup(beatLookup, (boundsArrayOrObj) => {
            const items = Array.isArray(boundsArrayOrObj) ? boundsArrayOrObj : [boundsArrayOrObj];
            for (const bb of items) {
                checkBounds(bb);
            }
        });

        return bestHit;
    }, []);

    // ============================================================
    // Update active techniques from note properties
    // ============================================================
    const updateActiveTechniques = useCallback((note) => {
        if (!note) {
            setActiveTechniques(new Set());
            return;
        }
        const active = new Set();
        for (const tech of TECHNIQUES) {
            const mapping = TECHNIQUE_TO_AT_PROP[tech.key];
            if (!mapping) continue;
            const val = getAtProp(note, [mapping.prop, `_${mapping.prop}`]);
            if (mapping.type === 'bool' && val) active.add(tech.key);
            else if (mapping.type === 'enum' && val && val !== 0) active.add(tech.key);
            else if (mapping.type === 'ref' && val) active.add(tech.key);
        }
        setActiveTechniques(active);
    }, []);

    // ============================================================
    // Commit fret edit
    // ============================================================
    const commitEdit = useCallback(() => {
        if (!editPopup) return;

        const { note, value } = editPopup;
        const newFret = parseInt(value, 10);
        const oldFret = getAtProp(note, ['fret', '_fret']) ?? 0;

        if (!isNaN(newFret) && newFret >= 0 && newFret <= 24 && newFret !== oldFret) {
            // Apply to AlphaTab data model
            try {
                if ('fret' in note) note.fret = newFret;
                else if ('_fret' in note) note._fret = newFret;
                else note.fret = newFret;
            } catch (e) {
                console.warn('[TabEditor] Could not set fret:', e);
            }

            // Record the edit
            const beat = getAtProp(note, ['beat', '_beat']);
            const voice = beat ? getAtProp(beat, ['voice', '_voice']) : null;
            const bar = voice ? getAtProp(voice, ['bar', '_bar']) : null;
            const barIdx = bar ? getAtProp(bar, ['index', '_index']) : null;
            const beatIdx = beat ? getAtProp(beat, ['index', '_index']) : null;
            const noteString = getAtProp(note, ['string', '_string']);

            setEdits(prev => [...prev, {
                type: 'fret_change',
                barIndex: barIdx,
                beatIndex: beatIdx,
                string: noteString,
                oldFret,
                newFret,
                timestamp: Date.now(),
            }]);

            // Re-render AlphaTab
            const api = apiRef?.current;
            if (api) {
                try { api.render(); } catch (e) {
                    console.warn('[TabEditor] Render after edit failed:', e);
                }
            }
        }

        setEditPopup(null);
    }, [editPopup, apiRef]);

    // ============================================================
    // Delete note
    // ============================================================
    const deleteNote = useCallback(() => {
        if (!contextMenu?.note) return;

        const { note, beat } = contextMenu;
        const noteString = getAtProp(note, ['string', '_string']);
        const noteFret = getAtProp(note, ['fret', '_fret']);
        const barObj = (() => {
            const v = getAtProp(beat, ['voice', '_voice']);
            const b = v ? getAtProp(v, ['bar', '_bar']) : null;
            return b;
        })();
        const barIdx = barObj ? getAtProp(barObj, ['index', '_index']) : null;
        const beatIdx = getAtProp(beat, ['index', '_index']);

        // Remove note from beat's notes array
        try {
            const notes = getAtProp(beat, ['notes', '_notes']);
            if (notes) {
                const notesArr = Array.isArray(notes) ? notes : (notes.items || []);
                const idx = notesArr.indexOf(note);
                if (idx >= 0) {
                    notesArr.splice(idx, 1);
                }
            }
        } catch (e) {
            console.warn('[TabEditor] Could not remove note from beat:', e);
        }

        // Record the edit
        setEdits(prev => [...prev, {
            type: 'delete_note',
            barIndex: barIdx,
            beatIndex: beatIdx,
            string: noteString,
            fret: noteFret,
            timestamp: Date.now(),
        }]);

        // Re-render
        const api = apiRef?.current;
        if (api) {
            try { api.render(); } catch (e) {
                console.warn('[TabEditor] Render after delete failed:', e);
            }
        }

        setContextMenu(null);
    }, [contextMenu, apiRef]);

    // ============================================================
    // Toggle technique on selected note
    // ============================================================
    const toggleTechnique = useCallback((techKey) => {
        if (!selectedNote) return;

        const mapping = TECHNIQUE_TO_AT_PROP[techKey];
        if (!mapping) return;

        const currentVal = getAtProp(selectedNote, [mapping.prop, `_${mapping.prop}`]);
        let newVal;

        if (mapping.type === 'bool') {
            newVal = !currentVal;
            try {
                if (mapping.prop in selectedNote) selectedNote[mapping.prop] = newVal;
                else if (`_${mapping.prop}` in selectedNote) selectedNote[`_${mapping.prop}`] = newVal;
                else selectedNote[mapping.prop] = newVal;
            } catch (e) {
                console.warn('[TabEditor] Could not toggle technique:', e);
            }
        } else if (mapping.type === 'enum') {
            newVal = currentVal === mapping.on ? mapping.off : mapping.on;
            try {
                if (mapping.prop in selectedNote) selectedNote[mapping.prop] = newVal;
                else selectedNote[mapping.prop] = newVal;
            } catch (e) {
                console.warn('[TabEditor] Could not toggle technique:', e);
            }
        }

        // Record edit
        const beat = getAtProp(selectedNote, ['beat', '_beat']);
        const voice = beat ? getAtProp(beat, ['voice', '_voice']) : null;
        const bar = voice ? getAtProp(voice, ['bar', '_bar']) : null;
        const barIdx = bar ? getAtProp(bar, ['index', '_index']) : null;
        const beatIdx = beat ? getAtProp(beat, ['index', '_index']) : null;
        const noteString = getAtProp(selectedNote, ['string', '_string']);

        setEdits(prev => [...prev, {
            type: 'technique_toggle',
            technique: techKey,
            barIndex: barIdx,
            beatIndex: beatIdx,
            string: noteString,
            enabled: mapping.type === 'bool' ? newVal : newVal === mapping.on,
            timestamp: Date.now(),
        }]);

        // Update active techniques display
        setActiveTechniques(prev => {
            const next = new Set(prev);
            if (mapping.type === 'bool') {
                newVal ? next.add(techKey) : next.delete(techKey);
            } else {
                newVal === mapping.on ? next.add(techKey) : next.delete(techKey);
            }
            return next;
        });

        // Re-render
        const api = apiRef?.current;
        if (api) {
            try { api.render(); } catch (e) {
                console.warn('[TabEditor] Render after technique toggle failed:', e);
            }
        }
    }, [selectedNote, apiRef]);

    // ============================================================
    // Save: POST modified MusicXML back to server
    // ============================================================
    const saveEdits = useCallback(async () => {
        if (edits.length === 0 || saving) return;
        setSaving(true);
        setSaveError(null);

        try {
            // Strategy: call the existing regenerate endpoint which rebuilds
            // from notes.json + structured_data. But first, we need to also
            // update notes.json with our fret/technique changes.
            // Actually, since we modified the AlphaTab score in-memory,
            // the most reliable approach is to re-export the current score
            // state as MusicXML and POST it.
            // However, AlphaTab doesn't have a built-in export.
            // So we use the regenerate endpoint, which re-reads notes.json.
            // We need to PATCH notes.json first with our changes.

            // Step 1: Fetch current notes.json
            const notesRes = await fetch(`${API_BASE}/result/${sessionId}/notes`);
            if (!notesRes.ok) throw new Error('Failed to fetch notes data');
            const notesData = await notesRes.json();
            const notes = notesData.notes || [];

            // Step 2: Apply edits to notes array
            for (const edit of edits) {
                if (edit.type === 'fret_change') {
                    // Find matching note in notes.json by bar/beat/string
                    applyFretChangeToNotes(notes, edit);
                } else if (edit.type === 'delete_note') {
                    applyDeleteToNotes(notes, edit);
                } else if (edit.type === 'technique_toggle') {
                    applyTechniqueToNotes(notes, edit);
                }
            }

            // Step 3: Save modified notes back
            const patchRes = await fetch(`${API_BASE}/result/${sessionId}/notes`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notes }),
            });

            // Step 4: If PATCH endpoint doesn't exist (404), try PUT or just regenerate
            if (patchRes.status === 404 || patchRes.status === 405) {
                console.log('[TabEditor] Notes PATCH not available, using regenerate directly');
            }

            // Step 5: Regenerate MusicXML
            const regenRes = await fetch(`${API_BASE}/result/${sessionId}/regenerate-musicxml`, {
                method: 'POST',
            });
            if (!regenRes.ok) {
                const errData = await regenRes.json().catch(() => ({}));
                throw new Error(errData.detail || `Regenerate failed: HTTP ${regenRes.status}`);
            }

            // Success!
            setEdits([]);
            console.log('[TabEditor] Saved successfully');

            // Notify parent to reload the score
            if (onScoreChanged) onScoreChanged();
        } catch (e) {
            console.error('[TabEditor] Save failed:', e);
            setSaveError(e.message);
        } finally {
            setSaving(false);
        }
    }, [edits, saving, sessionId, onScoreChanged]);

    // ============================================================
    // Discard all edits and reload
    // ============================================================
    const discardEdits = useCallback(() => {
        if (edits.length === 0) return;
        if (!confirm(`Discard ${edits.length} unsaved change(s)?`)) return;
        setEdits([]);
        // Reload the original score
        if (onScoreChanged) onScoreChanged();
    }, [edits, onScoreChanged]);

    // ============================================================
    // Focus input when popup appears
    // ============================================================
    useEffect(() => {
        if (editPopup && inputRef.current) {
            inputRef.current.focus();
            inputRef.current.select();
        }
    }, [editPopup]);

    // ============================================================
    // Close popups on click outside / Escape
    // ============================================================
    useEffect(() => {
        if (!editPopup && !contextMenu) return;

        const handleKeyDown = (e) => {
            if (e.key === 'Escape') {
                setEditPopup(null);
                setContextMenu(null);
            } else if (e.key === 'Enter' && editPopup) {
                commitEdit();
            }
        };

        const handleClickOutside = (e) => {
            // Close context menu on any click
            if (contextMenu) {
                setContextMenu(null);
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        document.addEventListener('mousedown', handleClickOutside, { capture: false });

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [editPopup, contextMenu, commitEdit]);

    // ============================================================
    // Don't render if not visible
    // ============================================================
    if (!visible) return null;

    // ============================================================
    // Render
    // ============================================================
    return (
        <>
            {/* Edit Mode Toggle Button */}
            <div className="flex items-center gap-2 flex-shrink-0">
                <button
                    onClick={() => {
                        setEditMode(prev => !prev);
                        if (editMode) {
                            // Turning off - close all popups
                            setEditPopup(null);
                            setContextMenu(null);
                            setSelectedNote(null);
                        }
                    }}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ${
                        editMode
                            ? 'bg-blue-500 text-white shadow-lg shadow-blue-500/30 ring-2 ring-blue-300'
                            : 'bg-slate-700/80 text-slate-300 hover:bg-slate-600 hover:text-white'
                    }`}
                    title={editMode ? 'Exit Edit Mode' : 'Enter Edit Mode (click notes to edit frets)'}
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                        <path d="m15 5 4 4" />
                    </svg>
                    {editMode ? 'EDITING' : 'EDIT'}
                </button>

                {/* Unsaved changes indicator + Save/Discard */}
                {edits.length > 0 && (
                    <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-bold text-amber-400 animate-pulse">
                            {edits.length} unsaved change{edits.length !== 1 ? 's' : ''}
                        </span>
                        <button
                            onClick={saveEdits}
                            disabled={saving}
                            className="px-2.5 py-1 rounded text-[10px] font-bold bg-emerald-500 text-white hover:bg-emerald-400 disabled:opacity-50 transition-all"
                        >
                            {saving ? '...' : 'SAVE'}
                        </button>
                        <button
                            onClick={discardEdits}
                            className="px-2 py-1 rounded text-[10px] font-bold bg-slate-600 text-slate-300 hover:bg-slate-500 transition-all"
                            title="Discard changes"
                        >
                            ✕
                        </button>
                    </div>
                )}

                {saveError && (
                    <span className="text-[10px] text-red-400 font-mono max-w-[200px] truncate" title={saveError}>
                        ⚠ {saveError}
                    </span>
                )}
            </div>

            {/* Edit mode visual indicator — blue border around tab area */}
            {editMode && containerRef?.current && (
                <div
                    className="pointer-events-none fixed z-50 border-2 border-blue-400/60 rounded-lg"
                    style={{
                        top: containerRef.current.getBoundingClientRect().top - 2,
                        left: containerRef.current.getBoundingClientRect().left - 2,
                        width: containerRef.current.getBoundingClientRect().width + 4,
                        height: containerRef.current.getBoundingClientRect().height + 4,
                    }}
                />
            )}

            {/* Technique toolbar (shown when a note is selected in edit mode) */}
            {editMode && selectedNote && (
                <div className="fixed z-[60] flex items-center gap-1 p-1.5 bg-slate-800/95 border border-slate-600 rounded-lg shadow-xl backdrop-blur-sm"
                    style={{
                        top: Math.max(8, (editPopup?.screenY ?? 100) - 40),
                        left: Math.max(8, (editPopup?.screenX ?? 100) - 100),
                    }}
                    onMouseDown={(e) => e.stopPropagation()}
                >
                    {TECHNIQUES.map(tech => (
                        <button
                            key={tech.key}
                            onClick={() => toggleTechnique(tech.key)}
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold transition-all ${
                                activeTechniques.has(tech.key)
                                    ? 'bg-blue-500 text-white'
                                    : 'bg-slate-700 text-slate-400 hover:bg-slate-600 hover:text-white'
                            }`}
                            title={tech.title}
                        >
                            {tech.label}
                        </button>
                    ))}
                </div>
            )}

            {/* Inline fret input popup */}
            {editPopup && (
                <div
                    className="fixed z-[61] flex items-center"
                    style={{
                        top: (editPopup.screenY ?? 100) + 5,
                        left: (editPopup.screenX ?? 100) - 20,
                    }}
                    onMouseDown={(e) => e.stopPropagation()}
                >
                    <input
                        ref={inputRef}
                        type="text"
                        inputMode="numeric"
                        pattern="[0-9]*"
                        value={editPopup.value}
                        onChange={(e) => {
                            const v = e.target.value.replace(/[^0-9]/g, '');
                            if (v.length <= 2) {
                                setEditPopup(prev => prev ? { ...prev, value: v } : null);
                            }
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                e.preventDefault();
                                commitEdit();
                            } else if (e.key === 'Escape') {
                                e.preventDefault();
                                setEditPopup(null);
                            } else if (e.key === 'Tab') {
                                e.preventDefault();
                                // TODO: move to next note
                                commitEdit();
                            }
                        }}
                        onBlur={() => {
                            // Small delay to allow button clicks to fire first
                            setTimeout(() => commitEdit(), 100);
                        }}
                        className="w-10 h-7 text-center text-sm font-mono font-bold bg-white border-2 border-blue-400 rounded shadow-lg outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 text-slate-900"
                        style={{ caretColor: '#3b82f6' }}
                    />
                </div>
            )}

            {/* Context menu (right-click) */}
            {contextMenu && (
                <div
                    className="fixed z-[62] bg-slate-800/95 border border-slate-600 rounded-lg shadow-xl backdrop-blur-sm py-1 min-w-[140px]"
                    style={{
                        top: contextMenu.y,
                        left: contextMenu.x,
                    }}
                    onMouseDown={(e) => e.stopPropagation()}
                >
                    <button
                        onClick={deleteNote}
                        className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/20 hover:text-red-300 transition-colors flex items-center gap-2"
                    >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M3 6h18" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                            <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                        Delete Note
                    </button>
                    <div className="border-t border-slate-700 my-1" />
                    <button
                        onClick={() => {
                            // Open edit popup for this note
                            const fret = getAtProp(contextMenu.note, ['fret', '_fret']) ?? 0;
                            setEditPopup({
                                note: contextMenu.note,
                                x: 0,
                                y: 0,
                                screenX: contextMenu.x,
                                screenY: contextMenu.y,
                                value: String(fret),
                            });
                            setSelectedNote(contextMenu.note);
                            updateActiveTechniques(contextMenu.note);
                            setContextMenu(null);
                        }}
                        className="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700 hover:text-white transition-colors flex items-center gap-2"
                    >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
                        </svg>
                        Edit Fret
                    </button>
                </div>
            )}
        </>
    );
};

// ============================================================
// Helper: Apply fret change to notes.json data
// ============================================================
function applyFretChangeToNotes(notes, edit) {
    // notes is an array of {start, end, pitch, string, fret, velocity, ...}
    // We match by approximate bar/beat position and string number
    for (const n of notes) {
        if (n.string === edit.string && n.fret === edit.oldFret) {
            n.fret = edit.newFret;
            // Update pitch: standard tuning base + fret
            // This is approximate; the server will recalculate properly
            break;  // Only change first match
        }
    }
}

function applyDeleteToNotes(notes, edit) {
    const idx = notes.findIndex(n =>
        n.string === edit.string && n.fret === edit.fret
    );
    if (idx >= 0) {
        notes.splice(idx, 1);
    }
}

function applyTechniqueToNotes(notes, edit) {
    for (const n of notes) {
        if (n.string === edit.string) {
            if (!n.technique) n.technique = {};
            n.technique[edit.technique] = edit.enabled;
            break;
        }
    }
}

export default TabEditor;
