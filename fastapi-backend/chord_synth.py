"""
chord_synth.py
全コードの音声を numpy で合成する。
ピアノ音色（倍音付き ADSR エンベロープ）。
"""
from __future__ import annotations
import io
import struct
import math
import numpy as np
from typing import List, Optional

# ============================================================
# 音名 → MIDI番号 / 周波数変換
# ============================================================

NOTE_MAP = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7,
    'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11,
}

CHORD_INTERVALS = {
    '':      [0, 4, 7],              # メジャー
    'maj':   [0, 4, 7],
    'm':     [0, 3, 7],              # マイナー
    'min':   [0, 3, 7],
    '7':     [0, 4, 7, 10],          # ドミナント7
    'maj7':  [0, 4, 7, 11],          # メジャー7
    'm7':    [0, 3, 7, 10],          # マイナー7
    'dim':   [0, 3, 6],              # ディミニッシュ
    'dim7':  [0, 3, 6, 9],           # ディミニッシュ7
    'aug':   [0, 4, 8],              # オーギュメント
    'sus4':  [0, 5, 7],              # サスペンデッド4
    'sus2':  [0, 2, 7],              # サスペンデッド2
    'm7b5':  [0, 3, 6, 10],          # ハーフディミニッシュ
    'add9':  [0, 4, 7, 14],          # アド9
    '6':     [0, 4, 7, 9],           # 6th
    'm6':    [0, 3, 7, 9],           # マイナー6
    '9':     [0, 4, 7, 10, 14],      # ドミナント9th
    'maj9':  [0, 4, 7, 11, 14],      # メジャー9th
    'm9':    [0, 3, 7, 10, 14],      # マイナー9th
    'add2':  [0, 2, 4, 7],           # アド2（=add9簡易版）
    '11':    [0, 4, 7, 10, 14, 17],  # 11th
    '13':    [0, 4, 7, 10, 14, 21],  # 13th
}


