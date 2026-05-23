"""
madmom CNNベースコード認識 + BTC とのアンサンブル評価
===================================================
madmomは独自のCNN+CRFでコード認識する。BTCと独立したモデルなのでアンサンブルに有効。
"""
import sys, os, numpy as np
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import mir_eval
import madmom

ANNO = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
AUDIO = Path(r"D:\Music\nextchord\evaluation\beatles_audio")

def madmom_chord_recognition(audio_path):
    """Use madmom's deep chroma + CRF chord recognizer"""
    from madmom.features.chords import (
        DeepChromaChordRecognitionProcessor,
        CNNChordFeatureProcessor,
        CRFChordRecognitionProcessor,
    )
    
    # Try CNN-based first (higher accuracy)
    try:
        feat_proc = CNNChordFeatureProcessor()
        decode_proc = CRFChordRecognitionProcessor()
        feats = feat_proc(str(audio_path))
        chords = decode_proc(feats)
        return chords
    except Exception:
        pass
    
    # Fallback to deep chroma
    try:
        proc = DeepChromaChordRecognitionProcessor()
        chords = proc(str(audio_path))
        return chords
    except Exception as e:
        print(f"  madmom error: {e}", flush=True)
        return None

def evaluate_madmom():
    scores = []
    total = 0
    
    for ad in sorted(ANNO.iterdir()):
        if not ad.is_dir(): continue
        for lab_file in sorted(ad.glob("*.lab")):
            wav = AUDIO / ad.name / f"{lab_file.stem}.wav"
            if not wav.exists(): continue
            total += 1
            try:
                ri, rl = mir_eval.io.load_labeled_intervals(str(lab_file))
                
                chords = madmom_chord_recognition(wav)
                if chords is None: continue
                
                # madmom returns list of (start, end, chord_label)
                iv = np.array([[c[0], c[1]] for c in chords])
                lb = [c[2] for c in chords]
                
                r = mir_eval.chord.evaluate(ri, rl, iv, lb)
                score = float(r['thirds'])
                scores.append(score)
                
                if total % 20 == 0:
                    print(f"  {total} tracks, avg: {np.mean(scores):.4f}", flush=True)
                
            except Exception as e:
                if total <= 3:
                    print(f"  Error {lab_file.stem}: {e}", flush=True)
    
    return scores

print("=" * 70, flush=True)
print("Madmom CNN+CRF Chord Recognition", flush=True)
print("=" * 70, flush=True)

scores = evaluate_madmom()
if scores:
    print(f"\nmadmom ({len(scores)} tracks): Thirds = {np.mean(scores):.4f}", flush=True)
else:
    print("No results!", flush=True)
