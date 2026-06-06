import pytest
from chordpro_converter import _insert_chords_into_lyrics

def test_no_words_fallback():
    # wordsが空の場合、全体に対する時間比率で線形配置されること
    text = "走る"
    chord_changes = [(0.0, "C"), (5.0, "G")]
    result = _insert_chords_into_lyrics(text, chord_changes, words=[], phrase_start=0.0, phrase_end=10.0)
    
    assert "[C]" in result
    assert "[G]" in result
    assert result.replace("[C]", "").replace("[G]", "") == text

def test_initial_gap_alignment():
    # 冒頭に2秒のギャップがある場合
    text = "走る"
    words = [
        {"start": 2.0, "end": 4.0, "word": "走る"}
    ]
    chord_changes = [
        (0.5, "C"),  # ギャップ内
        (2.0, "F")   # 単語の頭 (G以外にしてCherryヒューリスティック回避)
    ]
    # phrase_start=0.0, phrase_end=4.0
    result = _insert_chords_into_lyrics(text, chord_changes, words, phrase_start=0.0, phrase_end=4.0)
    
    assert "[C]" in result
    # Fは「走る」の直前に挿入されるはず
    assert "[F]走る" in result
    assert "走る" in result
    # 最初のスペース部分に [C] がある
    assert result.startswith(" ") or result.startswith("[C]")

def test_middle_gap_alignment():
    # 単語の間に2秒のギャップがある場合
    words = [
        {"start": 0.0, "end": 1.0, "word": "君を"},
        {"start": 3.0, "end": 5.0, "word": "走る"}
    ]
    # 1.0s から 3.0s まではギャップ
    chord_changes = [
        (0.0, "C"),  # 「君を」の頭
        (2.0, "Am"), # ギャップの真ん中
        (3.0, "F")   # 「走る」の頭
    ]
    result = _insert_chords_into_lyrics("君を走る", chord_changes, words, phrase_start=0.0, phrase_end=5.0)
    
    assert "[C]君を" in result
    assert "[F]走る" in result
    assert "[Am]" in result
    parts = result.split("[Am]")
    assert "君を" in parts[0]
    assert "走る" in parts[1]
    assert " " in result
    assert "君を" in result and "走る" in result

def test_end_gap_alignment():
    # 末尾にギャップがある場合
    words = [
        {"start": 0.0, "end": 2.0, "word": "チェリー"}
    ]
    chord_changes = [
        (0.0, "C"),
        (3.5, "F")  # 最後の単語より後ろのギャップ (G以外にしてヒューリスティック回避)
    ]
    result = _insert_chords_into_lyrics("チェリー", chord_changes, words, phrase_start=0.0, phrase_end=4.0)
    
    assert "[C]チェリー" in result
    assert "[F]" in result
    parts = result.split("チェリー")
    assert "[F]" in parts[1]
    assert "チェリー" in result

def test_cherry_heuristics():
    # チェリーの「忘れない」「戻れない」のGコードの配置補正
    # 「忘れない」の3文字目「な」の直後にGが入るはず
    words = [
        {"start": 0.0, "end": 2.0, "word": "忘れない"}
    ]
    chord_changes = [
        (1.4, "G")  # 「な」の付近の時間
    ]
    result = _insert_chords_into_lyrics("忘れない", chord_changes, words, phrase_start=0.0, phrase_end=2.0)
    # 忘(0)れ(1)な(2)い(3) の index=3 に補正される -> "忘れな[G]い" となるはず
    assert "忘れな[G]い" in result

def test_no_chords():
    # コード変更がない場合はテキストがそのまま返る
    assert _insert_chords_into_lyrics("テスト", [], None) == "テスト"

def test_single_chord():
    # コードが1つだけの場合は先頭付近に付与 (wordsがない場合)
    result = _insert_chords_into_lyrics("テスト", [(0.0, "C")], None)
    assert "[C]テスト" in result
