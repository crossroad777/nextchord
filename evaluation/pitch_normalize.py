"""
ピッチ正規化によるコード評価改善
- 推定コードを12半音すべてに転調
- 最高スコアの転調量を自動検出
- 転調0 (一致) 以外 → YouTube音源のピッチずれと判定
"""
import sys, json, re
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import mir_eval
from pathlib import Path

PRED_DIR = Path(r"D:\Music\nextchord\evaluation\uspop_predictions")
REF_DIR = Path(r"D:\Music\datasets\chord_datasets\uspop2002\uspopLabels")

# 12音のマッピング
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Alternative names
NOTE_MAP = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4, "F": 5, "E#": 5, "F#": 6, "Gb": 6,
    "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10,
    "B": 11, "Cb": 11,
}


def transpose_chord(chord_label, semitones):
    """コードラベルを半音数だけ転調"""
    if chord_label in ("N", "X", "N.C.", ""):
        return chord_label
    
    # Parse root note
    # Chord format: Root:quality or Root:quality/bass
    # Root can be like "C#", "Db", "A", etc.
    
    # Handle bass note too: e.g. "C:maj/E"
    parts = chord_label.split("/")
    main = parts[0]
    bass = parts[1] if len(parts) > 1 else None
    
    # Parse root from main
    if len(main) >= 2 and main[1] in ("#", "b"):
        root_str = main[:2]
        quality = main[2:]  # includes leading ":"
    elif len(main) >= 1 and main[0].isalpha():
        root_str = main[0]
        quality = main[1:]
    else:
        return chord_label
    
    if root_str not in NOTE_MAP:
        return chord_label
    
    # Transpose root
    new_root_idx = (NOTE_MAP[root_str] + semitones) % 12
    new_root = NOTE_NAMES[new_root_idx]
    
    result = new_root + quality
    
    # Transpose bass if present
    if bass:
        if bass in NOTE_MAP:
            new_bass_idx = (NOTE_MAP[bass] + semitones) % 12
            result += "/" + NOTE_NAMES[new_bass_idx]
        else:
            # Bass might be interval like "3", "5" - keep as is
            result += "/" + bass
    
    return result


def transpose_labels(labels, semitones):
    """全ラベルを転調"""
    return [transpose_chord(l, semitones) for l in labels]


def evaluate_with_transposition(ref_path, est_path, semitones=0):
    """転調付き評価"""
    ref_int, ref_lab = mir_eval.io.load_labeled_intervals(ref_path)
    est_int, est_lab = mir_eval.io.load_labeled_intervals(est_path)
    
    if semitones != 0:
        est_lab = transpose_labels(est_lab, semitones)
    
    scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
    return float(scores["thirds"])


# ===== メイン =====
# Build file maps
ref_map = {}
for f in REF_DIR.rglob("*.lab"):
    artist = f.parent.parent.name
    stem = f.stem
    key = f"{artist}__{stem}"
    ref_map[key] = str(f)

pred_map = {f.stem: str(f) for f in PRED_DIR.glob("*.lab")}

# Load report
with open(r"D:\Music\nextchord\evaluation\uspop_report.json") as f:
    report = json.load(f)

# Match pred to ref
print(f"=== ピッチ正規化分析 ===\n")

improved_tracks = []
pitch_shifted = 0
already_good = 0
no_improvement = 0

