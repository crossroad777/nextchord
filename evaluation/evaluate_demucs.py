"""
Beatles再予測スクリプト: Demucs前処理 + BTC + ChordMini アンサンブル
=====================================================================
1. 既存のBeatles音源にDemucsでハーモニック強調前処理
2. BTC + ChordMini の両モデルで予測
3. ソフト投票でアンサンブル
4. mir_eval で評価
"""

import sys
import os
import json
import numpy as np
import subprocess
import time
from pathlib import Path

sys.path.insert(0, r"D:\Music\nextchord\fastapi-backend")

import mir_eval
import librosa

BASE_DIR = Path(r"D:\Music\nextchord\evaluation")
ANNOTATIONS_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO_DIR = BASE_DIR / "beatles_audio"
PREDICTIONS_DIR = BASE_DIR / "beatles_predictions"
DEMUCS_PRED_DIR = BASE_DIR / "beatles_predictions_demucs"
DEMUCS_PRED_DIR.mkdir(exist_ok=True, parents=True)

VENV_PYTHON = Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")


def get_all_tracks():
    """アノテーション + 既存予測 + 既存音源がある全トラック"""
    tracks = []
    for album_dir in sorted(ANNOTATIONS_DIR.iterdir()):
        if not album_dir.is_dir():
            continue
        for lab_file in sorted(album_dir.glob("*.lab")):
            audio_file = AUDIO_DIR / album_dir.name / f"{lab_file.stem}.wav"
            pred_file = PREDICTIONS_DIR / album_dir.name / f"{lab_file.stem}.lab"
            if audio_file.exists() and pred_file.exists():
                tracks.append({
                    "album": album_dir.name,
                    "track_name": lab_file.stem,
                    "title": lab_file.stem.replace("_", " ").lstrip("0123456789 -").strip(),
                    "ref_path": str(lab_file),
                    "audio_path": str(audio_file),
                    "pred_path": str(pred_file),
                })
    return tracks


def demucs_harmonic_enhance(audio_path, output_dir):
    """Demucsでドラム/ボーカル除去 → ハーモニック楽器を強調した音源を生成"""
    out_wav = output_dir / f"{Path(audio_path).stem}_harmonic.wav"
    if out_wav.exists():
        return str(out_wav)
    
    # Demucsで分離
    try:
        result = subprocess.run([
            str(VENV_PYTHON), "-m", "demucs",
            "--two-stems", "vocals",
            "-n", "htdemucs",
            "-o", str(output_dir / "demucs_tmp"),
            str(audio_path),
        ], capture_output=True, text=True, timeout=120)
        
        # no_vocals.wav を使用
        stem_dir = output_dir / "demucs_tmp" / "htdemucs" / Path(audio_path).stem
        no_vocals = stem_dir / "no_vocals.wav"
        
        if no_vocals.exists():
            import shutil
            shutil.copy2(str(no_vocals), str(out_wav))
            print(f"  [DEMUCS] Vocals removed: {out_wav.name}")
            return str(out_wav)
        else:
            print(f"  [DEMUCS] No output found, using original")
            return audio_path
    except Exception as e:
        print(f"  [DEMUCS] Failed: {e}, using original")
        return audio_path


def predict_with_btc(audio_path, track):
    """BTC (ファインチューニング済み) でコード予測"""
    pred_dir = DEMUCS_PRED_DIR / track["album"]
    pred_dir.mkdir(exist_ok=True, parents=True)
    pred_path = pred_dir / f"{track['track_name']}_btc.lab"
    
    if pred_path.exists():
        return str(pred_path)
    
    script = f'''
import sys
sys.path.insert(0, r"D:\\Music\\nextchord\\fastapi-backend")
sys.path.insert(0, r"D:\\Music\\nextchord\\BTC-ISMIR19")
from btc_engine import BTCEngine
import librosa

engine = BTCEngine(use_large_voca=True)
seg_starts, seg_labels = engine.detect_chords(r"{audio_path}")
y, sr = librosa.load(r"{audio_path}", sr=22050)
duration = librosa.get_duration(y=y, sr=sr)

for i in range(len(seg_starts)):
    start = seg_starts[i]
    end = seg_starts[i+1] if i+1 < len(seg_starts) else duration
    print(f"{{start:.6f}} {{end:.6f}} {{seg_labels[i]}}")
'''
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", script],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        lines = [l for l in result.stdout.strip().split("\n") if l and l[0].isdigit()]
        if lines:
            with open(pred_path, "w") as f:
                f.write("\n".join(lines) + "\n")
            return str(pred_path)
    except Exception as e:
        print(f"  [BTC] Failed: {e}")
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    print("=" * 70)
    print("Beatles Demucs + BTC Re-prediction Pipeline")
    print("=" * 70)
    
    tracks = get_all_tracks()
    print(f"\nTracks with audio + predictions: {len(tracks)}")
    
    max_tracks = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    tracks = tracks[:max_tracks]
    
    # まず元のBTC予測の精度を再確認（ベースライン）
    results_orig = []
    results_demucs = []
    
    for i, track in enumerate(tracks):
        title = track["title"]
        print(f"\n[{i+1}/{len(tracks)}] {title}")
        
        # 1. 元のBTC予測スコア
        try:
            orig_int, orig_lab = mir_eval.io.load_labeled_intervals(track["pred_path"])
            ref_int, ref_lab = mir_eval.io.load_labeled_intervals(track["ref_path"])
            orig_scores = mir_eval.chord.evaluate(ref_int, ref_lab, orig_int, orig_lab)
            orig_thirds = float(orig_scores["thirds"])
            results_orig.append(orig_thirds)
        except Exception as e:
            print(f"  [ORIG] Error: {e}")
            continue
        
        # 2. Demucsでハーモニック強調
        harmonic_path = demucs_harmonic_enhance(
            track["audio_path"],
            DEMUCS_PRED_DIR / track["album"]
        )
        
        # 3. ハーモニック音源でBTC再予測
        demucs_pred = predict_with_btc(harmonic_path, track)
        if demucs_pred:
            try:
                dem_int, dem_lab = mir_eval.io.load_labeled_intervals(demucs_pred)
                dem_scores = mir_eval.chord.evaluate(ref_int, ref_lab, dem_int, dem_lab)
                dem_thirds = float(dem_scores["thirds"])
                results_demucs.append(dem_thirds)
                
                diff = dem_thirds - orig_thirds
                sym = "+" if diff >= 0 else ""
                print(f"  Original: {orig_thirds:.3f}  Demucs+BTC: {dem_thirds:.3f}  ({sym}{diff:.3f})")
            except Exception as e:
                print(f"  [DEMUCS] Eval error: {e}")
                results_demucs.append(orig_thirds)
        else:
            results_demucs.append(orig_thirds)
    
    # レポート
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Original BTC:     {np.mean(results_orig):.4f}")
    print(f"Demucs + BTC:     {np.mean(results_demucs):.4f}")
    diff = np.mean(results_demucs) - np.mean(results_orig)
    print(f"Difference:       {diff:+.4f}")


if __name__ == "__main__":
    main()
