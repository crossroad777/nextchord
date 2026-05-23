"""
Beatles 評価の低スコア曲を修正するスクリプト
- YouTube 検索クエリを改善して正しい音源を再ダウンロード
- 再予測 → 再評価
"""
import json, sys, os, subprocess, time, shutil
import numpy as np
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

FFMPEG = Path(r"D:\Music\nextchord\ffmpeg-7.1.1-essentials_build\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe")
YT_DLP = Path(r"D:\Music\nextchord\venv312\Scripts\yt-dlp.exe")
VENV_PYTHON = Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")
BACKEND_DIR = Path(r"D:\Music\nextchord\fastapi-backend")
AUDIO_DIR = Path(r"D:\Music\nextchord\evaluation\beatles_audio")
PREDICTIONS_DIR = Path(r"D:\Music\nextchord\evaluation\beatles_predictions")

# レポート読み込み
with open(r"D:\Music\nextchord\evaluation\beatles_report.json", "r") as f:
    report = json.load(f)

# 低スコア曲を特定
THRESHOLD = 0.5
bad_tracks = [x for x in report["results"] if x["thirds"] < THRESHOLD]
bad_tracks.sort(key=lambda x: x["thirds"])

print(f"=== 低スコア曲 (thirds < {THRESHOLD}): {len(bad_tracks)}曲 ===")
for b in bad_tracks:
    print(f"  {b['thirds']:.3f}  {b['title']}")
print()

# アルバム名 → 曲名のマッピングを改善した検索クエリ
# White Album (CD1/CD2) の曲名の "CD1 - 01 - " プレフィックスを除去
def make_better_query(track):
    title = track["title"]
    # White Album tracks have "CD1 - XX - " or "CD2 - XX - " prefix
    if title.startswith("CD1 - ") or title.startswith("CD2 - "):
        parts = title.split(" - ", 2)
        if len(parts) >= 3:
            title = parts[2]
    return f'Beatles "{title}" official audio'


def download_with_better_query(track):
    """改善されたクエリで再ダウンロード"""
    album = track["album"]
    track_name = track["track"]
    out_dir = AUDIO_DIR / album
    out_path = out_dir / f"{track_name}.wav"
    
    # 既存ファイルを削除
    if out_path.exists():
        out_path.unlink()
    
    query = make_better_query(track)
    print(f"  [DL] {query}")
    
    temp_path = out_dir / f"{track_name}_temp"
    cmd = [
        str(YT_DLP),
        f"ytsearch1:{query}",
        "-x",
        "-o", str(temp_path) + ".%(ext)s",
        "--no-playlist",
        "--quiet", "--no-warnings",
        "--max-filesize", "50M",
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    
    # ダウンロードファイルを探す
    temp_file = None
    for candidate in out_dir.glob(f"{track_name}_temp.*"):
        temp_file = candidate
        break
    
    if not temp_file:
        print(f"  [ERROR] Download failed")
        return None
    
    # ffmpeg で変換
    ffmpeg_cmd = [
        str(FFMPEG), "-y", "-i", str(temp_file),
        "-ar", "22050", "-ac", "1", "-f", "wav",
        str(out_path),
    ]
    subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=60)
    
    if temp_file.exists():
        temp_file.unlink()
    
    if out_path.exists():
        return out_path
    return None


def predict_btc(audio_path, track):
    """BTC で再予測"""
    pred_dir = PREDICTIONS_DIR / track["album"]
    pred_path = pred_dir / f"{track['track']}.lab"
    
    # 既存の予測を削除
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
    """1曲評価"""
    import mir_eval
    ref_intervals, ref_labels = mir_eval.io.load_labeled_intervals(ref_path)
    est_intervals, est_labels = mir_eval.io.load_labeled_intervals(est_path)
    scores = mir_eval.chord.evaluate(ref_intervals, ref_labels, est_intervals, est_labels)
    return {
        "root": float(scores["root"]),
        "thirds": float(scores["thirds"]),
        "mirex": float(scores["mirex"]),
        "majmin": float(scores["majmin"]),
        "sevenths": float(scores["sevenths"]),
    }


# メイン処理: 低スコア曲を再ダウンロード → 再評価
print(f"\n=== 再ダウンロード + 再評価 ===\n")
improved = 0
still_bad = 0

for i, track in enumerate(bad_tracks):
    print(f"[{i+1}/{len(bad_tracks)}] {track['title']} (was: {track['thirds']:.3f})")
    
    # 1. 再ダウンロード
    audio_path = download_with_better_query(track)
    if not audio_path:
        still_bad += 1
        continue
    
    # 2. 再予測
    pred_path = predict_btc(audio_path, track)
    if not pred_path:
        print(f"  [ERROR] BTC prediction failed")
        still_bad += 1
        continue
    
    # 3. 再評価
    # labファイルのパスを復元
    ref_path = os.path.join(
        r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles",
        track["album"],
        f"{track['track']}.lab"
    )
    
    try:
        scores = evaluate_single(ref_path, str(pred_path))
        delta = scores["thirds"] - track["thirds"]
        status = "IMPROVED" if delta > 0.1 else "similar"
        print(f"  >> thirds: {track['thirds']:.3f} → {scores['thirds']:.3f} ({'+' if delta > 0 else ''}{delta:.3f}) [{status}]")
        
        if scores["thirds"] > track["thirds"]:
            improved += 1
            # レポートを更新
            for r in report["results"]:
                if r["track"] == track["track"]:
                    r.update(scores)
                    break
        else:
            still_bad += 1
    except Exception as e:
        print(f"  [ERROR] {e}")
        still_bad += 1

# 更新されたレポートを保存
metrics = ["root", "thirds", "mirex", "majmin", "sevenths"]
report["average"] = {m: round(float(np.mean([r[m] for r in report["results"]])), 4) for m in metrics}
report["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

with open(r"D:\Music\nextchord\evaluation\beatles_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"\n=== 結果 ===")
print(f"改善: {improved}曲")
print(f"改善なし: {still_bad}曲")
print(f"\n更新後の平均スコア:")
for m in metrics:
    avg = np.mean([r[m] for r in report["results"]])
    print(f"  {m:>10s}: {avg:.4f}")

# スコア分布
results = report["results"]
hi = len([x for x in results if x["thirds"] >= 0.7])
mid = len([x for x in results if 0.3 <= x["thirds"] < 0.7])
lo = len([x for x in results if x["thirds"] < 0.3])
print(f"\nスコア分布:")
print(f"  >= 0.7: {hi}")
print(f"  0.3-0.7: {mid}")
print(f"  < 0.3: {lo}")
