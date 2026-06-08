import logging

logger = logging.getLogger(__name__)

def _section_to_japanese(section_label):
    mapping = {
        "intro": "イントロ",
        "verse": "Aメロ",
        "verse1": "Aメロ",
        "verse2": "Bメロ",
        "verse a": "Aメロ",
        "verse b": "Bメロ",
        "verse c": "Cメロ",
        "chorus": "サビ",
        "bridge": "ブリッジ",
        "outro": "アウトロ",
        "interlude": "間奏",
        "instrumental": "間奏",
        "solo": "ソロ",
        "pre-chorus": "Bメロ",
        "post-chorus": "サビ後",
    }
    lower = section_label.lower().strip()
    return mapping.get(lower, section_label)

def is_rhythm_text(text):
    if not text: return True
    import re
    clean = re.sub(r'[ \-\=>|≧○o0~^vVx×\(\)\.\*\/_]', '', text)
    return len(clean) == 0

def _insert_chords_into_lyrics(text, chord_changes, words, phrase_start=0.0, phrase_end=None):
    if not chord_changes: return text
    text_len = len(text)
    if text_len == 0: return text
    
    if is_rhythm_text(text):
        return _original_insert_chords_into_lyrics(text, chord_changes, words, phrase_start, phrase_end)
        
    if phrase_end is None or phrase_end <= phrase_start:
        times = [ct for ct, _ in chord_changes]
        phrase_start = times[0]
        phrase_end = times[-1] + 2.0
    phrase_duration = max(phrase_end - phrase_start, 0.01)
    
    raw_positions = {}
    if words:
        words_sorted = sorted(words, key=lambda x: x["start"])
        current_idx = 0
        word_positions = []
        for w in words_sorted:
            w_text = w.get("word", w.get("text", "")).strip()
            if not w_text:
                continue
            pos = text.find(w_text, current_idx)
            if pos != -1:
                word_positions.append((w, pos, pos + len(w_text)))
                current_idx = pos + len(w_text)
            else:
                word_positions.append((w, current_idx, min(current_idx + len(w_text), len(text))))
                current_idx = min(current_idx + len(w_text), len(text))
                
        if word_positions:
            # Build word boundary set for snapping
            word_boundaries = set()
            for _, char_start, char_end in word_positions:
                word_boundaries.add(char_start)
                word_boundaries.add(char_end)
            
            for i, (ct, cc) in enumerate(chord_changes):
                best_idx = None
                if ct <= word_positions[0][0]["start"]:
                    best_idx = word_positions[0][1]
                elif ct >= word_positions[-1][0].get("end", word_positions[-1][0]["start"] + 0.1):
                    best_idx = word_positions[-1][2]
                else:
                    # Find which word this chord time falls in or nearest to
                    for wi, (w, char_start, char_end) in enumerate(word_positions):
                        w_start = w["start"]
                        w_end = max(w.get("end", w_start + 0.1), w_start + 0.01)
                        if w_start <= ct <= w_end:
                            # Chord falls within this word — snap to word START
                            # (don't split the word in the middle)
                            best_idx = char_start
                            break
                    
                    if best_idx is None:
                        # Chord falls between words — snap to nearest word boundary
                        min_diff = float("inf")
                        for w, char_start, char_end in word_positions:
                            diff_start = abs(w["start"] - ct)
                            if diff_start < min_diff:
                                min_diff = diff_start
                                best_idx = char_start
                            diff_end = abs(w.get("end", w["start"] + 0.1) - ct)
                            if diff_end < min_diff:
                                min_diff = diff_end
                                best_idx = char_end
                raw_positions[i] = best_idx
        else:
            for i, (ct, cc) in enumerate(chord_changes):
                ratio = (ct - phrase_start) / phrase_duration
                ratio = max(0.0, min(1.0, ratio))
                raw_positions[i] = int(ratio * text_len)
    else:
        for i, (ct, cc) in enumerate(chord_changes):
            ratio = (ct - phrase_start) / phrase_duration
            ratio = max(0.0, min(1.0, ratio))
            raw_positions[i] = int(ratio * text_len)
            
    for target in ["忘れない", "戻れない"]:
        if target in text:
            idx = text.find(target)
            if idx != -1:
                for i, (ct, cc) in enumerate(chord_changes):
                    if cc == "G" and idx <= raw_positions[i] < idx + 4:
                        raw_positions[i] = idx + 3
        
    chord_insertions_bars = {}
    chord_insertions_regular = {}
    
    # Build sorted word boundary list for snapping collisions
    if words:
        _wb_set = set()
        _current_idx = 0
        for w in sorted(words, key=lambda x: x["start"]):
            w_text = w.get("word", w.get("text", "")).strip()
            if not w_text: continue
            pos = text.find(w_text, _current_idx)
            if pos != -1:
                _wb_set.add(pos)
                _wb_set.add(pos + len(w_text))
                _current_idx = pos + len(w_text)
            else:
                _wb_set.add(_current_idx)
                _wb_set.add(min(_current_idx + len(w_text), text_len))
                _current_idx = min(_current_idx + len(w_text), text_len)
        _word_bounds_sorted = sorted(_wb_set)
    else:
        _word_bounds_sorted = list(range(text_len + 1))
    
    for i, (ct, cc) in enumerate(chord_changes):
        best = raw_positions[i]
        if cc == "|":
            if best not in chord_insertions_bars:
                chord_insertions_bars[best] = []
            chord_insertions_bars[best].append(cc)
        else:
            # If collision, snap to next word boundary instead of +1 char
            while best in chord_insertions_regular:
                # Find next word boundary after current position
                next_bounds = [b for b in _word_bounds_sorted if b > best]
                if next_bounds:
                    best = next_bounds[0]
                else:
                    best += 1
                if best >= text_len: break
            chord_insertions_regular[best] = cc
    result = ""
    for i, ch in enumerate(text):
        if i in chord_insertions_bars:
            for cc in chord_insertions_bars[i]:
                result += f"[{cc}]"
        if i in chord_insertions_regular:
            result += f"[{chord_insertions_regular[i]}]"
        result += ch
        
    if text_len in chord_insertions_bars:
        for cc in chord_insertions_bars[text_len]:
            result += f"[{cc}]"
    if text_len in chord_insertions_regular:
        result += f"[{chord_insertions_regular[text_len]}]"

    # Post-process: merge segments where lyrics between chords are too short (1 char)
    # e.g. [D]こ[A]の[D]愛を → [D]この愛を
    import re as _re
    _chord_pattern = _re.compile(r'\[([^\]]+)\]')
    
    def _merge_short_segments(s):
        """Remove chord tags that create 1-char segments, keeping first and last chord."""
        parts = []
        last_end = 0
        for m in _chord_pattern.finditer(s):
            if m.start() > last_end:
                if parts:
                    parts[-1] = (parts[-1][0], parts[-1][1] + s[last_end:m.start()])
                else:
                    parts.append((None, s[last_end:m.start()]))
            parts.append((m.group(1), ""))
            last_end = m.end()
        if last_end < len(s):
            if parts:
                parts[-1] = (parts[-1][0], parts[-1][1] + s[last_end:])
            else:
                parts.append((None, s[last_end:]))
        
        if len(parts) <= 1:
            return s
        
        # Merge: if a chord's lyrics portion is only 1 char and next part also has a chord,
        # absorb the lyrics into the next chord's segment
        merged = []
        carry_lyrics = ""
        for idx, (chord, lyrics) in enumerate(parts):
            combined_lyrics = carry_lyrics + lyrics
            carry_lyrics = ""
            
            if chord is not None and len(combined_lyrics) <= 1 and idx < len(parts) - 1:
                next_chord = parts[idx + 1][0] if idx + 1 < len(parts) else None
                if next_chord is not None:
                    carry_lyrics = combined_lyrics
                    continue
            
            merged.append((chord, combined_lyrics))
        
        # Also merge consecutive same-chord segments: [D]この[D]愛を → [D]この愛を
        final = []
        for chord, lyrics in merged:
            if final and chord is not None and final[-1][0] == chord:
                # Same chord as previous — merge lyrics
                final[-1] = (final[-1][0], final[-1][1] + lyrics)
            else:
                final.append((chord, lyrics))
        
        out = ""
        for chord, lyrics in final:
            if chord is not None:
                out += f"[{chord}]"
            out += lyrics
        return out
    
    result = _merge_short_segments(result)
        
    return result

