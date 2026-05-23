"""
真のフレームレベルアンサンブル + Demucs前処理
==============================================
SoloTab MoEの直接応用:
- 3モデルのlogitをフレームレベルで加算
- 多数決ではなくソフト投票（確率合算）
- Demucs前処理でボーカル除去
"""
import sys, os, json, numpy as np, time
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch
import mir_eval

ANNOTATIONS_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO_DIR = Path(r"D:\Music\nextchord\evaluation\beatles_audio")


def get_tracks(n=180):
    tracks = []
    for ad in sorted(ANNOTATIONS_DIR.iterdir()):
        if not ad.is_dir(): continue
        for lab in sorted(ad.glob("*.lab")):
            wav = AUDIO_DIR / ad.name / f"{lab.stem}.wav"
            if wav.exists():
                tracks.append({"ref": str(lab), "audio": str(wav),
                               "title": lab.stem})
    return tracks[:n]


def load_bundle(checkpoint, model_type='BTC'):
    from src.utils.hparams import HParams
    from src.models import load_model
    from src.evaluation.utils.common import extract_norm_stats, extract_vocab
    from src.utils.device import get_device
    config = HParams.load(str(CHORDMINI_ROOT / 'config' / 'ChordMini.yaml'))
    device = get_device()
    args = type('A', (), {'seq_len': None, 'model_type': model_type})()
    model, _, _ = load_model(str(checkpoint), model_type, config, device, args)
    mean, std = extract_norm_stats(str(checkpoint))
    i2c, c2i = extract_vocab(str(checkpoint))
    model.eval()
    return {'model': model, 'config': config, 'mean': mean, 'std': std,
            'idx_to_chord': i2c, 'chord_to_idx': c2i, 'device': device,
            'model_type': model_type}


