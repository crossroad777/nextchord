"""
CQT Template Matching Chord Engine
Signal-processing approach using chroma features + chord templates.
Provides diversity for ensemble (non-neural method).
Interface: detect_chords(wav_path) -> (seg_starts, seg_labels)
"""
import numpy as np
from pathlib import Path
import time


# 12 pitch classes
PITCH_CLASSES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']

# Chord templates: each is a 12-element binary vector (chroma profile)
# Major triad: root + major 3rd + perfect 5th (0, 4, 7)
# Minor triad: root + minor 3rd + perfect 5th (0, 3, 7)
def _build_templates():
    """Build chord templates for all 24 major/minor chords."""
    templates = {}
    for i, root in enumerate(PITCH_CLASSES):
        # Major
        t_maj = np.zeros(12)
        t_maj[i] = 1.0
        t_maj[(i + 4) % 12] = 1.0  # major 3rd
        t_maj[(i + 7) % 12] = 1.0  # perfect 5th
        templates[f'{root}:maj'] = t_maj / np.linalg.norm(t_maj)

        # Minor
        t_min = np.zeros(12)
        t_min[i] = 1.0
        t_min[(i + 3) % 12] = 1.0  # minor 3rd
        t_min[(i + 7) % 12] = 1.0  # perfect 5th
        templates[f'{root}:min'] = t_min / np.linalg.norm(t_min)

    return templates


def _smooth_segments(frame_chords, hop_time, min_duration=0.3):
    """Merge consecutive identical chords and short segments."""
    if len(frame_chords) == 0:
        return np.array([0.0]), np.array(['N'])

    segments = []
    current_chord = frame_chords[0]
    current_start = 0.0

    for i in range(1, len(frame_chords)):
        if frame_chords[i] != current_chord:
            segments.append((current_start, i * hop_time, current_chord))
            current_chord = frame_chords[i]
            current_start = i * hop_time

    segments.append((current_start, len(frame_chords) * hop_time, current_chord))

    # Merge short segments into neighbors
    merged = []
    for start, end, chord in segments:
        duration = end - start
        if duration < min_duration and merged:
            # Absorb into previous segment
            prev_start, prev_end, prev_chord = merged[-1]
            merged[-1] = (prev_start, end, prev_chord)
        else:
            merged.append((start, end, chord))

    # Merge consecutive identical after absorption
    final = [merged[0]]
    for i in range(1, len(merged)):
        if merged[i][2] == final[-1][2]:
            final[-1] = (final[-1][0], merged[i][1], final[-1][2])
        else:
            final.append(merged[i])

    seg_starts = np.array([s[0] for s in final])
    seg_labels = np.array([s[2] for s in final])

    return seg_starts, seg_labels


class ChromaChordEngine:
    """CQT chroma-based chord detection using template matching."""

    def __init__(self):
        self._templates = None
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        self._templates = _build_templates()
        self._loaded = True
        print(f"[ChromaChord] {len(self._templates)} chord templates built")

    def detect_chords(self, wav_path) -> tuple:
        """
        Detect chords using CQT chroma template matching.

        Args:
            wav_path: Path to audio file

        Returns:
            (seg_starts, seg_labels) in BTC format
        """
        import librosa

        self.load()
        wav_path = str(wav_path)
        t0 = time.time()

        # Load audio
        y, sr = librosa.load(wav_path, sr=22050, mono=True)

        # Extract harmonic component for cleaner chroma
        y_harmonic = librosa.effects.harmonic(y, margin=3.0)

        # Compute CQT chroma with tuning correction
        tuning = librosa.estimate_tuning(y=y_harmonic, sr=sr)
        hop_length = 2048  # ~93ms per frame at 22050Hz
        chroma = librosa.feature.chroma_cqt(
            y=y_harmonic, sr=sr,
            hop_length=hop_length,
            tuning=tuning,
            n_chroma=12,
            norm=2,
        )
        # chroma shape: (12, n_frames)
        n_frames = chroma.shape[1]
        hop_time = hop_length / sr

        # Template matching per frame
        template_names = list(self._templates.keys())
        template_matrix = np.array([self._templates[name] for name in template_names])
        # template_matrix shape: (n_templates, 12)

        # Compute correlation: (n_templates, 12) @ (12, n_frames) = (n_templates, n_frames)
        correlations = template_matrix @ chroma

        # Best chord per frame
        best_indices = np.argmax(correlations, axis=0)
        best_scores = np.max(correlations, axis=0)

        # Assign chord labels (use N.C. for low-energy frames)
        energy_threshold = 0.05
        frame_energy = np.sum(chroma, axis=0)

        frame_chords = []
        for i in range(n_frames):
            if frame_energy[i] < energy_threshold:
                frame_chords.append('N')
            else:
                frame_chords.append(template_names[best_indices[i]])

        # Smooth into segments
        seg_starts, seg_labels = _smooth_segments(frame_chords, hop_time, min_duration=0.4)

        elapsed = time.time() - t0
        n_unique = len(set(seg_labels) - {'N'})
        print(f"[ChromaChord] {len(seg_starts)} segments, {n_unique} unique chords, "
              f"{elapsed:.1f}s")

        return seg_starts, seg_labels


_engine = None


def get_chroma_chord_engine():
    """Get singleton chroma chord engine."""
    global _engine
    if _engine is None:
        _engine = ChromaChordEngine()
    return _engine
