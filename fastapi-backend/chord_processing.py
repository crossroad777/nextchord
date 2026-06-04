"""
NextChord - コード処理モジュール
================================
コード表記の正規化、キー推定、セクション解析などの音楽理論関連ロジック。

main.py から分離して保守性を向上。
"""

import numpy as np
import librosa
from collections import Counter


# =========================================================================
# セクション解析
# =========================================================================

def analyze_sections(y, sr):
    """
    楽曲の構造（イントロ、サビ等）を解析する
    現在は固定8等分ラベリング（将来的にAIベースの構造解析に置き換え予定）
    """
    try:
        dur = librosa.get_duration(y=y, sr=sr)
        chunk = dur / 8
        labels = ["Intro", "Verse A", "Chorus", "Verse B", "Chorus", "Bridge", "Chorus", "Outro"]
        return [(i * chunk, (i+1) * chunk, labels[i]) for i in range(8)]
    except Exception as e:
        print(f"Section analysis error: {e}")
        return []


# =========================================================================
# キー関連
# =========================================================================

def standardized_key(key_idx: int) -> str:
    keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    # CNNKeyRecognitionProcessor outputs 24 indices (0-11 Major, 12-23 Minor)
    if key_idx < 12:
        return f"{keys[key_idx]} Major"
    else:
        return f"{keys[key_idx-12]} Minor"


# =========================================================================
# コード標準化
# =========================================================================

def standardize_chord(chord_label: str) -> str:
    """
    コードラベルを一般的な表記に変換する。
    BTC large_voca (170クラス) の全14品質に対応。
    """
    if not chord_label or chord_label == "N" or chord_label == "X":
        return "N.C."
    
    # コロンなし = ルートのみ（BTC は "C" = C:maj として出力する場合あり）
    if ":" not in chord_label:
        return chord_label
    
    try:
        root, quality = chord_label.split(":", 1)
        # スラッシュコード対応 (例: "C:min/5" -> "Cm/G")
        slash = ""
        if "/" in quality:
            quality, bass = quality.split("/", 1)
            slash = f"/{bass}"
        
        quality_map = {
            "maj": "",
            "min": "m",
            "dim": "dim",
            "aug": "aug",
            "min6": "m6",
            "maj6": "6",
            "min7": "m7",
            "minmaj7": "mMaj7",
            "maj7": "Maj7",
            "7": "7",
            "dim7": "dim7",
            "hdim7": "m7(b5)",
            "sus2": "sus2",
            "sus4": "sus4",
        }
        
        suffix = quality_map.get(quality, quality)
        return f"{root}{suffix}{slash}"
    except ValueError:
        return chord_label


# =========================================================================
# コードセグメント平滑化
# =========================================================================

def _smooth_chord_segments(seg_starts, seg_labels, min_duration=0.5):
    """
    コードセグメントを平滑化する。
    - min_duration秒未満の短いセグメントを前のセグメントにマージ
    - ノイズの多いDeepChromaの出力を安定化
    """
    if seg_starts is None or seg_labels is None or len(seg_starts) == 0:
        return seg_starts, seg_labels
    
    starts = list(seg_starts)
    labels = list(seg_labels)
    
    merged_starts = [starts[0]]
    merged_labels = [labels[0]]
    
    for i in range(1, len(starts)):
        # 前のセグメントの長さを計算
        prev_duration = starts[i] - merged_starts[-1]
        
        if prev_duration < min_duration and len(merged_starts) > 1:
            # 短すぎるセグメントはスキップ（前のコードを維持）
            continue
        
        # 同じコードが連続する場合もマージ
        if labels[i] == merged_labels[-1]:
            continue
        
        merged_starts.append(starts[i])
        merged_labels.append(labels[i])
    
    n_before = len(starts)
    n_after = len(merged_starts)
    print(f"[ChordSmooth] Segments: {n_before} -> {n_after} (merged {n_before - n_after})")
    
    return np.array(merged_starts), np.array(merged_labels)


# =========================================================================
# ビート多数決コード判定
# =========================================================================

