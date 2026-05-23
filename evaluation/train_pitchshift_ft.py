"""
Pitch-Shift Augmented Fine-Tuning
==================================
CQTビンシフト + ラベル転調 でデータ拡張
- 各サンプルをランダムに -3 ~ +3 半音シフト
- ラベル(コードルート)も同様にシフト
- ルート音偏りの解消 + 7倍のデータ量相当
"""
import sys, os, numpy as np, random
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, Subset
from src.utils.hparams import HParams
from src.utils.chords import idx2voca_chord, Chords, normalize_enharmonic_label
from src.utils.config_utils import get_config_value
from src.models import load_model
from src.utils.device import get_device

CONFIG_PATH = str(CHORDMINI_ROOT / "config" / "ChordMini.yaml")
CKPT = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
SAVE_DIR = str(CHORDMINI_ROOT / "checkpoints" / "pitchshift_ft")

# Chord vocabulary structure: 12 roots x 14 qualities + X(168) + N(169)
N_ROOTS = 12
N_QUALITIES = 14
ROOTS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def transpose_label_idx(label_idx, semitones):
    """Transpose a chord label index by semitones"""
    if label_idx >= 168:  # X or N
        return label_idx
    root = label_idx // N_QUALITIES
    quality = label_idx % N_QUALITIES
    new_root = (root + semitones) % N_ROOTS
    return new_root * N_QUALITIES + quality


def shift_cqt_bins(cqt, semitones, bins_per_semitone=2):
    """Shift CQT bins to simulate pitch shift"""
    if semitones == 0:
        return cqt.copy()
    shift = semitones * bins_per_semitone
    shifted = np.zeros_like(cqt)
    n_bins = cqt.shape[1]
    if shift > 0 and shift < n_bins:
        shifted[:, shift:] = cqt[:, :n_bins - shift]
    elif shift < 0 and -shift < n_bins:
        shifted[:, :n_bins + shift] = cqt[:, -shift:]
    return shifted


