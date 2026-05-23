"""
GuitarSet BTC コード認識評価
- 正規音源（マイク録音）使用 — YouTube不要
- 360トラック (30曲 × 6スタイル × comp/solo)
- ソロギター弾き語り特化のベンチマーク
"""
import sys, os, subprocess, time, json
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import mir_eval
import mirdata
from pathlib import Path

VENV_PYTHON = Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")
BACKEND_DIR = Path(r"D:\Music\nextchord\fastapi-backend")
PRED_DIR = Path(r"D:\Music\nextchord\evaluation\guitarset_predictions")
PRED_DIR.mkdir(parents=True, exist_ok=True)

ds = mirdata.initialize("guitarset", data_home=r"D:\Music\datasets\guitarset")

# Collect all tracks with chords and audio
tracks = []
for tid in sorted(ds.track_ids):
    t = ds.track(tid)
    if not os.path.exists(t.audio_mic_path):
        continue
    chords = t.leadsheet_chords
    if chords is None or len(chords.labels) == 0:
        continue
    tracks.append({
        "track_id": tid,
        "audio_path": t.audio_mic_path,
        "style": t.style,
        "chords": chords,
    })

print(f"GuitarSet: {len(tracks)} tracks with chords + audio")

# Style breakdown
from collections import Counter
styles = Counter(t["style"] for t in tracks)
print(f"Styles: {dict(styles)}")
print()


def predict_btc(audio_path, track_id):
    pred_path = PRED_DIR / f"{track_id}.lab"
    if pred_path.exists() and pred_path.stat().st_size > 0:
        return pred_path

    script = f'''
import sys, warnings
warnings.filterwarnings('ignore')
import librosa
sys.path.insert(0, r"{BACKEND_DIR}")
from btc_engine import BTCEngine

engine = BTCEngine(use_large_voca=True)
seg_starts, seg_labels = engine.detect_chords(r"{audio_path}")

y, sr = librosa.load(r"{audio_path}", sr=22050)
duration = librosa.get_duration(y=y, sr=sr)

lines = []
for i in range(len(seg_starts)):
    start = seg_starts[i]
    end = seg_starts[i+1] if i+1 < len(seg_starts) else duration
    lines.append(f"{{start:.6f}} {{end:.6f}} {{seg_labels[i]}}")
print("\\n".join(lines))
'''
    result = subprocess.run(
        [str(VENV_PYTHON), "-c", script],
        capture_output=True, text=True, timeout=180,
        cwd=str(BACKEND_DIR),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}
    )
    lines = [l for l in result.stdout.strip().split("\n") if l and l[0].isdigit()]
    if not lines:
        return None
    with open(pred_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return pred_path


# === MAIN ===
print(f"=== GuitarSet 評価開始 ({len(tracks)} tracks) ===\n")
t0 = time.time()
results = []
errors = 0

for i, track in enumerate(tracks):
    tid = track["track_id"]
    print(f"[{i+1:3d}/{len(tracks)}] {tid[:50]:<50s}", end=" ", flush=True)

    # 1. Predict
    pred_path = predict_btc(track["audio_path"], tid)
    if not pred_path:
        print("[BTC FAIL]")
        errors += 1
        continue

    # 2. Evaluate
    try:
        est_int, est_lab = mir_eval.io.load_labeled_intervals(str(pred_path))
        ref_int = track["chords"].intervals
        ref_lab = list(track["chords"].labels)

        scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
        result = {
            "track_id": tid,
            "style": track["style"],
            "root": float(scores["root"]),
            "thirds": float(scores["thirds"]),
            "mirex": float(scores["mirex"]),
            "majmin": float(scores["majmin"]),
            "sevenths": float(scores["sevenths"]),
        }
        results.append(result)
        print(f"thirds={result['thirds']:.3f}")
    except Exception as e:
        print(f"[ERR: {e}]")
        errors += 1

elapsed = time.time() - t0
metrics = ["root", "thirds", "mirex", "majmin", "sevenths"]
avg = {m: round(float(np.mean([r[m] for r in results])), 4) for m in metrics} if results else {}

# Per-style breakdown
style_scores = {}
for r in results:
    s = r["style"]
    if s not in style_scores:
        style_scores[s] = []
    style_scores[s].append(r["thirds"])

report = {
    "dataset": "GuitarSet",
    "total_tracks": len(tracks),
    "evaluated": len(results),
    "errors": errors,
    "elapsed_seconds": round(elapsed),
    "average": avg,
    "per_style": {s: round(float(np.mean(v)), 4) for s, v in style_scores.items()},
    "results": sorted(results, key=lambda x: x["thirds"], reverse=True),
}

report_path = Path(r"D:\Music\nextchord\evaluation\guitarset_report.json")
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"Evaluated: {len(results)} / {len(tracks)} (errors: {errors})")
print(f"Time: {elapsed:.0f}s")
print(f"\nAverage scores:")
for m in metrics:
    print(f"  {m:>10s}: {avg.get(m, 'N/A')}")

print(f"\nPer-style thirds:")
for s, v in sorted(style_scores.items()):
    print(f"  {s:>20s}: {np.mean(v):.4f} ({len(v)} tracks)")

# Distribution
if results:
    hi = sum(1 for x in results if x["thirds"] >= 0.7)
    mid = sum(1 for x in results if 0.3 <= x["thirds"] < 0.7)
    lo = sum(1 for x in results if x["thirds"] < 0.3)
    print(f"\nScore distribution:")
    print(f"  >= 0.7: {hi}")
    print(f"  0.3-0.7: {mid}")
    print(f"  < 0.3: {lo}")

# comp vs solo
comp = [r for r in results if "_comp" in r["track_id"]]
solo = [r for r in results if "_solo" in r["track_id"]]
if comp:
    print(f"\nComp (伴奏) {len(comp)}曲: avg thirds = {np.mean([r['thirds'] for r in comp]):.4f}")
if solo:
    print(f"Solo (ソロ) {len(solo)}曲: avg thirds = {np.mean([r['thirds'] for r in solo]):.4f}")

print(f"\nReport saved: {report_path}")
