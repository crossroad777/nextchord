"""
NextChord コード精度テスト
============================
U-FRET/ChordWiki/gakki.meの正解データと
NextChordの検出結果を照合して精度を計測する。

指標:
  - Root Accuracy: ルート音が一致した割合
  - Quality Accuracy: ルート+品質(major/minor)が一致した割合
  - MIREX Score: MIREX標準のコード評価
"""

import json
import sys
import os
from collections import Counter
from pathlib import Path

sys.path.insert(0, 'D:/Music/nextchord/fastapi-backend')

# ===================================================================
# 1. U-FRETデータからコード進行を抽出
# ===================================================================

def extract_chords_from_db(song_data):
    """songs_database.jsonlの1曲からコード列を抽出"""
    chords = []
    for section in song_data.get('sections', []):
        for line in section.get('lines', []):
            for ch in line.get('chords', []):
                root = ch.get('root', '')
                quality = ch.get('quality', 'maj')
                extension = ch.get('extension', '')
                if not root:
                    continue
                # 正規化
                if quality == 'min':
                    name = f"{root}m"
                elif quality == 'dim':
                    name = f"{root}dim"
                elif quality == 'aug':
                    name = f"{root}aug"
                else:
                    name = root
                # extension追加
                if extension == '7':
                    name += '7'
                elif extension == 'M7':
                    name += 'Maj7'
                elif quality == 'min' and extension == '7':
                    name = f"{root}m7"
                chords.append(name)
    return chords

# ===================================================================
# 2. NextChordの検出結果を取得
# ===================================================================

def load_nextchord_result(session_dir):
    """NextChordのセッションからコード列を抽出"""
    session_json = Path(session_dir) / 'session.json'
    if not session_json.exists():
        return None, None, None
    
    data = json.load(open(session_json, encoding='utf-8'))
    result = data.get('result', {})
    structured = result.get('structured_data', [])
    key = result.get('key', data.get('key', 'Unknown'))
    
    chords = [e.get('chord', 'N.C.') for e in structured]
    # N.C. を除外して連続するコードのみ取得
    chord_seq = []
    prev = None
    for c in chords:
        if c != 'N.C.' and c != prev:
            chord_seq.append(c)
            prev = c
    
    return chord_seq, key, data.get('filename', 'Unknown')

# ===================================================================
# 3. 精度計算
# ===================================================================

_ROOT_TO_PC = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
    'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11
}

def _parse_root(chord):
    if len(chord) > 1 and chord[1] in '#b':
        return _ROOT_TO_PC.get(chord[:2])
    return _ROOT_TO_PC.get(chord[:1])

def _is_minor(chord):
    root = chord[:2] if len(chord) > 1 and chord[1] in '#b' else chord[:1]
    suffix = chord[len(root):]
    return suffix.startswith('m') and not suffix.startswith('maj')

def compute_accuracy(detected, reference):
    """
    2つのコード列の精度を計算（順序一致ではなく、コード分布比較）
    
    実際の楽曲では拍の粒度が違うので、
    「検出されたコードの集合が正解に含まれるか」で評価
    """
    if not detected or not reference:
        return {'root': 0.0, 'quality': 0.0, 'exact': 0.0, 'n_detected': 0, 'n_reference': 0}
    
    # ユニークコード集合の比較
    det_set = set(detected)
    ref_set = set(reference)
    
    # 正解に含まれるルート
    ref_roots = {_parse_root(c) for c in ref_set if _parse_root(c) is not None}
    det_roots = {_parse_root(c) for c in det_set if _parse_root(c) is not None}
    
    # ルート一致率
    if det_roots:
        root_correct = len(det_roots & ref_roots) / len(det_roots)
    else:
        root_correct = 0.0
    
    # 品質一致率 (root + major/minor)
    ref_rq = {(_parse_root(c), _is_minor(c)) for c in ref_set if _parse_root(c) is not None}
    det_rq = {(_parse_root(c), _is_minor(c)) for c in det_set if _parse_root(c) is not None}
    if det_rq:
        quality_correct = len(det_rq & ref_rq) / len(det_rq)
    else:
        quality_correct = 0.0
    
    # 完全一致率
    if det_set:
        exact_correct = len(det_set & ref_set) / len(det_set)
    else:
        exact_correct = 0.0
    
    # コード分布のコサイン類似度
    all_chords = det_set | ref_set
    det_counts = Counter(detected)
    ref_counts = Counter(reference)
    
    import numpy as np
    det_vec = np.array([det_counts.get(c, 0) for c in all_chords], dtype=float)
    ref_vec = np.array([ref_counts.get(c, 0) for c in all_chords], dtype=float)
    
    d_norm = np.linalg.norm(det_vec)
    r_norm = np.linalg.norm(ref_vec)
    if d_norm > 0 and r_norm > 0:
        cosine = np.dot(det_vec, ref_vec) / (d_norm * r_norm)
    else:
        cosine = 0.0
    
    return {
        'root': root_correct,
        'quality': quality_correct,
        'exact': exact_correct,
        'cosine': float(cosine),
        'n_detected': len(det_set),
        'n_reference': len(ref_set),
        'det_unique': sorted(det_set),
        'ref_unique': sorted(ref_set),
        'matched': sorted(det_set & ref_set),
        'false_positive': sorted(det_set - ref_set),
        'missed': sorted(ref_set - det_set),
    }

