"""
NextChord 評価パイプライン
=========================
U-FRET の正解コード進行と BTC 予測を比較して精度を測定する。

【評価手法】
- U-FRET にはタイムスタンプが無いため、フレーム単位 (mir_eval) の評価は不可
- 代わりに「コード変化のシーケンス」を比較する
  1. chord_sequence_accuracy: 正解と予測のコード変化列を LCS で比較
  2. chord_set_precision/recall: 使用コードの集合比較 
  3. root_accuracy: ルート音だけで比較（maj/min 混同を無視）

【ステップ】
1. YouTube から音源ダウンロード (yt-dlp)
2. U-FRET からコード進行をスクレイピング (Selenium/requests)
3. BTC エンジンで予測
4. 予測 vs 正解 をシーケンス比較
5. レポート出力
"""

import json
import os
import sys
import re
import subprocess
import time
from pathlib import Path
from collections import Counter

# --- 設定 ---
BASE_DIR = Path(__file__).parent
SONGLIST = BASE_DIR / "songlist.json"
AUDIO_DIR = BASE_DIR / "audio"
RESULTS_DIR = BASE_DIR / "results"
REPORT_PATH = BASE_DIR / "report.txt"

# NextChord backend
BACKEND_DIR = Path(r"D:\Music\nextchord\fastapi-backend")
VENV_PYTHON = Path(r"D:\Music\nextchord\venv312\Scripts\python.exe")
YT_DLP = Path(r"D:\Music\nextchord\venv312\Scripts\yt-dlp.exe")

AUDIO_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# =================================================================
# コード正規化（比較用）
# =================================================================
# U-FRET表記 → BTC表記への変換
CHORD_ALIASES = {
    "Cmaj7": "CM7", "Dmaj7": "DM7", "Emaj7": "EM7", "Fmaj7": "FM7",
    "Gmaj7": "GM7", "Amaj7": "AM7", "Bmaj7": "BM7",
    "A#": "Bb", "C#": "Db", "D#": "Eb", "F#": "F#", "G#": "Ab",
}

def normalize_chord(chord):
    """コードを正規化して比較可能にする"""
    if not chord or chord in ("N.C.", "N", "", "—"):
        return None
    chord = chord.strip()
    # on コード (分数コード) → ルートのみ
    chord = chord.split("/")[0]
    # sus, add, dim 等の装飾を簡略化
    # まずエイリアス変換
    for alias, canonical in CHORD_ALIASES.items():
        if chord.startswith(alias):
            chord = canonical + chord[len(alias):]
            break
    # ルート + 品質のみ抽出 (例: C#m7 → C#m, Dsus4 → D)
    m = re.match(r'^([A-G][#b]?)(m(?!aj))?', chord)
    if m:
        root = m.group(1)
        quality = m.group(2) or ""
        return root + quality  # "C", "Cm", "F#m" 等
    return chord

def extract_root(chord):
    """コードからルート音だけ取り出す"""
    if not chord:
        return None
    m = re.match(r'^([A-G][#b]?)', chord)
    return m.group(1) if m else None

def chord_changes(chord_list):
    """連続する同一コードを除去して変化列を取得"""
    changes = []
    prev = None
    for c in chord_list:
        nc = normalize_chord(c)
        if nc and nc != prev:
            changes.append(nc)
            prev = nc
    return changes

# =================================================================
# LCS (Longest Common Subsequence) — シーケンス比較
# =================================================================
def lcs_length(a, b):
    """2つのリストのLCS長を計算"""
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i-1] == b[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = max(dp[i-1][j], dp[i][j-1])
    return dp[m][n]

def sequence_accuracy(ref, est):
    """LCSベースのシーケンス精度 (0.0 ~ 1.0)"""
    if not ref or not est:
        return 0.0
    lcs = lcs_length(ref, est)
    # precision と recall の調和平均 (F1)
    precision = lcs / len(est) if est else 0
    recall = lcs / len(ref) if ref else 0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)

def root_sequence_accuracy(ref, est):
    """ルート音のみでのシーケンス精度"""
    ref_roots = [extract_root(c) for c in ref if extract_root(c)]
    est_roots = [extract_root(c) for c in est if extract_root(c)]
    # 連続重複除去
    def dedup(lst):
        out = []
        for x in lst:
            if not out or x != out[-1]:
                out.append(x)
        return out
    return sequence_accuracy(dedup(ref_roots), dedup(est_roots))

def chord_set_metrics(ref, est):
    """使用コードの集合比較"""
    ref_set = set(ref)
    est_set = set(est)
    if not ref_set:
        return {"precision": 0, "recall": 0, "f1": 0}
    tp = len(ref_set & est_set)
    precision = tp / len(est_set) if est_set else 0
    recall = tp / len(ref_set) if ref_set else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    return {"precision": precision, "recall": recall, "f1": f1}

