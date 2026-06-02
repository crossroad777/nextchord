"""
NextChord Unit Tests -- note_transcription.py
=============================================
ノート検出・フィルタリングのユニットテスト。

Usage:
    python -m pytest test_note_transcription.py -v
"""

import pytest
import numpy as np
from note_transcription import (
    midi_to_note_name,
    midi_to_frequency,
    _remove_overlapping_notes,
    _apply_velocity_dynamics,
    notes_to_summary,
)


# =========================================================================
# midi_to_note_name
# =========================================================================

class TestMidiToNoteName:
    def test_middle_c(self):
        assert midi_to_note_name(60) == "C4"
    
    def test_a4(self):
        assert midi_to_note_name(69) == "A4"
    
    def test_low_e(self):
        """ギターの最低音 E2（MIDI 40）"""
        assert midi_to_note_name(40) == "E2"
    
    def test_high_e(self):
        """ギターの最高開放弦 E4（MIDI 64）"""
        assert midi_to_note_name(64) == "E4"
    
    def test_sharps(self):
        assert midi_to_note_name(61) == "C#4"
        assert midi_to_note_name(66) == "F#4"


# =========================================================================
# midi_to_frequency
# =========================================================================

class TestMidiToFrequency:
    def test_a4(self):
        assert midi_to_frequency(69) == pytest.approx(440.0)
    
    def test_a3(self):
        assert midi_to_frequency(57) == pytest.approx(220.0)
    
    def test_middle_c(self):
        assert midi_to_frequency(60) == pytest.approx(261.63, rel=0.01)
    
    def test_octave_relationship(self):
        """1オクターブ上は周波数が2倍"""
        f1 = midi_to_frequency(60)
        f2 = midi_to_frequency(72)
        assert f2 == pytest.approx(f1 * 2.0)


# =========================================================================
# _remove_overlapping_notes
# =========================================================================

def _make_note(start, end, pitch=60, velocity=80, confidence=0.8):
    """テスト用ノート生成ヘルパー"""
    return {
        "start_time": start,
        "end_time": end,
        "midi_pitch": pitch,
        "velocity": velocity,
        "confidence": confidence,
        "note_name": midi_to_note_name(pitch),
    }


class TestRemoveOverlappingNotes:
    def test_empty(self):
        assert _remove_overlapping_notes([]) == []
    
    def test_no_overlap(self):
        """重複なしの場合、そのまま返す"""
        notes = [
            _make_note(0.0, 0.5, pitch=60),
            _make_note(1.0, 1.5, pitch=62),
        ]
        result = _remove_overlapping_notes(notes)
        assert len(result) == 2
    
    def test_same_pitch_merge(self):
        """同一ピッチの連続ノートをマージ"""
        notes = [
            _make_note(0.0, 0.5, pitch=60),
            _make_note(0.52, 1.0, pitch=60),  # 30ms以内 -> マージ
        ]
        result = _remove_overlapping_notes(notes)
        assert len(result) == 1
        assert result[0]["end_time"] == 1.0
    
    def test_polyphony_limit(self):
        """6弦以上の同時発音を制限"""
        notes = [
            _make_note(0.0, 1.0, pitch=40 + i, confidence=0.5 + i * 0.05)
            for i in range(8)  # 8ノート同時
        ]
        result = _remove_overlapping_notes(notes, max_polyphony=6)
        # 同時発音が6以下
        concurrent = [
            n for n in result
            if n["start_time"] < 0.5 and n["end_time"] > 0.5
        ]
        assert len(concurrent) <= 6
    
    def test_higher_confidence_replaces(self):
        """高信頼度のノートが低信頼度のノートを置き換える"""
        # 6ノートでいっぱい -> 7番目は高信頼度
        notes = [
            _make_note(0.0, 1.0, pitch=40 + i, confidence=0.3)
            for i in range(6)
        ]
        notes.append(_make_note(0.0, 1.0, pitch=50, confidence=0.9))
        result = _remove_overlapping_notes(notes, max_polyphony=6)
        # 高信頼度のノートが含まれている
        pitches = [n["midi_pitch"] for n in result]
        assert 50 in pitches


# =========================================================================
# _apply_velocity_dynamics
# =========================================================================

class TestApplyVelocityDynamics:
    def test_empty(self):
        assert _apply_velocity_dynamics([]) == []
    
    def test_normalization_range(self):
        """正規化後のベロシティが40-120の範囲に収まる"""
        notes = [
            _make_note(0.0, 0.5, velocity=10),
            _make_note(1.0, 1.5, velocity=127),
            _make_note(2.0, 2.5, velocity=64),
        ]
        result = _apply_velocity_dynamics(notes)
        for n in result:
            assert 40 <= n["velocity"] <= 127
    
    def test_preserves_order(self):
        """ベロシティの大小関係を保持"""
        notes = [
            _make_note(0.0, 0.5, velocity=30),
            _make_note(1.0, 1.5, velocity=100),
        ]
        result = _apply_velocity_dynamics(notes)
        assert result[0]["velocity"] < result[1]["velocity"]
    
    def test_uniform_velocity(self):
        """全ノートが同じベロシティの場合、デフォルト値になる"""
        notes = [
            _make_note(0.0, 0.5, velocity=64),
            _make_note(1.0, 1.5, velocity=64),
        ]
        result = _apply_velocity_dynamics(notes)
        assert result[0]["velocity"] == 80
        assert result[1]["velocity"] == 80


# =========================================================================
# notes_to_summary
# =========================================================================

class TestNotesToSummary:
    def test_empty(self):
        result = notes_to_summary([])
        assert result["total_notes"] == 0
    
    def test_single_note(self):
        notes = [_make_note(0.0, 1.0, pitch=60)]
        result = notes_to_summary(notes)
        assert result["total_notes"] == 1
        assert result["pitch_range"]["min"] == 60
        assert result["pitch_range"]["max"] == 60
        assert result["pitch_range"]["min_name"] == "C4"
    
    def test_multiple_notes(self):
        notes = [
            _make_note(0.0, 0.5, pitch=40),  # E2
            _make_note(1.0, 1.5, pitch=64),  # E4
            _make_note(2.0, 3.0, pitch=60),  # C4
        ]
        result = notes_to_summary(notes)
        assert result["total_notes"] == 3
        assert result["pitch_range"]["min"] == 40
        assert result["pitch_range"]["max"] == 64
        assert result["time_span"]["start"] == 0.0
        assert result["time_span"]["end"] == 3.0
    
    def test_duration_stats(self):
        notes = [
            _make_note(0.0, 0.5),   # 0.5秒
            _make_note(1.0, 2.0),   # 1.0秒
            _make_note(3.0, 3.2),   # 0.2秒
        ]
        result = notes_to_summary(notes)
        assert result["duration_stats"]["min"] == pytest.approx(0.2)
        assert result["duration_stats"]["max"] == pytest.approx(1.0)
        assert result["duration_stats"]["mean"] == pytest.approx(0.5667, rel=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