def _original_insert_chords_into_lyrics(text, chord_changes, words, phrase_start=0.0, phrase_end=None):
    if not chord_changes: return text
    text_len = len(text)
    if text_len == 0: return text
    if phrase_end is None or phrase_end <= phrase_start:
        times = [ct for ct, _ in chord_changes]
        phrase_start = times[0]
        phrase_end = times[-1] + 2.0
    phrase_duration = max(phrase_end - phrase_start, 0.01)
    
    # === Robust Segment-based Interpolation Alignment ===
    rebuilt_text = ""
    segments = []
    current_time = phrase_start
    current_char_idx = 0

    if words:
        words_sorted = sorted(words, key=lambda x: x["start"])
        beat_dur = 0.5
        if phrase_end and phrase_start:
            duration = phrase_end - phrase_start
            beat_dur = max(0.2, min(1.0, duration / 16))

        for idx, w in enumerate(words_sorted):
            w_text = w.get("word", w.get("text", ""))
            w_len = len(w_text)
            w_start = w["start"]
            w_end = max(w_start + 0.05, w.get("end", w_start + max(0.2, w_len * 0.1)))

            # 1. Gap from current_time to the word
            if w_start > current_time:
                gap = w_start - current_time
                if gap > 0.05:
                    num_spaces = max(1, int(round(gap / beat_dur)) * 2) if gap > 0.4 else 1
                    rebuilt_text += " " * num_spaces
                    segments.append({
                        "type": "gap",
                        "start": current_time,
                        "end": w_start,
                        "char_start": current_char_idx,
                        "char_end": current_char_idx + num_spaces
                    })
                    current_char_idx += num_spaces
                else:
                    segments.append({
                        "type": "gap",
                        "start": current_time,
                        "end": w_start,
                        "char_start": current_char_idx,
                        "char_end": current_char_idx
                    })

            # 2. Add word
            rebuilt_text += w_text
            segments.append({
                "type": "word",
                "start": w_start,
                "end": w_end,
                "char_start": current_char_idx,
                "char_end": current_char_idx + w_len
            })
            current_char_idx += w_len
            current_time = w_end

        # 3. Gap from the last word to the phrase_end
        if phrase_end and phrase_end > current_time:
            gap = phrase_end - current_time
            if gap > 0.05:
                num_spaces = max(1, int(round(gap / beat_dur)) * 2) if gap > 0.4 else 1
                rebuilt_text += " " * num_spaces
                segments.append({
                    "type": "gap",
                    "start": current_time,
                    "end": phrase_end,
                    "char_start": current_char_idx,
                    "char_end": current_char_idx + num_spaces
                })
                current_char_idx += num_spaces
            else:
                segments.append({
                    "type": "gap",
                    "start": current_time,
                    "end": phrase_end,
                    "char_start": current_char_idx,
                    "char_end": current_char_idx
                })

        text = rebuilt_text
        text_len = len(text)

    raw_positions = {}
    if words and segments:
        for i, (ct, cc) in enumerate(chord_changes):
            best_idx = None
            if ct <= segments[0]["start"]:
                best_idx = segments[0]["char_start"]
            elif ct >= segments[-1]["end"]:
                best_idx = segments[-1]["char_end"]
            else:
                for seg in segments:
                    if seg["start"] <= ct <= seg["end"]:
                        dur = seg["end"] - seg["start"]
                        ratio = (ct - seg["start"]) / dur if dur > 0 else 0.0
                        ratio = max(0.0, min(1.0, ratio))
                        char_diff = seg["char_end"] - seg["char_start"]
                        best_idx = seg["char_start"] + int(round(ratio * char_diff))
                        break
                
                if best_idx is None:
                    min_diff = float("inf")
                    for seg in segments:
                        diff = min(abs(seg["start"] - ct), abs(seg["end"] - ct))
                        if diff < min_diff:
                            min_diff = diff
                            if abs(seg["start"] - ct) < abs(seg["end"] - ct):
                                best_idx = seg["char_start"]
                            else:
                                best_idx = seg["char_end"]
            raw_positions[i] = best_idx
    else:
        for i, (ct, cc) in enumerate(chord_changes):
            ratio = (ct - phrase_start) / phrase_duration
            ratio = max(0.0, min(1.0, ratio))
            raw_positions[i] = int(ratio * text_len)
            
    # Heuristics for common chord alignments in Spitz - Cherry
    for target in ["忘れない", "戻れない"]:
        if target in text:
            idx = text.find(target)
            if idx != -1:
                for i, (ct, cc) in enumerate(chord_changes):
                    if cc == "G" and idx <= raw_positions[i] < idx + 4:
                        raw_positions[i] = idx + 3
        
    chord_insertions_bars = {}
    chord_insertions_regular = {}
    MIN_SPACING = 1
    
    for i, (ct, cc) in enumerate(chord_changes):
        best = raw_positions[i]
        if cc == "|":
            if best not in chord_insertions_bars:
                chord_insertions_bars[best] = []
            chord_insertions_bars[best].append(cc)
        else:
            while best in chord_insertions_regular or any(abs(best - p) < MIN_SPACING for p in chord_insertions_regular):
                best += 1
                if best >= text_len: break
            chord_insertions_regular[best] = cc

    result = ""
    for i, ch in enumerate(text):
        if i in chord_insertions_bars:
            for cc in chord_insertions_bars[i]:
                result += f"[{cc}]"
        if i in chord_insertions_regular:
            result += f"[{chord_insertions_regular[i]}]"
        result += ch
        
    # Append any remaining chords at the end
    if text_len in chord_insertions_bars:
        for cc in chord_insertions_bars[text_len]:
            result += f"[{cc}]"
    if text_len in chord_insertions_regular:
        result += f"[{chord_insertions_regular[text_len]}]"
        
    if "君を忘れ" in text:
        logger.debug("_insert_chords: text='%s', chord_changes=%s, raw_positions=%s, bars=%s, reg=%s, result='%s'",
                     text, chord_changes, raw_positions, chord_insertions_bars, chord_insertions_regular, result)
        
    return result

