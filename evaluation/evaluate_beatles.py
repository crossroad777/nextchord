"""
NextChord Beatles 評価パイプライン (MIREX基準)
=============================================
Isophonics Beatles アノテーション + YouTube 音源 + BTC 予測
→ mir_eval で MIREX 基準のフレームレベル評価

【評価メトリクス】
- root: ルート音の一致率
- thirds: ルート + maj/min の一致率 ← 主要指標
- mirex: MIREX コンテスト基準
- majmin: Major/Minor 完全一致
- sevenths: 7th含む完全一致

【参考: BTC 論文のスコア】
- thirds: ~0.860 (Isophonics Beatles)
"""

import sys
import os
import json
import glob
import subprocess
import time
import traceback
from pathlib import Path

import numpy as np
import mir_eval

# --- 設定 ---
BASE_DIR = Path(r"D:\Music\nextchord\evaluation")
ANNOTATIONS_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO_DIR = BASE_DIR / "beatles_audio"
PREDICTIONS_DIR = BASE_DIR / "beatles_predictions"

VENV_PYTHON = Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")
YT_DLP = Path(r"D:\Music\nextchord\venv312\Scripts\yt-dlp.exe")
BACKEND_DIR = Path(r"D:\Music\nextchord\fastapi-backend")

AUDIO_DIR.mkdir(exist_ok=True, parents=True)
PREDICTIONS_DIR.mkdir(exist_ok=True, parents=True)


def get_all_tracks():
    """全トラックのリストを取得"""
    tracks = []
    for album_dir in sorted(ANNOTATIONS_DIR.iterdir()):
        if not album_dir.is_dir():
            continue
        album = album_dir.name
        for lab_file in sorted(album_dir.glob("*.lab")):
            track_name = lab_file.stem
            song_title = track_name.replace("_", " ").lstrip("0123456789 -").strip()
            tracks.append({
                "album": album,
                "track_name": track_name,
                "song_title": song_title,
                "lab_path": str(lab_file),
            })
    return tracks


def download_audio(track, max_retries=2):
    """YouTube から Beatles 音源をダウンロード（ffmpeg で PCM WAV に変換）"""
    FFMPEG = Path(r"D:\Music\nextchord\ffmpeg-7.1.1-essentials_build\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe")
    out_dir = AUDIO_DIR / track["album"]
    out_dir.mkdir(exist_ok=True, parents=True)
    out_path = out_dir / f"{track['track_name']}.wav"

    if out_path.exists():
        # 既存ファイルが正しいWAVか確認
        try:
            import soundfile as sf
            sf.SoundFile(str(out_path))
            return out_path
        except Exception:
            print(f"    [FIX] Re-converting corrupt WAV...")
            pass

    query = f"Beatles {track['song_title']}"
    print(f"    [DL] YouTube search: {query}")

    for attempt in range(max_retries):
        try:
            # yt-dlp でベスト音源ダウンロード（変換なし）
            temp_path = out_dir / f"{track['track_name']}_temp"
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

            # ダウンロードされたファイルを探す
            temp_file = None
            for candidate in out_dir.glob(f"{track['track_name']}_temp.*"):
                temp_file = candidate
                break

            if not temp_file:
                # 拡張子なしのリネーム版を探す
                for candidate in out_dir.glob(f"{track['track_name']}.*"):
                    if candidate.suffix != '.wav':
                        temp_file = candidate
                        break

            if not temp_file:
                print(f"    [WARN] No file downloaded on attempt {attempt+1}")
                continue

            # ffmpeg で PCM WAV に変換
            ffmpeg_cmd = [
                str(FFMPEG),
                "-y", "-i", str(temp_file),
                "-ar", "22050", "-ac", "1", "-f", "wav",
                str(out_path),
            ]
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=60)
            
            # temp ファイル削除
            if temp_file.exists():
                temp_file.unlink()

            if out_path.exists():
                print(f"    [OK] Downloaded and converted: {out_path.name}")
                return out_path

        except subprocess.TimeoutExpired:
            print(f"    [WARN] Attempt {attempt+1} timed out")
        except Exception as e:
            print(f"    [WARN] Attempt {attempt+1} failed: {e}")

    print(f"    [ERROR] Download failed after {max_retries} attempts")
    return None


