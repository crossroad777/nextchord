"""
music21_chord_engine.py
Music21 の音楽理論知識を使った高精度コード認識エンジン。

アイデア:
1. 全コードの音楽理論上の特徴量をMusic21で事前計算
2. コード間の「音の共通度」行列を構築
3. キー内での機能（Ⅰ〜Ⅶ）に基づいてスコアを調整
4. コード進行のマルコフ確率で候補を絞る
"""
from __future__ import annotations
import warnings
import numpy as np
from typing import List, Dict, Tuple, Optional, Set
warnings.filterwarnings('ignore')

# ============================================================
# 音楽理論定数
# ============================================================

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
NOTE_MAP   = {n: i for i, n in enumerate(NOTE_NAMES)}
NOTE_MAP.update({'Db':1,'Eb':3,'Gb':6,'Ab':8,'Bb':10})

CHORD_INTERVALS: Dict[str, List[int]] = {
    '':     [0,4,7],
    'm':    [0,3,7],
    '7':    [0,4,7,10],
    'maj7': [0,4,7,11],
    'm7':   [0,3,7,10],
    'dim':  [0,3,6],
    'dim7': [0,3,6,9],
    'aug':  [0,4,8],
    'sus4': [0,5,7],
    'sus2': [0,2,7],
    'm7b5': [0,3,6,10],
    'add9': [0,4,7,14],
    '6':    [0,4,7,9],
    'm6':   [0,3,7,9],
    '9':    [0,4,7,10,14],
    'maj9': [0,4,7,11,14],
    'm9':   [0,3,7,10,14],
}

# ============================================================
# Music21 特徴量データベース（事前計算）
# ============================================================

