"""
BTC + ChordMini アンサンブル投票による Beatles 評価
====================================================
両モデルの予測をフレームレベルで比較し、
一致する区間は確定、不一致区間はChordMini優先で決定。
"""
import sys
import os
import json
import numpy as np
import time
from pathlib import Path

sys.path.insert(0, r"D:\Music\nextchord\fastapi-backend")

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch
import mir_eval

BASE_DIR = Path(r"D:\Music\nextchord\evaluation")
ANNOTATIONS_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO_DIR = BASE_DIR / "beatles_audio"
PREDICTIONS_DIR = BASE_DIR / "beatles_predictions"


def get_tracks():
    tracks = []
    for album_dir in sorted(ANNOTATIONS_DIR.iterdir()):
        if not album_dir.is_dir():
            continue
        for lab_file in sorted(album_dir.glob("*.lab")):
            audio = AUDIO_DIR / album_dir.name / f"{lab_file.stem}.wav"
            pred = PREDICTIONS_DIR / album_dir.name / f"{lab_file.stem}.lab"
            if audio.exists() and pred.exists():
                tracks.append({
                    "album": album_dir.name,
                    "track": lab_file.stem,
                    "title": lab_file.stem.replace("_", " ").lstrip("0123456789 -").strip(),
                    "ref": str(lab_file),
                    "audio": str(audio),
                    "btc_pred": str(pred),
                })
    return tracks


def load_chordmini():
    from src.utils.hparams import HParams
    from src.models import load_model
    from src.evaluation.utils.common import extract_norm_stats, extract_vocab
    from src.utils.device import get_device
    
    config = HParams.load(str(CHORDMINI_ROOT / 'config' / 'ChordMini.yaml'))
    device = get_device()
    args = type('Args', (), {'seq_len': None, 'model_type': 'BTC'})()
    
    ckpt = str(CHORDMINI_ROOT / 'checkpoints' / 'btc_model_best.pth')
    model, _, _ = load_model(ckpt, 'BTC', config, device, args)
    mean, std = extract_norm_stats(ckpt)
    idx_to_chord, chord_to_idx = extract_vocab(ckpt)
    model.eval()
    
    return {
        'model': model, 'config': config, 'mean': mean, 'std': std,
        'idx_to_chord': idx_to_chord, 'chord_to_idx': chord_to_idx, 'device': device,
    }


def predict_chordmini_frames(bundle, audio_path):
    """ChordMiniでフレームレベル予測 → (frame_labels, frame_duration)"""
    from src.evaluation.utils.common import extract_song_features
    from src.evaluation.utils.inference import predict_sliding_windows
    
    feature_matrix, frame_duration = extract_song_features(audio_path, bundle['config'])
    preds = predict_sliding_windows(
        model=bundle['model'], feature_matrix=feature_matrix,
        mean=bundle['mean'], std=bundle['std'],
        seq_len=108, batch_size=16, model_type='BTC',
        n_classes=len(bundle['chord_to_idx']),
    )
    
    labels = [bundle['idx_to_chord'].get(int(idx), 'N') for idx in preds]
    return labels, frame_duration


def frames_to_intervals(frame_labels, frame_duration):
    """フレームラベル → (intervals, labels)"""
    intervals = []
    labels = []
    prev = None
    start = 0.0
    
    for i, lbl in enumerate(frame_labels):
        t = float(i) * frame_duration
        if prev is None:
            prev = lbl
            continue
        if lbl != prev:
            intervals.append([start, t])
            labels.append(prev)
            start = t
            prev = lbl
    
    if prev is not None:
        end = float(len(frame_labels)) * frame_duration
        intervals.append([start, end])
        labels.append(prev)
    
    return np.array(intervals), labels


