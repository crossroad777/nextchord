"""
エラー分析: FTモデル (82.94%) がどこで間違えているか
===================================================
- 曲ごとのスコア分布
- コードタイプ別の精度 (maj, min, 7th, etc.)
- 混同パターン (何を何と間違えているか)
"""
import sys, os, numpy as np, json
from pathlib import Path
from collections import Counter, defaultdict

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
CKPT_FT = str(CHORDMINI_ROOT / "checkpoints" / "beatles_ft" / "best_model.pth")

config = HParams.load(str(CHORDMINI_ROOT / "config" / "ChordMini.yaml"))
device = get_device()

# Try FT model, fallback to original
ckpt = CKPT_FT if os.path.exists(CKPT_FT) else str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
print(f"Model: {ckpt}", flush=True)

args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
model, _, _ = load_model(ckpt, 'BTC', config, device, args)
mn, st = extract_norm_stats(ckpt)
i2c, c2i = extract_vocab(ckpt)
model.eval()

song_scores = []
confusion = Counter()  # (ref_root, pred_root) -> count
chord_type_scores = defaultdict(list)  # chord_type -> [scores]
worst_songs = []

def get_root_type(chord):
    if chord == 'N': return 'N', 'N'
    parts = chord.split(':')
    root = parts[0] if parts else chord
    ctype = parts[1] if len(parts) > 1 else 'maj'
    return root, ctype

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
            
            # Build prediction intervals
            iv = []; lb = []; prev = None; start = 0.0
            for idx_i, idx in enumerate(p):
                ch = i2c.get(int(idx), 'N')
                t = float(idx_i) * fd
                if prev is None: prev = ch; continue
                if ch != prev:
                    iv.append([start, t]); lb.append(prev)
                    start = t; prev = ch
            if prev: iv.append([start, float(len(p)) * fd]); lb.append(prev)
            
            r = mir_eval.chord.evaluate(ri, rl, np.array(iv), lb)
            score = float(r['thirds'])
            
            song_scores.append((f"{ad.name}/{lab_file.stem}", score))
            
            # Per-frame confusion analysis
            for ref_int, ref_lab in zip(ri, rl):
                ref_root, ref_type = get_root_type(ref_lab)
                # Find overlapping predictions
                mid = (ref_int[0] + ref_int[1]) / 2
                pred_chord = 'N'
                for piv, plb in zip(iv, lb):
                    if piv[0] <= mid < piv[1]:
                        pred_chord = plb
                        break
                pred_root, pred_type = get_root_type(pred_chord)
                
                duration = ref_int[1] - ref_int[0]
                if ref_root != pred_root and ref_lab != 'N':
                    confusion[(ref_lab, pred_chord)] += 1
                
                chord_type_scores[ref_type].append(1.0 if ref_root == pred_root else 0.0)
        
        except Exception as e:
            pass

# Report
print(f"\n{'='*70}", flush=True)
print(f"Error Analysis: {len(song_scores)} tracks", flush=True)
print(f"{'='*70}", flush=True)

scores_arr = [s for _, s in song_scores]
print(f"\nOverall Thirds: {np.mean(scores_arr):.4f} ± {np.std(scores_arr):.4f}", flush=True)

# Score distribution
print(f"\nScore Distribution:", flush=True)
for threshold in [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]:
    count = sum(1 for s in scores_arr if s >= threshold)
    print(f"  >= {threshold:.0%}: {count}/{len(scores_arr)} ({count/len(scores_arr):.1%})", flush=True)

# Worst 10 songs
print(f"\n--- Worst 10 Songs ---", flush=True)
for name, score in sorted(song_scores, key=lambda x: x[1])[:10]:
    print(f"  {score:.4f}  {name}", flush=True)

# Best 10 songs
print(f"\n--- Best 10 Songs ---", flush=True)
for name, score in sorted(song_scores, key=lambda x: x[1], reverse=True)[:10]:
    print(f"  {score:.4f}  {name}", flush=True)

# Chord type accuracy
print(f"\n--- Chord Type Accuracy (root match) ---", flush=True)
for ct, accs in sorted(chord_type_scores.items(), key=lambda x: np.mean(x[1])):
    if len(accs) >= 5:
        print(f"  {ct:12s}: {np.mean(accs):.3f} ({len(accs)} segments)", flush=True)

# Top confusions
print(f"\n--- Top 20 Confusions (ref -> pred) ---", flush=True)
for (ref, pred), cnt in confusion.most_common(20):
    print(f"  {ref:12s} -> {pred:12s}: {cnt}", flush=True)

print("\nDone!", flush=True)
