"""
後処理最適化: median filter + min_segment_duration + key-aware correction
=========================================================================
学習不要の精度改善テクニック
"""
import sys, numpy as np, json
from pathlib import Path
from collections import Counter

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT)); sys.path.insert(0, str(CHORDMINI_ROOT/"src"))
import torch, mir_eval
from scipy.ndimage import median_filter

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")

def get_tracks(n=180):
    t = []
    for ad in sorted(ANNO.iterdir()):
        if not ad.is_dir(): continue
        for lab in sorted(ad.glob("*.lab")):
            wav = AUDIO / ad.name / f"{lab.stem}.wav"
            if wav.exists(): t.append({"ref": str(lab), "audio": str(wav), "title": lab.stem})
    return t[:n]

def load_b(ckpt, mt='BTC'):
    from src.utils.hparams import HParams; from src.models import load_model
    from src.evaluation.utils.common import extract_norm_stats, extract_vocab
    from src.utils.device import get_device
    c = HParams.load(str(CHORDMINI_ROOT/'config'/'ChordMini.yaml'))
    d = get_device(); a = type('A',(),{'seq_len':None,'model_type':mt})()
    m,_,_ = load_model(str(ckpt),mt,c,d,a)
    mn,st = extract_norm_stats(str(ckpt)); i2c,c2i = extract_vocab(str(ckpt))
    m.eval()
    return {'model':m,'config':c,'mean':mn,'std':st,'idx_to_chord':i2c,'chord_to_idx':c2i,'device':d}

def get_raw_preds(bundle, audio_path):
    """フレームレベルのインデックス予測を返す"""
    from src.evaluation.utils.common import extract_song_features
    from src.evaluation.utils.inference import predict_sliding_windows
    fm, fd = extract_song_features(audio_path, bundle['config'])
    p = predict_sliding_windows(model=bundle['model'], feature_matrix=fm,
        mean=bundle['mean'], std=bundle['std'], seq_len=108, batch_size=16,
        model_type='BTC', n_classes=len(bundle['chord_to_idx']),
        use_overlap=True, overlap_ratio=0.5)
    return np.array(p), fd

def preds_to_intervals(preds, fd, idx_to_chord):
    iv = []; lb = []; prev = None; start = 0.0
    for i, idx in enumerate(preds):
        ch = idx_to_chord.get(int(idx), 'N'); t = float(i) * fd
        if prev is None: prev = ch; continue
        if ch != prev: iv.append([start, t]); lb.append(prev); start = t; prev = ch
    if prev: iv.append([start, float(len(preds)) * fd]); lb.append(prev)
    return np.array(iv), lb

def apply_median_filter(preds, kernel_size):
    """Median filterで短いスパイクを除去"""
    return median_filter(preds.astype(np.float64), size=kernel_size).astype(int)

def apply_min_segment(intervals, labels, min_dur=0.3):
    """短すぎるセグメントを前後のセグメントにマージ"""
    if len(labels) <= 1:
        return intervals, labels
    
    new_iv = [intervals[0].tolist()]
    new_lb = [labels[0]]
    
    for i in range(1, len(labels)):
        dur = intervals[i][1] - intervals[i][0]
        if dur < min_dur and i < len(labels) - 1:
            # 短すぎる → 次のセグメントの開始を繰り上げ
            continue
        else:
            new_iv[-1][1] = intervals[i][0]  # 前のend = 現在のstart
            new_iv.append(intervals[i].tolist())
            new_lb.append(labels[i])
    
    return np.array(new_iv), new_lb

def evaluate_config(bundle, tracks, median_ks=None, min_seg=None, label=""):
    scores = []
    for i, t in enumerate(tracks):
        try:
            ri, rl = mir_eval.io.load_labeled_intervals(t['ref'])
            preds, fd = get_raw_preds(bundle, t['audio'])
            
            # Apply median filter
            if median_ks and median_ks > 1:
                preds = apply_median_filter(preds, median_ks)
            
            pi, pl = preds_to_intervals(preds, fd, bundle['idx_to_chord'])
            
            # Apply min segment duration
            if min_seg and min_seg > 0:
                pi, pl = apply_min_segment(pi, pl, min_seg)
            
            r = mir_eval.chord.evaluate(ri, rl, pi, pl)
            scores.append(float(r['thirds']))
        except Exception as e:
            pass
        if (i+1) % 30 == 0:
            print(f"  [{label}] {i+1}/{len(tracks)}: {np.mean(scores):.4f}")
    return np.mean(scores) if scores else 0

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tracks = get_tracks(180)
    
    print("=" * 70)
    print("Post-Processing Optimization")
    print("=" * 70)
    
    ft = load_b(CHORDMINI_ROOT / "checkpoints" / "beatles_ft" / "single_split" / "best_model.pth")
    print("FT model loaded.\n")
    
    configs = [
        ("baseline (overlap only)",   None,  None),
        ("median_3",                  3,     None),
        ("median_5",                  5,     None),
        ("median_7",                  7,     None),
        ("median_9",                  9,     None),
        ("median_11",                 11,    None),
        ("median_15",                 15,    None),
        ("median_21",                 21,    None),
        ("min_seg_0.2",               None,  0.2),
        ("min_seg_0.3",               None,  0.3),
        ("min_seg_0.5",               None,  0.5),
        ("median_5+min_0.3",          5,     0.3),
        ("median_7+min_0.3",          7,     0.3),
        ("median_9+min_0.3",          9,     0.3),
        ("median_11+min_0.3",         11,    0.3),
        ("median_5+min_0.5",          5,     0.5),
        ("median_7+min_0.5",          7,     0.5),
    ]
    
    results = {}
    best_score, best_name = 0, ""
    
    for name, mks, mseg in configs:
        print(f"\n--- {name} ---")
        score = evaluate_config(ft, tracks, median_ks=mks, min_seg=mseg, label=name[:12])
        results[name] = round(score, 4)
        marker = " *** BEST ***" if score > best_score else ""
        if score > best_score: best_score, best_name = score, name
        print(f"  {name}: {score:.4f}{marker}")
    
    print(f"\n{'='*70}")
    print(f"BEST: {best_name} = {best_score:.4f}")
    print(f"{'='*70}")
    
    with open(Path(r"D:\Music\nextchord\evaluation\postprocess_results.json"), "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
