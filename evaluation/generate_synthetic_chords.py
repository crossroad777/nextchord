"""
合成コードデータ生成器
======================
SoloTab戦略: 完璧なアノテーション付き合成データで事前学習

生成するもの:
- 各コードクラス × 複数ボイシング × 複数楽器 × 複数テンポ
- WAV音源 + 100%正確な.labファイル
- ChordMiniのdata/labeled/構造に準拠

コードクラス (ChordMini vocabulary = 170):
- 12 roots × (maj, min, dim, aug, maj7, min7, 7, dim7, hdim7, min6, maj6, sus2, sus4, N)
"""
import sys
import os
import random
import json
import numpy as np
import soundfile as sf
from pathlib import Path
from itertools import product as iter_product
import warnings
warnings.filterwarnings('ignore')

# MIDI note numbers
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
# Alternative names for flat notation
NOTE_NAMES_FLAT = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

# Chord intervals (semitones from root)
CHORD_TYPES = {
    'maj':   [0, 4, 7],
    'min':   [0, 3, 7],
    'dim':   [0, 3, 6],
    'aug':   [0, 4, 8],
    'maj7':  [0, 4, 7, 11],
    'min7':  [0, 3, 7, 10],
    '7':     [0, 4, 7, 10],
    'dim7':  [0, 3, 6, 9],
    'hdim7': [0, 3, 6, 10],
    'min6':  [0, 3, 7, 9],
    'maj6':  [0, 4, 7, 9],
    'sus2':  [0, 2, 7],
    'sus4':  [0, 5, 7],
}

# ChordMini label format
def chord_label(root_idx, chord_type):
    root = NOTE_NAMES[root_idx % 12]
    if chord_type == 'maj':
        return root
    elif chord_type == 'min':
        return f"{root}:min"
    elif chord_type == 'dim':
        return f"{root}:dim"
    elif chord_type == 'aug':
        return f"{root}:aug"
    elif chord_type == 'maj7':
        return f"{root}:maj7"
    elif chord_type == 'min7':
        return f"{root}:min7"
    elif chord_type == '7':
        return f"{root}:7"
    elif chord_type == 'dim7':
        return f"{root}:dim7"
    elif chord_type == 'hdim7':
        return f"{root}:hdim7"
    elif chord_type == 'min6':
        return f"{root}:min6"
    elif chord_type == 'maj6':
        return f"{root}:maj6"
    elif chord_type == 'sus2':
        return f"{root}:sus2"
    elif chord_type == 'sus4':
        return f"{root}:sus4"
    return 'N'


def generate_chord_midi_notes(root_midi, chord_type, voicing='close'):
    """コードのMIDIノート番号リストを生成"""
    intervals = CHORD_TYPES[chord_type]
    
    if voicing == 'close':
        # 密集形: root octave 3-4
        base = root_midi
        return [base + i for i in intervals]
    elif voicing == 'spread':
        # 開離形: bass + 上部構造
        notes = [root_midi - 12]  # bass note an octave lower
        for i in intervals[1:]:
            notes.append(root_midi + i)
        return notes
    elif voicing == 'doubled':
        # ダブリング: bass + close + octave
        notes = [root_midi - 12]
        for i in intervals:
            notes.append(root_midi + i)
        notes.append(root_midi + 12)  # root doubled up
        return notes
    elif voicing == 'guitar':
        # ギター風: 6弦に広がる
        notes = [root_midi - 12]  # bass
        for i in intervals:
            notes.append(root_midi + i)
            notes.append(root_midi + i + 12)  # octave up
        return notes[:6]  # max 6 strings


def synthesize_with_sine(midi_notes, duration, sr=22050, velocity=0.7):
    """正弦波ベースの簡易合成（FluidSynth失敗時のフォールバック）"""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    audio = np.zeros_like(t)
    
    for note in midi_notes:
        freq = 440.0 * (2.0 ** ((note - 69) / 12.0))
        # 基音 + 倍音
        audio += velocity * 0.5 * np.sin(2 * np.pi * freq * t)
        audio += velocity * 0.2 * np.sin(2 * np.pi * freq * 2 * t)  # 2nd harmonic
        audio += velocity * 0.1 * np.sin(2 * np.pi * freq * 3 * t)  # 3rd
    
    # ADSR envelope
    attack = int(0.02 * sr)
    decay = int(0.05 * sr)
    release = int(0.1 * sr)
    env = np.ones_like(audio)
    env[:attack] = np.linspace(0, 1, attack)
    env[attack:attack+decay] = np.linspace(1, 0.7, decay)
    if release < len(env):
        env[-release:] = np.linspace(0.7, 0, release)
    
    audio *= env
    # Normalize
    mx = np.max(np.abs(audio))
    if mx > 0:
        audio = audio / mx * 0.8
    
    return audio


def synthesize_with_fluidsynth(midi_notes, duration, sr=22050, 
                                soundfont=None, program=0, velocity=100):
    """FluidSynthでリアルな合成"""
    try:
        import fluidsynth
        
        fs = fluidsynth.Synth(samplerate=float(sr))
        if soundfont and os.path.exists(soundfont):
            sfid = fs.sfload(soundfont)
            fs.program_select(0, sfid, 0, program)
        else:
            return None
        
        # Note on
        for note in midi_notes:
            fs.noteon(0, note, velocity)
        
        # Render
        n_samples = int(sr * duration)
        samples = fs.get_samples(n_samples)
        
        # Note off
        for note in midi_notes:
            fs.noteoff(0, note)
        
        # Render release
        release_samples = fs.get_samples(int(sr * 0.5))
        samples = np.concatenate([samples, release_samples])
        
        fs.delete()
        
        # Convert to float, stereo -> mono
        audio = np.array(samples, dtype=np.float32) / 32768.0
        if len(audio.shape) == 1:
            # Interleaved stereo
            audio = audio.reshape(-1, 2).mean(axis=1)
        
        # Trim to duration
        audio = audio[:int(sr * duration)]
        
        # Normalize
        mx = np.max(np.abs(audio))
        if mx > 0:
            audio = audio / mx * 0.8
        
        return audio
    except Exception as e:
        return None