# ===================================================================
# 4. メインテスト
# ===================================================================

def find_matching_song(filename, db_path='D:/Music/Web Scraping/songs_database.jsonl'):
    """ファイル名からsongs_databaseで一致する曲を検索"""
    # ファイル名からタイトル候補を抽出
    name = Path(filename).stem
    # よくあるパターン: "アーティスト - 曲名" or "曲名"
    parts = name.split(' - ')
    if len(parts) >= 2:
        artist_query = parts[0].strip().lower()
        title_query = parts[1].strip().lower()
    else:
        artist_query = None
        title_query = name.strip().lower()
    
    print(f"Searching for: title='{title_query}', artist='{artist_query}'")
    
    best_match = None
    with open(db_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i > 10000:  # 最初の10000曲のみ検索（高速化）
                break
            try:
                song = json.loads(line)
                meta = song.get('meta', {})
                title = (meta.get('title', '') or '').lower()
                artist = (meta.get('artist', '') or '').lower()
                
                if title_query and title_query in title:
                    if artist_query is None or artist_query in artist:
                        best_match = song
                        print(f"  Found: {meta.get('title')} / {meta.get('artist')}")
                        break
            except:
                continue
    
    return best_match

def run_test():
    """全セッションの精度テスト"""
    uploads_dir = Path('D:/Music/nextchord/uploads')
    sessions = sorted([d for d in uploads_dir.iterdir() if d.is_dir()])
    
    print("=" * 70)
    print("NextChord コード精度テスト")
    print("=" * 70)
    print(f"セッション数: {len(sessions)}")
    print()
    
    results = []
    
    for session_dir in sessions:
        chords, key, filename = load_nextchord_result(session_dir)
        if not chords:
            continue
        
        print(f"\n--- {filename} ---")
        print(f"  Key: {key}")
        print(f"  Detected chords ({len(chords)} unique transitions): {chords[:15]}...")
        
        # U-FRETデータベースで検索
        match = find_matching_song(filename)
        if match:
            ref_chords = extract_chords_from_db(match)
            ref_seq = []
            prev = None
            for c in ref_chords:
                if c != prev:
                    ref_seq.append(c)
                    prev = c
            
            print(f"  Reference chords ({len(ref_seq)} unique transitions): {ref_seq[:15]}...")
            
            acc = compute_accuracy(chords, ref_seq)
            results.append(acc)
            
            print(f"  Root accuracy:    {acc['root']:.1%}")
            print(f"  Quality accuracy: {acc['quality']:.1%}")
            print(f"  Exact match:      {acc['exact']:.1%}")
            print(f"  Cosine similarity: {acc['cosine']:.3f}")
            print(f"  False positives:  {acc['false_positive']}")
            print(f"  Missed:           {acc['missed'][:10]}")
        else:
            print(f"  [SKIP] No reference found in database")
    
    if results:
        print("\n" + "=" * 70)
        print("総合結果")
        print("=" * 70)
        import numpy as np
        avg_root = np.mean([r['root'] for r in results])
        avg_qual = np.mean([r['quality'] for r in results])
        avg_exact = np.mean([r['exact'] for r in results])
        avg_cos = np.mean([r['cosine'] for r in results])
        print(f"  平均 Root accuracy:    {avg_root:.1%}")
        print(f"  平均 Quality accuracy: {avg_qual:.1%}")
        print(f"  平均 Exact match:      {avg_exact:.1%}")
        print(f"  平均 Cosine similarity: {avg_cos:.3f}")
        print(f"  テスト曲数: {len(results)}")
    else:
        print("\n[WARNING] No matching songs found for comparison")

if __name__ == '__main__':
    run_test()
