"""
NextChord Pipeline
==================
コード抽出パイプラインの実装。
main.py から分離された run_pipeline() 関数を含む。

依存関係:
    - chord_processing (セクション分析、コード処理、キー推定)
    - note_transcription (ノート検出)
    - tab_generator (TAB/MusicXML生成)
    - lyrics_postprocess (歌詞後処理)
    - phrase_processor (フレーズ分割)
"""

import time
import json
import csv
import threading
import concurrent.futures
from pathlib import Path

import numpy as np
import librosa

from chord_processing import (
    analyze_sections,
    standardize_chord,
    _smooth_chord_segments,
    _beat_majority_chords,
    _normalize_chords_to_key,
    estimate_key_from_audio,
    detect_song_type,
    key_consensus,
)

# GPU排他ロック: Whisper/Demucs等のGPUモデルを同時実行しないための排他制御
_gpu_lock = threading.Lock()


def run_pipeline(session_id: str, session_dir: Path, wav_path: Path, ctx: dict):
    """
    コード抽出パイプラインをバックグラウンドで実行（究極の並列化・インプロセス）
    
    並列実行するタスク:
      Group A: Beats, Key, Whisper, Notes (Demucs+basic-pitch)
      Group B: HPS → Chroma → Chord判定
    Group A と B は完全に並列で実行され、合流後に結果を統合する。
    
    Parameters
    ----------
    session_id : str
        セッションID
    session_dir : Path
        セッションディレクトリ
    wav_path : Path
        WAVファイルパス
    ctx : dict
        グローバルコンテキスト。以下のキーが必要:
        - sessions: セッション辞書
        - save_session: save_session関数
        - SessionStatus: SessionStatusクラス
        - beat_processor, beat_tracker: ビート検出モデル
        - key_processor: キー検出モデル
        - chroma_processor, chord_processor: コード検出モデル
        - whisper_model: Whisperモデル
        - transcribe_notes: ノート検出関数
        - notes_to_tab_data, notes_to_musicxml: TAB/MusicXML生成関数
        - estimate_key_from_chords, generate_chord_strum_notes: ユーティリティ
    """
    # コンテキストからグローバル変数を取得
    sessions = ctx["sessions"]
    save_session = ctx["save_session"]
    SessionStatus = ctx["SessionStatus"]
    beat_processor = ctx.get("beat_processor")
    beat_tracker = ctx.get("beat_tracker")
    key_processor = ctx.get("key_processor")
    chroma_processor = ctx.get("chroma_processor")
    chord_processor = ctx.get("chord_processor")
    whisper_model = ctx.get("whisper_model")
    transcribe_notes = ctx.get("transcribe_notes")
    notes_to_tab_data = ctx.get("notes_to_tab_data")
    notes_to_musicxml = ctx.get("notes_to_musicxml")
    estimate_key_from_chords_fn = ctx.get("estimate_key_from_chords")
    generate_chord_strum_notes = ctx.get("generate_chord_strum_notes")
    
    start_total = time.time()
    try:
        sessions[session_id]["status"] = SessionStatus.PROCESSING
        session_data = sessions[session_id]
        
        # --- HPS + Chroma + Chord を一括実行するヘルパー ---
        def _hps_chroma_chords(wav_p, sess_dir, sid):
            """HPS → Chroma → Chord判定を逐次実行（全体としては並列タスク）"""
            import soundfile as sf
            
            # HPS (22050Hzでロード: ネイティブSRの半分で十分、HPSS ~4倍高速)
            t_hps = time.time()
            print(f"[{sid}] [DEBUG] Applying HPS (sr=22050)...")
            y_full, sr_full = librosa.load(str(wav_p), sr=22050)
            y_harmonic, _ = librosa.effects.hpss(y_full)
            # harmonic.wav を書き出し（Chroma用）
            h_path = sess_dir / "harmonic.wav"
            sf.write(str(h_path), y_harmonic, sr_full)
            hps_sec = time.time() - t_hps
            print(f"[{sid}] [PERF] HPS: {hps_sec:.1f}s")
            _update_step(session_data, "harmony", f"✅ ハーモニー分離 ({hps_sec:.0f}s)")
            
            # Section Detection (軽量: 固定ラベリング)
            secs = analyze_sections(y_full, sr_full)
            _update_step(session_data, "sections", "✅ セクション検出")
            
            # Chroma + Chord判定
            t_chr = time.time()
            seg_s, seg_l = None, None
            
            if chroma_processor is not None and chord_processor is not None:
                # madmom が利用可能: DeepChroma → ChordRecognition
                print(f"[{sid}] [DEBUG] Starting madmom Chroma extraction...")
                feats_result = chroma_processor(str(h_path))
                if feats_result is not None:
                    collapsed = chord_processor(feats_result)
                    seg_s = collapsed['start']
                    seg_l = collapsed['label']
                    # デバッグ: madmom生ラベルの先頭20件
                    from collections import Counter
                    raw_labels = list(seg_l[:20]) if len(seg_l) > 20 else list(seg_l)
                    label_counts = Counter(seg_l)
                    print(f"[{sid}] [MADMOM RAW] First 20 segments: {raw_labels}")
                    print(f"[{sid}] [MADMOM RAW] Label distribution: {label_counts.most_common(15)}")
                    print(f"[{sid}] [MADMOM RAW] Total segments: {len(seg_l)}")
                    
                    # アンサンブル: librosaでも検出し、madmomのN(無音)区間を補完
                    try:
                        lib_s, lib_l = _librosa_chord_detection(y_harmonic, sr_full, sid)
                        n_count = sum(1 for l in seg_l if l == 'N')
                        if n_count > 0 and lib_s is not None:
                            patched = 0
                            seg_l_list = list(seg_l)
                            for i in range(len(seg_l_list)):
                                if seg_l_list[i] == 'N':
                                    # madmomがN判定した区間のlibrosa結果を採用
                                    t = seg_s[i] if i < len(seg_s) else 0
                                    best_lib = 'N'
                                    for j in range(len(lib_s)):
                                        lib_end = lib_s[j+1] if j+1 < len(lib_s) else t + 10
                                        if lib_s[j] <= t < lib_end and lib_l[j] != 'N':
                                            best_lib = lib_l[j]
                                            break
                                    if best_lib != 'N':
                                        seg_l_list[i] = best_lib
                                        patched += 1
                            if patched > 0:
                                seg_l = np.array(seg_l_list)
                                print(f"[{sid}] [ENSEMBLE] Patched {patched}/{n_count} N-segments with librosa results")
                    except Exception as e:
                        print(f"[{sid}] [ENSEMBLE] librosa fallback skipped: {e}")
            else:
                # librosa フォールバック: chroma_cqt → テンプレートマッチング
                print(f"[{sid}] [DEBUG] madmom unavailable, using librosa chroma fallback...")
                seg_s, seg_l = _librosa_chord_detection(y_harmonic, sr_full, sid)
            
            chr_sec = time.time() - t_chr
            print(f"[{sid}] [PERF] Chroma+Chord: {chr_sec:.1f}s")
            _update_step(session_data, "chroma", f"✅ コード解析 ({chr_sec:.0f}s)")
            
            return {
                'sections': secs,
                'seg_starts': seg_s,
                'seg_labels': seg_l,
            }
        
        def _librosa_chord_detection(y_harmonic, sr, sid):
            """librosaベースのコード検出（改良版: 8テンプレート + CQT/STFT統合 + メディアンフィルタ）"""
            # チューニング推定
            tuning = librosa.estimate_tuning(y=y_harmonic, sr=sr)
            
            # Chroma CQT + STFT を統合（単体より安定）
            hop_length = 2048
            chroma_cqt = librosa.feature.chroma_cqt(
                y=y_harmonic, sr=sr, hop_length=hop_length, n_chroma=12,
                tuning=tuning
            )
            chroma_stft = librosa.feature.chroma_stft(
                y=y_harmonic, sr=sr, hop_length=hop_length, n_chroma=12,
                tuning=tuning
            )
            # 50:50 統合
            chroma = (chroma_cqt + chroma_stft) / 2.0
            
            # コードテンプレート定義（8種類）
            chord_templates = {}
            note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            templates = {
                'maj':  np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], dtype=float),
                'min':  np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0], dtype=float),
                '7':    np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0], dtype=float),
                'min7': np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0], dtype=float),
                'maj7': np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1], dtype=float),
                'dim':  np.array([1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0], dtype=float),
                'sus4': np.array([1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0], dtype=float),
                'sus2': np.array([1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0], dtype=float),
            }
            
            for i, name in enumerate(note_names):
                for qual, tmpl in templates.items():
                    chord_templates[f"{name}:{qual}"] = np.roll(tmpl, i)
            
            # フレームごとにテンプレートマッチング
            n_frames = chroma.shape[1]
            frame_chords = []
            frame_scores = []
            
            for f in range(n_frames):
                frame = chroma[:, f]
                if np.sum(frame) < 0.01:
                    frame_chords.append("N")
                    frame_scores.append(0.0)
                    continue
                
                # 正規化
                frame_norm = frame / (np.linalg.norm(frame) + 1e-8)
                
                best_chord = "N"
                best_score = 0.3  # 最低閾値
                
                for chord_name, template in chord_templates.items():
                    template_norm = template / (np.linalg.norm(template) + 1e-8)
                    score = np.dot(frame_norm, template_norm)
                    if score > best_score:
                        best_score = score
                        best_chord = chord_name
                
                frame_chords.append(best_chord)
                frame_scores.append(best_score)
            
            # メディアンフィルタ: 3フレーム窓で短い揺らぎを除去
            if len(frame_chords) > 3:
                smoothed = list(frame_chords)
                for i in range(1, len(smoothed) - 1):
                    if smoothed[i] != smoothed[i-1] and smoothed[i] != smoothed[i+1] and smoothed[i-1] == smoothed[i+1]:
                        smoothed[i] = smoothed[i-1]
                frame_chords = smoothed
            
            # 隣接する同一コードをセグメントに統合
            if not frame_chords:
                return np.array([0.0]), np.array(['N'])
            
            seg_starts = []
            seg_labels = []
            prev_chord = None
            frame_duration = hop_length / sr
            
            for i, chord in enumerate(frame_chords):
                if chord != prev_chord:
                    seg_starts.append(i * frame_duration)
                    seg_labels.append(chord)
                    prev_chord = chord
            
            # 短すぎるセグメント（0.3秒未満）を前のセグメントにマージ
            merged_starts = [seg_starts[0]]
            merged_labels = [seg_labels[0]]
            min_duration = 0.3
            
            for i in range(1, len(seg_starts)):
                duration = seg_starts[i] - merged_starts[-1]
                if duration < min_duration and len(merged_starts) > 1:
                    continue
                merged_starts.append(seg_starts[i])
                merged_labels.append(seg_labels[i])
            
            seg_s = np.array(merged_starts)
            seg_l = np.array(merged_labels)
            
            n_unique = len(set(merged_labels) - {'N'})
            print(f"[{sid}] [LIBROSA] Detected {len(merged_labels)} chord segments ({n_unique} unique chords)")
            print(f"[{sid}] [LIBROSA] Tuning offset: {tuning:+.2f} semitones")
            
            return seg_s, seg_l
        
        # --- リアルタイム進捗追跡 ---
        def _update_step(sd, step_name, msg):
            """完了したステップを追跡し、プログレスメッセージを更新"""
            if "_steps" not in sd:
                sd["_steps"] = {}
            sd["_steps"][step_name] = msg
            # 完了ステップ数 / 全ステップ数 を計算
            total_steps = 7  # beats, key, whisper, notes, harmony, sections, chroma
            done = len(sd["_steps"])
            pct = int(done / total_steps * 100)
            # 最新の完了ステップを表示
            latest = list(sd["_steps"].values())[-1]
            sd["progress"] = f"解析中... ({done}/{total_steps}) {latest}"
            save_session(session_id)
        
        # === タスク実行（GPU競合回避のため順序最適化） ===
        # CPU系タスク: beats, key, HPS+Chroma → 即座に並列開始
        # GPU系タスク: Whisper → 完了後 → Demucs + basic-pitch（VRAM 8GBで同時利用不可）
        futures = {}
        session_data["progress"] = "🎵 解析開始... (0/7)"
        save_session(session_id)
        
        perf_log = []
        perf_log.append(f"=== NextChord Pipeline Log ===")
        perf_log.append(f"Session: {session_id}")
        perf_log.append(f"WAV: {wav_path}")
        perf_log.append(f"Models: beat_processor={'OK' if beat_processor else 'NONE'}, key_processor={'OK' if key_processor else 'NONE'}, whisper={'OK' if whisper_model else 'NONE'}, transcribe_notes={'OK' if transcribe_notes else 'NONE'}")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            print(f"[{session_id}] [PIPELINE] Starting all tasks...")
            
            # CPU系タスクを一気に投入
            futures['act'] = executor.submit(beat_processor, str(wav_path)) if beat_processor else None
            futures['key_vec'] = executor.submit(key_processor, str(wav_path)) if key_processor else None
            futures['hps_chroma'] = executor.submit(
                _hps_chroma_chords, wav_path, session_dir, session_id
            )
            
            # Whisper (GPU) を先に実行
            # initial_prompt: 日本語歌詞であることを伝え認識精度を向上
            # condition_on_previous_text=False: 繰り返しハルシネーション防止
            # no_speech_threshold: 歌声の取りこぼし防止（デフォルト0.6→0.4）
            _whisper_opts = dict(
                language="ja",
                word_timestamps=True,
                initial_prompt="日本語の歌詞。ポップス、ロック、バラード。歌詞を正確に書き起こしてください。",
                condition_on_previous_text=False,
                no_speech_threshold=0.4,
            )
            def _whisper_with_lock(model, wav, opts, sid):
                """GPU排他ロック付きWhisper実行（同時実行によるCUDA競合を防止）"""
                print(f"[{sid}] [WHISPER] Waiting for GPU lock...")
                with _gpu_lock:
                    print(f"[{sid}] [WHISPER] GPU lock acquired, starting transcription...")
                    try:
                        return model.transcribe(str(wav), **opts)
                    except RuntimeError as e:
                        # CUDA競合時のリトライ（1回）
                        print(f"[{sid}] [WHISPER] ⚠️ RuntimeError: {e}, retrying...")
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                        return model.transcribe(str(wav), **opts)
            
            futures['whisper_res'] = executor.submit(_whisper_with_lock, whisper_model, wav_path, _whisper_opts, session_id) if whisper_model else None
            
            # --- CPU系の結果を先に回収 ---
            # Beats
            act = None
            if futures.get('act'):
                try:
                    act = futures['act'].result()
                    t_beats = time.time() - start_total
                    perf_log.append(f"[OK] Beats: {t_beats:.1f}s (shape={act.shape if hasattr(act,'shape') else 'N/A'})")
                    print(f"[{session_id}] [PERF] Beats done: {t_beats:.1f}s")
                    _update_step(session_data, "beats", f"✅ ビート検出 ({t_beats:.0f}s)")
                except Exception as e:
                    perf_log.append(f"[FAIL] Beats: {type(e).__name__}: {e}")
                    print(f"[{session_id}] [ERROR] Beats failed: {e}")
            else:
                perf_log.append(f"[SKIP] Beats: beat_processor not available")
            
            # Key
            key_vec = None
            if futures.get('key_vec'):
                try:
                    key_vec = futures['key_vec'].result()
                    t_key = time.time() - start_total
                    perf_log.append(f"[OK] Key: {t_key:.1f}s (vec_len={len(key_vec) if key_vec is not None else 0})")
                    print(f"[{session_id}] [PERF] Key done: {t_key:.1f}s")
                    _update_step(session_data, "key", f"✅ キー検出 ({t_key:.0f}s)")
                except Exception as e:
                    perf_log.append(f"[FAIL] Key: {type(e).__name__}: {e}")
                    print(f"[{session_id}] [ERROR] Key failed: {e}")
            else:
                perf_log.append(f"[SKIP] Key: key_processor not available")
            
            # Whisper (GPU完了を待つ)
            whisper_res = None
            if futures.get('whisper_res'):
                try:
                    whisper_res = futures['whisper_res'].result()
                    
                    # 日本語歌詞の後処理（誤認識修正・ハルシネーション除去）
                    from lyrics_postprocess import postprocess_whisper_segments
                    if whisper_res and whisper_res.get('segments'):
                        original_count = len(whisper_res['segments'])
                        whisper_res['segments'] = postprocess_whisper_segments(whisper_res['segments'])
                        # テキスト全体も再構築
                        whisper_res['text'] = ''.join(s['text'] for s in whisper_res['segments'])
                        post_count = len(whisper_res['segments'])
                        if original_count != post_count:
                            print(f"[{session_id}] [LYRICS] Post-process: {original_count} → {post_count} segments")
                    
                    # === Whisper ハルシネーション検出（セグメント個別除去方式） ===
                    if whisper_res and whisper_res.get('segments'):
                        hallucination_markers = [
                            "歌詞を正確に書き起こしてください",
                            "ポップス、ロック、バラード",
                            "日本語の歌詞",
                        ]
                        
                        # マーカーを含むセグメントだけを除去（全体は削除しない）
                        clean_segments = []
                        removed_count = 0
                        for seg in whisper_res['segments']:
                            seg_text = seg.get('text', '')
                            is_hallu_seg = False
                            for marker in hallucination_markers:
                                if marker in seg_text:
                                    is_hallu_seg = True
                                    print(f"[{session_id}] [LYRICS] ⚠️ Removing hallucinated segment: '{seg_text[:50]}'")
                                    break
                            if not is_hallu_seg:
                                clean_segments.append(seg)
                            else:
                                removed_count += 1
                        
                        if removed_count > 0:
                            print(f"[{session_id}] [LYRICS] Removed {removed_count} hallucinated segments, {len(clean_segments)} remaining")
                            whisper_res['segments'] = clean_segments
                            whisper_res['text'] = ''.join(s['text'] for s in clean_segments)
                        
                        # 除去後にセグメントが全てなくなった場合のみNone化
                        if not clean_segments or not whisper_res['text'].strip():
                            print(f"[{session_id}] [LYRICS] 🚫 All segments were hallucinations — no lyrics")
                            whisper_res = None
                    
                    t_whisper = time.time() - start_total
                    n_segments = len(whisper_res.get('segments', [])) if whisper_res else 0
                    text_preview = whisper_res.get('text', '')[:100] if whisper_res else '(hallucination filtered)'
                    perf_log.append(f"[OK] Whisper: {t_whisper:.1f}s ({n_segments} segments)")
                    perf_log.append(f"     Whisper text: {text_preview}...")
                    print(f"[{session_id}] [PERF] Whisper done: {t_whisper:.1f}s ({n_segments} segments)")
                    _update_step(session_data, "whisper", f"✅ 歌詞検出 ({t_whisper:.0f}s, {n_segments}セグメント)")
                except Exception as e:
                    perf_log.append(f"[FAIL] Whisper: {type(e).__name__}: {e}")
                    print(f"[{session_id}] [ERROR] Whisper failed: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                perf_log.append(f"[SKIP] Whisper: whisper_model not available")
            
            # Whisper完了後にDemucs+basic-pitch開始（GPU空き確保）
            # CPU環境ではDemucsが非常に遅いため、Deep Analysis時のみ実行
            import torch
            _has_gpu = torch.cuda.is_available()
            note_events = []
            if transcribe_notes:
                # Deep Analysis の場合、分離済みギター音源を直接使う（Demucs再分離なし）
                guitar_wav_override = session_data.get("guitar_wav_path")
                if guitar_wav_override and Path(guitar_wav_override).exists():
                    print(f"[{session_id}] [PIPELINE] Deep Analysis: using pre-separated guitar: {guitar_wav_override}")
                    perf_log.append(f"[INFO] Deep Analysis: guitar_wav={guitar_wav_override}")
                    futures['note_events'] = executor.submit(
                        transcribe_notes, str(wav_path),
                        guitar_wav_path=guitar_wav_override,
                        use_demucs=False, solo_guitar_mode=True, use_basic_pitch=True
                    )
                elif _has_gpu:
                    print(f"[{session_id}] [PIPELINE] GPU mode: Demucs+basic-pitch...")
                    futures['note_events'] = executor.submit(
                        transcribe_notes, str(wav_path), use_demucs=True, solo_guitar_mode=True, use_basic_pitch=True
                    )
                else:
                    # CPU環境: Demucsスキップ、basic-pitchのみ
                    print(f"[{session_id}] [PIPELINE] CPU mode: basic-pitch only (Demucs skipped for speed)")
                    futures['note_events'] = executor.submit(
                        transcribe_notes, str(wav_path), use_demucs=False, solo_guitar_mode=True, use_basic_pitch=True
                    )
            else:
                futures['note_events'] = None
                perf_log.append(f"[SKIP] Notes: transcribe_notes not available")
            
            # HPS+Chroma (CPU - 既に並列実行中)
            hps_result = {}
            if futures.get('hps_chroma'):
                try:
                    hps_result = futures['hps_chroma'].result()
                except Exception as e:
                    perf_log.append(f"[FAIL] HPS+Chroma (future): {type(e).__name__}: {e}")
                    print(f"[{session_id}] [ERROR] HPS+Chroma failed: {e}")
                
                # ログ出力（hps_result が取得できた場合のみ）
                if hps_result:
                    t_hps = time.time() - start_total
                    _sec = hps_result.get('sections')
                    _lbl = hps_result.get('seg_labels')
                    n_sections = len(_sec) if _sec is not None else 0
                    n_chords = len(_lbl) if _lbl is not None else 0
                    perf_log.append(f"[OK] HPS+Chroma: {t_hps:.1f}s ({n_sections} sections, {n_chords} chord segments)")
                    print(f"[{session_id}] [PERF] HPS+Chroma done: {t_hps:.1f}s")
            
            # Notes (Demucs + basic-pitch) 最後に回収
            if futures.get('note_events'):
                try:
                    note_events = futures['note_events'].result()
                    t_notes = time.time() - start_total
                    perf_log.append(f"[OK] Notes: {t_notes:.1f}s ({len(note_events)} notes)")
                    print(f"[{session_id}] [PERF] Notes done: {t_notes:.1f}s ({len(note_events)} notes)")
                    _update_step(session_data, "notes", f"✅ 音符検出 ({len(note_events)}ノート, {t_notes:.0f}s)")
                except Exception as e:
                    perf_log.append(f"[FAIL] Notes: {type(e).__name__}: {e}")
                    print(f"[{session_id}] [ERROR] Notes failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            # === Whisper補完: Demucs vocals.wav で再解析 ===
            # フルミックスでは音楽に埋もれて歌詞を検出できない区間がある
            # Demucs分離後のvocals.wavで再度Whisperを実行し、欠落分を補完
            # ⚡ CPU環境ではスキップ（Whisper追加実行は非常に遅いため）
            vocals_wav = session_dir / "htdemucs" / "converted" / "vocals.wav"
            if whisper_model and vocals_wav.exists() and _has_gpu:
                try:
                    t_vocal_whisper = time.time()
                    print(f"[{session_id}] [LYRICS] 🎤 Running Whisper on vocals.wav for supplementary detection...")
                    _update_step(session_data, "whisper", "🎤 ボーカル分離音源で歌詞補完中...")
                    
                    # vocals.wav用: 背景音楽がないため検出感度を上げる
                    _vocal_whisper_opts = dict(
                        language="ja",
                        word_timestamps=True,
                        initial_prompt="日本語の歌詞。ポップス、ロック、バラード。歌詞を正確に書き起こしてください。",
                        condition_on_previous_text=False,
                        no_speech_threshold=0.2,
                    )
                    vocal_res = _whisper_with_lock(whisper_model, vocals_wav, _vocal_whisper_opts, session_id)
                    
                    if vocal_res and vocal_res.get('segments'):
                        # ハルシネーション除去
                        from lyrics_postprocess import postprocess_whisper_segments
                        vocal_res['segments'] = postprocess_whisper_segments(vocal_res['segments'])
                        
                        # マーカーテキスト除去
                        hallucination_markers = [
                            "歌詞を正確に書き起こしてください",
                            "ポップス、ロック、バラード",
                            "日本語の歌詞",
                        ]
                        vocal_segs = [s for s in vocal_res['segments']
                                     if not any(m in s.get('text', '') for m in hallucination_markers)]
                        
                        vocal_count = len(vocal_segs)
                        
                        def _is_time_covered(seg, existing, margin=1.0):
                            seg_mid = (seg.get('start', 0) + seg.get('end', 0)) / 2
                            for e in existing:
                                if e.get('start', 0) - margin <= seg_mid <= e.get('end', 0) + margin:
                                    return True
                            return False
                        
                        if whisper_res and whisper_res.get('segments'):
                            existing_segs = whisper_res['segments']
                            existing_count = len(existing_segs)
                            
                            # vocals.wavの結果が多い場合 → vocals.wavをベースにフルミックスで補完
                            if vocal_count >= existing_count:
                                primary = list(vocal_segs)
                                secondary = existing_segs
                            else:
                                primary = list(existing_segs)
                                secondary = vocal_segs
                            
                            added = 0
                            for seg in secondary:
                                if not _is_time_covered(seg, primary):
                                    primary.append(seg)
                                    added += 1
                            
                            primary.sort(key=lambda s: s.get('start', 0))
                            whisper_res = {
                                'segments': primary,
                                'text': ''.join(s['text'] for s in primary)
                            }
                            print(f"[{session_id}] [LYRICS] ✅ Merged: {len(primary)} segments (added {added} from secondary)")
                            perf_log.append(f"[OK] Vocal Whisper merged: {len(primary)} segments (+{added} supplemented)")
                        else:
                            if vocal_segs:
                                whisper_res = {
                                    'segments': vocal_segs,
                                    'text': ''.join(s['text'] for s in vocal_segs)
                                }
                                print(f"[{session_id}] [LYRICS] ✅ Using vocals.wav results: {len(vocal_segs)} segments (full mix had none)")
                                perf_log.append(f"[OK] Vocal Whisper (full replacement): {len(vocal_segs)} segments")
                        
                        dt = time.time() - t_vocal_whisper
                        print(f"[{session_id}] [PERF] Vocal Whisper: {dt:.1f}s")
                        n_final = len(whisper_res.get('segments', [])) if whisper_res else 0
                        _update_step(session_data, "whisper", f"✅ 歌詞検出完了 ({n_final}セグメント)")
                    
                except Exception as e:
                    print(f"[{session_id}] [LYRICS] Vocal Whisper supplement failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            # === 冒頭35秒の特別解析 ===
            # Whisperは曲冒頭を無音/音楽として誤判定しやすい
            # vocals.wavの冒頭35秒を切り出して超高感度で再解析
            # ⚡ CPU環境ではスキップ（Whisper追加実行は非常に遅いため）
            if whisper_model and vocals_wav.exists() and _has_gpu:
                try:
                    import soundfile as sf
                    y_vocal, sr_vocal = sf.read(str(vocals_wav))
                    intro_duration = 35  # 秒
                    intro_samples = int(sr_vocal * intro_duration)
                    
                    if len(y_vocal) > intro_samples:
                        intro_audio = y_vocal[:intro_samples]
                        intro_path = session_dir / "vocals_intro.wav"
                        sf.write(str(intro_path), intro_audio, sr_vocal)
                        
                        print(f"[{session_id}] [LYRICS] 🔍 Intro analysis: {intro_duration}s extracted from vocals.wav")
                        
                        _intro_opts = dict(
                            language="ja",
                            word_timestamps=True,
                            initial_prompt="歌詞。",
                            condition_on_previous_text=False,
                            no_speech_threshold=0.1,  # 超高感度
                        )
                        intro_res = _whisper_with_lock(whisper_model, intro_path, _intro_opts, session_id)
                        
                        if intro_res and intro_res.get('segments'):
                            from lyrics_postprocess import postprocess_whisper_segments
                            intro_res['segments'] = postprocess_whisper_segments(intro_res['segments'])
                            
                            # マーカー除去
                            hallucination_markers = [
                                "歌詞を正確に書き起こしてください",
                                "ポップス、ロック、バラード",
                                "日本語の歌詞",
                            ]
                            intro_segs = [s for s in intro_res['segments']
                                         if not any(m in s.get('text', '') for m in hallucination_markers)]
                            
                            print(f"[{session_id}] [LYRICS] 🔍 Intro detected: {len(intro_segs)} segments")
                            for s in intro_segs:
                                print(f"  [{s.get('start',0):.1f}-{s.get('end',0):.1f}] {s.get('text','')[:60]}")
                            
                            if intro_segs:
                                if whisper_res and whisper_res.get('segments'):
                                    # 既存セグメントでカバーされていない冒頭セグメントを追加
                                    existing = whisper_res['segments']
                                    added_intro = 0
                                    for seg in intro_segs:
                                        seg_mid = (seg.get('start', 0) + seg.get('end', 0)) / 2
                                        covered = False
                                        for e in existing:
                                            if e.get('start', 0) - 1.0 <= seg_mid <= e.get('end', 0) + 1.0:
                                                covered = True
                                                break
                                        if not covered:
                                            existing.append(seg)
                                            added_intro += 1
                                    
                                    if added_intro > 0:
                                        existing.sort(key=lambda s: s.get('start', 0))
                                        whisper_res['segments'] = existing
                                        whisper_res['text'] = ''.join(s['text'] for s in existing)
                                        print(f"[{session_id}] [LYRICS] ✅ Intro: added {added_intro} segments from intro analysis")
                                        perf_log.append(f"[OK] Intro analysis: +{added_intro} segments")
                                else:
                                    whisper_res = {
                                        'segments': intro_segs,
                                        'text': ''.join(s['text'] for s in intro_segs)
                                    }
                                    print(f"[{session_id}] [LYRICS] ✅ Intro: using {len(intro_segs)} intro segments (main had none)")
                        
                        # クリーンアップ
                        if intro_path.exists():
                            intro_path.unlink()
                            
                except Exception as e:
                    print(f"[{session_id}] [LYRICS] Intro analysis failed: {e}")
                    import traceback
                    traceback.print_exc()

        t_parallel = time.time() - start_total
        perf_log.append(f"")
        perf_log.append(f"Total parallel: {t_parallel:.1f}s")
        print(f"[{session_id}] [PERF] All parallel tasks done: {t_parallel:.1f}s")

        # === 楽曲タイプ自動判定 ===
        # Demucs 分離完了後、4ステムのエネルギー比で判定
        song_type = detect_song_type(session_dir, wav_path)
        is_solo_guitar = (song_type == "solo_guitar")
        session_data["song_type"] = song_type
        perf_log.append(f"Song type: {song_type} (solo_guitar={is_solo_guitar})")
        
        # ソロギターの場合、Whisperの歌詞は不要（ハルシネーション防止）
        if is_solo_guitar and whisper_res:
            print(f"[{session_id}] [LYRICS] 🎸 Solo guitar detected — discarding Whisper lyrics")
            whisper_res = None

        # === Post-Processing (結果の統合) ===
        # 1. Beats
        if act is not None and beat_tracker is not None:
            beats_raw = beat_tracker(act)
        else:
            print(f"[{session_id}] [WARN] madmom beat_tracker unavailable, using librosa fallback")
            y_beat, sr_beat = librosa.load(str(wav_path), sr=22050)
            tempo, beat_frames = librosa.beat.beat_track(y=y_beat, sr=sr_beat)
            beats_raw = librosa.frames_to_time(beat_frames, sr=sr_beat)
        v_time = np.sort(np.array(beats_raw).astype(float))
        
        # 最初のビート位置を保存（フロントエンドのカーソル同期用）
        first_beat_time = float(v_time[0]) if len(v_time) > 0 else 0.0
        session_data["first_beat_time"] = first_beat_time
        session_data["beat_times"] = [float(t) for t in v_time]  # 全ビートタイムスタンプ
        print(f"[{session_id}] [SYNC] First beat at {first_beat_time:.3f}s, {len(v_time)} beats total")
        
        # HPS + Chroma + Chord 結果を展開
        sections = hps_result.get('sections', [])
        seg_starts = hps_result.get('seg_starts')
        seg_labels = hps_result.get('seg_labels')
        
        session_data["progress"] = "コードを判別中..."
        save_session(session_id)
        
        if seg_starts is None or seg_labels is None:
            print(f"[{session_id}] [WARN] chord_processor unavailable, using N.C. placeholders")
            seg_starts = v_time if len(v_time) > 0 else np.array([0.0])
            seg_labels = np.array(['N.C.'] * len(seg_starts))

        # 2. Key
        if key_vec is not None:
            idx = int(key_vec.argmax())
            KEYS = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'G#', 'A', 'Bb', 'B']
            root = KEYS[idx % 12]
            mode = "major" if (len(key_vec) == 12 or idx < 12) else "minor"
            session_data["key"] = f"{root} {mode}"
            
        # 3. Whisper (Lyrics) — 単語レベルで拍/小節に配置
        lyrics_data = []
        if whisper_res:
            segments = whisper_res.get('segments', [])
            perf_log.append(f"")
            perf_log.append(f"--- Lyrics mapping ---")
            perf_log.append(f"Whisper segments: {len(segments)}")
            
            # 単語レベルのタイムスタンプを抽出
            word_count = 0
            for seg in segments:
                words = seg.get('words', [])
                if words:
                    for w in words:
                        t = w['start']
                        text = w.get('word', '').strip()
                        if not text:
                            continue
                        if len(v_time) > 0:
                            beat_idx = int(np.searchsorted(v_time, t) - 1)
                            beat_idx = max(0, beat_idx)
                            bar = beat_idx // 4
                            beat = beat_idx % 4
                        else:
                            bar = 0
                            beat = 0
                        lyrics_data.append((bar, beat, round(w['start'], 3), round(w['end'], 3), text))
                        word_count += 1
                else:
                    t = seg['start']
                    if len(v_time) > 0:
                        beat_idx = int(np.searchsorted(v_time, t) - 1)
                        beat_idx = max(0, beat_idx)
                        bar = beat_idx // 4
                        beat = beat_idx % 4
                    else:
                        bar = 0
                        beat = 0
                    lyrics_data.append((bar, beat, round(seg['start'], 3), round(seg['end'], 3), seg['text'].strip()))
            
            perf_log.append(f"Lyrics mapped: {len(lyrics_data)} entries (words={word_count})")
            if lyrics_data:
                perf_log.append(f"First lyric: bar={lyrics_data[0][0]} beat={lyrics_data[0][1]} [{lyrics_data[0][4]}]")
        else:
            perf_log.append(f"")
            perf_log.append(f"--- Lyrics mapping ---")
            perf_log.append(f"[WARN] whisper_res is None — no lyrics detected")

        # 4. Chords (Dense Mapping with Beat Majority Voting)
        structured = []
        bpm = 120.0
        if len(v_time) > 1:
            intervals = np.diff(v_time)
            avg_interval = np.mean(intervals)
            if avg_interval > 0:
                bpm = 60.0 / avg_interval
        
        # === BPM 倍取り補正 ===
        raw_bpm = bpm
        if bpm > 200 and len(v_time) > 4:
            half_bpm = bpm / 2
            half_beats = v_time[::2]
            half_intervals = np.diff(half_beats)
            cv_half = np.std(half_intervals) / np.mean(half_intervals) if np.mean(half_intervals) > 0 else 999
            cv_full = np.std(intervals) / np.mean(intervals) if np.mean(intervals) > 0 else 999
            
            if cv_half < 0.25 and 60 <= half_bpm <= 160 and cv_half <= cv_full * 1.5:
                print(f"[{session_id}] [BPM] Half-tempo correction: {raw_bpm:.1f} → {half_bpm:.1f} BPM (CV: full={cv_full:.3f}, half={cv_half:.3f})")
                bpm = half_bpm
                v_time = list(half_beats)
                perf_log.append(f"BPM correction: {raw_bpm:.1f} → {half_bpm:.1f} (half-tempo, beats: {len(v_time)})")
            else:
                print(f"[{session_id}] [BPM] No half-tempo correction needed: {raw_bpm:.1f} BPM (CV: full={cv_full:.3f}, half={cv_half:.3f})")
        else:
            if bpm > 160:
                print(f"[{session_id}] [BPM] Tempo {raw_bpm:.1f} BPM is in fingerpicking range (160-200), no correction applied")
        
        session_data["bpm"] = round(bpm, 1)
        if "key" not in session_data:
            session_data["key"] = "C major"

        if seg_starts is not None and len(v_time) > 0:
            # Step 1: セグメントの平滑化（短いセグメントをマージ）
            seg_starts, seg_labels = _smooth_chord_segments(
                seg_starts, seg_labels, min_duration=0.4
            )
            
            # Step 2: ビートごとに多数決でコードを決定
            beat_chords = _beat_majority_chords(v_time, seg_starts, seg_labels)
            
            n_unique_raw = len(set(beat_chords) - {"N.C."})
            perf_log.append(f"Beat chords (raw from detection): {n_unique_raw} unique")
            
            # デバッグ: 生のコード一覧（最初の40ビート）
            preview_raw = beat_chords[:40]
            print(f"[{session_id}] [CHORD] Raw detected (first 40): {preview_raw}")
            
            for i, b_time in enumerate(v_time):
                bar = i // 4
                beat_in_bar = i % 4
                
                next_b_time = v_time[i+1] if i < len(v_time) - 1 else b_time + 0.5
                
                clean_chord = beat_chords[i]
                
                # 歌詞のマッピング
                matching_lyrics = []
                lyric_duration = 0.0
                for lyr in lyrics_data:
                    if lyr[0] == bar and lyr[1] == beat_in_bar:
                        matching_lyrics.append(lyr[4])
                        lyric_duration += (lyr[3] - lyr[2])
                
                # セグメントのマッピング
                section_label = ""
                for s_start, s_end, s_lbl in sections:
                    if s_start <= b_time < s_end:
                        section_label = s_lbl
                        break

                structured.append({
                    "bar": bar + 1, "beat": beat_in_bar + 1, "time": round(b_time, 3),
                    "duration": round(next_b_time - b_time, 3),
                    "chord": clean_chord or "N.C.",
                    "lyric": " ".join(matching_lyrics),
                    "lyric_duration": round(lyric_duration, 3),
                    "section": section_label
                })
        
        # --- Write beats.txt and chords.csv for /result endpoint ---
        beats_txt_path = session_dir / "beats.txt"
        np.savetxt(beats_txt_path, v_time, fmt="%.6f")
        
        chords_csv_path = session_dir / "chords.csv"
        with chords_csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bar", "beat", "start", "end", "chords", "clean_chord"])
            for r in structured:
                w.writerow([r['bar'], r['beat'], r['time'], r['time']+r['duration'], r['chord'], r['chord']])
        
        # --- Write lyrics_split.csv ---
        lyrics_csv_path = session_dir / "lyrics_split.csv"
        with lyrics_csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bar", "beat", "start", "end", "lyrics"])
            for lyr in lyrics_data:
                w.writerow([lyr[0]+1, lyr[1]+1, lyr[2], lyr[3], lyr[4]])
        # Whisperのフレーズ単位セグメントを保存
        lyrics_phrases = []
        if whisper_res:
            for seg in whisper_res.get('segments', []):
                text = seg.get('text', '').strip()
                if text:
                    lyrics_phrases.append({
                        "start": round(seg['start'], 3),
                        "end": round(seg['end'], 3),
                        "text": text
                    })

        # Janome形態素解析で自然な日本語の分割を行った表示用フレーズを生成
        display_phrases = lyrics_phrases
        try:
            from phrase_processor import process_phrases_for_display
            from lyrics_postprocess import clean_hallucinated_endings
            # ハルシネーション除去 → フレーズ分割
            cleaned_phrases = clean_hallucinated_endings(lyrics_phrases)
            display_phrases = process_phrases_for_display(cleaned_phrases, target_chars=30)
            perf_log.append(f"Display phrases: {len(display_phrases)} (from {len(lyrics_phrases)} raw, {len(cleaned_phrases)} after cleanup)")
        except Exception as e:
            perf_log.append(f"Warning: phrase_processor failed: {e}, using raw phrases")

        session_data["result"] = {
            "session_id": session_id,
            "key": sessions[session_id].get("key", "Unknown"),
            "structured_data": structured,
            "lyrics_phrases": lyrics_phrases,
            "display_phrases": display_phrases
        }
        
        # --- Post-processing summary ---
        lyrics_in_structured = sum(1 for s in structured if s.get('lyric'))
        perf_log.append(f"")
        perf_log.append(f"--- Post-processing summary ---")
        perf_log.append(f"Beats: {len(v_time)}")
        perf_log.append(f"Key: {session_data.get('key', 'Unknown')}")
        perf_log.append(f"BPM: {session_data.get('bpm', '?')}")
        perf_log.append(f"Structured entries: {len(structured)}")
        perf_log.append(f"Lyrics in structured: {lyrics_in_structured}/{len(structured)}")
        perf_log.append(f"Note events: {len(note_events)}")
        perf_log.append(f"Sections: {len(sections)}")

        # 4.5 キー推定（3層: chroma > コード進行 > madmom）
        if structured:
            madmom_key = session_data.get("key", "C major")
            
            # (1) 音声chromaベースのキー推定（最も信頼できる）
            chroma_key = estimate_key_from_audio(str(wav_path))
            
            # (2) コード進行からのキー推定
            chord_key = estimate_key_from_chords_fn(structured)
            
            # ログに3つの推定結果を出力
            print(f"[{session_id}] Key estimates: madmom={madmom_key}, chroma={chroma_key}, chord={chord_key}")
            
            # コンセンサス投票（五度圏距離ベース）
            final_key, method = key_consensus(madmom_key, chroma_key, chord_key)
            
            perf_log.append(f"Key estimates: madmom={madmom_key}, chroma={chroma_key}, chord={chord_key}")
            perf_log.append(f"Key selected: {final_key} ({method})")
            print(f"[{session_id}] Key selected: {final_key} ({method})")
            session_data["key"] = final_key
            
            # 推定キーで1回だけダイアトニック正規化
            raw_chords = [e["chord"] for e in structured]
            print(f"[{session_id}] [CHORD] Before normalize (first 40): {raw_chords[:40]}")
            
            normalized_chords = _normalize_chords_to_key(raw_chords, final_key)
            for i, entry in enumerate(structured):
                entry["chord"] = normalized_chords[i]
            
            n_unique_before = len(set(raw_chords) - {"N.C."})
            n_unique_after = len(set(normalized_chords) - {"N.C."})
            perf_log.append(f"Beat chords: {n_unique_before} raw → {n_unique_after} after normalization (key={final_key})")
            print(f"[{session_id}] [CHORD] After normalize (first 40): {normalized_chords[:40]}")
            print(f"[{session_id}] Chord normalization: {n_unique_before} → {n_unique_after} unique chords (key={final_key})")

        # 4.6 TABノート生成 — 楽曲タイプに応じて分岐
        if is_solo_guitar:
            chord_strum_notes = []
            tab_source_notes = note_events if note_events else []
            tab_data = notes_to_tab_data(tab_source_notes)
            print(f"[{session_id}] [TAB] Solo guitar mode: using {len(tab_source_notes)} detected notes for TAB")
            perf_log.append(f"TAB source: detected notes ({len(tab_source_notes)}) [solo_guitar]")
        else:
            chord_strum_notes = generate_chord_strum_notes(structured, bpm=bpm)
            tab_source_notes = chord_strum_notes
            tab_data = notes_to_tab_data(chord_strum_notes)
            print(f"[{session_id}] [TAB] Band mode: using {len(chord_strum_notes)} chord strum notes for TAB")
            perf_log.append(f"TAB source: chord strum ({len(chord_strum_notes)}) [band]")

        # Generate MusicXML
        session_data["progress"] = "MusicXML譜面を生成中..."
        save_session(session_id)
        detected_key = session_data.get("key", "C major")
        
        xml_notes = tab_source_notes if tab_source_notes else note_events
        xml_content = notes_to_musicxml(
            xml_notes, 
            beats=v_time,
            chords=structured,
            lyrics=lyrics_data,
            key=detected_key,
            title=session_data.get("filename", session_id),
            bpm=bpm,
        )
        
        # Save artifacts
        notes_json_path = session_dir / "notes.json"
        with open(notes_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "notes": note_events,
                "tab": tab_data,
                "song_type": song_type,
                "tab_source": "detected_notes" if is_solo_guitar else "chord_strum",
                "tab_source_count": len(tab_source_notes),
            }, f, indent=2)
            
        musicxml_path = session_dir / "sheet.musicxml"
        with open(musicxml_path, "w", encoding="utf-8") as f:
            f.write(xml_content)
            
        perf_log.append(f"MusicXML: generated (tab_source={len(tab_source_notes)}, basic_pitch={len(note_events)}, type={song_type})")
        session_data["has_notes"] = True
        
        # 5. Build Chord Sheet
        sheet_lines = [f"# {session_id} - NextChord Sheet", f"Key: {session_data.get('key', 'Unknown')}\n"]
        all_bars = sorted(list(set([r['bar'] for r in structured])))
        for bar in all_bars:
            b_chords = [r for r in structured if r['bar'] == bar]
            b_lyrics = [l for l in lyrics_data if l[0] == bar]
            ch_str = " | ".join([c['chord'] for c in b_chords if c['chord'] != "N.C."])
            ly_str = "".join([l[4] for l in b_lyrics])
            if ch_str: sheet_lines.append(f"[{bar:03d}] {ch_str}")
            if ly_str: sheet_lines.append(f"      {ly_str}")
            sheet_lines.append("")
        session_data["chord_sheet"] = "\n".join(sheet_lines)
        
        t_total = time.time() - start_total
        perf_log.append(f"")
        perf_log.append(f"=== TOTAL PIPELINE TIME: {t_total:.1f}s ===")
        print(f"[{session_id}] ★ TOTAL PIPELINE TIME: {t_total:.1f}s")
        
        # PERFログをファイルに書き出し
        perf_path = session_dir / "perf.log"
        with open(perf_path, "w", encoding="utf-8") as f:
            f.write("\n".join(perf_log) + "\n")
        print(f"[{session_id}] ★ perf.log saved to {perf_path}")
        
        session_data["status"] = SessionStatus.COMPLETED
        session_data["progress"] = "完了"
        save_session(session_id)
        
    except Exception as e:
        print(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        sessions[session_id]["status"] = SessionStatus.FAILED
        sessions[session_id]["error"] = str(e)
        save_session(session_id)
        print(f"[{session_id}] Pipeline failed. Kept for user review.")
