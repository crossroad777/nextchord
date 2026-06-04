"""
NextChord - コード検証モジュール (music21 + クロマ照合)
=========================================================
BTCの予測コードを「音声の実際の音」と照合して検証・補正する。

原理:
  1. 各ビート区間の音声からクロマベクトル（12音の強度分布）を計算
     → ビート同期CQT: 固定hop_lengthではなくビート区間ごとにクロマを計算
  2. music21 でコード名 → 構成音(pitch class set) に変換
  3. 予測コードの構成音が実際の音に合っているかスコアリング
     → コサイン類似度 + 3度/7度の重み付け + 非構成音ペナルティ
  4. スコアが低い場合、より一致するコードに差し替え
     → 多重証拠投票: BTC信頼度 × クロマスコア × ダイアトニック適合

「正しい耳」= クロマ分析、「正しい知識」= music21
"""

import numpy as np
import librosa
import time as _time
from collections import Counter
from typing import Optional
from functools import lru_cache

# ===================================================================
# music21 によるコード理論辞書
# ===================================================================

# music21 の ChordSymbol は初回呼び出しが遅いので、
# 全コードテンプレートを事前計算してキャッシュする
_CHORD_PC_CACHE = {}


def _build_chord_templates():
    """全170コード品質×12ルートのpitch classテンプレートを構築"""
    from music21 import harmony

    roots = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    # BTC large_voca の14品質に対応する music21 表記
    qualities = {
        '': '',           # major
        'm': 'm',         # minor
        '7': '7',         # dominant 7th
        'Maj7': 'maj7',   # major 7th
        'm7': 'm7',       # minor 7th
        'dim': 'dim',     # diminished
        'aug': 'aug',     # augmented
        '6': '6',         # major 6th
        'm6': 'm6',       # minor 6th
        'mMaj7': 'mM7',   # minor-major 7th
        'dim7': 'dim7',   # diminished 7th
        'm7(b5)': 'm7b5', # half-diminished 7th
        'sus2': 'sus2',   # suspended 2nd
        'sus4': 'sus4',   # suspended 4th
    }

    for root in roots:
        for btc_q, m21_q in qualities.items():
            btc_name = f"{root}{btc_q}"
            m21_name = f"{root}{m21_q}"
            try:
                cs = harmony.ChordSymbol(m21_name)
                pcs = frozenset(p.pitchClass for p in cs.pitches)
                _CHORD_PC_CACHE[btc_name] = pcs
            except Exception:
                pass

    # エンハーモニック別名も登録
    enharmonic = {
        'Db': 'C#', 'D#': 'Eb', 'Gb': 'F#', 'G#': 'Ab', 'A#': 'Bb'
    }
    extra = {}
    for btc_name, pcs in list(_CHORD_PC_CACHE.items()):
        root = btc_name[:2] if len(btc_name) > 1 and btc_name[1] in '#b' else btc_name[:1]
        quality = btc_name[len(root):]
        for alt, canon in enharmonic.items():
            if root == canon:
                extra[f"{alt}{quality}"] = pcs
            elif root == alt:
                extra[f"{canon}{quality}"] = pcs
    _CHORD_PC_CACHE.update(extra)

    print(f"[ChordVerifier] Built {len(_CHORD_PC_CACHE)} chord templates")


def get_chord_pitch_classes(chord_name):
    """コード名 → pitch class set (frozenset of int 0-11)"""
    if not _CHORD_PC_CACHE:
        _build_chord_templates()
    return _CHORD_PC_CACHE.get(chord_name, None)


# ===================================================================
# ビート同期CQT (Beat-Synchronous Chroma)
# ===================================================================


@lru_cache(maxsize=2)
def _load_audio_data(audio_path, sr=22050, use_hpss=False):
    """LRUキャッシュ付き音声ロード。use_hpss=Trueの場合のみ調波打楽器分離(HPSS)を実行。"""
    t0 = _time.time()
    from waveform_utils import load_audio_cached
    y, sr_out = load_audio_cached(str(audio_path), sr=sr, mono=True)
    if use_hpss:
        y_out = librosa.effects.harmonic(y, margin=3.0)
        label = "harmonic (HPSS)"
    else:
        y_out = y
        label = "raw"
    print(f"[ChordVerifier] _load_audio_data ({label}): {_time.time()-t0:.1f}s (cached)")
    return y_out, sr_out