def _beat_majority_chords(v_time, seg_starts, seg_labels):
    """
    各ビート区間内のコードを多数決で決定する。
    短いノイズチャタリングを吸収し、各ビートに1つの安定したコードを割り当てる。
    
    Returns
    -------
    list of str : 各ビートに対応するクリーンなコード名
    """
    if seg_starts is None or seg_labels is None or len(v_time) == 0:
        return ["N.C."] * len(v_time)
    
    beat_chords = []
    
    for i, b_time in enumerate(v_time):
        # このビートの時間範囲
        next_b_time = v_time[i + 1] if i < len(v_time) - 1 else b_time + 0.5
        
        # この区間内のコードセグメントを収集
        chord_durations = Counter()
        
        for j in range(len(seg_starts)):
            seg_start = seg_starts[j]
            seg_end = seg_starts[j + 1] if j + 1 < len(seg_starts) else next_b_time + 1.0
            
            # オーバーラップ計算
            overlap_start = max(b_time, seg_start)
            overlap_end = min(next_b_time, seg_end)
            overlap = overlap_end - overlap_start
            
            if overlap > 0:
                label = seg_labels[j]
                chord_name = standardize_chord(label)
                if chord_name != "N.C.":
                    chord_durations[chord_name] += overlap
        
        if chord_durations:
            # 最も長い時間を占めるコードを選択
            best_chord = chord_durations.most_common(1)[0][0]
            beat_chords.append(best_chord)
        else:
            beat_chords.append("N.C.")
    
    return beat_chords


def _smooth_beat_chords(beat_chords, beats_per_bar=4, min_beats=3):
    """
    ビート列のコード配列をスムージングする。
    
    min_beats拍未満しか続かないコード変化を前後の文脈に基づいて吸収する。
    例: [C, C, G, C, C, C, G, G] → [C, C, C, C, C, C, G, G]
         (1拍だけのGは前後のCに吸収)
    
    ただし、前後のコードが異なる場合は「橋渡し」として残す:
    例: [C, C, G, G, Am, Am, ...] → そのまま（Gは十分長く、遷移は正当）
    
    Parameters
    ----------
    beat_chords : list of str
    beats_per_bar : int
    min_beats : int  最小拍数（これ未満のコードは吸収候補）
    """
    if len(beat_chords) <= 2:
        return beat_chords
    
    result = list(beat_chords)
    changed = True
    passes = 0
    
    while changed and passes < 3:
        changed = False
        passes += 1
        
        # コードの連続区間(run)を検出
        runs = []  # [(start_idx, length, chord), ...]
        i = 0
        while i < len(result):
            chord = result[i]
            j = i
            while j < len(result) and result[j] == chord:
                j += 1
            runs.append((i, j - i, chord))
            i = j
        
        # 短いrun(min_beats未満)を吸収
        new_result = list(result)
        for ri, (start, length, chord) in enumerate(runs):
            if chord == "N.C.":
                continue
            if length >= min_beats:
                continue
            
            # 前後のrunを取得
            prev_chord = runs[ri - 1][2] if ri > 0 else None
            next_chord = runs[ri + 1][2] if ri < len(runs) - 1 else None
            prev_len = runs[ri - 1][1] if ri > 0 else 0
            next_len = runs[ri + 1][1] if ri < len(runs) - 1 else 0
            
            # 前後が同じコード → 明らかにノイズ → 前後のコードで埋める
            if prev_chord and prev_chord == next_chord and prev_chord != "N.C.":
                for k in range(start, start + length):
                    new_result[k] = prev_chord
                changed = True
                continue
            
            # 前後のうち長い方に吸収（1拍のみの場合）
            if length == 1:
                if prev_len >= min_beats and prev_chord and prev_chord != "N.C.":
                    new_result[start] = prev_chord
                    changed = True
                elif next_len >= min_beats and next_chord and next_chord != "N.C.":
                    new_result[start] = next_chord
                    changed = True
        
        result = new_result
    
    # 統計
    n_changes_before = sum(1 for i in range(1, len(beat_chords)) if beat_chords[i] != beat_chords[i-1])
    n_changes_after = sum(1 for i in range(1, len(result)) if result[i] != result[i-1])
    if n_changes_before != n_changes_after:
        print(f"[ChordSmooth2] Beat chord changes: {n_changes_before} -> {n_changes_after} "
              f"(absorbed {n_changes_before - n_changes_after} short transitions)")
    
    return result


