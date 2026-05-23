import json, sys, numpy as np
sys.stdout.reconfigure(encoding='utf-8')

with open(r'D:\Music\nextchord\evaluation\beatles_report.json', 'r') as f:
    r = json.load(f)

print(f"Evaluated: {r['evaluated']} / {r['total_tracks']}")
print(f"Errors: {r['errors']}")
print(f"Time: {r['elapsed_seconds']}s")
print(f"\nAverage scores:")
for k, v in r['average'].items():
    print(f"  {k:>10s}: {v:.4f}")

results = r['results']
low = [x for x in results if x['thirds'] < 0.3]
mid = [x for x in results if 0.3 <= x['thirds'] < 0.7]
hi = [x for x in results if x['thirds'] >= 0.7]

print(f"\nScore distribution:")
print(f"  thirds >= 0.7 (good):                {len(hi)} tracks")
print(f"  0.3 <= thirds < 0.7 (medium):        {len(mid)} tracks")
print(f"  thirds < 0.3 (bad - wrong audio?):    {len(low)} tracks")

if hi:
    good_avg = np.mean([x['thirds'] for x in hi])
    print(f"\nAverage thirds (good tracks >= 0.7): {good_avg:.4f}")
if hi + mid:
    ok_avg = np.mean([x['thirds'] for x in hi + mid])
    print(f"Average thirds (excluding bad < 0.3):  {ok_avg:.4f}")