def _compute_beat_chroma(audio_path, beat_times, sr=22050, use_hpss=False):
    """Compute one chroma vector per beat interval (beat-synchronous).

    Uses vectorized np.searchsorted instead of per-beat masking for ~4x speedup.
    Uses LRU-cached audio to avoid redundant librosa.load calls.

    Parameters
    ----------
    audio_path : str or Path
        Path to the audio file.
    beat_times : array-like
        Beat onset times in seconds.
    sr : int
        Sample rate.
    use_hpss : bool
        Whether to perform HPSS.

    Returns
    -------
    np.ndarray, shape (N, 12)
        One chroma vector per beat interval.
    """
    t0 = _time.time()
    
    # Use LRU-cached audio loader
    try:
        y_processed, sr = _load_audio_data(str(audio_path), sr=sr, use_hpss=use_hpss)
    except Exception:
        # Fallback: load directly if cache fails
        from waveform_utils import load_audio_cached
        y, sr = load_audio_cached(str(audio_path), sr=sr, mono=True)
        if use_hpss:
            y_processed = librosa.effects.harmonic(y, margin=3.0)
        else:
            y_processed = y

    # Compute chroma CQT once for the entire audio
    hop_length = 512
    chroma_full = librosa.feature.chroma_cqt(y=y_processed, sr=sr, hop_length=hop_length)
    # shape: (12, n_frames)

    frame_times = librosa.frames_to_time(np.arange(chroma_full.shape[1]), sr=sr, hop_length=hop_length)

    # Vectorized beat-sync averaging using searchsorted (~4x faster than per-beat masking)
    n_beats = len(beat_times)
    beat_chromas = np.zeros((n_beats, 12))
    
    if n_beats > 0:
        # Compute end times for each beat
        ends = np.append(beat_times[1:], beat_times[-1] + 0.5)
        # Find frame indices for beat boundaries
        start_frames = np.searchsorted(frame_times, beat_times)
        end_frames = np.searchsorted(frame_times, ends)
        for i in range(n_beats):
            sf, ef = start_frames[i], end_frames[i]
            if ef > sf:
                beat_chromas[i] = chroma_full[:, sf:ef].mean(axis=1)
    
    elapsed = _time.time() - t0
    print(f"[ChordVerifier] _compute_beat_chroma: {n_beats} beats, {elapsed:.1f}s (vectorized searchsorted, HPSS={use_hpss})")
    return beat_chromas


# ===================================================================
# クロマベースのコード照合スコア（改良版）
# ===================================================================

# 音程ごとの重み: 3度(3,4) と 7度(10,11) を重く評価
# key = interval from root in semitones
_INTERVAL_WEIGHTS = {
    0: 1.0,   # root
    1: 0.6,   # b2
    2: 0.7,   # 2nd / 9th
    3: 1.4,   # minor 3rd  ← 重要: major/minor 判別
    4: 1.4,   # major 3rd  ← 重要: major/minor 判別
    5: 0.8,   # 4th / 11th
    6: 0.7,   # #4 / b5
    7: 1.0,   # 5th
    8: 0.7,   # b6 / #5
    9: 0.8,   # 6th / 13th
    10: 1.3,  # minor 7th  ← 重要: 7th 判別
    11: 1.3,  # major 7th  ← 重要: 7th 判別
}


def _build_chord_template(pitch_classes, root_pc=None):
    """Build a weighted ideal chroma template for a chord.

    Parameters
    ----------
    pitch_classes : frozenset of int
        Pitch classes (0-11) that belong to the chord.
    root_pc : int or None
        Root pitch class. If None, the lowest pitch class is used.

    Returns
    -------
    np.ndarray, shape (12,)
        Weighted template vector.
    """
    template = np.zeros(12)
    if root_pc is None:
        root_pc = min(pitch_classes) if pitch_classes else 0
    for pc in pitch_classes:
        interval = (pc - root_pc) % 12
        template[pc] = _INTERVAL_WEIGHTS.get(interval, 0.7)
    return template


