"""
Focal Loss Fine-Tuning: 難しいコードに集中学習
==============================================
- Focal Loss: 簡単なサンプルの重みを下げ、難しいサンプルに集中
- クラス重み: min/dim/sus4 を強調
- Label Smoothing: 過信を防ぐ
"""
import sys, os, numpy as np
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
SAVE_DIR = str(CHORDMINI_ROOT / "checkpoints" / "focal_ft")


class FocalLoss(nn.Module):
    """Focal Loss: γ=2 で簡単な例の影響を下げる"""
    def __init__(self, gamma=2.0, weight=None, ignore_index=-100, label_smoothing=0.05):
        super().__init__()
        self.gamma = gamma
        self.weight = weight
        self.ignore_index = ignore_index
        self.label_smoothing = label_smoothing
    
    def forward(self, input, target):
        # Label smoothing cross entropy
        n_classes = input.size(-1)
        log_probs = F.log_softmax(input, dim=-1)
        
        # Create mask
        mask = target != self.ignore_index
        valid_target = target.clone()
        valid_target[~mask] = 0
        
        # One-hot with smoothing
        with torch.no_grad():
            smooth = self.label_smoothing / (n_classes - 1)
            one_hot = torch.full_like(log_probs, smooth)
            one_hot.scatter_(1, valid_target.unsqueeze(1), 1.0 - self.label_smoothing)
        
        # Cross entropy
        ce = -(one_hot * log_probs).sum(dim=-1)
        
        # Focal weight
        pt = torch.exp(-F.cross_entropy(input, valid_target, reduction='none'))
        focal_weight = (1 - pt) ** self.gamma
        
        # Class weight
        if self.weight is not None:
            w = self.weight[valid_target]
            focal_weight = focal_weight * w
        
        loss = focal_weight * ce
        loss = loss[mask].mean()
        return loss


class PreextractedChordDataset(Dataset):
    def __init__(self, feature_dir, label_dir, seq_len=108, stride=54):
        self.seq_len = seq_len
        self.stride = stride
        self.idx_to_chord = idx2voca_chord()
        self.chord_to_idx = {v: k for k, v in self.idx_to_chord.items()}
        self.chord_parser = Chords()
        self.chord_parser.set_chord_mapping(self.chord_to_idx)
        
        config = HParams.load(CONFIG_PATH)
        self.hop_length = get_config_value(config, 'feature', 'hop_length', 2048)
        self.sample_rate = get_config_value(config, 'mp3', 'song_hz', 22050)
        self.frame_duration = self.hop_length / self.sample_rate
        
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
        ft = torch.from_numpy(feat)
        lt = torch.tensor(labels, dtype=torch.long)
        if ft.shape[0] < self.seq_len:
            pad = self.seq_len - ft.shape[0]
            ft = F.pad(ft, (0, 0, 0, pad))
            lt = F.pad(lt, (0, pad), value=169)
        return ft, lt


def compute_class_weights(dataset, n_classes=170):
    """Calculate inverse frequency weights"""
    counts = np.zeros(n_classes)
    for i in range(min(len(dataset), 2000)):
        _, lt = dataset[i]
        for c in lt:
            c = int(c)
            if 0 <= c < n_classes:
                counts[c] += 1
    
    # Inverse frequency, capped
    total = counts.sum()
    weights = np.ones(n_classes)
    for i in range(n_classes):
        if counts[i] > 0:
            weights[i] = total / (n_classes * counts[i])
    weights = np.clip(weights, 0.5, 10.0)
    weights[168] = 0.1  # X
    weights[169] = 0.1  # N
    return torch.tensor(weights, dtype=torch.float32)


def train():
    sys.stdout.reconfigure(encoding="utf-8")
    config = HParams.load(CONFIG_PATH)
    device = get_device()
    
    print("=" * 70, flush=True)
    print("Focal Loss Fine-Tuning", flush=True)
    print("=" * 70, flush=True)
    
    ds = PreextractedChordDataset(
        str(CHORDMINI_ROOT / "data" / "beatles" / "features"),
        str(CHORDMINI_ROOT / "data" / "beatles" / "chordlab"))
    
    n = len(ds.songs)
    rng = np.random.RandomState(42)
    perm = rng.permutation(n)
    n_train = int(n * 0.8)
    n_val = int(n * 0.1)
    
    train_songs = set(perm[:n_train])
    val_songs = set(perm[n_train:n_train+n_val])
    
    train_idx = [i for i, (si, _, _) in enumerate(ds.segments) if si in train_songs]
    val_idx = [i for i, (si, _, _) in enumerate(ds.segments) if si in val_songs]
    
    train_ds = Subset(ds, train_idx)
    val_ds = Subset(ds, val_idx)
    
    print(f"Train: {len(train_ds)}, Val: {len(val_ds)}", flush=True)
    
    # Class weights
    print("Computing class weights...", flush=True)
    class_weights = compute_class_weights(train_ds).to(device)
    
    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=32, shuffle=False, num_workers=0)
    
    # Model
    args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
    model, _, _ = load_model(CKPT, 'BTC', config, device, args)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-5, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=30, eta_min=1e-6)
    criterion = FocalLoss(gamma=2.0, weight=class_weights, ignore_index=169, label_smoothing=0.05)
    n_classes = len(ds.chord_to_idx)
    
    os.makedirs(SAVE_DIR, exist_ok=True)
    best_val_acc = 0
    patience = 0
    
    # Save snapshots for ensemble
    for epoch in range(1, 31):
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
        lr = scheduler.get_last_lr()[0]
        
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
        
        # Save snapshots every 5 epochs for ensemble
        if epoch % 5 == 0:
            ckpt_data = torch.load(CKPT, map_location='cpu', weights_only=False)
            ckpt_data['model'] = model.state_dict()
            torch.save(ckpt_data, os.path.join(SAVE_DIR, f"snapshot_ep{epoch}.pth"))
        
        print(f"Ep {epoch}/30 | Loss: {total_loss/len(train_loader):.4f} | "
              f"Acc: {train_acc:.4f} | Val: {val_acc:.4f} | LR: {lr:.6f}{marker}", flush=True)
        
        if patience >= 10:
            print(f"Early stop at epoch {epoch}", flush=True)
            break
    
    print(f"\nBest Val Acc: {best_val_acc:.4f}", flush=True)
    print(f"Saved: {SAVE_DIR}", flush=True)


if __name__ == "__main__":
    train()
