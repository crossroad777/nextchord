"""
混合学習: 合成3,080曲 + Beatles 180曲 + CQTデータ拡張
=====================================================
- 合成データ = コードの「正解の形」(100%正確ラベル)
- Beatles = 実音源の「質感」
- CQT拡張 = ゲイン・ノイズ・ピッチシフトで汎化性能向上
- 同一バッチに両方が入ることで、ドメインを同時学習
"""
import sys, os, random, numpy as np
from pathlib import Path
from collections import Counter

CHORDMINI_ROOT = Path(r"D:\Music\nextchord\ChordMini")
sys.path.insert(0, str(CHORDMINI_ROOT))
sys.path.insert(0, str(CHORDMINI_ROOT / "src"))

import torch
from torch.utils.data import Dataset, DataLoader, ConcatDataset
from src.data.AudioChordDataset import AudioChordDataset, create_train_val_test_split
from src.utils.hparams import HParams
from src.utils.chords import idx2voca_chord, transpose_chord_label
from src.models import load_model
from src.utils.device import get_device

BEATLES_AUDIO = str(CHORDMINI_ROOT / "data" / "beatles" / "audio")
BEATLES_LABEL = str(CHORDMINI_ROOT / "data" / "beatles" / "chordlab")
SYNTH_AUDIO = str(CHORDMINI_ROOT / "data" / "synthetic" / "audio")
SYNTH_LABEL = str(CHORDMINI_ROOT / "data" / "synthetic" / "chordlab")
CONFIG_PATH = str(CHORDMINI_ROOT / "config" / "ChordMini.yaml")
CKPT = str(CHORDMINI_ROOT / "checkpoints" / "btc_model_best.pth")
SAVE_DIR = str(CHORDMINI_ROOT / "checkpoints" / "mixed_aug")


