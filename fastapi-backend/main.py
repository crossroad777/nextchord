"""
NextChord FastAPI Backend
=========================
MP3ファイルをアップロードし、コード抽出パイプラインを実行するAPIサーバー

エンドポイント:
- POST /upload : MP3をアップロードしてコード解析を開始
- GET /status/{session_id} : 解析状況を取得
- GET /result/{session_id} : 解析結果を取得
"""

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager
import os
import sys
import uuid
import json
import shutil
import subprocess
import datetime as dt
import time
from typing import Optional, List
import concurrent.futures
from pathlib import Path
from enum import Enum
from dotenv import load_dotenv
import numpy as np

# NumPy 2.0+ patch for madmom
if not hasattr(np, 'int'): np.int = int
if not hasattr(np, 'float'): np.float = float
if not hasattr(np, 'complex'): np.complex = complex
if not hasattr(np, 'bool'): np.bool = bool

# --- Model Definitions (Initialize to None) ---
beat_processor = None
beat_tracker = None
key_processor = None
chroma_processor = None
chord_processor = None
whisper_model = None

import whisper
import librosa
import csv
import itertools
import re

try:
    from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
    from madmom.audio.chroma import DeepChromaProcessor
    from madmom.features.chords import DeepChromaChordRecognitionProcessor
    from madmom.features.key import CNNKeyRecognitionProcessor
except ImportError as e:
    import traceback
    print(f"Warning: madmom not available: {e}")
    traceback.print_exc()
    RNNBeatProcessor = None
    DBNBeatTrackingProcessor = None
    DeepChromaProcessor = None
    DeepChromaChordRecognitionProcessor = None
    CNNKeyRecognitionProcessor = None

try:
    from note_transcription import transcribe_notes, notes_to_summary, _band_score_filter
    from tab_generator import notes_to_tab_data, notes_to_musicxml, estimate_key_from_chords, generate_chord_strum_notes
except ImportError as e:
    import traceback
    print(f"Warning: note_transcription/tab_generator not available: {e}")
    traceback.print_exc()
    transcribe_notes = None
    _band_score_filter = None
    notes_to_tab_data = None
    notes_to_musicxml = None

import re

import time

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 環境変数を読み込み
load_dotenv(PROJECT_ROOT / ".env")

# FFMPEGパス
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

# 内部ライブラリ（madmom等）がffmpegを見つけられるよう、システムのPATHに追加
FFMPEG_BIN_DIR = str(Path(FFMPEG_PATH).parent)
if FFMPEG_BIN_DIR and FFMPEG_BIN_DIR not in os.environ["PATH"]:
    os.environ["PATH"] = FFMPEG_BIN_DIR + os.pathsep + os.environ["PATH"]

# Python パス
PYTHON_PATH = os.getenv("PYTHON_PATH", "python")

# yt-dlp パス
YT_DLP_PATH = os.getenv("YT_DLP_PATH", "yt-dlp")
if not shutil.which(YT_DLP_PATH):
    # venv内にあるか確認
    venv_yt = PROJECT_ROOT / "venv312" / "Scripts" / "yt-dlp.exe"
    if venv_yt.exists():
        YT_DLP_PATH = str(venv_yt)

print(f"Backend initializing. FFMPEG_PATH: {FFMPEG_PATH}, YT_DLP_PATH: {YT_DLP_PATH}")


# --- GLOBAL MODELS (WARM UP) ---
beat_processor = None
beat_tracker = None
key_processor = None
chroma_processor = None
chord_processor = None
whisper_model = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global beat_processor, beat_tracker, key_processor, chroma_processor, chord_processor, whisper_model
    print("Loading AI Models (Beats, Key, Chords, Whisper)...")
    try:
        # Load madmom models
        if RNNBeatProcessor:
            beat_processor = RNNBeatProcessor()
            beat_tracker = DBNBeatTrackingProcessor(fps=100)
            key_processor = CNNKeyRecognitionProcessor()
            chroma_processor = DeepChromaProcessor()
            chord_processor = DeepChromaChordRecognitionProcessor()
        else:
            print("WARNING: madmom not available. Skipping beat/chord/key models.")
        
        # Load whisper model (GPU自動検出)
        if whisper:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"🔥 PyTorch device: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))
            whisper_model = whisper.load_model("base", device=device)
            print(f"AI Models loaded successfully. Whisper on: {device}")
        else:
            print("WARNING: whisper not available. Skipping lyrics model.")
    except Exception as e:
        import traceback
        print("CRITICAL: Failed to load models in lifespan.")
        traceback.print_exc()
    
    load_all_sessions()
    yield

