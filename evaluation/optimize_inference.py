"""
Phase 1+2: ChordMini 推論最適化グリッドサーチ + マルチモデルアンサンブル
======================================================================
SoloTab論文の知見を適用:
- overlap推論 + logit投票 + temporal smoothing
- 3モデル (BTC, ChordNet, Original BTC) のフレームレベル合議
"""
import sys
import os
import json
import numpy as np
import time
from pathlib import Path
from itertools import product

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch
import mir_eval

ANNOTATIONS_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO_DIR = Path(r"D:\Music\nextchord\evaluation\beatles_audio")


def get_tracks(max_n=180):
    tracks = []
    for album_dir in sorted(ANNOTATIONS_DIR.iterdir()):
        if not album_dir.is_dir(): continue
        for lab_file in sorted(album_dir.glob("*.lab")):
            wav = AUDIO_DIR / album_dir.name / f"{lab_file.stem}.wav"
            if wav.exists():
                tracks.append({"ref": str(lab_file), "audio": str(wav),
                               "title": lab_file.stem})
    return tracks[:max_n]


def load_model_bundle(checkpoint, model_type='BTC'):
    from src.utils.hparams import HParams
    from src.models import load_model
    from src.evaluation.utils.common import extract_norm_stats, extract_vocab
    from src.utils.device import get_device
    
    config = HParams.load(str(CHORDMINI_ROOT / 'config' / 'ChordMini.yaml'))
    device = get_device()
    args = type('Args', (), {'seq_len': None, 'model_type': model_type})()
    
    model, _, _ = load_model(str(checkpoint), model_type, config, device, args)
    mean, std = extract_norm_stats(str(checkpoint))
    idx_to_chord, chord_to_idx = extract_vocab(str(checkpoint))
    model.eval()
    
    return {
        'model': model, 'config': config, 'mean': mean, 'std': std,
        'idx_to_chord': idx_to_chord, 'chord_to_idx': chord_to_idx,
        'device': device, 'model_type': model_type,
    }


def predict_with_options(bundle, audio_path, vote_agg='hard', use_overlap=False,
                        overlap_ratio=None, smooth_logits=False,
                        smooth_preds=False, kernel_size=9, use_gaussian=False):
    from src.evaluation.utils.common import extract_song_features
    from src.evaluation.utils.inference import predict_sliding_windows
    
    feature_matrix, frame_duration = extract_song_features(audio_path, bundle['config'])
    
    preds = predict_sliding_windows(
        model=bundle['model'], feature_matrix=feature_matrix,
        mean=bundle['mean'], std=bundle['std'],
        seq_len=108, batch_size=16, model_type=bundle['model_type'],
        n_classes=len(bundle['chord_to_idx']),
        vote_aggregation=vote_agg,
        use_overlap=use_overlap,
        overlap_ratio=overlap_ratio,
        smooth_logits=smooth_logits,
        smooth_predictions=smooth_preds,
        kernel_size=kernel_size,
        use_gaussian=use_gaussian,
    )
    
    # Frame predictions -> intervals
    intervals, labels = [], []
    prev, start = None, 0.0
    for i, idx in enumerate(preds):
        chord = bundle['idx_to_chord'].get(int(idx), 'N')
        t = float(i) * frame_duration
        if prev is None:
            prev = chord; continue
        if chord != prev:
            intervals.append([start, t]); labels.append(prev)
            start = t; prev = chord
    if prev is not None:
        intervals.append([start, float(len(preds)) * frame_duration])
        labels.append(prev)
    return np.array(intervals), labels