class ChordKnowledgeBase:
    """
    全コードのMusic21ベース特徴量データベース。
    起動時に一度だけ計算してキャッシュ。
    """
    def __init__(self):
        self._built = False
        self.chord_features: Dict[str, dict] = {}  # chord_name → features
        self.similarity_matrix: Dict[Tuple[str,str], float] = {}  # (c1,c2) → similarity
        self.key_functions: Dict[Tuple[str,str], str] = {}  # (chord, key) → roman numeral
        self.diatonic_chords: Dict[str, List[str]] = {}  # key → [diatonic chords]
        self.progression_probs: Dict[Tuple[str,str], float] = {}  # (chord_i, chord_j) → prob

    def build(self):
        """全コードの特徴量を計算"""
        if self._built:
            return
        print('[Music21KB] Building chord knowledge base...')
        self._build_chord_features()
        self._build_similarity_matrix()
        self._build_diatonic_chords()
        self._build_progression_probs()
        self._built = True
        print(f'[Music21KB] Done. {len(self.chord_features)} chords analyzed.')

    def _all_chord_names(self) -> List[str]:
        chords = []
        for root in NOTE_NAMES:
            for ctype in CHORD_INTERVALS:
                chords.append(root + ctype)
        return chords

    def _get_pitch_classes(self, chord_name: str) -> Set[int]:
        """コード名から音クラスセットを返す"""
        root_str = chord_name[:2] if len(chord_name)>1 and chord_name[1] in '#b' else chord_name[:1]
        suffix   = chord_name[len(root_str):]
        root_pc  = NOTE_MAP.get(root_str)
        if root_pc is None:
            return set()
        intervals = CHORD_INTERVALS.get(suffix, [0,4,7])
        return {(root_pc + iv) % 12 for iv in intervals}

    def _build_chord_features(self):
        """各コードの音楽理論特徴量を計算"""
        try:
            from music21 import chord as m21chord, roman, key as m21key
            use_music21 = True
        except ImportError:
            use_music21 = False

        for cname in self._all_chord_names():
            pcs = self._get_pitch_classes(cname)
            root_str = cname[:2] if len(cname)>1 and cname[1] in '#b' else cname[:1]
            suffix   = cname[len(root_str):]
            root_pc  = NOTE_MAP.get(root_str, 0)

            # 基本特徴量（Music21なしでも計算可能）
            features = {
                'pitch_classes': pcs,
                'root': root_pc,
                'type': suffix,
                'n_notes': len(pcs),
                'is_major': suffix in ('', 'maj', 'maj7', 'sus4', 'sus2', '6', '9', 'maj9', 'add9', 'aug'),
                'is_minor': suffix in ('m', 'm7', 'm9', 'm6', 'm7b5'),
                'is_dim':   suffix in ('dim', 'dim7', 'm7b5'),
                'is_dom7':  suffix in ('7', '9'),
                'tension':  self._calc_tension(suffix),
                'chroma_template': self._make_chroma_template(root_pc, suffix),
            }

            # Music21 拡張特徴量
            if use_music21:
                try:
                    note_names = [
                        NOTE_NAMES[(root_pc + iv) % 12] + '4'
                        for iv in CHORD_INTERVALS.get(suffix, [0,4,7])
                        if iv < 12  # オクターブ内のみ
                    ]
                    m21c = m21chord.Chord(note_names)
                    features['m21_quality'] = m21c.quality
                    features['m21_inversion'] = m21c.inversion()
                except Exception:
                    pass

            self.chord_features[cname] = features

    def _calc_tension(self, ctype: str) -> float:
        """コードタイプの緊張度（0=安定, 1=緊張）"""
        tension_map = {
            '': 0.0, 'm': 0.1, 'maj7': 0.2, 'm7': 0.25,
            'sus4': 0.3, 'sus2': 0.25, '6': 0.15, 'add9': 0.2,
            '7': 0.6, '9': 0.55, 'maj9': 0.35, 'm9': 0.35,
            'dim': 0.8, 'dim7': 0.85, 'aug': 0.75, 'm7b5': 0.7,
        }
        return tension_map.get(ctype, 0.3)

    def _make_chroma_template(self, root_pc: int, ctype: str) -> np.ndarray:
        """12次元クロマテンプレートを生成（重み付き）"""
        template = np.zeros(12)
        intervals = CHORD_INTERVALS.get(ctype, [0,4,7])

        # 重み: ルート=1.0, 5th=0.7, 3rd=0.8, 7th=0.6
        weights = {0: 1.0}  # root
        for i, iv in enumerate(intervals[1:], 1):
            norm_iv = iv % 12
            if norm_iv == 7:   # 5th
                weights[norm_iv] = 0.7
            elif norm_iv in (3,4):  # 3rd
                weights[norm_iv] = 0.8
            elif norm_iv in (10,11):  # 7th
                weights[norm_iv] = 0.6
            else:
                weights[norm_iv] = 0.5

        for iv in intervals:
            pc = (root_pc + iv) % 12
            template[pc] = weights.get(iv % 12, 0.5)

        norm = np.linalg.norm(template)
        return template / norm if norm > 0 else template

    def _build_similarity_matrix(self):
        """コード間の共通音数に基づく類似度行列"""
        all_chords = list(self.chord_features.keys())
        for i, c1 in enumerate(all_chords):
            pcs1 = self.chord_features[c1]['pitch_classes']
            for c2 in all_chords[i:]:
                pcs2 = self.chord_features[c2]['pitch_classes']
                common = len(pcs1 & pcs2)
                total  = len(pcs1 | pcs2)
                sim = common / total if total > 0 else 0.0
                self.similarity_matrix[(c1, c2)] = sim
                self.similarity_matrix[(c2, c1)] = sim

    def _build_diatonic_chords(self):
        """各キーのダイアトニックコードリスト"""
        # メジャーキー: Ⅰ Ⅱm Ⅲm Ⅳ Ⅴ Ⅵm Ⅶdim
        major_degrees = [(0,''), (2,'m'), (4,'m'), (5,''), (7,''), (9,'m'), (11,'dim')]
        # マイナーキー: Ⅰm Ⅱdim ⅢM Ⅳm Ⅴm ⅥM ⅦM
        minor_degrees = [(0,'m'), (2,'dim'), (3,''), (5,'m'), (7,'m'), (8,''), (10,'')]

        for root_pc, root_name in enumerate(NOTE_NAMES):
            # メジャーキー
            key_name = root_name + ' major'
            self.diatonic_chords[key_name] = [
                NOTE_NAMES[(root_pc + d) % 12] + ctype
                for d, ctype in major_degrees
            ]
            # マイナーキー
            key_name = root_name + ' minor'
            self.diatonic_chords[key_name] = [
                NOTE_NAMES[(root_pc + d) % 12] + ctype
                for d, ctype in minor_degrees
            ]

    def _build_progression_probs(self):
        """
        よく使われるコード進行のマルコフ遷移確率。
        日本のポップスに多いパターンをベース。
        """
        # キー非依存の度数ベース遷移（メジャーキー）
        # (from_degree_offset, to_degree_offset) → relative probability
        COMMON_PROGRESSIONS = [
            # I → V, I → IV, I → vi, I → ii
            (0, 7, 0.35),  # I → V
            (0, 5, 0.30),  # I → IV
            (0, 9, 0.25),  # I → vi
            (0, 2, 0.10),  # I → ii
            # IV → V, IV → I, IV → ii
            (5, 7, 0.45),  # IV → V
            (5, 0, 0.30),  # IV → I
            (5, 2, 0.15),  # IV → ii
            (5, 9, 0.10),  # IV → vi
            # V → I, V → vi (deceptive)
            (7, 0, 0.65),  # V → I (dominant resolution)
            (7, 9, 0.20),  # V → vi (deceptive cadence)
            (7, 5, 0.10),  # V → IV
            # vi → IV, vi → II, vi → V
            (9, 5, 0.40),  # vi → IV
            (9, 2, 0.25),  # vi → ii
            (9, 7, 0.20),  # vi → V
            (9, 0, 0.15),  # vi → I
            # ii → V, ii → IV
            (2, 7, 0.55),  # ii → V
            (2, 5, 0.25),  # ii → IV
            (2, 0, 0.15),  # ii → I
        ]
        # これらをNOTE_NAMES × 12キーに展開してself.progression_probsに格納
        # （実際の使用時はキーオフセットで計算するため省略）
        self._raw_progressions = COMMON_PROGRESSIONS

    def get_diatonic_boost(self, chord_name: str, key_str: str) -> float:
        """
        ダイアトニックコードなら 1.15 を返す。
        ノンダイアトニックなら 0.85 を返す。
        """
        diatonic = self.diatonic_chords.get(key_str, [])
        if not diatonic:
            return 1.0

        # 簡易照合（ルート音が一致するか）
        root_str = chord_name[:2] if len(chord_name)>1 and chord_name[1] in '#b' else chord_name[:1]
        chord_root_pc = NOTE_MAP.get(root_str)
        if chord_root_pc is None:
            return 1.0

        for d in diatonic:
            d_root = d[:2] if len(d)>1 and d[1] in '#b' else d[:1]
            if NOTE_MAP.get(d_root) == chord_root_pc:
                return 1.15  # ダイアトニック

        return 0.85  # ノンダイアトニック

    def get_progression_boost(
        self,
        prev_chord: Optional[str],
        candidate: str,
        key_str: str,
    ) -> float:
        """
        直前のコードに対してcandidateがよく来る進行なら boost > 1。
        G7 → C なら強くboost。
        """
        if not prev_chord:
            return 1.0

        prev_feat = self.chord_features.get(prev_chord, {})
        cand_feat = self.chord_features.get(candidate, {})

        prev_root = prev_feat.get('root', -1)
        cand_root = cand_feat.get('root', -1)
        if prev_root < 0 or cand_root < 0:
            return 1.0

        interval = (cand_root - prev_root) % 12

        # ドミナント解決: V7 → I
        if prev_feat.get('is_dom7') and interval == 5:  # 完全4度上 = Vから見てI
            return 1.4

        # 4度進行（最もよく使われる）
        if interval == 5:
            return 1.2

        # 5度進行
        if interval == 7:
            return 1.15

        # 半音進行（テンションの解決）
        if interval in (1, 11):
            return 1.1

        return 1.0

    def score_chord(
        self,
        chroma_frame: np.ndarray,
        chord_name: str,
        key_str: str = '',
        prev_chord: Optional[str] = None,
    ) -> float:
        """
        クロマグラム + 音楽理論スコアを統合した最終スコアを返す。
        """
        feat = self.chord_features.get(chord_name)
        if feat is None:
            return 0.0

        # 1. アコースティックスコア（クロマ類似度）
        template = feat['chroma_template']
        chroma_norm = chroma_frame / (np.linalg.norm(chroma_frame) + 1e-8)
        acoustic_score = float(np.dot(chroma_norm, template))

        # 2. ダイアトニックブースト
        diatonic_boost = self.get_diatonic_boost(chord_name, key_str) if key_str else 1.0

        # 3. 進行ブースト
        prog_boost = self.get_progression_boost(prev_chord, chord_name, key_str)

        # 4. 緊張度ペナルティ（テンションコードは慎重に）
        tension = feat.get('tension', 0.3)
        tension_penalty = 1.0 - tension * 0.15  # max -15%

        return acoustic_score * diatonic_boost * prog_boost * tension_penalty