# =========================================================================
# エンハーモニック表記マッピング
# =========================================================================

# ♯系キーで使うマッピング
_ENHARMONIC_MAP = {
    "Db": "C#", "Dbm": "C#m", "Db7": "C#7", "Dbmaj7": "C#maj7", "Dbm7": "C#m7",
    "Eb": "D#", "Ebm": "D#m", "Eb7": "D#7",
    "Gb": "F#", "Gbm": "F#m", "Gb7": "F#7",
    "Ab": "G#", "Abm": "G#m", "Ab7": "G#7",
    "Bb": "A#", "Bbm": "A#m", "Bb7": "A#7",
}

# ♭系キーでは♭表記を優先するマッピング
_ENHARMONIC_FLAT_MAP = {
    "C#": "Db", "C#m": "Dbm", "C#7": "Db7",
    "D#": "Eb", "D#m": "Ebm", "D#7": "Eb7",
    "F#": "Gb", "F#m": "Gbm", "F#7": "Gb7",
    "G#": "Ab", "G#m": "Abm", "G#7": "Ab7",
    "A#": "Bb", "A#m": "Bbm", "A#7": "Bb7",
}

# ♭系キー（これらのキーでは♭表記を使う）
_FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Db"}


# =========================================================================
# コード正規化（キーに合わせた表記統一 + チャタリング除去 + レアコード統合）
# =========================================================================

