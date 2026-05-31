"""
既存セッションのdisplay_phrasesをbar_positionsベースで再生成するスクリプト
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from phrase_processor import process_phrases_for_display
from lyrics_postprocess import clean_hallucinated_endings

UPLOADS_DIR = r"D:\Music\nextchord\uploads"

def regenerate_display_phrases(session_dir):
    """1セッションのdisplay_phrasesを再生成"""
    session_path = os.path.join(session_dir, "session.json")
    if not os.path.exists(session_path):
        return None
    
    with open(session_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if data.get("status") != "completed":
        return None
    
    result = data.get("result", {})
    lyrics_phrases = result.get("lyrics_phrases", [])
    bar_positions = result.get("bar_positions", [])
    
    if not lyrics_phrases:
        return None
    
    # 再生成
    cleaned = clean_hallucinated_endings(lyrics_phrases)
    old_display = result.get("display_phrases", [])
    new_display = process_phrases_for_display(
        cleaned, target_chars=30,
        bar_positions=bar_positions if bar_positions else None
    )
    # bar分割後も再度ハルシネーション除去
    new_display = clean_hallucinated_endings(new_display)
    
    # 更新
    result["display_phrases"] = new_display
    data["result"] = result
    
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    sid = os.path.basename(session_dir)
    return {
        "session": sid[-6:],
        "old_count": len(old_display),
        "new_count": len(new_display),
        "bars": len(bar_positions),
        "first_text": new_display[0]["text"][:30] if new_display else ""
    }

# 全セッション再生成
results = []
for entry in sorted(os.listdir(UPLOADS_DIR)):
    full_path = os.path.join(UPLOADS_DIR, entry)
    if os.path.isdir(full_path):
        r = regenerate_display_phrases(full_path)
        if r:
            results.append(r)
            print(f"  {r['session']}: {r['old_count']} -> {r['new_count']} phrases (bars={r['bars']})")

print(f"\nRegenerated {len(results)} sessions")
