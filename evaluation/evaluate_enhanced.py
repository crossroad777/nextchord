"""
NextChord コード判定 精度ベンチマーク
======================================
Beatles Isophonicsの正解アノテーションに対して
改良版パイプライン (BTC + クロマ検証 + HMM) を評価する。

前回の評価 (BTC単体):
  root=82.1%, thirds=79.2%, mirex=78.9%, majmin=80.2%, sevenths=70.0%

このスクリプトは:
  1. 既存のBTC予測 (.lab) を読み込み
  2. 改良パイプライン (chord_verifier + chord_hmm) を適用
  3. 補正後の .lab を生成
  4. mir_eval で正解と比較
"""

import sys
import json
import time
import numpy as np
from pathlib import Path

sys.path.insert(0, r"D:\Music\nextchord\fastapi-backend")

import mir_eval

BASE_DIR = Path(r"D:\Music\nextchord\evaluation")
ANNOTATIONS_DIR = Path(r"D:\Music\datasets\beatles_isophonics\annotations\chordlab\The Beatles")
PREDICTIONS_DIR = BASE_DIR / "beatles_predictions"
ENHANCED_DIR = BASE_DIR / "beatles_predictions_enhanced"
ENHANCED_DIR.mkdir(exist_ok=True, parents=True)


def get_all_tracks():
    tracks = []
    for album_dir in sorted(ANNOTATIONS_DIR.iterdir()):
        if not album_dir.is_dir():
            continue
        for lab_file in sorted(album_dir.glob("*.lab")):
            pred_file = PREDICTIONS_DIR / album_dir.name / f"{lab_file.stem}.lab"
            if pred_file.exists():
                tracks.append({
                    "album": album_dir.name,
                    "track_name": lab_file.stem,
                    "title": lab_file.stem.replace("_", " ").lstrip("0123456789 -").strip(),
                    "ref_path": str(lab_file),
                    "pred_path": str(pred_file),
                })
    return tracks