def _normalize_chords_to_key(beat_chords, key_name):
    """
    コード表記の正規化（軽量版）。
    
    行うこと:
    1. エンハーモニック表記の統一（♯ vs ♭ をキーに合わせて統一）
    2. チャタリング除去（1拍だけ出現するコードを前後で置換）
    3. レアコード統合（出現率2%未満で同ルート類似コードがあれば統合）
    
    行わないこと:
    - 非ダイアトニックコードの強制変換（♭VII, セカンダリードミナント等は保持）
    - madmomの検出結果を音楽理論で上書き（検出精度を信頼）
    """
    key_root = key_name.split()[0] if " " in key_name else key_name
    use_flats = key_root in _FLAT_KEYS
    enharmonic = _ENHARMONIC_FLAT_MAP if use_flats else _ENHARMONIC_MAP
    
    # Step 1: エンハーモニック表記統一
    normalized = []
    enharmonic_fixes = 0
    for chord in beat_chords:
        if chord == "N.C.":
            normalized.append(chord)
        elif chord in enharmonic:
            normalized.append(enharmonic[chord])
            enharmonic_fixes += 1
        else:
            normalized.append(chord)
    
    def _chord_root(ch):
        """コード名からルートを抽出"""
        if len(ch) > 1 and ch[1] in '#b':
            return ch[:2]
        return ch[:1] if ch else ch
    
    def _chord_quality(ch):
        """コード名から品質(major/minor等)を抽出"""
        root = _chord_root(ch)
        return ch[len(root):]
    
    # Step 2: チャタリング除去
    # 1拍だけ異なるコードは前のコードで置換（明らかなノイズ除去）
    smoothed = list(normalized)
    chatter_fixes = 0
    for i in range(1, len(smoothed) - 1):
        if (smoothed[i] != smoothed[i-1] and 
            smoothed[i] != smoothed[i+1] and 
            smoothed[i-1] == smoothed[i+1]):
            smoothed[i] = smoothed[i-1]
            chatter_fixes += 1
    
    # Step 2.5: ダイアトニックバイアス補正
    # キーのダイアトニックコードに対し、非ダイアトニックで出現数が極めて少ないコードを補正
    # 例: G major で Cm(2回) → C に補正（Cはダイアトニック）
    _DIATONIC = {
        'C':  {'C', 'Dm', 'Em', 'F', 'G', 'Am', 'Bdim'},
        'C#': {'C#', 'D#m', 'E#m', 'F#', 'G#', 'A#m', 'B#dim'},
        'D':  {'D', 'Em', 'F#m', 'G', 'A', 'Bm', 'C#dim'},
        'Eb': {'Eb', 'Fm', 'Gm', 'Ab', 'Bb', 'Cm', 'Ddim'},
        'E':  {'E', 'F#m', 'G#m', 'A', 'B', 'C#m', 'D#dim'},
        'F':  {'F', 'Gm', 'Am', 'Bb', 'C', 'Dm', 'Edim'},
        'F#': {'F#', 'G#m', 'A#m', 'B', 'C#', 'D#m', 'E#dim'},
        'G':  {'G', 'Am', 'Bm', 'C', 'D', 'Em', 'F#dim'},
        'Ab': {'Ab', 'Bbm', 'Cm', 'Db', 'Eb', 'Fm', 'Gdim'},
        'A':  {'A', 'Bm', 'C#m', 'D', 'E', 'F#m', 'G#dim'},
        'Bb': {'Bb', 'Cm', 'Dm', 'Eb', 'F', 'Gm', 'Adim'},
        'B':  {'B', 'C#m', 'D#m', 'E', 'F#', 'G#m', 'A#dim'},
    }
    
    # マイナーキーのダイアトニック（自然短音階 + 和声短音階のV）
    _DIATONIC_MINOR = {
        'Am': {'Am', 'Bdim', 'C', 'Dm', 'Em', 'E', 'F', 'G'},
        'Bm': {'Bm', 'C#dim', 'D', 'Em', 'F#m', 'F#', 'G', 'A'},
        'Cm': {'Cm', 'Ddim', 'Eb', 'Fm', 'Gm', 'G', 'Ab', 'Bb'},
        'Dm': {'Dm', 'Edim', 'F', 'Gm', 'Am', 'A', 'Bb', 'C'},
        'Em': {'Em', 'F#dim', 'G', 'Am', 'Bm', 'B', 'C', 'D'},
        'F#m': {'F#m', 'G#dim', 'A', 'Bm', 'C#m', 'C#', 'D', 'E'},
        'G#m': {'G#m', 'A#dim', 'B', 'C#m', 'D#m', 'D#', 'E', 'F#'},
    }
    
    key_mode = key_name.split()[-1].lower() if len(key_name.split()) > 1 else 'major'
    diatonic_set = set()
    if key_mode == 'minor':
        minor_key = key_root + 'm'
        diatonic_set = _DIATONIC_MINOR.get(minor_key, set())
    if not diatonic_set:
        diatonic_set = _DIATONIC.get(key_root, set())
    
    # 非ダイアトニックコードの補正マップ（同ルートのダイアトニックコードに変換）
    diatonic_fixes = 0
    diatonic_fix_map = {}
    if diatonic_set:
        chord_counts_pre = Counter(c for c in smoothed if c != 'N.C.')
        for chord, count in chord_counts_pre.items():
            if chord in diatonic_set or count > 3:  # 4回以上出現 = 意図的な非ダイアトニック
                continue
            root = _chord_root(chord)
            quality = _chord_quality(chord)
            # 同ルートでダイアトニックなコードを探す
            for dc in diatonic_set:
                if _chord_root(dc) == root and dc != chord:
                    diatonic_fix_map[chord] = dc
                    break
        
        if diatonic_fix_map:
            for i in range(len(smoothed)):
                if smoothed[i] in diatonic_fix_map:
                    smoothed[i] = diatonic_fix_map[smoothed[i]]
                    diatonic_fixes += 1
            print(f"[ChordNormalize] Diatonic fixes: {diatonic_fix_map}")
    
    # Step 3: レアコード統合（保守的）
    # 出現率1.5%未満のコードで、品質が近い類似コードがあれば統合
    # ★ メジャー↔マイナーの統合は禁止（コード精度を最優先）
    chord_counts = Counter(c for c in smoothed if c != "N.C.")
    total_chords = sum(chord_counts.values())
    rare_threshold = max(2, int(total_chords * 0.015))  # 1.5%に引き下げ
    

    
    def _is_minor(q):
        """マイナー系かどうか"""
        return q.startswith('m') and not q.startswith('maj')
    
    def _quality_compatible(q1, q2):
        """品質が統合可能かどうか（メジャー↔マイナーは禁止）"""
        minor1 = _is_minor(q1)
        minor2 = _is_minor(q2)
        # メジャー↔マイナーの変換は禁止
        if minor1 != minor2:
            return False
        # 7th → triad は許可 (Am7→Am, C7→C, Cmaj7→C)
        # sus → triad は許可 (Csus4→C)
        # dim/aug → triad は禁止（性格が大きく変わる）
        if 'dim' in q1 or 'dim' in q2 or 'aug' in q1 or 'aug' in q2:
            return False
        return True
    
    rare_merge_map = {}
    rare_fixes = 0
    for chord, count in chord_counts.items():
        if count >= rare_threshold:
            continue
        root = _chord_root(chord)
        quality = _chord_quality(chord)
        
        # 類似コードを検索（同じルートで互換品質）
        candidates = []
        for other, other_count in chord_counts.items():
            if other == chord:
                continue
            if _chord_root(other) == root and other_count > count:
                other_quality = _chord_quality(other)
                if _quality_compatible(quality, other_quality):
                    candidates.append((other, other_count))
        
        if candidates:
            best = max(candidates, key=lambda x: x[1])[0]
            rare_merge_map[chord] = best
    
    if rare_merge_map:
        for i in range(len(smoothed)):
            if smoothed[i] in rare_merge_map:
                smoothed[i] = rare_merge_map[smoothed[i]]
                rare_fixes += 1
    
    print(f"[ChordNormalize] enharmonic={enharmonic_fixes}, chatter_fixes={chatter_fixes}, rare_merge={rare_fixes}")
    if rare_merge_map:
        print(f"[ChordNormalize] Rare merges: {rare_merge_map}")
    return smoothed


