"""
NextChord Unit Tests -- export_utils.py
======================================
MIDI/PDF/テキストエクスポートのユニットテスト。

Usage:
    python -m pytest test_export_utils.py -v
"""

import pytest
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from export_utils import (
    parse_chord,
    get_char_width,
    get_str_width,
    pad_visual,
    create_text_score,
    create_midi,
)


# =========================================================================
#  parse_chord
# =========================================================================

class TestParseChord:
    """コードパーサーのテスト"""

    def test_c_major(self):
        root, offsets = parse_chord("C")
        assert root == 0  # C = 0
        assert offsets is not None
        assert 0 in offsets  # root

    def test_am(self):
        root, offsets = parse_chord("Am")
        assert root == 9  # A = 9
        assert offsets is not None

    def test_fsharp(self):
        root, offsets = parse_chord("F#")
        assert root == 6  # F# = 6

    def test_bb(self):
        root, offsets = parse_chord("Bb")
        assert root == 10  # Bb = 10

    def test_nc(self):
        root, offsets = parse_chord("N.C.")
        assert root is None
        assert offsets is None

    def test_n(self):
        root, offsets = parse_chord("N")
        assert root is None

    def test_empty(self):
        root, offsets = parse_chord("")
        assert root is None

    def test_none(self):
        root, offsets = parse_chord(None)
        assert root is None

    def test_seventh(self):
        root, offsets = parse_chord("G7")
        assert root == 7  # G = 7
        assert offsets is not None

    def test_minor_seventh(self):
        root, offsets = parse_chord("Em7")
        assert root == 4  # E = 4


# =========================================================================
#  get_char_width / get_str_width / pad_visual
# =========================================================================

class TestCharWidth:
    """文字幅計算のテスト"""

    def test_ascii(self):
        assert get_char_width("A") == 1
        assert get_char_width(" ") == 1

    def test_japanese(self):
        assert get_char_width("あ") == 2
        assert get_char_width("ア") == 2
        assert get_char_width("漢") == 2

    def test_str_width_ascii(self):
        assert get_str_width("Hello") == 5

    def test_str_width_japanese(self):
        assert get_str_width("こんにちは") == 10

    def test_str_width_mixed(self):
        assert get_str_width("Amこんにちは") == 12  # 2 + 10

    def test_str_width_empty(self):
        assert get_str_width("") == 0


class TestPadVisual:
    """ビジュアルパディングのテスト"""

    def test_pad_ascii(self):
        result = pad_visual("Am", 6)
        assert get_str_width(result) == 6

    def test_pad_japanese(self):
        result = pad_visual("あ", 6)
        # "あ" = 幅2, パディング4スペース
        assert get_str_width(result) == 6

    def test_no_pad_needed(self):
        result = pad_visual("ABCDEF", 6)
        assert result == "ABCDEF"

    def test_overflow(self):
        """target_wより長い文字列はそのまま"""
        result = pad_visual("ABCDEFGH", 4)
        assert result == "ABCDEFGH"


# =========================================================================
#  create_text_score
# =========================================================================

class TestCreateTextScore:
    """テキストスコア生成のテスト"""

    def test_basic(self):
        data = [
            {"bar": 1, "beat": 1, "chord": "C", "lyric": "Hello", "time": 0.0, "duration": 0.5, "section": ""},
            {"bar": 1, "beat": 2, "chord": "G", "lyric": "World", "time": 0.5, "duration": 0.5, "section": ""},
            {"bar": 1, "beat": 3, "chord": "Am", "lyric": "", "time": 1.0, "duration": 0.5, "section": ""},
            {"bar": 1, "beat": 4, "chord": "F", "lyric": "", "time": 1.5, "duration": 0.5, "section": ""},
        ]
        result = create_text_score(data)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "C" in result

    def test_empty_data(self):
        result = create_text_score([])
        assert isinstance(result, str)

    def test_nc_only(self):
        data = [
            {"bar": 1, "beat": 1, "chord": "N.C.", "lyric": "", "time": 0.0, "duration": 0.5, "section": ""},
        ]
        result = create_text_score(data)
        assert isinstance(result, str)

    def test_japanese_lyrics(self):
        data = [
            {"bar": 1, "beat": 1, "chord": "C", "lyric": "さくら", "time": 0.0, "duration": 0.5, "section": ""},
            {"bar": 1, "beat": 2, "chord": "Am", "lyric": "の花", "time": 0.5, "duration": 0.5, "section": ""},
            {"bar": 1, "beat": 3, "chord": "F", "lyric": "", "time": 1.0, "duration": 0.5, "section": ""},
            {"bar": 1, "beat": 4, "chord": "G", "lyric": "", "time": 1.5, "duration": 0.5, "section": ""},
        ]
        result = create_text_score(data)
        assert "さくら" in result or "C" in result


# =========================================================================
#  create_midi
# =========================================================================

class TestCreateMidi:
    """MIDI生成のテスト"""

    def test_basic_midi(self):
        data = [
            {"bar": 1, "beat": 1, "chord": "C", "time": 0.0, "duration": 0.5},
            {"bar": 1, "beat": 2, "chord": "G", "time": 0.5, "duration": 0.5},
            {"bar": 1, "beat": 3, "chord": "Am", "time": 1.0, "duration": 0.5},
            {"bar": 1, "beat": 4, "chord": "F", "time": 1.5, "duration": 0.5},
        ]
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            out_path = f.name
        try:
            create_midi(data, out_path, bpm=120)
            assert Path(out_path).exists()
            assert Path(out_path).stat().st_size > 0
        finally:
            Path(out_path).unlink(missing_ok=True)

    def test_midi_with_key(self):
        data = [{"bar": 1, "beat": 1, "chord": "Am", "time": 0.0, "duration": 0.5}]
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            out_path = f.name
        try:
            create_midi(data, out_path, bpm=120, key="A minor")
            assert Path(out_path).exists()
        finally:
            Path(out_path).unlink(missing_ok=True)

    def test_midi_nc_chords(self):
        """N.C. コードのみでもクラッシュしない"""
        data = [{"bar": 1, "beat": i, "chord": "N.C.", "time": i * 0.5, "duration": 0.5} for i in range(1, 5)]
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            out_path = f.name
        try:
            create_midi(data, out_path)
            assert Path(out_path).exists()
        finally:
            Path(out_path).unlink(missing_ok=True)

    def test_midi_empty(self):
        """空データでもクラッシュしない"""
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            out_path = f.name
        try:
            create_midi([], out_path)
            assert Path(out_path).exists()
        finally:
            Path(out_path).unlink(missing_ok=True)
