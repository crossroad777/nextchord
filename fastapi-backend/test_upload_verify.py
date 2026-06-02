"""
新規アップロードして最新コードの修正を検証
"""
import requests, time, json, sys

API = "http://localhost:8000"
WAV = r"D:\Music\nextchord\uploads\20260522-233134-499132ff\converted.wav"

print("=== Uploading test file ===")
with open(WAV, 'rb') as f:
    r = requests.post(f"{API}/upload", files={"file": ("test.wav", f, "audio/wav")}, timeout=30)

if r.status_code != 200:
    print(f"Upload FAILED: {r.status_code} {r.text}")
    sys.exit(1)

data = r.json()
sid = data.get("session_id")
print(f"Session ID: {sid}")

# Poll until done
print("=== Polling status ===")
max_wait = 120  # 2 minutes max
start = time.time()
while time.time() - start < max_wait:
    try:
        r = requests.get(f"{API}/status/{sid}", timeout=10)
        status = r.json()
        phase = status.get("phase", "")
        steps = status.get("steps_done", 0)
        total = status.get("steps_total", 5)
        print(f"  [{time.time()-start:.0f}s] phase={phase} steps={steps}/{total}")
        
        if phase == "done":
            print("  Pipeline complete!")
            break
        if phase == "error":
            print(f"  Pipeline ERROR: {status}")
            sys.exit(1)
    except Exception as e:
        print(f"  Error: {e}")
    
    time.sleep(3)

# Get result
print("\n=== Checking result ===")
r = requests.get(f"{API}/result/{sid}", timeout=30)
if r.status_code != 200:
    print(f"Result FAILED: {r.status_code}")
    sys.exit(1)

result = r.json()

# Check lyrics
lyrics = result.get("lyrics", {})
lyrics_text = lyrics.get("text", "")
segments = lyrics.get("segments", [])
print(f"\nLyrics text length: {len(lyrics_text)}")
print(f"Lyrics segments: {len(segments)}")
if lyrics_text:
    print(f"First 200 chars: {lyrics_text[:200]}")
else:
    print("WARNING: Lyrics text is EMPTY!")

# Check for hallucinations
import re
hangul = re.compile(r'[\uAC00-\uD7AF]')
if hangul.search(lyrics_text):
    print("FAIL: Korean text found in lyrics!")
elif "hodori" in lyrics_text.lower():
    print("FAIL: SoundHodori found!")
else:
    print("PASS: No hallucinations detected")

# Check MusicXML
print("\n=== Checking MusicXML ===")
r = requests.get(f"{API}/result/{sid}/musicxml", timeout=30)
if r.status_code == 200:
    xml = r.text
    x_count = len(re.findall(r'<notehead>x</notehead>', xml))
    note_count = len(re.findall(r'<note', xml))
    lyric_count = len(re.findall(r'<lyric', xml))
    print(f"X noteheads: {x_count}")
    print(f"Total notes: {note_count}")
    print(f"Lyric elements: {lyric_count}")
    
    if x_count > 50:
        print("PASS: Brushing X noteheads present")
    else:
        print(f"FAIL: Only {x_count} X noteheads")
    
    if lyric_count > 0:
        print("PASS: MusicXML has lyrics")
    else:
        print("FAIL: No lyrics in MusicXML")
    
    # Check for Korean in lyrics
    lyric_texts = re.findall(r'<text>(.*?)</text>', xml)
    korean_lyrics = [t for t in lyric_texts if hangul.search(t)]
    if korean_lyrics:
        print(f"FAIL: Korean in MusicXML lyrics: {korean_lyrics[:3]}")
    else:
        print("PASS: No Korean in MusicXML lyrics")
else:
    print(f"MusicXML FAILED: {r.status_code}")

print("\n=== Done ===")
