"""BTC エラー分析: どのコードで間違えるか、混同行列を作成"""
import json, numpy as np, sys, time
from pathlib import Path
from collections import defaultdict, Counter
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'D:\Music\nextchord\BTC-ISMIR19')

import torch
import mir_eval
from btc_model import BTC_model
from utils.hparams import HParams
from utils.mir_eval_modules import audio_file_to_features, idx2voca_chord

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
config = HParams.load(r"D:\Music\nextchord\BTC-ISMIR19\run_config.yaml")
config.feature['large_voca'] = True
config.model['num_chords'] = 170
model = BTC_model(config=config.model).to(device)
checkpoint = torch.load(r'D:\Music\nextchord\BTC-ISMIR19\test\btc_model_large_voca.pt', map_location=device, weights_only=False)
model.load_state_dict(checkpoint['model'])
model.eval()
mean, std = checkpoint['mean'], checkpoint['std']
idx_to_chord = idx2voca_chord()

ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")

def btc_detect(wav_path):
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
                if prev is None:
                    prev = ci; start_time = 0.0; continue
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

def simplify_chord(label):
    """コードを root:quality に簡略化"""
    if label == 'N' or label == 'X': return 'N'
    if ':' not in label: return label  # 'C' -> 'C' (= C:maj)
    root = label.split(':')[0]
    qual = label.split(':')[1].split('/')[0].split('(')[0]
    return f"{root}:{qual}"

def get_genre(stem):
    for p in stem.split('_'):
        if p.startswith('BN'): return 'BossaNova'
        if p.startswith('Funk'): return 'Funk'
        if p.startswith('Jazz'): return 'Jazz'
        if p.startswith('Rock'): return 'Rock'
        if p.startswith('SS'): return 'SS'
    return 'Unknown'

# --- 分析 ---
jams_files = sorted(ANNOTATION_DIR.glob('*_comp.jams'))

# 時間加重の混同データ
confusion = defaultdict(lambda: defaultdict(float))
quality_confusion = defaultdict(lambda: defaultdict(float))
root_confusion = defaultdict(lambda: defaultdict(float))
genre_errors = defaultdict(list)

total_duration = 0.0
correct_duration = 0.0
root_correct_duration = 0.0

# 品質ごとの精度
quality_stats = defaultdict(lambda: {'correct': 0.0, 'total': 0.0})

for i, jf in enumerate(jams_files):
    stem = jf.stem
    wav = AUDIO_DIR / f"{stem}_mic.wav"
    if not wav.exists(): continue
    ref_int, ref_lab = extract_gt(str(jf))
    if ref_int is None: continue
    
    est_int, est_lab = btc_detect(wav)
    genre = get_genre(stem)
    
    # mir_eval で区間をマージして比較
    try:
        est_int_adj, est_lab_adj = mir_eval.util.adjust_intervals(
            est_int, est_lab, ref_int.min(), ref_int.max(),
            mir_eval.chord.NO_CHORD, mir_eval.chord.NO_CHORD
        )
        intervals, ref_merged, est_merged = mir_eval.util.merge_labeled_intervals(
            ref_int, ref_lab, est_int_adj, est_lab_adj
        )
        durations = mir_eval.util.intervals_to_durations(intervals)
        
        for dur, ref_c, est_c in zip(durations, ref_merged, est_merged):
            ref_s = simplify_chord(ref_c)
            est_s = simplify_chord(est_c)
            
            # root 抽出
            ref_root = ref_s.split(':')[0] if ':' in ref_s else ref_s
            est_root = est_s.split(':')[0] if ':' in est_s else est_s
            
            # quality 抽出
            ref_qual = ref_s.split(':')[1] if ':' in ref_s else 'maj'
            est_qual = est_s.split(':')[1] if ':' in est_s else 'maj'
            
            total_duration += dur
            
            # root 正解判定
            root_match = mir_eval.chord.root(np.array([ref_c]), np.array([est_c]))[0]
            if root_match:
                root_correct_duration += dur
            
            # 完全一致（mirex レベル）
            mirex_match = mir_eval.chord.mirex(np.array([ref_c]), np.array([est_c]))[0]
            if mirex_match:
                correct_duration += dur
            
            # 品質統計
            quality_stats[ref_qual]['total'] += dur
            if mirex_match:
                quality_stats[ref_qual]['correct'] += dur
            
            # 混同データ（root ミスのみ記録）
            if not root_match and ref_root != 'N' and est_root != 'N':
                root_confusion[ref_root][est_root] += dur
            
            # quality ミスのみ（root は合ってるが quality が違う）
            if root_match and not mirex_match and ref_root != 'N':
                quality_confusion[ref_qual][est_qual] += dur
                
    except Exception as e:
        pass

# --- 結果出力 ---
print("=" * 65)
print("BTC エラー分析 (GuitarSet 180曲)")
print("=" * 65)

print(f"\n全体統計:")
print(f"  総時間: {total_duration:.0f}秒")
print(f"  Root 正答: {root_correct_duration/total_duration*100:.1f}%")
print(f"  MIREX 正答: {correct_duration/total_duration*100:.1f}%")

# --- 品質別精度 ---
print(f"\n品質別精度 (MIREX):")
print(f"{'Quality':<15s} {'Total(s)':>8s} {'Correct':>8s} {'Accuracy':>8s}")
print("-" * 45)
sorted_quals = sorted(quality_stats.items(), key=lambda x: x[1]['total'], reverse=True)
for qual, stats in sorted_quals:
    acc = stats['correct'] / stats['total'] * 100 if stats['total'] > 0 else 0
    print(f"{qual:<15s} {stats['total']:8.0f} {stats['correct']:8.0f} {acc:7.1f}%")

# --- Root 混同 Top 20 ---
print(f"\nRoot 混同 Top 20 (正解->推定, 時間加重):")
print(f"{'Ref->Est':<20s} {'Duration':>8s}")
print("-" * 30)
all_confusions = []
for ref, ests in root_confusion.items():
    for est, dur in ests.items():
        all_confusions.append((ref, est, dur))
all_confusions.sort(key=lambda x: x[2], reverse=True)
for ref, est, dur in all_confusions[:20]:
    print(f"{ref:>5s} -> {est:<10s} {dur:8.1f}s")

# --- Quality 混同 Top 15 ---
print(f"\nQuality 混同 Top 15 (Root正解, Quality誤り):")
print(f"{'Ref->Est':<25s} {'Duration':>8s}")
print("-" * 35)
all_q_conf = []
for ref_q, ests in quality_confusion.items():
    for est_q, dur in ests.items():
        all_q_conf.append((ref_q, est_q, dur))
all_q_conf.sort(key=lambda x: x[2], reverse=True)
for ref_q, est_q, dur in all_q_conf[:15]:
    print(f"{ref_q:>10s} -> {est_q:<10s} {dur:8.1f}s")
