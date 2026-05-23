"""
Source Separation + Chord Recognition
======================================
Demucsでドラム除去 → ハーモニック音を強調 → BTC推論
論文: "2,000フレーム以上の誤認識を修正"
"""
import sys, os, numpy as np, subprocess, tempfile, shutil
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch, mir_eval, librosa, soundfile as sf
from src.utils.hparams import HParams
from src.models import load_model
from src.evaluation.utils.common import extract_norm_stats, extract_vocab, extract_song_features
from src.evaluation.utils.inference import predict_sliding_windows
from src.utils.device import get_device

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")
SEP_CACHE = Path(r"D:\Music\nextchord\evaluation\separated_audio")

config = HParams.load(str(CHORDMINI_ROOT / "config" / "ChordMini.yaml"))
device = get_device()

# Load FT model
ckpt = str(CHORDMINI_ROOT / "checkpoints" / "beatles_ft" / "single_split" / "best_model.pth")
if not os.path.exists(ckpt):
    ckpt = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
args = type("A", (), {"seq_len": None, "model_type": "BTC"})()
model, _, _ = load_model(ckpt, "BTC", config, device, args)
mn, st = extract_norm_stats(ckpt)
i2c, c2i = extract_vocab(ckpt)
model.eval()
print(f"Model: {Path(ckpt).name}", flush=True)


