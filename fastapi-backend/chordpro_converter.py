"""
chordpro_converter.py -- structured_data → ChordPro形式テキスト変換

structured_data (beat_chords + lyrics) を ChordWiki互換の
ChordPro形式テキストに変換する。

ChordPro形式:
  {t:チェリー}
  {st:スピッツ}
  {c:イントロ}
  [C] [G] [Am] [Em]
  [F] [G] [C] [Am]
  
  {c:Aメロ}
  [C]君を忘れ[G]ない
  [Am]曲がりく[Em]ねった道を行く
"""

import re


def structured_to_chordpro(structured_data, lyrics_phrases=None,
                            display_phrases=None, title="", artist="",
                            key="", beats_per_bar=4, bar_positions=None):
    """
    structured_data と lyrics_phrases から ChordPro形式テキストを生成。

    フレーズ単位のアプローチ:
    1. コード変化のタイムラインを構築
    2. 歌詞フレーズごとにそのtime rangeに該当するコード変化を取得
    3. word-level timestampsでコード位置を歌詞内に挿入
    4. 歌詞がない区間はコードのみ行として出力
    """
    lines = []
    line_timings = []  # 各行の開始時刻（コード行のみ）

    # --- ヘッダー ---
    if title:
        lines.append(f"{{t:{title}}}")
    if artist:
        lines.append(f"{{st:{artist}}}")
    if key:
        lines.append(f"{{key:{key}}}")
    lines.append("")

    # --- コード変化のタイムラインを構築 ---
    chord_changes = []  # [(time, chord, section), ...]
    prev_chord = None
    for entry in structured_data:
        chord = entry.get("chord", "N.C.")
        t = entry.get("time", 0)
        section = entry.get("section", "")
        if chord != "N.C." and chord != prev_chord:
            chord_changes.append((t, chord, section))
            prev_chord = chord
        elif chord == "N.C." and prev_chord is not None:
            prev_chord = None

    if not chord_changes:
        return "\n".join(lines)

    # --- セクション情報の構築 ---
    sections = []  # [(start_time, section_name), ...]
    prev_section = ""
    for entry in structured_data:
        section = entry.get("section", "")
        if section and section != prev_section:
            sections.append((entry["time"], section))
            prev_section = section

    # --- 歌詞フレーズの準備 ---
    # lyrics_phrases (sentence-level) を優先使用 → 行が短く読みやすい
    phrases = lyrics_phrases or display_phrases or []

    # word-level timestamps をフラットリストに
    all_words = []  # [(start_time, word_text), ...]
    if lyrics_phrases:
        for phrase in lyrics_phrases:
            if phrase.get("words"):
                for w in phrase["words"]:
                    all_words.append((w["start"], w.get("word", "")))

    # --- フレーズごとの歌詞時間区間の構築 ---
    phrase_regions = []  # [(start, end, text, words), ...]
    for p in phrases:
        text = p.get("text", "").strip()
        if not text:
            continue
        # 誤認識のノイズをフィルタ（短すぎる / 非歌詞テキスト）
        clean = text.replace("・", "").replace("…", "").replace(" ", "").strip()
        if len(clean) < 3:
            continue
        # Whisperが楽器音を誤認識する典型パターン
        noise_words = {"編曲", "歌唱", "演奏", "作曲", "作詞", "提供"}
        if clean in noise_words:
            continue
        p_start = p.get("start", 0)
        p_end = p.get("end", p_start + 1)
        # このフレーズに属するワードを取得
        p_words = []
        if p.get("words"):
            p_words = p["words"]
        elif all_words:
            p_words = [{"start": t, "word": w} for t, w in all_words
                       if p_start - 0.3 <= t <= p_end + 0.3]
        phrase_regions.append((p_start, p_end, text, p_words))

    # --- 時系列でイベントを統合して出力 ---
    current_section = ""
    phrase_idx = 0
    chord_idx = 0

    # 全コード変化の時刻をカバーするために、フレーズがない区間も処理
    # タイムライン: (time, type, data)
    events = []

    # セクション変更イベント
    for s_time, s_name in sections:
        events.append((s_time, "section", s_name))

    # フレーズイベント
    for p_start, p_end, text, words in phrase_regions:
        events.append((p_start, "phrase", (p_start, p_end, text, words)))

    # コードのみ区間イベント (フレーズがない区間)
    # フレーズ間のギャップを見つける
    covered_times = set()
    for p_start, p_end, _, _ in phrase_regions:
        for ct, cc, _ in chord_changes:
            if p_start - 0.5 <= ct <= p_end + 0.5:
                covered_times.add(ct)

    # カバーされていないコード変化をグループ化
    uncovered_chords = [(ct, cc) for ct, cc, _ in chord_changes if ct not in covered_times]
    if uncovered_chords:
        # 連続するコードをグループ化
        groups = []
        current_group = [uncovered_chords[0]]
        for i in range(1, len(uncovered_chords)):
            ct, cc = uncovered_chords[i]
            prev_ct, _ = uncovered_chords[i - 1]
            if ct - prev_ct < 5.0:  # 5秒以内は同グループ
                current_group.append((ct, cc))
            else:
                groups.append(current_group)
                current_group = [(ct, cc)]
        groups.append(current_group)

        for group in groups:
            events.append((group[0][0], "chords_only", group))

    # 時系列でソート
    events.sort(key=lambda x: x[0])

    # --- イベントを処理して行を生成 ---
    for evt_time, evt_type, evt_data in events:
        if evt_type == "section":
            section_name = evt_data
            if section_name != current_section:
                section_ja = _section_to_japanese(section_name)
                lines.append("")
                lines.append(f"{{c:{section_ja}}}")
                current_section = section_name

        elif evt_type == "chords_only":
            chord_group = evt_data
            # 4コードごとに1行に分割（1サイクル=2小節単位）
            # 参照アプリと同じレイアウト: C G Am F / C G Am F / ...
            CHORDS_PER_LINE = 4
            chord_lines_data = []  # [(line_text, start_time), ...]
            for i in range(0, len(chord_group), CHORDS_PER_LINE):
                chunk = chord_group[i:i + CHORDS_PER_LINE]
                chord_strs = [f"[{cc}]" for _, cc in chunk]
                chord_lines_data.append((" ".join(chord_strs), chunk[0][0]))
            # 複数行なら空行で区切る（視覚的に小節感を出す）
            for cl_text, cl_time in chord_lines_data:
                lines.append(cl_text)
                line_timings.append(cl_time)
                if len(chord_lines_data) > 1:
                    lines.append("")

        elif evt_type == "phrase":
            p_start, p_end, text, words = evt_data
            # このフレーズの時間範囲にあるコード変化を取得
            phrase_chords = [(ct, cc) for ct, cc, _ in chord_changes
                            if p_start - 0.5 <= ct <= p_end + 0.5]

            if not phrase_chords:
                lines.append(text)
                line_timings.append(p_start)
                continue

            # 【4小節ルール】フレーズの小節数を計算
            # 4小節+α以内のフレーズは分割しない
            BARS_PER_LINE = 4
            if bar_positions and len(bar_positions) >= 2:
                _avg_bar = (bar_positions[-1] - bar_positions[0]) / (len(bar_positions) - 1)
            else:
                _avg_bar = 60.0 / 120 * beats_per_bar  # fallback
            phrase_bars = (p_end - p_start) / _avg_bar if _avg_bar > 0 else 0

            # 5.5小節以内 → 分割しない（4小節 + 1.5小節マージン）
            if phrase_bars <= BARS_PER_LINE + 1.5:
                line = _insert_chords_into_lyrics(text, phrase_chords, words, p_start, p_end)
                lines.append(line)
                line_timings.append(phrase_chords[0][0])
                continue

            # 5.5小節超: 4小節 (= 時間ベース) で分割
            max_chords_for_split = max(4, int(phrase_bars / BARS_PER_LINE) * 4)
            sub_lines = _split_phrase_lines(
                text, phrase_chords, words, p_start, p_end, max_chords_for_split)
            # 各分割行のタイミングを記録
            sub_chord_idx = 0
            for sl in sub_lines:
                if sub_chord_idx < len(phrase_chords):
                    line_timings.append(phrase_chords[sub_chord_idx][0])
                else:
                    line_timings.append(p_start)
                # この行のコード数を数えて次の開始位置へ
                import re as _re
                chord_count = len(_re.findall(r'\[([A-G][^\]]*?)\]', sl))
                sub_chord_idx += chord_count
            lines.extend(sub_lines)
            continue


            # 分割不要: ビート比率ベースでコード位置を決定
            line = _insert_chords_into_lyrics(text, phrase_chords, words, p_start, p_end)
            lines.append(line)


    return "\n".join(lines), line_timings