def predict_chords_btc(audio_path, track):
    """BTC でコード予測し、.lab 形式で保存"""
    pred_dir = PREDICTIONS_DIR / track["album"]
    pred_dir.mkdir(exist_ok=True, parents=True)
    pred_path = pred_dir / f"{track['track_name']}.lab"

    if pred_path.exists():
        return pred_path

    print(f"    [BTC] Predicting...")

    script = f'''
import sys, json
import librosa
sys.path.insert(0, r"{BACKEND_DIR}")
from btc_engine import BTCEngine

engine = BTCEngine(use_large_voca=True)
seg_starts, seg_labels = engine.detect_chords(r"{audio_path}")

# 曲の長さを取得
y, sr = librosa.load(r"{audio_path}", sr=22050)
duration = librosa.get_duration(y=y, sr=sr)

# .lab 形式で出力 (start end chord)
lines = []
for i in range(len(seg_starts)):
    start = seg_starts[i]
    end = seg_starts[i+1] if i+1 < len(seg_starts) else duration
    lines.append(f"{{start:.6f}} {{end:.6f}} {{seg_labels[i]}}")
print("\\n".join(lines))
'''

    try:
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", script],
            capture_output=True, text=True, timeout=180,
            cwd=str(BACKEND_DIR),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )

        # .lab ファイルとして保存（stderrに警告が出てもstdoutに結果があればOK）
        lines = [l for l in result.stdout.strip().split("\n") if l and l[0].isdigit()]
        
        if not lines:
            # stdout が空の場合のみエラー
            err_msg = result.stderr[:300] if result.stderr else "no output"
            print(f"    [ERROR] BTC failed: {err_msg}")
            return None

        with open(pred_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        print(f"    [OK] {len(lines)} chord segments")
        return pred_path

    except subprocess.TimeoutExpired:
        print(f"    [ERROR] BTC timed out")
        return None
    except Exception as e:
        print(f"    [ERROR] {e}")
        return None


def evaluate_track(ref_path, est_path):
    """1曲分の mir_eval 評価"""
    try:
        ref_intervals, ref_labels = mir_eval.io.load_labeled_intervals(ref_path)
        est_intervals, est_labels = mir_eval.io.load_labeled_intervals(est_path)

        # mir_eval でコード評価
        scores = mir_eval.chord.evaluate(ref_intervals, ref_labels, est_intervals, est_labels)

        return {
            "root": float(scores["root"]),
            "thirds": float(scores["thirds"]),
            "mirex": float(scores["mirex"]),
            "majmin": float(scores["majmin"]),
            "sevenths": float(scores["sevenths"]),
        }
    except Exception as e:
        print(f"    [ERROR] Evaluation failed: {e}")
        return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 70)
    print("NextChord Beatles Evaluation Pipeline (MIREX Standard)")
    print("=" * 70)

    tracks = get_all_tracks()
    print(f"\nTotal tracks with annotations: {len(tracks)}")

    # 処理するトラック数（全180曲はYouTubeDLに時間がかかるので、まず最初のアルバムでテスト）
    max_tracks = int(sys.argv[1]) if len(sys.argv) > 1 else 14  # デフォルト: 1アルバム分
    tracks = tracks[:max_tracks]
    print(f"Processing: {max_tracks} tracks")

    results = []
    errors = []
    start_time = time.time()

    for i, track in enumerate(tracks):
        print(f"\n[{i+1}/{len(tracks)}] {track['song_title']} ({track['album']})")

        # Step 1: ダウンロード
        audio_path = download_audio(track)
        if not audio_path:
            errors.append({"track": track["track_name"], "error": "download_failed"})
            continue

        # Step 2: BTC 予測
        pred_path = predict_chords_btc(audio_path, track)
        if not pred_path:
            errors.append({"track": track["track_name"], "error": "btc_failed"})
            continue

        # Step 3: 評価
        scores = evaluate_track(track["lab_path"], str(pred_path))
        if not scores:
            errors.append({"track": track["track_name"], "error": "eval_failed"})
            continue

        results.append({
            "track": track["track_name"],
            "title": track["song_title"],
            "album": track["album"],
            **scores,
        })
        print(f"    >> root={scores['root']:.3f}  thirds={scores['thirds']:.3f}  mirex={scores['mirex']:.3f}")

    elapsed = time.time() - start_time

    # --- レポート ---
    print("\n" + "=" * 70)
    print("EVALUATION REPORT")
    print("=" * 70)

    if results:
        metrics = ["root", "thirds", "mirex", "majmin", "sevenths"]
        print(f"\nTracks evaluated: {len(results)} / {len(tracks)}")
        print(f"Errors: {len(errors)}")
        print(f"Time: {elapsed:.0f}s")

        print(f"\n--- Average Scores ---")
        for m in metrics:
            avg = np.mean([r[m] for r in results])
            std = np.std([r[m] for r in results])
            print(f"  {m:>10s}: {avg:.4f} (+/- {std:.4f})")

        print(f"\n--- BTC Paper Reference (Isophonics Beatles) ---")
        print(f"  {'thirds':>10s}: ~0.860")
        print(f"  {'root':>10s}: ~0.900")

        print(f"\n--- Per-Track Scores (sorted by thirds) ---")
        print(f"{'Track':<40s} {'root':>6s} {'thirds':>7s} {'mirex':>7s}")
        print("-" * 62)
        for r in sorted(results, key=lambda x: x["thirds"], reverse=True):
            print(f"{r['title'][:38]:<40s} {r['root']:6.3f} {r['thirds']:7.3f} {r['mirex']:7.3f}")

    # JSON保存
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tracks": len(tracks),
        "evaluated": len(results),
        "errors": len(errors),
        "elapsed_seconds": round(elapsed),
        "average": {m: round(float(np.mean([r[m] for r in results])), 4) for m in metrics} if results else {},
        "btc_paper_reference": {"thirds": 0.860, "root": 0.900},
        "results": results,
        "errors_detail": errors,
    }
    report_path = BASE_DIR / "beatles_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
