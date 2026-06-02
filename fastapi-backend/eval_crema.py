"""CREMA (SOTA公開モデル) vs librosa(現行) コード認識比較"""
import json, numpy as np, sys, time
from pathlib import Path
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

import mir_eval

ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")

# --- CREMA ---
print("Loading CREMA model...")
t_load = time.time()
from crema.analyze import analyze as crema_analyze
print(f"CREMA loaded in {time.time()-t_load:.1f}s")

def crema_detect(wav_path):
    """CREMA でコード検出 -> intervals, labels"""
    jam = crema_analyze(filename=str(wav_path))
    # JAMS から chord アノテーションを取得
    for ann in jam.annotations:
        if ann.namespace == 'chord':
            intervals = []
            labels = []
            for obs in ann.data:
                intervals.append([obs.time, obs.time + obs.duration])
                labels.append(obs.value)
            return np.array(intervals), labels
    return None, None

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
        est_int, est_lab = crema_detect(wav)
        if est_int is None:
            print(f"  [{i+1}] SKIP: no chord annotation from CREMA")
            continue
        
        scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
        genre = get_genre(stem)
        for k in ['root', 'thirds', 'triads', 'sevenths', 'mirex']:
            genre_scores[genre][k].append(scores[k])
        
        dt = time.time() - t1
        if (i+1) % 10 == 0 or i < 3:
            print(f"  [{i+1}/{len(jams_files)}] {stem[:30]:30s} "
                  f"root={scores['root']:.3f} mirex={scores['mirex']:.3f} ({dt:.1f}s)")
    except Exception as e:
        errors += 1
        if errors <= 3:
            print(f"  [{i+1}] ERROR: {stem}: {e}")

elapsed = time.time() - t0

# --- 結果 ---
print(f"\n{'='*65}")
print(f"CREMA (Brian McFee, 公開学習済みモデル)")
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

# --- librosa 参考値（前回の結果）---
print(f"\n--- 比較表 ---")
print(f"{'Method':<20s} {'root':>7s} {'mirex':>7s}  SS_root SS_mirex")
print(f"{'librosa(現行)':<20s} {'0.476':>7s} {'0.414':>7s}  {'0.625':>7s} {'0.542':>7s}")
if all_r:
    ss_r = genre_scores.get('SS(弾き語り)', {}).get('root', [])
    ss_m = genre_scores.get('SS(弾き語り)', {}).get('mirex', [])
    ss_r_str = f"{np.mean(ss_r):.3f}" if ss_r else "N/A"
    ss_m_str = f"{np.mean(ss_m):.3f}" if ss_m else "N/A"
    print(f"{'CREMA(公開SOTA)':<20s} {np.mean(all_r):7.3f} {np.mean(all_m):7.3f}  {ss_r_str:>7s} {ss_m_str:>7s}")
print(f"{'SOTA参考値':<20s} {'~0.88':>7s} {'~0.82':>7s}")