# =========================================================================
# キー推定（改良版 Krumhansl-Schmuckler法）
# =========================================================================

def estimate_key_from_audio(wav_path: str) -> str:
    """
    音声ファイルからchromaベースでキーを推定する（改良版Krumhansl-Schmuckler法）。
    
    原曲原理主義: 音声の実際のピッチクラス分布のみを使用。
    
    改善点:
    1. HPSS で倍音成分のみ抽出（打楽器・アタック音を除去）
    2. チューニング推定・補正（YouTube音源のピッチずれ対応）
    3. 冒頭/終結部の重み付け（トニックが強い区間を重視）
    4. CQT + STFT 両方のchromaを統合
    
    Returns: "C major", "A minor" 等
    """
    # Krumhansl-Schmuckler 鍵プロファイル
    MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    
    KEYS = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    
    try:
        from waveform_utils import load_audio_cached
        y, sr = load_audio_cached(wav_path, sr=22050, mono=True)
        duration = len(y) / sr
        print(f"[ChromaKey] Audio loaded: {duration:.1f}s, sr={sr}")
        
        # === Step 1: HPSS で倍音成分のみ抽出 ===
        y_harmonic = librosa.effects.harmonic(y, margin=4.0)
        print(f"[ChromaKey] HPSS: harmonic component extracted")
        
        # === Step 2: チューニング推定・補正 ===
        tuning = librosa.estimate_tuning(y=y_harmonic, sr=sr)
        print(f"[ChromaKey] Estimated tuning: {tuning:+.2f} semitones")
        
        # === Step 3: CQT chroma（チューニング補正済み） ===
        chroma_cqt = librosa.feature.chroma_cqt(
            y=y_harmonic, sr=sr, hop_length=512,
            tuning=tuning, n_chroma=12
        )
        
        # === Step 4: STFT chroma（高音域に強い）===
        chroma_stft = librosa.feature.chroma_stft(
            y=y_harmonic, sr=sr, hop_length=512,
            tuning=tuning, n_chroma=12
        )
        
        # === Step 5: 冒頭/終結部の重み付け ===
        n_frames = chroma_cqt.shape[1]
        weights = np.ones(n_frames)
        
        # 冒頭15%と終結15%を2倍に重み付け（トニックが強い区間）
        edge_frames = max(1, int(n_frames * 0.15))
        weights[:edge_frames] *= 2.0
        weights[-edge_frames:] *= 2.0
        
        # 加重平均でピッチクラスプロファイルを計算
        profile_cqt = np.average(chroma_cqt, axis=1, weights=weights)
        profile_stft = np.average(chroma_stft, axis=1, weights=weights)
        
        # CQTとSTFTを50:50で統合
        pitch_profile = (profile_cqt + profile_stft) / 2.0
        
        # 正規化
        pitch_profile = pitch_profile / (pitch_profile.max() + 1e-10)
        
        # === Step 6: 全24キーの相関を計算 ===
        all_results = []
        
        for shift in range(12):
            shifted = np.roll(pitch_profile, -shift)
            
            corr_major = np.corrcoef(shifted, MAJOR_PROFILE)[0, 1]
            corr_minor = np.corrcoef(shifted, MINOR_PROFILE)[0, 1]
            
            all_results.append((KEYS[shift], "major", corr_major))
            all_results.append((KEYS[shift], "minor", corr_minor))
        
        # 相関値でソート（降順）
        all_results.sort(key=lambda x: x[2], reverse=True)
        
        # Top 5 をログ出力
        print(f"[ChromaKey] Top 5 candidates:")
        for rank, (k, m, c) in enumerate(all_results[:5]):
            print(f"  #{rank+1}: {k} {m} (r={c:.4f})")
        
        best_key, best_mode, best_corr = all_results[0]
        
        result = f"{best_key} {best_mode}"
        print(f"[ChromaKey] Estimated key: {result} (correlation={best_corr:.4f})")
        print(f"[ChromaKey] Pitch profile: {dict(zip(KEYS, [f'{v:.3f}' for v in pitch_profile]))}")
        print(f"[ChromaKey] Tuning offset: {tuning:+.2f} semitones")
        return result
        
    except Exception as e:
        import traceback
        print(f"[ChromaKey] Error: {type(e).__name__}: {e}")
        traceback.print_exc()
        return "C major"


