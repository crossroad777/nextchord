"""
ensemble_engine.py  (v2 - Timing Refinement アーキテクチャ)

設計原則:
  ┌──────────────────────────────────────────────────────────┐
  │  BTC/ChordMini (Transformer)                             │
  │    → コード「種類」を決定 (C, G, Am, F…) ← 変えない     │
  │    → ただしタイミングが 0-1.2秒 ずれる                   │
  │                          ↓                               │
  │  Chroma CQT Timing Refiner                               │
  │    → BTCの各コード変化点を ±1.5秒の範囲でスキャン        │
  │    → クロマが最もそのコードのテンプレートに一致する      │
  │      フレーム時刻 → それが本当の変化点                   │
  │                          ↓                               │
  │  Music21 Theory Smoother                                 │
  │    → ありえない進行（C→F#→C など）をスムーズ化          │
  └──────────────────────────────────────────────────────────┘

期待精度向上:
  BTC単体: 27% (±0s評価) / 79% (±1.5s評価)
  + タイミング修正: → 50-65% (±0s評価)
"""
from __future__ import annotations
import warnings
import numpy as np
import librosa
import re
from typing import List, Tuple, Optional, Dict, Set
from pathlib import Path

warnings.filterwarnings('ignore')


# ============================================================
# コードテンプレート（タイミング修正用）
# ============================================================

NOTE_MAP = {
    'C':0,'C#':1,'Db':1,'D':2,'D#':3,'Eb':3,
    'E':4,'F':5,'F#':6,'Gb':6,'G':7,'G#':8,
    'Ab':8,'A':9,'A#':10,'Bb':10,'B':11,
}

CHORD_INTERVALS = {
    '':     [0,4,7],        'm':    [0,3,7],
    '7':    [0,4,7,10],     'maj7': [0,4,7,11],
    'm7':   [0,3,7,10],     'dim':  [0,3,6],
    'aug':  [0,4,8],        'sus4': [0,5,7],
    'sus2': [0,2,7],        'add9': [0,4,7,14%12],
    '6':    [0,4,7,9],      'm6':   [0,3,7,9],
    'm7b5': [0,3,6,10],     'dim7': [0,3,6,9],
    '9':    [0,4,7,10,2],   'maj9': [0,4,7,11,2],
}

_TEMPLATE_CACHE: Optional[Dict[str, np.ndarray]] = None


def _build_template(root_pc: int, intervals: List[int]) -> np.ndarray:
    t = np.zeros(12)
    WEIGHTS = {0: 1.0, 7: 0.65, 4: 0.7, 3: 0.7}  # root, 5th, 3rd
    for iv in intervals:
        pc = (root_pc + iv) % 12
        t[pc] = max(t[pc], WEIGHTS.get(iv % 12, 0.5))
    n = np.linalg.norm(t)
    return t / n if n > 0 else t


def get_templates() -> Dict[str, np.ndarray]:
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        _TEMPLATE_CACHE = {}
        for root_name, root_pc in [
            ('C',0),('C#',1),('D',2),('D#',3),('E',4),('F',5),
            ('F#',6),('G',7),('G#',8),('A',9),('A#',10),('B',11),
        ]:
            for suf, ivs in CHORD_INTERVALS.items():
                _TEMPLATE_CACHE[root_name + suf] = _build_template(root_pc, ivs)
        # BTC 記法の別名も登録
        for root_name, root_pc in [('Db',1),('Eb',3),('Gb',6),('Ab',8),('Bb',10)]:
            for suf, ivs in CHORD_INTERVALS.items():
                _TEMPLATE_CACHE[root_name + suf] = _build_template(root_pc, ivs)
    return _TEMPLATE_CACHE


def _parse_root(label: str) -> Optional[int]:
    """コードラベルからルート音クラスを返す"""
    m = re.match(r'^([A-G][#b]?)', str(label))
    if m:
        return NOTE_MAP.get(m.group(1))
    return None