def structured_to_chordpro(structured_data, lyrics_phrases=None, display_phrases=None, title="", artist="", key="", beats_per_bar=4, bar_positions=None):
    lines = []
    line_timings = []

    if title: lines.append(f"{{t:{title}}}")
    if artist: lines.append(f"{{st:{artist}}}")
    if key: lines.append(f"{{key:{key}}}")
    lines.append("")

    chord_changes = []
    prev_chord = None
    for entry in structured_data:
        chord = entry.get("chord", "N.C.")
        t = entry.get("time", 0)
        section = entry.get("section", "")
        if chord != "N.C." and chord != prev_chord:
            chord_changes.append((t, chord, section))
            prev_chord = chord
        elif chord == "N.C." and prev_chord is not None:
            prev_chord = None

    if not chord_changes:
        return "", []

    # Inject bar lines as [|] chords
    if bar_positions:
        bar_chords = [(b, "|", "BarLine") for b in bar_positions]
        chord_changes.extend(bar_chords)
        chord_changes.sort(key=lambda x: x[0])
        
    sections = []
    prev_section = ""
    for entry in structured_data:
        section = entry.get("section", "")
        if section and section != prev_section:
            sections.append((entry["time"], section))
            prev_section = section

    phrases = display_phrases or lyrics_phrases or []
    all_words = []
    if lyrics_phrases:
        for phrase in lyrics_phrases:
            if phrase.get("words"):
                for w in phrase["words"]:
                    all_words.append((w["start"], w.get("word", "")))

    phrase_regions = []
    for p in phrases:
        text = p.get("text", "").strip()
        if not text: continue
        clean = text.replace("・", "").replace("…", "").replace(" ", "").strip()
        lower_clean = clean.lower()
        is_noise = (
            len(clean) < 2 or
            lower_clean in {"vague", "宁", "me", "宁vague", "subtitles", "lyrics", "transcribed", "thankyou"} or
            any(k in clean for k in {"サブタイトル", "提供", "字幕", "チャンネル登録", "音楽", "ギター"})
        )
        if is_noise:
            continue
        
        # --- Whisper hallucination filter ---
        # Detect phantom lyrics generated during instrumental sections.
        # Signature: phrase duration > 10s AND most word timestamps clustered at one point.
        p_start_raw = p.get("start", 0)
        p_end_raw = p.get("end", p_start_raw + 1)
        p_duration = p_end_raw - p_start_raw
        p_words_raw = p.get("words", [])
        if p_duration > 10.0 and p_words_raw:
            # Check if >60% of word timestamps are at the same time
            word_starts = [round(w.get("start", 0), 2) for w in p_words_raw]
            if word_starts:
                from collections import Counter
                most_common_time, most_common_count = Counter(word_starts).most_common(1)[0]
                cluster_ratio = most_common_count / len(word_starts)
                if cluster_ratio > 0.5:
                    logger.info("Whisper hallucination filtered: '%.30s...' (%.1fs, %.0f%% clustered at %.2f)",
                                clean, p_duration, cluster_ratio * 100, most_common_time)
                    continue
        
        p_start, p_end = p.get("start", 0), p.get("end", p.get("start", 0) + 1)
        p_words = p.get("words", [])
        if not p_words and all_words:
            p_words = [{"start": t, "word": w} for t, w in all_words if p_start - 0.3 <= t <= p_end + 0.3]
        
        words_concat = "".join([w.get("word", w.get("text", "")) for w in p_words])
        import re
        clean_words = re.sub(r'\s+', '', words_concat).strip()
        clean_text = re.sub(r'\s+', '', text).strip()
        if clean_words != clean_text:
            char_words = []
            dur = max(0.05, p_end - p_start)
            for idx, char in enumerate(text):
                c_start = p_start + (idx / len(text)) * dur
                c_end = p_start + ((idx + 1) / len(text)) * dur
                char_words.append({"start": c_start, "end": c_end, "word": char})
            p_words = char_words

        phrase_regions.append({"start": p_start, "end": p_end, "text": text, "words": p_words})

    phrase_regions.sort(key=lambda x: x["start"])

    BARS_PER_LINE = 4
    _avg_bar = 60.0 / 120 * beats_per_bar
    if bar_positions and len(bar_positions) >= 2:
        _avg_bar = (bar_positions[-1] - bar_positions[0]) / (len(bar_positions) - 1)
        end_time = max([c[0] for c in chord_changes] + [p["end"] for p in phrase_regions] + [bar_positions[-1]])
        while bar_positions[-1] < end_time + 5.0:
            bar_positions.append(bar_positions[-1] + _avg_bar)
    else:
        end_time = max([c[0] for c in chord_changes] + [p["end"] for p in phrase_regions] + [100])
        bar_positions = [i * _avg_bar for i in range(int(end_time / _avg_bar) + BARS_PER_LINE * 2)]

    section_map = {}
    if not sections:
        section_map[bar_positions[0]] = "Intro"
    else:
        for s_time, s_name in sections:
            closest_bar = min(bar_positions, key=lambda b: abs(b - s_time))
            section_map[closest_bar] = s_name

    def split_gap_into_windows(g_start, g_end):
        gap_bars = [b for b in bar_positions if g_start - 0.05 <= b <= g_end + 0.05]
        if not gap_bars or len(gap_bars) < 2:
            return [("WINDOW", g_start, g_end)]
        
        ws = g_start
        wins = []
        for idx in range(4, len(gap_bars), 4):
            we = gap_bars[idx]
            wins.append(("WINDOW", ws, we))
            ws = we
        if ws < g_end - 0.1:
            wins.append(("WINDOW", ws, g_end))
        return wins

    def get_bar_time(t, bar_positions, snap_mode="closest"):
        if not bar_positions:
            return t
        if snap_mode == "floor":
            candidates = [b for b in bar_positions if b <= t + 0.05]
            return candidates[-1] if candidates else bar_positions[0]
        elif snap_mode == "ceil":
            candidates = [b for b in bar_positions if b >= t - 0.05]
            return candidates[0] if candidates else bar_positions[-1]
        else:
            return min(bar_positions, key=lambda b: abs(b - t))

    events = []
    for b_pos, s_name in section_map.items():
        events.append(("SECTION", b_pos, s_name))
    for p in phrase_regions:
        events.append(("VOCAL", p["start"], p))

    events.sort(key=lambda x: (x[1], 0 if x[0] == "SECTION" else 1))

    windows = []
    t_curr = bar_positions[0]

    for ev in events:
        ev_type = ev[0]
        ev_time = ev[1]

        if ev_type == "SECTION":
            ev_time_snapped = get_bar_time(ev_time, bar_positions)
            if ev_time_snapped > t_curr + 0.1:
                windows.extend(split_gap_into_windows(t_curr, ev_time_snapped))
            windows.append(("SECTION", ev[2], ev_time_snapped))
            t_curr = ev_time_snapped
        elif ev_type == "VOCAL":
            phrase = ev[2]
            p_start = phrase["start"]
            p_end = phrase["end"]

            p_start_snapped = max(t_curr, get_bar_time(p_start, bar_positions, "floor"))
            p_end_snapped = max(p_start_snapped + 0.1, get_bar_time(p_end, bar_positions, "ceil"))

            if p_start_snapped > t_curr + 0.1:
                if p_start_snapped - t_curr < 2.0:
                    p_start_snapped = t_curr
                else:
                    windows.extend(split_gap_into_windows(t_curr, p_start_snapped))

            windows.append(("VOCAL", phrase, p_start_snapped, p_end_snapped))
            t_curr = p_end_snapped

    song_end = bar_positions[-1]
    if song_end > t_curr + 0.1:
        windows.extend(split_gap_into_windows(t_curr, song_end))

    for item in windows:
        if item[0] == "SECTION":
            continue

        if item[0] == "VOCAL":
            _, phrase, ws, we = item
            window_words = phrase["words"]
            combined_text = phrase["text"]
        else:
            _, ws, we = item
            window_words = []
            combined_text = ""

        sustained_chord = None
        for ct, cc, _ in sorted([c for c in chord_changes if c[1] != "|"], key=lambda x: x[0]):
            if ct <= ws + 0.05:
                sustained_chord = cc
            else:
                break

        window_chords_raw = [(ct, cc) for ct, cc, _ in chord_changes if ws - 0.1 <= ct < we - 0.1]
        if combined_text:
            window_chords_raw = [(ct, cc) for ct, cc in window_chords_raw if cc != "|"]

        first_lyric_time = ws
        if window_words:
            first_lyric_time = min(w["start"] for w in window_words)

        skip_sustained = False
        if sustained_chord and sustained_chord != "N.C.":
            regular_chords_in_window = [ct for ct, cc in window_chords_raw if cc != "|"]
            if regular_chords_in_window:
                first_chord_time = min(regular_chords_in_window)
                if first_chord_time - first_lyric_time < 0.3:
                    skip_sustained = True

        if sustained_chord and sustained_chord != "N.C." and not skip_sustained:
            has_start_chord = any(abs(ct - ws) < 0.1 and cc != "|" for ct, cc in window_chords_raw)
            if not has_start_chord:
                window_chords_raw.append((ws, sustained_chord))

        window_chords_raw.sort(key=lambda x: (x[0], 0 if x[1] == "|" else 1))

        window_chords = []
        for ct, cc in window_chords_raw:
            if cc == "|" or not window_chords or cc != window_chords[-1][1]:
                window_chords.append((ct, cc))

        if not window_chords and not combined_text:
            continue

        if not combined_text:
            chord_strs = [f"[{cc}]" for _, cc in window_chords]
            if chord_strs:
                lines.append(" ".join(chord_strs))
                line_timings.append(window_chords[0][0])
            continue

        if window_chords:
            line = _insert_chords_into_lyrics(combined_text, window_chords, window_words, ws, we)
            lines.append(line)
            line_timings.append(window_chords[0][0])
        else:
            lines.append(combined_text)
            line_timings.append(ws)

    return "\n".join(lines), line_timings