def generate_progression(n_chords=8, duration_per_chord=2.0, sr=22050, soundfont=None):
    """ランダムなコード進行を生成"""
    # ランダムなキーを選択
    key_root = random.randint(0, 11)
    
    # 一般的なコード進行パターン
    patterns = [
        # I-V-vi-IV (pop)
        [(0, 'maj'), (7, 'maj'), (9, 'min'), (5, 'maj')],
        # I-vi-IV-V
        [(0, 'maj'), (9, 'min'), (5, 'maj'), (7, 'maj')],
        # ii-V-I
        [(2, 'min7'), (7, '7'), (0, 'maj7')],
        # I-IV-V
        [(0, 'maj'), (5, 'maj'), (7, 'maj')],
        # i-iv-v (minor)
        [(0, 'min'), (5, 'min'), (7, 'min')],
        # i-VI-III-VII
        [(0, 'min'), (8, 'maj'), (3, 'maj'), (10, 'maj')],
        # I-V-vi-iii-IV-I-IV-V
        [(0, 'maj'), (7, 'maj'), (9, 'min'), (4, 'min'),
         (5, 'maj'), (0, 'maj'), (5, 'maj'), (7, 'maj')],
        # Blues: I7-IV7-I7-V7
        [(0, '7'), (5, '7'), (0, '7'), (7, '7')],
        # Jazz: ii7-V7-Imaj7
        [(2, 'min7'), (7, '7'), (0, 'maj7')],
        # Random chords
        None,
    ]
    
    pattern = random.choice(patterns)
    
    chords = []
    if pattern:
        while len(chords) < n_chords:
            for interval, ctype in pattern:
                if len(chords) >= n_chords:
                    break
                root = (key_root + interval) % 12
                chords.append((root, ctype))
    else:
        # Fully random
        types = list(CHORD_TYPES.keys())
        for _ in range(n_chords):
            root = random.randint(0, 11)
            ctype = random.choice(types)
            chords.append((root, ctype))
    
    # Generate audio + labels
    voicing = random.choice(['close', 'spread', 'doubled', 'guitar'])
    octave = random.choice([48, 60, 54])  # C3, C4, or F#3
    
    # GM programs: 0=Piano, 24=Guitar, 16=Organ, 4=EPiano, 48=Strings
    programs = [0, 4, 16, 24, 25, 26, 48]
    program = random.choice(programs)
    
    velocity = random.randint(70, 120)
    
    audio_segments = []
    lab_lines = []
    t = 0.0
    
    for root, ctype in chords:
        midi_root = octave + root
        midi_notes = generate_chord_midi_notes(midi_root, ctype, voicing)
        
        # Duration with slight variation
        dur = duration_per_chord * random.uniform(0.8, 1.2)
        
        # Try FluidSynth first
        audio = None
        if soundfont:
            audio = synthesize_with_fluidsynth(
                midi_notes, dur, sr=sr, soundfont=soundfont,
                program=program, velocity=velocity)
        
        if audio is None:
            audio = synthesize_with_sine(midi_notes, dur, sr=sr,
                                          velocity=velocity/127.0)
        
        label = chord_label(root, ctype)
        lab_lines.append(f"{t:.6f} {t+dur:.6f} {label}")
        
        audio_segments.append(audio)
        t += dur
    
    full_audio = np.concatenate(audio_segments)
    
    # Add slight noise for realism
    noise = np.random.randn(len(full_audio)) * 0.005
    full_audio = full_audio + noise
    full_audio = np.clip(full_audio, -1, 1)
    
    return full_audio, lab_lines, sr


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    
    OUT_DIR = Path(r"D:\Music\nextchord\ChordMini\data\synthetic")
    AUDIO_DIR = OUT_DIR / "audio"
    LABEL_DIR = OUT_DIR / "chordlab"
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    
    soundfont = r"D:\Music\nextchord-solotab\tools\FluidR3_GM.sf2"
    if os.path.exists(soundfont):
        print(f"SoundFont: {soundfont}")
    else:
        soundfont = None
        print("No SoundFont found, using sine wave synthesis")
    
    N_SONGS = 2000  # 2000曲生成
    N_CHORDS = random.choice([4, 6, 8, 12, 16])
    
    print(f"Generating {N_SONGS} synthetic chord progressions...")
    
    for i in range(N_SONGS):
        n_chords = random.choice([4, 6, 8, 12, 16])
        dur = random.choice([1.5, 2.0, 2.5, 3.0])
        
        audio, lab_lines, sr = generate_progression(
            n_chords=n_chords, duration_per_chord=dur,
            soundfont=soundfont)
        
        name = f"synth_{i:05d}"
        sf.write(str(AUDIO_DIR / f"{name}.wav"), audio, sr)
        
        with open(LABEL_DIR / f"{name}.lab", "w") as f:
            f.write("\n".join(lab_lines) + "\n")
        
        if (i + 1) % 200 == 0:
            print(f"  Generated {i+1}/{N_SONGS}")
    
    print(f"\nDone! {N_SONGS} songs in {OUT_DIR}")
    print(f"Audio: {AUDIO_DIR}")
    print(f"Labels: {LABEL_DIR}")


if __name__ == "__main__":
    main()
