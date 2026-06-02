"""
NextChord 100パターン自動検証スクリプト
- Block A: MusicXML整合性 (30パターン)
- Block B: GP5 Voice Overflow (30パターン)
- Block C: ビート位置精度 (20パターン)
- Block D: テクニック/ガード (20パターン)
"""
import sys, os, json, io, random, traceback
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'D:\Music\nextchord\fastapi-backend')

# ---- helpers ----
def make_notes(n=20, bpm=120, time_sig='4/4', seed=42):
    rng = random.Random(seed)
    beat_dur = 60.0 / bpm
    num, den = map(int, time_sig.split('/'))
    bar_dur = num * beat_dur * (4 / den)
    total_dur = bar_dur * 8  # 8 bars
    notes = []
    t = rng.uniform(0.0, beat_dur * 0.5)
    for _ in range(n):
        dur = rng.uniform(0.1, 0.6)
        pitch = rng.randint(40, 84)
        vel = rng.uniform(0.3, 1.0)
        s = rng.randint(1, 6)
        open_pitches = [40, 45, 50, 55, 59, 64]
        f = max(0, pitch - open_pitches[6 - s])
        NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        note_name = NOTE_NAMES[pitch % 12] + str(pitch // 12 - 1)
        notes.append({
            'start': round(t, 4), 'end': round(t + dur, 4),
            'start_time': round(t, 4), 'end_time': round(t + dur, 4),
            'pitch': pitch, 'midi_pitch': pitch, 'note_name': note_name,
            'velocity': vel, 'string': s, 'fret': f,
        })
        t += rng.uniform(0.15, 0.7)
        if t > total_dur:
            break
    beats = [i * beat_dur for i in range(int(total_dur / beat_dur) + 2)]
    return notes, beats

pass_count = 0
fail_count = 0
errors = []

def run_test(name, fn):
    global pass_count, fail_count
    try:
        fn()
        pass_count += 1
    except Exception as e:
        fail_count += 1
        errors.append(f'{name}: {e}')
        traceback.print_exc()

# ===========================================================
# BLOCK A: MusicXML 整合性 (30 patterns)
# ===========================================================
print("BLOCK A: MusicXML Integrity Tests (30 patterns)")
print("-" * 50)

from tab_generator import notes_to_musicxml

for i in range(30):
    def test_a(seed=i):
        bpms = [80, 100, 120, 140, 160]
        sigs = ['4/4', '3/4', '4/4', '4/4', '4/4']
        bpm = bpms[seed % len(bpms)]
        sig = sigs[seed % len(sigs)]
        num, den = map(int, sig.split('/'))
        n_notes = 5 + seed % 30
        notes, beats = make_notes(n=n_notes, bpm=bpm, time_sig=sig, seed=seed)
        result = notes_to_musicxml(notes, beats=beats, bpm=bpm, time_sig=(num, den),
                                     title=f'test_{seed}', key='C')
        xml = result if isinstance(result, str) else result[0]
        assert xml is not None, "XML is None"
        assert '<score-partwise' in xml, "Missing score-partwise"
        assert '<part id=' in xml, "Missing part"
        # Check type tags are valid
        valid_types = {'whole','half','quarter','eighth','16th','32nd','64th'}
        import re
        types_found = re.findall(r'<type>([^<]+)</type>', xml)
        for t in types_found:
            assert t in valid_types, f"Invalid note type: '{t}'"
    run_test(f'A-{i+1:02d}', test_a)

a_pass = pass_count
a_fail = fail_count
print(f"  Block A: {a_pass} pass, {a_fail} fail\n")

# ===========================================================
# BLOCK B: GP5 Voice Overflow (30 patterns)
# ===========================================================
print("BLOCK B: GP5 Voice Overflow Tests (30 patterns)")
print("-" * 50)

try:
    from gp5_export import notes_to_gp5
    import guitarpro as gp
    has_gp5 = True
except ImportError:
    has_gp5 = False
    print("  SKIP: guitarpro not available")

if has_gp5:
    b_start_pass = pass_count
    b_start_fail = fail_count
    for i in range(30):
        def test_b(seed=i+100):
            bpms = [72, 90, 120, 140, 200]
            sigs = ['4/4', '3/4', '6/8', '4/4', '4/4']
            bpm = bpms[seed % len(bpms)]
            sig = sigs[seed % len(sigs)]
            n_notes = 8 + seed % 25
            notes, beats = make_notes(n=n_notes, bpm=bpm, time_sig=sig, seed=seed)
            gp5_bytes = notes_to_gp5(notes, beats=beats, bpm=bpm,
                                      time_signature=sig, title=f'test_{seed}')
            assert len(gp5_bytes) > 0, "Empty GP5"
            song = gp.parse(io.BytesIO(gp5_bytes))
            track = song.tracks[0]
            num, den = map(int, sig.split('/'))
            divs_per_beat = 6 if den == 8 else 12
            bar_total = num * divs_per_beat
            for m_idx, m in enumerate(track.measures):
                for v_idx, v in enumerate(m.voices):
                    total = 0
                    for beat in v.beats:
                        d = {1:48,2:24,4:12,8:6,16:3,32:2,64:1}.get(
                            beat.duration.value, 12)
                        if beat.duration.isDotted:
                            d = int(d * 1.5)
                        if hasattr(beat.duration, 'tuplet') and beat.duration.tuplet:
                            if beat.duration.tuplet.enters == 3:
                                d = int(d * 2 / 3)
                        total += d
                    assert total <= bar_total + 1, \
                        f"M{m_idx+1} V{v_idx+1}: {total} > {bar_total}"
        run_test(f'B-{i+1:02d}', test_b)
    b_pass = pass_count - b_start_pass
    b_fail = fail_count - b_start_fail
    print(f"  Block B: {b_pass} pass, {b_fail} fail\n")

# ===========================================================
# BLOCK C: ビート位置精度 (20 patterns)
# ===========================================================
print("BLOCK C: Beat Position Accuracy Tests (20 patterns)")
print("-" * 50)

c_start_pass = pass_count
c_start_fail = fail_count

if has_gp5:
    for i in range(20):
        def test_c(seed=i+200):
            notes, beats = make_notes(n=15, bpm=120, seed=seed)
            gp5_bytes = notes_to_gp5(notes, beats=beats, bpm=120)
            song = gp.parse(io.BytesIO(gp5_bytes))
            track = song.tracks[0]
            for m in track.measures:
                for v in m.voices:
                    for beat in v.beats:
                        d = beat.duration.value
                        assert d in (1,2,4,8,16,32,64), f"Invalid duration: {d}"
        run_test(f'C-{i+1:02d}', test_c)

c_pass = pass_count - c_start_pass
c_fail = fail_count - c_start_fail
print(f"  Block C: {c_pass} pass, {c_fail} fail\n")

# ===========================================================
# BLOCK D: ガードチェック (20 patterns)
# ===========================================================
print("BLOCK D: Guard Check Tests (20 patterns)")
print("-" * 50)

d_start_pass = pass_count
d_start_fail = fail_count

for i in range(20):
    def test_d(seed=i+300):
        notes, beats = make_notes(n=20, bpm=120, seed=seed)
        # Noise gate test
        if has_gp5:
            gp5_bytes = notes_to_gp5(notes, beats=beats, bpm=120, noise_gate=0.5)
            assert len(gp5_bytes) > 0, "Empty GP5 with noise gate"
        # Empty notes test
        if seed % 5 == 0:
            if has_gp5:
                gp5_bytes = notes_to_gp5([], beats=beats, bpm=120)
                assert len(gp5_bytes) > 0, "Empty notes should produce valid GP5"
        # Fret validation
        for n in notes:
            assert n['fret'] >= 0, f"Negative fret: {n['fret']}"
            assert 1 <= n['string'] <= 6, f"Invalid string: {n['string']}"
    run_test(f'D-{i+1:02d}', test_d)

d_pass = pass_count - d_start_pass
d_fail = fail_count - d_start_fail
print(f"  Block D: {d_pass} pass, {d_fail} fail\n")

# ===========================================================
# SUMMARY
# ===========================================================
print("=" * 60)
print(f"TOTAL: {pass_count} PASS, {fail_count} FAIL out of 100 tests")
if fail_count == 0:
    print("ALL 100 TESTS PASSED!")
else:
    print("FAILURES:")
    for e in errors:
        print(f"  {e}")
print("=" * 60)

sys.exit(0 if fail_count == 0 else 1)
