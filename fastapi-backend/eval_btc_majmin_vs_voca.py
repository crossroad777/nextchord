"""BTC majmin (25クラス) vs large_voca (170クラス) 比較"""
import json, numpy as np, sys, time
from pathlib import Path
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'D:\Music\nextchord\BTC-ISMIR19')

import torch, mir_eval
from btc_model import BTC_model
from utils.hparams import HParams
from utils.mir_eval_modules import audio_file_to_features, idx2chord, idx2voca_chord

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")

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

def evaluate_model(model_type):
    config = HParams.load(r"D:\Music\nextchord\BTC-ISMIR19\run_config.yaml")
    if model_type == 'large_voca':
        config.feature['large_voca'] = True
        config.model['num_chords'] = 170
        model_file = r'D:\Music\nextchord\BTC-ISMIR19\test\btc_model_large_voca.pt'
        itc = idx2voca_chord()
    else:
        config.model['num_chords'] = 25
        model_file = r'D:\Music\nextchord\BTC-ISMIR19\test\btc_model.pt'
        itc = idx2chord
    
    model = BTC_model(config=config.model).to(device)
    ckpt = torch.load(model_file, map_location=device, weights_only=False)
    model.load_state_dict(ckpt['model'])
    model.eval()
    mean, std = ckpt['mean'], ckpt['std']
    
    def detect(wav_path):
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
                        intervals.append([start_time, ct]); labels.append(itc[ci] if isinstance(itc, dict) else itc[prev])
                        start_time = ct; prev = ci
                    if t == num_inst - 1 and i + num_pad == n_ts:
                        if start_time != ct:
                            intervals.append([start_time, ct]); labels.append(itc[ci] if isinstance(itc, dict) else itc[prev])
                        break
        return np.array(intervals), labels
    
    # 注: idx2chord はリスト、idx2voca_chord() は dict
    # 修正: labels.append で prev を使うべき
    def detect_fixed(wav_path):
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
                        lbl = itc[prev] if isinstance(itc, dict) else itc[prev]
                        intervals.append([start_time, ct]); labels.append(lbl)
                        start_time = ct; prev = ci
                    if t == num_inst - 1 and i + num_pad == n_ts:
                        if start_time != ct:
                            lbl = itc[prev] if isinstance(itc, dict) else itc[prev]
                            intervals.append([start_time, ct]); labels.append(lbl)
                        break
        return np.array(intervals), labels
    
    jams_files = sorted(ANNOTATION_DIR.glob('*_comp.jams'))
    genre_scores = defaultdict(lambda: defaultdict(list))
    
    for jf in jams_files:
        stem = jf.stem
        wav = AUDIO_DIR / f"{stem}_mic.wav"
        if not wav.exists(): continue
        ref_int, ref_lab = extract_gt(str(jf))
        if ref_int is None: continue
        try:
            est_int, est_lab = detect_fixed(wav)
            scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
            genre = get_genre(stem)
            for k in ['root', 'thirds', 'triads', 'mirex']:
                genre_scores[genre][k].append(scores[k])
        except Exception as e:
            pass
    
    return genre_scores

# --- 評価実行 ---
for mt in ['majmin', 'large_voca']:
    print(f"\n{'='*65}")
    print(f"BTC {mt}")
    print(f"{'='*65}")
    t0 = time.time()
    gs = evaluate_model(mt)
    
    print(f"{'Genre':<18s} {'N':>4s} {'root':>7s} {'thirds':>7s} {'triads':>7s} {'mirex':>7s}")
    print("-" * 60)
    for g in ['SS(弾き語り)', 'Rock', 'BossaNova', 'Funk', 'Jazz']:
        s = gs[g]
        n = len(s['root'])
        if n == 0: continue
        print(f"{g:<18s} {n:4d} {np.mean(s['root']):7.3f} {np.mean(s['thirds']):7.3f} {np.mean(s['triads']):7.3f} {np.mean(s['mirex']):7.3f}")
    print("-" * 60)
    all_r = [v for g in gs.values() for v in g['root']]
    all_m = [v for g in gs.values() for v in g['mirex']]
    print(f"{'ALL':<18s} {len(all_r):4d} {np.mean(all_r):7.3f} {'':7s} {'':7s} {np.mean(all_m):7.3f}")
    print(f"({time.time()-t0:.0f}s)")
