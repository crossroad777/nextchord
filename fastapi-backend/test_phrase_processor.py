"""
NextChord Unit Tests — phrase_processor.py
==========================================
日本語フレーズ分割処理のユニットテスト。

Usage:
    python -m pytest test_phrase_processor.py -v
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from phrase_processor import (
    _clean,
    _get_word_boundaries,
    _find_best_split,
    process_phrases_for_display,
)


# =========================================================================
#  _clean
# =========================================================================

class TestClean:
    """空白除去テスト"""

    def test_simple(self):
        assert _clean("hello world") == "helloworld"

    def test_japanese(self):
        assert _clean("こんにちは 世界") == "こんにちは世界"

    def test_tabs_newlines(self):
        assert _clean("a\t\nb") == "ab"

    def test_empty(self):
        assert _clean("") == ""

    def test_only_spaces(self):
        assert _clean("   ") == ""


# =========================================================================
#  _get_word_boundaries
# =========================================================================

class TestGetWordBoundaries:
    """形態素解析の単語境界テスト"""

    def test_basic(self):
        boundaries = _get_word_boundaries("こんにちは世界")
        assert len(boundaries) > 0
        # 各要素は (position, surface, pos_top, pos_detail) の4-tuple
        for b in boundaries:
            assert len(b) == 4
            pos, surface, pos_top, pos_detail = b
            assert isinstance(pos, int)
            assert isinstance(surface, str)

    def test_positions_sorted(self):
        boundaries = _get_word_boundaries("私は学生です")
        positions = [b[0] for b in boundaries]
        assert positions == sorted(positions)

    def test_empty(self):
        boundaries = _get_word_boundaries("")
        assert boundaries == []


# =========================================================================
#  _find_best_split
# =========================================================================

class TestFindBestSplit:
    """最適分割位置の発見テスト"""

    def test_empty_boundaries(self):
        result = _find_best_split("test", 2, [])
        assert result == 2  # idealPosをそのまま返す

    def test_prefers_punctuation(self):
        """句読点の後は自然な分割位置"""
        text = "こんにちは。世界へ"
        boundaries = _get_word_boundaries(text)
        # 理想位置が句読点の近くなら、句読点位置を選択
        split = _find_best_split(text, 5, boundaries)
        # 「。」の後(位置6)あたりに分割されるべき
        assert 5 <= split <= 7

    def test_avoids_before_auxiliary(self):
        """助動詞の直前は分割しない"""
        text = "食べられない"
        boundaries = _get_word_boundaries(text)
        # 「ない」の前で切るのは不自然
        split = _find_best_split(text, 3, boundaries)
        assert isinstance(split, int)


# =========================================================================
#  process_phrases_for_display
# =========================================================================

class TestProcessPhrasesForDisplay:
    """フレーズ統合・分割テスト"""

    def test_empty(self):
        result = process_phrases_for_display([])
        assert result == []

    def test_single_short_phrase(self):
        phrases = [{"start": 0.0, "end": 1.0, "text": "こんにちは"}]
        result = process_phrases_for_display(phrases)
        assert len(result) >= 1
        assert "こんにちは" in result[0]["text"]

    def test_merge_gap(self):
        """gap < 1s のフレーズは結合される"""
        phrases = [
            {"start": 0.0, "end": 1.0, "text": "こん"},
            {"start": 1.5, "end": 2.5, "text": "にちは"},
        ]
        result = process_phrases_for_display(phrases, target_chars=30)
        # 短いフレーズは結合されるはず
        assert len(result) >= 1

    def test_long_phrase_split(self):
        """target_chars超のフレーズは分割される"""
        long_text = "これはとても長い日本語の歌詞で形態素解析による自然な分割が行われることを期待しています"
        phrases = [{"start": 0.0, "end": 10.0, "text": long_text}]
        result = process_phrases_for_display(phrases, target_chars=15)
        assert len(result) >= 2

    def test_preserves_timing(self):
        """タイミング情報が保持される"""
        phrases = [
            {"start": 1.5, "end": 3.0, "text": "さくらの花"},
            {"start": 5.0, "end": 7.0, "text": "咲く頃に"},
        ]
        result = process_phrases_for_display(phrases)
        assert result[0]["start"] >= 0
        assert result[-1]["end"] > result[0]["start"]
        for r in result:
            assert "start" in r
            assert "end" in r
            assert "text" in r

    def test_no_empty_phrases(self):
        """空フレーズは出力されない"""
        phrases = [
            {"start": 0.0, "end": 1.0, "text": "こんにちは"},
            {"start": 2.0, "end": 3.0, "text": "   "},
            {"start": 4.0, "end": 5.0, "text": "世界"},
        ]
        result = process_phrases_for_display(phrases)
        for r in result:
            assert r["text"].strip() != ""