# =================================================================
# Step 1: YouTube からダウンロード
# =================================================================
def download_audio(song, max_duration=600):
    """YouTube から音源をダウンロード (既にあればスキップ)"""
    out_path = AUDIO_DIR / f"{song['id']:03d}.wav"
    if out_path.exists():
        print(f"  [SKIP] Audio already exists: {out_path.name}")
        return out_path

    query = song.get("youtube_query", f"{song['artist']} {song['title']}")
    print(f"  [DL] Searching YouTube: {query}")

    try:
        cmd = [
            str(YT_DLP),
            f"ytsearch1:{query}",
            "-x", "--audio-format", "wav",
            "--audio-quality", "0",
            "--max-filesize", "100M",
            "-o", str(out_path),
            "--no-playlist",
            "--quiet", "--no-warnings",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"  [ERROR] yt-dlp failed: {result.stderr[:200]}")
            return None
        if out_path.exists():
            print(f"  [OK] Downloaded: {out_path.name}")
            return out_path
        # yt-dlp might add extension
        for ext in [".wav", ".wav.wav"]:
            p = AUDIO_DIR / f"{song['id']:03d}{ext}"
            if p.exists():
                p.rename(out_path)
                return out_path
        print(f"  [ERROR] File not found after download")
        return None
    except subprocess.TimeoutExpired:
        print(f"  [ERROR] Download timed out")
        return None
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None

# =================================================================
# Step 2: U-FRET からコード進行取得
# =================================================================
def scrape_ufret_chords(song):
    """U-FRET からコード進行をスクレイピング（キャッシュ付き）"""
    cache_path = RESULTS_DIR / f"{song['id']:03d}_ufret.json"
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  [CACHE] U-FRET chords: {len(data['chords'])} chords")
        return data["chords"]

    url = song["ufret"]
    print(f"  [SCRAPE] U-FRET: {url}")

    try:
        # U-FRET はコードをHTMLのspanタグ内に配置
        # JavaScriptレンダリングが必要な場合はseleniumが必要だが、
        # まずrequestsで試す
        import requests
        from bs4 import BeautifulSoup

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        # U-FRET のコードは <ruby> や class="chord" 内
        chords = []
        for el in soup.select(".chord, rt, [data-chord]"):
            text = el.get_text(strip=True)
            if text and re.match(r'^[A-G]', text):
                chords.append(text)

        # フォールバック: テキスト全体からコードを正規表現で抽出
        if not chords:
            text = soup.get_text()
            chords = re.findall(r'\b([A-G][#b]?(?:m|M|dim|aug|sus|add|7|9|11|13|maj7|m7|M7)*(?:/[A-G][#b]?)?)\b', text)

        if chords:
            # キャッシュ保存
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"title": song["title"], "artist": song["artist"], "chords": chords}, f, ensure_ascii=False, indent=2)
            print(f"  [OK] Scraped {len(chords)} chords")
            return chords
        else:
            print(f"  [WARN] No chords found — U-FRET requires browser scraping")
            return None

    except Exception as e:
        print(f"  [ERROR] Scraping failed: {e}")
        return None

# =================================================================
# Step 3: BTC でコード予測
# =================================================================
def predict_chords_btc(audio_path, song):
    """BTC エンジンでコード予測"""
    cache_path = RESULTS_DIR / f"{song['id']:03d}_btc.json"
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  [CACHE] BTC prediction: {len(data['chords'])} chords")
        return data["chords"]

    print(f"  [BTC] Predicting chords for {audio_path.name}...")

    # BTC エンジンを直接呼び出す
    script = f"""
import sys, json
sys.path.insert(0, r'{BACKEND_DIR}')
from btc_engine import BTCEngine

engine = BTCEngine(
    model_path=r'D:\\Music\\nextchord\\BTC-ISMIR19\\finetuned\\btc_finetuned_val05_best.pt',
    config_path=r'D:\\Music\\nextchord\\BTC-ISMIR19\\test\\btc_model.pt',
    use_large_voca=False
)
results = engine.predict(r'{audio_path}')
chords = [r['chord'] for r in results]
# 出力
print(json.dumps(chords, ensure_ascii=False))
"""
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", script],
            capture_output=True, text=True, timeout=120,
            cwd=str(BACKEND_DIR),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        if result.returncode != 0:
            print(f"  [ERROR] BTC failed: {result.stderr[:300]}")
            return None

        # 最後の行がJSON
        lines = result.stdout.strip().split("\n")
        chords = json.loads(lines[-1])

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"audio": str(audio_path), "chords": chords}, f, ensure_ascii=False, indent=2)
        print(f"  [OK] BTC predicted {len(chords)} chords")
        return chords

    except subprocess.TimeoutExpired:
        print(f"  [ERROR] BTC prediction timed out")
        return None
    except Exception as e:
        print(f"  [ERROR] BTC failed: {e}")
        return None

