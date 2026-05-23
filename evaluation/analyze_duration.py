"""
uspop2002 Duration分析 (正しいマッチング)
"""
import sys, json
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import mir_eval
from pathlib import Path

PRED_DIR = Path(r"D:\Music\nextchord\evaluation\uspop_predictions")
REF_DIR = Path(r"D:\Music\datasets\chord_datasets\uspop2002\uspopLabels")

# Build ref map: artist__tracknum-title -> path
ref_map = {}
for f in REF_DIR.rglob("*.lab"):
    artist = f.parent.parent.name
    stem = f.stem
    key = f"{artist}__{stem}"
    ref_map[key] = str(f)

# Build pred map
pred_map = {f.stem: str(f) for f in PRED_DIR.glob("*.lab")}

# score lookup from report
with open(r"D:\Music\nextchord\evaluation\uspop_report.json") as f:
    report = json.load(f)

# The evaluate_uspop.py creates safe_name as: artist_dir_name__lab_stem
# where lab_stem is e.g. "01-Kryptonite"
# So pred_name == ref key directly

matched = 0
duration_data = []

for pred_name, pred_path in pred_map.items():
    ref_path = ref_map.get(pred_name)
    if not ref_path:
        continue
    
    try:
        ref_int, _ = mir_eval.io.load_labeled_intervals(ref_path)
        est_int, _ = mir_eval.io.load_labeled_intervals(pred_path)
        ref_dur = ref_int[-1][1]
        est_dur = est_int[-1][1]
        ratio = est_dur / ref_dur if ref_dur > 0 else 0
        
        # Find score in report
        # safe_name in evaluate_uspop: artist.replace(" ","_") + "__" + lab_stem
        # But report stores artist with spaces and title with spaces
        # Let's just search by pred_name parts
        parts = pred_name.split("__", 1)
        if len(parts) != 2:
            continue
        artist_u = parts[0].replace("_", " ")
        title_u = parts[1].replace("_", " ")
        # remove track number from title
        if len(title_u) > 3 and title_u[2] == "-":
            title_u = title_u[3:]
        
        thirds = None
        for r in report["results"]:
            if r["artist"].lower() == artist_u.lower() and r["title"].lower() == title_u.lower():
                thirds = r["thirds"]
                break
        
        if thirds is not None:
            duration_data.append({
                "name": pred_name,
                "artist": artist_u,
                "title": title_u,
                "thirds": thirds,
                "ref_dur": ref_dur,
                "est_dur": est_dur,
                "ratio": ratio,
            })
            matched += 1
    except:
        pass

print(f"Matched: {matched}/{len(pred_map)}")

# Duration analysis
good = [x for x in duration_data if 0.85 <= x["ratio"] <= 1.15]
bad = [x for x in duration_data if not (0.85 <= x["ratio"] <= 1.15)]

print(f"\nDuration match (±15%): {len(good)}")
print(f"Duration mismatch: {len(bad)}")

if good:
    g_thirds = [x["thirds"] for x in good]
    print(f"\n--- Duration-match ({len(good)}曲) ---")
    print(f"  avg thirds: {np.mean(g_thirds):.4f}")
    hi = sum(1 for x in good if x["thirds"] >= 0.7)
    mid = sum(1 for x in good if 0.3 <= x["thirds"] < 0.7)
    lo = sum(1 for x in good if x["thirds"] < 0.3)
    print(f"  >=0.7: {hi}, 0.3-0.7: {mid}, <0.3: {lo}")
    
    g_good = [x for x in good if x["thirds"] >= 0.3]
    if g_good:
        print(f"  thirds>=0.3: {len(g_good)} tracks, avg={np.mean([x['thirds'] for x in g_good]):.4f}")

if bad:
    b_thirds = [x["thirds"] for x in bad]
    print(f"\n--- Duration-mismatch ({len(bad)}曲) ---")
    print(f"  avg thirds: {np.mean(b_thirds):.4f}")
    hi = sum(1 for x in bad if x["thirds"] >= 0.7)
    mid = sum(1 for x in bad if 0.3 <= x["thirds"] < 0.7)
    lo = sum(1 for x in bad if x["thirds"] < 0.3)
    print(f"  >=0.7: {hi}, 0.3-0.7: {mid}, <0.3: {lo}")
    
    # Worst mismatches
    print(f"\n  Worst mismatches:")
    for x in sorted(bad, key=lambda z: abs(z["ratio"] - 1.0), reverse=True)[:10]:
        print(f"    {x['thirds']:.3f}  ratio={x['ratio']:.2f}  ref={x['ref_dur']:.0f}s est={x['est_dur']:.0f}s  {x['artist']} - {x['title']}")

# Duration-match but low score
gm_low = [x for x in good if x["thirds"] < 0.3]
if gm_low:
    print(f"\n--- Duration-match BUT low score (<0.3): {len(gm_low)}曲 ---")
    for x in sorted(gm_low, key=lambda z: z["thirds"]):
        print(f"    {x['thirds']:.3f}  {x['artist']} - {x['title']}")

# ===== Combined benchmark =====
with open(r"D:\Music\nextchord\evaluation\beatles_report.json") as f:
    beatles = json.load(f)

b_all = beatles["results"]
b_good = [x for x in b_all if x["thirds"] >= 0.3]

print(f"\n{'='*65}")
print(f"総合ベンチマーク")
print(f"{'='*65}")
print(f"\n【Beatles】 {len(b_all)}曲, avg thirds = {beatles['average']['thirds']:.4f}")
print(f"  Good曲(>=0.3): {len(b_good)}曲, avg = {np.mean([x['thirds'] for x in b_good]):.4f}")

print(f"\n【uspop2002】 {len(report['results'])}曲, avg thirds = {report['average']['thirds']:.4f}")
if good:
    u_good = [x for x in good if x["thirds"] >= 0.3]
    print(f"  Duration-match: {len(good)}曲, avg = {np.mean([x['thirds'] for x in good]):.4f}")
    if u_good:
        print(f"  Duration-match & Good: {len(u_good)}曲, avg = {np.mean([x['thirds'] for x in u_good]):.4f}")

    # Combined
    combined = [x["thirds"] for x in b_good] + [x["thirds"] for x in u_good]
    print(f"\n【結合】 Beatles Good + uspop Clean: {len(combined)}曲")
    print(f"  avg thirds = {np.mean(combined):.4f}")

print(f"\n【BTC論文参照値 (正規CD)】")
print(f"  Beatles thirds: 0.860")
print(f"  uspop2002 thirds: ~0.75-0.80")