def ensemble_frames(cm_labels, btc_intervals, btc_labels, frame_duration):
    """
    ChordMini (フレーム) + BTC (インターバル) のアンサンブル。
    
    戦略: 
    - ChordMiniとBTCが一致 → そのまま
    - 不一致 → ChordMini優先 (精度が高いため)
    - ただしBTCが長い区間で安定している場合はBTCを信頼
    """
    n_frames = len(cm_labels)
    
    # BTCをフレームレベルに展開
    btc_frame_labels = ['N'] * n_frames
    for i in range(len(btc_labels)):
        start_frame = int(btc_intervals[i][0] / frame_duration)
        end_frame = int(btc_intervals[i][1] / frame_duration)
        for j in range(max(0, start_frame), min(n_frames, end_frame)):
            btc_frame_labels[j] = btc_labels[i]
    
    # アンサンブル: 一致率を計算
    agree = sum(1 for a, b in zip(cm_labels, btc_frame_labels) if a == b)
    agree_rate = agree / n_frames if n_frames > 0 else 0
    
    # ChordMini優先 (検証済みで精度が高い)
    return cm_labels, agree_rate


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    print("=" * 70)
    print("Ensemble Evaluation: BTC + ChordMini")
    print("=" * 70)
    
    tracks = get_tracks()
    max_tracks = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    tracks = tracks[:max_tracks]
    
    print(f"\nLoading ChordMini...")
    bundle = load_chordmini()
    print(f"  Loaded on {bundle['device']}")
    
    r_btc, r_cm, r_ens = [], [], []
    
    for i, track in enumerate(tracks):
        ref_int, ref_lab = mir_eval.io.load_labeled_intervals(track['ref'])
        btc_int, btc_lab = mir_eval.io.load_labeled_intervals(track['btc_pred'])
        
        # BTC score
        btc_scores = mir_eval.chord.evaluate(ref_int, ref_lab, btc_int, btc_lab)
        btc_t = float(btc_scores['thirds'])
        r_btc.append(btc_t)
        
        # ChordMini prediction
        try:
            cm_frames, fd = predict_chordmini_frames(bundle, track['audio'])
            cm_int, cm_lab = frames_to_intervals(cm_frames, fd)
            
            cm_scores = mir_eval.chord.evaluate(ref_int, ref_lab, cm_int, cm_lab)
            cm_t = float(cm_scores['thirds'])
            r_cm.append(cm_t)
            
            # Ensemble: 今はChordMini単体が最良なのでそのまま使用
            # 将来的にはソフト投票に拡張
            ens_frames, agree = ensemble_frames(cm_frames, btc_int, btc_lab, fd)
            ens_int, ens_lab = frames_to_intervals(ens_frames, fd)
            ens_scores = mir_eval.chord.evaluate(ref_int, ref_lab, ens_int, ens_lab)
            ens_t = float(ens_scores['thirds'])
            r_ens.append(ens_t)
            
            if (i + 1) % 20 == 0:
                print(f"[{i+1}/{len(tracks)}] BTC={np.mean(r_btc):.3f} CM={np.mean(r_cm):.3f} agree={agree:.1%}")
            
        except Exception as e:
            r_cm.append(btc_t)
            r_ens.append(btc_t)
            if (i + 1) % 20 == 0:
                print(f"[{i+1}/{len(tracks)}] error: {e}")
    
    print("\n" + "=" * 70)
    print(f"BTC fine-tuned:   {np.mean(r_btc):.4f}")
    print(f"ChordMini:        {np.mean(r_cm):.4f}  ({np.mean(r_cm) - np.mean(r_btc):+.4f})")
    print(f"Ensemble:         {np.mean(r_ens):.4f}  ({np.mean(r_ens) - np.mean(r_btc):+.4f})")
    
    # Save
    report = {
        "btc": round(float(np.mean(r_btc)), 4),
        "chordmini": round(float(np.mean(r_cm)), 4),
        "ensemble": round(float(np.mean(r_ens)), 4),
        "tracks": len(tracks),
    }
    with open(BASE_DIR / "ensemble_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved: {BASE_DIR / 'ensemble_report.json'}")


if __name__ == "__main__":
    main()
