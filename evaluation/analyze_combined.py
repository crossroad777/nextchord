"""
uspop2002 全曲 Duration 分析（直接predファイルとrefファイルを突合）
"""
import sys, json
import numpy as np
from pathlib import Path
import mir_eval

sys.stdout.reconfigure(encoding="utf-8")

LABELS_DIR = Path(r"D:\Music\datasets\chord_datasets\uspop2002\uspopLabels")
PRED_DIR = Path(r"D:\Music\nextchord\evaluation\uspop_predictions")

# レポート読み込み
with open(r"D:\Music\nextchord\evaluation\uspop_report.json", "r") as f:
    uspop = json.load(f)

with open(r"D:\Music\nextchord\evaluation\beatles_report.json", "r") as f:
    beatles = json.load(f)

# 全 .lab ファイルをスキャン (ref)
ref_map = {}
for lab_file in LABELS_DIR.rglob("*.lab"):
    artist_dir = lab_file.parent.parent.name  # e.g., "abba"
    title_stem = lab_file.stem  # e.g., "03-I_Have_A_Dream"
    # safe_name と同じ形式のキーを作る
    safe = f"{artist_dir}__{title_stem}"
    ref_map[safe] = str(lab_file)

# pred ファイルをスキャン
pred_files = {f.stem: str(f) for f in PRED_DIR.glob("*.lab")}

print(f"REF files: {len(ref_map)}")
print(f"PRED files: {len(pred_files)}")

# マッチング
matched = 0
duration_data = []

for pred_name, pred_path in pred_files.items():
    # pred_name: "abba__I_Have_A_Dream"
    # ref_map key: "abba__03-I_Have_A_Dream"
    # マッチングロジック: artist部分が一致 & title部分が含まれる
    parts = pred_name.split("__", 1)
    if len(parts) != 2:
        continue
    artist_part, title_part = parts
    
    # 完全マッチを試す
    ref_path = None
    for rkey, rpath in ref_map.items():
        rparts = rkey.split("__", 1)
        if len(rparts) != 2:
            continue
        r_artist, r_title = rparts
        if r_artist.lower() == artist_part.lower():
            # タイトル部分: "03-I_Have_A_Dream" から "I_Have_A_Dream" を抽出
            r_title_clean = r_title
            if len(r_title_clean) > 3 and r_title_clean[2] == "-":
                r_title_clean = r_title_clean[3:]
            if r_title_clean.lower() == title_part.lower():
                ref_path = rpath
                break
    
    if not ref_path:
        continue
    
    try:
        ref_int, ref_lab = mir_eval.io.load_labeled_intervals(ref_path)
        est_int, est_lab = mir_eval.io.load_labeled_intervals(pred_path)
        ref_dur = ref_int[-1][1]
        est_dur = est_int[-1][1]
        ratio = est_dur / ref_dur if ref_dur > 0 else 0
        
        # report から thirds スコアを取得
        artist_name = artist_part.replace("_", " ")
        title_name = title_part.replace("_", " ")
        thirds_score = None
        for r in uspop["results"]:
            if r["artist"].lower() == artist_name.lower() and r["title"].lower() == title_name.lower():
                thirds_score = r["thirds"]
                break
        
        if thirds_score is not None:
            duration_data.append({
                "artist": artist_name,
                "title": title_name,
                "thirds": thirds_score,
                "ref_dur": ref_dur,
                "est_dur": est_dur,
                "dur_ratio": ratio,
            })
            matched += 1
    except:
        pass

print(f"Matched: {matched}")

# Duration ratio による分類
good_match = [x for x in duration_data if 0.85 <= x["dur_ratio"] <= 1.15]
bad_match = [x for x in duration_data if not (0.85 <= x["dur_ratio"] <= 1.15)]

print(f"\n{'='*65}")
print(f"Duration 分析 ({len(duration_data)}曲)")
print(f"{'='*65}")
print(f"  Duration マッチ (±15%): {len(good_match)}曲")
print(f"  Duration ミスマッチ: {len(bad_match)}曲")