def _chord_chroma_score(beat_chroma, pitch_classes):
    """
    ビートのクロマベクトルとコードの構成音の一致度を計算（改良版）。

    改良点:
    - コサイン類似度による音響マッチング
    - 3度/7度を重み付け（major/minor/7th の判別に重要）
    - 非構成音のエネルギーペナルティ

    Parameters
    ----------
    beat_chroma : np.ndarray, shape (12,)
        Observed chroma vector for one beat.
    pitch_classes : frozenset of int
        Expected pitch classes of the chord.

    Returns
    -------
    float
        Score in [0, 1]. Higher = better match.
    """
    if not pitch_classes or len(pitch_classes) == 0:
        return 0.0

    chroma = beat_chroma.copy()
    chroma_norm = np.linalg.norm(chroma)
    if chroma_norm < 1e-10:
        return 0.0

    # --- 1. コサイン類似度 (weighted template) ---
    template = _build_chord_template(pitch_classes)
    template_norm = np.linalg.norm(template)
    if template_norm < 1e-10:
        return 0.0
    cosine_sim = np.dot(chroma, template) / (chroma_norm * template_norm)
    cosine_sim = max(0.0, cosine_sim)  # clamp to [0, 1]

    # --- 2. 構成音 vs 非構成音のコントラスト ---
    chroma_01 = chroma / (np.max(chroma) + 1e-10)
    pcs = list(pitch_classes)
    in_chord = np.mean([chroma_01[pc] for pc in pcs])
    out_pcs = [i for i in range(12) if i not in pcs]
    out_chord = np.mean([chroma_01[pc] for pc in out_pcs]) if out_pcs else 0.0
    contrast = max(0.0, in_chord - 0.7 * out_chord)

    # --- 3. 非構成音ペナルティ ---
    # 非構成音に強いエネルギーがある場合にペナルティ
    if out_pcs:
        max_out = max(chroma_01[pc] for pc in out_pcs)
        # 非構成音の最大値が構成音の平均を超える場合ペナルティ
        penalty = max(0.0, max_out - in_chord) * 0.3
    else:
        penalty = 0.0

    # 最終スコア: コサイン50%, コントラスト40%, ペナルティ-10%
    score = 0.50 * cosine_sim + 0.40 * contrast + 0.10 * (1.0 - penalty)
    return max(0.0, min(1.0, score))


# ===================================================================
# 自然な和声進行テーブル (Common Chord Transitions)
# ===================================================================

# interval = (next_root - prev_root) % 12
# よくある進行のintervalに高いスコアを割り当て
_COMMON_TRANSITIONS = {
    0: 0.6,   # same root (e.g., C -> Cm)
    2: 0.5,   # whole step up (e.g., IV -> V)
    5: 0.9,   # perfect 4th up / 5th down (e.g., V -> I, strongest)
    7: 0.8,   # perfect 5th up / 4th down (e.g., I -> V)
    3: 0.5,   # minor 3rd up (e.g., vi -> I in relative major)
    4: 0.5,   # major 3rd up
    9: 0.6,   # minor 3rd down (e.g., I -> vi)
    8: 0.4,   # major 3rd down
    10: 0.5,  # whole step down (e.g., bVII -> I)
    1: 0.3,   # half step up
    11: 0.4,  # half step down (e.g., V/V -> V)
    6: 0.2,   # tritone (rare)
}


def _transition_score(prev_chord: str, next_chord: str) -> float:
    """Estimate how natural the transition from prev_chord to next_chord is.

    Returns a score in [0, 1].
    """
    if prev_chord == 'N.C.' or next_chord == 'N.C.':
        return 0.5  # neutral

    # Extract root pitch class
    _NOTE_TO_PC = {
        'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
        'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
        'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11,
    }

    def _root_pc(chord_name):
        if len(chord_name) > 1 and chord_name[1] in '#b':
            return _NOTE_TO_PC.get(chord_name[:2])
        return _NOTE_TO_PC.get(chord_name[:1])

    prev_pc = _root_pc(prev_chord)
    next_pc = _root_pc(next_chord)
    if prev_pc is None or next_pc is None:
        return 0.5

    interval = (next_pc - prev_pc) % 12
    return _COMMON_TRANSITIONS.get(interval, 0.3)


