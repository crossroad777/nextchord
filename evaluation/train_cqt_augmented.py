"""
Beatles FT + CQTレベルデータ拡張 (rubberband不要)
==================================================
論文§8.6.7の手法: ゲイン変動・ノイズ・周波数シフトをCQTスペクトル上で実施
rubberband不要。CQTのビンをシフトするだけでピッチシフトと同等の効果。
"""
import sys, os, shutil, subprocess, json
from pathlib import Path

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch, numpy as np
from torch.utils.data import Dataset, DataLoader, Subset
from src.data.AudioChordDataset import AudioChordDataset, create_train_val_test_split
from src.utils.hparams import HParams
from src.utils.chords import idx2voca_chord, transpose_chord_label
from src.models import load_model
from src.utils.device import get_device
from src.training.continual_learning_trainer import ContinualLearningTrainer

AUDIO = str(CHORDMINI_ROOT / "data" / "beatles" / "audio")
LABEL = str(CHORDMINI_ROOT / "data" / "beatles" / "chordlab")
CONFIG_PATH = str(CHORDMINI_ROOT / "config" / "ChordMini.yaml")
CKPT = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
SAVE_DIR = str(CHORDMINI_ROOT / "checkpoints" / "beatles_cqt_aug")


class CQTAugmentedDataset(Dataset):
    """CQTレベルでのデータ拡張ラッパー"""
    
    def __init__(self, base_dataset, indices, augment=True,
                 gain_range=(0.85, 1.15), noise_std=0.015,
                 freq_shift_range=(-2, 2), freq_shift_prob=0.3):
        self.base = base_dataset
        self.indices = list(indices)
        self.augment = augment
        self.gain_range = gain_range
        self.noise_std = noise_std
        self.freq_shift_range = freq_shift_range
        self.freq_shift_prob = freq_shift_prob
        
        # ピッチシフト拡張: 各サンプルに対し-5~+6半音のコピーを追加
        self.augmented = []
        if augment:
            bins_per_semitone = 2  # 24 bins/octave ÷ 12 = 2 bins/semitone
            for idx in self.indices:
                # Original
                self.augmented.append((idx, 0))
                # Pitch shifts
                for shift in range(-5, 7):
                    if shift == 0: continue
                    self.augmented.append((idx, shift))
        else:
            self.augmented = [(idx, 0) for idx in self.indices]
    
    def __len__(self):
        return len(self.augmented)
    
    def __getitem__(self, i):
        orig_idx, pitch_shift = self.augmented[i]
        item = self.base[orig_idx]
        spectro = item['spectro'].clone()
        chord_idx = item['chord_idx'].clone()
        
        bins_per_semitone = 2  # 24 bins/octave
        
        # 1. CQTビンシフト (ピッチシフト相当)
        if pitch_shift != 0:
            bin_shift = pitch_shift * bins_per_semitone
            shifted = torch.zeros_like(spectro)
            n_bins = spectro.shape[1]
            
            if bin_shift > 0:
                shifted[:, bin_shift:] = spectro[:, :n_bins-bin_shift]
            else:
                shifted[:, :n_bins+bin_shift] = spectro[:, -bin_shift:]
            
            spectro = shifted
            
            # コードラベルも転調
            i2c = self.base.idx_to_chord
            c2i = self.base.chord_to_idx
            new_labels = []
            for ci in chord_idx:
                ci_int = int(ci)
                chord_name = i2c.get(ci_int, 'N')
                transposed = transpose_chord_label(chord_name, pitch_shift)
                new_idx = c2i.get(transposed, c2i.get('N', 169))
                new_labels.append(new_idx)
            chord_idx = torch.tensor(new_labels, dtype=torch.long)
        
        # 2. ゲイン変動
        if self.augment:
            gain = np.random.uniform(*self.gain_range)
            spectro = spectro * gain
        
        # 3. ガウスノイズ
        if self.augment:
            noise = torch.randn_like(spectro) * self.noise_std
            spectro = spectro + noise
        
        return {
            'spectro': spectro,
            'chord_idx': chord_idx,
            'song_id': item['song_id'],
            'start_frame': item['start_frame'],
            'end_frame': item['end_frame'],
            'pitch_shift': pitch_shift,
        }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    config = HParams.load(CONFIG_PATH)
    device = get_device()
    
    print("=" * 70)
    print("Beatles FT + CQT-Level Augmentation")
    print("  Gain: 0.85-1.15, Noise: σ=0.015, Pitch: -5~+6 semitones")
    print("=" * 70)
    
    # Load dataset
    dataset = AudioChordDataset(AUDIO, LABEL, config, seq_len=108, stride=54)
    train_idx, val_idx, test_idx = create_train_val_test_split(
        dataset, train_ratio=0.8, val_ratio=0.1, seed=42)
    
    print(f"Split: train={len(train_idx)}, val={len(val_idx)}, test={len(test_idx)}")
    
    # Augmented training dataset
    aug_train = CQTAugmentedDataset(dataset, train_idx, augment=True)
    val_set = CQTAugmentedDataset(dataset, val_idx, augment=False)
    
    print(f"Augmented train: {len(aug_train)} segments (12x pitch + gain + noise)")
    print(f"Val: {len(val_set)} segments")
    
    train_loader = DataLoader(aug_train, batch_size=16, shuffle=True,
                               num_workers=0, pin_memory=True)
    val_loader = DataLoader(val_set, batch_size=16, shuffle=False,
                             num_workers=0, pin_memory=True)
    
    # Load model
    args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
    model, _, _ = load_model(CKPT, 'BTC', config, device, args)
    
    # Optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=50, eta_min=1e-6)
    
    # Training
    os.makedirs(SAVE_DIR, exist_ok=True)
    best_val_acc = 0
    patience = 15
    patience_counter = 0
    
    n_classes = len(dataset.chord_to_idx)
    criterion = torch.nn.CrossEntropyLoss(ignore_index=169)
    
    for epoch in range(1, 51):
        # Train
        model.train()
        total_loss, correct, total = 0, 0, 0
        for batch_idx, batch in enumerate(train_loader):
            spectro = batch['spectro'].to(device)
            labels = batch['chord_idx'].to(device)
            
            optimizer.zero_grad()
            output = model(spectro)
            logits = output[0] if isinstance(output, tuple) else output
            
            loss = criterion(logits.reshape(-1, n_classes), labels.reshape(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            
            total_loss += loss.item()
            pred = logits.argmax(dim=-1)
            mask = labels != 169
            correct += (pred[mask] == labels[mask]).sum().item()
            total += mask.sum().item()
            
            if batch_idx % 50 == 0:
                print(f"  Epoch {epoch} | Batch {batch_idx}/{len(train_loader)} | Loss: {loss.item():.4f}")
        
        train_acc = correct / max(total, 1)
        train_loss = total_loss / len(train_loader)
        
        # Validate
        model.eval()
        val_correct, val_total = 0, 0
        with torch.no_grad():
            for batch in val_loader:
                spectro = batch['spectro'].to(device)
                labels = batch['chord_idx'].to(device)
                output = model(spectro)
                logits = output[0] if isinstance(output, tuple) else output
                pred = logits.argmax(dim=-1)
                mask = labels != 169
                val_correct += (pred[mask] == labels[mask]).sum().item()
                val_total += mask.sum().item()
        
        val_acc = val_correct / max(val_total, 1)
        scheduler.step()
        lr = scheduler.get_last_lr()[0]
        
        marker = ""
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience_counter = 0
            # Save best
            save_path = os.path.join(SAVE_DIR, "best_model.pth")
            ckpt_data = torch.load(CKPT, map_location='cpu', weights_only=False)
            ckpt_data['model'] = model.state_dict()
            ckpt_data['optimizer'] = optimizer.state_dict()
            ckpt_data['epoch'] = epoch
            ckpt_data['best_val_acc'] = best_val_acc
            torch.save(ckpt_data, save_path)
            marker = " *** BEST ***"
        else:
            patience_counter += 1
        
        print(f"Epoch {epoch}/50 | Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.4f} | "
              f"Val Acc: {val_acc:.4f} | LR: {lr:.6f}{marker}")
        
        if patience_counter >= patience:
            print(f"Early stopping at epoch {epoch}")
            break
    
    print(f"\nBest Val Acc: {best_val_acc:.4f}")
    print(f"Saved to: {SAVE_DIR}/best_model.pth")


if __name__ == "__main__":
    main()
