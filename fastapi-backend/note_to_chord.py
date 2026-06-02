"""
note_to_chord.py
Basic Pitch の音符認識結果からコードを推定するモジュール。
クロマグラムベースのコード認識より高精度。
"""
from __future__ import annotations
import pathlib
import warnings
from collections import defaultdict
from typing import List, Tuple, Optional, Dict

# ============================================================
# コードテンプレート定義
# ============================================================
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# 各コードタイプの音程インターバル（半音単位）
# ポップス向けに絞り込み: 3和音を優先、7th系は限定的に
CHORD_TEMPLATES: Dict[str, List[int]] = {
    'maj':   [0, 4, 7],          # メジャー（最優先）
    'min':   [0, 3, 7],          # マイナー（最優先）
    '7':     [0, 4, 7, 10],      # ドミナント7
    'maj7':  [0, 4, 7, 11],      # メジャー7
    'm7':    [0, 3, 7, 10],      # マイナー7
    'sus4':  [0, 5, 7],          # サスペンデッド4
    'sus2':  [0, 2, 7],          # サスペンデッド2
    'dim':   [0, 3, 6],          # ディミニッシュ
    'aug':   [0, 4, 8],          # オーギュメント
}

# ポップス向け: 7th系を基本3和音に正規化するマップ
SIMPLIFY_CHORD: Dict[str, str] = {
    'maj7': 'maj',   # Cmaj7 → C
    'm7':   'min',   # Am7 → Am
    'dim7': 'dim',
    'm7b5': 'dim',
    'add9': 'maj',
    'sus2': 'maj',   # Csus2 → C
}

# 表示名マッピング（ChordPro互換）
CHORD_DISPLAY: Dict[str, str] = {
    'maj': '',
    'min': 'm',
    '7': '7',
    'maj7': 'maj7',
    'm7': 'm7',
    'dim': 'dim',
    'dim7': 'dim7',
    'aug': 'aug',
    'sus2': 'sus2',
    'sus4': 'sus4',
    'm7b5': 'm7b5',
    'add9': 'add9',
}

# メジャーキーのダイアトニックコード (root_interval, chord_type)
MAJOR_DIATONIC = [
    (0, 'maj'), (2, 'min'), (4, 'min'), (5, 'maj'),
    (7, 'maj'), (9, 'min'), (11, 'dim'),
    # よく使う借用コード
    (0, 'maj7'), (4, 'm7'), (7, '7'), (9, 'm7'),
    (5, 'maj7'), (2, 'm7'), (10, 'maj'),  # VII♭
]

# マイナーキーのダイアトニックコード
MINOR_DIATONIC = [
    (0, 'min'), (2, 'dim'), (3, 'maj'), (5, 'min'),
    (7, 'min'), (8, 'maj'), (10, 'maj'),
    (0, 'm7'), (5, 'm7'), (7, '7'), (3, 'maj7'),
    (7, 'min'), (2, 'm7b5'),
]


def get_diatonic_set(key_root: int, key_type: str = 'major') -> set:
    """キーに属するコードの集合を返す (root_pc, chord_type)"""
    diatonic_list = MAJOR_DIATONIC if key_type == 'major' else MINOR_DIATONIC
    return {((key_root + interval) % 12, ctype) for interval, ctype in diatonic_list}


def chord_to_name(root_pc: int, chord_type: str) -> str:
    """(root_pc, chord_type) → コード名文字列 例: (0, 'min') → 'Cm'"""
    return NOTE_NAMES[root_pc] + CHORD_DISPLAY.get(chord_type, chord_type)


def score_chord(
    pc_weights: Dict[int, float],
    root: int,
    chord_type: str,
    diatonic_set: Optional[set] = None,
) -> float:
    """
    ピッチクラス重み辞書に対してコードのスコアを計算する。
    F1スコアベース + ダイアトニックボーナス。
    """
    template = {(root + i) % 12 for i in CHORD_TEMPLATES[chord_type]}
    
    total_weight = sum(pc_weights.values())
    if total_weight == 0:
        return 0.0

    # テンプレート内に存在する重みの合計（precision分子）
    in_template_w = sum(w for pc, w in pc_weights.items() if pc in template)

    # Precision: 検出音のうちテンプレートに含まれる割合
    precision = in_template_w / total_weight

    # Recall: テンプレート音のうち検出されているものの割合
    detected_pcs = {pc for pc, w in pc_weights.items() if w > 0}
    present_count = len(template & detected_pcs)
    recall = present_count / len(template)

    if precision + recall == 0:
        return 0.0
    f1 = 2 * precision * recall / (precision + recall)

    # ダイアトニックボーナス (+15%)
    if diatonic_set and (root, chord_type) in diatonic_set:
        f1 *= 1.15

    # 3和音ボーナス（ポップスでは3和音が多い）
    if len(CHORD_TEMPLATES[chord_type]) == 3:
        f1 *= 1.08

    # 7th系ペナルティ（3和音で説明できるなら3和音を優先）
    if chord_type in ('maj7', 'm7', '7'):
        f1 *= 0.92

    return f1


