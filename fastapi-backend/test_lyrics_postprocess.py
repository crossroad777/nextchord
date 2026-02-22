"""
NextChord Unit Tests — lyrics_postprocess.py
=============================================
歌詞後処理のユニットテスト。

Usage:
    python -m pytest test_lyrics_postprocess.py -v
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from lyrics_postprocess import (
    postprocess_japanese_lyrics,
    postprocess_whisper_segments,
    clean_hallucinated_endings,
)


# =========================================================================
#  postprocess_japanese_lyrics
# =========================================================================

class TestPostprocessJapaneseLyrics:
    """日本語歌詞テキスト後処理のテスト"""

    def test_empty(self):
        assert postprocess_japanese_lyrics("") == ""

    def test_none(self):
        assert postprocess_japanese_lyrics(None) is None

    def test_no_change(self):
        """変更不要なテキストはそのまま"""
        assert postprocess_japanese_lyrics("遠回りしてたどり着くから") == "遠回りしてたどり着くから"

    def test_unicode_normalize(self):
        """半角カタカナ → 全角カタカナ"""
        assert "ア" in postprocess_japanese_lyrics("ｱ")

    def test_remove_jp_spaces(self):
        """日本語文字間の不要スペース除去"""
        result = postprocess_japanese_lyrics("こんにちは 世界")
        assert "こんにちは世界" == result

    def test_keep_en_spaces(self):
        """英単語間のスペースは保持"""
        result = postprocess_japanese_lyrics("Hello World")
        assert " " in result

    def test_remove_hallucination_credit(self):
        """ハルシネーションクレジット除去"""
        result = postprocess_japanese_lyrics("作詞・作曲・編曲・編曲")
        assert result == ""

    def test_remove_hallucination_thanks(self):
        result = postprocess_japanese_lyrics("ご視聴ありがとうございました")
        assert result == ""

    def test_repeated_chars(self):
        """4回以上の連続文字を2回に制限"""
        result = postprocess_japanese_lyrics("ああああああ")
        assert result == "ああ"

    def test_long_vowel_preserved(self):
        """長音ーは繰り返し制限の対象外"""
        result = postprocess_japanese_lyrics("ずーーーーっと")
        assert "ーーーー" in result

    def test_punctuation_normalize(self):
        """全角ピリオドはNFKCで半角ピリオドに変換される"""
        result = postprocess_japanese_lyrics("こんにちは．世界")
        # NFKC正規化が先に適用され '．' → '.'
        assert "." in result or "。" in result


# =========================================================================
#  postprocess_whisper_segments
# =========================================================================

class TestPostprocessWhisperSegments:
    """Whisperセグメント後処理のテスト"""

    def test_empty(self):
        assert postprocess_whisper_segments([]) == []

    def test_none(self):
        assert postprocess_whisper_segments(None) is None

    def test_basic(self):
        segments = [
            {"text": "こんにちは", "start": 0.0, "end": 1.0},
            {"text": "世界", "start": 1.0, "end": 2.0},
        ]
        result = postprocess_whisper_segments(segments)
        assert len(result) == 2

    def test_removes_empty(self):
        """空テキストのセグメントは除去"""
        segments = [
            {"text": "こんにちは", "start": 0.0, "end": 1.0},
            {"text": "作詞・作曲", "start": 5.0, "end": 6.0},  # → 空になる
        ]
        result = postprocess_whisper_segments(segments)
        assert len(result) == 1

    def test_dedup_consecutive(self):
        """連続する同一テキストの重複除去"""
        segments = [
            {"text": "ラララ", "start": 0.0, "end": 1.0},
            {"text": "ラララ", "start": 1.0, "end": 2.0},
            {"text": "歌おう", "start": 2.0, "end": 3.0},
        ]
        result = postprocess_whisper_segments(segments)
        assert len(result) == 2

    def test_word_level_processing(self):
        """単語レベルのタイムスタンプも処理"""
        segments = [
            {
                "text": "こんにちは",
                "start": 0.0,
                "end": 1.0,
                "words": [
                    {"word": "こんにちは", "start": 0.0, "end": 1.0},
                ]
            },
        ]
        result = postprocess_whisper_segments(segments)
        assert len(result) == 1
        assert "words" in result[0]


# =========================================================================
#  clean_hallucinated_endings
# =========================================================================

class TestCleanHallucinatedEndings:
    """ハルシネーション除去テスト"""

    def test_empty(self):
        assert clean_hallucinated_endings([]) == []

    def test_none(self):
        assert clean_hallucinated_endings(None) is None

    def test_no_hallucination(self):
        phrases = [
            {"text": "さくらの花", "start": 0.0, "end": 1.0},
            {"text": "咲く頃に", "start": 1.0, "end": 2.0},
        ]
        result = clean_hallucinated_endings(phrases)
        assert len(result) == 2

    def test_removes_credit(self):
        """作詞/作曲クレジットを除去"""
        phrases = [
            {"text": "さくらの花", "start": 0.0, "end": 1.0},
            {"text": "作詞: 山田太郎", "start": 5.0, "end": 6.0},
        ]
        result = clean_hallucinated_endings(phrases)
        assert len(result) == 1

    def test_removes_mv(self):
        """MV/PV表記を除去"""
        phrases = [
            {"text": "歌詞", "start": 0.0, "end": 1.0},
            {"text": "Music Video", "start": 5.0, "end": 6.0},
        ]
        result = clean_hallucinated_endings(phrases)
        assert len(result) == 1

    def test_removes_empty(self):
        """空テキストフレーズを除去"""
        phrases = [
            {"text": "歌詞", "start": 0.0, "end": 1.0},
            {"text": "   ", "start": 5.0, "end": 6.0},
        ]
        result = clean_hallucinated_endings(phrases)
        assert len(result) == 1
