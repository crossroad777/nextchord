"""
NextChord コード認識ベースライン評価
====================================
GuitarSet の comp (伴奏) トラックを使用して、
現行パイプライン (madmom DeepChroma or librosa fallback) の
コード認識精度を mir_eval で計測する。

使用法:
    python eval_chord_baseline.py

出力:
    - 各曲の WCSR (Weighted Chord Symbol Recall)
    - 全体の平均スコア (root, thirds, triads, sevenths, majmin, mirex)
"""

import json
import sys
import time
from pathlib import Path
from collections import Counter

import numpy as np

# mir_eval
import mir_eval

# --- パス設定 ---
ANNOTATION_DIR = Path(r"D:\Music\datasets\GuitarSet\annotation")
AUDIO_DIR = Path(r"D:\Music\datasets\GuitarSet\audio_mono-mic")

# --- madmom の利用可否を確認 ---
try:
    from madmom.features.chords import DeepChromaProcessor, CNNChordFeatureProcessor
    MADMOM_AVAILABLE = True
    chroma_proc = DeepChromaProcessor()
    chord_proc = CNNChordFeatureProcessor()
    print("[EVAL] madmom DeepChroma + CNNChord: AVAILABLE")
except Exception as e:
    MADMOM_AVAILABLE = False
    print(f"[EVAL] madmom unavailable: {e}")
    print("[EVAL] Using librosa fallback")

# --- librosa フォールバック ---
import librosa


def librosa_chord_detection(wav_path: str):
    """librosa ベースのコード検出（pipeline.py と同じロジック）"""
    y, sr = librosa.load(wav_path, sr=22050, mono=True)
    tuning = librosa.estimate_tuning(y=y, sr=sr)
    
    hop_length = 2048
    chroma_cqt = librosa.feature.chroma_cqt(
        y=y, sr=sr, hop_length=hop_length, n_chroma=12, tuning=tuning
    )
    chroma_stft = librosa.feature.chroma_stft(
        y=y, sr=sr, hop_length=hop_length, n_chroma=12, tuning=tuning
    )
    chroma = (chroma_cqt + chroma_stft) / 2.0
    
    # 8種テンプレート
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    templates = {
        'maj':  np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], dtype=float),
        'min':  np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0], dtype=float),
        '7':    np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0], dtype=float),
        'min7': np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0], dtype=float),
        'maj7': np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1], dtype=float),
        'dim':  np.array([1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0], dtype=float),
        'sus4': np.array([1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0], dtype=float),
        'sus2': np.array([1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0], dtype=float),
    }
    
    chord_templates = {}
    for i, name in enumerate(note_names):
        for qual, tmpl in templates.items():
            chord_templates[f"{name}:{qual}"] = np.roll(tmpl, i)
    
    n_frames = chroma.shape[1]
    frame_duration = hop_length / sr
    
    seg_starts = []
    seg_labels = []
    prev_chord = None
    
    for f in range(n_frames):
        frame = chroma[:, f]
        if np.sum(frame) < 0.01:
            chord = "N"
        else:
            frame_norm = frame / (np.linalg.norm(frame) + 1e-8)
            best_chord = "N"
            best_score = 0.3
            for chord_name, template in chord_templates.items():
                template_norm = template / (np.linalg.norm(template) + 1e-8)
                score = np.dot(frame_norm, template_norm)
                if score > best_score:
                    best_score = score
                    best_chord = chord_name
            chord = best_chord
        
        if chord != prev_chord:
            seg_starts.append(f * frame_duration)
            seg_labels.append(chord)
            prev_chord = chord
    
    return np.array(seg_starts), np.array(seg_labels)


def madmom_chord_detection(wav_path: str):
    """madmom ベースのコード検出"""
    feats = chroma_proc(wav_path)
    result = chord_proc(feats)
    return result['start'], result['label']


def extract_ground_truth(jams_path: str):
    """JAMS ファイルからコードの Ground Truth を抽出"""
    with open(jams_path, 'r') as f:
        data = json.load(f)
    
    # namespace='chord' のアノテーションを探す（簡略版 = index 14 付近）
    for ann in data['annotations']:
        if ann['namespace'] == 'chord':
            intervals = []
            labels = []
            for d in ann['data']:
                t = d['time']
                dur = d['duration']
                val = d['value']
                intervals.append([t, t + dur])
                labels.append(val)
            return np.array(intervals), labels
    
    return None, None


