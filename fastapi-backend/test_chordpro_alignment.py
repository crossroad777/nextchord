import pytest
from chordpro_converter import _insert_chords_into_lyrics, structured_to_chordpro

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

def test_long_extrapolated_beats():
    # ビートが補完されて、歌詞の終了時間以降まで十分に続いている場合のアライメント確認
    words = [
        {"start": 0.0, "end": 2.0, "word": "未来が"},
        {"start": 2.0, "end": 4.0, "word": "待ってる"}
    ]
    chord_changes = [
        (0.0, "Am"),
        (1.0, "F"),
        (2.0, "C"),
        (3.0, "G")
    ]
    result = _insert_chords_into_lyrics("未来が待ってる", chord_changes, words, phrase_start=0.0, phrase_end=4.0)
    
    assert "[Am]" in result
    assert "[F]" in result
    assert "[C]" in result
    assert "[G]" in result
    assert result.replace("[Am]", "").replace("[F]", "").replace("[C]", "").replace("[G]", "") == "未来が待ってる"

def test_smart_sustained_chord_skipping():
    # 改行（窓の開始）の直後（閾値以内）に別のコードチェンジがある場合、
    # 直前の持続コードが改行の先頭に補填されて重複表示されないことを検証。
    structured_data = [
        # 窓1 (0.0s - 4.0s) の最後のビートで Em が発生
        {"bar": 3, "beat": 3, "time": 2.5, "chord": "C", "section": ""},
        {"bar": 4, "beat": 1, "time": 3.2, "chord": "Em", "section": ""},
        # 窓2 (4.0s - 8.0s) の開始直後 (4.2s) に F が発生
        {"bar": 5, "beat": 1, "time": 4.2, "chord": "F", "section": ""},
        {"bar": 6, "beat": 1, "time": 5.2, "chord": "G", "section": ""}
    ]
    # display_phrases
    display_phrases = [
        {"start": 0.0, "end": 3.5, "text": "未来が僕を待ってる", "words": [
            {"start": 0.0, "end": 1.5, "word": "未来が"},
            {"start": 1.5, "end": 3.5, "word": "僕を待ってる"}
        ]},
        {"start": 4.0, "end": 7.5, "text": "生まれたての太陽と", "words": [
            {"start": 4.0, "end": 5.5, "word": "生まれたての"},
            {"start": 5.5, "end": 7.5, "word": "太陽と"}
        ]}
    ]
    
    # 窓の切り分け位置となる bar_positions (1.0秒間隔で8小節定義)
    bar_positions = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    
    chordpro_text, timings = structured_to_chordpro(
        structured_data,
        display_phrases=display_phrases,
        beats_per_bar=4,
        bar_positions=bar_positions
    )
    
    # 1行目は [C] ... [Em] ... となるはず
    # 2行目は、先頭の [Em] がスキップされて [F]生まれたての ... となるはず (重複 [Em] は無い)
    lines = [line.strip() for line in chordpro_text.split('\n') if line.strip() and not line.startswith('{')]
    
    print("Generated lines:")
    for l in lines:
        print(f"-> {l}")
    
    # lines が 2 行以上あること
    assert len(lines) >= 2
    
    # 1行目に C と Em が含まれていること
    assert "[C]" in lines[0]
    assert "[Em]" in lines[0]
    
    # 2行目に Em が含まれておらず、F があること
    assert "[Em]" not in lines[1]
    assert "[F]" in lines[1]