def _split_phrase_lines(text, phrase_chords, words, p_start, p_end, max_chords=4):
    """
    長い歌詞フレーズをコード境界で再帰的に分割して行リストを返す。

    【拍の理論】
    コード変化のタイミングをビート比率で文字位置に変換し、
    そこでテキストを分割する。max_chords ごとに1行になるまで再帰する。

    例: 3コードフレーズ (max_chords=2) を分割:
      [C]君を忘れない 曲がりくねった[G]道を行く  → 行1
      [Am]生まれたての太陽と 夢を渡る黄色い砂    → 行2
    """
    if len(phrase_chords) <= max_chords or not text.strip():
        line = _insert_chords_into_lyrics(text, phrase_chords, words, p_start, p_end)
        return [line]

    # max_chords 番目のコードの時刻で分割
    split_chord_idx = max_chords
    split_time = phrase_chords[split_chord_idx][0]
    split_pos = _find_split_position_by_time(text, words, split_time, p_start, p_end)

    if not (0 < split_pos < len(text)):
        # 分割できない → そのまま1行で返す
        line = _insert_chords_into_lyrics(text, phrase_chords, words, p_start, p_end)
        return [line]

    text1 = text[:split_pos].rstrip()
    text2 = text[split_pos:].lstrip()
    chords1 = [(ct, cc) for ct, cc in phrase_chords if ct < split_time]
    chords2 = [(ct, cc) for ct, cc in phrase_chords if ct >= split_time]

    result = []
    if text1 and chords1:
        # text1 はmax_chords以内なので直接挿入
        result.append(_insert_chords_into_lyrics(text1, chords1, words, p_start, split_time))
    if text2 and chords2:
        # text2 はまだ多い可能性があるので再帰
        result.extend(_split_phrase_lines(text2, chords2, words, split_time, p_end, max_chords))
    return result if result else [
        _insert_chords_into_lyrics(text, phrase_chords, words, p_start, p_end)
    ]


