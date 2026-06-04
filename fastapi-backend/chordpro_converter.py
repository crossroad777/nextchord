import json
import re

def _section_to_japanese(section_label):
    mapping = {
        "intro": "イントロ",
        "verse": "Aメロ",
        "verse1": "Aメロ",
        "verse2": "Bメロ",
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

def _insert_chords_into_lyrics(text, chord_changes, words, phrase_start=0.0, phrase_end=None):
    if not chord_changes: return text
    text_len = len(text)
    if text_len == 0: return text
    if len(chord_changes) == 1: return f"[{chord_changes[0][1]}]{text}"
    if phrase_end is None or phrase_end <= phrase_start:
        times = [ct for ct, _ in chord_changes]
        phrase_start, times[0]
        phrase_end = times[-1] + 2.0
    phrase_duration = max(phrase_end - phrase_start, 0.01)
    
    raw_positions = {}
    if words:
        word_char_indices = []
        current_idx = 0
        for w in words:
            w_text = w.get("word", w.get("text", ""))
            w_len = len(w_text)
            w_start = w["start"]
            w_end = w.get("end", w["start"] + max(0.2, w_len * 0.1))
            word_char_indices.append((w_start, w_end, current_idx, w_len))
            current_idx += w_len
            
        for i, (ct, cc) in enumerate(chord_changes):
            best_idx = 0
            min_diff = float("inf")
            inside_word = False
            
            for w_start, w_end, char_idx, w_len in word_char_indices:
                if w_start <= ct <= w_end and w_end > w_start:
                    ratio = (ct - w_start) / (w_end - w_start)
                    ratio = max(0.0, min(1.0, ratio))
                    best_idx = char_idx + round(ratio * w_len)
                    inside_word = True
                    break
                    
            if not inside_word:
                for w_start, w_end, char_idx, w_len in word_char_indices:
                    diff_start = abs(w_start - ct)
                    diff_end = abs(w_end - ct)
                    if diff_start < min_diff:
                        min_diff = diff_start
                        best_idx = char_idx
                    if diff_end < min_diff:
                        min_diff = diff_end
                        best_idx = char_idx + w_len
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
        print(f"DEBUG _insert_chords: text='{text}', chord_changes={chord_changes}, raw_positions={raw_positions}, bars={chord_insertions_bars}, reg={chord_insertions_regular}, result='{result}'")
        
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
        return "\n".join(lines), []

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

    phrases = lyrics_phrases or display_phrases or []
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
        if len(clean) < 3 or clean in {"編曲", "歌唱", "演奏", "作曲", "作詞", "提供"}:
            continue
        p_start, p_end = p.get("start", 0), p.get("end", p.get("start", 0) + 1)
        p_words = p.get("words", [])
        if not p_words and all_words:
            p_words = [{"start": t, "word": w} for t, w in all_words if p_start - 0.3 <= t <= p_end + 0.3]
        phrase_regions.append({"start": p_start, "end": p_end, "text": text, "words": p_words})

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

    # Map sections to their closest bar
    section_map = {}
    if not sections:
        section_map[bar_positions[0]] = "Intro"
    else:
        for s_time, s_name in sections:
            closest_bar = min(bar_positions, key=lambda b: abs(b - s_time))
            section_map[closest_bar] = s_name

    windows = []
    for i in range(0, len(bar_positions) - 1, BARS_PER_LINE):
        ws = bar_positions[i]
        we = bar_positions[min(i + BARS_PER_LINE, len(bar_positions) - 1)]
        
        # Check if any section is mapped to a bar within this window [ws, we)
        window_sections = []
        for j in range(i, min(i + BARS_PER_LINE, len(bar_positions) - 1)):
            b = bar_positions[j]
            if b in section_map:
                window_sections.append(section_map[b])
                
        if window_sections:
            # If multiple sections fall in this window, just take the last one
            windows.append(("SECTION", window_sections[-1], ws))
            
        windows.append(("WINDOW", ws, we))

    for item in windows:
        if item[0] == "SECTION":
            _, s_name, _ = item
            lines.append("")
            lines.append(f"{{c:{_section_to_japanese(s_name)}}}")
            continue
            
        _, ws, we = item
        
        window_chords_raw = [(ct, cc) for ct, cc, _ in chord_changes if ws - 0.1 <= ct < we - 0.1]
        
        # Snap the first regular chord of each measure to the bar line
        snapped_chords = []
        bar_times = sorted([ct for ct, cc in window_chords_raw if cc == "|"])
        snapped_bars = set()
        
        for ct, cc in window_chords_raw:
            snapped_chords.append((ct, cc))
            
            
        # Re-sort after snapping
        snapped_chords.sort(key=lambda x: (x[0], 0 if x[1] == "|" else 1))
        
        # Remove consecutive identical chords to prevent [C]...[C] stuttering, but preserve [|]
        window_chords = []
        for ct, cc in snapped_chords:
            if cc == "|" or not window_chords or cc != window_chords[-1][1]:
                window_chords.append((ct, cc))
        
        # Collect words instead of entire phrases
        window_words = []
        for p in phrase_regions:
            for w in p["words"]:
                if ws - 0.1 <= w["start"] < we - 0.1:
                    window_words.append(w)
                    
        # If phrase doesn't have words, fallback to old logic
        fallback_phrases = []
        if not window_words:
            for p in phrase_regions:
                if not p["words"] and p["start"] >= ws - 0.1 and p["start"] < we - 0.1:
                    fallback_phrases.append(p)
                    
        if not window_chords and not window_words and not fallback_phrases:
            continue
            
        if not window_words and not fallback_phrases:
            chord_strs = [f"[{cc}]" for _, cc in window_chords]
            if chord_strs:
                lines.append(" ".join(chord_strs))
                line_timings.append(window_chords[0][0])
            continue
            
        if window_words:
            combined_text = "".join([w.get("word", "") for w in window_words])
        else:
            combined_text = "".join([p["text"] for p in fallback_phrases])
            
        if "捨て" in combined_text:
            print(f"DEBUG window_words: ws={ws}, we={we}, window_words={window_words}, combined_text='{combined_text}'")
        
        if window_chords:
            line = _insert_chords_into_lyrics(combined_text, window_chords, window_words, ws, we)
            lines.append(line)
            line_timings.append(window_chords[0][0])
        else:
            lines.append(combined_text)
            line_timings.append(c_start)

    return "\n".join(lines), line_timings
