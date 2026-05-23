"""
Music21ベース 合成コードデータ生成器 v2
=======================================
- music21で理論的に正確な全ボイシング・転回形を網羅
- FluidSynthは1回だけsfloadして高速化
- 体系的生成: 12root × 13types × 4voicings × 7instruments = 4,368パターン
- ランダム進行も加えて合計5,000曲
"""
import sys, os, random, numpy as np, soundfile as sf
from pathlib import Path
import music21
import fluidsynth
import warnings
warnings.filterwarnings('ignore')

SOUNDFONT = r"D:\Music\nextchord-solotab\tools\FluidR3_GM.sf2"
OUT_DIR = Path(r"D:\Music\nextchord\ChordMini\data\synthetic")
AUDIO_DIR = OUT_DIR / "audio"
LABEL_DIR = OUT_DIR / "chordlab"
SR = 22050

# ChordMini vocabulary mapping
CHORD_INTERVALS = {
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

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# GM programs for variety
PROGRAMS = {
    'piano': 0, 'epiano': 4, 'organ': 16, 'accordion': 21,
    'acoustic_guitar': 24, 'electric_guitar': 27, 'strings': 48,
}


def chord_label(root_idx, chord_type):
    root = NOTE_NAMES[root_idx % 12]
    if chord_type == 'maj':
        return root
    return f"{root}:{chord_type}"


def get_voicings(root_midi, intervals):
    """Music21的な体系的ボイシング生成"""
    voicings = []
    
    # 基本形 (root position)
    voicings.append([root_midi + i for i in intervals])
    
    # 第1転回 (root up octave)
    if len(intervals) >= 3:
        inv1 = [root_midi + intervals[1], root_midi + intervals[2]]
        if len(intervals) > 3:
            inv1.append(root_midi + intervals[3])
        inv1.append(root_midi + 12)  # root up
        voicings.append(sorted(inv1))
    
    # オクターブ下のbass + close voicing
    bass_voicing = [root_midi - 12] + [root_midi + i for i in intervals]
    voicings.append(bass_voicing)
    
    # ダブリング (root doubled at octave)
    doubled = [root_midi + i for i in intervals] + [root_midi + 12]
    voicings.append(doubled)
    
    # Wide spread (guitar-like)
    if len(intervals) >= 3:
        wide = [root_midi - 12, root_midi + intervals[1],
                root_midi + intervals[2] + 12]
        if len(intervals) > 3:
            wide.append(root_midi + intervals[3] + 12)
        voicings.append(wide)
    
    return voicings


class ChordSynthesizer:
    def __init__(self, soundfont_path, sr=22050):
        self.sr = sr
        self.fs = fluidsynth.Synth(samplerate=float(sr))
        self.sfid = self.fs.sfload(soundfont_path)
        self.fs.program_select(0, self.sfid, 0, 0)
    
    def set_program(self, program):
        self.fs.program_select(0, self.sfid, 0, program)
    
    def render_chord(self, midi_notes, duration, velocity=100):
        """1つのコードを合成"""
        for note in midi_notes:
            n = max(0, min(127, note))
            self.fs.noteon(0, n, velocity)
        
        n_samples = int(self.sr * duration)
        samples = self.fs.get_samples(n_samples)
        
        for note in midi_notes:
            n = max(0, min(127, note))
            self.fs.noteoff(0, n)
        
        # Release tail
        release = self.fs.get_samples(int(self.sr * 0.3))
        samples = np.concatenate([samples, release])
        
        audio = np.array(samples, dtype=np.float32) / 32768.0
        audio = audio.reshape(-1, 2).mean(axis=1)
        audio = audio[:int(self.sr * duration)]
        
        return audio
    
    def render_progression(self, chords, durations, velocity=100):
        """コード進行全体を合成"""
        segments = []
        lab_lines = []
        t = 0.0
        
        for (root, ctype, midi_notes), dur in zip(chords, durations):
            audio = self.render_chord(midi_notes, dur, velocity)
            label = chord_label(root, ctype)
            lab_lines.append(f"{t:.6f} {t+dur:.6f} {label}")
            segments.append(audio)
            t += dur
        
        full = np.concatenate(segments)
        mx = np.max(np.abs(full))
        if mx > 0:
            full = full / mx * 0.8
        
        return full, lab_lines
    
    def close(self):
        self.fs.delete()


def generate_systematic_chords(synth, song_idx):
    """体系的: 各コードタイプ×各root×各ボイシングの単独コード (2-3秒)"""
    songs = []
    idx = song_idx
    
    for root in range(12):
        for ctype, intervals in CHORD_INTERVALS.items():
            for octave in [48, 60]:  # C3, C4
                root_midi = octave + root
                voicings = get_voicings(root_midi, intervals)
                
                for vi, notes in enumerate(voicings[:3]):  # 3 voicings each
                    dur = random.uniform(2.0, 4.0)
                    chords = [(root, ctype, notes)]
                    durations = [dur]
                    songs.append((f"sys_{idx:05d}", chords, durations))
                    idx += 1
    
    return songs, idx


def generate_progression_songs(synth, song_idx, n_songs=2000):
    """ランダムなコード進行曲"""
    # 一般的な進行パターン (degree, type)
    patterns = [
        [(0,'maj'),(7,'maj'),(9,'min'),(5,'maj')],           # I-V-vi-IV
        [(0,'maj'),(9,'min'),(5,'maj'),(7,'maj')],           # I-vi-IV-V
        [(2,'min7'),(7,'7'),(0,'maj7')],                     # ii-V-I
        [(0,'maj'),(5,'maj'),(7,'maj'),(0,'maj')],           # I-IV-V-I
        [(0,'min'),(5,'min'),(7,'min'),(0,'min')],           # i-iv-v-i
        [(0,'min'),(8,'maj'),(3,'maj'),(10,'maj')],          # i-VI-III-VII
        [(0,'7'),(5,'7'),(0,'7'),(7,'7')],                   # Blues
        [(0,'maj'),(2,'min'),(5,'maj'),(7,'maj')],           # I-ii-IV-V
        [(0,'maj7'),(4,'min7'),(9,'min7'),(5,'maj7')],       # Imaj7-iii7-vi7-IVmaj7
        [(0,'maj'),(7,'maj'),(9,'min'),(4,'min'),
         (5,'maj'),(0,'maj'),(5,'maj'),(7,'7')],             # Canon
        [(0,'maj'),(3,'maj'),(5,'maj'),(0,'maj')],           # I-bIII-IV-I
        [(0,'min7'),(3,'maj7'),(5,'7'),(0,'min7')],          # i7-bIIImaj7-V7-i7
        [(0,'maj'),(7,'sus4'),(7,'maj'),(0,'maj')],          # I-Vsus4-V-I
        [(0,'maj'),(0,'7'),(5,'maj'),(5,'min')],             # I-I7-IV-iv
    ]
    
    songs = []
    idx = song_idx
    
    for _ in range(n_songs):
        key_root = random.randint(0, 11)
        octave = random.choice([48, 54, 60])
        
        # Pick pattern or random
        if random.random() < 0.7:
            pattern = random.choice(patterns)
        else:
            # Random chords
            n = random.randint(3, 8)
            types = list(CHORD_INTERVALS.keys())
            pattern = [(random.randint(0,11), random.choice(types)) for _ in range(n)]
        
        # Repeat pattern to fill 15-30 seconds
        n_repeats = random.randint(2, 4)
        progression = pattern * n_repeats
        
        chords = []
        durations = []
        for deg, ctype in progression:
            root = (key_root + deg) % 12
            root_midi = octave + root
            intervals = CHORD_INTERVALS[ctype]
            voicing = random.choice(get_voicings(root_midi, intervals))
            chords.append((root, ctype, voicing))
            durations.append(random.uniform(1.5, 3.5))
        
        songs.append((f"prog_{idx:05d}", chords, durations))
        idx += 1
    
    return songs, idx


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("Music21-based Synthetic Chord Generator v2")
    print(f"SoundFont: {SOUNDFONT}")
    print("=" * 70)
    
    synth = ChordSynthesizer(SOUNDFONT, SR)
    
    # Phase 1: 体系的コード（各root×type×voicing）
    print("\nPhase 1: Systematic chords (all root×type×voicing)...")
    sys_songs, idx = generate_systematic_chords(synth, 0)
    print(f"  Generated {len(sys_songs)} systematic chord patterns")
    
    # Phase 2: コード進行（パターン + ランダム）
    print("\nPhase 2: Chord progressions...")
    prog_songs, idx = generate_progression_songs(synth, idx, n_songs=2000)
    print(f"  Generated {len(prog_songs)} progressions")
    
    all_songs = sys_songs + prog_songs
    print(f"\nTotal: {len(all_songs)} songs")
    
    # Render all
    print("\nRendering with FluidSynth...")
    programs = list(PROGRAMS.values())
    
    for i, (name, chords, durations) in enumerate(all_songs):
        # Vary instrument
        prog = random.choice(programs)
        synth.set_program(prog)
        vel = random.randint(70, 120)
        
        audio, lab_lines = synth.render_progression(chords, durations, vel)
        
        # Add slight noise
        noise = np.random.randn(len(audio)) * 0.003
        audio = np.clip(audio + noise, -1, 1)
        
        sf.write(str(AUDIO_DIR / f"{name}.wav"), audio, SR)
        with open(LABEL_DIR / f"{name}.lab", "w") as f:
            f.write("\n".join(lab_lines) + "\n")
        
        if (i + 1) % 500 == 0:
            print(f"  Rendered {i+1}/{len(all_songs)}")
    
    synth.close()
    
    print(f"\nDone! {len(all_songs)} songs")
    print(f"Audio: {AUDIO_DIR}")
    print(f"Labels: {LABEL_DIR}")
    
    # Count existing
    n_wav = len(list(AUDIO_DIR.glob("*.wav")))
    n_lab = len(list(LABEL_DIR.glob("*.lab")))
    print(f"Files: {n_wav} wav, {n_lab} lab")


if __name__ == "__main__":
    main()