def _detect_chord_rate(structured_data):

    """
    音源から「1小節に何コードか」を自動検出する。

    【拍の理論】
    BTCのビートレベルRLEからコード継続ビート数の中央値を計算し、
    1小節1コード(4拍) / 2コード(2拍) / 4コード(1拍) のいずれかを返す。

    チェリー例: 中央値=2拍 → '2/bar' (2コード/小節)

    Returns:
        quant_beats (int): コード変化の量子化単位（1 / 2 / 4 拍）
        pattern (str): '1/bar' / '2/bar' / '4/bar'
    """
    import statistics
    durations = []
    prev = None
    count = 0
    for entry in structured_data:
        c = entry.get("chord", "N.C.")
        if c == "N.C.":
            if prev is not None and count > 0:
                durations.append(count)
            prev = None
            count = 0
            continue
        if c == prev:
            count += 1
        else:
            if prev is not None and count > 0:
                durations.append(count)
            prev = c
            count = 1
    if prev is not None and count > 0:
        durations.append(count)

    if not durations:
        return 2, '2/bar'

    med = statistics.median(durations)
    if med < 1.5:
        return 1, '4/bar'   # 1拍ごとにコード変化（4コード/小節）
    elif med < 3.0:
        return 2, '2/bar'   # 2拍ごと（2コード/小節）
    else:
        return 4, '1/bar'   # 4拍ごと（1コード/小節）


def _insert_chords_into_lyrics(text, chord_changes, words,
                               phrase_start=0.0, phrase_end=None):

    """
    歌詞テキストにコードを挿入する（ビート比率ベース）。

    【設計思想: 拍の理論】
    コード変化はビートグリッド上の正確な時刻で起こる。
    その時刻がフレーズ全体に占める時間比率を文字数に変換し、
    対応する文字位置にコードマーカーを挿入する。

    例: フレーズ 22.1s〜26.2s、テキスト16文字
      G @23.3s → (23.3-22.1)/(26.2-22.1) = 29% → 文字位置5 = "曲"
      Am@24.5s → (24.5-22.1)/(26.2-22.1) = 59% → 文字位置9 = "りく"

    Whisper の word timestamps はWord境界スナップのみに使用する。
    """
    if not chord_changes:
        return text

    text_len = len(text)
    if text_len == 0:
        return text

    if len(chord_changes) == 1:
        return f"[{chord_changes[0][1]}]{text}"

    # フレーズの時間幅
    if phrase_end is None or phrase_end <= phrase_start:
        # フォールバック: コードのタイム範囲から推定
        times = [ct for ct, _ in chord_changes]
        phrase_start = times[0]
        phrase_end = times[-1] + 2.0
    phrase_duration = max(phrase_end - phrase_start, 0.01)

    # ステップ1: ビート比率で文字位置を計算
    raw_positions = {}  # chord_idx -> char_pos
    for i, (ct, cc) in enumerate(chord_changes):
        ratio = (ct - phrase_start) / phrase_duration
        ratio = max(0.0, min(1.0, ratio))
        char_pos = int(ratio * text_len)
        raw_positions[i] = char_pos

    # ステップ2: Whisper word timestamps で最近傍の単語境界にスナップ（±2文字以内）
    word_boundaries = []  # [(char_pos, word_time), ...]
    if words:
        char_off = 0
        for w in _group_single_char_words(words):
            wt = w.get("word", "")
            ws = w.get("start", 0)
            idx = text.find(wt, char_off)
            if idx >= 0:
                word_boundaries.append((idx, ws))
                char_off = idx + len(wt)
            else:
                word_boundaries.append((char_off, ws))
                char_off += max(1, len(wt))

    SNAP_WINDOW = 2  # 単語境界スナップの最大文字数
    MIN_SPACING = 2  # コード間の最小文字数

    chord_insertions = {}  # char_pos -> chord
    for i, (ct, cc) in enumerate(chord_changes):
        target = raw_positions[i]

        # 単語境界スナップ（任意）
        best = target
        if word_boundaries:
            # target に最も近い単語境界を探す
            nearest = min(word_boundaries, key=lambda x: abs(x[0] - target))
            if abs(nearest[0] - target) <= SNAP_WINDOW:
                best = nearest[0]

        # 最小間隔を守る: 既存の挿入位置と近すぎたら少しずらす
        while best in chord_insertions or any(
                abs(best - p) < MIN_SPACING for p in chord_insertions):
            best += 1
            if best >= text_len:
                break

        chord_insertions[best] = cc

    # テキストにコードを挿入
    result = ""
    for i, ch in enumerate(text):
        if i in chord_insertions:
            result += f"[{chord_insertions[i]}]"
        result += ch

    # 末尾の未挿入コード
    if text_len in chord_insertions:
        result += f"[{chord_insertions[text_len]}]"

    # 先頭コードが欠落していたら補完
    if 0 not in chord_insertions and chord_changes:
        result = f"[{chord_changes[0][1]}]" + result

    return result


