"""
NextChord YouTube Cookie Setup
===============================
ブラウザのクッキーをModal Secretに登録するヘルパースクリプト。

使い方:
  1. Chromeを完全に閉じる (タスクトレイも)
  2. このスクリプトを実行:
     python setup_yt_cookies.py
  3. 完了！以降YouTubeダウンロードが動作します
"""
import subprocess
import sys
import tempfile
import os

def main():
    print("=" * 60)
    print("  NextChord YouTube Cookie Setup")
    print("=" * 60)
    print()
    
    # Step 1: Try to export cookies from browser
    cookies_content = None
    cookies_file = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8')
    cookies_path = cookies_file.name
    cookies_file.close()
    
    browsers = ["chrome", "edge", "firefox", "brave", "opera"]
    
    for browser in browsers:
        print(f"[*] {browser} からクッキーを取得中...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "yt_dlp",
                 "--cookies-from-browser", browser,
                 "--cookies", cookies_path,
                 "--skip-download",
                 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and os.path.getsize(cookies_path) > 100:
                with open(cookies_path, 'r', encoding='utf-8') as f:
                    cookies_content = f.read()
                print(f"[✓] {browser} からクッキーを取得しました！")
                break
            else:
                print(f"[x] {browser}: 失敗 - {result.stderr[:100] if result.stderr else '空のクッキー'}")
        except Exception as e:
            print(f"[x] {browser}: {str(e)[:80]}")
    
    # Step 2: If browser export failed, ask for manual paste
    if not cookies_content:
        print()
        print("-" * 60)
        print("ブラウザからの自動取得に失敗しました。")
        print("手動でクッキーを貼り付けてください。")
        print()
        print("手順:")
        print("  1. Chrome拡張 'Get cookies.txt LOCALLY' をインストール")
        print("     https://chromewebstore.google.com/detail/cclelndahbckbenkjhflpdbgdldlbecc")
        print("  2. YouTubeを開く (ログイン状態)")
        print("  3. 拡張アイコンをクリック → 'Export' → コピー")
        print("  4. ファイルに保存: d:/Music/nextchord/_modal/yt_cookies.txt")
        print("-" * 60)
        
        cookie_file_path = "d:/Music/nextchord/_modal/yt_cookies.txt"
        input(f"\n{cookie_file_path} にクッキーを保存したら Enter を押してください...")
        
        if os.path.exists(cookie_file_path):
            with open(cookie_file_path, 'r', encoding='utf-8') as f:
                cookies_content = f.read()
        else:
            print(f"[!] ファイルが見つかりません: {cookie_file_path}")
            sys.exit(1)
    
    if not cookies_content or len(cookies_content.strip()) < 50:
        print("[!] クッキーが空または無効です")
        sys.exit(1)
    
    # Step 3: Verify cookies work
    print()
    print("[*] クッキーをテスト中...")
    test_cookie_file = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8')
    test_cookie_file.write(cookies_content)
    test_cookie_file.close()
    
    test_result = subprocess.run(
        [sys.executable, "-m", "yt_dlp",
         "--cookies", test_cookie_file.name,
         "--no-playlist", "--skip-download",
         "--print", "%(title)s",
         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
        capture_output=True, text=True, timeout=30
    )
    os.remove(test_cookie_file.name)
    
    if test_result.returncode == 0 and test_result.stdout.strip():
        print(f"[✓] クッキーが有効です！ (テスト動画: {test_result.stdout.strip()})")
    else:
        print(f"[!] クッキーが無効な可能性があります: {test_result.stderr[:200]}")
        answer = input("続行しますか？ (y/N): ")
        if answer.lower() != 'y':
            sys.exit(1)
    
    # Step 4: Upload to Modal Secret
    print()
    print("[*] Modal Secretにアップロード中...")
    
    # Write cookies to a temp file for the modal command
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    
    # Use modal secret create/update
    modal_result = subprocess.run(
        [sys.executable, "-m", "modal", "secret", "create", "youtube-cookies",
         f"YOUTUBE_COOKIES={cookies_content}",
         "--force"],
        capture_output=True, text=True, env=env, timeout=30
    )
    
    if modal_result.returncode == 0:
        print("[✓] Modal Secretを更新しました！")
        print()
        print("=" * 60)
        print("  セットアップ完了！")
        print("  NextChordからYouTube URLで解析できます。")
        print("  (クッキーは通常1〜2年有効です)")
        print("=" * 60)
    else:
        print(f"[!] Modal Secretの更新に失敗: {modal_result.stderr[:200]}")
        print("手動で実行してください:")
        print(f'  python -m modal secret create youtube-cookies "YOUTUBE_COOKIES=..." --force')
        sys.exit(1)
    
    # Cleanup
    try:
        os.remove(cookies_path)
    except:
        pass

if __name__ == "__main__":
    main()
