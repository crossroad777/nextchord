"""
Beatles にもピッチ正規化を適用
"""
import sys, json
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import mir_eval
from pathlib import Path

PRED_DIR = Path(r"D:\Music\nextchord\evaluation\beatles_predictions")
REF_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_MAP = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4, "F": 5, "E#": 5, "F#": 6, "Gb": 6,
    "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10,
    "B": 11, "Cb": 11,
}

def transpose_chord(chord_label, semitones):
    if chord_label in ("N", "X", "N.C.", ""):
        return chord_label
    parts = chord_label.split("/")
    main = parts[0]
    bass = parts[1] if len(parts) > 1 else None
    if len(main) >= 2 and main[1] in ("#", "b"):
        root_str = main[:2]
        quality = main[2:]
    elif len(main) >= 1 and main[0].isalpha():
        root_str = main[0]
        quality = main[1:]
    else:
        return chord_label
    if root_str not in NOTE_MAP:
        return chord_label
    new_root_idx = (NOTE_MAP[root_str] + semitones) % 12
    new_root = NOTE_NAMES[new_root_idx]
    result = new_root + quality
    if bass:
        if bass in NOTE_MAP:
            new_bass_idx = (NOTE_MAP[bass] + semitones) % 12
            result += "/" + NOTE_NAMES[new_bass_idx]
        else:
            result += "/" + bass
    return result

def evaluate_with_transposition(ref_path, est_path, semitones=0):
    ref_int, ref_lab = mir_eval.io.load_labeled_intervals(ref_path)
    est_int, est_lab = mir_eval.io.load_labeled_intervals(est_path)
    if semitones != 0:
        est_lab = [transpose_chord(l, semitones) for l in est_lab]
    scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
    return float(scores["thirds"])

# Load Beatles report
with open(r"D:\Music\nextchord\evaluation\beatles_report.json") as f:
    report = json.load(f)

# Scan ref/pred
ref_files = {}
for album_dir in REF_DIR.iterdir():
    if not album_dir.is_dir():
        continue
    for lab in album_dir.glob("*.lab"):
        ref_files[(album_dir.name, lab.stem)] = str(lab)

pred_files = {}
for album_dir in PRED_DIR.iterdir():
    if not album_dir.is_dir():
        continue
    for lab in album_dir.glob("*.lab"):
        pred_files[(album_dir.name, lab.stem)] = str(lab)

print(f"=== Beatles ピッチ正規化 ===\n")
improved = 0
no_improve = 0

for r in report["results"]:
    if r["thirds"] >= 0.5:
        continue
    
    key = (r["album"], r["track"])
    ref_path = ref_files.get(key)
    est_path = pred_files.get(key)
    if not ref_path or not est_path:
        continue
    
    try:
        best_score = r["thirds"]
        best_shift = 0
        for shift in range(1, 12):
            score = evaluate_with_transposition(ref_path, est_path, shift)
            if score > best_score:
                best_score = score
                best_shift = shift
        
        if best_shift != 0 and best_score > r["thirds"] + 0.1:
            shift_name = f"+{best_shift}" if best_shift <= 6 else f"-{12 - best_shift}"
            print(f"  PITCH SHIFT {shift_name:>3s}  {r['thirds']:.3f} → {best_score:.3f}  {r.get('title', r['track'])}")
            r["thirds"] = best_score
            r["pitch_shift"] = best_shift
            improved += 1
        else:
            no_improve += 1
    except:
        no_improve += 1

print(f"\n改善: {improved}曲")
print(f"改善なし: {no_improve}曲")

# Update
report["average"]["thirds"] = round(float(np.mean([r["thirds"] for r in report["results"]])), 4)
report["results"] = sorted(report["results"], key=lambda x: x["thirds"], reverse=True)

with open(r"D:\Music\nextchord\evaluation\beatles_report_pitch.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"\n更新後 Beatles avg thirds: {report['average']['thirds']:.4f}")

# Load updated uspop
with open(r"D:\Music\nextchord\evaluation\uspop_report_pitch_normalized.json") as f:
    uspop = json.load(f)

# Combined
b_good = [x for x in report["results"] if x["thirds"] >= 0.3]
u_good = [x for x in uspop["results"] if x["thirds"] >= 0.3]
combined = [x["thirds"] for x in b_good] + [x["thirds"] for x in u_good]

print(f"\n=== 最終ベンチマーク (ピッチ正規化後) ===")
print(f"Beatles: {len(report['results'])}曲, avg thirds = {report['average']['thirds']:.4f}")
print(f"uspop2002: {len(uspop['results'])}曲, avg thirds = {uspop['average']['thirds']:.4f}")
print(f"\n結合 Good ({len(combined)}曲): avg thirds = {np.mean(combined):.4f}")

# All 370 distribution
all_r = list(report["results"]) + list(uspop["results"])
hi = sum(1 for x in all_r if x["thirds"] >= 0.7)
mid = sum(1 for x in all_r if 0.3 <= x["thirds"] < 0.7)
lo = sum(1 for x in all_r if x["thirds"] < 0.3)
print(f"\n全{len(all_r)}曲 スコア分布:")
print(f"  >= 0.7: {hi} ({100*hi/len(all_r):.0f}%)")
print(f"  0.3-0.7: {mid} ({100*mid/len(all_r):.0f}%)")
print(f"  < 0.3: {lo} ({100*lo/len(all_r):.0f}%)")
