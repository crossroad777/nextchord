"""
BTC (Bi-directional Transformer for Chords) エンジンモジュール
================================================================
NextChord パイプライン用のコード認識エンジン。
ISMIR 2019 論文のモデルを GuitarSet でファインチューニング済み。

GuitarSet 評価結果 (2026-04-26):
  Original -> Fine-tuned:
  - SS(弾き語り) mirex: 0.881 -> 0.945
  - Rock mirex:         0.868 -> 0.935
  - 全体平均 mirex:     0.757 -> 0.859
"""

import os
import sys
import numpy as np
import torch
import librosa

# BTC モジュールのパスを追加
BTC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'BTC-ISMIR19')
if BTC_DIR not in sys.path:
    sys.path.insert(0, BTC_DIR)

from btc_model import BTC_model
from utils.hparams import HParams
from utils.mir_eval_modules import audio_file_to_features, idx2chord, idx2voca_chord


class BTCEngine:
    """BTC コード認識エンジン"""
    
    def __init__(self, use_large_voca=True, device=None):
        """
        Parameters
        ----------
        use_large_voca : bool
            True: 170クラス (maj/min/7th/dim/aug/sus等), False: 25クラス (maj/min + N)
        device : torch.device or None
            None の場合は自動検出 (CUDA > CPU)
        """
        # faster-whisper (CTranslate2) と PyTorch CUDA は同一プロセスで競合する
        # (cudnnGetLibConfig Error code 127)
        # BTC は CPU でも 2-3 秒で推論可能なので CPU を強制使用
        self.device = device or torch.device("cpu")
        self.use_large_voca = use_large_voca
        self.model = None
        self.config = None
        self.mean = None
        self.std = None
        self.idx_to_chord = None
        self._loaded = False
    
    def load(self):
        """モデルをロード（遅延初期化）
        
        優先順位:
          1. ファインチューニング済み重み (mirex=0.859)
          2. オリジナル重み (mirex=0.757) ← フォールバック
        """
        if self._loaded:
            return
        
        config_path = os.path.join(BTC_DIR, 'run_config.yaml')
        self.config = HParams.load(config_path)
        
        if self.use_large_voca:
            self.config.feature['large_voca'] = True
            self.config.model['num_chords'] = 170
            # ファインチューニング済みモデルを優先
            finetuned_file = os.path.join(BTC_DIR, 'finetuned', 'btc_finetuned_val05_best.pt')
            original_file = os.path.join(BTC_DIR, 'test', 'btc_model_large_voca.pt')
            if os.path.isfile(finetuned_file):
                model_file = finetuned_file
                model_label = "fine-tuned (mirex=0.859)"
            else:
                model_file = original_file
                model_label = "original (mirex=0.757)"
            self.idx_to_chord = idx2voca_chord()
        else:
            model_file = os.path.join(BTC_DIR, 'test', 'btc_model.pt')
            model_label = "majmin (25)"
            self.idx_to_chord = idx2chord
        
        self.model = BTC_model(config=self.config.model).to(self.device)
        
        checkpoint = torch.load(model_file, map_location=self.device, weights_only=False)
        self.mean = checkpoint['mean']
        self.std = checkpoint['std']
        self.model.load_state_dict(checkpoint['model'])
        self.model.eval()
        self._loaded = True
        
        print(f"[BTC] Model loaded: {model_label} on {self.device}")
    
    def detect_chords(self, wav_path):
        """
        音声ファイルからコード進行を検出する。
        
        Parameters
        ----------
        wav_path : str or Path
            WAV/MP3 ファイルパス
        
        Returns
        -------
        seg_starts : np.ndarray
            各コードセグメントの開始時刻 (秒)
        seg_labels : np.ndarray
            各コードセグメントのラベル (例: 'C', 'A:min', 'G:7')
        """
        if not self._loaded:
            self.load()
        
        # CQT 特徴量を計算
        feature, feature_per_second, song_length_second = audio_file_to_features(
            str(wav_path), self.config
        )
        
        # 正規化
        feature = feature.T
        feature = (feature - self.mean) / self.std
        time_unit = feature_per_second
        n_timestep = self.config.model['timestep']
        
        # パディング
        num_pad = n_timestep - (feature.shape[0] % n_timestep)
        feature = np.pad(feature, ((0, num_pad), (0, 0)), mode="constant", constant_values=0)
        num_instance = feature.shape[0] // n_timestep
        
        # 推論（確信度付き）
        seg_starts = []
        seg_labels = []
        start_time = 0.0
        
        with torch.no_grad():
            feat_tensor = torch.tensor(feature, dtype=torch.float32).unsqueeze(0).to(self.device)
            prev_chord = None
            prev_conf = 0.0
            
            # 確信度を取得するために logits -> softmax を直接計算
            for t in range(num_instance):
                chunk = feat_tensor[:, n_timestep * t:n_timestep * (t + 1), :]
                self_attn_output, _ = self.model.self_attn_layers(chunk)
                # output_layer は predictions, second を返すが、確信度が必要
                # output_projection を直接呼んで logits -> softmax を再計算
                logits = self.model.output_layer.output_projection(
                    self.model.output_layer.lstm(self_attn_output)[0]
                    if hasattr(self.model.output_layer, 'lstm')
                    else self_attn_output
                )
                probs = torch.softmax(logits.squeeze(0), dim=-1)  # [timestep, num_chords]
                
                for i in range(n_timestep):
                    current_time = time_unit * (n_timestep * t + i)
                    
                    frame_probs = probs[i]
                    conf, chord_idx_t = torch.max(frame_probs, dim=-1)
                    chord_idx = chord_idx_t.item()
                    confidence = conf.item()
                    
                    # 確信度が低い場合は N (no chord) として扱う
                    if confidence < 0.3:
                        chord_idx = 0  # N.C. に相当するインデックス
                    
                    if prev_chord is None:
                        prev_chord = chord_idx
                        prev_conf = confidence
                        start_time = 0.0
                        continue
                    
                    if chord_idx != prev_chord:
                        seg_starts.append(start_time)
                        seg_labels.append(self.idx_to_chord[prev_chord])
                        start_time = current_time
                        prev_chord = chord_idx
                        prev_conf = confidence
                    
                    # 最後のフレーム
                    if t == num_instance - 1 and i + num_pad == n_timestep:
                        if start_time != current_time:
                            seg_starts.append(start_time)
                            seg_labels.append(self.idx_to_chord[prev_chord])
                        break
        
        return np.array(seg_starts), np.array(seg_labels)


# --- シングルトンインスタンス（パイプライン用） ---
_btc_engine = None

def get_btc_engine():
    """グローバル BTC エンジンを取得（遅延初期化）"""
    global _btc_engine
    if _btc_engine is None:
        _btc_engine = BTCEngine(use_large_voca=True)
    return _btc_engine
