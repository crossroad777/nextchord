"""
NextChord - エクスポートユーティリティ
======================================
MIDI / PDF / テキスト形式でのコード譜エクスポート。
"""

import re
import unicodedata
import math
import json
from pathlib import Path
from midiutil import MIDIFile
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, mm
from reportlab.lib.colors import HexColor

# ------------------------------------------------------------------
# MIDI Generation
# ------------------------------------------------------------------
NOTE_MAP = {
    "C": 0, "C#": 1, "Db": 1,
    "D": 2, "D#": 3, "Eb": 3,
    "E": 4, 
    "F": 5, "F#": 6, "Gb": 6,
    "G": 7, "G#": 8, "Ab": 8,
    "A": 9, "A#": 10, "Bb": 10,
    "B": 11
}

CHORD_OFFSETS = {
    "": [0, 4, 7],           # Major
    "m": [0, 3, 7],          # Minor
    "min": [0, 3, 7],
    "7": [0, 4, 7, 10],      # Dom7
    "Maj7": [0, 4, 7, 11],   # Maj7
    "maj7": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10],     # Min7
    "min7": [0, 3, 7, 10],
    "dim": [0, 3, 6],        # Diminished
    "dim7": [0, 3, 6, 9],    # Diminished 7th
    "aug": [0, 4, 8],        # Augmented
    "sus4": [0, 5, 7],
    "sus2": [0, 2, 7],
    "6": [0, 4, 7, 9],       # Major 6th
    "m6": [0, 3, 7, 9],      # Minor 6th
    "9": [0, 4, 7, 10, 14],  # Dominant 9th
    "add9": [0, 4, 7, 14],   # Add 9
}

def parse_chord(chord_str):
    if not chord_str or chord_str in ("N", "N.C."):
        return None, None
    
    match = re.match(r"^([A-G][#b]?)(.*)$", chord_str)
    if not match:
        return None, None
    
    root_str = match.group(1)
    quality = match.group(2)
    
    root_val = NOTE_MAP.get(root_str, 0)
    offsets = CHORD_OFFSETS.get(quality, [0, 4, 7])
    
    return root_val, offsets


def create_midi(structured_data, output_path, bpm=120, key=None, notes_data=None):
    """
    MIDIファイルを生成する。
    
    Parameters
    ----------
    structured_data : list
        コード構造化データ (bar, beat, chord, time, duration)
    output_path : str or Path
        出力パス
    bpm : float
        テンポ (BPM)
    key : str or None
        キー名 (例: "C major", "A minor")
    notes_data : list or None
        検出済みノートデータ（MIDIトラック2に追加）
    """
    bpm = float(bpm) if bpm else 120.0
    n_tracks = 2 if notes_data else 1
    midi = MIDIFile(n_tracks)
    
    # Track 0: コード
    midi.addTrackName(0, 0, "Chords")
    midi.addTempo(0, 0, bpm)
    
    # キーシグネチャ（MIDIイベント）
    if key:
        # key_name -> MIDI key signature
        key_parts = key.split()
        if len(key_parts) >= 2:
            root = key_parts[0]
            mode = 0 if key_parts[1].lower() == "major" else 1
            # 五度圏の位置（シャープ数）
            sharp_map = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6,
                         "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6,
                         "C#": 7}
            sharps = sharp_map.get(root, 0)
            try:
                midi.addKeySignature(0, 0, abs(sharps), 1 if sharps < 0 else 0, mode)
            except Exception:
                pass
    
    channel = 0
    volume = 80
    
    # ビート間隔をBPMから計算（1ビート = 1拍）
    prev_chord = None
    current_beat = 0
    
    for item in structured_data:
        chord = item.get("chord")
        duration = item.get("duration", 0.5)
        beat_duration = duration * bpm / 60.0  # 秒 -> ビート数に変換
        
        if chord and chord not in ("N", "N.C."):
            root, offsets = parse_chord(chord)
            if root is not None:
                base_note = 48 + root  # C3 (オクターブ3、より自然なギター音域)
                
                # コードが変わった時のみ鳴らす（連続する同じコードは不要）
                if chord != prev_chord:
                    for offset in offsets:
                        note = base_note + offset
                        midi.addNote(0, channel, note, current_beat, max(0.5, beat_duration), volume)
                    prev_chord = chord
        
        current_beat += max(0.25, beat_duration)
    
    # Track 1: 検出ノート（メロディ/ギターライン）
    if notes_data:
        midi.addTrackName(1, 0, "Guitar")
        channel_guitar = 1
        
        for note in notes_data:
            start_beat = note["start_time"] * bpm / 60.0
            duration_beat = max(0.1, (note["end_time"] - note["start_time"]) * bpm / 60.0)
            pitch = note["midi_pitch"]
            vel = note.get("velocity", 80)
            
            midi.addNote(1, channel_guitar, pitch, start_beat, duration_beat, vel)
    
    with open(output_path, "wb") as f:
        midi.writeFile(f)