def separate_and_remix(wav_path, output_dir, remix_type="no_drums"):
    """
    Demucsで分離して再ミックス
    remix_type:
      - "no_drums": ドラム除去 (vocals + bass + other)
      - "harmony_only": ドラム+ボーカル除去 (bass + other)
      - "harmony_boost": ドラム除去 + other(ギター/ピアノ)を1.5倍
    """
    out_path = Path(output_dir) / f"{Path(wav_path).stem}_{remix_type}.wav"
    if out_path.exists():
        return str(out_path)
    
    # Run demucs separation
    sep_dir = Path(output_dir) / "stems" / Path(wav_path).stem
    if not (sep_dir / "vocals.wav").exists():
        cmd = [
            sys.executable, "-m", "demucs",
            "--two-stems", "drums",  # Quick: just separate drums vs rest
            "-o", str(Path(output_dir) / "stems"),
            "--name", "htdemucs",
            str(wav_path)
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            return None
    
    # Check for separated files
    stem_dir = sep_dir
    if not stem_dir.exists():
        # Try htdemucs subdirectory
        stem_dir = Path(output_dir) / "stems" / "htdemucs" / Path(wav_path).stem
    
    if not stem_dir.exists():
        return None
    
    # Load stems
    try:
        if remix_type == "no_drums":
            # --two-stems=drums produces "drums.wav" and "no_drums.wav"
            no_drums = stem_dir / "no_drums.wav"
            if no_drums.exists():
                y, sr = librosa.load(str(no_drums), sr=None)
                sf.write(str(out_path), y, sr)
                return str(out_path)
        
        # Fallback: use full 4-stem separation
        vocals_path = stem_dir / "vocals.wav"
        bass_path = stem_dir / "bass.wav"
        other_path = stem_dir / "other.wav"
        drums_path = stem_dir / "drums.wav"
        
        if not all(p.exists() for p in [vocals_path, bass_path, other_path]):
            return None
        
        vocals, sr = librosa.load(str(vocals_path), sr=None)
        bass, _ = librosa.load(str(bass_path), sr=sr)
        other, _ = librosa.load(str(other_path), sr=sr)
        
        n = min(len(vocals), len(bass), len(other))
        
        if remix_type == "no_drums":
            mix = vocals[:n] + bass[:n] + other[:n]
        elif remix_type == "harmony_only":
            mix = bass[:n] + other[:n]
        elif remix_type == "harmony_boost":
            mix = vocals[:n] * 0.7 + bass[:n] + other[:n] * 1.5
        else:
            mix = vocals[:n] + bass[:n] + other[:n]
        
        sf.write(str(out_path), mix, sr)
        return str(out_path)
    except Exception as e:
        print(f"  Remix error: {e}", flush=True)
        return None


def evaluate_config(remix_type, max_tracks=180):
    """Evaluate a remix configuration"""
    scores = []
    count = 0
    
    for ad in sorted(ANNO.iterdir()):
        if not ad.is_dir(): continue
        for lab_file in sorted(ad.glob("*.lab")):
            wav = AUDIO / ad.name / f"{lab_file.stem}.wav"
            if not wav.exists(): continue
            count += 1
            if count > max_tracks: break
            
            try:
                ri, rl = mir_eval.io.load_labeled_intervals(str(lab_file))
                
                # Separate and remix
                cache_dir = SEP_CACHE / ad.name
                cache_dir.mkdir(parents=True, exist_ok=True)
                
                remixed = separate_and_remix(str(wav), str(cache_dir), remix_type)
                
                if remixed is None:
                    # Fallback to original
                    fm, fd = extract_song_features(str(wav), config)
                else:
                    fm, fd = extract_song_features(remixed, config)
                
                p = predict_sliding_windows(
                    model=model, feature_matrix=fm, mean=mn, std=st,
                    seq_len=108, batch_size=16, model_type="BTC",
                    n_classes=len(c2i), use_overlap=True, overlap_ratio=0.9)
                
                iv = []; lb = []; prev = None; start = 0.0
                for ii, idx in enumerate(p):
                    ch = i2c.get(int(idx), "N"); t = float(ii) * fd
                    if prev is None: prev = ch; continue
                    if ch != prev:
                        iv.append([start, t]); lb.append(prev)
                        start = t; prev = ch
                if prev: iv.append([start, float(len(p)) * fd]); lb.append(prev)
                
                r = mir_eval.chord.evaluate(ri, rl, np.array(iv), lb)
                scores.append(float(r["thirds"]))
                
                if count % 10 == 0:
                    print(f"  [{remix_type}] {count} tracks: {np.mean(scores):.4f}", flush=True)
            
            except Exception as e:
                if count <= 3:
                    import traceback; traceback.print_exc()
        if count > max_tracks: break
    
    return scores


print("=" * 60, flush=True)
print("Source Separation Chord Recognition", flush=True)
print("=" * 60, flush=True)

# First: quick test with 10 tracks
print("\n--- Quick test (10 tracks) ---", flush=True)
for rt in ["no_drums"]:
    s = evaluate_config(rt, max_tracks=10)
    if s:
        print(f"  {rt}: {np.mean(s):.4f} ({len(s)} tracks)", flush=True)

# Baseline on same 10 tracks
print("\n--- Baseline (original, 10 tracks) ---", flush=True)
scores_base = []
count = 0
for ad in sorted(ANNO.iterdir()):
    if not ad.is_dir(): continue
    for lab_file in sorted(ad.glob("*.lab")):
        wav = AUDIO / ad.name / f"{lab_file.stem}.wav"
        if not wav.exists(): continue
        count += 1
        if count > 10: break
        try:
            ri, rl = mir_eval.io.load_labeled_intervals(str(lab_file))
            fm, fd = extract_song_features(str(wav), config)
            p = predict_sliding_windows(model=model, feature_matrix=fm, mean=mn, std=st,
                seq_len=108, batch_size=16, model_type="BTC",
                n_classes=len(c2i), use_overlap=True, overlap_ratio=0.9)
            iv = []; lb = []; prev = None; start = 0.0
            for ii, idx in enumerate(p):
                ch = i2c.get(int(idx), "N"); t = float(ii) * fd
                if prev is None: prev = ch; continue
                if ch != prev: iv.append([start, t]); lb.append(prev); start = t; prev = ch
            if prev: iv.append([start, float(len(p)) * fd]); lb.append(prev)
            r = mir_eval.chord.evaluate(ri, rl, np.array(iv), lb)
            scores_base.append(float(r["thirds"]))
        except: pass
    if count > 10: break
print(f"  baseline: {np.mean(scores_base):.4f} ({len(scores_base)} tracks)", flush=True)

# If quick test shows improvement, run full
print("\n--- Full evaluation (180 tracks) ---", flush=True)
for rt in ["no_drums"]:
    s = evaluate_config(rt, max_tracks=180)
    if s:
        print(f"\n  {rt}: {np.mean(s):.4f} ({len(s)} tracks)", flush=True)

print("\nDone!", flush=True)
