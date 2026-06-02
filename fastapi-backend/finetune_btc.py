"""
BTC ファインチューニング on GuitarSet
=====================================
- Leave-one-player-out (6 players: 00-05)
- 学習済み重み (large_voca) をベースにファインチューニング
- GuitarSet の JAMS アノテーションを BTC の chord index に変換
- 低い学習率 (1e-5) で過学習を避ける

使用法:
    python finetune_btc.py --val_player 05
"""

import os, sys, json, time, argparse
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'D:\Music\nextchord\BTC-ISMIR19')

import torch
import torch.nn as nn
from torch import optim
from torch.utils.data import Dataset, DataLoader
from pathlib import Path

import librosa
import mir_eval

from btc_model import BTC_model
from utils.hparams import HParams
from utils.mir_eval_modules import idx2voca_chord

# --- コード語彙マッピング ---
root_list = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
quality_list = ['min', 'maj', 'dim', 'aug', 'min6', 'maj6', 'min7', 'minmaj7', 'maj7', '7', 'dim7', 'hdim7', 'sus2', 'sus4']

def chord_label_to_idx(label):
    """JAMS のコードラベルを BTC の large_voca インデックスに変換"""
    if label == 'N' or label == 'X':
        return 169  # N = no chord
    
    if ':' not in label:
        # 'C' -> C:maj -> idx
        root = label
        quality = 'maj'
    else:
        parts = label.split(':')
        root = parts[0]
        quality = parts[1].split('/')[0].split('(')[0]  # スラッシュコードと拡張を除去
    
    # enharmonic normalization
    enharmonic = {'Db': 'C#', 'Eb': 'D#', 'Fb': 'E', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#', 'Cb': 'B'}
    if root in enharmonic:
        root = enharmonic[root]
    
    if root not in root_list:
        return 169
    
    root_idx = root_list.index(root)
    
    if quality not in quality_list:
        # 近いものにマップ
        if quality in ['', 'maj']:
            quality = 'maj'
        elif quality.startswith('min'):
            quality = 'min'
        else:
            quality = 'maj'
    
    qual_idx = quality_list.index(quality)
    return root_idx * 14 + qual_idx


class GuitarSetChordDataset(Dataset):
    """GuitarSet の comp トラックを BTC 学習用に変換"""
    
    def __init__(self, config, annotation_dir, audio_dir, player_ids, timestep=108):
        self.config = config
        self.timestep = timestep
        self.instances = []  # (feature_chunk, chord_labels)
        
        annotation_dir = Path(annotation_dir)
        audio_dir = Path(audio_dir)
        
        jams_files = sorted(annotation_dir.glob('*_comp.jams'))
        
        for jf in jams_files:
            stem = jf.stem
            player_id = stem[:2]
            if player_id not in player_ids:
                continue
            
            wav = audio_dir / f"{stem}_mic.wav"
            if not wav.exists():
                continue
            
            # Ground Truth 読み込み
            with open(jf, 'r') as f:
                data = json.load(f)
            
            gt_intervals, gt_labels = None, None
            for ann in data['annotations']:
                if ann['namespace'] == 'chord':
                    gt_intervals = []
                    gt_labels = []
                    for d in ann['data']:
                        gt_intervals.append([d['time'], d['time'] + d['duration']])
                        gt_labels.append(d['value'])
                    gt_intervals = np.array(gt_intervals)
                    break
            
            if gt_intervals is None:
                continue
            
            # CQT 特徴量を計算
            y, sr = librosa.load(str(wav), sr=config.mp3['song_hz'], mono=True)
            feature = librosa.cqt(y, sr=sr,
                                  n_bins=config.feature['n_bins'],
                                  bins_per_octave=config.feature['bins_per_octave'],
                                  hop_length=config.feature['hop_length'])
            feature = np.log(np.abs(feature) + 1e-6)  # log magnitude
            
            # フレームごとのコードラベルを生成
            n_frames = feature.shape[1]
            hop_sec = config.feature['hop_length'] / config.mp3['song_hz']
            
            frame_chords = []
            for f in range(n_frames):
                t = f * hop_sec
                # この時刻のコードを探す
                chord_idx = 169  # N
                for j, (interval, label) in enumerate(zip(gt_intervals, gt_labels)):
                    if interval[0] <= t < interval[1]:
                        chord_idx = chord_label_to_idx(label)
                        break
                frame_chords.append(chord_idx)
            
            frame_chords = np.array(frame_chords)
            
            # timestep ごとにチャンク化
            n_chunks = n_frames // timestep
            for c in range(n_chunks):
                feat_chunk = feature[:, c * timestep:(c + 1) * timestep]  # (144, timestep)
                chord_chunk = frame_chords[c * timestep:(c + 1) * timestep]  # (timestep,)
                self.instances.append((feat_chunk, chord_chunk))
        
        print(f"[GuitarSetChordDataset] Players: {player_ids}, Songs: {len([jf for jf in jams_files if jf.stem[:2] in player_ids])}, Instances: {len(self.instances)}")
    
    def __len__(self):
        return len(self.instances)
    
    def __getitem__(self, idx):
        feat, chord = self.instances[idx]
        return {
            'feature': feat.astype(np.float32),  # (144, timestep)
            'chord': chord.astype(np.int64),      # (timestep,)
        }


def collate_fn(batch):
    features = torch.stack([torch.tensor(b['feature']) for b in batch])  # (B, 144, T)
    chords = torch.cat([torch.tensor(b['chord']) for b in batch])  # (B*T,)
    return features, chords


def evaluate_on_guitarset(model, config, mean, std, device, player_ids):
    """GuitarSet で評価（曲単位、mir_eval）"""
    annotation_dir = Path(r"D:\Music\datasets\GuitarSet\annotation")
    audio_dir = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")
    idx_to_chord = idx2voca_chord()
    
    from utils.mir_eval_modules import audio_file_to_features
    
    jams_files = sorted(annotation_dir.glob('*_comp.jams'))
    scores_list = {'root': [], 'thirds': [], 'mirex': []}
    
    for jf in jams_files:
        stem = jf.stem
        if stem[:2] not in player_ids:
            continue
        wav = audio_dir / f"{stem}_mic.wav"
        if not wav.exists():
            continue
        
        # GT
        with open(jf, 'r') as f:
            data = json.load(f)
        ref_int, ref_lab = None, None
        for ann in data['annotations']:
            if ann['namespace'] == 'chord':
                ref_int = np.array([[d['time'], d['time'] + d['duration']] for d in ann['data']])
                ref_lab = [d['value'] for d in ann['data']]
                break
        if ref_int is None:
            continue
        
        # BTC 推論
        feature, fps, dur = audio_file_to_features(str(wav), config)
        feature = feature.T
        feature = (feature - mean) / std
        time_unit = fps
        n_ts = config.model['timestep']
        num_pad = n_ts - (feature.shape[0] % n_ts)
        feature = np.pad(feature, ((0, num_pad), (0, 0)), mode="constant", constant_values=0)
        num_inst = feature.shape[0] // n_ts
        
        est_intervals, est_labels = [], []
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
                        est_intervals.append([start_time, ct])
                        est_labels.append(idx_to_chord[prev])
                        start_time = ct; prev = ci
                    if t == num_inst - 1 and i + num_pad == n_ts:
                        if start_time != ct:
                            est_intervals.append([start_time, ct])
                            est_labels.append(idx_to_chord[prev])
                        break
        
        if not est_intervals:
            continue
        
        try:
            scores = mir_eval.chord.evaluate(ref_int, ref_lab, np.array(est_intervals), est_labels)
            for k in scores_list:
                scores_list[k].append(scores[k])
        except:
            pass
    
    return {k: np.mean(v) for k, v in scores_list.items() if v}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--val_player', type=str, default='05', help='Validation player ID (00-05)')
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--lr', type=float, default=1e-5, help='Learning rate (low for fine-tuning)')
    parser.add_argument('--batch_size', type=int, default=16)
    args = parser.parse_args()
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    
    # Config
    config = HParams.load(r"D:\Music\nextchord\BTC-ISMIR19\run_config.yaml")
    config.feature['large_voca'] = True
    config.model['num_chords'] = 170
    
    # Load pretrained model
    model = BTC_model(config=config.model).to(device)
    ckpt = torch.load(r'D:\Music\nextchord\BTC-ISMIR19\test\btc_model_large_voca.pt',
                       map_location=device, weights_only=False)
    model.load_state_dict(ckpt['model'])
    pretrained_mean = ckpt['mean']
    pretrained_std = ckpt['std']
    print(f"Pretrained model loaded (mean={pretrained_mean:.4f}, std={pretrained_std:.4f})")
    
    # Player split
    all_players = ['00', '01', '02', '03', '04', '05']
    val_player = args.val_player
    train_players = [p for p in all_players if p != val_player]
    print(f"Train players: {train_players}, Val player: {val_player}")
    
    # Dataset
    annotation_dir = r"D:\Music\datasets\GuitarSet\annotation"
    audio_dir = r"D:\Music\datasets\GuitarSet\audio_mono-mic"
    
    train_dataset = GuitarSetChordDataset(config, annotation_dir, audio_dir, train_players)
    val_dataset = GuitarSetChordDataset(config, annotation_dir, audio_dir, [val_player])
    
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, collate_fn=collate_fn)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, collate_fn=collate_fn)
    
    # Compute GuitarSet mean/std
    all_feats = []
    for feat, _ in train_loader:
        all_feats.append(feat.mean().item())
    gs_mean = np.mean(all_feats)
    # Use pretrained normalization for stability
    mean = pretrained_mean
    std = pretrained_std
    print(f"Using pretrained normalization (mean={mean:.4f}, std={std:.4f})")
    
    # Evaluate baseline (before fine-tuning)
    model.eval()
    baseline_scores = evaluate_on_guitarset(model, config, mean, std, device, [val_player])
    print(f"\n[BASELINE] Val player {val_player}: root={baseline_scores.get('root', 0):.4f}, mirex={baseline_scores.get('mirex', 0):.4f}")
    
    # Optimizer (low LR for fine-tuning)
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=3)
    
    # Save dir
    save_dir = Path(r"D:\Music\nextchord\BTC-ISMIR19\finetuned")
    save_dir.mkdir(exist_ok=True)
    
    best_mirex = baseline_scores.get('mirex', 0)
    best_epoch = -1
    
    print(f"\n{'='*65}")
    print(f"Fine-tuning BTC on GuitarSet (val_player={val_player})")
    print(f"Epochs: {args.epochs}, LR: {args.lr}, Batch: {args.batch_size}")
    print(f"{'='*65}")
    
    for epoch in range(args.epochs):
        # --- Training ---
        model.train()
        train_losses = []
        train_correct = 0
        train_total = 0
        
        for features, chords in train_loader:
            features = features.to(device)  # (B, 144, T)
            chords = chords.to(device)      # (B*T,)
            
            # Normalize
            features = (features - mean) / std
            
            # BTC expects (B, T, 144)
            features = features.permute(0, 2, 1)
            
            optimizer.zero_grad()
            prediction, loss, weights, second = model(features, chords)
            
            train_correct += (prediction == chords).sum().item()
            train_total += chords.size(0)
            train_losses.append(loss.item())
            
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        
        train_acc = train_correct / train_total if train_total > 0 else 0
        train_loss = np.mean(train_losses)
        
        # --- Validation (frame-level) ---
        model.eval()
        val_correct = 0
        val_total = 0
        val_losses = []
        
        with torch.no_grad():
            for features, chords in val_loader:
                features = features.to(device)
                chords = chords.to(device)
                features = (features - mean) / std
                features = features.permute(0, 2, 1)
                prediction, loss, weights, second = model(features, chords)
                val_correct += (prediction == chords).sum().item()
                val_total += chords.size(0)
                val_losses.append(loss.item())
        
        val_acc = val_correct / val_total if val_total > 0 else 0
        val_loss = np.mean(val_losses)
        scheduler.step(val_loss)
        
        # --- mir_eval evaluation (every 5 epochs or last) ---
        if (epoch + 1) % 5 == 0 or epoch == args.epochs - 1 or epoch < 3:
            scores = evaluate_on_guitarset(model, config, mean, std, device, [val_player])
            mirex = scores.get('mirex', 0)
            root = scores.get('root', 0)
            
            improved = ""
            if mirex > best_mirex:
                best_mirex = mirex
                best_epoch = epoch + 1
                improved = " *** BEST ***"
                # Save best model
                torch.save({
                    'model': model.state_dict(),
                    'mean': mean,
                    'std': std,
                    'epoch': epoch + 1,
                    'mirex': mirex,
                    'root': root,
                }, save_dir / f'btc_finetuned_val{val_player}_best.pt')
            
            print(f"Epoch {epoch+1:3d}/{args.epochs} | "
                  f"loss={train_loss:.4f}/{val_loss:.4f} | "
                  f"acc={train_acc:.3f}/{val_acc:.3f} | "
                  f"root={root:.4f} mirex={mirex:.4f}{improved}")
        else:
            print(f"Epoch {epoch+1:3d}/{args.epochs} | "
                  f"loss={train_loss:.4f}/{val_loss:.4f} | "
                  f"acc={train_acc:.3f}/{val_acc:.3f}")
    
    print(f"\n{'='*65}")
    print(f"Fine-tuning complete!")
    print(f"Best mirex: {best_mirex:.4f} at epoch {best_epoch}")
    print(f"Baseline mirex: {baseline_scores.get('mirex', 0):.4f}")
    print(f"Improvement: {best_mirex - baseline_scores.get('mirex', 0):+.4f}")
    print(f"Model saved: {save_dir / f'btc_finetuned_val{val_player}_best.pt'}")


if __name__ == "__main__":
    main()