def notes_to_chord(
    note_events: List,
    t_start: float,
    t_end: float,
    key_root: Optional[int] = None,
    key_type: str = 'major',
    min_confidence: float = 0.25,
) -> Optional[str]:
    """
    指定時間範囲の音符イベントからコードを推定する。

    Parameters
    ----------
    note_events : list
        Basic Pitch の出力 [(start, end, pitch_midi, amplitude, ...), ...]
    t_start, t_end : float
        分析する時間範囲 (秒)
    key_root : int or None
        キーの根音 (0=C, 1=C#, ..., 11=B)
    key_type : str
        'major' or 'minor'
    min_confidence : float
        この値未満のスコアは N.C. を返す

    Returns
    -------
    str or None
        コード名 ('C', 'Am', 'G7', ...) または None
    """
    # 区間内の音符を収集し、ピッチクラス×重みを計算
    pc_weights: Dict[int, float] = defaultdict(float)

    for ne in note_events:
        start = float(ne[0])
        end   = float(ne[1])
        pitch = int(ne[2])
        amp   = float(ne[3]) if len(ne) > 3 else 1.0

        # 区間との重複時間を計算
        overlap = min(end, t_end) - max(start, t_start)
        if overlap <= 0:
            continue

        pc = pitch % 12
        # 重み = 重複時間 × 振幅（音量）
        pc_weights[pc] += overlap * amp

    if not pc_weights:
        return None

    # ダイアトニック集合
    diatonic = get_diatonic_set(key_root, key_type) if key_root is not None else None

    # 全108コードをスコアリング
    best_score = 0.0
    best_chord = None

    for root in range(12):
        for ctype in CHORD_TEMPLATES:
            s = score_chord(pc_weights, root, ctype, diatonic)
            if s > best_score:
                best_score = s
                best_chord = (root, ctype)

    if best_chord is None or best_score < min_confidence:
        return None

    root_pc, ctype = best_chord
    # ポップス向け簡略化: 7th系 → 基本3和音
    ctype = SIMPLIFY_CHORD.get(ctype, ctype)
    return chord_to_name(root_pc, ctype)


def build_chord_timeline(
    note_events: List,
    beat_times: List[float],
    key_root: Optional[int] = None,
    key_type: str = 'major',
    min_confidence: float = 0.25,
) -> List[Tuple[float, str]]:
    """
    ビートごとのコードタイムラインを構築する。

    Returns
    -------
    list of (time, chord_name)
        各ビート開始時刻とコード名のリスト
    """
    if not beat_times:
        return []

    timeline = []
    prev_chord = None

    for i, t_start in enumerate(beat_times):
        t_end = beat_times[i + 1] if i + 1 < len(beat_times) else t_start + 0.6

        chord = notes_to_chord(note_events, t_start, t_end, key_root, key_type, min_confidence)

        if chord is None:
            chord = prev_chord or 'N.C.'

        timeline.append((t_start, chord))
        prev_chord = chord

    return timeline


# ============================================================
# Basic Pitch モデルのロード・推論
# ============================================================

_bp_model_path: Optional[str] = None


def get_bp_model_path() -> str:
    """Basic Pitch の ONNX モデルパスを返す"""
    global _bp_model_path
    if _bp_model_path:
        return _bp_model_path
    try:
        import basic_pitch
        p = pathlib.Path(basic_pitch.__file__).parent / 'saved_models' / 'icassp_2022' / 'nmp.onnx'
        if p.exists():
            _bp_model_path = str(p)
            return _bp_model_path
    except ImportError:
        pass
    raise FileNotFoundError("Basic Pitch ONNX model not found. Install with: pip install basic-pitch")


