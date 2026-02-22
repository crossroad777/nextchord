"""
lyrics_postprocess.py — Whisper日本語歌詞の後処理

Whisperの出力にありがちな日本語誤認識パターンを修正する。
音楽の歌詞に特化した補正ロジック。
"""
import re
import unicodedata


def postprocess_japanese_lyrics(text: str) -> str:
    """
    日本語歌詞テキストの後処理。
    Whisperのよくある誤認識パターンを修正する。
    """
    if not text:
        return text

    result = text

    # === 1. 全角/半角の統一 ===
    # 半角カタカナ → 全角カタカナ
    result = unicodedata.normalize('NFKC', result)

    # === 2. 不要な空白の除去 ===
    # 日本語文字間の不要なスペースを除去（英単語間のスペースは保持）
    result = re.sub(r'(?<=[ぁ-んァ-ヶー一-龥])\s+(?=[ぁ-んァ-ヶー一-龥])', '', result)

    # === 3. Whisperのよくある誤認識パターン修正 ===
    _corrections = {
        # 汎用的なWhisper誤認識パターンのみ
        # ※曲固有の誤認識はここに入れない（手動編集で対応）
        
        # 繰り返しハルシネーション対策（最後にクレジットが出る）
        '作詞・作曲・編曲・編曲': '',
        '作詞作曲': '',
        '作詞・作曲': '',
        'ご視聴ありがとうございました': '',
        'チャンネル登録': '',
        'ご清聴ありがとうございました': '',
    }

    for wrong, correct in _corrections.items():
        if wrong in result:
            result = result.replace(wrong, correct)

    # === 4. 繰り返し検出 ===
    # 同じ文字が4回以上連続する場合は2回に制限（「ああああ」→「ああ」）
    # ただし「ー」（長音）は許可
    result = re.sub(r'([^ー])\1{3,}', r'\1\1', result)

    # === 5. 句読点の統一 ===
    # 全角ピリオド → 句点（歌詞ではあまり使わないが統一）
    result = result.replace('．', '。')
    result = result.replace('，', '、')

    # === 6. 前後の空白除去 ===
    result = result.strip()

    return result


def postprocess_whisper_segments(segments: list) -> list:
    """
    Whisperのセグメントリスト全体を後処理する。
    
    Args:
        segments: Whisperのsegmentsリスト
    
    Returns:
        修正済みのsegmentsリスト
    """
    if not segments:
        return segments

    processed = []
    for seg in segments:
        new_seg = dict(seg)

        # セグメントテキストの修正
        new_seg['text'] = postprocess_japanese_lyrics(new_seg.get('text', ''))

        # 単語レベルのタイムスタンプも修正
        if 'words' in new_seg:
            new_words = []
            for w in new_seg['words']:
                new_w = dict(w)
                word_text = postprocess_japanese_lyrics(new_w.get('word', ''))
                if word_text:  # 空になった単語は除去
                    new_w['word'] = word_text
                    new_words.append(new_w)
            new_seg['words'] = new_words

        # 空のセグメントは除去
        if new_seg['text'].strip():
            processed.append(new_seg)

    # --- ハルシネーション検出 ---
    # 最後のセグメントが不自然に短い or 繰り返しの場合除去
    if len(processed) > 2:
        last = processed[-1]
        last_text = last['text'].strip()

        # 最後のセグメントが5文字以下で歌詞っぽくない
        if len(last_text) <= 5 and not re.search(r'[ぁ-ん]{2,}', last_text):
            processed.pop()

    # --- 重複セグメント検出 ---
    # 同じテキストが連続する場合、2つ目を除去
    deduped = [processed[0]] if processed else []
    for i in range(1, len(processed)):
        if processed[i]['text'].strip() != processed[i-1]['text'].strip():
            deduped.append(processed[i])

    return deduped


def clean_hallucinated_endings(lyrics_phrases: list) -> list:
    """
    歌詞フレーズリストから、曲の最後に出るWhisperハルシネーションを除去。
    """
    if not lyrics_phrases:
        return lyrics_phrases

    # ハルシネーションパターン
    _hallucination_patterns = [
        r'作詞', r'作曲', r'編曲', r'MV', r'PV',
        r'ご視聴', r'ご清聴', r'チャンネル',
        r'Music\s*Video', r'Official',
        r'^\s*$',  # 空文字
    ]

    cleaned = []
    for phrase in lyrics_phrases:
        text = phrase.get('text', '')
        is_hallucination = False
        for pat in _hallucination_patterns:
            if re.search(pat, text, re.IGNORECASE):
                is_hallucination = True
                break
        if not is_hallucination:
            cleaned.append(phrase)

    return cleaned


# --- テスト用 ---
if __name__ == "__main__":
    test_cases = [
        "お笑のままわがまま許してよベイビー",
        "君への愛だけおままりにして",
        "間に合わせの化けの香茶君にはお見通し",
        "作詞・作曲・編曲・編曲",
        "ああああああ",
        "遠回りしてたどり着くから",
    ]

    print("=== 歌詞後処理テスト ===")
    for t in test_cases:
        result = postprocess_japanese_lyrics(t)
        if result != t:
            print(f"  ✅ [{t}] → [{result}]")
        else:
            print(f"  ○ [{t}] (変更なし)")
