"""
NextChord E2E 検証スクリプト
全修正項目を1行ずつ検証する
"""
import sys, os, json, time, re, requests

API = "http://localhost:8000"
PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} -- {detail}")

def section(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

# =============================================
# 1. Backend Health
# =============================================
section("1. Backend Health Check")
try:
    r = requests.get(f"{API}/health", timeout=10)
    data = r.json()
    check("Health endpoint returns 200", r.status_code == 200, f"status={r.status_code}")
    check("Status is healthy", data.get("status") == "healthy", f"status={data.get('status')}")
    check("Whisper model loaded", "Whisper" in str(data.get("whisper", "")), f"whisper={data.get('whisper')}")
except Exception as e:
    check("Health endpoint reachable", False, str(e))

# =============================================
# 2. Session List
# =============================================
section("2. Session List")
try:
    r = requests.get(f"{API}/sessions", timeout=10)
    sessions = r.json()
    check("Sessions endpoint returns 200", r.status_code == 200)
    check("Sessions is a list", isinstance(sessions, list), f"type={type(sessions)}")
    check("At least 1 session exists", len(sessions) >= 1, f"count={len(sessions)}")
except Exception as e:
    check("Sessions endpoint reachable", False, str(e))

# =============================================
# 3. Latest Session Analysis
# =============================================
section("3. Latest Session Data")
# Find latest completed session
latest_sid = None
uploads_dir = r"D:\Music\nextchord\uploads"
for d in sorted(os.listdir(uploads_dir), reverse=True):
    session_json = os.path.join(uploads_dir, d, "session.json")
    sheet_xml = os.path.join(uploads_dir, d, "sheet.musicxml")
    if os.path.exists(session_json) and os.path.exists(sheet_xml):
        latest_sid = d
        break

if not latest_sid:
    check("Found completed session", False, "No session with sheet.musicxml found")
    sys.exit(1)

print(f"  Using session: {latest_sid}")

# Load session data
session_path = os.path.join(uploads_dir, latest_sid, "session.json")
with open(session_path, 'r', encoding='utf-8') as f:
    session = json.load(f)

# =============================================
# 4. Whisper Hallucination Filter
# =============================================
section("4. Whisper Hallucination Filter")
lyrics_text = session.get("result", {}).get("lyrics", {}).get("text", "")
segments = session.get("result", {}).get("lyrics", {}).get("segments", [])

# Check for Korean characters (Hangul)
hangul_re = re.compile(r'[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]')
has_korean = bool(hangul_re.search(lyrics_text))
check("No Korean (Hangul) in lyrics", not has_korean, 
      f"Found Korean: {hangul_re.findall(lyrics_text)[:5]}")

# Check for known hallucinations
has_hodori = "hodori" in lyrics_text.lower() or "호돌이" in lyrics_text
check("No 'SoundHodori' in lyrics", not has_hodori,
      f"Found in: {lyrics_text[:100]}")

# Check for emoji
emoji_re = re.compile(r'[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF]')
has_emoji = bool(emoji_re.search(lyrics_text))
check("No emoji in lyrics", not has_emoji,
      f"Found emoji in lyrics text")

# Check lyrics exist (not all filtered)
check("Lyrics text is not empty", len(lyrics_text.strip()) > 0,
      f"lyrics_text length={len(lyrics_text)}")
check("At least 5 segments exist", len(segments) >= 5,
      f"segment count={len(segments)}")

# Check lyrics contain Japanese
jp_re = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')
has_japanese = bool(jp_re.search(lyrics_text))
check("Lyrics contain Japanese characters", has_japanese,
      f"No Japanese found in: {lyrics_text[:100]}")

# =============================================
# 5. MusicXML X Noteheads (Brushing)
# =============================================
section("5. MusicXML Brushing (X Noteheads)")
sheet_path = os.path.join(uploads_dir, latest_sid, "sheet.musicxml")
with open(sheet_path, 'r', encoding='utf-8') as f:
    xml_content = f.read()

x_noteheads = len(re.findall(r'<notehead>x</notehead>', xml_content))
total_notes = len(re.findall(r'<note', xml_content))
check("X noteheads exist in MusicXML", x_noteheads > 0,
      f"x_noteheads={x_noteheads}")
check("X noteheads > 50 (enough brushing)", x_noteheads > 50,
      f"x_noteheads={x_noteheads} (expected >50 for zuncha pattern)")
check("X noteheads ratio reasonable (10-40%)", 
      0.10 < x_noteheads/max(1,total_notes) < 0.40,
      f"ratio={x_noteheads}/{total_notes}={x_noteheads/max(1,total_notes):.1%}")

print(f"  Info: {x_noteheads} X noteheads / {total_notes} total notes")

# =============================================
# 6. Structured Data (Chords)
# =============================================
section("6. Chord Detection")
structured = session.get("result", {}).get("structured_data", [])
chords_set = set()
for entry in structured:
    c = entry.get("chord", "")
    if c and c != "N.C.":
        chords_set.add(c)

check("Multiple unique chords detected", len(chords_set) >= 3,
      f"unique chords={chords_set}")
check("Structured data has beat field", 
      len(structured) > 0 and "beat" in structured[0],
      f"keys={list(structured[0].keys()) if structured else 'empty'}")

# Check beat values
beat_values = set(e.get("beat") for e in structured if e.get("beat"))
check("Beat values include 1,2,3,4", 
      {1,2,3,4}.issubset(beat_values),
      f"beat_values={beat_values}")

print(f"  Info: Unique chords = {sorted(chords_set)}")

# =============================================
# 7. Strum Note Techniques
# =============================================
section("7. Strum Brushing Technique Field")
# Check tab_data or notes for mute_brush technique
notes = session.get("result", {}).get("notes", [])
if not notes:
    # Try tab_data
    notes = session.get("result", {}).get("tab_data", [])

mute_count = 0
tech_count = 0
for n in notes:
    tech = n.get("technique", "")
    techs = n.get("techniques", [])
    if tech == "mute_brush" or "mute_brush" in str(techs):
        mute_count += 1
    if tech or techs:
        tech_count += 1

check("Notes have mute_brush technique", mute_count > 0,
      f"mute_brush={mute_count}, total_tech={tech_count}")
check("Significant brushing count (>100)", mute_count > 100,
      f"mute_brush={mute_count}")

print(f"  Info: {mute_count} mute_brush / {len(notes)} total notes")

# =============================================
# 8. Frontend Accessibility
# =============================================
section("8. Frontend Check")
try:
    r = requests.get("http://localhost:5173/", timeout=10)
    check("Frontend returns 200", r.status_code == 200)
    check("HTML contains root div", 'id="root"' in r.text)
    check("No Korean in HTML", not hangul_re.search(r.text),
          "Korean found in frontend HTML")
except Exception as e:
    check("Frontend reachable", False, str(e))

# =============================================
# 9. MusicXML Lyrics
# =============================================
section("9. MusicXML Lyrics")
lyric_count = len(re.findall(r'<lyric', xml_content))
lyric_texts = re.findall(r'<text>(.*?)</text>', xml_content)
jp_lyric_count = sum(1 for t in lyric_texts if jp_re.search(t))

check("MusicXML has <lyric> elements", lyric_count > 0,
      f"lyric_count={lyric_count}")
check("Lyrics contain Japanese text", jp_lyric_count > 0,
      f"jp_lyrics={jp_lyric_count}/{len(lyric_texts)}")

# Check no Korean in MusicXML lyrics
korean_lyrics = [t for t in lyric_texts if hangul_re.search(t)]
check("No Korean in MusicXML lyrics", len(korean_lyrics) == 0,
      f"korean_lyrics={korean_lyrics[:3]}")

# Check no Hodori in MusicXML
check("No Hodori in MusicXML", "hodori" not in xml_content.lower(),
      "SoundHodori found in MusicXML")

print(f"  Info: {lyric_count} lyric elements, {jp_lyric_count} Japanese")

# =============================================
# 10. ProcessingView Step Order
# =============================================
section("10. ProcessingView Step Config")
pv_path = r"D:\Music\nextchord\nextchord-ui\src\components\ProcessingView.jsx"
with open(pv_path, 'r', encoding='utf-8') as f:
    pv_content = f.read()

# Check step order matches backend
step_keys = re.findall(r"key:\s*'(\w+)'", pv_content)
check("Steps include all 5 keys", 
      set(step_keys) == {'beats', 'key', 'whisper', 'chords', 'postprocess'},
      f"keys={step_keys}")

# Check avgSec values are reasonable
avg_secs = re.findall(r"avgSec:\s*(\d+)", pv_content)
avg_secs = [int(x) for x in avg_secs]
total_avg = sum(avg_secs)
check("Total avgSec is 30-60s", 30 <= total_avg <= 60,
      f"total={total_avg}s, values={avg_secs}")

# =============================================
# 11. TabView showTechniques prop
# =============================================
section("11. TabView Component")
tv_path = r"D:\Music\nextchord\nextchord-ui\src\components\TabView.jsx"
with open(tv_path, 'r', encoding='utf-8') as f:
    tv_content = f.read()

check("TabView accepts showTechniques prop",
      "showTechniques" in tv_content.split('\n')[6],  # first line of component
      "showTechniques not in props destructuring")

check("SVG spacing added in renderFinished",
      "marginBottom" in tv_content,
      "No marginBottom CSS for SVG spacing")

# =============================================
# Summary
# =============================================
print(f"\n{'='*60}")
print(f"  SUMMARY: {PASS} PASS / {FAIL} FAIL / {PASS+FAIL} TOTAL")
print(f"{'='*60}")
if FAIL > 0:
    print(f"\n  ⚠ {FAIL} tests FAILED!")
    sys.exit(1)
else:
    print(f"\n  ✅ All tests passed!")
    sys.exit(0)