class PitchShiftChordDataset(Dataset):
    def __init__(self, feature_dir, label_dir, seq_len=108, stride=54, augment=True):
        self.seq_len = seq_len
        self.stride = stride
        self.augment = augment
        self.idx_to_chord = idx2voca_chord()
        self.chord_to_idx = {v: k for k, v in self.idx_to_chord.items()}
        self.chord_parser = Chords()
        self.chord_parser.set_chord_mapping(self.chord_to_idx)
        
        config = HParams.load(CONFIG_PATH)
        self.hop_length = get_config_value(config, 'feature', 'hop_length', 2048)
        self.sample_rate = get_config_value(config, 'mp3', 'song_hz', 22050)
        self.frame_duration = self.hop_length / self.sample_rate
        self.bps = get_config_value(config, 'feature', 'bins_per_octave', 24) // 12
        
        self.songs = []
        self.segments = []
        
        feat_files = sorted(Path(feature_dir).glob("*.npy"))
        for fp in feat_files:
            lab = Path(label_dir) / f"{fp.stem}.lab"
            if not lab.exists(): continue
            feat = np.load(str(fp))
            labels = self._parse_lab(str(lab))
            song_idx = len(self.songs)
            self.songs.append({'feat': feat, 'labels': labels, 'name': fp.stem})
            n = feat.shape[0]
            for start in range(0, max(1, n - seq_len + 1), stride):
                end = min(start + seq_len, n)
                if end - start < seq_len // 2: continue
                self.segments.append((song_idx, start, end))
    
    def _parse_lab(self, path):
        labels = []
        with open(path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    labels.append((float(parts[0]), float(parts[1]),
                                   self.chord_parser.label_error_modify(parts[2])))
        return labels
    
    def _get_chord_indices(self, labels, start, end):
        indices = []
        for fi in range(start, end):
            t = fi * self.frame_duration
            chord = 'N'
            for s, e, lbl in labels:
                if s <= t < e:
                    chord = lbl
                    break
            if chord in self.chord_to_idx:
                indices.append(self.chord_to_idx[chord])
            else:
                norm = normalize_enharmonic_label(chord)
                if norm in self.chord_to_idx:
                    indices.append(self.chord_to_idx[norm])
                else:
                    idx = self.chord_parser.get_chord_idx(chord)
                    indices.append(idx if idx is not None else 169)
        return indices
    
    def __len__(self):
        return len(self.segments)
    
    def __getitem__(self, idx):
        song_idx, start, end = self.segments[idx]
        song = self.songs[song_idx]
        feat = song['feat'][start:end].copy()
        labels = self._get_chord_indices(song['labels'], start, end)
        
        # Pitch shift augmentation
        if self.augment:
            shift = random.choice([-3, -2, -1, 0, 0, 0, 1, 2, 3])  # bias toward 0
            if shift != 0:
                feat = shift_cqt_bins(feat, shift, self.bps)
                labels = [transpose_label_idx(l, shift) for l in labels]
        
        ft = torch.from_numpy(feat).float()
        lt = torch.tensor(labels, dtype=torch.long)
        
        if ft.shape[0] < self.seq_len:
            pad = self.seq_len - ft.shape[0]
            ft = F.pad(ft, (0, 0, 0, pad))
            lt = F.pad(lt, (0, pad), value=169)
        
        return ft, lt


def train():
    sys.stdout.reconfigure(encoding="utf-8")
    config = HParams.load(CONFIG_PATH)
    device = get_device()
    
    print("=" * 70, flush=True)
    print("Pitch-Shift Augmented Fine-Tuning", flush=True)
    print("=" * 70, flush=True)
    
    # Training with augmentation, validation without
    ds_train = PitchShiftChordDataset(
        str(CHORDMINI_ROOT / "data" / "beatles" / "features"),
        str(CHORDMINI_ROOT / "data" / "beatles" / "chordlab"),
        augment=True)
    ds_val = PitchShiftChordDataset(
        str(CHORDMINI_ROOT / "data" / "beatles" / "features"),
        str(CHORDMINI_ROOT / "data" / "beatles" / "chordlab"),
        augment=False)
    
    n = len(ds_train.songs)
    rng = np.random.RandomState(42)
    perm = rng.permutation(n)
    n_train = int(n * 0.8)
    n_val = int(n * 0.1)
    
    train_songs = set(perm[:n_train])
    val_songs = set(perm[n_train:n_train + n_val])
    
    train_idx = [i for i, (si, _, _) in enumerate(ds_train.segments) if si in train_songs]
    val_idx = [i for i, (si, _, _) in enumerate(ds_val.segments) if si in val_songs]
    
    train_ds = Subset(ds_train, train_idx)
    val_ds = Subset(ds_val, val_idx)
    
    print(f"Train: {len(train_ds)}, Val: {len(val_ds)}", flush=True)
    
    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=32, shuffle=False, num_workers=0)
    
    # Model
    args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
    model, _, _ = load_model(CKPT, 'BTC', config, device, args)
    n_classes = len(ds_train.chord_to_idx)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-5, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10, T_mult=2, eta_min=1e-6)
    criterion = nn.CrossEntropyLoss(ignore_index=169, label_smoothing=0.05)
    
    os.makedirs(SAVE_DIR, exist_ok=True)
    best_val_acc = 0
    patience = 0
    
    for epoch in range(1, 41):
        model.train()
        total_loss, correct, total = 0, 0, 0
        
        for ft, lt in train_loader:
            ft, lt = ft.to(device), lt.to(device)
            optimizer.zero_grad()
            out = model(ft)
            logits = out[0] if isinstance(out, tuple) else out
            loss = criterion(logits.reshape(-1, n_classes), lt.reshape(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            total_loss += loss.item()
            pred = logits.argmax(dim=-1)
            mask = lt != 169
            correct += (pred[mask] == lt[mask]).sum().item()
            total += mask.sum().item()
        
        train_acc = correct / max(total, 1)
        
        # Validate
        model.eval()
        vc, vt = 0, 0
        with torch.no_grad():
            for ft, lt in val_loader:
                ft, lt = ft.to(device), lt.to(device)
                out = model(ft)
                logits = out[0] if isinstance(out, tuple) else out
                pred = logits.argmax(dim=-1)
                mask = lt != 169
                vc += (pred[mask] == lt[mask]).sum().item()
                vt += mask.sum().item()
        
        val_acc = vc / max(vt, 1)
        scheduler.step()
        lr = optimizer.param_groups[0]['lr']
        
        marker = ""
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience = 0
            ckpt_data = torch.load(CKPT, map_location='cpu', weights_only=False)
            ckpt_data['model'] = model.state_dict()
            ckpt_data['epoch'] = epoch
            torch.save(ckpt_data, os.path.join(SAVE_DIR, "best_model.pth"))
            marker = " *** BEST ***"
        else:
            patience += 1
        
        print(f"Ep {epoch}/40 | Loss: {total_loss/len(train_loader):.4f} | "
              f"Acc: {train_acc:.4f} | Val: {val_acc:.4f} | LR: {lr:.6f}{marker}", flush=True)
        
        if patience >= 12:
            print(f"Early stop at epoch {epoch}", flush=True)
            break
    
    print(f"\nBest Val Acc: {best_val_acc:.4f}", flush=True)
    print(f"Saved: {SAVE_DIR}", flush=True)


if __name__ == "__main__":
    train()
