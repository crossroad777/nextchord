"""
Step 2: 合成データ事前学習 → Beatles FT パイプライン
===================================================
SoloTab完全再現:
1. 合成2000曲で事前学習（100%正解ラベル、「コードの形」を学習）
2. Beatles 180曲でFT（実音源への適応）
3. 180曲ベンチマーク評価
"""
import sys
import subprocess
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
VENV_PYTHON = str(Path(r"D:\Music\nextchord\venv312\Scripts\python.exe"))
TRAIN_SCRIPT = str(CHORDMINI_ROOT / "src" / "training_scripts" / "train_from_scratch.py")
CONFIG = str(CHORDMINI_ROOT / "config" / "ChordMini.yaml")

# Data paths
SYNTH_AUDIO = str(CHORDMINI_ROOT / "data" / "synthetic" / "audio")
SYNTH_LABEL = str(CHORDMINI_ROOT / "data" / "synthetic" / "chordlab")
BEATLES_AUDIO = str(CHORDMINI_ROOT / "data" / "beatles" / "audio")
BEATLES_LABEL = str(CHORDMINI_ROOT / "data" / "beatles" / "chordlab")

# Checkpoints
ORIGINAL_CKPT = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
SYNTH_SAVE = str(CHORDMINI_ROOT / "checkpoints" / "synth_pretrain")
SYNTH_FT_SAVE = str(CHORDMINI_ROOT / "checkpoints" / "synth_then_beatles")


def step1_synth_pretrain():
    """Step 1: 合成データで事前学習"""
    print("=" * 70)
    print("Step 1: Synthetic Pre-Training (2000 songs, perfect labels)")
    print("=" * 70)
    
    cmd = [
        VENV_PYTHON, TRAIN_SCRIPT,
        "--audio_dir", SYNTH_AUDIO,
        "--label_dir", SYNTH_LABEL,
        "--config", CONFIG,
        "--model_type", "BTC",
        "--resume_checkpoint", ORIGINAL_CKPT,  # ChordMiniから開始
        "--save_dir", SYNTH_SAVE,
        "--learning_rate", "5e-5",   # 合成データは量が多いのでやや高め
        "--num_epochs", "30",
        "--early_stopping_patience", "10",
        "--batch_size", "32",
        "--seq_len", "108",
        "--stride", "54",
        "--train_ratio", "0.9",
        "--val_ratio", "0.05",
        "--seed", "42",
        "--no_kd",
    ]
    
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(CHORDMINI_ROOT))
    
    if result.returncode != 0:
        print(f"Step 1 FAILED (exit {result.returncode})")
        return False
    
    print("Step 1 DONE")
    return True


def step2_beatles_ft():
    """Step 2: Beatles FT"""
    print("\n" + "=" * 70)
    print("Step 2: Beatles Fine-Tuning (180 songs, domain adaptation)")
    print("=" * 70)
    
    # Use the best synth-pretrained checkpoint
    synth_best = str(Path(SYNTH_SAVE) / "single_split" / "best_model.pth")
    
    cmd = [
        VENV_PYTHON, TRAIN_SCRIPT,
        "--audio_dir", BEATLES_AUDIO,
        "--label_dir", BEATLES_LABEL,
        "--config", CONFIG,
        "--model_type", "BTC",
        "--resume_checkpoint", synth_best,
        "--save_dir", SYNTH_FT_SAVE,
        "--learning_rate", "1e-5",   # 保守的LR
        "--num_epochs", "50",
        "--early_stopping_patience", "15",
        "--batch_size", "16",
        "--seq_len", "108",
        "--stride", "54",
        "--train_ratio", "0.8",
        "--val_ratio", "0.1",
        "--seed", "42",
        "--no_kd",
    ]
    
    print(f"Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(CHORDMINI_ROOT))
    
    if result.returncode != 0:
        print(f"Step 2 FAILED (exit {result.returncode})")
        return False
    
    print("Step 2 DONE")
    return True


def step3_evaluate():
    """Step 3: 180曲ベンチマーク"""
    print("\n" + "=" * 70)
    print("Step 3: Beatles 180-track Evaluation")
    print("=" * 70)
    
    import numpy as np
    import mir_eval
    
    sys.path.insert(0, str(CHORDMINI_ROOT))
    sys.path.insert(0, str(CHORDMINI_ROOT / "src"))
    
    from src.utils.hparams import HParams
    from src.models import load_model
    from src.evaluation.utils.common import (
        extract_norm_stats, extract_vocab, extract_song_features)
    from src.evaluation.utils.inference import predict_sliding_windows
    from src.utils.device import get_device
    
    ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
    AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")
    
    # Load model
    ckpt = str(Path(SYNTH_FT_SAVE) / "single_split" / "best_model.pth")
    config = HParams.load(CONFIG)
    device = get_device()
    args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
    model, _, _ = load_model(ckpt, 'BTC', config, device, args)
    mean, std = extract_norm_stats(ckpt)
    i2c, c2i = extract_vocab(ckpt)
    model.eval()
    
    scores = []
    for ad in sorted(ANNO.iterdir()):
        if not ad.is_dir(): continue
        for lab in sorted(ad.glob("*.lab")):
            wav = AUDIO / ad.name / f"{lab.stem}.wav"
            if not wav.exists(): continue
            try:
                ri, rl = mir_eval.io.load_labeled_intervals(str(lab))
                fm, fd = extract_song_features(str(wav), config)
                p = predict_sliding_windows(
                    model=model, feature_matrix=fm, mean=mean, std=std,
                    seq_len=108, batch_size=16, model_type='BTC',
                    n_classes=len(c2i), use_overlap=True, overlap_ratio=0.5)
                iv = []; lb = []; prev = None; start = 0.0
                for idx_i, idx in enumerate(p):
                    ch = i2c.get(int(idx), 'N'); t = float(idx_i) * fd
                    if prev is None: prev = ch; continue
                    if ch != prev: iv.append([start, t]); lb.append(prev); start = t; prev = ch
                if prev: iv.append([start, float(len(p)) * fd]); lb.append(prev)
                r = mir_eval.chord.evaluate(ri, rl, np.array(iv), lb)
                scores.append(float(r['thirds']))
            except: pass
    
    result = np.mean(scores)
    print(f"\nSynth+Beatles FT (180 tracks): {result:.4f}")
    print(f"Previous best (FT only):       0.8294")
    print(f"Diff:                          {result - 0.8294:+.4f}")
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    if step1_synth_pretrain():
        if step2_beatles_ft():
            step3_evaluate()


if __name__ == "__main__":
    main()
