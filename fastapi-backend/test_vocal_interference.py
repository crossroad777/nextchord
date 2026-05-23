"""
ボーカル干渉テスト: GuitarSet に合成ボーカルを混ぜて BTC の精度劣化を測定
=============================================================================
1. GuitarSet のギター音源 (ground truth あり)
2. ランダムな正弦波ハーモニクスでボーカル的な干渉を生成
3. raw mix vs Demucs 分離 vs ギターのみ で BTC 精度を比較

※ 本テストは「ボーカル混入が精度をどの程度下げるか」の定量測定が目的
"""

import json, numpy as np, sys, time, os
from pathlib import Path
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'D:\Music\nextchord\BTC-ISMIR19')

import torch, mir_eval, librosa, soundfile as sf

from btc_model import BTC_model
from utils.hparams import HParams
from utils.mir_eval_modules import audio_file_to_features, idx2voca_chord

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")
TMP_DIR = Path(r"D:\Music\nextchord\tmp_vocal_test")
TMP_DIR.mkdir(exist_ok=True)

# --- モデルロード ---
config = HParams.load(r"D:\Music\nextchord\BTC-ISMIR19\run_config.yaml")
config.feature['large_voca'] = True
config.model['num_chords'] = 170
model = BTC_model(config=config.model).to(device)
ckpt = torch.load(r'D:\Music\nextchord\BTC-ISMIR19\finetuned\btc_finetuned_val05_best.pt',
                   map_location=device, weights_only=False)
model.load_state_dict(ckpt['model'])
model.eval()
mean, std = ckpt['mean'], ckpt['std']
idx_to_chord = idx2voca_chord()

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
                if prev is None: prev = ci; start_time = 0.0; continue
                if ci != prev:
                    intervals.append([start_time, ct]); labels.append(idx_to_chord[prev])
                    start_time = ct; prev = ci
                if t == num_inst - 1 and i + num_pad == n_ts:
                    if start_time != ct:
                        intervals.append([start_time, ct]); labels.append(idx_to_chord[prev])
                    break
    return np.array(intervals), labels

def extract_gt(jams_path):
    with open(jams_path, 'r') as f:
        data = json.load(f)
    for ann in data['annotations']:
        if ann['namespace'] == 'chord':
            intervals = np.array([[d['time'], d['time'] + d['duration']] for d in ann['data']])
            labels = [d['value'] for d in ann['data']]
            return intervals, labels
    return None, None

def generate_vocal_noise(duration, sr=22050, seed=42):
    """ボーカル帯域 (200-4000Hz) のランダムハーモニクスを生成"""
    rng = np.random.RandomState(seed)
    t = np.arange(int(duration * sr)) / sr
    signal = np.zeros_like(t)
    # 複数のランダム周波数でボーカル的な信号を生成
    for _ in range(8):
        freq = rng.uniform(200, 800)  # 基本周波数
        for h in range(1, 5):  # ハーモニクス
            amp = rng.uniform(0.05, 0.15) / h
            phase = rng.uniform(0, 2 * np.pi)
            signal += amp * np.sin(2 * np.pi * freq * h * t + phase)
    # ゆっくりした振幅変調（自然なボーカル感）
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 0.3 * t)
    signal *= env
    return signal

def demucs_separate(wav_path, output_dir):
    """Demucs で音源分離"""
    import subprocess
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", "htdemucs",
        "-o", str(output_dir),
        str(wav_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    song_name = Path(wav_path).stem
    other_path = Path(output_dir) / "htdemucs" / song_name / "other.wav"
    return other_path if other_path.exists() else None

# --- テスト実行 ---
# SS(弾き語り) ジャンルのファイルを6曲選択
jams_files = sorted(ANNOTATION_DIR.glob('*SS*_comp.jams'))[:6]
print(f"テスト対象: {len(jams_files)} SS comp tracks")

results = {'guitar_only': [], 'with_vocal': [], 'demucs_separated': []}
vocal_ratios = [0.3, 0.5]  # ボーカル混合比率

for ratio in vocal_ratios:
    print(f"\n{'='*65}")
    print(f"ボーカル混合比率: {ratio}")
    print(f"{'='*65}")
    
    ratio_results = {'guitar_only': [], 'with_vocal': [], 'demucs_separated': []}
    
    for i, jf in enumerate(jams_files):
        stem = jf.stem
        wav = AUDIO_DIR / f"{stem}_mic.wav"
        if not wav.exists(): continue
        ref_int, ref_lab = extract_gt(str(jf))
        if ref_int is None: continue
        
        # 1. ギターのみ (ベースライン)
        try:
            est_int, est_lab = btc_detect(wav)
            scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
            ratio_results['guitar_only'].append(scores['mirex'])
            guitar_mirex = scores['mirex']
        except:
            guitar_mirex = 0
            continue
        
        # 2. ボーカル混合
        y_guitar, sr = librosa.load(str(wav), sr=22050, mono=True)
        vocal = generate_vocal_noise(len(y_guitar) / sr, sr=sr, seed=i)
        y_mix = y_guitar + ratio * vocal[:len(y_guitar)]
        y_mix = y_mix / np.max(np.abs(y_mix) + 1e-8)  # 正規化
        
        mix_path = TMP_DIR / f"{stem}_mix_{ratio}.wav"
        sf.write(str(mix_path), y_mix, sr)
        
        try:
            est_int, est_lab = btc_detect(mix_path)
            scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
            ratio_results['with_vocal'].append(scores['mirex'])
            mix_mirex = scores['mirex']
        except:
            mix_mirex = 0
        
        # 3. Demucs 分離
        try:
            other_path = demucs_separate(mix_path, TMP_DIR)
            if other_path and other_path.exists():
                est_int, est_lab = btc_detect(other_path)
                scores = mir_eval.chord.evaluate(ref_int, ref_lab, est_int, est_lab)
                ratio_results['demucs_separated'].append(scores['mirex'])
                demucs_mirex = scores['mirex']
            else:
                demucs_mirex = -1
        except Exception as e:
            demucs_mirex = -1
            print(f"  Demucs error: {e}")
        
        print(f"  [{i+1}] {stem[:35]:35s} guitar={guitar_mirex:.3f} mix={mix_mirex:.3f} demucs={demucs_mirex:.3f}")
    
    print(f"\n--- 比率 {ratio} まとめ ---")
    print(f"  ギターのみ:   mirex={np.mean(ratio_results['guitar_only']):.4f}")
    print(f"  ボーカル混合:  mirex={np.mean(ratio_results['with_vocal']):.4f} (劣化: {np.mean(ratio_results['guitar_only'])-np.mean(ratio_results['with_vocal']):+.4f})")
    if ratio_results['demucs_separated']:
        print(f"  Demucs分離:   mirex={np.mean(ratio_results['demucs_separated']):.4f} (回復: {np.mean(ratio_results['demucs_separated'])-np.mean(ratio_results['with_vocal']):+.4f})")
