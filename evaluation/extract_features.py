"""
Step 1: CQT特徴量の事前抽出
=============================
Beatles 180曲 + Synth 3080曲のCQTを事前計算してnpy保存
→ 学習時はI/Oのみで高速化
"""
import sys, os, numpy as np, librosa, json
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))
from src.utils.audio_io import suppress_stderr
from src.utils.hparams import HParams

CONFIG = HParams.load(str(CHORDMINI_ROOT / "config" / "ChordMini.yaml"))

def get_config_val(cfg, *keys, default=None):
    from src.utils.config_utils import get_config_value
    return get_config_value(cfg, *keys, default)

SR = get_config_val(CONFIG, 'mp3', 'song_hz', default=22050)
HOP = get_config_val(CONFIG, 'feature', 'hop_length', default=2048)
N_BINS = get_config_val(CONFIG, 'feature', 'n_bins', default=144)
BPO = get_config_val(CONFIG, 'feature', 'bins_per_octave', default=24)

def extract_cqt(audio_path):
    with suppress_stderr():
        y, sr = librosa.load(audio_path, sr=SR)
    cqt = librosa.cqt(y, sr=sr, n_bins=N_BINS, bins_per_octave=BPO,
                       hop_length=HOP, fmin=librosa.note_to_hz('C1'))
    return np.log(np.abs(cqt) + 1e-6).T.astype(np.float32)

def extract_all(audio_dir, label_dir, out_dir, tag):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    audio_files = sorted([f for f in os.listdir(audio_dir)
                          if f.endswith(('.mp3', '.wav', '.flac'))])
    
    processed = 0
    for af in audio_files:
        stem = os.path.splitext(af)[0]
        lab = os.path.join(label_dir, f"{stem}.lab")
        if not os.path.exists(lab):
            continue
        
        npy_path = out_dir / f"{stem}.npy"
        if npy_path.exists():
            processed += 1
            continue
        
        try:
            feat = extract_cqt(os.path.join(audio_dir, af))
            np.save(str(npy_path), feat)
            processed += 1
            if processed % 100 == 0:
                print(f"  [{tag}] {processed}: {stem} ({feat.shape})")
        except Exception as e:
            print(f"  ERROR: {stem}: {e}")
    
    print(f"  [{tag}] Done: {processed} files")
    return processed

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    print("=" * 70)
    print("CQT Feature Pre-extraction")
    print("=" * 70)
    
    # Beatles
    print("\nBeatles (180 tracks)...")
    b = extract_all(
        str(CHORDMINI_ROOT / "data" / "beatles" / "audio"),
        str(CHORDMINI_ROOT / "data" / "beatles" / "chordlab"),
        str(CHORDMINI_ROOT / "data" / "beatles" / "features"),
        "Beatles")
    
    # Synthetic
    print("\nSynthetic (3080 tracks)...")
    s = extract_all(
        str(CHORDMINI_ROOT / "data" / "synthetic" / "audio"),
        str(CHORDMINI_ROOT / "data" / "synthetic" / "chordlab"),
        str(CHORDMINI_ROOT / "data" / "synthetic" / "features"),
        "Synth")
    
    print(f"\nTotal: {b + s} feature files extracted")

if __name__ == "__main__":
    main()