def midi_to_hz(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def parse_chord(chord_name: str):
    """
    コード名をパースして (root_pc, intervals) を返す。
    例: 'Am7' → (9, [0,3,7,10])
        'Fmaj7' → (5, [0,4,7,11])
        'G7' → (7, [0,4,7,10])
    """
    if not chord_name or chord_name in ('N', 'N.C.', 'X'):
        return None, []

    # BTC形式 'C:maj' → 'C'
    if ':' in chord_name:
        root_str, qual = chord_name.split(':', 1)
        qual_map = {
            'maj': '', 'min': 'm', '7': '7', 'maj7': 'maj7',
            'min7': 'm7', 'dim': 'dim', 'aug': 'aug',
            'sus4': 'sus4', 'sus2': 'sus2', 'hdim7': 'm7b5',
        }
        quality = qual_map.get(qual, '')
        chord_name = root_str + quality

    # ルート音を解析
    root_str = None
    suffix = ''
    if len(chord_name) >= 2 and chord_name[1] in ('#', 'b'):
        root_str = chord_name[:2]
        suffix = chord_name[2:]
    else:
        root_str = chord_name[:1]
        suffix = chord_name[1:]

    root_pc = NOTE_MAP.get(root_str)
    if root_pc is None:
        return None, []

    intervals = CHORD_INTERVALS.get(suffix, CHORD_INTERVALS.get(suffix.lower(), [0, 4, 7]))
    return root_pc, intervals


def synthesize_chord(
    chord_name: str,
    octave: int = 4,
    duration: float = 1.8,
    sr: int = 44100,
    volume: float = 0.75,
) -> bytes:
    """
    コード名から WAV バイナリを生成する。

    Parameters
    ----------
    chord_name : str
        コード名 ('C', 'Am', 'G7', 'Fmaj7', ...)
    octave : int
        ルート音のオクターブ (4 = 中央付近)
    duration : float
        音の長さ（秒）
    sr : int
        サンプルレート
    volume : float
        音量 (0.0-1.0)

    Returns
    -------
    bytes
        WAV ファイルバイナリ
    """
    root_pc, intervals = parse_chord(chord_name)
    if root_pc is None or not intervals:
        # 無音を返す
        return _make_wav(np.zeros(int(sr * duration), dtype=np.int16), sr)

    # MIDI ノート番号の計算
    root_midi = (octave + 1) * 12 + root_pc  # C4 = 60
    midi_notes = [root_midi + iv for iv in intervals]
    
    # 高音が出すぎないよう1オクターブ下げる
    # (例: add9 の14半音上は1オクターブ上 → 折りたたむ)
    adjusted_notes = []
    for n in midi_notes:
        while n > root_midi + 12:
            n -= 12
        adjusted_notes.append(n)

    # 周波数リスト
    freqs = [midi_to_hz(n) for n in adjusted_notes]

    # 時間軸
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    audio = np.zeros(len(t), dtype=np.float64)

    # ピアノ音色: 倍音合成
    harmonic_amps = [1.0, 0.6, 0.35, 0.2, 0.12, 0.07]
    for freq in freqs:
        note_wave = np.zeros(len(t), dtype=np.float64)
        for h, amp in enumerate(harmonic_amps, start=1):
            note_wave += amp * np.sin(2 * np.pi * freq * h * t)
        audio += note_wave

    # ADSR エンベロープ
    attack  = 0.01   # 秒
    decay   = 0.15
    sustain = 0.55   # レベル (0-1)
    release = 0.5

    n_total = len(t)
    n_atk = int(attack  * sr)
    n_dcy = int(decay   * sr)
    n_rel = int(release * sr)
    n_sus = max(0, n_total - n_atk - n_dcy - n_rel)

    env = np.concatenate([
        np.linspace(0.0, 1.0,     n_atk),        # attack
        np.linspace(1.0, sustain, n_dcy),         # decay
        np.full(n_sus, sustain),                  # sustain
        np.linspace(sustain, 0.0, n_rel),         # release
    ])
    env = env[:n_total]
    audio = audio * env

    # 正規化・音量調整
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * volume

    # 16bit PCM に変換
    audio_int16 = (audio * 32767).clip(-32767, 32767).astype(np.int16)
    return _make_wav(audio_int16, sr)


def _make_wav(samples: np.ndarray, sr: int) -> bytes:
    """numpy int16 配列を WAV バイナリに変換"""
    buf = io.BytesIO()
    n_samples = len(samples)
    n_channels = 1
    bit_depth = 16
    byte_rate = sr * n_channels * bit_depth // 8
    block_align = n_channels * bit_depth // 8
    data_size = n_samples * block_align

    # WAV ヘッダ
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + data_size))
    buf.write(b'WAVE')
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))           # chunk size
    buf.write(struct.pack('<H', 1))            # PCM
    buf.write(struct.pack('<H', n_channels))
    buf.write(struct.pack('<I', sr))
    buf.write(struct.pack('<I', byte_rate))
    buf.write(struct.pack('<H', block_align))
    buf.write(struct.pack('<H', bit_depth))
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(samples.tobytes())
    return buf.getvalue()


# ============================================================
# 全コード一括生成
# ============================================================

ALL_ROOTS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
ALL_TYPES = ['', 'm', '7', 'maj7', 'm7', 'dim', 'aug', 'sus4', 'sus2', 'm7b5']

def get_all_chords() -> List[str]:
    """全コード名リストを返す"""
    chords = []
    for root in ALL_ROOTS:
        for ctype in ALL_TYPES:
            chords.append(root + ctype)
    return chords


if __name__ == '__main__':
    # テスト: Cメジャー を生成して保存
    import pathlib, sys
    out = pathlib.Path('chord_test.wav')
    wav = synthesize_chord('C', octave=4, duration=2.0)
    out.write_bytes(wav)
    print(f'Generated: {out} ({len(wav)} bytes)')
    
    wav_am = synthesize_chord('Am', octave=4, duration=2.0)
    pathlib.Path('chord_test_am.wav').write_bytes(wav_am)
    print('Generated: chord_test_am.wav')
    
    wav_g7 = synthesize_chord('G7', octave=3, duration=2.0)
    pathlib.Path('chord_test_g7.wav').write_bytes(wav_g7)
    print('Generated: chord_test_g7.wav')
    
    print(f'Total chords: {len(get_all_chords())}')