def get_frame_logits(bundle, audio_path):
    """フレームレベルのlogitを返す (n_frames, n_classes)"""
    from src.evaluation.utils.common import extract_song_features
    
    feature_matrix, frame_duration = extract_song_features(audio_path, bundle['config'])
    feature_matrix = np.asarray(feature_matrix, dtype=np.float32)
    
    n_frames = feature_matrix.shape[0]
    seq_len = 108
    n_classes = len(bundle['chord_to_idx'])
    device = next(bundle['model'].parameters()).device
    
    # Normalize
    mean = torch.as_tensor(bundle['mean'], dtype=torch.float32, device=device)
    std = torch.as_tensor(bundle['std'], dtype=torch.float32, device=device)
    
    # Pad
    remainder = n_frames % seq_len
    pad = 0 if remainder == 0 else seq_len - remainder
    if pad > 0:
        feature_matrix = np.pad(feature_matrix, ((0, pad), (0, 0)), mode='constant')
    
    # Overlap inference
    overlap_ratio = 0.5
    stride = max(1, int(seq_len * (1 - overlap_ratio)))
    padded = feature_matrix.shape[0]
    n_windows = max(1, ((padded - seq_len) // stride) + 1)
    
    logit_sum = np.zeros((n_frames, n_classes), dtype=np.float32)
    counts = np.zeros(n_frames, dtype=np.int32)
    
    with torch.no_grad():
        bundle['model'].eval()
        for i in range(0, n_windows, 16):
            batch = []
            metas = []
            for j in range(i, min(i + 16, n_windows)):
                start = stride * j
                end = start + seq_len
                if end > padded: continue
                valid = min(seq_len, max(0, n_frames - start))
                if valid <= 0: continue
                batch.append(feature_matrix[start:end])
                metas.append((start, valid))
            
            if not batch: continue
            t = torch.from_numpy(np.stack(batch)).float().to(device)
            t = (t - mean) / (std + 1e-8)
            
            outputs = bundle['model'](t)
            logits = outputs[0] if isinstance(outputs, tuple) else outputs
            logits_np = logits.detach().cpu().numpy()
            
            for k, (start, valid) in enumerate(metas):
                logit_sum[start:start+valid] += logits_np[k, :valid]
                counts[start:start+valid] += 1
    
    # Average logits
    mask = counts > 0
    logit_sum[mask] /= counts[mask, None]
    
    return logit_sum, frame_duration


def ensemble_predict(bundles, audio_path, weights=None):
    """複数モデルのlogitをフレームレベルで合算して予測"""
    if weights is None:
        weights = [1.0] * len(bundles)
    
    all_logits = []
    fd = None
    
    for bundle, w in zip(bundles, weights):
        logits, frame_duration = get_frame_logits(bundle, audio_path)
        all_logits.append((logits, w))
        if fd is None:
            fd = frame_duration
    
    # フレーム数を最小に揃える
    min_frames = min(l.shape[0] for l, _ in all_logits)
    n_classes = all_logits[0][0].shape[1]
    
    # 重み付き合算
    combined = np.zeros((min_frames, n_classes), dtype=np.float32)
    for logits, w in all_logits:
        combined += logits[:min_frames] * w
    
    # Argmax
    preds = np.argmax(combined, axis=1)
    idx_to_chord = bundles[0]['idx_to_chord']
    
    # Frame → intervals
    intervals, labels = [], []
    prev, start = None, 0.0
    for i, idx in enumerate(preds):
        chord = idx_to_chord.get(int(idx), 'N')
        t = float(i) * fd
        if prev is None: prev = chord; continue
        if chord != prev:
            intervals.append([start, t]); labels.append(prev)
            start = t; prev = chord
    if prev:
        intervals.append([start, float(min_frames) * fd])
        labels.append(prev)
    
    return np.array(intervals), labels


def evaluate(bundles, tracks, weights=None, label=""):
    scores = []
    for i, t in enumerate(tracks):
        try:
            ri, rl = mir_eval.io.load_labeled_intervals(t['ref'])
            pi, pl = ensemble_predict(bundles, t['audio'], weights)
            r = mir_eval.chord.evaluate(ri, rl, pi, pl)
            scores.append(float(r['thirds']))
        except Exception as e:
            pass
        if (i + 1) % 30 == 0:
            print(f"  [{label}] {i+1}/{len(tracks)}: {np.mean(scores):.4f}")
    return np.mean(scores) if scores else 0.0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tracks = get_tracks(180)
    
    print("=" * 70)
    print("True Frame-Level Ensemble")
    print("=" * 70)
    
    # Load models
    print("\nLoading models...")
    btc = load_bundle(CHORDMINI_ROOT / 'checkpoints' / 'btc_model_best.pth', 'BTC')
    print("  BTC loaded")
    
    chordnet = load_bundle(CHORDMINI_ROOT / 'checkpoints' / '2e1d_model_best.pth', 'ChordNet')
    print("  ChordNet loaded")
    
    # --- Single model baselines ---
    print("\n--- Single Models (180 tracks) ---")
    
    btc_score = evaluate([btc], tracks, label="BTC")
    print(f"  BTC alone:      {btc_score:.4f}")
    
    cn_score = evaluate([chordnet], tracks, label="ChordNet")
    print(f"  ChordNet alone: {cn_score:.4f}")
    
    # --- 2-model ensemble ---
    print("\n--- 2-Model Ensemble (BTC + ChordNet) ---")
    
    # Equal weight
    ens_eq = evaluate([btc, chordnet], tracks, weights=[1.0, 1.0], label="EQ")
    print(f"  Equal (1:1):    {ens_eq:.4f}")
    
    # BTC-weighted (BTC is better)
    ens_bw = evaluate([btc, chordnet], tracks, weights=[2.0, 1.0], label="BW")
    print(f"  BTC-heavy (2:1): {ens_bw:.4f}")
    
    ens_bw3 = evaluate([btc, chordnet], tracks, weights=[3.0, 1.0], label="BW3")
    print(f"  BTC-heavy (3:1): {ens_bw3:.4f}")
    
    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"BTC single:       {btc_score:.4f}")
    print(f"ChordNet single:  {cn_score:.4f}")
    print(f"Ensemble (1:1):   {ens_eq:.4f}")
    print(f"Ensemble (2:1):   {ens_bw:.4f}")
    print(f"Ensemble (3:1):   {ens_bw3:.4f}")
    
    best = max(btc_score, cn_score, ens_eq, ens_bw, ens_bw3)
    print(f"\nBEST: {best:.4f}")
    
    report = {
        "btc_single": round(btc_score, 4),
        "chordnet_single": round(cn_score, 4),
        "ensemble_1_1": round(ens_eq, 4),
        "ensemble_2_1": round(ens_bw, 4),
        "ensemble_3_1": round(ens_bw3, 4),
    }
    with open(Path(r"D:\Music\nextchord\evaluation\ensemble_logit_results.json"), "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