# =========================================================================
# 楽曲タイプ自動判定（Demucsステムのエネルギー比較）
# =========================================================================

def detect_song_type(session_dir, wav_path) -> str:
    """
    Demucsの4ステム出力（vocals/drums/bass/other）のRMSエネルギー比率から
    楽曲タイプを推定する。

    Returns
    -------
    str : "solo_guitar" | "vocal_guitar" | "band"
        - solo_guitar: other(ギター) が支配的、vocals/drums が微弱
        - vocal_guitar: vocals + other が主体（弾き語り）
        - band: 全ステムが均等（バンド）
    """
    from pathlib import Path
    
    wav_p = Path(wav_path)
    session_dir = Path(session_dir)
    stems_dir = session_dir / "htdemucs" / wav_p.stem
    
    # Demucsステムが存在しない場合はデフォルト
    if not stems_dir.exists():
        htdemucs_dir = session_dir / "htdemucs"
        if htdemucs_dir.exists():
            candidates = [d for d in htdemucs_dir.iterdir() if d.is_dir()]
            if candidates:
                stems_dir = candidates[-1]
            else:
                print(f"[SongType] No Demucs stems found, defaulting to 'band'")
                return "band"
        else:
            print(f"[SongType] No htdemucs dir found, defaulting to 'band'")
            return "band"
    
    stem_rms = {}
    for stem_name in ["vocals", "drums", "bass", "other"]:
        stem_path = stems_dir / f"{stem_name}.wav"
        if stem_path.exists():
            try:
                y, sr = librosa.load(str(stem_path), sr=22050, duration=60)
                rms = float(np.sqrt(np.mean(y ** 2)))
                stem_rms[stem_name] = rms
            except Exception as e:
                print(f"[SongType] Failed to load {stem_name}: {e}")
                stem_rms[stem_name] = 0.0
        else:
            stem_rms[stem_name] = 0.0
    
    total_rms = sum(stem_rms.values()) + 1e-10
    ratios = {k: v / total_rms for k, v in stem_rms.items()}
    
    print(f"[SongType] RMS: {', '.join(f'{k}={v:.4f}' for k, v in stem_rms.items())}")
    print(f"[SongType] Ratios: {', '.join(f'{k}={v:.1%}' for k, v in ratios.items())}")
    
    # 判定ロジック
    guitar_ratio = ratios.get("other", 0)
    vocal_ratio = ratios.get("vocals", 0)
    drums_ratio = ratios.get("drums", 0)
    bass_ratio = ratios.get("bass", 0)
    
    if guitar_ratio > 0.50 and drums_ratio < 0.10 and vocal_ratio < 0.15:
        song_type = "solo_guitar"
    elif guitar_ratio > 0.30 and vocal_ratio > 0.25 and drums_ratio < 0.15:
        song_type = "vocal_guitar"
    else:
        song_type = "band"
    
    print(f"[SongType] Detected: {song_type}")
    return song_type


