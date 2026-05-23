"""
音楽理論ベース後処理: キー推定 + コード補正
=============================================
1. 曲全体のキーを推定 (chromagram → Krumhansl-Kessler key profiles)
2. フレーム予測のconfidenceが低い箇所で、調性外コードを調性内コードに補正
3. 短い区間のフリッカーを除去 (median filter)
"""
import sys, os, numpy as np
from pathlib import Path
from collections import Counter

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch, mir_eval, librosa
from src.utils.hparams import HParams
from src.models import load_model
from src.evaluation.utils.common import extract_norm_stats, extract_vocab, extract_song_features
from src.evaluation.utils.inference import predict_sliding_windows
from src.utils.device import get_device
from src.utils.chords import idx2voca_chord

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")

# Key profiles (Krumhansl-Kessler)
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
PITCH_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Diatonic chords for each major key (root pitch classes)
def get_diatonic_chords(key_root, is_minor=False):
    """Return set of pitch classes that are diatonic to the key"""
    if is_minor:
        # Natural minor: 0, 2, 3, 5, 7, 8, 10
        intervals = [0, 2, 3, 5, 7, 8, 10]
    else:
        # Major: 0, 2, 4, 5, 7, 9, 11
        intervals = [0, 2, 4, 5, 7, 9, 11]
    return set((key_root + i) % 12 for i in intervals)

def estimate_key(audio_path, sr=22050):
    """Estimate key using chromagram correlation with key profiles"""
    y, sr = librosa.load(audio_path, sr=sr)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = chroma.mean(axis=1)
    
    best_corr = -1
    best_key = 0
    best_mode = 'major'
    
    for shift in range(12):
        shifted_major = np.roll(MAJOR_PROFILE, shift)
        shifted_minor = np.roll(MINOR_PROFILE, shift)
        
        corr_major = np.corrcoef(chroma_mean, shifted_major)[0, 1]
        corr_minor = np.corrcoef(chroma_mean, shifted_minor)[0, 1]
        
        if corr_major > best_corr:
            best_corr = corr_major
            best_key = shift
            best_mode = 'major'
        if corr_minor > best_corr:
            best_corr = corr_minor
            best_key = shift
            best_mode = 'minor'
    
    return best_key, best_mode, best_corr

def chord_to_root_pc(chord_name):
    """Convert chord name to root pitch class (0-11)"""
    if chord_name in ('N', 'X', ''): return -1
    root = chord_name.split(':')[0]
    pc_map = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5,
              'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11,
              'Db': 1, 'Eb': 3, 'Gb': 6, 'Ab': 8, 'Bb': 10}
    return pc_map.get(root, -1)

def apply_median_filter(predictions, window=5):
    """Apply median filter to smooth out short chord flickers"""
    from scipy.ndimage import median_filter
    filtered = median_filter(predictions, size=window)
    return filtered

def postprocess_predictions(predictions, i2c, key_root, is_minor, logits=None, confidence_threshold=0.5):
    """
    Post-process predictions using music theory:
    1. If confidence is low AND chord is non-diatonic, replace with most likely diatonic chord
    2. Apply median filter to smooth flickers
    """
    diatonic = get_diatonic_chords(key_root, is_minor)
    result = predictions.copy()
    
    if logits is not None:
        # Use softmax confidence
        probs = torch.softmax(torch.tensor(logits), dim=-1).numpy()
        max_probs = probs.max(axis=-1)
        
        for i in range(len(result)):
            chord_name = i2c.get(int(result[i]), 'N')
            root_pc = chord_to_root_pc(chord_name)
            
            if root_pc >= 0 and root_pc not in diatonic and max_probs[i] < confidence_threshold:
                # Find best diatonic alternative
                sorted_indices = np.argsort(-probs[i])
                for alt_idx in sorted_indices:
                    alt_chord = i2c.get(int(alt_idx), 'N')
                    alt_pc = chord_to_root_pc(alt_chord)
                    if alt_pc in diatonic or alt_chord == 'N':
                        result[i] = alt_idx
                        break
    
    # Median filter
    result = apply_median_filter(result, window=5)
    
    return result


config = HParams.load(str(CHORDMINI_ROOT / "config" / "ChordMini.yaml"))
device = get_device()

ckpt = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
model, _, _ = load_model(ckpt, 'BTC', config, device, args)
mn, st = extract_norm_stats(ckpt)
i2c, c2i = extract_vocab(ckpt)
model.eval()

scores_raw = []
scores_key = []
scores_median = []

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
            
            # Helper to build intervals
            def build_intervals(preds):
                iv = []; lb = []; prev = None; start = 0.0
                for ii, idx in enumerate(preds):
                    ch = i2c.get(int(idx), 'N'); t = float(ii) * fd
                    if prev is None: prev = ch; continue
                    if ch != prev:
                        iv.append([start, t]); lb.append(prev)
                        start = t; prev = ch
                if prev: iv.append([start, float(len(preds)) * fd]); lb.append(prev)
                return np.array(iv), lb
            
            # Raw score
            iv, lb = build_intervals(p)
            r = mir_eval.chord.evaluate(ri, rl, iv, lb)
            scores_raw.append(float(r['thirds']))
            
            # Key estimation
            key_root, key_mode, key_conf = estimate_key(str(wav))
            is_minor = key_mode == 'minor'
            
            # Median filter only
            p_med = apply_median_filter(p, window=5)
            iv_m, lb_m = build_intervals(p_med)
            r_m = mir_eval.chord.evaluate(ri, rl, iv_m, lb_m)
            scores_median.append(float(r_m['thirds']))
            
            # Key-aware correction (without logits, just median)
            # For key-aware, we need logits - skip for now, just do median
            scores_key.append(float(r_m['thirds']))
            
        except Exception as e:
            pass

print(f"{'='*70}", flush=True)
print(f"Post-Processing Results ({len(scores_raw)} tracks)", flush=True)
print(f"{'='*70}", flush=True)
print(f"Raw:           {np.mean(scores_raw):.4f}", flush=True)
print(f"Median(w=5):   {np.mean(scores_median):.4f} ({(np.mean(scores_median)-np.mean(scores_raw))*100:+.2f}%)", flush=True)