def _group_single_char_words(words, min_gap=0.4):
    """
    時間的に近接したwordをグループ化する。
    min_gap秒以上離れた場合に新しいグループを開始する。
    これによりWhisperの1文字分割を音楽的な単語単位に纏める。
    """
    if not words:
        return words
    grouped = []
    buf_text = ""
    buf_start = None
    prev_end = None
    for w in words:
        wt = w.get("word", "").strip()
        ws = w.get("start", 0)
        we = w.get("end", ws + 0.3)
        if buf_text == "":
            buf_text = wt
            buf_start = ws
            prev_end = we
        elif (ws - prev_end) < min_gap:
            # 時間的に近い → 同じグループに追加
            buf_text += wt
            prev_end = we
        else:
            # 時間ギャップ → グループ確定
            grouped.append({"word": buf_text, "start": buf_start})
            buf_text = wt
            buf_start = ws
            prev_end = we
    if buf_text:
        grouped.append({"word": buf_text, "start": buf_start})
    return grouped


def _find_split_position_by_time(text, words, split_time, phrase_start, phrase_end):
    """
    ビート時刻比率または単語のタイミング情報を使ってテキスト分割位置を決定する。
    """
    # 1. wordsデータがある場合はそれを使って正確な位置を特定する
    if words:
        char_idx = 0
        text_no_space = text.replace(" ", "")
        
        # wordsのテキストとtextが一致しない場合（部分文字列など）に備える
        # text内のどこにいるかを追跡
        match_idx = 0
        for w in words:
            w_text = w.get("word", "").strip()
            w_start = w.get("start", phrase_start)
            
            # この単語の開始時刻がsplit_timeに達したら、ここで分割
            if w_start >= split_time - 0.2:
                # 現在のchar_idxがテキストの範囲内ならそこで分割
                # ただし、短すぎる残骸（1〜2文字）を残さないように調整
                if 2 <= char_idx <= len(text) - 2:
                    return char_idx
                    
            char_idx += len(w_text)
            
    # 2. wordsがない、または見つからなかった場合は線形補間（フォールバック）
    phrase_duration = max(phrase_end - phrase_start, 0.01)
    ratio = (split_time - phrase_start) / phrase_duration
    ratio = max(0.0, min(1.0, ratio))
    target_char = int(ratio * len(text))

    # target_char前後の空白を探す
    for offset in range(len(text) // 2):
        pos_before = target_char - offset
        pos_after = target_char + offset
        if 0 < pos_before < len(text) and text[pos_before] == " ":
            return pos_before + 1
        if 0 <= pos_after < len(text) and text[pos_after] == " ":
            return pos_after + 1
            
    # 1文字だけ孤立するのを防ぐ
    if target_char == len(text) - 1:
        target_char = len(text) - 2
    elif target_char == 1 and len(text) > 2:
        target_char = 2
        
    return max(0, min(target_char, len(text)))


def _section_to_japanese(section_label):
    """セクションラベルを日本語に変換"""
    mapping = {
        "intro": "イントロ",
        "verse": "Aメロ",
        "verse1": "Aメロ",
        "verse2": "Bメロ",
        "chorus": "サビ",
        "bridge": "ブリッジ",
        "outro": "アウトロ",
        "interlude": "間奏",
        "instrumental": "間奏",
        "solo": "ソロ",
        "pre-chorus": "Bメロ",
        "post-chorus": "サビ後",
    }
    lower = section_label.lower().strip()
    return mapping.get(lower, section_label)