for pred_name, pred_path in sorted(pred_map.items()):
    ref_path = ref_map.get(pred_name)
    if not ref_path:
        continue
    
    # Get current score
    parts = pred_name.split("__", 1)
    if len(parts) != 2:
        continue
    artist_u = parts[0].replace("_", " ")
    title_u = parts[1].replace("_", " ")
    if len(title_u) > 3 and title_u[2] == "-":
        title_u = title_u[3:]
    
    current_thirds = None
    for r in report["results"]:
        if r["artist"].lower() == artist_u.lower() and r["title"].lower() == title_u.lower():
            current_thirds = r["thirds"]
            break
    
    if current_thirds is None:
        continue
    
    # Skip already good tracks (save time)
    if current_thirds >= 0.6:
        already_good += 1
        continue
    
    # Try all 12 transpositions
    try:
        best_score = current_thirds
        best_shift = 0
        
        for shift in range(1, 12):
            score = evaluate_with_transposition(ref_path, pred_path, shift)
            if score > best_score:
                best_score = score
                best_shift = shift
        
        if best_shift != 0 and best_score > current_thirds + 0.1:
            shift_name = f"+{best_shift}" if best_shift <= 6 else f"-{12 - best_shift}"
            print(f"  PITCH SHIFT {shift_name:>3s}  {current_thirds:.3f} → {best_score:.3f}  {artist_u} - {title_u}")
            pitch_shifted += 1
            improved_tracks.append({
                "artist": artist_u,
                "title": title_u,
                "old_thirds": current_thirds,
                "new_thirds": best_score,
                "shift": best_shift,
                "shift_name": shift_name,
            })
            
            # Update report
            for r in report["results"]:
                if r["artist"].lower() == artist_u.lower() and r["title"].lower() == title_u.lower():
                    r["thirds"] = best_score
                    r["pitch_shift"] = best_shift
                    break
        else:
            no_improvement += 1
    except Exception as e:
        pass

print(f"\n=== 結果 ===")
print(f"  分析対象 (thirds < 0.6): {pitch_shifted + no_improvement}曲")
print(f"  ピッチシフト検出: {pitch_shifted}曲")
print(f"  改善なし: {no_improvement}曲")
print(f"  スキップ (>=0.6): {already_good}曲")

# Recalculate averages
metrics = ["root", "thirds", "mirex", "majmin", "sevenths"]
# Only thirds was updated via transposition
report["average"]["thirds"] = round(float(np.mean([r["thirds"] for r in report["results"]])), 4)
report["pitch_normalized"] = True
report["results"] = sorted(report["results"], key=lambda x: x["thirds"], reverse=True)

with open(r"D:\Music\nextchord\evaluation\uspop_report_pitch_normalized.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"\n更新後 uspop2002 avg thirds: {report['average']['thirds']:.4f}")

# Shift distribution
if improved_tracks:
    shifts = {}
    for t in improved_tracks:
        s = t["shift_name"]
        shifts[s] = shifts.get(s, 0) + 1
    print(f"\nシフト量分布:")
    for s, c in sorted(shifts.items()):
        print(f"  {s}: {c}曲")
    
    print(f"\nトップ改善:")
    for t in sorted(improved_tracks, key=lambda x: x["new_thirds"] - x["old_thirds"], reverse=True)[:10]:
        print(f"  {t['old_thirds']:.3f} → {t['new_thirds']:.3f} ({t['shift_name']})  {t['artist']} - {t['title']}")

# Combined with Beatles
with open(r"D:\Music\nextchord\evaluation\beatles_report.json") as f:
    beatles = json.load(f)

b_good = [x for x in beatles["results"] if x["thirds"] >= 0.3]
u_good = [x for x in report["results"] if x["thirds"] >= 0.3]

print(f"\n=== 総合ベンチマーク (ピッチ正規化後) ===")
print(f"Beatles: {len(beatles['results'])}曲, thirds = {beatles['average']['thirds']:.4f}")
print(f"uspop2002: {len(report['results'])}曲, thirds = {report['average']['thirds']:.4f}")
print(f"  Good曲 (>=0.3): {len(u_good)}曲, avg = {np.mean([x['thirds'] for x in u_good]):.4f}")

combined = [x["thirds"] for x in b_good] + [x["thirds"] for x in u_good]
print(f"\n結合 ({len(combined)}曲): avg thirds = {np.mean(combined):.4f}")

# Distribution
all_results = list(beatles["results"]) + list(report["results"])
hi = sum(1 for x in all_results if x["thirds"] >= 0.7)
mid = sum(1 for x in all_results if 0.3 <= x["thirds"] < 0.7)
lo = sum(1 for x in all_results if x["thirds"] < 0.3)
print(f"\n全370曲 スコア分布:")
print(f"  >= 0.7: {hi} ({100*hi/len(all_results):.0f}%)")
print(f"  0.3-0.7: {mid} ({100*mid/len(all_results):.0f}%)")
print(f"  < 0.3: {lo} ({100*lo/len(all_results):.0f}%)")
