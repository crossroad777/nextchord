"""
混合学習: 合成3,080曲 + Beatles 180曲 を同一データセットで同時学習
====================================================================
SoloTab論文の教訓: 逐次ではなく混合で負の転移を防ぐ
"""
import sys, os, shutil
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
MIX_DIR = CHORDMINI_ROOT / "data" / "mixed"
MIX_AUDIO = MIX_DIR / "audio"
MIX_LABEL = MIX_DIR / "chordlab"

SYNTH_AUDIO = CHORDMINI_ROOT / "data" / "synthetic" / "audio"
SYNTH_LABEL = CHORDMINI_ROOT / "data" / "synthetic" / "chordlab"
BEATLES_AUDIO = CHORDMINI_ROOT / "data" / "beatles" / "audio"
BEATLES_LABEL = CHORDMINI_ROOT / "data" / "beatles" / "chordlab"

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    MIX_AUDIO.mkdir(parents=True, exist_ok=True)
    MIX_LABEL.mkdir(parents=True, exist_ok=True)
    
    count = 0
    
    # Synthetic data (hardlink or copy)
    print("Linking synthetic data...")
    for wav in sorted(SYNTH_AUDIO.glob("*.wav")):
        lab = SYNTH_LABEL / f"{wav.stem}.lab"
        if not lab.exists(): continue
        dst_wav = MIX_AUDIO / f"synth_{wav.name}"
        dst_lab = MIX_LABEL / f"synth_{wav.stem}.lab"
        if not dst_wav.exists():
            try: os.link(str(wav), str(dst_wav))
            except: shutil.copy2(str(wav), str(dst_wav))
        if not dst_lab.exists():
            shutil.copy2(str(lab), str(dst_lab))
        count += 1
    print(f"  Synthetic: {count}")
    
    # Beatles data (hardlink or copy)
    beatles_count = 0
    print("Linking Beatles data...")
    for wav in sorted(BEATLES_AUDIO.glob("*.wav")):
        lab = BEATLES_LABEL / f"{wav.stem}.lab"
        if not lab.exists(): continue
        dst_wav = MIX_AUDIO / f"real_{wav.name}"
        dst_lab = MIX_LABEL / f"real_{wav.stem}.lab"
        if not dst_wav.exists():
            try: os.link(str(wav), str(dst_wav))
            except: shutil.copy2(str(wav), str(dst_wav))
        if not dst_lab.exists():
            shutil.copy2(str(lab), str(dst_lab))
        beatles_count += 1
    print(f"  Beatles: {beatles_count}")
    
    total_wav = len(list(MIX_AUDIO.glob("*.wav")))
    total_lab = len(list(MIX_LABEL.glob("*.lab")))
    print(f"\nTotal mixed: {total_wav} wav, {total_lab} lab")
    
    # Now train
    import subprocess
    VENV = str(Path(r"D:\Music\nextchord\venv312\Scripts\python.exe"))
    TRAIN = str(CHORDMINI_ROOT / "src" / "training_scripts" / "train_from_scratch.py")
    CONFIG = str(CHORDMINI_ROOT / "config" / "ChordMini.yaml")
    CKPT = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
    SAVE = str(CHORDMINI_ROOT / "checkpoints" / "mixed_train")
    
    cmd = [
        VENV, TRAIN,
        "--audio_dir", str(MIX_AUDIO),
        "--label_dir", str(MIX_LABEL),
        "--config", CONFIG,
        "--model_type", "BTC",
        "--resume_checkpoint", CKPT,
        "--save_dir", SAVE,
        "--learning_rate", "1e-5",   # 保守的 (混合なので実データのドメインを壊さない)
        "--num_epochs", "50",
        "--early_stopping_patience", "15",
        "--batch_size", "16",
        "--seq_len", "108",
        "--stride", "54",
        "--train_ratio", "0.85",
        "--val_ratio", "0.075",
        "--seed", "42",
        "--no_kd",
    ]
    
    print("\n" + "=" * 70)
    print("Mixed Training: Synthetic + Beatles")
    print(f"  Data: {total_wav} songs (synth {count} + real {beatles_count})")
    print(f"  LR: 1e-5 (conservative)")
    print("=" * 70)
    
    result = subprocess.run(cmd, cwd=str(CHORDMINI_ROOT))
    print(f"\nExit code: {result.returncode}")

if __name__ == "__main__":
    main()
