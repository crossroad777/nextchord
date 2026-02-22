"""
phrase_processor.py — Janome形態素解析による日本語歌詞フレーズ処理

Whisperの出力フレーズを自然な日本語の単語境界で結合・分割し、
テキストビュー表示用のフレーズリストを生成する。
"""
import re
from janome.tokenizer import Tokenizer

_tokenizer = Tokenizer()


def _clean(text: str) -> str:
    """空白除去"""
    return re.sub(r'\s+', '', text).strip()


def _get_word_boundaries(text: str) -> list[tuple[int, str, str, str]]:
    """
    Janome形態素解析でテキストの単語境界位置と品詞情報を取得する。
    戻り値: [(position, surface, pos_top, pos_detail), ...]
    """
    tokens = list(_tokenizer.tokenize(text))
    boundaries = []
    pos = 0
    for token in tokens:
        pos += len(token.surface)
        if pos < len(text):
            parts = token.part_of_speech.split(',')
            pos_top = parts[0]
            pos_detail = parts[1] if len(parts) > 1 else '*'
            boundaries.append((pos, token.surface, pos_top, pos_detail))
    return boundaries


def _find_best_split(text: str, ideal_pos: int, boundaries: list[tuple[int, str, str, str]]) -> int:
    """
    単語境界リストから、idealPosに最も近い自然な分割位置を見つける。
    品詞情報を活用して日本語として自然な分割を選択する。
    """
    if not boundaries:
        return ideal_pos

    best_pos = ideal_pos
    best_score = float('inf')

    # 次のトークン情報を事前構築 (4-tuple)
    next_info = {}
    for idx in range(len(boundaries)):
        if idx + 1 < len(boundaries):
            next_info[idx] = boundaries[idx + 1]
        else:
            b = boundaries[idx][0]
            next_char = text[b] if b < len(text) else ''
            next_info[idx] = (len(text), next_char, '', '*')

    for i, (b, surface, pos_tag, pos_detail) in enumerate(boundaries):
        dist = abs(b - ideal_pos)
        if dist > 15:
            continue

        score = dist

        # === ボーナス（自然な分割位置） ===

        # 句読点・感嘆符の後
        if surface in ('。', '！', '？', '、', '…'):
            score = max(0, score - 6)

        # て/で形の後（助詞の「て」「で」）
        elif surface in ('て', 'で') and pos_tag == '助詞':
            score = max(0, score - 4)

        # 終助詞（さ、よ、ね等）の後は良い分割位置
        elif pos_tag == '助詞' and pos_detail == '終助詞':
            score = max(0, score - 3)

        # 接続助詞（から、けど、ので等）の後
        elif pos_tag == '助詞' and pos_detail == '接続助詞':
            score = max(0, score - 3)

        # 格助詞・係助詞（は/が/を/に/へ/も）の後
        elif surface in ('は', 'が', 'を', 'に', 'へ', 'も') and pos_tag == '助詞':
            score = max(0, score - 2)

        # 動詞・形容詞の終止形の後
        elif pos_tag in ('動詞', '形容詞') and surface.endswith(('る', 'た', 'だ', 'い')):
            score = max(0, score - 1)

        # 接続助詞（から、けど、ので等）の後は自然な区切り
        # ただし次が「の」「は」等の場合はさらにボーナス
        if pos_tag == '助詞' and pos_detail == '接続助詞' and surface in ('から', 'けど', 'ので', 'のに'):
            score = max(0, score - 4)

        # カタカナ語（外来語）の後
        elif pos_tag == '名詞' and len(surface) >= 2 and all('\u30A0' <= c <= '\u30FF' or c == 'ー' for c in surface):
            score = max(0, score - 1)

        # === ペナルティ（不自然な分割位置） ===

        next_b, next_surface, next_pos_tag, next_detail = next_info[i]

        # 終助詞の直前で切らない
        if next_pos_tag == '助詞' and next_detail == '終助詞':
            score += 10

        # 助動詞の直前で切らない（「ない」「です」「ます」等）
        if next_pos_tag == '助動詞':
            score += 6

        # 連体詞（この、その、あの）の後：次の名詞と分離しない
        if pos_tag == '連体詞':
            score += 10

        # 非自立名詞の直前で切らない（「のこと」「のもの」等）
        if next_pos_tag == '名詞' and next_detail == '非自立':
            score += 4

        # 接続助詞（から、けど等）の直前で切らない（「君だ / から」防止）
        if next_pos_tag == '助詞' and next_detail == '接続助詞':
            score += 8

        # 非自立の形容詞・動詞の直前で切らない（「許して / よ」防止）
        if next_detail == '非自立' and next_pos_tag in ('形容詞', '動詞'):
            score += 10

        # フィラーの直前では切らない
        if next_pos_tag == 'フィラー':
            score += 6

        if score < best_score:
            best_score = score
            best_pos = b

    return best_pos