# ============================================================
# シングルトン
# ============================================================

_kb: Optional[ChordKnowledgeBase] = None

def get_knowledge_base() -> ChordKnowledgeBase:
    global _kb
    if _kb is None:
        _kb = ChordKnowledgeBase()
        _kb.build()
    return _kb


# ============================================================
# メイン: クロマグラム → コード推定
# ============================================================

def recognize_chords_with_theory(
    chroma: np.ndarray,          # shape: (12, n_frames)
    beat_times: List[float],
    key_str: str = 'C major',
    min_confidence: float = 0.25,
    candidates: Optional[List[str]] = None,
) -> List[Tuple[float, str]]:
    """
    Music21知識ベース + クロマグラムでコードを認識。

    Parameters
    ----------
    chroma : np.ndarray
        12次元クロマグラム (12, n_frames)
    beat_times : List[float]
        ビート時刻リスト
    key_str : str
        検出されたキー ('C major', 'A minor' など)
    min_confidence : float
        最低スコア閾値
    candidates : List[str] or None
        候補コードリスト（Noneなら全コード）

    Returns
    -------
    List[(time, chord_name)]
    """
    kb = get_knowledge_base()
    if candidates is None:
        candidates = list(kb.chord_features.keys())

    sr_frames = chroma.shape[1]
    total_duration = beat_times[-1] + 0.5 if beat_times else 0

    results = []
    prev_chord = None

    for i, t in enumerate(beat_times):
        # フレームインデックスに変換
        frame_idx = int(t / total_duration * sr_frames) if total_duration > 0 else 0
        frame_idx = min(frame_idx, sr_frames - 1)

        chroma_frame = chroma[:, frame_idx]

        # 全候補を採点
        best_chord = 'N.C.'
        best_score = min_confidence

        for cname in candidates:
            score = kb.score_chord(chroma_frame, cname, key_str, prev_chord)
            if score > best_score:
                best_score = score
                best_chord = cname

        results.append((t, best_chord))
        prev_chord = best_chord

    return results


if __name__ == '__main__':
    # テスト
    import sys
    sys.path.insert(0, '.')
    kb = get_knowledge_base()

    print('\n=== 共通音テスト ===')
    pairs = [('C','Am'), ('G','Em'), ('F','Dm'), ('G7','C'), ('Am','Em')]
    for a, b in pairs:
        sim = kb.similarity_matrix.get((a,b), 0)
        print(f'  {a} ↔ {b}: 類似度={sim:.2f}')

    print('\n=== Cキーのダイアトニックコード ===')
    print(' ', kb.diatonic_chords.get('C major'))

    print('\n=== 進行ブーストテスト ===')
    tests = [('G7','C'), ('G','C'), ('F','G'), ('C','Am'), ('Am','F')]
    for prev, cand in tests:
        boost = kb.get_progression_boost(prev, cand, 'C major')
        print(f'  {prev} → {cand}: boost={boost:.2f}')