def segments_to_intervals(seg_starts, seg_labels, total_duration):
    """セグメント開始時刻 -> (start, end) intervals に変換"""
    intervals = []
    labels = []
    for i in range(len(seg_starts)):
        start = seg_starts[i]
        end = seg_starts[i + 1] if i + 1 < len(seg_starts) else total_duration
        intervals.append([start, end])
        labels.append(seg_labels[i])
    return np.array(intervals), labels


def evaluate_single(jams_path: Path, wav_path: Path):
    """1曲の評価"""
    # Ground Truth
    ref_intervals, ref_labels = extract_ground_truth(str(jams_path))
    if ref_intervals is None:
        return None
    
    total_duration = ref_intervals[-1, 1]
    
    # 推定
    if MADMOM_AVAILABLE:
        seg_starts, seg_labels = madmom_chord_detection(str(wav_path))
    else:
        seg_starts, seg_labels = librosa_chord_detection(str(wav_path))
    
    est_intervals, est_labels = segments_to_intervals(seg_starts, seg_labels, total_duration)
    
    # mir_eval で評価
    try:
        scores = mir_eval.chord.evaluate(ref_intervals, ref_labels, est_intervals, est_labels)
        return scores
    except Exception as e:
        print(f"  [ERROR] mir_eval failed: {e}")
        return None


def main():
    print("=" * 70)
    print("NextChord コード認識ベースライン評価")
    print(f"Method: {'madmom DeepChroma' if MADMOM_AVAILABLE else 'librosa template matching'}")
    print("=" * 70)
    
    # comp トラックのみ（伴奏 = コード弾き）を評価
    jams_files = sorted(ANNOTATION_DIR.glob("*_comp.jams"))
    print(f"\n評価対象: {len(jams_files)} comp tracks")
    
    all_scores = {}
    score_keys = ['root', 'thirds', 'triads', 'sevenths', 'majmin', 'mirex']
    for key in score_keys:
        all_scores[key] = []
    
    t0 = time.time()
    
    for i, jams_path in enumerate(jams_files):
        # 対応する WAV ファイルを探す
        stem = jams_path.stem  # e.g. "00_BN1-129-Eb_comp"
        wav_path = AUDIO_DIR / f"{stem}_mic.wav"
        
        if not wav_path.exists():
            print(f"[{i+1}/{len(jams_files)}] SKIP: {wav_path.name} not found")
            continue
        
        t1 = time.time()
        scores = evaluate_single(jams_path, wav_path)
        dt = time.time() - t1
        
        if scores is None:
            print(f"[{i+1}/{len(jams_files)}] FAIL: {stem}")
            continue
        
        root_score = scores['root']
        mirex_score = scores['mirex']
        thirds_score = scores['thirds']
        
        for key in score_keys:
            all_scores[key].append(scores[key])
        
        print(f"[{i+1}/{len(jams_files)}] {stem[:30]:30s} "
              f"root={root_score:.3f} thirds={thirds_score:.3f} mirex={mirex_score:.3f} "
              f"({dt:.1f}s)")
    
    total_time = time.time() - t0
    
    # --- 集計 ---
    print("\n" + "=" * 70)
    print("集計結果")
    print("=" * 70)
    print(f"評価曲数: {len(all_scores['root'])}")
    print(f"処理時間: {total_time:.1f}s")
    print(f"検出方式: {'madmom DeepChroma' if MADMOM_AVAILABLE else 'librosa template matching'}")
    print()
    
    print(f"{'指標':12s} {'平均':>8s} {'中央値':>8s} {'最小':>8s} {'最大':>8s}")
    print("-" * 50)
    for key in score_keys:
        vals = all_scores[key]
        if vals:
            mean = np.mean(vals)
            median = np.median(vals)
            vmin = np.min(vals)
            vmax = np.max(vals)
            print(f"{key:12s} {mean:8.4f} {median:8.4f} {vmin:8.4f} {vmax:8.4f}")
    
    print()
    print("指標の意味:")
    print("  root    : ルート音が正しいか")
    print("  thirds  : ルート + 3度 (maj/min区別) が正しいか")
    print("  triads  : 三和音 (root + 3rd + 5th) が正しいか")
    print("  sevenths: 七和音が正しいか")
    print("  majmin  : メジャー/マイナーの区別が正しいか")
    print("  mirex   : MIREX ACE タスクの標準評価")
    print()
    print(f"SOTA参考値 (MIREX 2023): root~=0.88, thirds~=0.85, mirex~=0.82")


if __name__ == "__main__":
    main()
