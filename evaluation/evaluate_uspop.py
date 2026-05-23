"""
uspop2002 148曲 BTC コード認識評価
- 有名洋楽ポップス。YouTube検索の精度が高い
- .lab ファイルは BTC互換フォーマット
"""
import sys, os, subprocess, time, json
import numpy as np
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

FFMPEG = Path(r"D:\Music\nextchord\ffmpeg-7.1.1-essentials_build\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe")
YT_DLP = Path(r"D:\Music\nextchord\venv312\Scripts\yt-dlp.exe")
VENV_PYTHON = Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")
BACKEND_DIR = Path(r"D:\Music\nextchord\fastapi-backend")

LABELS_DIR = Path(r"D:\Music\datasets\chord_datasets\uspop2002\uspopLabels")
AUDIO_DIR = Path(r"D:\Music\nextchord\evaluation\uspop_audio")
PRED_DIR = Path(r"D:\Music\nextchord\evaluation\uspop_predictions")
REPORT_PATH = Path(r"D:\Music\nextchord\evaluation\uspop_report.json")

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
PRED_DIR.mkdir(parents=True, exist_ok=True)

# Scan all .lab files
track_list = []
for artist_dir in sorted(LABELS_DIR.iterdir()):
    if not artist_dir.is_dir():
        continue
    artist = artist_dir.name.replace("_", " ")
    for album_dir in sorted(artist_dir.iterdir()):
        if not album_dir.is_dir():
            continue
        for lab_file in sorted(album_dir.glob("*.lab")):
            title = lab_file.stem.replace("_", " ")
            # Remove leading track numbers like "01-" 
            if len(title) > 3 and title[2] == "-":
                title = title[3:]
            track_list.append({
                "lab_file": str(lab_file),
                "artist": artist,
                "title": title,
                "safe_name": f"{artist_dir.name}__{lab_file.stem}",
            })

print(f"Found {len(track_list)} tracks from {len(set(t['artist'] for t in track_list))} artists")
for t in track_list[:5]:
    print(f"  {t['artist']} - {t['title']}")
print("  ...\n")


def download_audio(track):
    out_path = AUDIO_DIR / f"{track['safe_name']}.wav"
    if out_path.exists() and out_path.stat().st_size > 10000:
        return out_path

    query = f'{track["artist"]} "{track["title"]}" audio'
    temp_path = AUDIO_DIR / f"{track['safe_name']}_temp"

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
    for candidate in AUDIO_DIR.glob(f"{track['safe_name']}_temp.*"):
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
    pred_path = PRED_DIR / f"{track['safe_name']}.lab"
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
print(f"=== uspop2002 評価開始 ({len(track_list)} tracks) ===\n")
t0 = time.time()
results = []
errors = 0

for i, track in enumerate(track_list):
    short = f"{track['artist']} - {track['title']}"
    print(f"[{i+1:3d}/{len(track_list)}] {short[:55]:<55s}", end=" ", flush=True)

    audio_path = download_audio(track)
    if not audio_path:
        print("[DL FAIL]")
        errors += 1
        continue

    pred_path = predict_btc(audio_path, track)
    if not pred_path:
        print("[BTC FAIL]")
        errors += 1
        continue

    try:
        scores = evaluate_single(track["lab_file"], str(pred_path))
        results.append({"artist": track["artist"], "title": track["title"], **scores})
        print(f"root={scores['root']:.3f}  thirds={scores['thirds']:.3f}  mirex={scores['mirex']:.3f}")
    except Exception as e:
        print(f"[EVAL ERR: {e}]")
        errors += 1

elapsed = time.time() - t0
metrics = ["root", "thirds", "mirex", "majmin", "sevenths"]
avg = {m: round(float(np.mean([r[m] for r in results])), 4) for m in metrics} if results else {}

report = {
    "dataset": "uspop2002",
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

if results:
    srt = sorted(results, key=lambda x: x["thirds"], reverse=True)
    print(f"\nTop 5:")
    for r in srt[:5]:
        print(f"  {r['thirds']:.3f}  {r['artist']} - {r['title']}")
    print(f"\nBottom 5:")
    for r in srt[-5:]:
        print(f"  {r['thirds']:.3f}  {r['artist']} - {r['title']}")

# Distribution
hi = len([x for x in results if x["thirds"] >= 0.7])
mid = len([x for x in results if 0.3 <= x["thirds"] < 0.7])
lo = len([x for x in results if x["thirds"] < 0.3])
print(f"\nScore distribution:")
print(f"  >= 0.7: {hi}")
print(f"  0.3-0.7: {mid}")
print(f"  < 0.3: {lo}")

print(f"\nReport saved: {REPORT_PATH}")
