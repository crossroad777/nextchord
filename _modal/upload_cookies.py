import subprocess, os, sys

cookie_path = "d:/Music/nextchord/_modal/www.youtube.com_cookies.txt"
with open(cookie_path, "r", encoding="utf-8") as f:
    cookies = f.read()

print(f"Cookie length: {len(cookies)} chars")
print(f"Contains .youtube.com: {'.youtube.com' in cookies}")
lines = [l for l in cookies.split('\n') if l.strip() and not l.startswith('#')]
print(f"Cookie entries: {len(lines)}")

# Set Modal secret
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"
result = subprocess.run(
    [sys.executable, "-m", "modal", "secret", "create", "youtube-cookies",
     f"YOUTUBE_COOKIES={cookies}", "--force"],
    capture_output=True, text=True, env=env
)
print(f"Modal exit code: {result.returncode}")
if result.stdout:
    print(result.stdout[:300])
if result.stderr:
    print(f"Error: {result.stderr[:300]}")