def _normalize_label(label: str) -> str:
    """BTC の 'A:min7' などを 'Am7' に変換"""
    s = str(label).strip()
    s = s.replace(':min7', 'm7').replace(':min', 'm')
    s = s.replace(':maj7', 'maj7').replace(':maj', '')
    s = s.replace(':7', '7').replace(':dim7', 'dim7').replace(':dim', 'dim')
    s = s.replace(':aug', 'aug').replace(':sus4', 'sus4').replace(':sus2', 'sus2')
    return s


# ============================================================
# Step 1: Chroma グラムの計算
# ============================================================

def compute_chroma(wav_path: str, hop_length: int = 1024) -> Tuple[np.ndarray, float]:
    """
    音声からクロマグラムを計算。
    hop_length を 1024 (約46ms) に設定して精細なタイミング解像度を確保。
    """
    y, sr = librosa.load(str(wav_path), sr=22050, mono=True)
    y_harm, _ = librosa.effects.hpss(y, margin=4.0)

    # CQT (高解像度) + STFT の統合
    cqt = librosa.feature.chroma_cqt(
        y=y_harm, sr=sr, hop_length=hop_length,
        bins_per_octave=36, norm=2,
    )
    stft = librosa.feature.chroma_stft(
        y=y_harm, sr=sr, hop_length=hop_length,
        n_fft=8192, norm=2,
    )
    chroma = 0.65 * cqt + 0.35 * stft

    frame_time = hop_length / sr  # 約 0.046秒/フレーム
    return chroma, frame_time


def score_chord_at_frame(
    chroma: np.ndarray,
    frame: int,
    label: str,
    templates: Dict[str, np.ndarray],
    window: int = 3,
) -> float:
    """指定フレーム周辺のクロマとコードテンプレートのコサイン類似度"""
    n = chroma.shape[1]
    f_start = max(0, frame - window)
    f_end   = min(n, frame + window + 1)
    vec = np.mean(chroma[:, f_start:f_end], axis=1)
    norm = np.linalg.norm(vec)
    if norm < 0.01:
        return 0.0
    vec = vec / norm
    tmpl = templates.get(label, templates.get(_normalize_label(label)))
    if tmpl is None:
        return 0.0
    return float(np.dot(vec, tmpl))


# ============================================================
# Step 2: タイミング修正（メイン改善点）
# ============================================================

def refine_timing(
    seg_starts: np.ndarray,
    seg_labels: np.ndarray,
    chroma: np.ndarray,
    frame_time: float,
    search_window: float = 1.5,  # ±秒
    min_segment: float = 0.5,    # 最短セグメント（秒）
) -> Tuple[np.ndarray, np.ndarray]:
    """
    BTC の各コード変化点を Chroma で精密化する。

    各変化点について:
      1. ±search_window 秒の範囲をスキャン
      2. 「新しいコード」のテンプレートに最も一致するフレームを探す
      3. そのフレームを真の変化点として採用
    """
    templates = get_templates()
    n_frames = chroma.shape[1]

    refined_starts = []
    refined_labels = []

    for i, (t, label) in enumerate(zip(seg_starts, seg_labels)):
        norm_label = _normalize_label(str(label))

        if norm_label in ('N', 'N.C.', 'X', ''):
            refined_starts.append(float(t))
            refined_labels.append(norm_label)
            continue

        tmpl = templates.get(norm_label)
        if tmpl is None:
            refined_starts.append(float(t))
            refined_labels.append(norm_label)
            continue

        # 探索範囲を決定
        t_lo = float(t) - search_window
        t_hi = float(t) + search_window

        # 前のセグメント終了前には変化しない
        if i > 0:
            t_lo = max(t_lo, float(refined_starts[-1]) + min_segment)
        # 次のセグメント開始前に変化しなければならない
        if i + 1 < len(seg_starts):
            t_hi = min(t_hi, float(seg_starts[i+1]) - min_segment)

        t_lo = max(0.0, t_lo)

        f_lo = int(t_lo / frame_time)
        f_hi = int(t_hi / frame_time)
        f_lo = max(0, min(f_lo, n_frames - 1))
        f_hi = max(f_lo, min(f_hi, n_frames - 1))

        if f_lo >= f_hi:
            refined_starts.append(float(t))
            refined_labels.append(norm_label)
            continue

        # このコードのテンプレートスコアが最高のフレームを探す
        best_score = -1.0
        best_frame = int(t / frame_time)

        for f in range(f_lo, f_hi + 1):
            vec = chroma[:, f]
            n = np.linalg.norm(vec)
            if n < 0.01:
                continue
            score = float(np.dot(vec / n, tmpl))
            if score > best_score:
                best_score = score
                best_frame = f

        best_t = best_frame * frame_time
        # 前のセグメントの開始より前にはならない
        if refined_starts:
            best_t = max(best_t, refined_starts[-1] + min_segment)

        refined_starts.append(best_t)
        refined_labels.append(norm_label)

    return np.array(refined_starts), np.array(refined_labels)