# ===================================================================
# 多重証拠投票 (Confidence-Weighted Voting)
# ===================================================================

def multi_evidence_chord_vote(
    btc_chord: str,
    btc_confidence: float,
    chroma_scores: dict,
    key_name: str,
    prev_chord: Optional[str] = None,
) -> tuple:
    """Combine multiple evidence sources to pick the best chord.

    Evidence sources and their weights:
    - BTC prediction:   weight = btc_confidence
    - Chroma match:     weight = chroma_score × 0.8
    - Diatonic bonus:   +0.2 if chord is diatonic to key
    - Transition bonus: +0.1 if chord follows naturally from previous

    Parameters
    ----------
    btc_chord : str
        Chord predicted by BTC model.
    btc_confidence : float
        BTC model's confidence (0-1).
    chroma_scores : dict
        Mapping {chord_name: chroma_match_score} for candidate chords.
    key_name : str
        Detected key (e.g. "G major").
    prev_chord : str or None
        Previous chord for transition scoring.

    Returns
    -------
    (best_chord, final_confidence) : tuple
        Best chord after voting and its combined confidence.
    """
    diatonic_set = set(_get_diatonic_chords(key_name))

    # Collect all candidate chords (BTC chord + chroma candidates)
    candidates = set(chroma_scores.keys())
    candidates.add(btc_chord)

    best_chord = btc_chord
    best_score = -1.0

    for chord in candidates:
        if chord == 'N.C.':
            continue

        # --- BTC evidence ---
        btc_weight = btc_confidence if chord == btc_chord else 0.0

        # --- Chroma evidence ---
        chroma_weight = chroma_scores.get(chord, 0.0) * 0.8

        # --- Diatonic bonus ---
        diatonic_bonus = 0.2 if chord in diatonic_set else 0.0

        # --- Transition bonus ---
        transition_bonus = 0.0
        if prev_chord is not None:
            trans = _transition_score(prev_chord, chord)
            transition_bonus = trans * 0.1

        total = btc_weight + chroma_weight + diatonic_bonus + transition_bonus

        if total > best_score:
            best_score = total
            best_chord = chord

    # Normalize confidence to [0, 1]
    # Max possible score ≈ 1.0 (btc) + 0.8 (chroma) + 0.2 (diatonic) + 0.1 (transition) = 2.1
    final_confidence = min(1.0, best_score / 2.1) if best_score > 0 else 0.0

    return best_chord, final_confidence


# ===================================================================
# コード検証・補正
# ===================================================================

def _get_diatonic_chords(key_name):
    """キーのダイアトニックコード + よく使う借用和音を返す"""
    from music21 import key as m21key

    try:
        k = m21key.Key(key_name.replace(' major', '').replace(' minor', 'm')
                       if 'minor' in key_name.lower()
                       else key_name.split()[0])
    except Exception:
        return []

    diatonic = []
    # I-VII のトライアド + 7th
    for degree in range(1, 8):
        try:
            ch = k.getChord(degree, 3)  # triad
            if ch:
                from music21 import harmony
                cs = harmony.chordSymbolFromChord(ch)
                diatonic.append(cs.figure)
        except Exception:
            pass
        try:
            ch = k.getChord(degree, 4)  # 7th
            if ch:
                from music21 import harmony
                cs = harmony.chordSymbolFromChord(ch)
                diatonic.append(cs.figure)
        except Exception:
            pass

    return list(set(diatonic))


