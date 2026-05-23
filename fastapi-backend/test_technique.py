"""Quick test for technique.py"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from technique import detect_techniques

# Test 1: empty / single note
print('=== Test 1: Empty & single note ===')
assert detect_techniques([]) == []
single = [{'start_time': 0.0, 'end_time': 0.5, 'midi_pitch': 60, 'string': 1, 'fret': 5, 'velocity': 80}]
result = detect_techniques(single)
assert len(result) == 1
print('PASS: safe with 0-1 notes')

# Test 2: hammer-on (different frets, pitch up)
print('=== Test 2: Hammer-on ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 60, 'string': 3, 'fret': 5, 'velocity': 80},
    {'start_time': 0.1, 'end_time': 0.4, 'midi_pitch': 62, 'string': 3, 'fret': 7, 'velocity': 70},
]
result = detect_techniques(notes, bpm=120)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
assert tech == 'h', f'Expected h, got {tech}'
print('PASS')

# Test 3: pull-off (different frets, pitch down)
print('=== Test 3: Pull-off ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 64, 'string': 2, 'fret': 8, 'velocity': 80},
    {'start_time': 0.1, 'end_time': 0.4, 'midi_pitch': 62, 'string': 2, 'fret': 6, 'velocity': 70},
]
result = detect_techniques(notes)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
assert tech == 'p', f'Expected p, got {tech}'
print('PASS')

# Test 4: slide up (abs_pitch > 6 bypasses H/P, fret_diff in [2,5] triggers slide)
print('=== Test 4: Slide up ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 48, 'string': 4, 'fret': 3, 'velocity': 80},
    {'start_time': 0.2, 'end_time': 0.5, 'midi_pitch': 55, 'string': 4, 'fret': 8, 'velocity': 70},
]
# pitch_diff=7 > 6 -> H/P won't fire. fret_diff=5, 2<=5<=5 -> slide '/'
result = detect_techniques(notes)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
assert tech == '/', f'Expected /, got {tech}'
print('PASS')

# Test 5: bend guard (fret=0 should NOT be bend)
print('=== Test 5: Bend guard fret=0 ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 64, 'string': 1, 'fret': 0, 'velocity': 80},
    {'start_time': 0.1, 'end_time': 0.4, 'midi_pitch': 65, 'string': 1, 'fret': 0, 'velocity': 70},
]
result = detect_techniques(notes)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
# fret=0, fret_diff=0 -> bend blocked (fret<3), H/P blocked (fret_diff==0) -> None
assert tech is None, f'Expected None on fret=0/same-fret, got {tech}'
print('PASS: fret=0 not detected as bend')

# Test 6: bend guard (fret<3 should NOT be bend)
print('=== Test 6: Bend guard fret<3 ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 64, 'string': 2, 'fret': 2, 'velocity': 80},
    {'start_time': 0.1, 'end_time': 0.4, 'midi_pitch': 65, 'string': 2, 'fret': 2, 'velocity': 70},
]
result = detect_techniques(notes)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
# fret=2, fret_diff=0 -> bend blocked (fret<3), H/P blocked (fret_diff==0) -> None
assert tech is None, f'Expected None on fret<3/same-fret, got {tech}'
print('PASS: fret<3 not detected as bend')

# Test 7: bend (fret>=3, same fret, pitch+1 -> b_half)
print('=== Test 7: Bend (fret>=3) ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 64, 'string': 2, 'fret': 5, 'velocity': 80},
    {'start_time': 0.1, 'end_time': 0.4, 'midi_pitch': 65, 'string': 2, 'fret': 5, 'velocity': 70},
]
result = detect_techniques(notes)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
assert tech == 'b_half', f'Expected b_half, got {tech}'
print('PASS')

# Test 7b: bend full tone (fret>=3, same fret, pitch+2 -> b)
print('=== Test 7b: Bend full (fret>=3) ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 64, 'string': 2, 'fret': 7, 'velocity': 80},
    {'start_time': 0.1, 'end_time': 0.4, 'midi_pitch': 66, 'string': 2, 'fret': 7, 'velocity': 70},
]
result = detect_techniques(notes)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
assert tech == 'b', f'Expected b, got {tech}'
print('PASS')

# Test 8: tempo scaling
print('=== Test 8: Tempo scaling ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 60, 'string': 3, 'fret': 5, 'velocity': 80},
    {'start_time': 0.35, 'end_time': 0.6, 'midi_pitch': 62, 'string': 3, 'fret': 7, 'velocity': 70},
]
result_fast = detect_techniques([n.copy() for n in notes], bpm=200)
result_slow = detect_techniques([n.copy() for n in notes], bpm=60)
print(f'  BPM=200: {result_fast[0].get("technique")}')
print(f'  BPM=60:  {result_slow[0].get("technique")}')
# At BPM=200: tempo_scale=0.6, hp_max=0.15 -> IOI 0.35 > 0.15, so no H/P
# At BPM=60:  tempo_scale=1.6 (capped), hp_max=0.40 -> IOI 0.35 <= 0.40, so H detected
assert result_slow[0].get('technique') == 'h'
print('PASS: tempo scaling works')

# Test 9: slide down (abs_pitch > 6, fret_diff in [2,5])
print('=== Test 9: Slide down ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 62, 'string': 3, 'fret': 10, 'velocity': 80},
    {'start_time': 0.2, 'end_time': 0.5, 'midi_pitch': 55, 'string': 3, 'fret': 5, 'velocity': 70},
]
# pitch_diff=-7, abs_pitch=7 > 6, fret_diff=5 -> slide '\\'
result = detect_techniques(notes)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
assert tech == '\\', f'Expected \\, got {tech}'
print('PASS')

# Test 10: no technique when different strings
print('=== Test 10: Different strings ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 60, 'string': 3, 'fret': 5, 'velocity': 80},
    {'start_time': 0.1, 'end_time': 0.4, 'midi_pitch': 62, 'string': 2, 'fret': 3, 'velocity': 70},
]
result = detect_techniques(notes)
t1 = result[0].get('technique')
t2 = result[1].get('technique')
print(f'  note[0].technique = {t1}')
print(f'  note[1].technique = {t2}')
# Different strings -> no pair technique should be detected
assert t1 is None, f'Expected None on different strings, got {t1}'
print('PASS')

# Test 11: glissando (fret_diff >= 5)
print('=== Test 11: Glissando ===')
notes = [
    {'start_time': 0.0, 'end_time': 0.3, 'midi_pitch': 48, 'string': 4, 'fret': 3, 'velocity': 80},
    {'start_time': 0.2, 'end_time': 0.5, 'midi_pitch': 60, 'string': 4, 'fret': 15, 'velocity': 70},
]
# pitch_diff=12, fret_diff=12 > GLISS_MIN_FRET=5, fret_diff > 5 so slide (<=5) won't fire
result = detect_techniques(notes)
tech = result[0].get('technique')
print(f'  note[0].technique = {tech}')
assert tech == 'gliss_up', f'Expected gliss_up, got {tech}'
print('PASS')

print()
print('All 12 tests passed!')
