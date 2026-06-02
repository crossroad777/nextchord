"""ジャンル別コード認識精度の分析"""
import json, numpy as np, sys, os
from pathlib import Path
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

import mir_eval, librosa

ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")

def librosa_chord_detection(wav_path):
    y, sr = librosa.load(wav_path, sr=22050, mono=True)
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
    return np.array(seg_starts), np.array(seg_labels)

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

def segs_to_intervals(starts, labels, dur):
    intervals = []
    for i in range(len(starts)):
        end = starts[i+1] if i+1 < len(starts) else dur
        intervals.append([starts[i], end])
    return np.array(intervals), list(labels)

def get_genre(stem):
    for p in stem.split('_'):
        if p.startswith('BN'): return 'BossaNova'
        if p.startswith('Funk'): return 'Funk'
        if p.startswith('Jazz'): return 'Jazz'
        if p.startswith('Rock'): return 'Rock'
        if p.startswith('SS'): return 'SS(弾き語り系)'
    return 'Unknown'

# --- Ground Truth のコード語彙を調査 ---
all_gt_chords = []
genre_scores = defaultdict(lambda: defaultdict(list))
jams_files = sorted(ANNOTATION_DIR.glob('*_comp.jams'))

for jf in jams_files:
    stem = jf.stem
    wav = AUDIO_DIR / f"{stem}_mic.wav"
    if not wav.exists():
        continue
    ref_int, ref_lab = extract_gt(str(jf))
    if ref_int is None:
        continue
    
    all_gt_chords.extend(ref_lab)
    
    dur = ref_int[-1, 1]
    seg_s, seg_l = librosa_chord_detection(str(wav))
    est_int, est_lab = segs_to_intervals(seg_s, seg_l, dur)
    try:
        scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
        genre = get_genre(stem)
        for k in ['root', 'thirds', 'triads', 'sevenths', 'mirex']:
            genre_scores[genre][k].append(scores[k])
    except Exception as e:
        pass

# --- 結果出力 ---
print("=" * 65)
print("ジャンル別コード認識精度")
print("=" * 65)

header = f"{'Genre':<18s} {'N':>4s} {'root':>7s} {'thirds':>7s} {'triads':>7s} {'mirex':>7s}"
print(header)
print("-" * 65)

for genre in ['SS(弾き語り系)', 'Rock', 'BossaNova', 'Funk', 'Jazz']:
    s = genre_scores[genre]
    n = len(s['root'])
    if n == 0:
        continue
    r = np.mean(s['root'])
    t = np.mean(s['thirds'])
    tr = np.mean(s['triads'])
    m = np.mean(s['mirex'])
    print(f"{genre:<18s} {n:4d} {r:7.3f} {t:7.3f} {tr:7.3f} {m:7.3f}")

print("-" * 65)
all_r = [v for g in genre_scores.values() for v in g['root']]
all_m = [v for g in genre_scores.values() for v in g['mirex']]
print(f"{'ALL':<18s} {len(all_r):4d} {np.mean(all_r):7.3f} {'':7s} {'':7s} {np.mean(all_m):7.3f}")

# --- Ground Truth のコード語彙分析 ---
print("\n" + "=" * 65)
print("Ground Truth コード語彙分析")
print("=" * 65)

from collections import Counter
chord_counts = Counter(all_gt_chords)
print(f"総コードイベント数: {len(all_gt_chords)}")
print(f"ユニークコード数: {len(chord_counts)}")
print(f"\n出現頻度 Top 20:")
for ch, cnt in chord_counts.most_common(20):
    print(f"  {ch:30s} {cnt:4d} ({cnt/len(all_gt_chords)*100:.1f}%)")

# 品質の分布
qualities = Counter()
for ch in all_gt_chords:
    if ch == 'N':
        qualities['N'] += 1
    elif ':' in ch:
        q = ch.split(':')[1].split('/')[0].split('(')[0]
        qualities[q] += 1
    else:
        qualities['unknown'] += 1

print(f"\n品質の分布:")
for q, cnt in qualities.most_common():
    print(f"  {q:20s} {cnt:4d} ({cnt/len(all_gt_chords)*100:.1f}%)")
