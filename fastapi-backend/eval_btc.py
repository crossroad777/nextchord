"""BTC (Bi-directional Transformer for Chords) を GuitarSet で評価"""
import os, sys, json, time
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')

# BTC のパスを追加
sys.path.insert(0, r'D:\Music\nextchord\BTC-ISMIR19')

import torch
import librosa
import mir_eval
from pathlib import Path
from collections import defaultdict

from btc_model import BTC_model
from utils.hparams import HParams
from utils.mir_eval_modules import audio_file_to_features, idx2chord, idx2voca_chord

# --- セットアップ ---
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}")

config = HParams.load(r"D:\Music\nextchord\BTC-ISMIR19\run_config.yaml")

# large_voca = True (170クラス) で評価 -> 7th系も検出可能
config.feature['large_voca'] = True
config.model['num_chords'] = 170
model_file = r'D:\Music\nextchord\BTC-ISMIR19\test\btc_model_large_voca.pt'
idx_to_chord = idx2voca_chord()
print(f"Model: large_voca (170 chords)")

model = BTC_model(config=config.model).to(device)

checkpoint = torch.load(model_file, map_location=device, weights_only=False)
mean = checkpoint['mean']
std = checkpoint['std']
model.load_state_dict(checkpoint['model'])
model.eval()
print(f"Model loaded: {model_file}")

# --- パス ---
ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")

def btc_detect(wav_path):
    """BTC でコード検出 -> .lab 形式の lines を返す"""
    feature, feature_per_second, song_length_second = audio_file_to_features(str(wav_path), config)
    feature = feature.T
    feature = (feature - mean) / std
    time_unit = feature_per_second
    n_timestep = config.model['timestep']

    num_pad = n_timestep - (feature.shape[0] % n_timestep)
    feature = np.pad(feature, ((0, num_pad), (0, 0)), mode="constant", constant_values=0)
    num_instance = feature.shape[0] // n_timestep

    start_time = 0.0
    intervals = []
    labels = []

    with torch.no_grad():
        feat_tensor = torch.tensor(feature, dtype=torch.float32).unsqueeze(0).to(device)
        prev_chord = None
        for t in range(num_instance):
            self_attn_output, _ = model.self_attn_layers(feat_tensor[:, n_timestep * t:n_timestep * (t + 1), :])
            prediction, _ = model.output_layer(self_attn_output)
            prediction = prediction.squeeze()
            for i in range(n_timestep):
                current_time = time_unit * (n_timestep * t + i)
                chord_idx = prediction[i].item()
                if prev_chord is None:
                    prev_chord = chord_idx
                    start_time = 0.0
                    continue
                if chord_idx != prev_chord:
                    intervals.append([start_time, current_time])
                    labels.append(idx_to_chord[prev_chord])
                    start_time = current_time
                    prev_chord = chord_idx
                if t == num_instance - 1 and i + num_pad == n_timestep:
                    if start_time != current_time:
                        intervals.append([start_time, current_time])
                        labels.append(idx_to_chord[prev_chord])
                    break

    return np.array(intervals), labels

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

def get_genre(stem):
    for p in stem.split('_'):
        if p.startswith('BN'): return 'BossaNova'
        if p.startswith('Funk'): return 'Funk'
        if p.startswith('Jazz'): return 'Jazz'
        if p.startswith('Rock'): return 'Rock'
        if p.startswith('SS'): return 'SS(弾き語り)'
    return 'Unknown'

# --- 評価 ---
jams_files = sorted(ANNOTATION_DIR.glob('*_comp.jams'))
print(f"\n評価対象: {len(jams_files)} comp tracks")

genre_scores = defaultdict(lambda: defaultdict(list))
t0 = time.time()
errors = 0

for i, jf in enumerate(jams_files):
    stem = jf.stem
    wav = AUDIO_DIR / f"{stem}_mic.wav"
    if not wav.exists():
        continue
    ref_int, ref_lab = extract_gt(str(jf))
    if ref_int is None:
        continue

    try:
        t1 = time.time()
        est_int, est_lab = btc_detect(wav)
        scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
        genre = get_genre(stem)
        for k in ['root', 'thirds', 'triads', 'sevenths', 'mirex']:
            genre_scores[genre][k].append(scores[k])
        dt = time.time() - t1
        if (i+1) % 10 == 0 or i < 3:
            print(f"  [{i+1}/{len(jams_files)}] {stem[:30]:30s} root={scores['root']:.3f} mirex={scores['mirex']:.3f} ({dt:.1f}s)")
    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  [{i+1}] ERROR: {stem}: {e}")

elapsed = time.time() - t0

# --- 結果 ---
print(f"\n{'='*65}")
print(f"BTC (Bi-directional Transformer, ISMIR 2019) - large_voca")
print(f"{'='*65}")
print(f"{'Genre':<18s} {'N':>4s} {'root':>7s} {'thirds':>7s} {'triads':>7s} {'mirex':>7s}")
print("-" * 60)

for genre in ['SS(弾き語り)', 'Rock', 'BossaNova', 'Funk', 'Jazz']:
    s = genre_scores[genre]
    n = len(s['root'])
    if n == 0:
        continue
    print(f"{genre:<18s} {n:4d} {np.mean(s['root']):7.3f} {np.mean(s['thirds']):7.3f} {np.mean(s['triads']):7.3f} {np.mean(s['mirex']):7.3f}")

print("-" * 60)
all_r = [v for g in genre_scores.values() for v in g['root']]
all_t = [v for g in genre_scores.values() for v in g['thirds']]
all_tr = [v for g in genre_scores.values() for v in g['triads']]
all_m = [v for g in genre_scores.values() for v in g['mirex']]
if all_r:
    print(f"{'ALL':<18s} {len(all_r):4d} {np.mean(all_r):7.3f} {np.mean(all_t):7.3f} {np.mean(all_tr):7.3f} {np.mean(all_m):7.3f}")
print(f"\n処理時間: {elapsed:.0f}s, エラー: {errors}")

# --- 比較表 ---
print(f"\n{'='*65}")
print(f"比較表")
print(f"{'='*65}")
print(f"{'Method':<22s} {'ALL_root':>8s} {'ALL_mirex':>9s}  {'SS_root':>7s} {'SS_mirex':>8s}")
print("-" * 60)
print(f"{'librosa(現行)':<22s} {'0.476':>8s} {'0.414':>9s}  {'0.625':>7s} {'0.542':>8s}")
if all_r:
    ss_r = genre_scores.get('SS(弾き語り)', {}).get('root', [])
    ss_m = genre_scores.get('SS(弾き語り)', {}).get('mirex', [])
    ss_r_s = f"{np.mean(ss_r):.3f}" if ss_r else "N/A"
    ss_m_s = f"{np.mean(ss_m):.3f}" if ss_m else "N/A"
    print(f"{'BTC(large_voca)':<22s} {np.mean(all_r):8.3f} {np.mean(all_m):9.3f}  {ss_r_s:>7s} {ss_m_s:>8s}")
print(f"{'SOTA(公表値)':<22s} {'~0.88':>8s} {'~0.82':>9s}")
