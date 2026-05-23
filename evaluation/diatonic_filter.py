"""
ダイアトニックフィルタ: 音楽理論ベースのコード後処理

原理:
1. コード列からキー(調)を推定
2. 推定キーのダイアトニックコード表に基づき、
   非ダイアトニックコードを最寄りのダイアトニックコードに補正
3. maj/min の混同（最も一般的なエラー）を修正

例: Key=C の場合
  - ダイアトニック: C, Dm, Em, F, G, Am, Bdim
  - 検出 "E" (maj) → 補正 "E:min" (ダイアトニック)
  - 検出 "A" (maj) → 補正 "A:min" (ダイアトニック)
"""
import sys, json, copy
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import mir_eval
from pathlib import Path
from collections import Counter

# ===== 音楽理論テーブル =====

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_MAP = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4, "F": 5, "E#": 5, "F#": 6, "Gb": 6,
    "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10,
    "B": 11, "Cb": 11,
}

# Major scale intervals: W W H W W W H
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
# Natural minor scale intervals: W H W W H W W
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]

# Diatonic chord qualities for major key (I ii iii IV V vi vii°)
MAJOR_QUALITIES = ["maj", "min", "min", "maj", "maj", "min", "dim"]
# Diatonic chord qualities for minor key (i ii° III iv v VI VII)
MINOR_QUALITIES = ["min", "dim", "maj", "min", "min", "maj", "maj"]


def get_diatonic_chords(root_idx, mode="major"):
    """指定キーのダイアトニックコード一覧を返す"""
    scale = MAJOR_SCALE if mode == "major" else MINOR_SCALE
    qualities = MAJOR_QUALITIES if mode == "major" else MINOR_QUALITIES
    
    chords = []
    for i, interval in enumerate(scale):
        note_idx = (root_idx + interval) % 12
        note_name = NOTE_NAMES[note_idx]
        quality = qualities[i]
        chords.append((note_idx, note_name, quality))
    return chords


def parse_chord(label):
    """コードラベルをパース → (root_idx, quality, bass)"""
    if label in ("N", "X", "N.C.", ""):
        return None, None, None
    
    # Handle bass note
    parts = label.split("/")
    main = parts[0]
    bass = parts[1] if len(parts) > 1 else None
    
    # Parse root
    if len(main) >= 2 and main[1] in ("#", "b"):
        root_str = main[:2]
        quality_str = main[2:]
    elif len(main) >= 1 and main[0].isalpha():
        root_str = main[0]
        quality_str = main[1:]
    else:
        return None, None, None
    
    if root_str not in NOTE_MAP:
        return None, None, None
    
    root_idx = NOTE_MAP[root_str]
    
    # Classify quality
    q = quality_str.lstrip(":")
    if q in ("", "maj", "major"):
        quality = "maj"
    elif q in ("min", "minor", "m"):
        quality = "min"
    elif q.startswith("7") or q == "dom7":
        quality = "7"
    elif q.startswith("maj7"):
        quality = "maj7"
    elif q.startswith("min7"):
        quality = "min7"
    elif q in ("dim", "dim7"):
        quality = "dim"
    elif q in ("aug",):
        quality = "aug"
    elif q.startswith("sus"):
        quality = "sus"
    else:
        quality = q  # Keep original
    
    return root_idx, quality, bass


def estimate_key(labels, durations):
    """コード列からキーを推定 (Krumhansl-Schmuckler 簡易版)"""
    # 各音のウェイトを計算（コード根音の出現時間）
    root_weights = np.zeros(12)
    for label, dur in zip(labels, durations):
        root_idx, quality, _ = parse_chord(label)
        if root_idx is not None:
            root_weights[root_idx] += dur
    
    if root_weights.sum() == 0:
        return 0, "major"
    
    # Krumhansl-Kessler profiles
    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    
    best_corr = -1
    best_key = 0
    best_mode = "major"
    
    for key in range(12):
        # Rotate weights to align with key
        rotated = np.roll(root_weights, -key)
        
        # Correlate with profiles
        corr_maj = np.corrcoef(rotated, major_profile)[0, 1]
        corr_min = np.corrcoef(rotated, minor_profile)[0, 1]
        
        if corr_maj > best_corr:
            best_corr = corr_maj
            best_key = key
            best_mode = "major"
        if corr_min > best_corr:
            best_corr = corr_min
            best_key = key
            best_mode = "minor"
    
    return best_key, best_mode


