import sys, json
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np

with open(r"D:\Music\nextchord\evaluation\beatles_report.json", "r", encoding="utf-8") as f:
    beatles = json.load(f)
with open(r"D:\Music\nextchord\evaluation\uspop_report_pitch_normalized.json", "r", encoding="utf-8") as f:
    uspop = json.load(f)

b_all = beatles["results"]
u_all = uspop["results"]

b_good = [x for x in b_all if x["thirds"] >= 0.3]
u_good = [x for x in u_all if x["thirds"] >= 0.3]
combined = [x["thirds"] for x in b_good] + [x["thirds"] for x in u_good]

print("=== FINAL BENCHMARK (Pitch Normalized) ===")
b_avg = beatles["average"]["thirds"]
u_avg = uspop["average"]["thirds"]
bg_avg = float(np.mean([x["thirds"] for x in b_good]))
ug_avg = float(np.mean([x["thirds"] for x in u_good]))
c_avg = float(np.mean(combined))

print(f"Beatles: {len(b_all)} tracks, avg thirds = {b_avg:.4f}")
print(f"  Good (>=0.3): {len(b_good)} tracks, avg = {bg_avg:.4f}")
print()
print(f"uspop2002 (pitch-norm): {len(u_all)} tracks, avg thirds = {u_avg:.4f}")
print(f"  Good (>=0.3): {len(u_good)} tracks, avg = {ug_avg:.4f}")
print()
print(f"Combined Good: {len(combined)} tracks, avg thirds = {c_avg:.4f}")
print()

all_r = b_all + u_all
hi = sum(1 for x in all_r if x["thirds"] >= 0.7)
mid = sum(1 for x in all_r if 0.3 <= x["thirds"] < 0.7)
lo = sum(1 for x in all_r if x["thirds"] < 0.3)
total = len(all_r)
print(f"全{total}曲 スコア分布:")
print(f"  >= 0.7: {hi} ({100*hi//total}%)")
print(f"  0.3-0.7: {mid} ({100*mid//total}%)")
print(f"  < 0.3: {lo} ({100*lo//total}%)")
print()
print("BTC論文参照値 (正規CD):")
print("  Beatles thirds: 0.860")
print("  uspop2002 thirds: ~0.75-0.80")