# =================================================================
# Step 4: 評価
# =================================================================
def evaluate_song(song, ref_chords, est_chords):
    """1曲分の評価"""
    ref_changes = chord_changes(ref_chords)
    est_changes = chord_changes(est_chords)

    seq_acc = sequence_accuracy(ref_changes, est_changes)
    root_acc = root_sequence_accuracy(ref_changes, est_changes)
    set_metrics = chord_set_metrics(ref_changes, est_changes)

    return {
        "id": song["id"],
        "title": song["title"],
        "artist": song["artist"],
        "ref_chords": len(ref_changes),
        "est_chords": len(est_changes),
        "sequence_f1": round(seq_acc, 4),
        "root_sequence_f1": round(root_acc, 4),
        "chord_set_precision": round(set_metrics["precision"], 4),
        "chord_set_recall": round(set_metrics["recall"], 4),
        "chord_set_f1": round(set_metrics["f1"], 4),
        "ref_unique": sorted(set(ref_changes)),
        "est_unique": sorted(set(est_changes)),
    }

# =================================================================
# メイン
# =================================================================
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("NextChord 評価パイプライン")
    print("=" * 60)

    with open(SONGLIST, "r", encoding="utf-8") as f:
        songs = json.load(f)

    print(f"\n対象曲数: {len(songs)}")

    results = []
    errors = []

    for song in songs:
        print(f"\n--- [{song['id']:03d}] {song['title']} / {song['artist']} ---")

        # Step 1: ダウンロード
        audio_path = download_audio(song)
        if not audio_path:
            errors.append({"id": song["id"], "title": song["title"], "error": "download_failed"})
            continue

        # Step 2: U-FRET スクレイピング
        ref_chords = scrape_ufret_chords(song)
        if not ref_chords:
            errors.append({"id": song["id"], "title": song["title"], "error": "scrape_failed"})
            continue

        # Step 3: BTC 予測
        est_chords = predict_chords_btc(audio_path, song)
        if not est_chords:
            errors.append({"id": song["id"], "title": song["title"], "error": "btc_failed"})
            continue

        # Step 4: 評価
        result = evaluate_song(song, ref_chords, est_chords)
        results.append(result)
        print(f"  >> seq_f1={result['sequence_f1']:.3f}, root_f1={result['root_sequence_f1']:.3f}, set_f1={result['chord_set_f1']:.3f}")

    # レポート生成
    print("\n" + "=" * 60)
    print("評価結果サマリー")
    print("=" * 60)

    if results:
        avg_seq = sum(r["sequence_f1"] for r in results) / len(results)
        avg_root = sum(r["root_sequence_f1"] for r in results) / len(results)
        avg_set = sum(r["chord_set_f1"] for r in results) / len(results)

        print(f"\n評価曲数: {len(results)} / {len(songs)}")
        print(f"エラー数: {len(errors)}")
        print(f"\n--- 平均スコア ---")
        print(f"  Sequence F1 (コード進行一致度): {avg_seq:.4f}")
        print(f"  Root Sequence F1 (ルート音一致度): {avg_root:.4f}")
        print(f"  Chord Set F1 (使用コード一致度):  {avg_set:.4f}")

        print(f"\n--- 曲別スコア ---")
        print(f"{'ID':>4} {'Seq_F1':>7} {'Root_F1':>8} {'Set_F1':>7}  Title")
        print("-" * 60)
        for r in sorted(results, key=lambda x: x["sequence_f1"], reverse=True):
            print(f"{r['id']:4d} {r['sequence_f1']:7.3f} {r['root_sequence_f1']:8.3f} {r['chord_set_f1']:7.3f}  {r['title']}")

    # JSON レポート保存
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_songs": len(songs),
        "evaluated": len(results),
        "errors": len(errors),
        "average": {
            "sequence_f1": round(avg_seq, 4) if results else 0,
            "root_sequence_f1": round(avg_root, 4) if results else 0,
            "chord_set_f1": round(avg_set, 4) if results else 0,
        },
        "results": results,
        "errors_detail": errors,
    }
    report_json = BASE_DIR / "report.json"
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nレポート保存: {report_json}")

if __name__ == "__main__":
    main()
