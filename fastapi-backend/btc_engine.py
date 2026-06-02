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
    
    def detect_chords(self, wav_path, use_hpss=True):
        """
        音声ファイルからコード進行を検出する。

        Parameters
        ----------
        wav_path : str or Path
        use_hpss : bool
            True: HPSS で調波成分のみ抽出してから解析（Chordify式、推奨）

        Returns
        -------
        seg_starts : np.ndarray
        seg_labels : np.ndarray
        """
        if not self._loaded:
            self.load()

        # HPSS 前処理（Chordify 方式）
        if use_hpss:
            y_raw, sr_raw = librosa.load(str(wav_path), sr=22050, mono=True)
            y_harmonic, _ = librosa.effects.hpss(y_raw, margin=3.0)
            # 一時ファイルに書き出す
            import tempfile, soundfile as sf
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            sf.write(tmp.name, y_harmonic, sr_raw)
            input_path = tmp.name
            print(f'[BTC] HPSS applied → {tmp.name}')
        else:
            input_path = str(wav_path)

        # CQT 特徴量を計算
        feature, feature_per_second, song_length_second = audio_file_to_features(
            input_path, self.config
        )

        # 一時ファイル削除
        if use_hpss:
            import os as _os
            try:
                _os.unlink(tmp.name)
            except Exception:
                pass

        # 正規化
        feature = feature.T
        feature = (feature - self.mean) / self.std
        time_unit = feature_per_second
        n_timestep = self.config.model['timestep']

        # パディング
        num_pad = n_timestep - (feature.shape[0] % n_timestep)
        if num_pad == n_timestep:
            num_pad = 0
        feature = np.pad(feature, ((0, num_pad), (0, 0)), mode="constant", constant_values=0)
        num_instance = feature.shape[0] // n_timestep

        # 推論
        all_chord_indices = []
        with torch.no_grad():
            for t in range(num_instance):
                chunk = feature[n_timestep * t: n_timestep * (t + 1), :]
                chunk_tensor = torch.tensor(
                    chunk, dtype=torch.float32
                ).unsqueeze(0).to(self.device)  # [1, timestep, features]

                # self_attn_layers の出力を取得
                self_attn_output, _ = self.model.self_attn_layers(chunk_tensor)

                # SoftmaxOutputLayer で予測
                prediction, _ = self.model.output_layer(self_attn_output)
                # prediction: [1, timestep] のインデックス
                pred_np = prediction.squeeze(0).cpu().numpy()
                all_chord_indices.extend(pred_np.tolist())

        # パディング分を除去
        if num_pad > 0:
            all_chord_indices = all_chord_indices[:-num_pad]

        # フレーム → セグメント変換
        seg_starts = []
        seg_labels = []
        prev_chord = None
        prev_start = 0.0

        for i, chord_idx in enumerate(all_chord_indices):
            chord_idx = int(chord_idx)
            current_time = i * time_unit

            if prev_chord is None:
                prev_chord = chord_idx
                prev_start = current_time
                continue

            if chord_idx != prev_chord:
                seg_starts.append(prev_start)
                seg_labels.append(self.idx_to_chord[prev_chord])
                prev_start = current_time
                prev_chord = chord_idx

        # 最後のセグメント
        if prev_chord is not None:
            seg_starts.append(prev_start)
            seg_labels.append(self.idx_to_chord[prev_chord])

        # 短すぎるセグメント（0.5秒未満）を前にマージ
        if len(seg_starts) > 1:
            merged_s, merged_l = [seg_starts[0]], [seg_labels[0]]
            for i in range(1, len(seg_starts)):
                duration = (seg_starts[i] - merged_s[-1])
                if duration < 0.5:
                    continue  # 前のセグメントに吸収
                merged_s.append(seg_starts[i])
                merged_l.append(seg_labels[i])
            seg_starts, seg_labels = merged_s, merged_l

        print(f'[BTC] {len(seg_labels)} chord segments detected')

        # ============================================================
        # タイミング補正: BTC は約 0.4秒遅れてコード変化を検出する
        # (フレームベース処理の固有遅延)。0.4秒前方に補正して精度向上。
        # ============================================================
        TIMING_OFFSET = 0.40  # seconds
        seg_starts_arr = np.array(seg_starts, dtype=float)
        seg_starts_arr = np.maximum(0.0, seg_starts_arr - TIMING_OFFSET)
        print(f'[BTC] Timing correction applied: -{TIMING_OFFSET}s to all segments')

        return seg_starts_arr, np.array(seg_labels)



# --- シングルトンインスタンス（パイプライン用） ---
_btc_engine = None

def get_btc_engine():
    """グローバル BTC エンジンを取得（遅延初期化）"""
    global _btc_engine
    if _btc_engine is None:
        _btc_engine = BTCEngine(use_large_voca=True)
    return _btc_engine