def verify_and_correct_chords(
    beat_chords,
    beat_times,
    audio_path,
    key_name,
    sr=11025,  # デフォルトを11025Hzにダウンサンプリングして高速化
    correction_threshold=0.25,
    min_improvement=0.15,
    use_hpss=True,  # 11025Hzなら十分に高速なため、精度を維持するHPSSをデフォルトで有効化
):
    """
    BTCの予測コードを音声クロマと照合して検証・補正する。

    Parameters
    ----------
    beat_chords : list of str
        各ビートのコード名 (BTC予測済み)
    beat_times : array-like
        各ビートの時刻 (秒)
    audio_path : str
        音声ファイルパス (WAV)
    key_name : str
        検出済みのキー (例: "G major")
    correction_threshold : float
        この値以下のスコアのコードを補正候補にする
    min_improvement : float
        代替コードのスコアが元のスコアよりこれ以上高い場合のみ差し替え
    use_hpss : bool
        コード検証に調波打楽器分離(HPSS)を利用するかどうか

    Returns
    -------
    verified_chords : list of str
        検証・補正済みコード
    stats : dict
        検証統計 (corrections, avg_score, etc.)
    """
    # テンプレート初期化
    if not _CHORD_PC_CACHE:
        _build_chord_templates()

    # ビート同期クロマを計算 (beat-synchronous CQT)
    beat_chromas = _compute_beat_chroma(audio_path, beat_times, sr=sr, use_hpss=use_hpss)

    # 候補コードリスト: BTCが検出したコードのみ（+ ダイアトニック）
    # ← 全84コードと比較すると GMaj7/BMaj7 など無関係なコードに誤置換される
    chord_counts = Counter(c for c in beat_chords if c != 'N.C.')
    btc_detected = set(chord_counts.keys())

    # ダイアトニックコードも候補に（ただし基本形のみ）
    diatonic_set = set(_get_diatonic_chords(key_name))

    # 候補 = BTC検出コード + ダイアトニック基本形
    # ※ GMaj7/BMaj7/DMaj7 などはここに入らない
    candidate_chords = list(btc_detected | diatonic_set)

    print(f"[ChordVerifier] Candidates restricted to {len(candidate_chords)} chords: {sorted(candidate_chords)[:12]}...")

    verified = list(beat_chords)
    scores = []
    corrections = 0
    correction_log = []

    for i in range(len(beat_chords)):
        chord_name = beat_chords[i]
        if chord_name == 'N.C.':
            continue

        if i >= len(beat_chromas):
            continue

        beat_chroma = beat_chromas[i]

        # 予測コードのスコア
        expected_pcs = get_chord_pitch_classes(chord_name)
        if expected_pcs is None:
            continue

        orig_score = _chord_chroma_score(beat_chroma, expected_pcs)
        scores.append(orig_score)

        # スコアが低い → 多重証拠投票で最適コードを選択
        if orig_score < correction_threshold:
            # 全候補のクロマスコアを計算
            chroma_scores_dict = {}
            for cand in candidate_chords:
                cand_pcs = get_chord_pitch_classes(cand)
                if cand_pcs is None:
                    continue
                chroma_scores_dict[cand] = _chord_chroma_score(beat_chroma, cand_pcs)

            # BTC信頼度はスコアの相対値で推定
            # (外部から渡せない場合のフォールバック)
            btc_confidence = orig_score

            prev_chord = beat_chords[i - 1] if i > 0 else None

            best_chord, vote_confidence = multi_evidence_chord_vote(
                btc_chord=chord_name,
                btc_confidence=btc_confidence,
                chroma_scores=chroma_scores_dict,
                key_name=key_name,
                prev_chord=prev_chord,
            )

            if best_chord != chord_name:
                best_score = chroma_scores_dict.get(best_chord, 0.0)
                if best_score > orig_score + min_improvement:
                    beat_time = beat_times[i] if i < len(beat_times) else 0
                    verified[i] = best_chord
                    corrections += 1
                    correction_log.append(
                        f"  beat {i+1} ({beat_time:.1f}s): {chord_name} ({orig_score:.3f}) -> {best_chord} ({best_score:.3f}, vote={vote_confidence:.3f})"
                    )

    avg_score = np.mean(scores) if scores else 0.0

    stats = {
        'corrections': corrections,
        'total_beats': len([c for c in beat_chords if c != 'N.C.']),
        'avg_score': float(avg_score),
        'correction_log': correction_log,
    }

    print(f"[ChordVerifier] Verified {stats['total_beats']} beats, "
          f"avg_score={avg_score:.3f}, corrections={corrections}")
    if correction_log:
        print(f"[ChordVerifier] Corrections:")
        for line in correction_log[:20]:  # 最大20件表示
            print(line)

    return verified, stats