def apply_diatonic_filter(labels, durations, strength="moderate"):
    """
    ダイアトニックフィルタを適用
    
    strength:
      "soft"     - maj/min の混同のみ修正
      "moderate" - maj/min + 7th コードの簡略化
      "strong"   - すべての非ダイアトニックを置換
    """
    # 1. キー推定
    key_idx, mode = estimate_key(labels, durations)
    
    # 2. ダイアトニックコード表を構築
    diatonic = get_diatonic_chords(key_idx, mode)
    diatonic_roots = {d[0]: d[2] for d in diatonic}  # root_idx → quality
    
    # 3. 各コードをフィルタ
    filtered = []
    changes = 0
    for label in labels:
        root_idx, quality, bass = parse_chord(label)
        
        if root_idx is None:
            filtered.append(label)
            continue
        
        new_label = label
        
        if root_idx in diatonic_roots:
            expected_quality = diatonic_roots[root_idx]
            
            if strength == "soft":
                # maj/min の混同のみ修正
                if quality == "maj" and expected_quality == "min":
                    new_label = NOTE_NAMES[root_idx] + ":min"
                    changes += 1
                elif quality == "min" and expected_quality == "maj":
                    new_label = NOTE_NAMES[root_idx] + ":maj"
                    changes += 1
            
            elif strength == "moderate":
                # maj/min + 7thコードの簡略化
                if quality in ("maj", "min") and expected_quality in ("maj", "min"):
                    if quality != expected_quality:
                        new_label = NOTE_NAMES[root_idx] + ":" + expected_quality
                        changes += 1
                elif quality in ("7", "dom7", "maj7", "min7"):
                    # 7thを基本形に戻す
                    new_label = NOTE_NAMES[root_idx] + ":" + expected_quality
                    changes += 1
            
            elif strength == "strong":
                # すべてダイアトニックに強制
                new_label = NOTE_NAMES[root_idx] + ":" + expected_quality
                if new_label != label:
                    changes += 1
        
        filtered.append(new_label)
    
    return filtered, key_idx, mode, changes


def evaluate_single(ref_path, est_labels, est_intervals):
    """カスタムラベルで評価"""
    ref_int, ref_lab = mir_eval.io.load_labeled_intervals(ref_path)
    scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_intervals, est_labels)
    return {k: float(scores[k]) for k in ["root", "thirds", "mirex", "majmin", "sevenths"]}


# ===== Beatles で評価 =====
PRED_DIR = Path(r"D:\Music\nextchord\evaluation\beatles_predictions")
REF_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")

with open(r"D:\Music\nextchord\evaluation\beatles_report.json", "r", encoding="utf-8") as f:
    report = json.load(f)

print("=" * 65)
print("ダイアトニックフィルタ評価 (Beatles)")
print("=" * 65)

# Collect ref/pred paths
ref_files = {}
for album_dir in REF_DIR.iterdir():
    if album_dir.is_dir():
        for lab in album_dir.glob("*.lab"):
            ref_files[(album_dir.name, lab.stem)] = str(lab)

pred_files = {}
for album_dir in PRED_DIR.iterdir():
    if album_dir.is_dir():
        for lab in album_dir.glob("*.lab"):
            pred_files[(album_dir.name, lab.stem)] = str(lab)

for strength in ["soft", "moderate", "strong"]:
    results_filtered = []
    total_changes = 0
    total_tracks = 0
    
    for r in report["results"]:
        key = (r["album"], r["track"])
        ref_path = ref_files.get(key)
        est_path = pred_files.get(key)
        if not ref_path or not est_path:
            continue
        
        try:
            est_int, est_lab = mir_eval.io.load_labeled_intervals(est_path)
            
            # Calculate durations
            durations = [est_int[i][1] - est_int[i][0] for i in range(len(est_int))]
            
            # Apply filter
            filtered_lab, key_idx, mode, changes = apply_diatonic_filter(
                est_lab, durations, strength=strength
            )
            total_changes += changes
            total_tracks += 1
            
            # Evaluate
            ref_int, ref_lab = mir_eval.io.load_labeled_intervals(ref_path)
            scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, filtered_lab)
            results_filtered.append({
                "thirds_orig": r["thirds"],
                "thirds_filtered": float(scores["thirds"]),
                "root_filtered": float(scores["root"]),
                "mirex_filtered": float(scores["mirex"]),
                "majmin_filtered": float(scores["majmin"]),
                "key": NOTE_NAMES[key_idx],
                "mode": mode,
                "changes": changes,
            })
        except:
            pass
    
    if results_filtered:
        avg_orig = np.mean([r["thirds_orig"] for r in results_filtered])
        avg_filt = np.mean([r["thirds_filtered"] for r in results_filtered])
        avg_root = np.mean([r["root_filtered"] for r in results_filtered])
        avg_mirex = np.mean([r["mirex_filtered"] for r in results_filtered])
        avg_majmin = np.mean([r["majmin_filtered"] for r in results_filtered])
        delta = avg_filt - avg_orig
        
        improved = sum(1 for r in results_filtered if r["thirds_filtered"] > r["thirds_orig"] + 0.01)
        worsened = sum(1 for r in results_filtered if r["thirds_filtered"] < r["thirds_orig"] - 0.01)
        
        print(f"\n--- strength={strength} ({total_tracks}曲, {total_changes} changes) ---")
        print(f"  thirds:  {avg_orig:.4f} → {avg_filt:.4f} ({'+' if delta >= 0 else ''}{delta:.4f})")
        print(f"  root:    {avg_root:.4f}")
        print(f"  mirex:   {avg_mirex:.4f}")
        print(f"  majmin:  {avg_majmin:.4f}")
        print(f"  改善: {improved}曲 / 悪化: {worsened}曲")
        
        # Top improvements
        by_delta = sorted(results_filtered, key=lambda x: x["thirds_filtered"] - x["thirds_orig"], reverse=True)
        if by_delta[0]["thirds_filtered"] > by_delta[0]["thirds_orig"] + 0.01:
            print(f"  トップ改善:")
            for b in by_delta[:5]:
                d = b["thirds_filtered"] - b["thirds_orig"]
                if d > 0.01:
                    print(f"    {b['thirds_orig']:.3f} → {b['thirds_filtered']:.3f} (+{d:.3f})")
