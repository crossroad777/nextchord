"""
Madmom Chord Recognition Engine
Uses CNN feature extraction + CRF decoding for chord recognition.
Interface: detect_chords(wav_path) -> (seg_starts, seg_labels)
"""
import numpy as np
from pathlib import Path


class MadmomChordEngine:
    """Madmom-based chord detection engine."""

    def __init__(self):
        self._feat_proc = None
        self._chord_proc = None
        self._loaded = False

    def load(self):
        """Load madmom chord processors (lazy)."""
        if self._loaded:
            return
        from madmom.features.chords import (
            CNNChordFeatureProcessor,
            CRFChordRecognitionProcessor,
        )
        self._feat_proc = CNNChordFeatureProcessor()
        self._chord_proc = CRFChordRecognitionProcessor()
        self._loaded = True
        print("[MadmomChord] Processors loaded")

    def detect_chords(self, wav_path) -> tuple:
        """
        Detect chords from audio file.
        Limits processing to first 120 seconds for speed.
        """
        import time
        self.load()
        wav_path = str(wav_path)
        t0 = time.time()

        # Truncate audio to 120s for speed (75s -> ~35s processing)
        # Most songs repeat chord patterns, so 120s captures full structure
        MAX_DURATION = 120  # seconds
        truncated_path = None
        try:
            import librosa
            import soundfile as sf
            import tempfile
            import os
            y, sr = librosa.load(wav_path, sr=44100, mono=True,
                                 duration=MAX_DURATION)
            truncated_path = os.path.join(
                tempfile.gettempdir(), '_madmom_truncated.wav')
            sf.write(truncated_path, y, sr)
            process_path = truncated_path
            print(f"[MadmomChord] Truncated to {MAX_DURATION}s "
                  f"({len(y)/sr:.1f}s actual)")
        except Exception as e:
            print(f"[MadmomChord] Truncation failed, using full: {e}")
            process_path = wav_path

        # Extract features and decode
        features = self._feat_proc(process_path)
        chords = self._chord_proc(features)

        # Cleanup temp file
        if truncated_path:
            try:
                os.remove(truncated_path)
            except:
                pass

        # Convert (start, end, label) tuples to (seg_starts, seg_labels)
        if len(chords) == 0:
            return np.array([]), np.array([])

        seg_starts = np.array([c[0] for c in chords], dtype=np.float64)
        seg_labels = np.array([c[2] for c in chords], dtype=object)

        elapsed = time.time() - t0
        print(f"[MadmomChord] Detected {len(seg_starts)} segments, "
              f"unique: {len(set(seg_labels))}, {elapsed:.1f}s")

        return seg_starts, seg_labels


_engine = None


def get_madmom_chord_engine():
    """Get singleton madmom chord engine instance."""
    global _engine
    if _engine is None:
        _engine = MadmomChordEngine()
    return _engine