# ------------------------------------------------------------------
# PDF Generation (Enhanced)
# ------------------------------------------------------------------

# プレミアムなカラーパレット
_PDF_COLORS = {
    "title": HexColor("#1a1a2e"),
    "subtitle": HexColor("#16213e"),
    "section": HexColor("#0f3460"),
    "chord": HexColor("#e94560"),
    "lyric": HexColor("#333333"),
    "bar_line": HexColor("#cccccc"),
    "bar_num": HexColor("#999999"),
    "header_bg": HexColor("#f8f9fa"),
    "section_bg": HexColor("#e8f0fe"),
}


def create_pdf(structured_data, output_path, title="Chord Sheet",
               key=None, bpm=None, filename=None):
    """
    高品質なPDFコード譜を生成する。
    
    Parameters
    ----------
    structured_data : list
        コード構造化データ
    output_path : str or Path
        出力パス
    title : str
        タイトル
    key : str or None
        キー名
    bpm : float or None
        テンポ
    filename : str or None
        元ファイル名
    """
    c = canvas.Canvas(str(output_path), pagesize=A4)
    width, height = A4
    margin = 20 * mm
    usable_width = width - 2 * margin
    
    # ===== ヘッダー =====
    # タイトル
    display_title = filename.replace(".mp3", "").replace(".wav", "") if filename else title
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(_PDF_COLORS["title"])
    c.drawString(margin, height - margin - 5*mm, display_title)
    
    # サブ情報（キー、BPM）
    info_parts = []
    if key:
        info_parts.append(f"Key: {key}")
    if bpm:
        try:
            info_parts.append(f"BPM: {float(bpm):.0f}")
        except (ValueError, TypeError):
            pass
    
    if info_parts:
        c.setFont("Helvetica", 11)
        c.setFillColor(_PDF_COLORS["subtitle"])
        c.drawString(margin, height - margin - 12*mm, "  |  ".join(info_parts))
    
    # 区切り線
    y_line = height - margin - 16*mm
    c.setStrokeColor(_PDF_COLORS["bar_line"])
    c.setLineWidth(0.5)
    c.line(margin, y_line, width - margin, y_line)
    
    # ===== コードグリッド =====
    cols = 4  # 1行に4小節
    box_w = usable_width / cols
    box_h = 14 * mm
    section_h = 6 * mm
    
    y = y_line - 8 * mm
    
    # 小節単位でグループ化
    bars = {}
    for item in structured_data:
        b = item["bar"]
        if b not in bars:
            bars[b] = []
        bars[b].append(item)
    
    sorted_bars = sorted(bars.keys())
    
    current_section = None
    col = 0
    
    for bar_idx in sorted_bars:
        items = bars[bar_idx]
        section = items[0].get("section")
        
        # セクション変更
        if section and section != current_section:
            # 新しい行から始める
            if col > 0:
                y -= box_h + 2*mm
                col = 0
            
            # ページ送り
            if y < margin + box_h + section_h:
                c.showPage()
                y = height - margin - 5*mm
            
            # セクション名を描画
            c.setFillColor(_PDF_COLORS["section_bg"])
            c.roundRect(margin, y - section_h + 1*mm, usable_width, section_h, 2*mm, fill=1, stroke=0)
            c.setFillColor(_PDF_COLORS["section"])
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin + 3*mm, y - section_h + 3*mm, f"| {section}")
            y -= section_h + 3*mm
            current_section = section
        
        # ページ送り
        if y < margin + box_h:
            c.showPage()
            y = height - margin - 5*mm
            c.setFont("Helvetica-Bold", 14)
        
        x = margin + col * box_w
        
        # 小節ボックスを描画
        c.setStrokeColor(_PDF_COLORS["bar_line"])
        c.setLineWidth(0.3)
        c.rect(x, y - box_h, box_w, box_h, stroke=1, fill=0)
        
        # 小節番号
        c.setFont("Helvetica", 6)
        c.setFillColor(_PDF_COLORS["bar_num"])
        c.drawString(x + 1*mm, y - 3*mm, str(bar_idx))
        
        # コード名（重複除去）
        unique_chords = []
        prev = None
        for item in items:
            ch = item.get("chord", "")
            if ch in ("N", "N.C."):
                ch = ""
            if ch and ch != prev:
                unique_chords.append(ch)
                prev = ch
        
        if unique_chords:
            c.setFont("Helvetica-Bold", 13)
            c.setFillColor(_PDF_COLORS["chord"])
            
            if len(unique_chords) == 1:
                # 中央に配置
                c.drawCentredString(x + box_w / 2, y - box_h / 2 - 1*mm, unique_chords[0])
            else:
                # 均等配置
                step = box_w / len(unique_chords)
                for i, ch in enumerate(unique_chords):
                    cx = x + (i * step) + (step / 2)
                    c.drawCentredString(cx, y - box_h / 2 - 1*mm, ch)
        
        # 歌詞（あれば小節下部に小さく表示）
        lyrics = [item.get("lyric", "") for item in items if item.get("lyric")]
        if lyrics:
            lyric_text = " ".join(lyrics)[:20]  # 20文字まで
            c.setFont("Helvetica", 7)
            c.setFillColor(_PDF_COLORS["lyric"])
            c.drawString(x + 2*mm, y - box_h + 2*mm, lyric_text)
        
        col += 1
        if col >= cols:
            col = 0
            y -= box_h + 1*mm
    
    # フッター
    c.setFont("Helvetica", 8)
    c.setFillColor(_PDF_COLORS["bar_num"])
    c.drawCentredString(width / 2, margin / 2, "Generated by NextChord")
    
    c.save()


