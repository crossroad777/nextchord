"""
U-FRET コード一括抽出スクリプト
================================
ブラウザのDevToolsコンソールにコピペして実行するJavaScriptを生成する。
生成されたJSをブラウザで実行すると、全曲のコード進行をJSON形式で取得できる。
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
SONGLIST = BASE_DIR / "songlist.json"

with open(SONGLIST, "r", encoding="utf-8") as f:
    songs = json.load(f)

# 各曲のURLリストを出力
urls = [s["ufret"] for s in songs]

# ブラウザで実行するJavaScript
js_code = f"""
// === U-FRET 50曲一括コード抽出 ===
// ブラウザの DevTools Console にペーストして実行

const urls = {json.dumps(urls)};
const results = [];

async function scrapeOne(url, idx) {{
  return new Promise((resolve) => {{
    const iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    iframe.src = url;
    document.body.appendChild(iframe);
    
    iframe.onload = () => {{
      setTimeout(() => {{
        try {{
          const doc = iframe.contentDocument || iframe.contentWindow.document;
          const chords = Array.from(doc.querySelectorAll('rt'))
            .map(e => e.textContent.trim())
            .filter(t => /^[A-G]/.test(t));
          const title = doc.querySelector('title')?.textContent?.split('/')[0]?.trim() || '';
          results.push({{ idx, url, title, chords }});
          console.log(`[${{idx+1}}/${{urls.length}}] ${{title}}: ${{chords.length}} chords`);
        }} catch(e) {{
          console.warn(`[${{idx+1}}] Cross-origin error:`, e);
          results.push({{ idx, url, title: 'ERROR', chords: [] }});
        }}
        document.body.removeChild(iframe);
        resolve();
      }}, 3000);
    }};
    
    iframe.onerror = () => {{
      results.push({{ idx, url, title: 'LOAD_ERROR', chords: [] }});
      document.body.removeChild(iframe);
      resolve();
    }};
  }});
}}

(async () => {{
  // 同時5件ずつ処理
  for (let i = 0; i < urls.length; i += 5) {{
    const batch = urls.slice(i, i+5).map((url, j) => scrapeOne(url, i+j));
    await Promise.all(batch);
    console.log(`=== Batch ${{Math.floor(i/5)+1}} done ===`);
  }}
  
  // 結果をダウンロード
  const blob = new Blob([JSON.stringify(results, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'ufret_chords_50.json';
  a.click();
  console.log('=== 完了! ufret_chords_50.json をダウンロードしました ===');
}})();
"""

print("=" * 60)
print("U-FRET コード抽出 JavaScript")
print("=" * 60)
print()
print("【手順】")
print("1. ブラウザで https://www.ufret.jp/ を開く")
print("2. DevTools (F12) → Console タブを開く")
print("3. 以下のJSをペーストして実行")
print("4. ufret_chords_50.json が自動ダウンロードされる")
print()
print("※ iframeのcross-origin制限で失敗する場合あり")
print("   その場合は個別取得スクリプトを使用")
print()

# 代替案: 個別にフェッチするシンプルなスクリプト
simple_js = """
// === 個別ページ用: このページのコードを抽出 ===
// U-FRET の曲ページで実行
const chords = Array.from(document.querySelectorAll('rt'))
  .map(e => e.textContent.trim())
  .filter(t => /^[A-G]/.test(t));
const title = document.title.split('/')[0].trim();
const artist = document.title.split('/')[1]?.trim()?.split(' ')[0] || '';
console.log(JSON.stringify({title, artist, chords}));
// クリップボードにコピー
copy(JSON.stringify({title, artist, chords}));
console.log('📋 Copied to clipboard!');
"""

# ファイル保存
with open(BASE_DIR / "scrape_all.js", "w", encoding="utf-8") as f:
    f.write(js_code)

with open(BASE_DIR / "scrape_one.js", "w", encoding="utf-8") as f:
    f.write(simple_js)

print("保存済み:")
print(f"  - {BASE_DIR / 'scrape_all.js'} (一括取得)")
print(f"  - {BASE_DIR / 'scrape_one.js'} (個別取得)")
