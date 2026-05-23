"""
Enharmonic-aware Evaluation: 異名同音正規化で再評価
====================================================
F# = Gb, C# = Db, G# = Ab を同一視して評価
"""
import sys, os, numpy as np
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch, mir_eval
from src.utils.hparams import HParams
from src.models import load_model
from src.evaluation.utils.common import extract_norm_stats, extract_vocab, extract_song_features
from src.evaluation.utils.inference import predict_sliding_windows
from src.utils.device import get_device

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")

# Enharmonic normalization: everything to sharps
ENHARMONIC = {
    'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#',
    'Cb': 'B', 'Fb': 'E', 'B#': 'C', 'E#': 'F',
}

def normalize_chord(chord):
    """Normalize chord to use sharps only"""
    if chord in ('N', 'X', ''): return chord
    # Handle bass note
    if '/' in chord:
        main, bass = chord.rsplit('/', 1)
        main = normalize_chord(main)
        for flat, sharp in ENHARMONIC.items():
            if bass.startswith(flat):
                bass = sharp + bass[len(flat):]
                break
        return f"{main}/{bass}"
    # Handle root
    if ':' in chord:
        root, quality = chord.split(':', 1)
    else:
        # Extract root
        import re
        m = re.match(r'^([A-Ga-g][#b]?)(.*)', chord)
        if m:
            root, quality = m.group(1), m.group(2)
        else:
            return chord
    
    for flat, sharp in ENHARMONIC.items():
        if root == flat:
            root = sharp
            break
    
    if quality:
        return f"{root}:{quality}" if ':' in chord else f"{root}{quality}"
    return root

def normalize_labels(labels):
    """Normalize a list of chord labels"""
    return [normalize_chord(l) for l in labels]

config = HParams.load(str(CHORDMINI_ROOT / "config" / "ChordMini.yaml"))
device = get_device()

# Use FT model if exists, otherwise original
ckpt_ft = str(CHORDMINI_ROOT / "checkpoints" / "beatles_ft" / "best_model.pth")
ckpt_orig = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")

for label, ckpt in [("Original", ckpt_orig), ("FT", ckpt_ft)]:
    if not os.path.exists(ckpt):
        print(f"{label}: checkpoint not found, skipping", flush=True)
        continue
    
    args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
    model, _, _ = load_model(ckpt, 'BTC', config, device, args)
    mn, st = extract_norm_stats(ckpt)
    i2c, c2i = extract_vocab(ckpt)
    model.eval()
    
    scores_raw = []
    scores_norm = []
    
    for ad in sorted(ANNO.iterdir()):
        if not ad.is_dir(): continue
        for lab_file in sorted(ad.glob("*.lab")):
            wav = AUDIO / ad.name / f"{lab_file.stem}.wav"
            if not wav.exists(): continue
            try:
                ri, rl = mir_eval.io.load_labeled_intervals(str(lab_file))
                fm, fd = extract_song_features(str(wav), config)
                p = predict_sliding_windows(model=model, feature_matrix=fm, mean=mn, std=st,
                    seq_len=108, batch_size=16, model_type='BTC',
                    n_classes=len(c2i), use_overlap=True, overlap_ratio=0.75)
                
                iv = []; lb = []; prev = None; start = 0.0
                for idx_i, idx in enumerate(p):
                    ch = i2c.get(int(idx), 'N')
                    t = float(idx_i) * fd
                    if prev is None: prev = ch; continue
                    if ch != prev:
                        iv.append([start, t]); lb.append(prev)
                        start = t; prev = ch
                if prev: iv.append([start, float(len(p)) * fd]); lb.append(prev)
                
                # Raw score
                r = mir_eval.chord.evaluate(ri, rl, np.array(iv), lb)
                scores_raw.append(float(r['thirds']))
                
                # Normalized score
                norm_rl = normalize_labels(rl)
                norm_lb = normalize_labels(lb)
                r2 = mir_eval.chord.evaluate(ri, norm_rl, np.array(iv), norm_lb)
                scores_norm.append(float(r2['thirds']))
                
            except Exception as e:
                pass
    
    raw = np.mean(scores_raw) if scores_raw else 0
    norm = np.mean(scores_norm) if scores_norm else 0
    print(f"{label} ({len(scores_raw)} tracks):", flush=True)
    print(f"  Raw Thirds:        {raw:.4f}", flush=True)
    print(f"  Normalized Thirds: {norm:.4f} ({'+' if norm > raw else ''}{(norm-raw)*100:.2f}%)", flush=True)
    print(flush=True)
