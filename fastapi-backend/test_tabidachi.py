"""
松山千春「旅立ち」-- BTC vs Ufret 比較テスト
===========================================
1. raw WAV -> BTC
2. Demucs -> other.wav -> BTC
3. Ufret のコード譜と目視比較
"""
import sys, time, subprocess, os
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'D:\Music\nextchord\fastapi-backend')
sys.path.insert(0, r'D:\Music\nextchord\BTC-ISMIR19')

from btc_engine import get_btc_engine
from chord_processing import standardize_chord
from pathlib import Path

WAV_PATH = Path(r"D:\Music\nextchord\tmp_vocal_test\tabidachi.wav")
TMP_DIR = Path(r"D:\Music\nextchord\tmp_vocal_test")

# Ufret のコード譜（手動抽出）
# 松山千春「旅立ち」キー: D
UFRET_CHORDS = """
[イントロ]
D G A D
D G A D

[Aメロ]
D A/C# Bm F#m G D Em A
D A/C# Bm F#m G D A D

[Bメロ]
G A F#m Bm Em A D D/C#
Bm D/A G F#m Em Asus4 A

[サビ]
D G A F#m Bm
G A D
D G A F#m Bm
G A D
"""

# 1. raw WAV -> BTC
print("=" * 65)
print("松山千春「旅立ち」 BTC コード検出テスト")
print("=" * 65)

engine = get_btc_engine()
engine.load()

print("\n--- [1] raw WAV -> BTC ---")
t1 = time.time()
seg_s, seg_l = engine.detect_chords(WAV_PATH)
t_raw = time.time() - t1
print(f"処理時間: {t_raw:.1f}s, セグメント数: {len(seg_s)}")
print(f"\n{'Time':>8s}  {'BTC Label':>15s}  {'Display':>12s}")
print("-" * 40)
for i in range(len(seg_s)):
    end = seg_s[i+1] if i+1 < len(seg_s) else 186.4  # 3:06
    dur = end - seg_s[i]
    label = seg_l[i]
    display = standardize_chord(label)
    if dur >= 0.5:  # 0.5秒以上のセグメントのみ
        mm = int(seg_s[i]) // 60
        ss = seg_s[i] % 60
        print(f"  {mm:01d}:{ss:05.2f}  {label:>15s}  {display:>12s}  ({dur:.1f}s)")

# 2. Demucs 分離
print("\n--- [2] Demucs 分離 ---")
t2 = time.time()
cmd = [
    sys.executable, "-m", "demucs.separate",
    "-n", "htdemucs",
    "-o", str(TMP_DIR),
    str(WAV_PATH)
]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
t_demucs = time.time() - t2
print(f"Demucs 処理時間: {t_demucs:.1f}s")
if result.returncode != 0:
    print(f"Demucs error: {result.stderr[:500]}")

other_wav = TMP_DIR / "htdemucs" / "tabidachi" / "other.wav"
if other_wav.exists():
    print(f"other.wav: {other_wav}")
    
    print("\n--- [3] Demucs other.wav -> BTC ---")
    t3 = time.time()
    seg_s2, seg_l2 = engine.detect_chords(other_wav)
    t_sep = time.time() - t3
    print(f"処理時間: {t_sep:.1f}s, セグメント数: {len(seg_s2)}")
    print(f"\n{'Time':>8s}  {'BTC Label':>15s}  {'Display':>12s}")
    print("-" * 40)
    for i in range(len(seg_s2)):
        end = seg_s2[i+1] if i+1 < len(seg_s2) else 186.4
        dur = end - seg_s2[i]
        label = seg_l2[i]
        display = standardize_chord(label)
        if dur >= 0.5:
            mm = int(seg_s2[i]) // 60
            ss = seg_s2[i] % 60
            print(f"  {mm:01d}:{ss:05.2f}  {label:>15s}  {display:>12s}  ({dur:.1f}s)")
else:
    print(f"other.wav not found: {other_wav}")

# 比較まとめ
print("\n" + "=" * 65)
print("Ufret 基準コード（キー: D）")
print("=" * 65)
print(UFRET_CHORDS)

# コードの一致率を簡易計算
def extract_unique_chords(seg_l):
    """N, X 以外のユニークコードを抽出"""
    chords = set()
    for c in seg_l:
        d = standardize_chord(c)
        if d != "N.C.":
            chords.add(d)
    return chords

ufret_chords = {'D', 'G', 'A', 'Bm', 'F#m', 'Em', 'Asus4'}
raw_chords = extract_unique_chords(seg_l)
print(f"\nUfret コード: {sorted(ufret_chords)}")
print(f"BTC raw コード: {sorted(raw_chords)}")
overlap = ufret_chords & raw_chords
print(f"一致: {sorted(overlap)} ({len(overlap)}/{len(ufret_chords)})")
print(f"BTC のみ: {sorted(raw_chords - ufret_chords)}")
print(f"Ufret のみ: {sorted(ufret_chords - raw_chords)}")

if other_wav.exists():
    sep_chords = extract_unique_chords(seg_l2)
    print(f"\nBTC Demucs コード: {sorted(sep_chords)}")
    overlap2 = ufret_chords & sep_chords
    print(f"一致: {sorted(overlap2)} ({len(overlap2)}/{len(ufret_chords)})")
    print(f"BTC のみ: {sorted(sep_chords - ufret_chords)}")
    print(f"Ufret のみ: {sorted(ufret_chords - sep_chords)}")