def process_phrases_for_display(phrases: list[dict], target_chars: int = 30) -> list[dict]:
    """
    lyrics_phrasesを処理してテキストビュー表示用フレーズに変換する。
    
    1. gap < 1sの連続フレーズを結合（ブロック化）
    2. 長いブロックをJanome形態素解析の単語境界で自然に再分割
    
    Args:
        phrases: [{"start": float, "end": float, "text": str}, ...]
        target_chars: 目標文字数
    
    Returns:
        [{"start": float, "end": float, "text": str}, ...]
    """
    if not phrases:
        return []

    # Pass 1: gap < 1s のフレーズを結合
    blocks = []
    cur = {
        "start": phrases[0]["start"],
        "end": phrases[0]["end"],
        "text": _clean(phrases[0].get("text", "")),
    }

    for p in phrases[1:]:
        p_text = _clean(p.get("text", ""))
        gap = p["start"] - cur["end"]

        if gap < 1.0:
            cur["end"] = p["end"]
            cur["text"] += p_text
        else:
            if cur["text"]:
                blocks.append(cur)
            cur = {"start": p["start"], "end": p["end"], "text": p_text}

    if cur["text"]:
        blocks.append(cur)

    # Pass 2: 長いブロックを単語境界で再分割
    result = []
    max_chars = target_chars + 5

    for block in blocks:
        text = block["text"]

        if len(text) <= max_chars:
            result.append(block)
            continue

        # Janomeで単語境界を取得
        boundaries = _get_word_boundaries(text)
        total_duration = block["end"] - block["start"]
        pos = 0

        while pos < len(text):
            remaining = len(text) - pos

            if remaining <= max_chars:
                ratio = pos / len(text)
                result.append({
                    "start": round(block["start"] + total_duration * ratio, 3),
                    "end": block["end"],
                    "text": text[pos:],
                })
                break

            # 現在位置からの相対境界に変換
            ideal = pos + target_chars
            split_pos = _find_best_split(text, ideal, boundaries)

            # 安全チェック: 進行しない場合は強制分割
            if split_pos <= pos:
                split_pos = pos + target_chars

            chunk = text[pos:split_pos]
            ratio1 = pos / len(text)
            ratio2 = split_pos / len(text)

            result.append({
                "start": round(block["start"] + total_duration * ratio1, 3),
                "end": round(block["start"] + total_duration * ratio2, 3),
                "text": chunk,
            })
            pos = split_pos

    return result


# --- テスト用 ---
if __name__ == "__main__":
    test_phrases = [
        {"start": 11.9, "end": 21.0, "text": "このままでいいのさベイビー俺はどうしようもなく俺なのさ"},
        {"start": 21.4, "end": 30.9, "text": "他の誰にもなれやしないから"},
        {"start": 38.5, "end": 48.4, "text": "また間違えたまたしくじった果てにやらかした"},
        {"start": 49.4, "end": 59.1, "text": "あきれがおの君を残し部屋を飛び出した"},
        {"start": 59.1, "end": 70.8, "text": "ふてくされて宛なく歩いて夜空を見上げれば"},
        {"start": 70.8, "end": 80.8, "text": "流れ星は君の涙拾いに行かなけりゃ"},
        {"start": 82.7, "end": 92.2, "text": "まだ間に合うか空が知らぬ前に"},
        {"start": 93.7, "end": 102.4, "text": "もう手遅れか街が動き出す"},
        {"start": 102.4, "end": 112.1, "text": "このままでいいのかベイビーもう一度チャンスをくれないか"},
        {"start": 112.1, "end": 122.1, "text": "明日からの俺を見ていておくれ"},
        {"start": 129.2, "end": 139.1, "text": "生まれ変わるつもり心を入れ替えるつもりが"},
        {"start": 140.1, "end": 149.7, "text": "間に合わせの化けの香茶君にはお見通し"},
        {"start": 152.2, "end": 160.7, "text": "もうお手上げだ俺はお笑のまま"},
        {"start": 160.7, "end": 170.8, "text": "わがまま許してよベイビー遠回りしてたどり着くから"},
        {"start": 170.8, "end": 178.7, "text": "君への愛だけおままりにして"},
        {"start": 197.5, "end": 208.8, "text": "君のその手のひらで君のその歌でずっと踊らせて"},
        {"start": 208.8, "end": 218.8, "text": "このままがいいのさベイビー君はどうしようもなく君だから"},
        {"start": 218.8, "end": 230.2, "text": "他の誰かじゃダメなのさこのままいつまでもベイビー"},
        {"start": 230.2, "end": 243.0, "text": "喧嘩してはまた抱き合ってやがて来る朝に笑えるように"},
        {"start": 243.0, "end": 253.8, "text": "二人でいつまでもこのままでいいのさ"},
        {"start": 277.8, "end": 279.2, "text": "作詞・作曲・編曲・編曲"},
    ]

    print("=== Janome形態素解析による分割テスト ===\n")

    # まず単語境界を確認
    test_text = "このままでいいのさベイビー俺はどうしようもなく俺なのさ他の誰にもなれやしないから"
    tokens = list(_tokenizer.tokenize(test_text))
    print(f"テスト文: {test_text}")
    print(f"形態素: {' | '.join(t.surface for t in tokens)}\n")

    result = process_phrases_for_display(test_phrases, target_chars=25)

    for i, r in enumerate(result):
        mark = " ★" if "やがて" in r["text"] else ""
        print(f"[{i:2d}] {r['text']}{mark}")

    print(f"\nやがて OK: {'やがて' in ' '.join(r['text'] for r in result)}")

    # 問題チェック
    print("\n=== 品質チェック ===")
    for i, r in enumerate(result):
        t = r["text"]
        if t.startswith("さ") and len(t) > 1 and i > 0:
            print(f"  ⚠ Line[{i}] 「さ」始まり: {t}")
        if t.endswith("この") or t.endswith("その"):
            print(f"  ⚠ Line[{i}] 連体詞で終わる: {t}")
    print("チェック完了")