# ------------------------------------------------------------------
# Text Generation (Chords over Lyrics)
# ------------------------------------------------------------------

def get_char_width(char):
    if unicodedata.east_asian_width(char) in ('F', 'W', 'A'):
        return 2
    return 1

def get_str_width(text):
    return sum(get_char_width(c) for c in text)

def pad_visual(text, target_w):
    cw = get_str_width(text)
    needed = target_w - cw
    if needed < 0: needed = 0
    return text + " " * needed

def create_text_score(structured_data):
    """
    Generate a text-based score with chords ALIGNED ABOVE lyrics.
    Ensures phrase-by-phrase layout without redundancy.
    """
    if not structured_data:
        return ""

    all_items = sorted(structured_data, key=lambda x: (x["bar"], x["beat"]))

    def get_global_beat(item):
        return (item["bar"] - 1) * 4 + (item["beat"] - 1)

    # Pre-collect all unique chord changes with global beat
    global_chords = {}
    for it in all_items:
        c = it.get("chord", "")
        if c in ["N", "N.C."]: c = ""
        if c:
            global_chords[get_global_beat(it)] = c

    def get_chord_at(beat):
        sorted_beats = sorted(global_chords.keys())
        active = ""
        for b in sorted_beats:
            if b <= beat: active = global_chords[b]
            else: break
        return active

    lines = []
    current_section = None
    last_chord = None
    
    # 2. Iterate and render
    idx = 0
    while idx < len(all_items):
        item = all_items[idx]
        section = item.get("section")
        
        if section and section != current_section:
            if lines and lines[-1] != "": lines.append("")
            lines.append(f"[{section}]")
            current_section = section

        if item.get("lyric"):
            # PHRASE BLOCK
            lyric_text = item.get("lyric", "")
            start_beat = get_global_beat(item)
            
            # Find next phrase or section change to define duration
            end_beat = start_beat + 4
            for next_idx in range(idx + 1, len(all_items)):
                if all_items[next_idx].get("lyric") or all_items[next_idx].get("section"):
                    end_beat = get_global_beat(all_items[next_idx])
                    break
            
            duration = max(1, end_beat - start_beat)
            
            # Chords for THIS phrase
            phrase_chords = [] # (vis_pos, chord)
            
            # Phrase start chord
            sc = get_chord_at(start_beat)
            if sc:
                phrase_chords.append((0, sc))
            
            # Intermediate changes
            tmp_c = sc
            for b in sorted(global_chords.keys()):
                if b > start_beat and b < end_beat:
                    cur_c = global_chords[b]
                    if cur_c != tmp_c:
                        rel = (b - start_beat) / duration
                        vis_pos = int(rel * get_str_width(lyric_text))
                        phrase_chords.append((vis_pos, cur_c))
                        tmp_c = cur_c
            
            # Render phrase
            if phrase_chords:
                placed = []
                last_vis = -2
                for pos, c in phrase_chords:
                    actual = max(pos, last_vis + 2)
                    placed.append((actual, c))
                    last_vis = actual + len(c)
                
                c_line = ""
                cv = 0
                for pos, c in placed:
                    c_line += " " * (pos - cv) + c
                    cv = pos + len(c)
                lines.append(c_line)
            
            lines.append(lyric_text)
            lines.append("")
            
            # Consume all items used in this phrase duration
            while idx < len(all_items) and get_global_beat(all_items[idx]) < end_beat:
                last_chord = all_items[idx].get("chord", last_chord) # carry over
                idx += 1
        else:
            # INSTRUMENTAL BLOCK
            instr_chords = []
            while idx < len(all_items) and not all_items[idx].get("lyric"):
                if all_items[idx].get("section") and all_items[idx].get("section") != current_section:
                    break
                
                c = all_items[idx].get("chord", "")
                if c in ["N", "N.C."]: c = ""
                if c and c != last_chord:
                    instr_chords.append(c)
                    last_chord = c
                idx += 1
            
            if instr_chords:
                lines.append("  ".join(instr_chords))
                lines.append("")
                
    return "\n".join(lines).strip()
