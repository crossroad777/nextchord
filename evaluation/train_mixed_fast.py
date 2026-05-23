"""
高速混合学習: 事前抽出CQT + CQTビンシフト拡張
==============================================
npy読み込みのみ → on-the-fly CQT不要で100倍高速
"""
import sys, os, random, numpy as np
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch
from torch.utils.data import Dataset, DataLoader, ConcatDataset
from src.utils.hparams import HParams
from src.utils.chords import idx2voca_chord, transpose_chord_label, Chords, normalize_enharmonic_label
from src.utils.config_utils import get_config_value
from src.models import load_model
from src.utils.device import get_device

CONFIG_PATH = str(CHORDMINI_ROOT / "config" / "ChordMini.yaml")
CKPT = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
SAVE_DIR = str(CHORDMINI_ROOT / "checkpoints" / "mixed_aug_fast")


class PreextractedChordDataset(Dataset):
    """事前抽出CQTから読み込む高速データセット"""
    
    def __init__(self, feature_dir, label_dir, seq_len=108, stride=54, verbose=True):
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
        self._load(feature_dir, label_dir, verbose)
    
    def _load(self, feature_dir, label_dir, verbose):
        feat_files = sorted(Path(feature_dir).glob("*.npy"))
        for fp in feat_files:
            lab = Path(label_dir) / f"{fp.stem}.lab"
            if not lab.exists():
                continue
            
            feat = np.load(str(fp))
            labels = self._parse_lab(str(lab))
            song_idx = len(self.songs)
            self.songs.append({'feat': feat, 'labels': labels, 'name': fp.stem})
            
            n_frames = feat.shape[0]
            for start in range(0, max(1, n_frames - self.seq_len + 1), self.stride):
                end = min(start + self.seq_len, n_frames)
                if end - start < self.seq_len // 2:
                    continue
                self.segments.append((song_idx, start, end))
        
        if verbose:
            print(f"  Loaded {len(self.songs)} songs, {len(self.segments)} segments")
    
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
                    indices.append(idx if idx is not None else self.chord_to_idx.get('N', 169))
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
            ft = torch.nn.functional.pad(ft, (0, 0, 0, pad))
            lt = torch.nn.functional.pad(lt, (0, pad), value=169)
        
        return ft, lt, song['name']


class AugmentedWrapper(Dataset):
    """CQTビンシフト + ゲイン + ノイズ拡張"""
    
    def __init__(self, base_ds, augment=True, pitch_shifts=None):
        self.base = base_ds
        self.augment = augment
        
        # Get chord vocab from base or its underlying dataset
        ds = base_ds
        while hasattr(ds, 'dataset'):
            ds = ds.dataset
        self.idx_to_chord = ds.idx_to_chord
        self.chord_to_idx = ds.chord_to_idx
        
        self.items = []
        for i in range(len(base_ds)):
            self.items.append((i, 0))
            if augment and pitch_shifts:
                for ps in pitch_shifts:
                    if ps != 0:
                        self.items.append((i, ps))
    
    def __len__(self):
        return len(self.items)
    
    def __getitem__(self, idx):
        orig_idx, ps = self.items[idx]
        ft, lt, name = self.base[orig_idx]
        ft = ft.clone()
        lt = lt.clone()
        
        if ps != 0:
            # CQTビンシフト
            bps = 2  # bins per semitone (24 bpo / 12)
            shift = ps * bps
            shifted = torch.zeros_like(ft)
            n = ft.shape[1]
            if shift > 0 and shift < n:
                shifted[:, shift:] = ft[:, :n-shift]
            elif shift < 0 and -shift < n:
                shifted[:, :n+shift] = ft[:, -shift:]
            ft = shifted
            
            # ラベル転調
            i2c = self.idx_to_chord
            c2i = self.chord_to_idx
            new = []
            for ci in lt:
                ch = i2c.get(int(ci), 'N')
                tr = transpose_chord_label(ch, ps)
                new.append(c2i.get(tr, c2i.get('N', 169)))
            lt = torch.tensor(new, dtype=torch.long)
        
        if self.augment:
            ft = ft * np.random.uniform(0.85, 1.15)
            ft = ft + torch.randn_like(ft) * 0.015
        
        return ft, lt, name


