"""
ChordMini Beatles Fine-Tuning スクリプト
=========================================
SoloTab論文のドメイン適応FT戦略を適用:
- 保守的な学習率 (1e-5)
- 早期停止 (patience=15)
- Beatles Isophonics 180曲 → Train 144 / Val 18 / Test 18

SoloTab実績: GuitarSet FTで F1: 0.5610 → 0.8310 (+48.1%)
"""
import sys
import os
import shutil
import json
import random
import numpy as np
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

ANNO_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO_DIR = Path(r"D:\Music\nextchord\evaluation\beatles_audio")
FT_DATA_DIR = Path(r"D:\Music\nextchord\ChordMini\data\beatles")
FT_AUDIO_DIR = FT_DATA_DIR / "audio"
FT_LABEL_DIR = FT_DATA_DIR / "chordlab"

CHECKPOINT = CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth"
SAVE_DIR = CHORDMINI_ROOT / "checkpoints" / "beatles_ft"


def prepare_data():
    """Beatles データを ChordMini のディレクトリ構造に変換"""
    FT_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    FT_LABEL_DIR.mkdir(parents=True, exist_ok=True)
    
    pairs = []
    for album_dir in sorted(ANNO_DIR.iterdir()):
        if not album_dir.is_dir():
            continue
        for lab_file in sorted(album_dir.glob("*.lab")):
            wav_file = AUDIO_DIR / album_dir.name / f"{lab_file.stem}.wav"
            if wav_file.exists():
                # フラットなファイル名に変換 (album__track)
                flat_name = f"{album_dir.name}__{lab_file.stem}"
                
                # シンボリックリンクまたはコピー
                audio_dst = FT_AUDIO_DIR / f"{flat_name}.wav"
                label_dst = FT_LABEL_DIR / f"{flat_name}.lab"
                
                if not audio_dst.exists():
                    # Windowsではハードリンクを使用（シンボリックリンクは管理者権限必要）
                    try:
                        os.link(str(wav_file), str(audio_dst))
                    except OSError:
                        shutil.copy2(str(wav_file), str(audio_dst))
                
                if not label_dst.exists():
                    shutil.copy2(str(lab_file), str(label_dst))
                
                pairs.append(flat_name)
    
    print(f"Prepared {len(pairs)} audio+label pairs in {FT_DATA_DIR}")
    return pairs


def run_finetune():
    """ChordMini を Beatles でファインチューニング"""
    import subprocess
    
    cmd = [
        str(Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")),
        str(CHORDMINI_ROOT / "src" / "training_scripts" / "train_from_scratch.py"),
        "--audio_dir", str(FT_AUDIO_DIR),
        "--label_dir", str(FT_LABEL_DIR),
        "--config", str(CHORDMINI_ROOT / "config" / "ChordMini.yaml"),
        "--model_type", "BTC",
        "--resume_checkpoint", str(CHECKPOINT),
        "--save_dir", str(SAVE_DIR),
        # SoloTab式: 保守的FT設定
        "--learning_rate", "1e-5",
        "--num_epochs", "50",
        "--early_stopping_patience", "15",
        "--batch_size", "16",
        "--seq_len", "108",
        "--stride", "54",
        "--train_ratio", "0.8",
        "--val_ratio", "0.1",
        "--seed", "42",
        "--no_kd",  # 教師なし（事前学習済み重みから直接FT）
    ]
    
    print("\n" + "=" * 70)
    print("ChordMini Beatles Fine-Tuning")
    print("=" * 70)
    print(f"Checkpoint: {CHECKPOINT}")
    print(f"Save dir: {SAVE_DIR}")
    print(f"LR: 1e-5 (conservative, SoloTab strategy)")
    print(f"Patience: 15")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 70 + "\n")
    
    result = subprocess.run(cmd, cwd=str(CHORDMINI_ROOT))
    return result.returncode


def main():
    print("Step 1: Preparing Beatles data...")
    pairs = prepare_data()
    
    print(f"\nStep 2: Fine-tuning ChordMini on {len(pairs)} Beatles tracks...")
    rc = run_finetune()
    
    if rc == 0:
        print("\n✅ Fine-tuning completed successfully!")
    else:
        print(f"\n❌ Fine-tuning failed with exit code {rc}")


if __name__ == "__main__":
    main()
