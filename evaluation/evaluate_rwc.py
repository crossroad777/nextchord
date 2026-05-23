"""
RWC Popular 100曲の BTC コード認識評価
- mirdata から曲名マッピング取得
- 既存の .lab アノテーション (uspop2002/RWC_Pop_Chords) を正解データとして使用
- YouTube から音源を自動ダウンロード
- BTC で予測 → mir_eval で評価
"""
import sys, os, subprocess, time, json
import numpy as np
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

FFMPEG = Path(r"D:\Music\nextchord\ffmpeg-7.1.1-essentials_build\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe")
YT_DLP = Path(r"D:\Music\nextchord\venv312\Scripts\yt-dlp.exe")
VENV_PYTHON = Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")
BACKEND_DIR = Path(r"D:\Music\nextchord\fastapi-backend")

# Paths
REF_DIR = Path(r"D:\Music\datasets\chord_datasets\uspop2002\RWC_Pop_Chords")
AUDIO_DIR = Path(r"D:\Music\nextchord\evaluation\rwc_audio")
PRED_DIR = Path(r"D:\Music\nextchord\evaluation\rwc_predictions")
REPORT_PATH = Path(r"D:\Music\nextchord\evaluation\rwc_report.json")

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
PRED_DIR.mkdir(parents=True, exist_ok=True)

# RWC track metadata
import mirdata
ds = mirdata.initialize("rwc_popular", data_home=r"D:\Music\datasets\rwc_popular")
tracks_meta = {}
for tid in ds.track_ids:
    t = ds.track(tid)
    tracks_meta[tid] = {"title": t.title, "artist": t.artist}

# Map .lab files to track metadata
# Lab files: N001-M01-T01.lab ... N100-M01-T01.lab
# Track IDs: RM-P001 ... RM-P100
lab_files = sorted([f for f in REF_DIR.iterdir() if f.suffix == ".lab"])
print(f"Found {len(lab_files)} .lab files")

# Build mapping
track_list = []
for lab in lab_files:
    # N001-M01-T01.lab → track number 001
    name = lab.stem  # N001-M01-T01
    num_str = name[1:4]  # "001"
    tid = f"RM-P{num_str}"
    meta = tracks_meta.get(tid, {})
    track_list.append({
        "lab_file": str(lab),
        "lab_stem": name,
        "track_id": tid,
        "title": meta.get("title", name),
        "artist": meta.get("artist", "RWC"),
    })

print(f"Mapped {len(track_list)} tracks\n")
for t in track_list[:5]:
    print(f"  {t['lab_stem']}: {t['artist']} - {t['title']}")
print("  ...\n")


def download_audio(track):
    out_path = AUDIO_DIR / f"{track['lab_stem']}.wav"
    if out_path.exists() and out_path.stat().st_size > 10000:
        return out_path

    query = f"{track['artist']} \"{track['title']}\" audio"
    temp_path = AUDIO_DIR / f"{track['lab_stem']}_temp"

    cmd = [
        str(YT_DLP),
        f"ytsearch1:{query}",
        "-x", "-o", str(temp_path) + ".%(ext)s",
        "--no-playlist", "--quiet", "--no-warnings",
        "--max-filesize", "50M",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return None

    temp_file = None
    for candidate in AUDIO_DIR.glob(f"{track['lab_stem']}_temp.*"):
        temp_file = candidate
        break

    if not temp_file:
        return None

    ffmpeg_cmd = [
        str(FFMPEG), "-y", "-i", str(temp_file),
        "-ar", "22050", "-ac", "1", "-f", "wav", str(out_path),
    ]
    subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=60)
    if temp_file.exists():
        temp_file.unlink()

    return out_path if out_path.exists() else None


def predict_btc(audio_path, track):
    pred_path = PRED_DIR / f"{track['lab_stem']}.lab"
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


def evaluate_single(ref_path, est_path):
    import mir_eval
    ref_intervals, ref_labels = mir_eval.io.load_labeled_intervals(ref_path)
    est_intervals, est_labels = mir_eval.io.load_labeled_intervals(est_path)
    scores = mir_eval.chord.evaluate(ref_intervals, ref_labels, est_intervals, est_labels)
    return {k: float(scores[k]) for k in ["root", "thirds", "mirex", "majmin", "sevenths"]}


# === MAIN ===
print(f"=== RWC Popular 評価開始 ({len(track_list)} tracks) ===\n")
t0 = time.time()
results = []
errors = 0

for i, track in enumerate(track_list):
    short = f"{track['artist']} - {track['title']}"
    print(f"[{i+1:3d}/{len(track_list)}] {short[:55]:<55s}", end=" ", flush=True)

    # 1. Download
    audio_path = download_audio(track)
    if not audio_path:
        print("[DL FAIL]")
        errors += 1
        continue

    # 2. Predict
    pred_path = predict_btc(audio_path, track)
    if not pred_path:
        print("[BTC FAIL]")
        errors += 1
        continue

    # 3. Evaluate
    try:
        scores = evaluate_single(track["lab_file"], str(pred_path))
        results.append({
            "track_id": track["track_id"],
            "title": track["title"],
            "artist": track["artist"],
            **scores,
        })
        print(f"root={scores['root']:.3f}  thirds={scores['thirds']:.3f}  mirex={scores['mirex']:.3f}")
    except Exception as e:
        print(f"[EVAL ERR: {e}]")
        errors += 1

elapsed = time.time() - t0
metrics = ["root", "thirds", "mirex", "majmin", "sevenths"]
avg = {m: round(float(np.mean([r[m] for r in results])), 4) for m in metrics} if results else {}

report = {
    "dataset": "RWC Popular",
    "total_tracks": len(track_list),
    "evaluated": len(results),
    "errors": errors,
    "elapsed_seconds": round(elapsed),
    "average": avg,
    "results": sorted(results, key=lambda x: x["thirds"], reverse=True),
}

with open(REPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"Evaluated: {len(results)} / {len(track_list)} (errors: {errors})")
print(f"Time: {elapsed:.0f}s")
print(f"\nAverage scores:")
for m in metrics:
    print(f"  {m:>10s}: {avg.get(m, 'N/A')}")

# Top / Bottom
if results:
    srt = sorted(results, key=lambda x: x["thirds"], reverse=True)
    print(f"\nTop 5:")
    for r in srt[:5]:
        print(f"  {r['thirds']:.3f}  {r['artist']} - {r['title']}")
    print(f"\nBottom 5:")
    for r in srt[-5:]:
        print(f"  {r['thirds']:.3f}  {r['artist']} - {r['title']}")

print(f"\nReport saved: {REPORT_PATH}")
