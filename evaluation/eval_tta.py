"""
Test-Time Augmentation (TTA): 推論時ピッチシフト平均
====================================================
同じ音源を複数キーにシフトして推論、結果を元キーに戻して投票
モデル変更不要で精度向上
"""
import sys, os, numpy as np
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch, mir_eval, librosa
from src.utils.hparams import HParams
from src.utils.config_utils import get_config_value
from src.models import load_model
from src.evaluation.utils.common import extract_norm_stats, extract_vocab
from src.utils.device import get_device
from src.utils.chords import PITCH_CLASS, transpose_chord_label, idx2voca_chord

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")

config = HParams.load(str(CHORDMINI_ROOT / "config" / "ChordMini.yaml"))
device = get_device()

SR = get_config_value(config, 'mp3', 'song_hz', 22050)
HOP = get_config_value(config, 'feature', 'hop_length', 2048)
N_BINS = get_config_value(config, 'feature', 'n_bins', 144)
BPO = get_config_value(config, 'feature', 'bins_per_octave', 24)
BPS = BPO // 12  # bins per semitone = 2

def extract_cqt(audio_path):
    from src.utils.audio_io import suppress_stderr
    with suppress_stderr():
        y, sr = librosa.load(str(audio_path), sr=SR)
    cqt = librosa.cqt(y, sr=sr, n_bins=N_BINS, bins_per_octave=BPO,
                       hop_length=HOP, fmin=librosa.note_to_hz('C1'))
    return np.log(np.abs(cqt) + 1e-6).T.astype(np.float32)

def shift_cqt(cqt, semitones):
    """CQTビンシフトでピッチシフト"""
    if semitones == 0: return cqt
    shift = semitones * BPS
    shifted = np.zeros_like(cqt)
    n = cqt.shape[1]
    if shift > 0 and shift < n:
        shifted[:, shift:] = cqt[:, :n-shift]
    elif shift < 0 and -shift < n:
        shifted[:, :n+shift] = cqt[:, -shift:]
    return shifted

def predict_with_logits(model, feature_matrix, mean, std, seq_len, n_classes):
    """推論してlogitsを返す"""
    feature_matrix = (feature_matrix - mean) / (std + 1e-8)
    n_frames = feature_matrix.shape[0]
    stride = seq_len // 2
    all_logits = np.zeros((n_frames, n_classes), dtype=np.float32)
    counts = np.zeros(n_frames, dtype=np.float32)
    
    for start in range(0, max(1, n_frames - seq_len + 1), stride):
        end = min(start + seq_len, n_frames)
        chunk = feature_matrix[start:end]
        if chunk.shape[0] < seq_len:
            pad = np.zeros((seq_len - chunk.shape[0], chunk.shape[1]), dtype=np.float32)
            chunk = np.concatenate([chunk, pad])
        
        x = torch.from_numpy(chunk).unsqueeze(0).to(device)
        with torch.no_grad():
            out = model(x)
            logits = out[0] if isinstance(out, tuple) else out
        logits = logits.cpu().numpy()[0]  # (seq_len, n_classes)
        
        valid = min(end - start, seq_len)
        all_logits[start:start+valid] += logits[:valid]
        counts[start:start+valid] += 1
    
    mask = counts > 0
    all_logits[mask] /= counts[mask, None]
    return all_logits

def transpose_logits(logits, semitones, n_roots=12, n_qualities=14):
    """Logitsを転調に合わせて逆シフト (元キーに戻す)"""
    # Chord vocabulary: root(12) x quality(14) + X(168) + N(169)
    n_classes = logits.shape[1]
    transposed = np.zeros_like(logits)
    
    for frame in range(logits.shape[0]):
        for root in range(n_roots):
            for q in range(n_qualities):
                orig_idx = root * n_qualities + q
                # Transpose back: if we shifted +2, the detected "D:maj" is actually "C:maj"
                new_root = (root - semitones) % n_roots
                new_idx = new_root * n_qualities + q
                transposed[frame, new_idx] += logits[frame, orig_idx]
        # Copy X and N
        if n_classes > 168:
            transposed[frame, 168] = logits[frame, 168]
        if n_classes > 169:
            transposed[frame, 169] = logits[frame, 169]
    
    return transposed

