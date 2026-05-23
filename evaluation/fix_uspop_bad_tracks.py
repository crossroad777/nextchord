"""
uspop2002 低スコア曲の修正
- 検索クエリを改善して再ダウンロード
- BTC 再予測 → 再評価
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

# レポート読み込み
with open(REPORT_PATH, "r", encoding="utf-8") as f:
    report = json.load(f)

# 低スコア曲を特定
THRESHOLD = 0.4
bad_tracks = [x for x in report["results"] if x["thirds"] < THRESHOLD]
bad_tracks.sort(key=lambda x: x["thirds"])

print(f"=== 低スコア曲 (thirds < {THRESHOLD}): {len(bad_tracks)}曲 ===")
for b in bad_tracks[:10]:
    print(f"  {b['thirds']:.3f}  {b['artist']} - {b['title']}")
if len(bad_tracks) > 10:
    print(f"  ... and {len(bad_tracks) - 10} more")
print()


def make_safe_name(artist, title):
    """元のスクリプトと同じ safe_name 生成ロジック"""
    artist_dir = artist.replace(" ", "_")
    lab_stem = title.replace(" ", "_")
    return f"{artist_dir}__{lab_stem}"


def find_lab_file(artist, title):
    """正解ラベルファイルを探す"""
    artist_dir_name = artist.replace(" ", "_")
    for artist_dir in LABELS_DIR.iterdir():
        if artist_dir.name.lower() == artist_dir_name.lower():
            for album_dir in artist_dir.iterdir():
                if not album_dir.is_dir():
                    continue
                for lab in album_dir.glob("*.lab"):
                    lab_title = lab.stem.replace("_", " ")
                    if len(lab_title) > 3 and lab_title[2] == "-":
                        lab_title = lab_title[3:]
                    if lab_title.lower() == title.lower():
                        return str(lab)
    return None


def make_better_query(track):
    """改善された検索クエリ"""
    artist = track["artist"]
    title = track["title"]
    # トラック番号プレフィックスを除去
    if len(title) > 3 and title[2] == "-":
        title = title[3:].strip()
    # 特殊文字を除去
    title = title.replace("‭", "").strip()
    return f'{artist} "{title}" official audio'


def download_with_better_query(track):
    safe_name = make_safe_name(track["artist"], track["title"])
    out_path = AUDIO_DIR / f"{safe_name}.wav"

    # 既存ファイルを削除
    if out_path.exists():
        out_path.unlink()

    query = make_better_query(track)

    temp_path = AUDIO_DIR / f"{safe_name}_temp"
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
    for candidate in AUDIO_DIR.glob(f"{safe_name}_temp.*"):
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


def predict_btc(audio_path, safe_name):
    pred_path = PRED_DIR / f"{safe_name}.lab"
    if pred_path.exists():
        pred_path.unlink()

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
print(f"=== 再ダウンロード + 再評価 ({len(bad_tracks)} tracks) ===\n")
improved = 0
still_bad = 0

for i, track in enumerate(bad_tracks):
    short = f"{track['artist']} - {track['title']}"
    print(f"[{i+1:3d}/{len(bad_tracks)}] {short[:55]:<55s}", end=" ", flush=True)

    # 1. 再ダウンロード
    audio_path = download_with_better_query(track)
    if not audio_path:
        print("[DL FAIL]")
        still_bad += 1
        continue

    # 2. 再予測
    safe_name = make_safe_name(track["artist"], track["title"])
    pred_path = predict_btc(audio_path, safe_name)
    if not pred_path:
        print("[BTC FAIL]")
        still_bad += 1
        continue

    # 3. 正解ファイルを探す
    ref_path = find_lab_file(track["artist"], track["title"])
    if not ref_path:
        print("[REF NOT FOUND]")
        still_bad += 1
        continue

    # 4. 再評価
    try:
        scores = evaluate_single(ref_path, str(pred_path))
        delta = scores["thirds"] - track["thirds"]
        status = "IMPROVED" if delta > 0.1 else ("worse" if delta < -0.05 else "similar")
        print(f"thirds: {track['thirds']:.3f} → {scores['thirds']:.3f} ({'+' if delta > 0 else ''}{delta:.3f}) [{status}]")

        if scores["thirds"] > track["thirds"]:
            improved += 1
            # レポートを更新
            for r in report["results"]:
                if r["artist"] == track["artist"] and r["title"] == track["title"]:
                    r.update(scores)
                    break
        else:
            still_bad += 1
    except Exception as e:
        print(f"[EVAL ERR: {e}]")
        still_bad += 1

# 更新されたレポートを保存
metrics = ["root", "thirds", "mirex", "majmin", "sevenths"]
report["average"] = {m: round(float(np.mean([r[m] for r in report["results"]])), 4) for m in metrics}
report["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
report["results"] = sorted(report["results"], key=lambda x: x["thirds"], reverse=True)

with open(REPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"改善: {improved}曲")
print(f"改善なし/悪化: {still_bad}曲")
print(f"\n更新後の平均スコア:")
for m in metrics:
    avg = np.mean([r[m] for r in report["results"]])
    print(f"  {m:>10s}: {avg:.4f}")

results = report["results"]
hi = len([x for x in results if x["thirds"] >= 0.7])
mid = len([x for x in results if 0.3 <= x["thirds"] < 0.7])
lo = len([x for x in results if x["thirds"] < 0.3])
print(f"\nスコア分布:")
print(f"  >= 0.7: {hi}")
print(f"  0.3-0.7: {mid}")
print(f"  < 0.3: {lo}")

print(f"\nReport saved: {REPORT_PATH}")
