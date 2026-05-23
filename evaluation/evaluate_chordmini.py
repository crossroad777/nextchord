"""
ChordMini を Beatles Isophonics で評価し、
既存BTC (ファインチューニング済み) と比較する。
"""
import sys
import os
import json
import numpy as np
import time
from pathlib import Path

# ChordMini の src を PATH に追加
CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch
import mir_eval
import librosa

BASE_DIR = Path(r"D:\Music\nextchord\evaluation")
ANNOTATIONS_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO_DIR = BASE_DIR / "beatles_audio"
PREDICTIONS_DIR = BASE_DIR / "beatles_predictions"

CHORDMINI_CHECKPOINT = CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth"
CHORDMINI_CONFIG = CHORDMINI_ROOT / "config" / "ChordMini.yaml"


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
    """ChordMini BTC student モデルをロード"""
    from src.utils.hparams import HParams
    from src.models import load_model
    from src.evaluation.utils.common import extract_norm_stats, extract_vocab
    from src.utils.device import get_device
    
    config = HParams.load(str(CHORDMINI_CONFIG))
    device = get_device()
    
    model, _, _ = load_model(str(CHORDMINI_CHECKPOINT), 'BTC', config, device, 
                             type('Args', (), {'seq_len': None, 'model_type': 'BTC'})())
    mean, std = extract_norm_stats(str(CHORDMINI_CHECKPOINT))
    idx_to_chord, chord_to_idx = extract_vocab(str(CHORDMINI_CHECKPOINT))
    
    model.eval()
    
    return {
        'model': model,
        'config': config,
        'mean': mean,
        'std': std,
        'idx_to_chord': idx_to_chord,
        'chord_to_idx': chord_to_idx,
        'device': device,
    }


def predict_chordmini(bundle, audio_path):
    """ChordMiniで1曲予測 → (intervals, labels)"""
    from src.evaluation.utils.common import extract_song_features
    from src.evaluation.utils.inference import predict_sliding_windows
    from src.utils.chords import Chords
    
    feature_matrix, frame_duration = extract_song_features(audio_path, bundle['config'])
    
    seq_len = 108  # BTC default
    preds = predict_sliding_windows(
        model=bundle['model'],
        feature_matrix=feature_matrix,
        mean=bundle['mean'],
        std=bundle['std'],
        seq_len=seq_len,
        batch_size=16,
        model_type='BTC',
        n_classes=len(bundle['chord_to_idx']),
    )
    
    # フレーム予測 → interval/label に変換
    intervals = []
    labels = []
    prev_chord = None
    start_time = 0.0
    
    for i, idx in enumerate(preds):
        chord = bundle['idx_to_chord'].get(int(idx), 'N')
        t = float(i) * frame_duration
        
        if prev_chord is None:
            prev_chord = chord
            start_time = 0.0
            continue
        
        if chord != prev_chord:
            intervals.append([start_time, t])
            labels.append(prev_chord)
            start_time = t
            prev_chord = chord
    
    # 最後のセグメント
    if prev_chord is not None:
        end_time = float(len(preds)) * frame_duration
        intervals.append([start_time, end_time])
        labels.append(prev_chord)
    
    return np.array(intervals), labels


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    print("=" * 70)
    print("ChordMini vs BTC - Beatles Isophonics Comparison")
    print("=" * 70)
    
    tracks = get_tracks()
    max_tracks = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    tracks = tracks[:max_tracks]
    print(f"\nTracks: {len(tracks)}")
    
    # ChordMini ロード
    print("\nLoading ChordMini...")
    try:
        bundle = load_chordmini()
        print(f"  Model loaded on {bundle['device']}")
        print(f"  Vocab size: {len(bundle['idx_to_chord'])}")
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback; traceback.print_exc()
        return
    
    results_btc = []
    results_cm = []
    
    for i, track in enumerate(tracks):
        print(f"\n[{i+1}/{len(tracks)}] {track['title']}")
        
        # BTC既存予測
        ref_int, ref_lab = mir_eval.io.load_labeled_intervals(track['ref'])
        btc_int, btc_lab = mir_eval.io.load_labeled_intervals(track['btc_pred'])
        btc_scores = mir_eval.chord.evaluate(ref_int, ref_lab, btc_int, btc_lab)
        btc_thirds = float(btc_scores['thirds'])
        results_btc.append(btc_thirds)
        
        # ChordMini予測
        try:
            cm_int, cm_lab = predict_chordmini(bundle, track['audio'])
            cm_scores = mir_eval.chord.evaluate(ref_int, ref_lab, cm_int, cm_lab)
            cm_thirds = float(cm_scores['thirds'])
            results_cm.append(cm_thirds)
            
            diff = cm_thirds - btc_thirds
            sym = "+" if diff >= 0 else ""
            print(f"  BTC={btc_thirds:.3f}  ChordMini={cm_thirds:.3f}  ({sym}{diff:.3f})")
        except Exception as e:
            print(f"  ChordMini ERROR: {e}")
            results_cm.append(btc_thirds)
    
    # レポート
    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    print(f"BTC (fine-tuned):  {np.mean(results_btc):.4f}")
    print(f"ChordMini:         {np.mean(results_cm):.4f}")
    diff = np.mean(results_cm) - np.mean(results_btc)
    print(f"Difference:        {diff:+.4f}")
    
    improved = sum(1 for b, c in zip(results_btc, results_cm) if c > b + 0.01)
    degraded = sum(1 for b, c in zip(results_btc, results_cm) if c < b - 0.01)
    print(f"Improved: {improved}, Degraded: {degraded}, Unchanged: {len(tracks) - improved - degraded}")


if __name__ == "__main__":
    main()