# Load model
ckpt_ft = str(CHORDMINI_ROOT / "checkpoints" / "beatles_ft" / "single_split" / "best_model.pth")
ckpt_orig = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
ckpt = ckpt_ft if os.path.exists(ckpt_ft) else ckpt_orig

print(f"Model: {Path(ckpt).name}", flush=True)
args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
model, _, _ = load_model(ckpt, 'BTC', config, device, args)
mn, st = extract_norm_stats(ckpt)
i2c, c2i = extract_vocab(ckpt)
model.eval()
n_classes = len(c2i)
fd = HOP / SR  # frame duration

TTA_SHIFTS = [-2, -1, 0, 1, 2]  # semitones

scores_raw = []
scores_tta = []
count = 0

for ad in sorted(ANNO.iterdir()):
    if not ad.is_dir(): continue
    for lab_file in sorted(ad.glob("*.lab")):
        wav = AUDIO / ad.name / f"{lab_file.stem}.wav"
        if not wav.exists(): continue
        count += 1
        try:
            ri, rl = mir_eval.io.load_labeled_intervals(str(lab_file))
            cqt = extract_cqt(wav)
            
            # Raw prediction (shift=0 only)
            logits_raw = predict_with_logits(model, cqt, mn, st, 108, n_classes)
            pred_raw = logits_raw.argmax(axis=1)
            
            # TTA: average logits from multiple shifts
            accumulated = np.zeros_like(logits_raw)
            for shift in TTA_SHIFTS:
                shifted_cqt = shift_cqt(cqt, shift)
                logits_s = predict_with_logits(model, shifted_cqt, mn, st, 108, n_classes)
                # Transpose logits back to original key
                logits_back = transpose_logits(logits_s, shift)
                accumulated += logits_back
            
            accumulated /= len(TTA_SHIFTS)
            pred_tta = accumulated.argmax(axis=1)
            
            # Build intervals helper
            def build_iv(preds):
                iv = []; lb = []; prev = None; start = 0.0
                for ii, idx in enumerate(preds):
                    ch = i2c.get(int(idx), 'N'); t = float(ii) * fd
                    if prev is None: prev = ch; continue
                    if ch != prev:
                        iv.append([start, t]); lb.append(prev); start = t; prev = ch
                if prev: iv.append([start, float(len(preds)) * fd]); lb.append(prev)
                return np.array(iv) if iv else np.array([[0, 1]]), lb if lb else ['N']
            
            iv_r, lb_r = build_iv(pred_raw)
            r = mir_eval.chord.evaluate(ri, rl, iv_r, lb_r)
            scores_raw.append(float(r['thirds']))
            
            iv_t, lb_t = build_iv(pred_tta)
            r2 = mir_eval.chord.evaluate(ri, rl, iv_t, lb_t)
            scores_tta.append(float(r2['thirds']))
            
            if count % 30 == 0:
                print(f"  {count} tracks | Raw: {np.mean(scores_raw):.4f} | TTA: {np.mean(scores_tta):.4f}", flush=True)
            
        except Exception as e:
            if count <= 3:
                import traceback; traceback.print_exc()

print(f"\n{'='*70}", flush=True)
print(f"Test-Time Augmentation Results ({len(scores_raw)} tracks)", flush=True)
print(f"{'='*70}", flush=True)
print(f"Raw:  {np.mean(scores_raw):.4f}", flush=True)
print(f"TTA:  {np.mean(scores_tta):.4f} ({(np.mean(scores_tta)-np.mean(scores_raw))*100:+.2f}%)", flush=True)
