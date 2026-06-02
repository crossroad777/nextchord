"""
NextChord - コード確信度フィルタ v2
====================================
HMM Viterbiによるルート/品質補正はBeatles 180曲ベンチマークで
常に精度を悪化させることが判明した。

代替アプローチ: BTCの確信度が低いビートのみ、
ダイアトニック代替を探して差し替える。
確信度が高ければBTC予測をそのまま信頼する。

ベンチマーク結果:
  HMM v1 (品質変更あり): -16.7% → 完全に有害
  HMM v2 (ルートのみ):   -0.33% → 微小だが改善なし
  → HMMアプローチは廃止
"""

import numpy as np
from pathlib import Path
from collections import Counter

_ROOT_TO_PC = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
    'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11
}

_DIATONIC_MAJOR_ROOTS = {0, 2, 4, 5, 7, 9, 11}
_DIATONIC_MINOR_ROOTS = {0, 2, 3, 5, 7, 8, 10}


def _extract_root_pc(chord_name):
    if not chord_name or chord_name in ('N', 'N.C.', 'X'):
        return None
    if ':' in chord_name:
        root_str = chord_name.split(':')[0]
    elif len(chord_name) > 1 and chord_name[1] in '#b':
        root_str = chord_name[:2]
    else:
        root_str = chord_name[:1]
    return _ROOT_TO_PC.get(root_str)


def confidence_filter(
    beat_chords,
    key_name,
    confidences,
    threshold=0.25,
):
    """
    低確信度ビートのみN.C.に置換する。

    BTCの確信度が threshold 未満のビートを N.C. にする。
    HMMのような「別のコードに変える」アプローチは使わない。

    Parameters
    ----------
    beat_chords : list of str
    key_name : str
    confidences : list of float
    threshold : float

    Returns
    -------
    list of str
    """
    if not beat_chords or not confidences:
        return list(beat_chords)

    result = list(beat_chords)
    n_filtered = 0

    for i in range(len(result)):
        if i >= len(confidences):
            break
        if confidences[i] < threshold and result[i] not in ('N', 'N.C.', 'X'):
            result[i] = 'N.C.'
            n_filtered += 1

    if n_filtered > 0:
        print(f"[ChordFilter] Filtered {n_filtered}/{len(result)} low-confidence beats "
              f"(threshold={threshold})")

    return result


# 後方互換性のため viterbi_chord_correction はダミーとして残す
def viterbi_chord_correction(beat_chords, key_name, confidences=None, transition_weight=0.15):
    """HMM Viterbiは廃止。入力をそのまま返す。"""
    return list(beat_chords)
