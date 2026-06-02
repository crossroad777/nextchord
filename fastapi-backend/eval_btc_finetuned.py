"""ファインチューニング済み BTC を全 GuitarSet で評価"""
import json, numpy as np, sys, time
from pathlib import Path
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'D:\Music\nextchord\BTC-ISMIR19')

import torch, mir_eval
from btc_model import BTC_model
from utils.hparams import HParams
from utils.mir_eval_modules import audio_file_to_features, idx2voca_chord

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")

def load_model(model_path, config):
    model = BTC_model(config=config.model).to(device)
    ckpt = torch.load(model_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt['model'])
    model.eval()
    return model, ckpt['mean'], ckpt['std']

def extract_gt(jams_path):
    with open(jams_path, 'r') as f:
        data = json.load(f)
    for ann in data['annotations']:
        if ann['namespace'] == 'chord':
            intervals = np.array([[d['time'], d['time'] + d['duration']] for d in ann['data']])
            labels = [d['value'] for d in ann['data']]
            return intervals, labels
    return None, None

def btc_detect(model, config, mean, std, wav_path, idx_to_chord):
    feature, fps, dur = audio_file_to_features(str(wav_path), config)
    feature = feature.T
    feature = (feature - mean) / std
    time_unit = fps
    n_ts = config.model['timestep']
    num_pad = n_ts - (feature.shape[0] % n_ts)
    feature = np.pad(feature, ((0, num_pad), (0, 0)), mode="constant", constant_values=0)
    num_inst = feature.shape[0] // n_ts
    intervals, labels = [], []
    start_time = 0.0
    with torch.no_grad():
        ft = torch.tensor(feature, dtype=torch.float32).unsqueeze(0).to(device)
        prev = None
        for t in range(num_inst):
            out, _ = model.self_attn_layers(ft[:, n_ts*t:n_ts*(t+1), :])
            pred, _ = model.output_layer(out)
            pred = pred.squeeze()
            for i in range(n_ts):
                ct = time_unit * (n_ts * t + i)
                ci = pred[i].item()
                if prev is None: prev = ci; start_time = 0.0; continue
                if ci != prev:
                    intervals.append([start_time, ct])
                    labels.append(idx_to_chord[prev])
                    start_time = ct; prev = ci
                if t == num_inst - 1 and i + num_pad == n_ts:
                    if start_time != ct:
                        intervals.append([start_time, ct])
                        labels.append(idx_to_chord[prev])
                    break
    return np.array(intervals), labels

def get_genre(stem):
    for p in stem.split('_'):
        if p.startswith('BN'): return 'BossaNova'
        if p.startswith('Funk'): return 'Funk'
        if p.startswith('Jazz'): return 'Jazz'
        if p.startswith('Rock'): return 'Rock'
        if p.startswith('SS'): return 'SS(弾き語り)'
    return 'Unknown'

def eval_model(label, model, config, mean, std):
    idx_to_chord = idx2voca_chord()
    jams_files = sorted(ANNOTATION_DIR.glob('*_comp.jams'))
    genre_scores = defaultdict(lambda: defaultdict(list))
    
    for jf in jams_files:
        stem = jf.stem
        wav = AUDIO_DIR / f"{stem}_mic.wav"
        if not wav.exists(): continue
        ref_int, ref_lab = extract_gt(str(jf))
        if ref_int is None: continue
        try:
            est_int, est_lab = btc_detect(model, config, mean, std, wav, idx_to_chord)
            scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
            genre = get_genre(stem)
            for k in ['root', 'thirds', 'triads', 'mirex']:
                genre_scores[genre][k].append(scores[k])
        except:
            pass
    
    print(f"\n{'='*65}")
    print(f"{label}")
    print(f"{'='*65}")
    print(f"{'Genre':<18s} {'N':>4s} {'root':>7s} {'thirds':>7s} {'triads':>7s} {'mirex':>7s}")
    print("-" * 60)
    for g in ['SS(弾き語り)', 'Rock', 'BossaNova', 'Funk', 'Jazz']:
        s = genre_scores[g]
        n = len(s['root'])
        if n == 0: continue
        print(f"{g:<18s} {n:4d} {np.mean(s['root']):7.3f} {np.mean(s['thirds']):7.3f} {np.mean(s['triads']):7.3f} {np.mean(s['mirex']):7.3f}")
    print("-" * 60)
    all_r = [v for g in genre_scores.values() for v in g['root']]
    all_m = [v for g in genre_scores.values() for v in g['mirex']]
    print(f"{'ALL':<18s} {len(all_r):4d} {np.mean(all_r):7.3f} {'':7s} {'':7s} {np.mean(all_m):7.3f}")
    return {'all_root': np.mean(all_r), 'all_mirex': np.mean(all_m),
            'ss_root': np.mean(genre_scores['SS(弾き語り)']['root']),
            'ss_mirex': np.mean(genre_scores['SS(弾き語り)']['mirex'])}

# --- 比較 ---
config = HParams.load(r"D:\Music\nextchord\BTC-ISMIR19\run_config.yaml")
config.feature['large_voca'] = True
config.model['num_chords'] = 170

# 1. Original
m1, mean1, std1 = load_model(r'D:\Music\nextchord\BTC-ISMIR19\test\btc_model_large_voca.pt', config)
r1 = eval_model("BTC Original (large_voca)", m1, config, mean1, std1)

# 2. Fine-tuned
ft_path = r'D:\Music\nextchord\BTC-ISMIR19\finetuned\btc_finetuned_val05_best.pt'
m2, mean2, std2 = load_model(ft_path, config)
r2 = eval_model("BTC Fine-tuned (GuitarSet, val=05)", m2, config, mean2, std2)

# 比較表
print(f"\n{'='*65}")
print(f"比較表")
print(f"{'='*65}")
print(f"{'Method':<30s} {'ALL root':>8s} {'ALL mirex':>9s} {'SS root':>8s} {'SS mirex':>9s}")
print("-" * 68)
print(f"{'librosa(現行)':<30s} {'0.476':>8s} {'0.414':>9s} {'0.625':>8s} {'0.542':>9s}")
print(f"{'BTC Original':<30s} {r1['all_root']:8.3f} {r1['all_mirex']:9.3f} {r1['ss_root']:8.3f} {r1['ss_mirex']:9.3f}")
print(f"{'BTC Fine-tuned':<30s} {r2['all_root']:8.3f} {r2['all_mirex']:9.3f} {r2['ss_root']:8.3f} {r2['ss_mirex']:9.3f}")
