"""
ChordMini エンジンモジュール
=============================
ChordMini (BTC student + Knowledge Distillation) による
高精度コード認識。BTC fine-tuned より +3-5% の精度向上。
"""

import os
import sys
import numpy as np
import torch
from pathlib import Path

CHORDMINI_ROOT = Path(os.path.dirname(os.path.dirname(__file__))) / 'ChordMini'

# ChordMini の src を PATH に追加
if str(CHORDMINI_ROOT) not in sys.path:
    sys.path.insert(0, str(CHORDMINI_ROOT))
if str(CHORDMINI_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(CHORDMINI_ROOT / 'src'))


class ChordMiniEngine:
    """ChordMini コード認識エンジン"""
    
    def __init__(self, device=None):
        self.device = device
        self.model = None
        self.config = None
        self.mean = None
        self.std = None
        self.idx_to_chord = None
        self.chord_to_idx = None
        self._loaded = False
    
    def load(self):
        if self.model is not None:
            # Model is already loaded in memory, just move back to the target device
            try:
                self.model.to(self.device)
                self.model.eval()
                self._loaded = True
                print(f"[ChordMini] Model moved back to {self.device}")
                return
            except Exception as e:
                print(f"[ChordMini] Failed to move model back to device: {e}, will reload")
                self.model = None

        from src.utils.hparams import HParams
        from src.models import load_model
        from src.evaluation.utils.common import extract_norm_stats, extract_vocab
        from src.utils.device import get_device
        
        config_path = CHORDMINI_ROOT / 'config' / 'ChordMini.yaml'
        checkpoint_path = CHORDMINI_ROOT / 'checkpoints' / 'btc_model_best.pth'
        
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"ChordMini checkpoint not found: {checkpoint_path}")
        
        self.config = HParams.load(str(config_path))
        
        if self.device is None:
            self.device = get_device()
        
        # ダミー args
        args = type('Args', (), {'seq_len': None, 'model_type': 'BTC'})()
        
        self.model, _, _ = load_model(str(checkpoint_path), 'BTC', self.config, self.device, args)
        self.mean, self.std = extract_norm_stats(str(checkpoint_path))
        self.idx_to_chord, self.chord_to_idx = extract_vocab(str(checkpoint_path))
        
        self.model.eval()
        self._loaded = True
        
        print(f"[ChordMini] Model loaded on {self.device}, vocab={len(self.idx_to_chord)}")
    
    def unload(self):
        """GPU VRAM を解放する（モデルをCPUに移動 + キャッシュクリア。モデル自体はメモリに保持）"""
        if self.model is not None:
            try:
                self.model.cpu()
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                self._loaded = False
                print("[ChordMini] Model offloaded to CPU, VRAM freed")
            except Exception as e:
                print(f"[ChordMini] Failed to offload model to CPU: {e}")
    
    def detect_chords(self, wav_path):
        """
        音声ファイルからコード進行を検出する。
        
        Returns
        -------
        seg_starts : np.ndarray
            各コードセグメントの開始時刻 (秒)
        seg_labels : np.ndarray
            各コードセグメントのラベル
        """
        if not self._loaded:
            self.load()
        
        from src.evaluation.utils.common import extract_song_features
        from src.evaluation.utils.inference import predict_sliding_windows
        
        feature_matrix, frame_duration = extract_song_features(str(wav_path), self.config)
        
        seq_len = 108
        preds = predict_sliding_windows(
            model=self.model,
            feature_matrix=feature_matrix,
            mean=self.mean,
            std=self.std,
            seq_len=seq_len,
            batch_size=16,
            model_type='BTC',
            n_classes=len(self.chord_to_idx),
        )
        
        # フレーム予測 → セグメントに変換 (btc_engine.py と整合)
        seg_starts = []
        seg_labels = []
        prev_chord = None
        prev_start = 0.0
        
        for i, idx in enumerate(preds):
            chord = self.idx_to_chord.get(int(idx), 'N')
            t = float(i) * frame_duration
            
            if prev_chord is None:
                prev_chord = chord
                prev_start = t
                continue
            
            if chord != prev_chord:
                seg_starts.append(prev_start)
                seg_labels.append(prev_chord)
                prev_start = t
                prev_chord = chord
        
        # 最後のセグメント
        if prev_chord is not None:
            seg_starts.append(prev_start)
            seg_labels.append(prev_chord)
 
        # タイミング補正: BTC系モデルは約0.4秒遅れてコード変化を検出する
        TIMING_OFFSET = 0.40
        seg_starts_arr = np.array(seg_starts, dtype=float)
        seg_starts_arr = np.maximum(0.0, seg_starts_arr - TIMING_OFFSET)
        print(f'[ChordMini] {len(seg_labels)} chord segments, timing correction -{TIMING_OFFSET}s applied')
 
        return seg_starts_arr, np.array(seg_labels)


# --- シングルトンインスタンス ---
_chordmini_engine = None

def get_chordmini_engine():
    global _chordmini_engine
    if _chordmini_engine is None:
        _chordmini_engine = ChordMiniEngine()
    return _chordmini_engine