def train():
    sys.stdout.reconfigure(encoding="utf-8")
    config = HParams.load(CONFIG_PATH)
    device = get_device()
    
    print("=" * 70)
    print("Fast Mixed Training (Pre-extracted CQT)")
    print("=" * 70)
    
    # Load datasets from pre-extracted features
    print("\nLoading Beatles...")
    beatles = PreextractedChordDataset(
        str(CHORDMINI_ROOT / "data" / "beatles" / "features"),
        str(CHORDMINI_ROOT / "data" / "beatles" / "chordlab"))
    
    print("Loading Synthetic...")
    synth = PreextractedChordDataset(
        str(CHORDMINI_ROOT / "data" / "synthetic" / "features"),
        str(CHORDMINI_ROOT / "data" / "synthetic" / "chordlab"))
    
    # Split Beatles: 80/10/10
    n_b = len(beatles.songs)
    rng = np.random.RandomState(42)
    perm = rng.permutation(n_b)
    n_train = int(n_b * 0.8)
    n_val = int(n_b * 0.1)
    train_songs = set(perm[:n_train])
    val_songs = set(perm[n_train:n_train+n_val])
    
    b_train_idx = [i for i, (si, _, _) in enumerate(beatles.segments) if si in train_songs]
    b_val_idx = [i for i, (si, _, _) in enumerate(beatles.segments) if si in val_songs]
    
    # Synth: 90% train
    n_s = len(synth.songs)
    s_perm = rng.permutation(n_s)
    s_train_songs = set(s_perm[:int(n_s * 0.9)])
    s_train_idx = [i for i, (si, _, _) in enumerate(synth.segments) if si in s_train_songs]
    
    # Create subset datasets
    from torch.utils.data import Subset
    b_train = Subset(beatles, b_train_idx)
    b_val = Subset(beatles, b_val_idx)
    s_train = Subset(synth, s_train_idx)
    
    # Augment Beatles with pitch shifts, synth with gain/noise only
    pitches = list(range(-5, 7))
    b_aug = AugmentedWrapper(b_train, augment=True, pitch_shifts=pitches)
    s_aug = AugmentedWrapper(s_train, augment=True, pitch_shifts=None)
    val_ds = AugmentedWrapper(b_val, augment=False, pitch_shifts=None)
    
    combined = ConcatDataset([b_aug, s_aug])
    
    print(f"\nBeatles train: {len(b_train)} → aug: {len(b_aug)}")
    print(f"Synth train:   {len(s_train)} → aug: {len(s_aug)}")
    print(f"Combined:      {len(combined)}")
    print(f"Val (Beatles): {len(val_ds)}")
    
    train_loader = DataLoader(combined, batch_size=32, shuffle=True,
                               num_workers=0, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=32, shuffle=False,
                             num_workers=0, pin_memory=True)
    
    # Model
    args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
    model, _, _ = load_model(CKPT, 'BTC', config, device, args)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=50, eta_min=1e-6)
    criterion = torch.nn.CrossEntropyLoss(ignore_index=169)
    n_classes = len(beatles.chord_to_idx)
    
    os.makedirs(SAVE_DIR, exist_ok=True)
    best_val_acc = 0
    patience_counter = 0
    
    for epoch in range(1, 51):
        model.train()
        total_loss, correct, total = 0, 0, 0
        
        for batch_idx, (ft, lt, _) in enumerate(train_loader):
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
            
            if batch_idx % 50 == 0:
                print(f"  Ep {epoch} | {batch_idx}/{len(train_loader)} | Loss: {loss.item():.4f}", flush=True)
        
        train_acc = correct / max(total, 1)
        train_loss = total_loss / len(train_loader)
        
        # Validate
        model.eval()
        vc, vt = 0, 0
        with torch.no_grad():
            for ft, lt, _ in val_loader:
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
            patience_counter = 0
            ckpt_data = torch.load(CKPT, map_location='cpu', weights_only=False)
            ckpt_data['model'] = model.state_dict()
            ckpt_data['epoch'] = epoch
            ckpt_data['best_val_acc'] = best_val_acc
            torch.save(ckpt_data, os.path.join(SAVE_DIR, "best_model.pth"))
            marker = " *** BEST ***"
        else:
            patience_counter += 1
        
        print(f"Ep {epoch}/50 | Loss: {train_loss:.4f} | Acc: {train_acc:.4f} | "
              f"Val: {val_acc:.4f} | LR: {lr:.6f}{marker}")
        
        if patience_counter >= 15:
            print(f"Early stopping at epoch {epoch}")
            break
    
    print(f"\nBest Val Acc: {best_val_acc:.4f}")
    print(f"Saved: {SAVE_DIR}/best_model.pth")


if __name__ == "__main__":
    train()