app = FastAPI(
    title="NextChord API",
    description="MP3からコード譜を自動生成するAPI",
    version="0.2.0",
    lifespan=lifespan
)

# CORS設定（React等からのアクセスを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ディレクトリ設定
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# セッション状態管理
class SessionStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

sessions: dict = {}

def save_session(session_id):
    """Save session data to session.json."""
    if session_id in sessions:
        session_dir = Path(sessions[session_id]["session_dir"])
        with open(session_dir / "session.json", "w", encoding="utf-8") as f:
            json.dump(sessions[session_id], f, ensure_ascii=False, indent=2)

def safe_remove(path: Path, retries=5, delay=0.5):
    """Attempt to remove a file with retries for Windows file lock issues."""
    if not path.exists():
        return
    for i in range(retries):
        try:
            os.remove(path)
            return
        except OSError:
            if i < retries - 1:
                time.sleep(delay)
            else:
                raise

def safe_rename(src: Path, dst: Path, retries=5, delay=0.5):
    """Attempt to rename a file with retries for Windows file lock issues."""
    for i in range(retries):
        try:
            if dst.exists() and src != dst:
                safe_remove(dst, retries=retries, delay=delay)
            if src != dst:
                src.rename(dst)
            return
        except OSError:
            if i < retries - 1:
                time.sleep(delay)
            else:
                raise
        except Exception as e:
            print(f"Failed to save session {session_id}: {e}")

# --- Session Cleanup Settings ---
SESSION_MAX_AGE_DAYS = 7      # これより古いセッションは起動時に自動削除
SESSION_MAX_COUNT = 20        # メモリに保持する最大セッション数

def cleanup_session_dir(s_dir: Path):
    """セッションディレクトリを安全に削除する"""
    try:
        shutil.rmtree(str(s_dir), ignore_errors=True)
        print(f"  [CLEANUP] Deleted: {s_dir.name}")
    except Exception as e:
        print(f"  [CLEANUP] Failed to delete {s_dir.name}: {e}")

