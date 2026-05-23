"""
Tab Generator Module -- Solo Guitar Precision Edition
=====================================================
ノートイベントデータからTab譜データおよびMusicXMLを生成する。

機能:
1. メロディTab: ノート->ギターフレット位置変換（ポジション最適化付き）
2. コードTab: コード名->標準ボイシングのTab表記
3. MusicXML: 五線譜+Tab譜の2段構成MusicXML生成
   - Part 1 (Melody): 五線譜でメロディ + コード記号
   - Part 2 (Guitar TAB): 実際の転記ノートをTAB譜で表示
4. 高精度音価量子化（三連符・付点・32分音符対応）
"""

import math
import json
import numpy as np
from typing import List, Dict, Optional, Tuple
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

# =========================================================================
# T-4: ビートグリッドスナップ (16分音符 / 3連符)
# =========================================================================
STRAIGHT_GRID = [0, 3, 6, 9, 12]   # divisions=12 の 16分グリッド
TRIPLET_GRID  = [0, 4, 8, 12]      # 3連符グリッド

def snap_to_grid(val, divisions=12):
    """val を 16分音符 / 3連符グリッドに最寄りスナップする"""
    candidates = STRAIGHT_GRID + TRIPLET_GRID
    return min(candidates, key=lambda x: abs(x - (val % divisions))) + (val // divisions) * divisions

# =========================================================================
# ギター標準チューニング (弦番号: 6=最低音, 1=最高音)
# =========================================================================
STANDARD_TUNING = {
    6: 40,  # E2
    5: 45,  # A2
    4: 50,  # D3
    3: 55,  # G3
    2: 59,  # B3
    1: 64,  # E4
}

# 代替チューニングプリセット
TUNING_PRESETS = {
    "standard":    {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64},
    "drop_d":      {6: 38, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64},
    "half_step":   {6: 39, 5: 44, 4: 49, 3: 54, 2: 58, 1: 63},
    "open_g":      {6: 38, 5: 43, 4: 50, 3: 55, 2: 59, 1: 62},
    "dadgad":      {6: 38, 5: 45, 4: 50, 3: 55, 2: 57, 1: 62},
    "open_d":      {6: 38, 5: 45, 4: 50, 3: 54, 2: 57, 1: 62},
}

MAX_FRET = 15  # 最大フレット数（一般的なTABの範囲に制限）

# =========================================================================
# コードボイシングデータ (ギター標準チューニング)
# 弦順: [6弦, 5弦, 4弦, 3弦, 2弦, 1弦], -1 = ミュート, 0 = 開放
# =========================================================================
CHORD_VOICINGS = {
    # メジャー
    "C":  [-1, 3, 2, 0, 1, 0],
    "D":  [-1, -1, 0, 2, 3, 2],
    "E":  [0, 2, 2, 1, 0, 0],
    "F":  [1, 3, 3, 2, 1, 1],
    "G":  [3, 2, 0, 0, 0, 3],
    "A":  [-1, 0, 2, 2, 2, 0],
    "B":  [-1, 2, 4, 4, 4, 2],
    "C#": [-1, 4, 3, 1, 2, 1], "Db": [-1, 4, 3, 1, 2, 1],
    "D#": [-1, -1, 1, 3, 4, 3], "Eb": [-1, -1, 1, 3, 4, 3],
    "F#": [2, 4, 4, 3, 2, 2], "Gb": [2, 4, 4, 3, 2, 2],
    "G#": [4, 6, 6, 5, 4, 4], "Ab": [4, 6, 6, 5, 4, 4],
    "A#": [-1, 1, 3, 3, 3, 1], "Bb": [-1, 1, 3, 3, 3, 1],
    # マイナー
    "Cm":  [-1, 3, 5, 5, 4, 3],
    "Dm":  [-1, -1, 0, 2, 3, 1],
    "Em":  [0, 2, 2, 0, 0, 0],
    "Fm":  [1, 3, 3, 1, 1, 1],
    "Gm":  [3, 5, 5, 3, 3, 3],
    "Am":  [-1, 0, 2, 2, 1, 0],
    "Bm":  [-1, 2, 4, 4, 3, 2],
    "C#m": [-1, 4, 6, 6, 5, 4], "Dbm": [-1, 4, 6, 6, 5, 4],
    "D#m": [-1, -1, 1, 3, 4, 2], "Ebm": [-1, -1, 1, 3, 4, 2],
    "F#m": [2, 4, 4, 2, 2, 2], "Gbm": [2, 4, 4, 2, 2, 2],
    "G#m": [4, 6, 6, 4, 4, 4], "Abm": [4, 6, 6, 4, 4, 4],
    "A#m": [-1, 1, 3, 3, 2, 1], "Bbm": [-1, 1, 3, 3, 2, 1],
    # 7th
    "C7":  [-1, 3, 2, 3, 1, 0],
    "D7":  [-1, -1, 0, 2, 1, 2],
    "E7":  [0, 2, 0, 1, 0, 0],
    "F7":  [1, 3, 1, 2, 1, 1],
    "G7":  [3, 2, 0, 0, 0, 1],
    "A7":  [-1, 0, 2, 0, 2, 0],
    "B7":  [-1, 2, 1, 2, 0, 2],
    # マイナー7th
    "Cm7": [-1, 3, 5, 3, 4, 3],
    "Dm7": [-1, -1, 0, 2, 1, 1],
    "Em7": [0, 2, 0, 0, 0, 0],
    "Am7": [-1, 0, 2, 0, 1, 0],
    "Bm7": [-1, 2, 0, 2, 0, 2],
    # メジャー7th
    "Cmaj7": [-1, 3, 2, 0, 0, 0],
    "Dmaj7": [-1, -1, 0, 2, 2, 2],
    "Fmaj7": [1, -1, 3, 2, 1, 0],
    "Gmaj7": [3, 2, 0, 0, 0, 2],
    "Amaj7": [-1, 0, 2, 1, 2, 0],
    # sus4
    "Csus4": [-1, 3, 3, 0, 1, 1],
    "Dsus4": [-1, -1, 0, 2, 3, 3],
    "Esus4": [0, 2, 2, 2, 0, 0],
    "Asus4": [-1, 0, 2, 2, 3, 0],
    # sus2
    "Dsus2": [-1, -1, 0, 2, 3, 0],
    "Asus2": [-1, 0, 2, 2, 0, 0],
    "Esus2": [0, 2, 4, 4, 0, 0],
    # add9
    "Cadd9": [-1, 3, 2, 0, 3, 0],
    "Gadd9": [3, 2, 0, 2, 0, 3],
    # dim
    "Bdim": [-1, 2, 3, 4, 3, -1],
    "Cdim": [-1, 3, 4, 5, 4, -1],
    # aug
    "Caug": [-1, 3, 2, 1, 1, 0],
    "Eaug": [0, 3, 2, 1, 1, 0],
}

# キー -> 調号の#/b数 (正=シャープ, 負=フラット)
KEY_SIGNATURES = {
    "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "Gb": -6,
    "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Cb": -7,
    # マイナーキー
    "Am": 0, "Em": 1, "Bm": 2, "F#m": 3, "C#m": 4, "G#m": 5, "D#m": 6,
    "Dm": -1, "Gm": -2, "Cm": -3, "Fm": -4, "Bbm": -5, "Ebm": -6,
}

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
SHARP_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
FLAT_NOTE_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']


# =========================================================================
# メロディTab変換（ポジション最適化版）
# =========================================================================
def midi_to_guitar_position(
    midi_pitch: int,
    prev_positions: List[Tuple[int, int]] = None,
    tuning: Dict[int, int] = None,
    avoid_strings: set = None,
) -> Optional[Tuple[int, int]]:
    """
    MIDIピッチをギターの(弦番号, フレット番号)に変換する。
    前のポジションからの移動を最小化するヒューリスティック。

    Parameters
    ----------
    midi_pitch : int
        MIDI番号
    prev_positions : list of (string, fret)
        直前に弾いたポジション群（ポジション移動最小化用）
    tuning : dict
        チューニング。None の場合は標準チューニング。
    avoid_strings : set
        同時に鳴っているため避けるべき弦の集合

    Returns
    -------
    (string_num, fret_num) or None
    """
    if tuning is None:
        tuning = STANDARD_TUNING

    candidates = []
    for string_num, open_pitch in tuning.items():
        fret = midi_pitch - open_pitch
        if 0 <= fret <= MAX_FRET:
            # 避けるべき弦をスキップ
            if avoid_strings and string_num in avoid_strings:
                continue
            candidates.append((string_num, fret))

    if not candidates:
        return None

    # スコアリングによるポジション最適化
    if prev_positions and any(f > 0 for _, f in prev_positions):
        active_frets = [f for _, f in prev_positions if f > 0]
        avg_fret = sum(active_frets) / len(active_frets)

        def position_score(c):
            string_num, fret = c
            # フレット距離ペナルティ（前のポジションからの距離）
            fret_penalty = abs(fret - avg_fret) * 2.0
            # 開放弦ボーナス（自然な演奏）
            open_bonus = -1.0 if fret == 0 else 0
            # ストレッチペナルティ（5フレット以上の移動）
            stretch_penalty = max(0, abs(fret - avg_fret) - 4) * 3.0
            # 低フレット微小ボーナス（演奏しやすさ）
            low_fret_bonus = -0.5 if fret <= 5 else 0
            # 高フレット強力ペナルティ（12フレット以上は避ける）
            high_fret_penalty = max(0, fret - 9) * 5.0
            return fret_penalty + stretch_penalty + open_bonus + low_fret_bonus + high_fret_penalty

        candidates.sort(key=position_score)
    else:
        # デフォルト: 低いフレットを優先（開放弦寄り）
        candidates.sort(key=lambda c: c[1])

    return candidates[0]


def _convert_technique_field(note: dict) -> list:
    """technique.py output ('technique': 'h') -> tab_generator format ('techniques': ['hammer_on'])"""
    # If already has techniques list, use it
    existing = note.get("techniques", [])
    if existing:
        return existing
    
    tech = note.get("technique", "")
    if not tech or tech == "normal":
        return []
    
    # Map technique.py short codes to MusicXML technique names
    TECH_MAP = {
        "h": "hammer_on",
        "p": "pull_off",
        "/": "slide_up",
        "\\": "slide_down",
        "b": "bend",
        "b_half": "bend",
        "b_1half": "bend",
        "b_2": "bend",
        "~": "vibrato",
        "gliss_up": "slide_up",
        "gliss_down": "slide_down",
        "harmonic": "natural_harmonic",
        "pm": "palm_mute",
        "tr": "trill",
    }
    
    mapped = TECH_MAP.get(tech)
    if mapped:
        if mapped == "bend":
            # Bend amount mapping
            amounts = {"b_half": 0.5, "b": 1.0, "b_1half": 1.5, "b_2": 2.0}
            return [{"type": "bend", "amount": amounts.get(tech, 1.0)}]
        return [mapped]
    
    # Direct passthrough for techniques that tab_generator checks by name
    if tech in ("mute_brush", "ghost_note", "x"):
        return [tech]
    
    return []


def notes_to_tab_data(
    notes: List[Dict],
    beats: List[float] = None,
    tuning: Dict[int, int] = None,
) -> List[Dict]:
    """
    ノートイベントをTab譜データに変換する。
    Viterbi DP最適化（string_optimizer）を試行し、
    import失敗時はグリーディヒューリスティックにフォールバック。
    """
    if tuning is None:
        tuning = STANDARD_TUNING

    # --- Viterbi DP 最適化を試行 ---
    try:
        from string_optimizer import optimize_string_assignment

        # tuning を list 形式に変換 (string_optimizer は [6弦,5弦,...,1弦] のリスト)
        if isinstance(tuning, dict):
            tuning_list = [tuning[s] for s in range(6, 0, -1)]
        else:
            tuning_list = list(tuning)

        optimized = optimize_string_assignment(notes, tuning=tuning_list, capo=0)

        tab_data = []
        for note in optimized:
            tab_data.append({
                "time": note["start_time"],
                "duration": round(note["end_time"] - note["start_time"], 4),
                "string": note["string"],
                "fret": note["fret"],
                "midi_pitch": note["midi_pitch"],
                "note_name": note["note_name"],
                "velocity": note.get("velocity", 80),
                "techniques": _convert_technique_field(note),
                "bar": note.get("bar"),
                "beat": note.get("beat"),
            })
        print(f"[TabGen] Viterbi DP string optimization applied ({len(tab_data)} notes)")
        return tab_data

    except Exception as e:
        print(f"[TabGen] string_optimizer unavailable, using greedy fallback: {e}")

    # --- フォールバック: 従来のグリーディ割り当て ---
    tab_data = []
    prev_positions = []

    # 同時発音グループを検出
    groups = _group_simultaneous_notes(notes, tolerance=0.03)

    for group in groups:
        used_strings = set()
        group_positions = []

        # グループ内のノートをピッチ順にソート（低音から）
        group.sort(key=lambda n: n["midi_pitch"])

        for note in group:
            pos = midi_to_guitar_position(
                note["midi_pitch"],
                prev_positions,
                tuning,
                avoid_strings=used_strings
            )
            if pos is None:
                continue

            string_num, fret = pos
            used_strings.add(string_num)
            group_positions.append(pos)

            tab_data.append({
                "time": note["start_time"],
                "duration": round(note["end_time"] - note["start_time"], 4),
                "string": string_num,
                "fret": fret,
                "midi_pitch": note["midi_pitch"],
                "note_name": note["note_name"],
                "velocity": note.get("velocity", 80),
                "techniques": _convert_technique_field(note),
                "bar": note.get("bar"),
                "beat": note.get("beat"),
            })

        # 直近ポジションを更新
        if group_positions:
            prev_positions = group_positions[-5:]

    return tab_data


def _group_simultaneous_notes(notes: List[Dict], tolerance: float = 0.03) -> List[List[Dict]]:
    """ほぼ同時に発音されるノートをグループ化する"""
    if not notes:
        return []

    groups = []
    current_group = [notes[0]]

    for i in range(1, len(notes)):
        if abs(notes[i]["start_time"] - current_group[0]["start_time"]) <= tolerance:
            current_group.append(notes[i])
        else:
            groups.append(current_group)
            current_group = [notes[i]]

    groups.append(current_group)
    return groups


def chord_to_tab_data(chord_name: str) -> Optional[List[int]]:
    """
    コード名からTab譜データ（フレット配列）を返す。

    Returns
    -------
    list of int or None
        [6弦, 5弦, 4弦, 3弦, 2弦, 1弦] フレット, -1=ミュート
    """
    clean = chord_name.replace("N.C.", "").strip()
    if not clean or clean == "N":
        return None

    # 直接一致
    if clean in CHORD_VOICINGS:
        return CHORD_VOICINGS[clean]

    # 末尾の修飾を段階的に除去して検索
    # 例: "Gadd9" -> "G", "Am7" -> "Am" -> "A"
    variants = [clean]
    # sus, add, dim, aug の除去
    for suffix in ["add9", "add11", "sus4", "sus2", "aug", "dim"]:
        if suffix in clean:
            variants.append(clean.replace(suffix, ""))
    # 数字（7, 9, 11, 13）の除去
    import re
    base_no_num = re.sub(r'\d+', '', clean)
    if base_no_num and base_no_num not in variants:
        variants.append(base_no_num)
    # Maj/maj の除去
    base_no_maj = clean.replace("Maj", "").replace("maj", "")
    if base_no_maj and base_no_maj not in variants:
        variants.append(base_no_maj)

    for v in variants:
        if v in CHORD_VOICINGS:
            return CHORD_VOICINGS[v]

    return None


# =========================================================================
# コード進行からキーを推定する
# =========================================================================
# 各メジャーキーのダイアトニックコード
_DIATONIC = {
    "C":  {"C","Dm","Em","F","G","Am","Bdim","D","D7","G7","E7","A7","Cmaj7","Fmaj7","Am7","Em7","Dm7"},
    "G":  {"G","Am","Bm","C","D","Em","F#dim","D7","G7","A7","E7","B7","F#7","Cm","Gmaj7","Cmaj7","Am7","Em7","Bm7"},
    "D":  {"D","Em","F#m","G","A","Bm","C#dim","A7","D7","E7","B7","F#7","Dmaj7","Gmaj7","Em7","Bm7","F#m7"},
    "A":  {"A","Bm","C#m","D","E","F#m","G#dim","E7","A7","B7","F#7","Amaj7","Dmaj7","Bm7","F#m7","C#m7"},
    "E":  {"E","F#m","G#m","A","B","C#m","D#dim","B7","E7","F#7","Emaj7","Amaj7","F#m7","C#m7","G#m7"},
    "F":  {"F","Gm","Am","Bb","C","Dm","Edim","C7","F7","G7","D7","Fmaj7","Bbmaj7","Am7","Dm7","Gm7"},
    "Bb": {"Bb","Cm","Dm","Eb","F","Gm","Adim","F7","Bb7","C7","G7","Bbmaj7","Ebmaj7","Cm7","Dm7","Gm7"},
    "Eb": {"Eb","Fm","Gm","Ab","Bb","Cm","Ddim","Bb7","Eb7","F7","C7","Ebmaj7","Abmaj7","Fm7","Gm7","Cm7"},
}

# マイナーキーのダイアトニックコード（ナチュラル + ハーモニック混合）
_DIATONIC_MINOR = {
    "Am":  {"Am","Bdim","C","Dm","Em","E","E7","F","G","G7","Am7","Dm7","Fmaj7","Cmaj7"},
    "Em":  {"Em","F#dim","G","Am","Bm","B","B7","C","D","D7","Em7","Am7","Gmaj7","Cmaj7"},
    "Bm":  {"Bm","C#dim","D","Em","F#m","F#","F#7","G","A","A7","Bm7","Em7","Dmaj7","Gmaj7"},
    "F#m": {"F#m","G#dim","A","Bm","C#m","C#","C#7","D","E","E7","F#m7","Bm7","Amaj7","Dmaj7"},
    "C#m": {"C#m","D#dim","E","F#m","G#m","G#","G#7","A","B","B7","C#m7","F#m7","Emaj7","Amaj7"},
    "Dm":  {"Dm","Edim","F","Gm","Am","A","A7","Bb","C","C7","Dm7","Gm7","Fmaj7","Bbmaj7"},
    "Gm":  {"Gm","Adim","Bb","Cm","Dm","D","D7","Eb","F","F7","Gm7","Cm7","Bbmaj7","Ebmaj7"},
    "Cm":  {"Cm","Ddim","Eb","Fm","Gm","G","G7","Ab","Bb","Bb7","Cm7","Fm7","Ebmaj7","Abmaj7"},
}


def estimate_key_from_chords(structured_data: list) -> str:
    """
    構造化データのコード進行からキーを推定する。
    メジャーキーとマイナーキーの両方に対応。
    ダイアトニックコードとの一致率 + 冒頭コードボーナスで判定。
    """
    from collections import Counter
    chord_counts = Counter()
    first_chord = None
    first_chord_root = None

    for entry in structured_data:
        chord = entry.get("chord", "N.C.")
        if chord and chord != "N.C.":
            chord_counts[chord] += 1
            if first_chord is None:
                first_chord = chord
                first_chord_root = chord[0]
                if len(chord) > 1 and chord[1] in '#b':
                    first_chord_root = chord[:2]

    if not chord_counts:
        return "C major"

    # 冒頭コード（最初の12ビート = 3小節）にボーナスウェイト
    first_bonus = Counter()
    for entry in structured_data[:12]:
        chord = entry.get("chord", "N.C.")
        if chord and chord != "N.C.":
            first_bonus[chord] += 2

    # マイナーコードの比率を計算（メジャー/マイナー判定の手がかり）
    total_chord_count = sum(chord_counts.values())
    minor_chord_count = sum(count for chord, count in chord_counts.items() 
                          if 'm' in chord.lower() and 'maj' not in chord.lower())
    minor_ratio = minor_chord_count / total_chord_count if total_chord_count > 0 else 0

    best_key = "C"
    best_score = -1
    best_mode = "major"

    # メジャーキー候補を評価
    for key_name, diatonic_set in _DIATONIC.items():
        score = 0
        for chord, count in chord_counts.items():
            if chord in diatonic_set:
                score += count
        for chord, bonus in first_bonus.items():
            if chord in diatonic_set:
                score += bonus
        if first_chord_root and key_name == first_chord_root:
            score += 5
        if score > best_score:
            best_score = score
            best_key = key_name
            best_mode = "major"

    # マイナーキー候補を評価
    for key_name, diatonic_set in _DIATONIC_MINOR.items():
        score = 0
        for chord, count in chord_counts.items():
            if chord in diatonic_set:
                score += count
        for chord, bonus in first_bonus.items():
            if chord in diatonic_set:
                score += bonus
        # マイナーキーのトニック一致ボーナス
        if first_chord and first_chord == key_name:
            score += 8  # マイナーキーでトニック一致は強い証拠
        elif first_chord_root and key_name.startswith(first_chord_root):
            score += 3
        # マイナーコード比率が高ければマイナーキーにボーナス
        if minor_ratio > 0.3:
            score += int(total_chord_count * 0.1)
        if score > best_score:
            best_score = score
            best_key = key_name
            best_mode = "minor"

    # 最終結果
    if best_mode == "minor":
        result = f"{best_key.replace('m', '')} minor"
        # best_key は "Am" 形式なので、"A minor" に変換
        root = best_key[:-1] if best_key.endswith('m') else best_key
        result = f"{root} minor"
    else:
        result = f"{best_key} major"

    pct = (best_score / total_chord_count * 100) if total_chord_count > 0 else 0
    print(f"[KeyEstimate] Best key: {result} ({best_score}/{total_chord_count} = {pct:.0f}% diatonic match)")
    print(f"[KeyEstimate] First chord: {first_chord} (root={first_chord_root}), minor_ratio={minor_ratio:.1%}")
    print(f"[KeyEstimate] Chord counts: {chord_counts.most_common(10)}")

    return result


# =========================================================================
# コードストロークベースのTABノート生成
# =========================================================================
def generate_chord_strum_notes(
    structured_data: list,
    bpm: float = 120.0,
    beats_per_measure: int = 4,
) -> list:
    """
    検出済みコード進行からギターストロークパターンのノートイベントを生成する。
    
    ズンチャパターン（4/4）:
      Beat 1: ダウンストローク（全弦、強）
      Beat 2: ミュートストローク（ブラッシング、X表記）
      Beat 3: ダウンストローク（全弦、中）
      Beat 4: ミュートストローク（ブラッシング、X表記）
    
    各ビートで8分音符2つ (down + up) を生成。
    偶数拍（2,4）のダウンストロークをミュートブラッシングにする。
    """
    beat_duration = 60.0 / bpm
    eighth_duration = beat_duration / 2
    
    notes = []
    last_chord = None
    
    for entry in structured_data:
        chord_name = entry.get("chord", "N.C.")
        beat_time = entry.get("time", 0.0)
        beat_in_bar = entry.get("beat", 1)  # 1-indexed beat within measure
        
        if chord_name == "N.C." or not chord_name:
            continue
        
        voicing = chord_to_tab_data(chord_name)
        if voicing is None:
            continue
        
        # ズンチャパターン: 偶数拍（2,4）はミュートブラッシング
        is_muted_beat = (beat_in_bar % 2 == 0)
        
        # 各ビートで 2つの8分音符 (down + up strum)
        for sub in range(2):
            strum_time = beat_time + sub * eighth_duration
            dur = eighth_duration * 0.8  # 少しスタッカート
            
            # ミュートビートの場合: 短いduration（ブラッシング感）
            if is_muted_beat:
                dur = eighth_duration * 0.3  # 短くカット
            
            # Down strum (sub=0): 全弦, Up strum (sub=1): 上4弦
            if sub == 0:
                strings_to_play = range(6)  # 6弦〜1弦
            else:
                strings_to_play = range(2, 6)  # 4弦〜1弦 (up strum)
            
            # Velocity: 強拍>弱拍、ダウン>アップ
            if is_muted_beat:
                vel = 45 if sub == 0 else 35  # ミュートは弱く
            else:
                vel = 80 if sub == 0 else 55  # 通常は強く
            
            for str_idx in strings_to_play:
                fret = voicing[str_idx]
                if fret < 0:  # ミュート弦
                    continue
                
                string_num = 6 - str_idx  # voicing[0]=6弦, voicing[5]=1弦
                open_pitch = STANDARD_TUNING[string_num]
                midi_pitch = open_pitch + fret
                
                note_name = NOTE_NAMES[midi_pitch % 12] + str((midi_pitch // 12) - 1)
                
                note = {
                    "start_time": round(strum_time, 4),
                    "end_time": round(strum_time + dur, 4),
                    "midi_pitch": midi_pitch,
                    "velocity": vel,
                    "confidence": 0.95,
                    "note_name": note_name,
                    "frequency": round(440.0 * (2 ** ((midi_pitch - 69) / 12)), 2),
                    "techniques": [],
                    "bar": entry.get("bar", None),
                    "beat": entry.get("beat", None),
                }
                
                # ミュートビートのダウンストロークにブラッシング付与
                if is_muted_beat and sub == 0:
                    note["technique"] = "mute_brush"
                
                notes.append(note)
    
    notes.sort(key=lambda n: (n["start_time"], n["midi_pitch"]))
    
    brush_count = sum(1 for n in notes if n.get("technique") == "mute_brush")
    print(f"[ChordStrum] Generated {len(notes)} strum notes from {len(structured_data)} beats ({brush_count} muted)")
    return notes


# =========================================================================
# 音価の量子化（高精度版: 三連符・付点・32分音符対応）
# =========================================================================
def quantize_duration_to_note_type(
    duration: float,
    beat_duration: float,
    divisions: int = 12,
) -> Tuple[str, int, bool]:
    """
    実時間の長さを音符の種類に量子化する。
    divisions=12 で三連符にも対応。

    Parameters
    ----------
    duration : float
        ノートの実時間長（秒）
    beat_duration : float
        1拍の長さ（秒）
    divisions : int
        1拍あたりのdivision数。12でquarter=12, triplets=4(8th triplet)

    Returns
    -------
    (note_type, duration_divisions, is_dotted)
    """
    if beat_duration <= 0:
        return "quarter", divisions, False

    ratio = duration / beat_duration

    # 高精度量子化テーブル (ratio範囲, type, divisions倍率, dotted)
    # divisions=12の場合: whole=48, half=24, quarter=12, eighth=6, 16th=3, 32nd=1.5
    note_table = [
        # 全音符以上
        (3.5,  999.0, "whole",    48, False),
        # 付点2分
        (2.5,  3.5,   "half",    36, True),
        # 2分
        (1.75, 2.5,   "half",    24, False),
        # 付点4分
        (1.25, 1.75,  "quarter", 18, True),
        # 4分
        (0.875, 1.25, "quarter", 12, False),
        # 付点8分
        (0.625, 0.875, "eighth", 9,  True),
        # 8分
        (0.4375, 0.625, "eighth", 6, False),
        # 8分三連符  (ratio ~= 1/3 ~= 0.333)
        (0.29, 0.4375, "eighth", 4,  False),  # triplet: 12/3=4
        # 付点16分
        (0.21875, 0.29, "16th",  4,  True),
        # 16分
        (0.15625, 0.21875, "16th", 3, False),
        # 32分
        (0.0, 0.15625, "32nd",  1,   False),
    ]

    for min_r, max_r, ntype, divs, dotted in note_table:
        if min_r <= ratio < max_r:
            return ntype, divs, dotted

    return "quarter", divisions, False


# =========================================================================
# MusicXML 生成 -- ソロギター精密版
# =========================================================================
def notes_to_musicxml(
    notes: List[Dict],
    beats: List[float] = None,
    chords: List[Dict] = None,
    lyrics: List[tuple] = None,
    key: str = "C",
    time_sig: Tuple[int, int] = (4, 4),
    title: str = "NextChord Transcription",
    bpm: float = 120.0,
    tuning: Dict[int, int] = None,
) -> str:
    """
    MusicXML with 2 parts:
      Part 1 (Melody): 五線譜でメロディ + コード記号（Harmony）
      Part 2 (Guitar TAB): 実際の転記ノートをTAB譜で表示

    ソロギター向け: 転記ノートをTABに正確にマッピング。
    """
    print("DEBUG: tab_generator version 2026.02.20.01 (solo guitar precision)")

    if tuning is None:
        tuning = STANDARD_TUNING

    if not notes and not chords:
        return _empty_musicxml(title, key, time_sig)

    # Key normalization
    if not key:
        key = "C"
    key_root = key.split()[0] if " " in key else key
    key_mode = "minor" if "minor" in key.lower() or key.endswith("m") else "major"
    fifths = KEY_SIGNATURES.get(key_root, 0)
    if key_mode == "minor" and key_root + "m" in KEY_SIGNATURES:
        fifths = KEY_SIGNATURES[key_root + "m"]

    note_names = FLAT_NOTE_NAMES if fifths < 0 else SHARP_NOTE_NAMES

    # Tempo estimation
    beat_duration = 60.0 / bpm
    if beats is not None and len(beats) > 1:
        intervals = [beats[i+1] - beats[i] for i in range(len(beats)-1)]
        beat_duration = float(sum(intervals) / len(intervals))
        bpm = 60.0 / beat_duration

    divisions = 12  # 12で三連符対応
    beats_per_measure = time_sig[0]
    measure_duration = beat_duration * beats_per_measure
    measure_total_divs = divisions * beats_per_measure

    # --- ノートをTABデータに変換 ---
    tab_data = notes_to_tab_data(notes, beats, tuning)

    # Group notes by measure (bar番号があればそれを使う、なければtime計算)
    note_measures = {}
    for note in notes:
        if note.get("bar") is not None:
            m_num = note["bar"]  # structured_dataのbar番号(1-indexed)
        else:
            m_num = int(note["start_time"] / measure_duration) + 1 if measure_duration > 0 else 1
        if m_num not in note_measures:
            note_measures[m_num] = []
        note_measures[m_num].append(note)

    # Group tab data by measure (bar番号があればそれを使う)
    tab_measures = {}
    for td in tab_data:
        if td.get("bar") is not None:
            m_num = td["bar"]
        else:
            m_num = int(td["time"] / measure_duration) + 1 if measure_duration > 0 else 1
        if m_num not in tab_measures:
            tab_measures[m_num] = []
        tab_measures[m_num].append(td)

    # Group chords by measure
    chord_measures = {}
    if chords:
        for c in chords:
            m_num = c.get("bar") or (int(c["time"] / measure_duration) + 1)
            if m_num not in chord_measures:
                chord_measures[m_num] = []
            chord_measures[m_num].append(c)


    # Group lyrics by measure
    lyric_measures = {}
    if lyrics:
        for lyr in lyrics:
            # lyr = (bar, beat, start, end, text)
            if len(lyr) >= 5:
                m_num = lyr[0] + 1  # 0-indexed -> 1-indexed
                beat_pos = lyr[1]   # 0-indexed beat within measure
                if m_num not in lyric_measures:
                    lyric_measures[m_num] = []
                lyric_measures[m_num].append({
                    'beat': beat_pos,
                    'start': lyr[2],
                    'end': lyr[3],
                    'text': lyr[4]
                })
    
    all_keys = set()
    if note_measures: all_keys.update(note_measures.keys())
    if tab_measures: all_keys.update(tab_measures.keys())
    if chord_measures: all_keys.update(chord_measures.keys())
    if lyric_measures: all_keys.update(lyric_measures.keys())
    max_measure = max(all_keys) if all_keys else 1

    # --- Build MusicXML ---
    score = Element("score-partwise", version="4.0")
    work = SubElement(score, "work")
    SubElement(work, "work-title").text = title

    # --- defaults: スタッフ間距離を広めに設定（歌詞・コード記号の被り防止） ---
    defaults = SubElement(score, "defaults")
    scaling = SubElement(defaults, "scaling")
    SubElement(scaling, "millimeters").text = "7.0"
    SubElement(scaling, "tenths").text = "40"
    staff_layout = SubElement(defaults, "staff-layout")
    SubElement(staff_layout, "staff-distance").text = "150"
    system_layout = SubElement(defaults, "system-layout")
    system_margins = SubElement(system_layout, "system-margins")
    SubElement(system_margins, "left-margin").text = "0"
    SubElement(system_margins, "right-margin").text = "0"
    SubElement(system_layout, "system-distance").text = "200"
    SubElement(system_layout, "top-system-distance").text = "60"

    part_list = SubElement(score, "part-list")

    # Part 1: Melody (五線譜)
    p1_info = SubElement(part_list, "score-part", id="P1")
    SubElement(p1_info, "part-name").text = "Melody"

    # Part 2: Guitar TAB
    p2_info = SubElement(part_list, "score-part", id="P2")
    SubElement(p2_info, "part-name").text = "Guitar"
    p2_inst = SubElement(p2_info, "score-instrument", id="P2-I1")
    SubElement(p2_inst, "instrument-name").text = "Acoustic Guitar"
    p2_midi_inst = SubElement(p2_info, "midi-instrument", id="P2-I1")
    SubElement(p2_midi_inst, "midi-channel").text = "1"
    SubElement(p2_midi_inst, "midi-program").text = "25"

    part1 = SubElement(score, "part", id="P1")
    part2 = SubElement(score, "part", id="P2")

    parts = [part1, part2]
    prev_chord_name = None  # 小節間のコード重複排除用

    for m_num in range(1, max_measure + 1):
        for p_idx, part_obj in enumerate(parts):
            measure = SubElement(part_obj, "measure", number=str(m_num))

            # --- 小節1: attributes ---
            if m_num == 1:
                attrs = SubElement(measure, "attributes")
                SubElement(attrs, "divisions").text = str(divisions)
                key_elem = SubElement(attrs, "key")
                SubElement(key_elem, "fifths").text = str(fifths)
                SubElement(key_elem, "mode").text = key_mode
                time_elem = SubElement(attrs, "time")
                SubElement(time_elem, "beats").text = str(time_sig[0])
                SubElement(time_elem, "beat-type").text = str(time_sig[1])

                if p_idx == 1:  # Guitar TAB
                    clef = SubElement(attrs, "clef")
                    SubElement(clef, "sign").text = "TAB"
                    SubElement(clef, "line").text = "5"
                    # TAB staff details
                    staff_details = SubElement(attrs, "staff-details")
                    SubElement(staff_details, "staff-lines").text = "6"
                    for i in range(1, 7):
                        pitch = tuning[i]
                        t = SubElement(staff_details, "staff-tuning", line=str(7-i))
                        SubElement(t, "tuning-step").text = SHARP_NOTE_NAMES[pitch % 12][0]
                        if "#" in SHARP_NOTE_NAMES[pitch % 12]:
                            SubElement(t, "tuning-alter").text = "1"
                        SubElement(t, "tuning-octave").text = str((pitch // 12) - 1)
                else:  # Melody
                    clef = SubElement(attrs, "clef")
                    SubElement(clef, "sign").text = "G"
                    SubElement(clef, "line").text = "2"

                # Tempo (Part 1 only)
                if p_idx == 0:
                    direction = SubElement(measure, "direction", placement="above")
                    direction_type = SubElement(direction, "direction-type")
                    metronome = SubElement(direction_type, "metronome")
                    SubElement(metronome, "beat-unit").text = "quarter"
                    SubElement(metronome, "per-minute").text = str(int(bpm))

            # --- 小節内容 ---
            if p_idx == 0:
                # Part 1: Melody (五線譜 + コード記号)
                prev_chord_name = _build_melody_measure(
                    measure, m_num, note_measures, chord_measures, lyric_measures,
                    note_names, beat_duration, divisions, beats_per_measure,
                    measure_duration, measure_total_divs, prev_chord_name, beats
                )
            else:
                # Part 2: Guitar TAB (転記ノートをTABで表示)
                _build_tab_measure(
                    measure, m_num, tab_measures,
                    note_names, beat_duration, divisions, beats_per_measure,
                    measure_duration, measure_total_divs, tuning, beats
                )

    # Final XML
    rough = tostring(score, encoding="unicode")
    dom = minidom.parseString(rough)
    xml_decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    doctype = '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n'
    return xml_decl + doctype + dom.documentElement.toprettyxml(indent="  ")


def _insert_harmony_element(measure, c_name, offset_divs=None):
    """コード名からMusicXMLのharmony要素を生成して挿入する"""
    root_char = c_name[0].upper() if c_name else ""
    if root_char not in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
        return
    harm = SubElement(measure, "harmony")
    root = SubElement(harm, "root")
    SubElement(root, "root-step").text = root_char
    if len(c_name) > 1 and c_name[1] == "#":
        SubElement(root, "root-alter").text = "1"
    if len(c_name) > 1 and c_name[1] == "b":
        SubElement(root, "root-alter").text = "-1"
    kind = SubElement(harm, "kind")
    kind.text = _chord_name_to_kind(c_name)
    # offset で正確なビート位置を指定
    if offset_divs is not None and offset_divs > 0:
        SubElement(harm, "offset").text = str(int(offset_divs))


def _insert_invisible_rest(measure, duration):
    """空小節のスペーサー: <forward>で時間を進める（AlphaTabで何も表示しない）。
    
    以前は print-object="no" の <rest> ノートを使用していたが、
    AlphaTabがこの属性を無視して赤い四角を表示し、さらにMIDI再生にも
    悪影響を及ぼしていたため <forward> に変更。
    """
    fwd = SubElement(measure, "forward")
    SubElement(fwd, "duration").text = str(duration)
    return fwd



def _build_melody_measure(
    measure, m_num, note_measures, chord_measures, lyric_measures,
    note_names, beat_duration, divisions, beats_per_measure,
    measure_duration, measure_total_divs, prev_chord_name=None, beats=None
):
    """Part 1: Melody 五線譜を構築（歌詞付き）。戻り値: この小節の最後のコード名"""
    m_notes = note_measures.get(m_num, [])
    m_chords = chord_measures.get(m_num, [])
    m_lyrics = lyric_measures.get(m_num, [])  # この小節の歌詞

    # コード変化をビート位置ごとに整理 (division位置 -> chord_name)
    # 同じコードが続く場合はスキップし、変化点のみ記録
    # prev_chord_name: 前の小節から引き継いだ最後のコード
    chord_at_beat = {}
    last_chord_name = prev_chord_name
    for c_data in m_chords:
        c_name = c_data.get("chord", "N.C.")
        if c_name == last_chord_name or c_name == "N.C.":
            continue
        last_chord_name = c_name
        # beat位置を小節内のdivision位置に変換
        c_beat = c_data.get("beat", 1)  # 1-indexed
        c_div = (c_beat - 1) * divisions  # division位置
        chord_at_beat[c_div] = c_name

    # ★ コードを全て小節先頭に挿入（offsetで正確な位置を指定）
    for c_div in sorted(chord_at_beat.keys()):
        _insert_harmony_element(measure, chord_at_beat[c_div], offset_divs=c_div)

    if not m_notes:
        if m_lyrics:
            # 歌詞がある場合: 正規の休符ノートに歌詞を付与
            # ★ durationに対応する正しいtypeを使用（不一致はAlphaTabで赤四角になる）
            for lyr in m_lyrics:
                note_elem = SubElement(measure, "note")
                SubElement(note_elem, "rest")
                dur = measure_total_divs // max(len(m_lyrics), 1)
                SubElement(note_elem, "duration").text = str(dur)
                _nt, _dot = _divs_to_note_type(dur, divisions)
                SubElement(note_elem, "type").text = _nt
                if _dot:
                    SubElement(note_elem, "dot")
                lyric_elem = SubElement(note_elem, "lyric", number="1", **{"default-y": "-30"})
                SubElement(lyric_elem, "syllabic").text = "single"
                SubElement(lyric_elem, "text").text = lyr['text']
        else:
            _insert_invisible_rest(measure, measure_total_divs)
        return last_chord_name

    # ノートを時間順にソート & グループ化（同時発音）
    m_notes.sort(key=lambda n: (n["start_time"], n["midi_pitch"]))
    groups = _group_simultaneous_notes(m_notes, tolerance=0.03)

    # 各グループのdivision位置を先に計算
    group_positions = []
    for group in groups:
        if not group:
            continue
        note_start = group[0]["start_time"]
        # T-2: beats配列があれば正確なビート位置を計算
        if beats is not None and len(beats) > 1:
            beat_idx = int(np.searchsorted(beats, note_start, side='right')) - 1
            beat_idx = max(0, beat_idx)
            measure_first_beat = (m_num - 1) * beats_per_measure
            beat_in_measure = beat_idx - measure_first_beat
            if beat_idx < len(beats) - 1:
                local_beat_dur = beats[beat_idx + 1] - beats[beat_idx]
            else:
                local_beat_dur = beat_duration
            frac = (note_start - beats[beat_idx]) / local_beat_dur if local_beat_dur > 0 else 0.0
            raw_div = (beat_in_measure + frac) * divisions
        else:
            note_offset_in_measure = note_start - (m_num - 1) * measure_duration
            raw_div = note_offset_in_measure / beat_duration * divisions
        # T-4: グリッドスナップ
        target_div = snap_to_grid(round(raw_div), divisions)
        target_div = max(0, min(target_div, measure_total_divs - 1))
        group_positions.append((target_div, group))

    # グループが無い場合
    if not group_positions:
        _insert_invisible_rest(measure, measure_total_divs)
        return last_chord_name

    filled_divs = 0

    for g_idx, (target_div, group) in enumerate(group_positions):
        # ギャップは作らない: ノートの長さで吸収する

        # 次のグループまでの距離でノート長を決定（ギャップなし）
        if g_idx + 1 < len(group_positions):
            next_div = group_positions[g_idx + 1][0]
            note_divs = next_div - filled_divs
        else:
            note_divs = measure_total_divs - filled_divs

        if note_divs <= 0:
            note_divs = divisions  # 最小でも1拍分
        
        # 小節からはみ出さないようにクランプ
        remaining = measure_total_divs - filled_divs
        if note_divs > remaining:
            note_divs = remaining
        
        if note_divs <= 0:
            continue

        note_type, is_dotted = _divs_to_note_type(note_divs, divisions)

        # グループ内の各ノートを出力
        first_in_chord = True
        for note in group:
            note_elem = SubElement(measure, "note")
            if not first_in_chord:
                SubElement(note_elem, "chord")

            pitch_elem = SubElement(note_elem, "pitch")
            midi_p = note["midi_pitch"]
            step_name = note_names[midi_p % 12]
            step = step_name[0]
            alter = 1 if "#" in step_name else (-1 if "b" in step_name else 0)

            SubElement(pitch_elem, "step").text = step
            if alter != 0:
                SubElement(pitch_elem, "alter").text = str(alter)
            SubElement(pitch_elem, "octave").text = str((midi_p // 12) - 1)

            SubElement(note_elem, "duration").text = str(note_divs)
            SubElement(note_elem, "type").text = note_type
            if is_dotted:
                SubElement(note_elem, "dot")

            # 歌詞をグループの最初のノートにのみ付与（1ノート1歌詞）
            if first_in_chord and m_lyrics:
                note_start_time = note["start_time"]
                # このノートに最も近い歌詞を1つだけ検索
                best_lyr = None
                best_dist = float('inf')
                for lyr in m_lyrics:
                    dist = abs(lyr['start'] - note_start_time)
                    if dist < best_dist and dist < beat_duration * 0.8:
                        best_dist = dist
                        best_lyr = lyr
                if best_lyr:
                    lyric_elem = SubElement(note_elem, "lyric", number="1", **{"default-y": "-30"})
                    SubElement(lyric_elem, "syllabic").text = "single"
                    SubElement(lyric_elem, "text").text = best_lyr['text']
                    m_lyrics = [l for l in m_lyrics if l is not best_lyr]


            first_in_chord = False

        filled_divs += note_divs

    # 小節内で未割り当ての歌詞がある場合、歌詞がないノートに順番に分配
    if m_lyrics:
        note_elems = [ne for ne in measure.findall("note") if ne.find("chord") is None and ne.find("lyric") is None]
        for i, lyr in enumerate(m_lyrics):
            if i < len(note_elems):
                lyric_elem = SubElement(note_elems[i], "lyric", number="1", **{"default-y": "-30"})
                SubElement(lyric_elem, "syllabic").text = "single"
                SubElement(lyric_elem, "text").text = lyr['text']

    return last_chord_name


# =========================================================================
# テクニック表記ヘルパー関数
# =========================================================================

def _has_technique(techniques: list, name: str) -> bool:
    """テクニックリスト内に指定のテクニックが存在するか確認"""
    for t in techniques:
        if isinstance(t, str) and t == name:
            return True
        if isinstance(t, dict) and t.get("type") == name:
            return True
    return False


def _get_technique(techniques: list, name: str):
    """テクニックリストから指定のテクニック情報を取得（dict型で返す）"""
    for t in techniques:
        if isinstance(t, str) and t == name:
            return {"type": name}
        if isinstance(t, dict) and t.get("type") == name:
            return t
    return None


def _add_technique_notations(note_elem, notations, tech, techniques, measure_elem=None):
    """
    Add technique symbols to MusicXML output.
    
    MusicXML structure:
    <notations>
      <technical>
        <hammer-on>H</hammer-on>
        <pull-off>P</pull-off>
      </technical>
      <slide/>
      <ornaments><tremolo/></ornaments>
      <articulations><accent/></articulations>
    </notations>
    
    <direction> elements are added as children of <measure>, NOT <note>,
    per the MusicXML specification. They are inserted before the <note>.
    
    Parameters
    ----------
    note_elem : Element
        The <note> element.
    notations : Element
        The <notations> element (child of <note>).
    tech : Element
        The <technical> element (child of <notations>).
    techniques : list
        List of technique names or dicts.
    measure_elem : Element, optional
        The parent <measure> element, needed for <direction> elements.
    """
    from xml.etree.ElementTree import SubElement
    
    if not techniques:
        return
    
    # ハンマリングオン
    if _has_technique(techniques, "hammer_on"):
        ho = SubElement(tech, "hammer-on")
        ho.set("type", "start")
        ho.text = "H"
    
    # プルオフ
    if _has_technique(techniques, "pull_off"):
        po = SubElement(tech, "pull-off")
        po.set("type", "start")
        po.text = "P"
    
    # スライド
    if _has_technique(techniques, "slide_up") or _has_technique(techniques, "slide_down"):
        sl = SubElement(notations, "slide")
        sl.set("type", "start")
        sl.set("line-type", "solid")
    
    # ベンド
    if _has_technique(techniques, "bend"):
        bend_info = _get_technique(techniques, "bend")
        bend_elem = SubElement(tech, "bend")
        # ベンド量（半音単位）
        amount = 1.0  # デフォルト全音ベンド
        if isinstance(bend_info, dict):
            amount = bend_info.get("amount", 1.0)
        SubElement(bend_elem, "bend-alter").text = str(amount)
    
    # ビブラート
    if _has_technique(techniques, "vibrato"):
        ornaments = SubElement(notations, "ornaments")
        SubElement(ornaments, "wavy-line").set("type", "start")
    
    # ナチュラルハーモニクス
    if _has_technique(techniques, "natural_harmonic"):
        SubElement(tech, "harmonic")
    
    # タッピング
    if _has_technique(techniques, "tapping"):
        tap = SubElement(tech, "tap")
        tap.text = "T"
    
    # パームミュート -- <direction> must be child of <measure>, not <note>
    if _has_technique(techniques, "palm_mute"):
        if measure_elem is not None:
            # Insert <direction> before the <note> element in <measure>
            direction = Element("direction")
            direction.set("placement", "above")
            dt = SubElement(direction, "direction-type")
            words = SubElement(dt, "words")
            words.text = "P.M."
            # Find the position of note_elem in measure and insert before it
            note_index = list(measure_elem).index(note_elem)
            measure_elem.insert(note_index, direction)
        else:
            # Fallback: add as notation words if measure_elem not available
            words_elem = SubElement(notations, "other-notation")
            words_elem.set("type", "start")
            words_elem.text = "P.M."
    
    # アクセント / スタッカート
    has_artic = _has_technique(techniques, "accent") or _has_technique(techniques, "staccato")
    if has_artic:
        artic = SubElement(notations, "articulations")
        if _has_technique(techniques, "accent"):
            SubElement(artic, "accent")
        if _has_technique(techniques, "staccato"):
            SubElement(artic, "staccato")
    
    # トレモロ
    if _has_technique(techniques, "tremolo"):
        ornaments = notations.find("ornaments")
        if ornaments is None:
            ornaments = SubElement(notations, "ornaments")
        trem = SubElement(ornaments, "tremolo")
        trem.set("type", "single")
        trem.text = "3"  # 32nd note tremolo
    
    # トリル
    if _has_technique(techniques, "trill"):
        ornaments = notations.find("ornaments")
        if ornaments is None:
            ornaments = SubElement(notations, "ornaments")
        SubElement(ornaments, "trill-mark")


def _build_tab_measure(
    measure, m_num, tab_measures,
    note_names, beat_duration, divisions, beats_per_measure,
    measure_duration, measure_total_divs, tuning, beats=None
):
    """Part 2: Guitar TAB を構築（転記ノートをTABで表示）"""
    m_tabs = tab_measures.get(m_num, [])

    if not m_tabs:
        _insert_invisible_rest(measure, measure_total_divs)
        return

    # 時間順にソート & グループ化
    m_tabs.sort(key=lambda t: (t["time"], t["midi_pitch"]))
    groups = _group_tab_simultaneous(m_tabs, tolerance=0.03)

    # 各グループのdivision位置を先に計算
    group_positions = []
    for group in groups:
        if not group:
            continue
        tab_start = group[0]["time"]
        # T-2: beats配列があれば正確なビート位置を計算
        if beats is not None and len(beats) > 1:
            beat_idx = int(np.searchsorted(beats, tab_start, side='right')) - 1
            beat_idx = max(0, beat_idx)
            measure_first_beat = (m_num - 1) * beats_per_measure
            beat_in_measure = beat_idx - measure_first_beat
            if beat_idx < len(beats) - 1:
                local_beat_dur = beats[beat_idx + 1] - beats[beat_idx]
            else:
                local_beat_dur = beat_duration
            frac = (tab_start - beats[beat_idx]) / local_beat_dur if local_beat_dur > 0 else 0.0
            raw_div = (beat_in_measure + frac) * divisions
        else:
            tab_offset = tab_start - (m_num - 1) * measure_duration
            raw_div = tab_offset / beat_duration * divisions
        # T-4: グリッドスナップ
        target_div = snap_to_grid(round(raw_div), divisions)
        target_div = max(0, min(target_div, measure_total_divs - 1))
        group_positions.append((target_div, group))

    if not group_positions:
        _insert_invisible_rest(measure, measure_total_divs)
        return

    # T-5: 同弦衝突防止 -- 同弦の2ノートが同じbeat_posなら後者を3divs後方に押し出す
    _resolve_same_string_collisions(group_positions, measure_total_divs)

    filled_divs = 0

    for g_idx, (target_div, group) in enumerate(group_positions):

        # T-3: Hybrid IOI で duration を決定
        note_divs = _calc_hybrid_ioi_divs(
            g_idx, group, group_positions,
            filled_divs, measure_total_divs, divisions, beat_duration
        )

        if note_divs <= 0:
            note_divs = divisions  # 最小でも1拍分

        remaining = measure_total_divs - filled_divs
        if note_divs > remaining:
            note_divs = remaining

        # T-6: duration小節境界キャップ
        if filled_divs + note_divs > measure_total_divs:
            note_divs = measure_total_divs - filled_divs

        if note_divs <= 0:
            continue

        note_type, is_dotted = _divs_to_note_type(note_divs, divisions)

        # グループ内の各TABノートを出力
        first_in_chord = True
        for td in group:
            techniques = td.get("techniques", [])
            note_elem = SubElement(measure, "note")
            if not first_in_chord:
                SubElement(note_elem, "chord")
            first_in_chord = False

            # ピッチ情報（実音のまま記譜 -- AlphaTabはTABクレフでも自動転位しない）
            pitch_elem = SubElement(note_elem, "pitch")
            midi_p = td["midi_pitch"]
            written_midi = midi_p
            step_name = note_names[written_midi % 12]
            step = step_name[0]
            alter = 1 if "#" in step_name else (-1 if "b" in step_name else 0)

            SubElement(pitch_elem, "step").text = step
            if alter != 0:
                SubElement(pitch_elem, "alter").text = str(alter)
            SubElement(pitch_elem, "octave").text = str((written_midi // 12) - 1)

            SubElement(note_elem, "duration").text = str(note_divs)
            SubElement(note_elem, "type").text = note_type
            if is_dotted:
                SubElement(note_elem, "dot")

            # ブラッシング/ミュート/デッドノート: Xノートヘッド
            if _has_technique(techniques, "mute_brush") or _has_technique(techniques, "x"):
                SubElement(note_elem, "notehead").text = "x"
            # ゴーストノート: 括弧付きノートヘッド
            elif _has_technique(techniques, "ghost_note"):
                nh = SubElement(note_elem, "notehead")
                nh.text = "normal"
                nh.set("parentheses", "yes")

            # TAB technical notation + テクニック記号
            notations = SubElement(note_elem, "notations")
            tech = SubElement(notations, "technical")
            SubElement(tech, "string").text = str(td["string"])
            SubElement(tech, "fret").text = str(td["fret"])

            # テクニック要素を付加 (pass measure for <direction> placement)
            _add_technique_notations(note_elem, notations, tech, techniques, measure_elem=measure)

        filled_divs += note_divs


def _resolve_same_string_collisions(group_positions, measure_total_divs):
    """T-5: 同弦衝突防止 -- 同じbeat_posに同弦ノートがあれば後者を3divs押し出す"""
    # (beat_pos, string) -> 使用済みかどうか を追跡
    used = {}  # (beat_pos, string_num) -> True
    for gp_idx in range(len(group_positions)):
        beat_pos, group = group_positions[gp_idx]
        for td in group:
            key = (beat_pos, td["string"])
            if key in used:
                # 衝突: beat_posを3divs後方に押し出す
                new_pos = min(beat_pos + 3, measure_total_divs - 1)
                group_positions[gp_idx] = (new_pos, group)
                beat_pos = new_pos
                key = (beat_pos, td["string"])
            used[key] = True


def _calc_hybrid_ioi_divs(
    g_idx, group, group_positions,
    filled_divs, measure_total_divs, divisions, beat_duration
):
    """
    T-3: Hybrid IOI でdurationを決定する。
    1. 同弦の次ノートがある -> 同弦IOI (start差) を divisions 換算
    2. ない場合 -> 全弦の次ノートまでの距離を divisions 換算
    3. 最後のノート -> 小節末まで
    """
    current_strings = {td["string"] for td in group}
    current_time = group[0]["time"]

    # 1. 同弦の次ノートを探す
    same_string_ioi = None
    for future_idx in range(g_idx + 1, len(group_positions)):
        _, future_group = group_positions[future_idx]
        for ftd in future_group:
            if ftd["string"] in current_strings:
                ioi_sec = ftd["time"] - current_time
                if ioi_sec > 0:
                    same_string_ioi = round(ioi_sec / beat_duration * divisions)
                    same_string_ioi = snap_to_grid(same_string_ioi, divisions)
                break
        if same_string_ioi is not None:
            break

    if same_string_ioi is not None and same_string_ioi > 0:
        return same_string_ioi

    # 2. 全弦の次ノートまでの距離
    if g_idx + 1 < len(group_positions):
        next_div = group_positions[g_idx + 1][0]
        note_divs = next_div - filled_divs
        if note_divs > 0:
            return note_divs

    # 3. 最後のノート -> 小節末まで
    return measure_total_divs - filled_divs


def _group_tab_simultaneous(tabs: List[Dict], tolerance: float = 0.03) -> List[List[Dict]]:
    """TABデータの同時発音グループ化"""
    if not tabs:
        return []
    groups = []
    current = [tabs[0]]
    for i in range(1, len(tabs)):
        if abs(tabs[i]["time"] - current[0]["time"]) <= tolerance:
            current.append(tabs[i])
        else:
            groups.append(current)
            current = [tabs[i]]
    groups.append(current)
    return groups


def _divs_to_note_type(divs: int, divisions: int = 12):
    """divisions値から (note_type, is_dotted) を返す。
    
    divisions=12 の場合:
      whole=48, dotted half=36, half=24, dotted quarter=18,
      quarter=12, dotted eighth=9, eighth=6, triplet eighth=4,
      16th=3, 32nd=1-2
    
    付点音符を正しく判定し、AlphaTabでduration/type不整合による
    赤い四角やリズムのズレを防止する。
    """
    # 正確な値にマッチ（付点音符対応）
    exact_map = {
        48: ("whole", False),
        36: ("half", True),      # 付点2分
        24: ("half", False),
        18: ("quarter", True),   # 付点4分
        12: ("quarter", False),
        9:  ("eighth", True),    # 付点8分
        6:  ("eighth", False),
        4:  ("eighth", False),   # 三連符（8分）
        3:  ("16th", False),
        2:  ("16th", False),
        1:  ("32nd", False),
    }
    if divs in exact_map:
        return exact_map[divs]
    # 最も近い標準音価にスナップ
    closest = min(exact_map.keys(), key=lambda k: abs(k - divs))
    return exact_map[closest]


def _chord_name_to_kind(chord_name: str) -> str:
    """コード名からMusicXMLのkind文字列に変換"""
    name = chord_name
    if not name:
        return "major"

    # ルートを除去
    root = name[0]
    rest = name[1:]
    if rest.startswith("#") or rest.startswith("b"):
        rest = rest[1:]

    rest_lower = rest.lower()

    if "maj7" in rest_lower or "maj9" in rest_lower:
        return "major-seventh"
    elif "m7" in rest_lower or "min7" in rest_lower:
        return "minor-seventh"
    elif "dim7" in rest_lower:
        return "diminished-seventh"
    elif "dim" in rest_lower:
        return "diminished"
    elif "aug" in rest_lower:
        return "augmented"
    elif "sus4" in rest_lower:
        return "suspended-fourth"
    elif "sus2" in rest_lower:
        return "suspended-second"
    elif "add9" in rest_lower:
        return "major"  # add9 は major + added note
    elif "7" in rest:
        return "dominant"
    elif "m" in rest_lower or "min" in rest_lower:
        return "minor"
    else:
        return "major"


def _empty_musicxml(title: str, key: str, time_sig: Tuple[int, int]) -> str:
    """空のMusicXML（ノートなし）を生成"""
    score = Element("score-partwise", version="4.0")
    work = SubElement(score, "work")
    SubElement(work, "work-title").text = title
    part_list = SubElement(score, "part-list")
    score_part = SubElement(part_list, "score-part", id="P1")
    SubElement(score_part, "part-name").text = "Guitar"
    part = SubElement(score, "part", id="P1")
    measure = SubElement(part, "measure", number="1")
    attrs = SubElement(measure, "attributes")
    SubElement(attrs, "divisions").text = "12"
    key_elem = SubElement(attrs, "key")
    SubElement(key_elem, "fifths").text = "0"
    time_elem = SubElement(attrs, "time")
    SubElement(time_elem, "beats").text = str(time_sig[0])
    SubElement(time_elem, "beat-type").text = str(time_sig[1])
    clef = SubElement(attrs, "clef")
    SubElement(clef, "sign").text = "G"
    SubElement(clef, "line").text = "2"
    _insert_invisible_rest(measure, 12 * time_sig[0])

    rough_string = tostring(score, encoding="unicode")
    dom = minidom.parseString(rough_string)
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    doctype = '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n'
    return xml_declaration + doctype + dom.documentElement.toprettyxml(indent="  ")