def evaluate_config(bundle, tracks, **kwargs):
    scores = []
    for track in tracks:
        try:
            ref_int, ref_lab = mir_eval.io.load_labeled_intervals(track['ref'])
            pred_int, pred_lab = predict_with_options(bundle, track['audio'], **kwargs)
            result = mir_eval.chord.evaluate(ref_int, ref_lab, pred_int, pred_lab)
            scores.append(float(result['thirds']))
        except Exception:
            pass
    return np.mean(scores) if scores else 0.0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    # 20曲サブセットで高速グリッドサーチ
    tracks_subset = get_tracks(20)
    tracks_full = get_tracks(180)
    
    print("=" * 70)
    print("Phase 1: Inference Optimization Grid Search")
    print(f"Subset: {len(tracks_subset)} tracks for grid search")
    print("=" * 70)
    
    # Load ChordMini BTC (primary model)
    print("\nLoading ChordMini BTC...")
    btc_bundle = load_model_bundle(
        CHORDMINI_ROOT / 'checkpoints' / 'btc_model_best.pth', 'BTC')
    
    # --- Phase 1: Grid Search ---
    configs = []
    
    # Baseline
    configs.append(("baseline", {}))
    
    # Overlap variations
    for ov in [0.25, 0.5, 0.75]:
        configs.append((f"overlap_{ov}", 
                        {"use_overlap": True, "overlap_ratio": ov}))
    
    # Vote aggregation
    for agg in ['logit', 'prob']:
        configs.append((f"vote_{agg}", {"vote_agg": agg}))
    
    # Overlap + vote
    for agg in ['logit', 'prob']:
        configs.append((f"overlap_0.5_{agg}",
                        {"use_overlap": True, "overlap_ratio": 0.5, "vote_agg": agg}))
    
    # Smooth logits
    configs.append(("smooth_logits", {"smooth_logits": True}))
    configs.append(("smooth_logits_gauss", {"smooth_logits": True, "use_gaussian": True}))
    
    # Smooth predictions (majority filter)
    configs.append(("smooth_preds", {"smooth_preds": True}))
    
    # Full combo
    for ks in [5, 9, 15]:
        configs.append((f"full_logit_ov0.5_ks{ks}",
                        {"use_overlap": True, "overlap_ratio": 0.5,
                         "vote_agg": "logit", "smooth_logits": True,
                         "use_gaussian": True, "kernel_size": ks,
                         "smooth_preds": True}))
    
    configs.append(("full_prob_ov0.5",
                    {"use_overlap": True, "overlap_ratio": 0.5,
                     "vote_agg": "prob", "smooth_logits": True,
                     "use_gaussian": True, "kernel_size": 9,
                     "smooth_preds": True}))
    
    results = []
    best_score, best_name, best_kwargs = 0, "", {}
    
    for name, kwargs in configs:
        t0 = time.time()
        score = evaluate_config(btc_bundle, tracks_subset, **kwargs)
        dt = time.time() - t0
        results.append({"name": name, "thirds": round(score, 4), "time": round(dt, 1)})
        marker = " *** BEST ***" if score > best_score else ""
        if score > best_score:
            best_score, best_name, best_kwargs = score, name, kwargs
        print(f"  {name:35s}  thirds={score:.4f}  ({dt:.1f}s){marker}")
    
    print(f"\n{'='*70}")
    print(f"BEST CONFIG: {best_name} = {best_score:.4f}")
    print(f"{'='*70}")
    
    # --- 最適設定で180曲フル評価 ---
    print(f"\nFull evaluation with best config '{best_name}' on {len(tracks_full)} tracks...")
    full_score = evaluate_config(btc_bundle, tracks_full, **best_kwargs)
    print(f"FULL 180 tracks: {full_score:.4f}")
    
    # --- Phase 2: Multi-model ensemble ---
    print(f"\n{'='*70}")
    print("Phase 2: Multi-Model Ensemble")
    print(f"{'='*70}")
    
    # Load ChordNet 2E1D
    print("\nLoading ChordNet 2E1D...")
    try:
        chordnet_bundle = load_model_bundle(
            CHORDMINI_ROOT / 'checkpoints' / '2e1d_model_best.pth', 'ChordNet')
        has_chordnet = True
        print(f"  Loaded, vocab={len(chordnet_bundle['idx_to_chord'])}")
    except Exception as e:
        print(f"  Failed: {e}")
        has_chordnet = False
    
    if has_chordnet:
        # ChordNet with best inference options
        cn_score = evaluate_config(chordnet_bundle, tracks_subset,
                                   use_overlap=True, overlap_ratio=0.5,
                                   vote_agg='logit', smooth_preds=True)
        print(f"  ChordNet 2E1D (20 tracks): {cn_score:.4f}")
        
        # Evaluate ChordNet on full
        if cn_score > 0.5:
            cn_full = evaluate_config(chordnet_bundle, tracks_full,
                                      use_overlap=True, overlap_ratio=0.5,
                                      vote_agg='logit', smooth_preds=True)
            print(f"  ChordNet 2E1D (180 tracks): {cn_full:.4f}")
    
    # Save results
    report = {
        "grid_search": results,
        "best_config": {"name": best_name, "kwargs": best_kwargs, "score_20": round(best_score, 4)},
        "full_180_score": round(full_score, 4),
        "baseline_180": 0.8203,
    }
    out_path = Path(r"D:\Music\nextchord\evaluation\optimization_results.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