class CQTAugWrapper(Dataset):
    """CQTレベル拡張ラッパー (ピッチシフト+ゲイン+ノイズ)"""
    
    def __init__(self, base_dataset, indices, augment=True, pitch_shifts=None):
        self.base = base_dataset
        self.indices = list(indices)
        self.augment = augment
        
        self.items = []
        if augment and pitch_shifts:
            for idx in self.indices:
                self.items.append((idx, 0))  # original
                for ps in pitch_shifts:
                    if ps != 0:
                        self.items.append((idx, ps))
        else:
            self.items = [(idx, 0) for idx in self.indices]
    
    def __len__(self):
        return len(self.items)
    
    def __getitem__(self, i):
        orig_idx, pitch_shift = self.items[i]
        item = self.base[orig_idx]
        spectro = item['spectro'].clone()
        chord_idx = item['chord_idx'].clone()
        
        # CQTビンシフト (ピッチシフト)
        if pitch_shift != 0:
            bins_per_semitone = 2  # 24 bins/octave
            bin_shift = pitch_shift * bins_per_semitone
            shifted = torch.zeros_like(spectro)
            n_bins = spectro.shape[1]
            if bin_shift > 0:
                if bin_shift < n_bins:
                    shifted[:, bin_shift:] = spectro[:, :n_bins-bin_shift]
            else:
                if -bin_shift < n_bins:
                    shifted[:, :n_bins+bin_shift] = spectro[:, -bin_shift:]
            spectro = shifted
            
            i2c = self.base.idx_to_chord
            c2i = self.base.chord_to_idx
            new_labels = []
            for ci in chord_idx:
                chord_name = i2c.get(int(ci), 'N')
                transposed = transpose_chord_label(chord_name, pitch_shift)
                new_labels.append(c2i.get(transposed, c2i.get('N', 169)))
            chord_idx = torch.tensor(new_labels, dtype=torch.long)
        
        # ゲイン変動 + ノイズ (training only)
        if self.augment:
            gain = np.random.uniform(0.85, 1.15)
            spectro = spectro * gain
            spectro = spectro + torch.randn_like(spectro) * 0.015
        
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
    print("Mixed Training: Synthetic + Beatles + CQT Augmentation")
    print("=" * 70)
    
    # Load Beatles
    beatles_ds = AudioChordDataset(BEATLES_AUDIO, BEATLES_LABEL, config,
                                    seq_len=108, stride=54, verbose=True)
    b_train, b_val, b_test = create_train_val_test_split(
        beatles_ds, train_ratio=0.8, val_ratio=0.1, seed=42)
    
    # Load Synthetic
    synth_ds = AudioChordDataset(SYNTH_AUDIO, SYNTH_LABEL, config,
                                  seq_len=108, stride=54, verbose=True)
    s_train, s_val, s_test = create_train_val_test_split(
        synth_ds, train_ratio=0.9, val_ratio=0.05, seed=42)
    
    print(f"\nBeatles: train={len(b_train)}, val={len(b_val)}, test={len(b_test)}")
    print(f"Synth:   train={len(s_train)}, val={len(s_val)}")
    
    # Beatles: 12キー拡張 (実データは貴重なので全12転調)
    pitch_shifts = list(range(-5, 7))
    beatles_aug = CQTAugWrapper(beatles_ds, b_train, augment=True, pitch_shifts=pitch_shifts)
    
    # Synth: 拡張なし (元々全キーが含まれている。ゲイン・ノイズのみ)
    synth_aug = CQTAugWrapper(synth_ds, s_train, augment=True, pitch_shifts=None)
    
    # 混合データセット
    train_combined = ConcatDataset([beatles_aug, synth_aug])
    
    # Valは Beatles のみ (実データでの性能を測る)
    val_set = CQTAugWrapper(beatles_ds, b_val, augment=False, pitch_shifts=None)
    
    print(f"\nMixed train: {len(train_combined)} segments")
    print(f"  Beatles aug: {len(beatles_aug)} (x{len(pitch_shifts)+1} pitches)")
    print(f"  Synth:       {len(synth_aug)} (gain+noise only)")
    print(f"Val (Beatles only): {len(val_set)}")
    
    train_loader = DataLoader(train_combined, batch_size=32, shuffle=True,
                               num_workers=0, pin_memory=True)
    val_loader = DataLoader(val_set, batch_size=32, shuffle=False,
                             num_workers=0, pin_memory=True)
    
    # Load model
    args = type('A', (), {'seq_len': None, 'model_type': 'BTC'})()
    model, _, _ = load_model(CKPT, 'BTC', config, device, args)
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=50, eta_min=1e-6)
    criterion = torch.nn.CrossEntropyLoss(ignore_index=169)
    n_classes = len(beatles_ds.chord_to_idx)
    
    os.makedirs(SAVE_DIR, exist_ok=True)
    best_val_acc = 0
    patience_counter = 0
    
    for epoch in range(1, 51):
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
            
            if batch_idx % 100 == 0:
                print(f"  Ep {epoch} | {batch_idx}/{len(train_loader)} | Loss: {loss.item():.4f}")
        
        train_acc = correct / max(total, 1)
        train_loss = total_loss / len(train_loader)
        
        # Validate on Beatles only
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
            save_path = os.path.join(SAVE_DIR, "best_model.pth")
            ckpt_data = torch.load(CKPT, map_location='cpu', weights_only=False)
            ckpt_data['model'] = model.state_dict()
            ckpt_data['epoch'] = epoch
            ckpt_data['best_val_acc'] = best_val_acc
            torch.save(ckpt_data, save_path)
            marker = " *** BEST ***"
        else:
            patience_counter += 1
        
        print(f"Ep {epoch}/50 | Loss: {train_loss:.4f} | Acc: {train_acc:.4f} | "
              f"Val: {val_acc:.4f} | LR: {lr:.6f}{marker}")
        
        if patience_counter >= 15:
            print(f"Early stopping at epoch {epoch}")
            break
    
    print(f"\nBest Val Acc: {best_val_acc:.4f}")
    print(f"Saved to: {SAVE_DIR}/best_model.pth")


if __name__ == "__main__":
    main()