# =========================================================================
# キーコンセンサス投票（3手法の結果を統合）
# =========================================================================

_KEY_TO_SEMI = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8, 'Ab': 8,
    'A': 9, 'A#': 10, 'Bb': 10, 'B': 11
}
_SEMI_TO_FIFTH = [0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5]


def _key_to_semi(key_str):
    parts = key_str.split()
    root = parts[0] if parts else 'C'
    return _KEY_TO_SEMI.get(root, 0)


def _key_mode(key_str):
    return "minor" if "minor" in key_str.lower() else "major"


def _fifth_distance(semi_a, semi_b):
    """五度圏上の距離（0-6）"""
    fa = _SEMI_TO_FIFTH[semi_a % 12]
    fb = _SEMI_TO_FIFTH[semi_b % 12]
    diff = abs(fa - fb)
    return min(diff, 12 - diff)


def _relative_semi(semi, mode):
    """平行調の半音番号を返す（minor->+3=relative major, major->-3=relative minor）"""
    if mode == "minor":
        return (semi + 3) % 12
    else:
        return (semi - 3) % 12


def _keys_near(sa, ma, sb, mb):
    """2つのキーが五度圏で近いか（平行調も考慮）"""
    d1 = _fifth_distance(sa, sb)
    d2 = _fifth_distance(_relative_semi(sa, ma), sb)
    d3 = _fifth_distance(sa, _relative_semi(sb, mb))
    d4 = _fifth_distance(_relative_semi(sa, ma), _relative_semi(sb, mb))
    return min(d1, d2, d3, d4) <= 1


def key_consensus(madmom_key: str, chroma_key: str, chord_key: str) -> tuple:
    """
    3つのキー推定結果からコンセンサス投票でキーを決定する。
    
    Returns
    -------
    tuple: (final_key: str, method: str)
    """
    semi_m = _key_to_semi(madmom_key)
    semi_c = _key_to_semi(chroma_key)
    semi_d = _key_to_semi(chord_key)
    
    mode_m = _key_mode(madmom_key)
    mode_c = _key_mode(chroma_key)
    mode_d = _key_mode(chord_key)
    
    mc_near = _keys_near(semi_m, mode_m, semi_c, mode_c)
    cd_near = _keys_near(semi_c, mode_c, semi_d, mode_d)
    md_near = _keys_near(semi_m, mode_m, semi_d, mode_d)
    
    print(f"[KeyConsensus] M-C={mc_near}, C-D={cd_near}, M-D={md_near}")
    print(f"[KeyConsensus] Fifth positions: madmom={_SEMI_TO_FIFTH[semi_m]}, chroma={_SEMI_TO_FIFTH[semi_c]}, chord={_SEMI_TO_FIFTH[semi_d]}")
    
    if mc_near and cd_near:
        final_key = chroma_key
        method = "consensus-all"
    elif md_near and not mc_near:
        final_key = madmom_key
        method = "consensus-madmom+chord"
    elif mc_near:
        final_key = chroma_key
        method = "consensus-chroma+madmom"
    elif cd_near:
        final_key = chroma_key
        method = "consensus-chroma+chord"
    else:
        final_key = chroma_key
        method = "chroma-only"
    
    print(f"[KeyConsensus] Selected: {final_key} ({method})")
    return final_key, method
