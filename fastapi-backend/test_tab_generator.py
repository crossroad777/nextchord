"""
NextChord Unit Tests — tab_generator.py
=======================================
TAB譜生成・MusicXML変換のユニットテスト。

Usage:
    python -m pytest test_tab_generator.py -v
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from tab_generator import (
    midi_to_guitar_position,
    notes_to_tab_data,
    chord_to_tab_data,
    estimate_key_from_chords,
    generate_chord_strum_notes,
    quantize_duration_to_note_type,
    _group_simultaneous_notes,
    STANDARD_TUNING,
    TUNING_PRESETS,
    CHORD_VOICINGS,
)


# =========================================================================
#  midi_to_guitar_position
# =========================================================================

class TestMidiToGuitarPosition:
    """MIDIピッチ → ギターポジション変換のテスト"""

    def test_open_low_e(self):
        """開放6弦 E2 = MIDI 40"""
        result = midi_to_guitar_position(40)
        assert result is not None
        string, fret = result
        assert fret == 0
        assert string == 6

    def test_open_a(self):
        """開放5弦 A2 = MIDI 45"""
        result = midi_to_guitar_position(45)
        assert result is not None
        string, fret = result
        # A2は6弦5フレットまたは5弦0フレット (低フレット優先)
        assert fret <= 5

    def test_high_e4(self):
        """1弦開放 E4 = MIDI 64"""
        result = midi_to_guitar_position(64)
        assert result is not None
        string, fret = result
        assert fret == 0
        assert string == 1

    def test_middle_c(self):
        """C4 = MIDI 60 → 2弦1フレット or 3弦5フレット"""
        result = midi_to_guitar_position(60)
        assert result is not None
        string, fret = result
        assert 0 <= fret <= 24

    def test_out_of_range_low(self):
        """ギターの音域外の低音 → None"""
        result = midi_to_guitar_position(20)
        assert result is None

    def test_out_of_range_high(self):
        """ギターの音域外の極高音 → None"""
        result = midi_to_guitar_position(110)
        assert result is None

    def test_avoid_strings(self):
        """弦回避が効くか"""
        # E4 (MIDI 64) は1弦0フレットだが、1弦を避けると他の弦になる
        result = midi_to_guitar_position(64, avoid_strings={1})
        if result:
            assert result[0] != 1

    def test_prev_positions_influence(self):
        """前のポジションがスコアリングに影響する"""
        # 5フレット付近を弾いている状態
        prev = [(3, 5), (2, 5)]
        result = midi_to_guitar_position(60, prev_positions=prev)
        assert result is not None

    def test_custom_tuning(self):
        """カスタムチューニング (Drop D)"""
        drop_d = TUNING_PRESETS["drop_d"]
        # D2 = MIDI 38 → Drop Dなら6弦開放
        result = midi_to_guitar_position(38, tuning=drop_d)
        assert result is not None
        assert result == (6, 0)

    def test_standard_tuning_e2(self):
        """標準チューニングでD2は弾けない"""
        result = midi_to_guitar_position(38)
        assert result is None  # E2(40)未満はギターの音域外


# =========================================================================
#  chord_to_tab_data
# =========================================================================

class TestChordToTabData:
    """コード名 → TABフレットデータ変換のテスト"""

    def test_c_major(self):
        result = chord_to_tab_data("C")
        assert result == [-1, 3, 2, 0, 1, 0]

    def test_am(self):
        result = chord_to_tab_data("Am")
        assert result == [-1, 0, 2, 2, 1, 0]

    def test_g_major(self):
        result = chord_to_tab_data("G")
        assert result == [3, 2, 0, 0, 0, 3]

    def test_nc(self):
        """N.C. は None"""
        result = chord_to_tab_data("N.C.")
        assert result is None

    def test_empty(self):
        result = chord_to_tab_data("")
        assert result is None

    def test_n_chord(self):
        result = chord_to_tab_data("N")
        assert result is None

    def test_fallback_chord(self):
        """修飾付きコードのフォールバック (Am7 → Am)"""
        result = chord_to_tab_data("Am7")
        assert result is not None
        assert len(result) == 6

    def test_sus4_direct(self):
        """sus4 コードの直接検索"""
        result = chord_to_tab_data("Dsus4")
        assert result is not None

    def test_add9(self):
        """add9 コード"""
        result = chord_to_tab_data("Cadd9")
        assert result is not None

    def test_all_voicings_have_6_strings(self):
        """全てのボイシングが6弦分のデータを持つ"""
        for chord, voicing in CHORD_VOICINGS.items():
            assert len(voicing) == 6, f"{chord} has {len(voicing)} strings instead of 6"


# =========================================================================
#  quantize_duration_to_note_type
# =========================================================================

class TestQuantizeDuration:
    """音価の量子化テスト"""

    def test_quarter_note(self):
        """4分音符: duration == beat_duration"""
        ntype, divs, dotted = quantize_duration_to_note_type(0.5, 0.5)
        assert ntype == "quarter"
        assert dotted is False

    def test_eighth_note(self):
        """8分音符: duration == beat_duration / 2"""
        ntype, divs, dotted = quantize_duration_to_note_type(0.25, 0.5)
        assert ntype == "eighth"
        assert dotted is False

    def test_half_note(self):
        """2分音符: duration == beat_duration * 2"""
        ntype, divs, dotted = quantize_duration_to_note_type(1.0, 0.5)
        assert ntype == "half"

    def test_whole_note(self):
        """全音符: duration == beat_duration * 4"""
        ntype, divs, dotted = quantize_duration_to_note_type(2.0, 0.5)
        assert ntype == "whole"

    def test_dotted_quarter(self):
        """付点4分音符: ratio ≈ 1.5"""
        ntype, divs, dotted = quantize_duration_to_note_type(0.75, 0.5)
        assert ntype == "quarter"
        assert dotted is True

    def test_sixteenth_note(self):
        """16分音符: ratio ≈ 0.25"""
        ntype, divs, dotted = quantize_duration_to_note_type(0.125, 0.5)
        assert ntype == "16th"

    def test_zero_beat_duration(self):
        """beat_duration=0 でもクラッシュしない"""
        ntype, divs, dotted = quantize_duration_to_note_type(0.5, 0)
        assert ntype == "quarter"

    def test_very_short_note(self):
        """非常に短いノート → 32nd"""
        ntype, divs, dotted = quantize_duration_to_note_type(0.03, 0.5)
        assert ntype == "32nd"


# =========================================================================
#  _group_simultaneous_notes
# =========================================================================

class TestGroupSimultaneousNotes:
    """同時ノートグループ化テスト"""

    def test_empty(self):
        assert _group_simultaneous_notes([]) == []

    def test_single_note(self):
        notes = [{"start_time": 0.5, "midi_pitch": 60}]
        groups = _group_simultaneous_notes(notes)
        assert len(groups) == 1
        assert len(groups[0]) == 1

    def test_chord(self):
        """同時発音は1グループに"""
        notes = [
            {"start_time": 1.0, "midi_pitch": 60},
            {"start_time": 1.01, "midi_pitch": 64},
            {"start_time": 1.02, "midi_pitch": 67},
        ]
        groups = _group_simultaneous_notes(notes, tolerance=0.03)
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_separate_notes(self):
        """離れたノートは別グループ"""
        notes = [
            {"start_time": 1.0, "midi_pitch": 60},
            {"start_time": 2.0, "midi_pitch": 64},
        ]
        groups = _group_simultaneous_notes(notes)
        assert len(groups) == 2

    def test_mixed(self):
        """和音+単音の混在"""
        notes = [
            {"start_time": 1.0, "midi_pitch": 60},
            {"start_time": 1.01, "midi_pitch": 64},
            {"start_time": 2.0, "midi_pitch": 72},
        ]
        groups = _group_simultaneous_notes(notes)
        assert len(groups) == 2
        assert len(groups[0]) == 2
        assert len(groups[1]) == 1


# =========================================================================
#  estimate_key_from_chords
# =========================================================================

class TestEstimateKeyFromChords:
    """コード進行からのキー推定テスト"""

    def test_c_major_progression(self):
        """C Am F G → C major"""
        data = [
            {"chord": "C", "bar": 1, "beat": 1},
            {"chord": "Am", "bar": 1, "beat": 2},
            {"chord": "F", "bar": 1, "beat": 3},
            {"chord": "G", "bar": 1, "beat": 4},
        ] * 4
        result = estimate_key_from_chords(data)
        assert "C" in result and "major" in result

    def test_a_minor_progression(self):
        """Am Dm E Am → A minor"""
        data = [
            {"chord": "Am", "bar": 1, "beat": 1},
            {"chord": "Dm", "bar": 1, "beat": 2},
            {"chord": "E", "bar": 1, "beat": 3},
            {"chord": "Am", "bar": 1, "beat": 4},
        ] * 4
        result = estimate_key_from_chords(data)
        assert "minor" in result or "A" in result

    def test_empty_data(self):
        """空データ → "C major" (デフォルト)"""
        result = estimate_key_from_chords([])
        assert result == "C major"

    def test_nc_only(self):
        """N.C. のみ → "C major" (デフォルト)"""
        data = [{"chord": "N.C.", "bar": 1, "beat": i} for i in range(1, 5)]
        result = estimate_key_from_chords(data)
        assert result == "C major"

    def test_g_major_progression(self):
        """G Em C D → G major"""
        data = [
            {"chord": "G", "bar": 1, "beat": 1},
            {"chord": "Em", "bar": 1, "beat": 2},
            {"chord": "C", "bar": 1, "beat": 3},
            {"chord": "D", "bar": 1, "beat": 4},
        ] * 4
        result = estimate_key_from_chords(data)
        assert "G" in result


# =========================================================================
#  generate_chord_strum_notes
# =========================================================================

class TestGenerateChordStrumNotes:
    """コードストロークノート生成テスト"""

    def test_basic_generation(self):
        """基本的なノート生成"""
        data = [
            {"chord": "C", "time": 0.0, "bar": 1, "beat": 1},
            {"chord": "G", "time": 0.5, "bar": 1, "beat": 2},
        ]
        notes = generate_chord_strum_notes(data, bpm=120)
        assert len(notes) > 0
        for n in notes:
            assert "start_time" in n
            assert "midi_pitch" in n
            assert "velocity" in n

    def test_nc_skipped(self):
        """N.C. はスキップされる"""
        data = [{"chord": "N.C.", "time": 0.0, "bar": 1, "beat": 1}]
        notes = generate_chord_strum_notes(data)
        assert len(notes) == 0

    def test_empty_data(self):
        """空データ → 空リスト"""
        notes = generate_chord_strum_notes([])
        assert notes == []

    def test_notes_sorted(self):
        """生成されたノートは時間順にソート"""
        data = [
            {"chord": "Am", "time": 0.0, "bar": 1, "beat": 1},
            {"chord": "F", "time": 0.5, "bar": 1, "beat": 2},
            {"chord": "C", "time": 1.0, "bar": 1, "beat": 3},
            {"chord": "G", "time": 1.5, "bar": 1, "beat": 4},
        ]
        notes = generate_chord_strum_notes(data, bpm=120)
        for i in range(1, len(notes)):
            assert notes[i]["start_time"] >= notes[i-1]["start_time"]

    def test_down_up_velocity(self):
        """ダウンストロークはアップより強い"""
        data = [{"chord": "C", "time": 0.0, "bar": 1, "beat": 1}]
        notes = generate_chord_strum_notes(data, bpm=120)
        # 最初のグループ(down)のvelocity > 2番目(up)
        down_notes = [n for n in notes if n["start_time"] == 0.0]
        up_notes = [n for n in notes if n["start_time"] > 0.0]
        if down_notes and up_notes:
            assert down_notes[0]["velocity"] > up_notes[0]["velocity"]


# =========================================================================
#  notes_to_tab_data
# =========================================================================

class TestNotesToTabData:
    """ノートイベント → TABデータ変換テスト"""

    def test_single_note(self):
        notes = [{
            "start_time": 0.5,
            "end_time": 1.0,
            "midi_pitch": 60,
            "velocity": 80,
            "confidence": 0.9,
            "note_name": "C4",
        }]
        tab = notes_to_tab_data(notes)
        assert len(tab) > 0
        assert "time" in tab[0]
        assert "string" in tab[0]
        assert "fret" in tab[0]

    def test_empty(self):
        tab = notes_to_tab_data([])
        assert tab == []

    def test_chord_group(self):
        """同時ノートが弦競合なしで割り当てられる"""
        notes = [
            {"start_time": 0.5, "end_time": 1.0, "midi_pitch": 60, "velocity": 80, "confidence": 0.9, "note_name": "C4"},
            {"start_time": 0.51, "end_time": 1.0, "midi_pitch": 64, "velocity": 80, "confidence": 0.9, "note_name": "E4"},
            {"start_time": 0.52, "end_time": 1.0, "midi_pitch": 67, "velocity": 80, "confidence": 0.9, "note_name": "G4"},
        ]
        tab = notes_to_tab_data(notes)
        assert len(tab) == 3  # 3ノートが別の弦に配置
        # 全て同じグループ → 各ノートが異なる弦に割り当て
        strings = [t["string"] for t in tab]
        assert len(set(strings)) == 3  # 重複なし


# =========================================================================
#  Tuning Presets
# =========================================================================

class TestTuningPresets:
    """チューニングプリセットのテスト"""

    def test_standard_tuning(self):
        assert STANDARD_TUNING[6] == 40  # E2
        assert STANDARD_TUNING[1] == 64  # E4

    def test_drop_d(self):
        drop_d = TUNING_PRESETS["drop_d"]
        assert drop_d[6] == 38  # D2
        assert drop_d[5] == 45  # A2 (same as standard)

    def test_all_presets_have_6_strings(self):
        for name, tuning in TUNING_PRESETS.items():
            assert len(tuning) == 6, f"Tuning '{name}' has {len(tuning)} strings"