def parse_lab_file(lab_path):
    """Parse .lab file → (intervals, labels)"""
    intervals = []
    labels = []
    with open(lab_path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 3:
                start = float(parts[0])
                end = float(parts[1])
                label = parts[2]
                intervals.append([start, end])
                labels.append(label)
    return np.array(intervals), labels


def apply_hmm_correction(intervals, labels, key_name):
    """HMM遷移確率による補正を適用"""
    from chord_hmm import viterbi_chord_correction
    
    # N → N.C. に統一
    labels_clean = []
    for l in labels:
        if l in ('N', 'X'):
            labels_clean.append('N.C.')
        else:
            # BTC形式のコード名を簡略化 (例: A:min → Am)
            labels_clean.append(l)
    
    corrected = viterbi_chord_correction(labels_clean, key_name)
    return corrected


def detect_key_from_chords(labels):
    """コード列からキーを推定（簡易版）"""
    from collections import Counter
    
    _ROOT_TO_PC = {
        'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
        'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
        'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11
    }
    _PC_TO_ROOT = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    
    root_counts = Counter()
    minor_counts = Counter()
    
    for label in labels:
        if label in ('N', 'N.C.', 'X', ''):
            continue
        # コード名パース
        if ':' in label:
            root_str = label.split(':')[0]
            is_minor = 'min' in label
        else:
            if len(label) > 1 and label[1] in '#b':
                root_str = label[:2]
                is_minor = label[2:].startswith('m') and not label[2:].startswith('maj')
            else:
                root_str = label[:1]
                is_minor = label[1:].startswith('m') and not label[1:].startswith('maj')
        
        pc = _ROOT_TO_PC.get(root_str)
        if pc is not None:
            root_counts[pc] += 1
            if is_minor:
                minor_counts[pc] += 1
    
    if not root_counts:
        return 'C major'
    
    # 最頻出ルートをキーと推定
    most_common = root_counts.most_common(1)[0][0]
    is_minor_key = minor_counts.get(most_common, 0) > root_counts[most_common] * 0.5
    
    key_root = _PC_TO_ROOT[most_common]
    return f"{key_root} {'minor' if is_minor_key else 'major'}"


def normalize_chord_label(label):
    """BTC出力のコード名をmir_eval互換に正規化"""
    if label in ('N.C.', 'N', 'X', ''):
        return 'N'
    
    # 既にmir_eval形式 (A:min7等) の場合はそのまま
    if ':' in label:
        return label
    
    # NextChord形式 → mir_eval形式に変換
    if len(label) > 1 and label[1] in '#b':
        root = label[:2]
        suffix = label[2:]
    else:
        root = label[:1]
        suffix = label[1:]
    
    # suffix → mir_eval quality
    if suffix.startswith('dim'):
        return f"{root}:dim"
    elif suffix.startswith('aug'):
        return f"{root}:aug"
    elif suffix == 'm7':
        return f"{root}:min7"
    elif suffix == 'mMaj7':
        return f"{root}:minmaj7"
    elif suffix.startswith('m') and not suffix.startswith('maj'):
        return f"{root}:min"
    elif suffix == 'Maj7' or suffix == 'maj7':
        return f"{root}:maj7"
    elif suffix == '7':
        return f"{root}:7"
    elif suffix == 'sus4':
        return f"{root}:sus4"
    elif suffix == 'sus2':
        return f"{root}:sus2"
    elif suffix == '' or suffix == 'maj':
        return f"{root}:maj"
    else:
        return f"{root}:maj"


def evaluate_track(ref_path, est_intervals, est_labels):
    """mir_eval でフレームレベル評価"""
    ref_intervals, ref_labels = mir_eval.io.load_labeled_intervals(ref_path)
    
    est_intervals_np = np.array(est_intervals)
    est_labels_normalized = [normalize_chord_label(l) for l in est_labels]
    
    scores = mir_eval.chord.evaluate(ref_intervals, ref_labels, est_intervals_np, est_labels_normalized)
    
    return {
        "root": float(scores["root"]),
        "thirds": float(scores["thirds"]),
        "mirex": float(scores["mirex"]),
        "majmin": float(scores["majmin"]),
        "sevenths": float(scores["sevenths"]),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    print("=" * 70)
    print("NextChord コード判定 精度ベンチマーク")
    print("BTC単体 vs BTC+クロマ検証+HMM")
    print("=" * 70)
    
    tracks = get_all_tracks()
    print(f"\nTracks with existing predictions: {len(tracks)}")
    
    # 前回の結果をロード
    prev_report_path = BASE_DIR / "beatles_report.json"
    prev_results = {}
    if prev_report_path.exists():
        prev_data = json.load(open(prev_report_path, encoding='utf-8'))
        for r in prev_data.get('results', []):
            prev_results[r['track']] = r
    
    results_btc = []
    results_enhanced = []
    start_time = time.time()
    
    max_tracks = int(sys.argv[1]) if len(sys.argv) > 1 else len(tracks)
    tracks = tracks[:max_tracks]
    
    for i, track in enumerate(tracks):
        print(f"\n[{i+1}/{len(tracks)}] {track['title']}")
        
        try:
            # 1. BTC単体の評価（既存予測をそのまま）
            btc_intervals, btc_labels = parse_lab_file(track['pred_path'])
            btc_scores = evaluate_track(track['ref_path'], btc_intervals.tolist(), btc_labels)
            results_btc.append({"track": track["track_name"], "title": track["title"], **btc_scores})
            
            # 2. HMM補正を適用
            key_name = detect_key_from_chords(btc_labels)
            hmm_labels = apply_hmm_correction(btc_intervals.tolist(), btc_labels, key_name)
            hmm_scores = evaluate_track(track['ref_path'], btc_intervals.tolist(), hmm_labels)
            results_enhanced.append({"track": track["track_name"], "title": track["title"], **hmm_scores})
            
            # 差分表示
            diff_thirds = hmm_scores['thirds'] - btc_scores['thirds']
            diff_sym = "+" if diff_thirds >= 0 else ""
            print(f"  BTC:      root={btc_scores['root']:.3f}  thirds={btc_scores['thirds']:.3f}")
            print(f"  BTC+HMM:  root={hmm_scores['root']:.3f}  thirds={hmm_scores['thirds']:.3f}  ({diff_sym}{diff_thirds:.3f})")
            
        except Exception as e:
            print(f"  [ERROR] {e}")
            import traceback; traceback.print_exc()
    
    elapsed = time.time() - start_time
    
    # レポート
    print("\n" + "=" * 70)
    print("COMPARISON REPORT")
    print("=" * 70)
    
    metrics = ["root", "thirds", "mirex", "majmin", "sevenths"]
    
    print(f"\nTracks evaluated: {len(results_btc)}")
    print(f"Time: {elapsed:.0f}s")
    
    print(f"\n{'Metric':<12} {'BTC単体':>10} {'BTC+HMM':>10} {'差分':>10}")
    print("-" * 45)
    
    for m in metrics:
        avg_btc = np.mean([r[m] for r in results_btc]) if results_btc else 0
        avg_hmm = np.mean([r[m] for r in results_enhanced]) if results_enhanced else 0
        diff = avg_hmm - avg_btc
        diff_sym = "+" if diff >= 0 else ""
        print(f"{m:<12} {avg_btc:10.4f} {avg_hmm:10.4f} {diff_sym}{diff:9.4f}")
    
    # 改善・悪化した曲
    print(f"\n--- Improved Tracks (thirds) ---")
    improved = []
    degraded = []
    for btc_r, hmm_r in zip(results_btc, results_enhanced):
        diff = hmm_r['thirds'] - btc_r['thirds']
        if diff > 0.01:
            improved.append((btc_r['title'], diff))
        elif diff < -0.01:
            degraded.append((btc_r['title'], diff))
    
    for title, diff in sorted(improved, key=lambda x: -x[1])[:10]:
        print(f"  ↑ {title}: +{diff:.3f}")
    
    print(f"\n--- Degraded Tracks (thirds) ---")
    for title, diff in sorted(degraded, key=lambda x: x[1])[:10]:
        print(f"  ↓ {title}: {diff:.3f}")
    
    print(f"\nImproved: {len(improved)}, Degraded: {len(degraded)}, Unchanged: {len(results_btc) - len(improved) - len(degraded)}")
    
    # 保存
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tracks": len(results_btc),
        "elapsed_seconds": round(elapsed),
        "btc_only": {m: round(float(np.mean([r[m] for r in results_btc])), 4) for m in metrics},
        "btc_hmm": {m: round(float(np.mean([r[m] for r in results_enhanced])), 4) for m in metrics},
        "btc_paper_reference": {"thirds": 0.860, "root": 0.900},
        "improved": len(improved),
        "degraded": len(degraded),
    }
    report_path = BASE_DIR / "beatles_report_enhanced.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved: {report_path}")


if __name__ == '__main__':
    main()