def load_all_sessions():
    global sessions
    if not UPLOAD_DIR.exists(): return
    
    all_sessions = []
    deleted_old = 0
    deleted_failed = 0
    deleted_orphan = 0
    now = dt.datetime.now()
    
    for s_dir in UPLOAD_DIR.iterdir():
        if not s_dir.is_dir():
            continue
        s_file = s_dir / "session.json"
        
        # session.jsonが無いディレクトリは孤立データとして削除
        if not s_file.exists():
            cleanup_session_dir(s_dir)
            deleted_orphan += 1
            continue
        
        try:
            with open(s_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            cleanup_session_dir(s_dir)
            deleted_orphan += 1
            continue
        
        # 1. 失敗セッションは起動時には読み込まない（またはクリーンアップ）
        # ただし、実行中のままサーバーが落ちたものは failed にして保存し直す
        current_status = data.get("status")
        if current_status in [SessionStatus.PENDING, SessionStatus.PROCESSING]:
            data["status"] = SessionStatus.FAILED
            data["error"] = "サーバー再起動により解析が中断されました。"
            data["progress"] = "中断"
            # 更新して保存
            with open(s_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 破棄せず読み込みを続行
            # cleanup_session_dir(s_dir)
            # deleted_failed += 1
            # continue

        # 失敗セッションも破棄せず読み込み対象にする
        # if current_status == SessionStatus.FAILED:
        #     cleanup_session_dir(s_dir)
        #     deleted_failed += 1
        #     continue
        
        # 2. 古いセッションを削除（ディレクトリ名の日付 or ファイル更新日時で判定）
        try:
            # ディレクトリ名が "YYYYMMDD-HHMMSS-xxx" 形式
            dir_date_str = s_dir.name[:15]  # "20260204-152435"
            dir_date = dt.datetime.strptime(dir_date_str, "%Y%m%d-%H%M%S")
            age_days = (now - dir_date).days
        except (ValueError, IndexError):
            # 日付パースに失敗した場合はファイルの更新日時を使用
            age_days = (now - dt.datetime.fromtimestamp(s_file.stat().st_mtime)).days
        
        if age_days > SESSION_MAX_AGE_DAYS:
            cleanup_session_dir(s_dir)
            deleted_old += 1
            continue
        
        data["session_dir"] = str(s_dir)
        data["_age_days"] = age_days
        all_sessions.append((s_dir.name, data))
    
    # 3. 最新のセッションのみ保持（SESSION_MAX_COUNT件まで）
    # 新しいものが先に来るようにソート
    all_sessions.sort(key=lambda x: x[0], reverse=True)
    
    deleted_overflow = 0
    for i, (sid, data) in enumerate(all_sessions):
        if i < SESSION_MAX_COUNT:
            data.pop("_age_days", None)
            sessions[sid] = data
        else:
            cleanup_session_dir(Path(data["session_dir"]))
            deleted_overflow += 1
    
    kept = min(len(all_sessions), SESSION_MAX_COUNT)
    print(f"[SESSION CLEANUP] Kept: {kept}, Deleted: old={deleted_old}, failed={deleted_failed}, orphan={deleted_orphan}, overflow={deleted_overflow}")


# レスポンスモデル
class UploadResponse(BaseModel):
    session_id: str
    message: str
    status: SessionStatus
    audio_url: Optional[str] = None

class StatusResponse(BaseModel):
    session_id: str
    status: SessionStatus
    progress: Optional[str] = None
    error: Optional[str] = None
    filename: Optional[str] = None
    artist: Optional[str] = None
    first_beat_time: Optional[float] = None
    beat_times: Optional[list] = None

class ResultResponse(BaseModel):
    session_id: str
    status: SessionStatus
    key: Optional[str] = None
    bpm: Optional[float] = None
    filename: Optional[str] = None
    artist: Optional[str] = None
    chord_sheet: Optional[str] = None
    chords_csv_url: Optional[str] = None
    lyrics_csv_url: Optional[str] = None
    structured_data: Optional[list] = None
    lyrics_phrases: Optional[list] = None
    display_phrases: Optional[list] = None
    has_notes: Optional[bool] = False

class YouTubeRequest(BaseModel):
    url: str

# =========================================================================
# コード処理・キー推定 (chord_processing.py に分離)
# =========================================================================
from chord_processing import (
    analyze_sections,
    standardized_key,
    standardize_chord,
    _smooth_chord_segments,
    _beat_majority_chords,
    _normalize_chords_to_key,
    estimate_key_from_audio,
    detect_song_type,
    key_consensus,
    _ENHARMONIC_MAP,
    _ENHARMONIC_FLAT_MAP,
    _FLAT_KEYS,
)



from pipeline import run_pipeline as _run_pipeline_impl


def run_pipeline(session_id: str, session_dir: Path, wav_path: Path):
    """パイプライン実行 (pipeline.py に委譲)"""
    ctx = {
        "sessions": sessions,
        "save_session": save_session,
        "SessionStatus": SessionStatus,
        "beat_processor": beat_processor,
        "beat_tracker": beat_tracker,
        "key_processor": key_processor,
        "chroma_processor": chroma_processor,
        "chord_processor": chord_processor,
        "whisper_model": whisper_model,
        "transcribe_notes": transcribe_notes,
        "notes_to_tab_data": notes_to_tab_data,
        "notes_to_musicxml": notes_to_musicxml,
        "estimate_key_from_chords": estimate_key_from_chords,
        "generate_chord_strum_notes": generate_chord_strum_notes,
    }
    _run_pipeline_impl(session_id, session_dir, wav_path, ctx)

@app.post("/upload", response_model=UploadResponse)
async def upload_audio(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    MP3ファイルをアップロードしてコード解析を開始
    """
    # ファイル形式チェック
    if not file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.flac')):
        raise HTTPException(status_code=400, detail="サポートされるファイル形式: MP3, WAV, M4A, FLAC")
    
    # セッション作成
    session_id = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    
    # ファイル保存
    input_path = session_dir / f"input{Path(file.filename).suffix}"
    with open(input_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # WAVに変換（必要な場合）
    wav_path = session_dir / "converted.wav"
    try:
        subprocess.run(
            [FFMPEG_PATH, "-y", "-i", str(input_path), str(wav_path)],
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"音声変換に失敗しました: {e.stderr.decode() if e.stderr else str(e)}")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="ffmpegがインストールされていません")
    
    # セッション情報を初期化
    sessions[session_id] = {
        "status": SessionStatus.PENDING,
        "session_dir": str(session_dir),
        "wav_path": str(wav_path),
        "progress": "アップロード完了",
        "key": None,
        "chord_sheet": None,
        "is_separating": False,
        "separation_progress": "未開始",
        "error": None
    }
    
    # バックグラウンドでパイプライン実行
    background_tasks.add_task(run_pipeline, session_id, session_dir, wav_path)
    
    return UploadResponse(
        session_id=session_id,
        message="アップロード成功。解析を開始しました。",
        status=SessionStatus.PENDING,
        audio_url=f"/files/{session_id}/converted.wav"
    )

def download_youtube_audio(url: str, output_dir: Path) -> tuple:
    """Download audio from YouTube using yt-dlp. Returns (audio_path, metadata_dict)."""
    # タイトルとアーティスト名を取得
    meta = {"title": "YouTube Video", "artist": ""}
    try:
        info_cmd = [
            YT_DLP_PATH, "--no-playlist", "--no-warnings",
            "--print", "%(title)s\n%(artist,uploader)s",
            url
        ]
        info_result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=15)
        if info_result.returncode == 0 and info_result.stdout.strip():
            lines = info_result.stdout.strip().split("\n")
            if len(lines) >= 1 and lines[0].strip():
                meta["title"] = lines[0].strip()
            if len(lines) >= 2 and lines[1].strip() and lines[1].strip() != "NA":
                meta["artist"] = lines[1].strip()
            print(f"[YouTube] Title: {meta['title']}, Artist: {meta['artist']}")
    except Exception as e:
        print(f"[YouTube] Could not get metadata: {e}")
    
    # Use a separate temporary name for downloading to avoid lock/collision with converted.wav
    temp_name = "download_temp"
    output_path = output_dir / temp_name
    
    # yt-dlp コマンド
    cmd = [
        YT_DLP_PATH,
        "--no-playlist",
        "--no-warnings", # Suppress benign runtime warnings
        "-x",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "-o", str(output_path) + ".%(ext)s",
        url
    ]
    
    print(f"Downloading YouTube audio (temp): {url}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"yt-dlp error: {result.stderr}")
        raise Exception(f"YouTube download failed: {result.stderr}")
    
    # Windowsでファイルロックが発生する場合があるため、待機
    time.sleep(1)
    
    # 保存されたファイルを確認
    wav_path = output_dir / f"{temp_name}.wav"
    if wav_path.exists():
        return wav_path, meta
    
    # 他の形式で保存された可能性を確認
    for f in output_dir.glob(f"{temp_name}.*"):
        if f.suffix.lower() in [".mp3", ".m4a", ".webm", ".opus", ".wav"]:
            return f, meta
            
    raise FileNotFoundError("Could not find downloaded YouTube audio file.")

@app.post("/upload/youtube", response_model=UploadResponse)
async def upload_youtube(background_tasks: BackgroundTasks, request: YouTubeRequest):
    """
    YouTube URLを受け取って解析を開始
    """
    url = request.url
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
        
    session_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + "yt-" + uuid.uuid4().hex[:6]
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    
    # セッション情報を初期化
    sessions[session_id] = {
        "status": SessionStatus.PENDING,
        "session_dir": str(session_dir),
        "filename": "YouTube Video",
        "url": url,
        "progress": "YouTube音声をダウンロード中...",
        "key": None,
        "chord_sheet": None,
        "is_separating": False,
        "separation_progress": "未開始",
        "error": None
    }
    save_session(session_id)
    
    def process_youtube():
        try:
            # 1. YouTubeからダウンロード（メタデータも取得）
            audio_path, yt_meta = download_youtube_audio(url, session_dir)
            sessions[session_id]["filename"] = yt_meta["title"]
            sessions[session_id]["artist"] = yt_meta.get("artist", "")
            save_session(session_id)
            
            # 2. 必要に応じてWAVに変換/確定 (converted.wavに統一)
            final_wav = session_dir / "converted.wav"
            
            if audio_path.suffix.lower() != ".wav":
                temp_wav = session_dir / "ffmpeg_temp.wav"
                subprocess.run([FFMPEG_PATH, "-y", "-i", str(audio_path), str(temp_wav)], check=True)
                safe_rename(temp_wav, final_wav)
                safe_remove(audio_path)
            else:
                # すでにwavなら配置
                safe_rename(audio_path, final_wav)
            
            sessions[session_id]["wav_path"] = str(final_wav)
            sessions[session_id]["progress"] = "ダウンロード完了。解析を開始します..."
            save_session(session_id)
            
            # 3. 解析パイプラインを実行
            run_pipeline(session_id, session_dir, final_wav)
        except Exception as e:
            print(f"YouTube processing failed: {e}")
            import traceback
            traceback.print_exc()
            sessions[session_id]["status"] = SessionStatus.FAILED
            sessions[session_id]["error"] = f"YouTube解析エラー: {str(e)}"
            save_session(session_id)
            
    background_tasks.add_task(process_youtube)
    
    return UploadResponse(
        session_id=session_id,
        message="YouTubeダウンロードと解析を開始しました。",
        status=SessionStatus.PENDING
    )


@app.post("/separate/{session_id}")
async def trigger_separation(session_id: str, background_tasks: BackgroundTasks):
    """
    AI音源分離 (Demucs) を手動で実行
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    
    session = sessions[session_id]
    session_dir = Path(session["session_dir"])
    wav_path = Path(session["wav_path"])
    clean_wav_path = session_dir / "clean.wav"

    if clean_wav_path.exists():
        return {"session_id": session_id, "status": "exists", "message": "すでに分離済みです"}
    
    if session.get("is_separating"):
        return {"session_id": session_id, "status": "processing", "message": "分離処理中です"}

    session["is_separating"] = True
    session["separation_progress"] = "分離開始..."
    
    background_tasks.add_task(run_separation, session_id, session_dir, wav_path)
    
    return {"session_id": session_id, "status": "started", "message": "音源分離を開始しました"}


def run_separation(session_id: str, session_dir: Path, wav_path: Path):
    """
    音源分離 (Demucs) をバックグラウンドで実行
    """
    try:
        sessions[session_id]["separation_progress"] = "AI音源分離中 (Demucs)..."
        clean_wav_path = session_dir / "clean.wav"
        
        subprocess.run(
            [PYTHON_PATH, str(PROJECT_ROOT / "step0_separate_sources.py"), 
             str(wav_path), str(session_dir), str(clean_wav_path)],
            check=True,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            env={"PYTHONIOENCODING": "utf-8", **os.environ}
        )
        
        sessions[session_id]["separation_progress"] = "分離完了"
        sessions[session_id]["is_separating"] = False
        sessions[session_id]["has_clean_audio"] = True
        
    except Exception as e:
        print(f"Demucs separation failed: {e}")
        sessions[session_id]["is_separating"] = False
        sessions[session_id]["separation_error"] = str(e)


@app.get("/sessions")
async def get_sessions_list():
    """
    メモリに保持されているセッション一覧を返す（最新20件）
    """
    history = []
    # sessionsは辞書なので、session_id降順でソートしてリスト化
    sorted_ids = sorted(sessions.keys(), reverse=True)
    for sid in sorted_ids:
        s = sessions[sid]
        history.append({
            "session_id": sid,
            "filename": s.get("fileName") or s.get("filename") or "Unknown",
            "status": s.get("status"),
            "key": s.get("key"),
            "created_at": sid[:15] if len(sid) >= 15 else "" # YYYYMMDD-HHMMSS
        })
    return history


@app.get("/status/separation/{session_id}")
async def get_separation_status(session_id: str):
    """
    音源分離の状況を個別に取得
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    
    session = sessions[session_id]
    return {
        "session_id": session_id,
        "is_separating": session.get("is_separating", False),
        "progress": session.get("separation_progress", "未開始"),
        "has_clean_audio": (Path(session["session_dir"]) / "htdemucs").exists(),
        "error": session.get("separation_error")
    }


@app.post("/reanalyze/{session_id}")
async def reanalyze_guitar(session_id: str, background_tasks: BackgroundTasks):
    """
    分離されたギター音源 (other.wav) を使用して転記を再実行する
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    
    session = sessions[session_id]
    session_dir = Path(session["session_dir"])
    
    # Demucsの出力から guitar (other) を探す
    # 構造: session_dir / htdemucs / {song_name} / other.wav
    ht_dir = session_dir / "htdemucs"
    if not ht_dir.exists():
        raise HTTPException(status_code=400, detail="音源分離が完了していません。先に分離を実行してください。")
    
    # 実際のディレクトリ名（曲名）を取得
    song_dirs = list(ht_dir.iterdir())
    if not song_dirs:
        raise HTTPException(status_code=400, detail="分離データが見つかりません")
    
    guitar_wav = song_dirs[0] / "other.wav"
    if not guitar_wav.exists():
        raise HTTPException(status_code=400, detail="ギター音源 (other.wav) が見つかりません")
    
    session["status"] = SessionStatus.PENDING
    session["progress"] = "ギター音源を解析中 (Deep Analysis)..."
    session["is_deep_analysis"] = True
    # guitar_wav_path を保存して note_transcription に渡す
    session["guitar_wav_path"] = str(guitar_wav)
    save_session(session_id)
    
    # ★ 重要: Whisper/Beats/Key は元のフル音源 (converted.wav) で実行
    #    Notes だけ guitar_wav を direct に使う
    original_wav = session_dir / "converted.wav"
    if not original_wav.exists():
        # fallback: session に保存されている wav_path を使う
        original_wav = Path(session.get("wav_path", str(session_dir / "converted.wav")))
    
    print(f"[reanalyze] session={session_id}")
    print(f"[reanalyze] original_wav={original_wav} (exists={original_wav.exists()})")
    print(f"[reanalyze] guitar_wav={guitar_wav} (exists={guitar_wav.exists()})")
    
    background_tasks.add_task(run_pipeline, session_id, session_dir, original_wav)
    
    return {"session_id": session_id, "status": "started", "message": "Deep Analysis (Guitar Isolation) を開始しました"}


@app.get("/status/{session_id}", response_model=StatusResponse)
async def get_status(session_id: str):
    """
    解析状況を取得
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    
    session = sessions[session_id]
    return StatusResponse(
        session_id=session_id,
        status=session["status"],
        progress=session.get("progress"),
        error=session.get("error"),
        filename=session.get("filename"),
        artist=session.get("artist"),
        first_beat_time=session.get("first_beat_time"),
        beat_times=session.get("beat_times")
    )


@app.get("/status/{session_id}/stream")
async def stream_status(session_id: str):
    """
    SSE (Server-Sent Events) で解析進捗をリアルタイム配信。
    ポーリングの代替。completion/failureで自動終了。
    """
    import asyncio
    from starlette.responses import StreamingResponse

    async def event_generator():
        last_progress = None
        while True:
            if session_id not in sessions:
                yield f"data: {json.dumps({'status': 'not_found', 'error': 'セッションが見つかりません'})}\n\n"
                return

            session = sessions[session_id]
            current = {
                "status": session.get("status", "pending"),
                "progress": session.get("progress", ""),
                "filename": session.get("filename"),
                "artist": session.get("artist"),
            }

            # 変化があった場合のみ送信
            progress_key = f"{current['status']}:{current['progress']}"
            if progress_key != last_progress:
                yield f"data: {json.dumps(current, ensure_ascii=False)}\n\n"
                last_progress = progress_key

            # 完了・失敗で終了
            if current["status"] in ("completed", "failed"):
                if current["status"] == "failed":
                    current["error"] = session.get("error", "")
                    yield f"data: {json.dumps(current, ensure_ascii=False)}\n\n"
                return

            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



@app.get("/result/{session_id}/text")
def get_text_result(session_id: str):
    """
    解析結果をテキスト形式（コード譜）で取得
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    
    session = sessions[session_id]
    if session["status"] != SessionStatus.COMPLETED or not session.get("result"):
         raise HTTPException(status_code=400, detail="解析が完了していません")
         
    structured_data = session["result"]["structured_data"]
    
    # Generate text
    try:
        from export_utils import create_text_score
        text_score = create_text_score(structured_data)
        return Response(content=text_score, media_type="text/plain")
    except Exception as e:
        print(f"Text generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/result/{session_id}", response_model=ResultResponse)
async def get_result(session_id: str):
    """
    解析結果を取得 (保存された高精度な構造化データを返す)
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    
    session = sessions[session_id]
    
    if session["status"] == SessionStatus.FAILED:
        raise HTTPException(status_code=500, detail=session.get("error", "不明なエラー"))
    
    if session["status"] != SessionStatus.COMPLETED:
        raise HTTPException(status_code=202, detail="まだ解析中です")
    
    # run_pipelineで計算済みのデータを取得
    result = session.get("result", {})
    structured_data = result.get("structured_data", [])
    
    # 万が一データが空の場合のみ、最低限のフォールバック (通常は通らない)
    if not structured_data:
        print(f"Warning: structured_data missing in session {session_id}, check extraction pipeline.")

    # display_phrasesがない既存セッションの場合、リアルタイムでJanome処理
    display_phrases = result.get("display_phrases", [])
    if not display_phrases:
        lyrics_phrases = result.get("lyrics_phrases", [])
        if lyrics_phrases:
            try:
                from phrase_processor import process_phrases_for_display
                display_phrases = process_phrases_for_display(lyrics_phrases, target_chars=30)
                # キャッシュ
                result["display_phrases"] = display_phrases
            except Exception as e:
                print(f"Warning: phrase_processor failed for {session_id}: {e}")

    return ResultResponse(
        session_id=session_id,
        status=session["status"],
        key=session.get("key"),
        bpm=session.get("bpm"),
        filename=session.get("filename"),
        artist=session.get("artist"),
        chord_sheet=session.get("chord_sheet"),
        chords_csv_url=f"/files/{session_id}/chords.csv",
        lyrics_csv_url=f"/files/{session_id}/lyrics_split.csv",
        structured_data=structured_data,
        lyrics_phrases=result.get("lyrics_phrases", []),
        display_phrases=display_phrases,
        has_notes=session.get("has_notes", False)
    )

@app.patch("/result/{session_id}/chords")
async def update_chords(session_id: str, request: Request):
    """
    コードを部分的に更新する（手動編集用）
    Body: { "edits": [{ "index": 0, "chord": "Am" }, ...] }
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    body = await request.json()
    edits = body.get("edits", [])
    if not edits:
        return {"status": "no changes"}

    session = sessions[session_id]
    session_dir = Path(session["session_dir"])

    # structured_dataを読み込み
    structured_data = await _get_structured_data(session_id)
    if not structured_data:
        raise HTTPException(status_code=404, detail="No structured data found")

    # 編集を適用
    changed = 0
    for edit in edits:
        idx = edit.get("index")
        new_chord = edit.get("chord")
        if idx is not None and 0 <= idx < len(structured_data) and new_chord is not None:
            structured_data[idx]["chord"] = new_chord
            changed += 1

    # 保存（structured_data.jsonに書き込み）
    sd_path = session_dir / "structured_data.json"
    with open(sd_path, "w", encoding="utf-8") as f:
        json.dump(structured_data, f, ensure_ascii=False, indent=2)

    logger.info(f"[{session_id}] Updated {changed} chord(s)")
    return {"status": "ok", "changed": changed}

@app.patch("/result/{session_id}/lyrics")
async def update_lyrics(session_id: str, request: Request):
    """
    歌詞を部分的に更新する（手動編集用）
    Body: { "display_phrases": [{ "start": 1.0, "end": 2.0, "text": "..." }, ...] }
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    body = await request.json()
    new_phrases = body.get("display_phrases", [])
    if not new_phrases:
        return {"status": "no changes"}

    session = sessions[session_id]
    session_dir = Path(session["session_dir"])

    # session.json を更新
    session_json_path = session_dir / "session.json"
    if session_json_path.exists():
        with open(session_json_path, "r", encoding="utf-8") as f:
            session_data = json.load(f)
    else:
        session_data = session

    # display_phrases を更新
    if "result" not in session_data:
        session_data["result"] = {}
    session_data["result"]["display_phrases"] = new_phrases

    # メモリ上のセッションも更新
    if "result" in session:
        session["result"]["display_phrases"] = new_phrases

    with open(session_json_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    logger.info(f"[{session_id}] Updated lyrics ({len(new_phrases)} phrases)")
    return {"status": "ok", "phrases": len(new_phrases)}

@app.get("/result/{session_id}/notes")
async def get_notes(session_id: str):
    """
    音符データ(JSON)を取得
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[session_id]
    session_dir = Path(session["session_dir"])
    notes_path = session_dir / "notes.json"
    
    if not notes_path.exists():
        return {"notes": [], "tab": []}
        
    with open(notes_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    return data

@app.get("/result/{session_id}/musicxml")
async def get_musicxml_content(session_id: str):
    """
    MusicXMLのコンテンツをテキストで取得 (alphaTab表示用)
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[session_id]
    session_dir = Path(session["session_dir"])
    xml_path = session_dir / "sheet.musicxml"
    
    if not xml_path.exists():
        raise HTTPException(status_code=404, detail="MusicXML not generated")
        
    with open(xml_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    return Response(content=content, media_type="application/xml")

@app.get("/export/{session_id}/musicxml")
async def export_musicxml(session_id: str):
    """
    MusicXMLファイルをダウンロード
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[session_id]
    session_dir = Path(session["session_dir"])
    xml_path = session_dir / "sheet.musicxml"
    
    if not xml_path.exists():
        raise HTTPException(status_code=404, detail="MusicXML not generated")
        
    return FileResponse(xml_path, filename=f"nextchord_{session_id}.musicxml")


@app.get("/files/{session_id}/{filename}")
async def get_file(session_id: str, filename: str):
    """
    セッションのファイルをダウンロード
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    
    session_dir = Path(sessions[session_id]["session_dir"])
    file_path = session_dir / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")
    
    return FileResponse(file_path, filename=filename)


# ------------------------------------------------------------------
# Export Endpoints
# ------------------------------------------------------------------
from export_utils import create_midi, create_pdf

@app.get("/export/{session_id}/midi")
async def export_midi(session_id: str):
    """
    MIDIファイルを生成してダウンロード
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[session_id]
    if not session.get("status") == SessionStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Analysis not completed")
        
    session_dir = Path(session["session_dir"])
    midi_path = session_dir / "chords.mid"
    
    data = await _get_structured_data(session_id)
    
    # セッション情報を取得
    bpm = session.get("bpm", 120)
    key = session.get("key", None)
    
    # ノートデータを読み込み（存在すれば第2トラックに追加）
    notes_data = None
    notes_path = session_dir / "notes.json"
    if notes_path.exists():
        try:
            import json
            raw = json.loads(notes_path.read_text(encoding="utf-8"))
            # notes.json は {"notes": [...], "song_type": ...} 形式
            notes_data = raw.get("notes", raw) if isinstance(raw, dict) else raw
        except Exception:
            pass
    
    create_midi(data, midi_path, bpm=bpm, key=key, notes_data=notes_data)
    
    fname = session.get("filename", session_id)
    fname_stem = Path(fname).stem if fname else session_id
    return FileResponse(midi_path, filename=f"{fname_stem}.mid")

@app.get("/export/{session_id}/pdf")
async def export_pdf(session_id: str):
    """
    PDFファイルを生成してダウンロード
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[session_id]
    if not session.get("status") == SessionStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Analysis not completed")
        
    session_dir = Path(session["session_dir"])
    pdf_path = session_dir / "sheet.pdf"
    
    data = await _get_structured_data(session_id)
    
    # セッション情報を取得
    bpm = session.get("bpm", None)
    key = session.get("key", None)
    filename = session.get("filename", None)
    
    create_pdf(data, pdf_path, title="Chord Sheet",
               key=key, bpm=bpm, filename=filename)
    
    fname = session.get("filename", session_id)
    fname_stem = Path(fname).stem if fname else session_id
    return FileResponse(pdf_path, filename=f"{fname_stem}.pdf")


async def _get_structured_data(session_id):
    # Re-using logic from get_result... careful with consistency.
    #Ideally we refactor. For now, copy-paste-modify slightly or call the function?
    # Calling the function `get_result` directly is okay if we change it to return Py object not response.
    # But `get_result` returns ResultResponse.
    
    res = await get_result(session_id)
    return res.structured_data

from waveform_utils import generate_waveform

@app.get("/result/{session_id}/waveform")
async def get_waveform(session_id: str):
    """
    波形データを取得 (2000 points)
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sessions[session_id]
    session_dir = Path(session["session_dir"])
    
    # Use converted.wav (original audio) for visualization
    # Or clean.wav? Usually users want to see the main audio.
    wav_path = Path(session["wav_path"])
    
    # Check cache or generate on fly? 
    # Generating on fly might be slow (1sec for 5min song).
    # Return JSON directly.
    
    data = generate_waveform(str(wav_path), n_points=2000)
    return data

@app.get("/health")
async def health_check():
    """
    ヘルスチェック
    """
    return {"status": "healthy", "version": "0.4.0", "demucs": "enabled"}


def run_pipeline_with_save(session_id: str, session_dir: Path, wav_path: Path):
    try:
        run_pipeline(session_id, session_dir, wav_path)
    finally:
        save_session(session_id)

# --- Frontend Static File Serving (Production / HF Spaces) ---
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend-dist"
if FRONTEND_DIR.exists():
    from starlette.responses import HTMLResponse
    # 静的アセット (js, css, images, fonts) を配信
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="static-assets")
    # public ディレクトリのファイル (favicon, fonts, soundfont 等)
    for sub in ["font", "soundfont"]:
        sub_dir = FRONTEND_DIR / sub
        if sub_dir.exists():
            app.mount(f"/{sub}", StaticFiles(directory=str(sub_dir)), name=f"static-{sub}")
    
    # SPA catch-all: API以外のリクエストは index.html を返す
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # APIパスは除外（既にルーティング済み）
        file_path = FRONTEND_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return HTMLResponse((FRONTEND_DIR / "index.html").read_text())
    
    print(f"✅ Frontend serving from: {FRONTEND_DIR}")
else:
    print(f"ℹ️ No frontend-dist found at {FRONTEND_DIR} (development mode)")

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
