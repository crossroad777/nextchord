"""madmom vs librosa vs BTC/CREMA 比較評価"""
import json, numpy as np, sys, time
from pathlib import Path
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

import mir_eval, librosa

ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")

# --- madmom ---
from madmom.features.chords import (
    CNNChordFeatureProcessor,
    DeepChromaChordRecognitionProcessor,
)
madmom_feat = CNNChordFeatureProcessor()
madmom_chord = DeepChromaChordRecognitionProcessor()
print("[OK] madmom CNNChordFeature + DeepChromaChordRecognition loaded")

def madmom_detect(wav_path):
    feats = madmom_feat(str(wav_path))
    result = madmom_chord(feats)
    # result is structured array with 'start', 'end', 'label'
    starts = result['start']
    labels = result['label']
    ends = result['end']
    return starts, labels, ends

def librosa_detect(wav_path):
    y, sr = librosa.load(str(wav_path), sr=22050, mono=True)
    tuning = librosa.estimate_tuning(y=y, sr=sr)
    hop_length = 2048
    chroma_cqt = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length, n_chroma=12, tuning=tuning)
    chroma_stft = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=hop_length, n_chroma=12, tuning=tuning)
    chroma = (chroma_cqt + chroma_stft) / 2.0
    note_names = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    templates = {
        'maj': np.array([1,0,0,0,1,0,0,1,0,0,0,0],dtype=float),
        'min': np.array([1,0,0,1,0,0,0,1,0,0,0,0],dtype=float),
        '7':   np.array([1,0,0,0,1,0,0,1,0,0,1,0],dtype=float),
        'min7':np.array([1,0,0,1,0,0,0,1,0,0,1,0],dtype=float),
        'maj7':np.array([1,0,0,0,1,0,0,1,0,0,0,1],dtype=float),
        'dim': np.array([1,0,0,1,0,0,1,0,0,0,0,0],dtype=float),
        'sus4':np.array([1,0,0,0,0,1,0,1,0,0,0,0],dtype=float),
        'sus2':np.array([1,0,1,0,0,0,0,1,0,0,0,0],dtype=float),
    }
    chord_templates = {}
    for i, name in enumerate(note_names):
        for qual, tmpl in templates.items():
            chord_templates[f"{name}:{qual}"] = np.roll(tmpl, i)
    n_frames = chroma.shape[1]
    frame_duration = hop_length / sr
    seg_starts, seg_labels = [], []
    prev = None
    for f in range(n_frames):
        frame = chroma[:, f]
        if np.sum(frame) < 0.01:
            chord = 'N'
        else:
            fn = frame / (np.linalg.norm(frame) + 1e-8)
            best_chord, best_score = 'N', 0.3
            for cn, t in chord_templates.items():
                tn = t / (np.linalg.norm(t) + 1e-8)
                s = np.dot(fn, tn)
                if s > best_score:
                    best_score = s
                    best_chord = cn
            chord = best_chord
        if chord != prev:
            seg_starts.append(f * frame_duration)
            seg_labels.append(chord)
            prev = chord
    return np.array(seg_starts), np.array(seg_labels), None

def extract_gt(jams_path):
    with open(jams_path, 'r') as f:
        data = json.load(f)
    for ann in data['annotations']:
        if ann['namespace'] == 'chord':
            intervals, labels = [], []
            for d in ann['data']:
                intervals.append([d['time'], d['time'] + d['duration']])
                labels.append(d['value'])
            return np.array(intervals), labels
    return None, None

def segs_to_intervals(starts, labels, dur, ends=None):
    intervals = []
    for i in range(len(starts)):
        if ends is not None:
            end = ends[i]
        else:
            end = starts[i+1] if i+1 < len(starts) else dur
        intervals.append([starts[i], end])
    return np.array(intervals), list(labels)

def get_genre(stem):
    for p in stem.split('_'):
        if p.startswith('BN'): return 'BossaNova'
        if p.startswith('Funk'): return 'Funk'
        if p.startswith('Jazz'): return 'Jazz'
        if p.startswith('Rock'): return 'Rock'
        if p.startswith('SS'): return 'SS(弾き語り)'
    return 'Unknown'

# --- 評価ループ ---
jams_files = sorted(ANNOTATION_DIR.glob('*_comp.jams'))
# SS + Rock のみ（弾き語りに近いジャンル）を重点評価しつつ全ジャンルも
methods = ['madmom', 'librosa']

for method in methods:
    print(f"\n{'='*65}")
    print(f"評価: {method}")
    print(f"{'='*65}")
    
    genre_scores = defaultdict(lambda: defaultdict(list))
    t0 = time.time()
    
    for i, jf in enumerate(jams_files):
        stem = jf.stem
        wav = AUDIO_DIR / f"{stem}_mic.wav"
        if not wav.exists():
            continue
        ref_int, ref_lab = extract_gt(str(jf))
        if ref_int is None:
            continue
        dur = ref_int[-1, 1]
        
        try:
            if method == 'madmom':
                seg_s, seg_l, seg_e = madmom_detect(wav)
                est_int, est_lab = segs_to_intervals(seg_s, seg_l, dur, seg_e)
            else:
                seg_s, seg_l, _ = librosa_detect(wav)
                est_int, est_lab = segs_to_intervals(seg_s, seg_l, dur)
            
            scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
            genre = get_genre(stem)
            for k in ['root', 'thirds', 'triads', 'mirex']:
                genre_scores[genre][k].append(scores[k])
        except Exception as e:
            print(f"  [{i+1}] ERROR: {stem}: {e}")
    
    elapsed = time.time() - t0
    
    print(f"\n{'Genre':<18s} {'N':>4s} {'root':>7s} {'thirds':>7s} {'triads':>7s} {'mirex':>7s}")
    print("-" * 60)
    for genre in ['SS(弾き語り)', 'Rock', 'BossaNova', 'Funk', 'Jazz']:
        s = genre_scores[genre]
        n = len(s['root'])
        if n == 0:
            continue
        print(f"{genre:<18s} {n:4d} {np.mean(s['root']):7.3f} {np.mean(s['thirds']):7.3f} {np.mean(s['triads']):7.3f} {np.mean(s['mirex']):7.3f}")
    print("-" * 60)
    all_r = [v for g in genre_scores.values() for v in g['root']]
    all_m = [v for g in genre_scores.values() for v in g['mirex']]
    print(f"{'ALL':<18s} {len(all_r):4d} {np.mean(all_r):7.3f} {'':7s} {'':7s} {np.mean(all_m):7.3f}")
    print(f"({elapsed:.0f}s)")