def run_basic_pitch(
    wav_path: str,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    minimum_note_length_ms: float = 58.0,
    min_freq: float = 55.0,   # A1 ≈ギターの最低音
    max_freq: float = 2000.0,
) -> List:
    """
    Basic Pitch で音符を認識して note_events を返す。

    Returns
    -------
    list of (start_sec, end_sec, pitch_midi, amplitude)
    """
    import warnings
    import os
    os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
    os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')
    warnings.filterwarnings('ignore')

    from basic_pitch.inference import predict

    model_path = get_bp_model_path()
    print(f"[BasicPitch] Running inference on {wav_path} ...")

    _, _, note_events = predict(
        wav_path,
        model_path,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=minimum_note_length_ms,
        minimum_frequency=min_freq,
        maximum_frequency=max_freq,
        multiple_pitch_bends=False,
        melodia_trick=True,
    )
    print(f"[BasicPitch] Done. {len(note_events)} notes detected.")
    return note_events


def analyze_chords_with_basic_pitch(
    wav_path: str,
    beat_times: List[float],
    key_root: Optional[int] = None,
    key_type: str = 'major',
) -> List[Tuple[float, str]]:
    """
    wav_path に対して Basic Pitch を実行し、ビート同期コードタイムラインを返す。
    パイプラインから呼び出すメインエントリポイント。
    """
    note_events = run_basic_pitch(wav_path)
    return build_chord_timeline(note_events, beat_times, key_root, key_type)


def key_name_to_root(key_str: str) -> Tuple[Optional[int], str]:
    """
    "C major", "A minor", "F# major" 等をパースして (root_pc, key_type) を返す。
    """
    if not key_str:
        return None, 'major'
    parts = key_str.strip().lower().split()
    root_str = parts[0].capitalize() if parts else 'C'
    key_type = 'minor' if len(parts) > 1 and 'min' in parts[1] else 'major'
    try:
        root_pc = NOTE_NAMES.index(root_str)
    except ValueError:
        # C# / Db 等の別表記
        enharmonic = {'Db': 1, 'Eb': 3, 'Gb': 6, 'Ab': 8, 'Bb': 10,
                      'C#': 1, 'D#': 3, 'F#': 6, 'G#': 8, 'A#': 10}
        root_pc = enharmonic.get(root_str, 0)
    return root_pc, key_type


def smooth_chord_timeline(
    timeline: List[Tuple[float, str]],
    min_duration: float = 1.0,
) -> List[Tuple[float, str]]:
    """
    短すぎるコード変化（min_duration秒未満）を除去する。
    ポップス向けデフォルト: 1秒未満の変化は無視。
    """
    if len(timeline) < 3:
        return timeline

    smoothed = list(timeline)
    changed = True
    iterations = 0
    while changed and iterations < 10:
        changed = False
        iterations += 1
        new = []
        i = 0
        while i < len(smoothed):
            t_start, chord = smoothed[i]
            t_end = smoothed[i + 1][0] if i + 1 < len(smoothed) else t_start + 2.0
            duration = t_end - t_start

            if duration < min_duration and i > 0:
                prev_chord = new[-1][1] if new else chord
                next_chord = smoothed[i + 1][1] if i + 1 < len(smoothed) else chord
                if prev_chord == next_chord and prev_chord != chord:
                    new.append((t_start, prev_chord))
                    changed = True
                    i += 1
                    continue
                elif prev_chord != chord:
                    # 前のコードに吸収
                    new.append((t_start, prev_chord))
                    changed = True
                    i += 1
                    continue
            new.append((t_start, chord))
            i += 1
        smoothed = new

    return smoothed


def ensemble_chords(
    bp_timeline: List[Tuple[float, str]],
    chroma_changes: List[Tuple[float, str]],
    beat_times: List[float],
) -> List[Tuple[float, str]]:
    """
    Basic Pitch と クロマグラム の結果をアンサンブルする。
    ルート音が一致する場合はBasicPitch、不一致ならクロマグラムを採用。
    """
    def chord_root(c: str) -> str:
        if not c or c == 'N.C.':
            return ''
        return c[:2] if len(c) > 1 and c[1] in '#b' else c[:1]

    def lookup(timeline, t):
        """時刻tでのコードを返す"""
        result = None
        for tt, c in timeline:
            if tt <= t:
                result = c
            else:
                break
        return result

    if not bp_timeline:
        return [(t, c) for t, c in chroma_changes]

    result = []
    prev = None
    for t in beat_times:
        bp_c  = lookup(bp_timeline, t)  or 'N.C.'
        chr_c = lookup(chroma_changes, t) or 'N.C.'

        bp_root  = chord_root(bp_c)
        chr_root = chord_root(chr_c)

        if bp_root == chr_root:
            # ルート一致 → Basic Pitch のコードタイプを採用
            chosen = bp_c
        else:
            # ルート不一致 → クロマグラムを採用（より安定）
            chosen = chr_c

        if chosen != prev:
            result.append((t, chosen))
            prev = chosen

    return result