# ---- Duration マッチ曲のスコア ----
if good_match:
    gm_thirds = [x["thirds"] for x in good_match]
    print(f"\n--- Duration マッチ曲 ({len(good_match)}曲) ---")
    print(f"  平均 thirds: {np.mean(gm_thirds):.4f}")
    hi = len([x for x in good_match if x["thirds"] >= 0.7])
    mid = len([x for x in good_match if 0.3 <= x["thirds"] < 0.7])
    lo = len([x for x in good_match if x["thirds"] < 0.3])
    print(f"  >= 0.7: {hi}")
    print(f"  0.3-0.7: {mid}")
    print(f"  < 0.3: {lo}")

    # Good曲のみ (thirds >= 0.3)
    gm_good = [x for x in good_match if x["thirds"] >= 0.3]
    if gm_good:
        print(f"\n  Duration-match & thirds>=0.3: {len(gm_good)}曲")
        print(f"  平均 thirds: {np.mean([x['thirds'] for x in gm_good]):.4f}")

# ---- Duration ミスマッチ曲 ----
if bad_match:
    print(f"\n--- Duration ミスマッチ曲 ({len(bad_match)}曲) ---")
    print(f"  平均 thirds: {np.mean([x['thirds'] for x in bad_match]):.4f}")
    for x in sorted(bad_match, key=lambda z: z["dur_ratio"])[:10]:
        print(f"    {x['thirds']:.3f}  ratio={x['dur_ratio']:.2f}  ref={x['ref_dur']:.0f}s est={x['est_dur']:.0f}s  {x['artist']} - {x['title']}")
    if len(bad_match) > 10:
        print(f"    ... and {len(bad_match) - 10} more")

# ---- Duration マッチだが低スコアの曲 ----
gm_low = [x for x in good_match if x["thirds"] < 0.3]
if gm_low:
    print(f"\n--- Duration マッチだが低スコア (thirds<0.3): {len(gm_low)}曲 ---")
    print(f"  (音源は正しいが BTC が苦手な曲)")
    for x in sorted(gm_low, key=lambda z: z["thirds"]):
        print(f"    {x['thirds']:.3f}  ratio={x['dur_ratio']:.2f}  {x['artist']} - {x['title']}")

# ===== 総合サマリー =====
print(f"\n{'='*65}")
print(f"総合ベンチマーク")
print(f"{'='*65}")

# Beatles
b_all = beatles["results"]
b_good = [x for x in b_all if x["thirds"] >= 0.3]
print(f"\n【Beatles (Isophonics)】")
print(f"  全{len(b_all)}曲 → thirds = {beatles['average']['thirds']:.4f}")
print(f"  Good曲 {len(b_good)}曲 → thirds = {np.mean([x['thirds'] for x in b_good]):.4f}")

# uspop2002
print(f"\n【uspop2002】")
print(f"  全{len(uspop['results'])}曲 → thirds = {uspop['average']['thirds']:.4f}")
if good_match:
    print(f"  Duration-clean {len(good_match)}曲 → thirds = {np.mean([x['thirds'] for x in good_match]):.4f}")
    if gm_good:
        print(f"  Duration-clean & Good {len(gm_good)}曲 → thirds = {np.mean([x['thirds'] for x in gm_good]):.4f}")

# 結合
print(f"\n【結合 (クリーン)】")
if gm_good:
    combined = list(b_good) + [{"thirds": x["thirds"]} for x in gm_good]
    print(f"  Beatles Good + uspop Clean&Good: {len(combined)}曲")
    print(f"  結合 thirds: {np.mean([x['thirds'] for x in combined]):.4f}")

print(f"\n【BTC論文参照値】")
print(f"  Beatles thirds: 0.860 (正規CD)")
print(f"  uspop2002 thirds: ~0.75-0.80 (正規CD)")
