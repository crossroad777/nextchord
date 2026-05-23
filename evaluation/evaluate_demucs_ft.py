"""
Demucs前処理 + ChordMini FT 評価
==================================
ボーカル除去→ハーモニック成分(ギター+ピアノ+ベース)でコード認識
"""
import sys, numpy as np, json, subprocess, tempfile, os
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT)); sys.path.insert(0, str(CHORDMINI_ROOT/"src"))
import torch, mir_eval, soundfile as sf

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")
DEMUCS_CACHE = Path(r"D:\Music\nextchord\evaluation\demucs_cache")

def get_tracks(n=180):
    t = []
    for ad in sorted(ANNO.iterdir()):
        if not ad.is_dir(): continue
        for lab in sorted(ad.glob("*.lab")):
            wav = AUDIO / ad.name / f"{lab.stem}.wav"
            if wav.exists(): t.append({"ref": str(lab), "audio": str(wav),
                                        "title": lab.stem, "album": ad.name})
    return t[:n]

def demucs_separate(wav_path, cache_dir):
    """Demucsで音源分離、ハーモニック成分のみ返す"""
    stem = Path(wav_path).stem
    album = Path(wav_path).parent.name
    cache_path = cache_dir / album / f"{stem}_harmonic.wav"
    
    if cache_path.exists():
        return str(cache_path)
    
    # Demucs実行
    out_dir = cache_dir / "_demucs_tmp"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        str(Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")),
        "-m", "demucs", "--two-stems=vocals",
        "-n", "htdemucs",
        "-o", str(out_dir),
        str(wav_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    
    # no_vocalsを探す
    no_vocals = out_dir / "htdemucs" / Path(wav_path).stem / "no_vocals.wav"
    
    if no_vocals.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(str(no_vocals), str(cache_path))
        # cleanup
        demucs_dir = out_dir / "htdemucs" / Path(wav_path).stem
        if demucs_dir.exists():
            shutil.rmtree(str(demucs_dir), ignore_errors=True)
        return str(cache_path)
    
    return None

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

def predict(bundle, audio_path):
    from src.evaluation.utils.common import extract_song_features
    from src.evaluation.utils.inference import predict_sliding_windows
    fm, fd = extract_song_features(audio_path, bundle['config'])
    p = predict_sliding_windows(model=bundle['model'], feature_matrix=fm,
        mean=bundle['mean'], std=bundle['std'], seq_len=108, batch_size=16,
        model_type='BTC', n_classes=len(bundle['chord_to_idx']),
        use_overlap=True, overlap_ratio=0.5)
    iv = []; lb = []; prev = None; start = 0.0
    for i, idx in enumerate(p):
        ch = bundle['idx_to_chord'].get(int(idx), 'N'); t = float(i) * fd
        if prev is None: prev = ch; continue
        if ch != prev: iv.append([start, t]); lb.append(prev); start = t; prev = ch
    if prev: iv.append([start, float(len(p)) * fd]); lb.append(prev)
    return np.array(iv), lb

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    # まず10曲でDemucsの効果を検証
    tracks = get_tracks(10)
    DEMUCS_CACHE.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("Demucs Preprocessing + ChordMini FT")
    print(f"Testing on {len(tracks)} tracks first")
    print("=" * 70)
    
    ft = load_b(CHORDMINI_ROOT / "checkpoints" / "beatles_ft" / "single_split" / "best_model.pth")
    print("FT model loaded.\n")
    
    raw_scores = []
    demucs_scores = []
    
    for i, t in enumerate(tracks):
        ref_int, ref_lab = mir_eval.io.load_labeled_intervals(t['ref'])
        
        # Raw audio
        try:
            pi, pl = predict(ft, t['audio'])
            r = mir_eval.chord.evaluate(ref_int, ref_lab, pi, pl)
            raw = float(r['thirds'])
            raw_scores.append(raw)
        except Exception as e:
            raw = 0; raw_scores.append(0)
        
        # Demucs separated
        print(f"[{i+1}/{len(tracks)}] {t['title']}: raw={raw:.3f}", end="")
        try:
            harmonic = demucs_separate(t['audio'], DEMUCS_CACHE)
            if harmonic:
                pi, pl = predict(ft, harmonic)
                r = mir_eval.chord.evaluate(ref_int, ref_lab, pi, pl)
                dem = float(r['thirds'])
                demucs_scores.append(dem)
                diff = dem - raw
                print(f"  demucs={dem:.3f}  ({diff:+.3f})")
            else:
                demucs_scores.append(raw)
                print("  demucs=FAILED")
        except Exception as e:
            demucs_scores.append(raw)
            print(f"  demucs=ERROR: {e}")
    
    print(f"\n{'='*70}")
    print(f"Raw:    {np.mean(raw_scores):.4f}")
    print(f"Demucs: {np.mean(demucs_scores):.4f}")
    print(f"Diff:   {np.mean(demucs_scores) - np.mean(raw_scores):+.4f}")
    
    improved = sum(1 for r, d in zip(raw_scores, demucs_scores) if d > r + 0.01)
    degraded = sum(1 for r, d in zip(raw_scores, demucs_scores) if d < r - 0.01)
    print(f"Improved: {improved}, Degraded: {degraded}")

if __name__ == "__main__":
    main()