# ============================================================
# Step 3: Music21 による進行スムーズ化
# ============================================================

def smooth_progression(
    seg_starts: np.ndarray,
    seg_labels: np.ndarray,
    chroma: np.ndarray,
    frame_time: float,
    key_str: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    ありえない進行を Music21 理論で修正する。
    例: Cキーで F# が出たら → F か G に修正
    """
    try:
        from music21_chord_engine import get_knowledge_base
        kb = get_knowledge_base()
    except Exception:
        return seg_starts, seg_labels

    templates = get_templates()
    new_labels = list(seg_labels)
    prev = None

    for i, (t, label) in enumerate(zip(seg_starts, seg_labels)):
        if label in ('N', 'N.C.', ''):
            prev = None
            continue

        # ダイアトニックなら変えない（BTC は正しい）
        is_diatonic = kb.get_diatonic_boost(label, key_str) >= 1.0
        if is_diatonic:
            prev = label
            continue

        # ノンダイアトニック → ダイアトニック候補で採点
        f = int(t / frame_time)
        f = max(0, min(f, chroma.shape[1] - 1))
        vec = chroma[:, max(0, f-2):min(chroma.shape[1], f+3)]
        chroma_frame = np.mean(vec, axis=1)

        diatonic = kb.diatonic_chords.get(key_str, [])
        current_score = kb.score_chord(chroma_frame, label, key_str, prev)
        best, best_score = label, current_score

        for d in diatonic:
            s = kb.score_chord(chroma_frame, d, key_str, prev)
            if s > best_score * 1.20:
                best_score = s
                best = d

        if best != label:
            print(f'[Smooth] t={t:.1f}s: {label}(non-diatonic) → {best}')
        new_labels[i] = best
        prev = best

    return seg_starts, np.array(new_labels)


# ============================================================
# メインエントリ
# ============================================================

def run_ensemble(
    wav_path: str,
    beat_times: np.ndarray,
    key_str: str = 'C major',
    session_id: str = '',
    use_chordmini: bool = True,
    use_btc: bool = True,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    フルアンサンブルパイプライン:
      1. BTC/ChordMini でコード種類を決定
      2. Chroma でタイミングを精密化
      3. Music21 でノンダイアトニックを修正
    """
    sid = session_id or 'ensemble'

    # --- Step 1: Transformer モデルでコード系列取得 ---
    seg_s, seg_l = None, None

    if use_chordmini:
        try:
            from chordmini_engine import get_chordmini_engine
            cm = get_chordmini_engine()
            cm.load()
            seg_s, seg_l = cm.detect_chords(wav_path)
            cm.unload()
            print(f'[{sid}] [Ensemble] ChordMini: {len(seg_l)} segments')
        except Exception as e:
            print(f'[{sid}] [Ensemble] ChordMini failed: {e}')

    if seg_s is None and use_btc:
        try:
            from btc_engine import get_btc_engine
            btc = get_btc_engine()
            btc.load()
            seg_s, seg_l = btc.detect_chords(wav_path, use_hpss=True)
            print(f'[{sid}] [Ensemble] BTC: {len(seg_l)} segments')
        except Exception as e:
            print(f'[{sid}] [Ensemble] BTC failed: {e}')

    if seg_s is None:
        return np.array([0.0]), np.array(['N'])

    # --- Step 2: Chroma グラム計算 ---
    print(f'[{sid}] [Ensemble] Computing chroma (hop=1024)...')
    chroma, frame_time = compute_chroma(wav_path, hop_length=1024)
    print(f'[{sid}] [Ensemble] Chroma: {chroma.shape[1]} frames, {frame_time*1000:.0f}ms/frame')

    # --- Step 3: タイミング修正 ---
    print(f'[{sid}] [Ensemble] Refining timing (±1.5s window)...')
    seg_s, seg_l = refine_timing(
        seg_s, seg_l, chroma, frame_time,
        search_window=1.5, min_segment=0.4,
    )

    # 前後チェック（refined が単調増加か）
    mono = np.all(np.diff(seg_s) >= 0)
    print(f'[{sid}] [Ensemble] Timing refined: {len(seg_l)} segments, monotone={mono}')

    # --- Step 4: Music21 スムーズ化 ---
    seg_s, seg_l = smooth_progression(seg_s, seg_l, chroma, frame_time, key_str)

    # --- 統計表示 ---
    from collections import Counter
    counts = Counter(seg_l)
    print(f'[{sid}] [Ensemble] Top chords: {counts.most_common(8)}')

    return seg_s, seg_l


# ============================================================
# スタンドアロンテスト
# ============================================================

if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.path.insert(0, str(Path(__file__).parent))

    WAV = 'D:/Music/nextchord/uploads/20260531-094434-yt-7d6cc5/converted.wav'
    KEY = 'C major'
    beat_interval = 60 / 97  # 97 BPM
    beat_times = np.arange(5.0, 115.0, beat_interval)

    print('=== Ensemble Engine v2 (Timing Refinement) ===')
    seg_s, seg_l = run_ensemble(WAV, beat_times, KEY, session_id='test')

    print()
    print('=== 最初の35セグメント ===')
    for t, label in zip(seg_s[:35], seg_l[:35]):
        print(f'  {t:6.2f}s: {label}')

    # MIREX 評価
    GT_SEGS = [
        (4.9,7.3,'C'),(7.3,9.6,'G'),(9.6,12.0,'Am'),(12.0,14.5,'F'),
        (14.5,17.0,'C'),(17.0,19.3,'G'),(19.3,21.8,'Am'),(21.8,24.2,'F'),
        (24.2,26.7,'C'),(26.7,29.2,'G'),(29.2,31.7,'Am'),(31.7,34.2,'F'),
        (34.2,39.0,'C'),(39.0,43.8,'G'),(43.8,48.6,'Am'),(48.6,53.4,'Em'),
        (53.4,58.2,'F'),(58.2,63.0,'C'),(63.0,67.8,'F'),(67.8,72.6,'G'),
        (72.6,77.4,'C'),(77.4,82.2,'G'),(82.2,87.0,'Am'),(87.0,91.8,'Em'),
        (91.8,96.6,'F'),(96.6,101.4,'C'),(101.4,106.2,'F'),(106.2,111.0,'G'),
    ]

    def norm(c):
        c = str(c).replace(':','').replace('min','m').replace('maj','').strip()
        m = re.match(r'^([A-G][#b]?)(m?)', c)
        return (m.group(1)+m.group(2)) if m else c

    def get_pred(t, ss, sl):
        r='N'
        for i in range(len(ss)):
            if float(ss[i])<=t: r=str(sl[i])
            else: break
        return r

    # 許容誤差別精度
    print()
    print('=== 精度評価 ===')
    for tol in [0.0, 0.25, 0.5, 0.75, 1.0]:
        ok=tot=0
        for s,e,gt in GT_SEGS:
            mid=(s+e)/2
            found=False
            for off in np.arange(-tol, tol+0.05, 0.05):
                if norm(get_pred(mid+off, seg_s, seg_l))==gt:
                    found=True; break
            ok+=int(found); tot+=1
        print(f'  ±{tol:.2f}s: {ok}/{tot} = {ok/tot*100:.1f}%')
