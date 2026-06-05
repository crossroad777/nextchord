"""
NextChord FastAPI Backend
=========================
MP3ファイルをアップロードし、コード抽出パイプラインを実行するAPIサーバー

エンドポイント:
- POST /upload : MP3をアップロードしてコード解析を開始
- GET /status/{session_id} : 解析状況を取得
- GET /result/{session_id} : 解析結果を取得
"""

# cuDNN無効化: CTranslate2(faster-whisper)とPyTorch cuDNN 9の
# DLLシンボル競合 (cudnnGetLibConfig) によるクラッシュを回避
import torch
torch.backends.cudnn.enabled = False

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager
import os
import sys
if sys.platform == 'win32':
    import asyncio.proactor_events
    _original_call_connection_lost = asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost
    def _patched_call_connection_lost(self, exc):
        try:
            _original_call_connection_lost(self, exc)
        except ConnectionResetError:
            pass
    asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost

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

import asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
if not hasattr(np, 'complex'): np.complex = complex
if not hasattr(np, 'bool'): np.bool = bool

# --- Model Definitions (Initialize to None) ---
beat_processor = None
beat_tracker = None
key_processor = None
chroma_processor = None
chord_processor = None
whisper_model = None

try:
    from faster_whisper import WhisperModel as FasterWhisperModel
    _use_faster_whisper = True
    print("Using faster-whisper (CTranslate2 backend)")
except ImportError:
    import whisper
    _use_faster_whisper = False
    print("Using openai-whisper (fallback)")
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
    from tab_generator import TUNING_PRESETS
except ImportError as e:
    import traceback
    print(f"Warning: note_transcription/tab_generator not available: {e}")
    traceback.print_exc()
    transcribe_notes = None
    _band_score_filter = None
    notes_to_tab_data = None
    notes_to_musicxml = None
    TUNING_PRESETS = {}

try:
    from gp5_export import notes_to_gp5
except ImportError as e:
    print(f"Warning: gp5_export not available: {e}")
    notes_to_gp5 = None

import re

import time

# --- Audio Metadata Extraction ---
try:
    import mutagen
    from mutagen.easyid3 import EasyID3
    from mutagen.mp4 import MP4
    from mutagen.flac import FLAC as MutagenFLAC
    _has_mutagen = True
except ImportError:
    _has_mutagen = False
    print("Warning: mutagen not available. Metadata extraction disabled.")


def _clean_filename(filename: str) -> str:
    """ファイル名からカタログ番号的なプレフィックスや拡張子を除去して表示名にする"""
    name = Path(filename).stem
    # Remove long numeric prefixes (e.g. "1234567890 - Song Title" or "1234567890_Song")
    name = re.sub(r'^\d{6,}[\s_\-]+', '', name)
    # Remove leading/trailing whitespace and underscores
    name = name.strip(' _-')
    return name if name else Path(filename).stem


def extract_audio_metadata(file_path: Path) -> dict:
    """mutagenを使ってオーディオファイルからtitle/artistメタデータを抽出する"""
    result = {"title": None, "artist": None}
    if not _has_mutagen:
        return result
    try:
        audio = mutagen.File(file_path, easy=True)
        if audio is None:
            return result

        # easy=True works for ID3 (MP3), FLAC, OGG etc.
        # For MP4/M4A, easy mode maps '\xa9nam' -> 'title', '\xa9ART' -> 'artist'
        title_val = audio.get("title")
        artist_val = audio.get("artist")

        if title_val:
            result["title"] = title_val[0].strip() if isinstance(title_val, list) else str(title_val).strip()
        if artist_val:
            result["artist"] = artist_val[0].strip() if isinstance(artist_val, list) else str(artist_val).strip()

        # Filter out empty strings
        if result["title"] == "":
            result["title"] = None
        if result["artist"] == "":
            result["artist"] = None

        print(f"[Metadata] title={result['title']}, artist={result['artist']} from {file_path.name}")
    except Exception as e:
        print(f"[Metadata] Failed to extract from {file_path.name}: {e}")
    return result

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
        
        # Load whisper model (GPU自動検出 + 環境変数対応)
        import torch
        import os
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[FIRE] PyTorch device: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else ""))
        # 日本語認識精度維持のためデフォルトは "medium"。環境変数で変更可能。
        whisper_size = os.getenv("WHISPER_MODEL_SIZE", "medium")
        
        if _use_faster_whisper:
            compute_type = "float16" if device == "cuda" else "int8"
            # CPU環境(2 vCPU)でのスレッド競合を防ぎ、動作を高速化するために cpu_threads=2 を指定
            cpu_threads = 2 if device == "cpu" else 4
            whisper_model = FasterWhisperModel(
                whisper_size, 
                device=device, 
                compute_type=compute_type,
                cpu_threads=cpu_threads
            )
            print(f"AI Models loaded. faster-whisper '{whisper_size}' on {device} ({compute_type})")
        else:
            whisper_model = whisper.load_model(whisper_size, device=device)
            print(f"AI Models loaded. openai-whisper '{whisper_size}' on {device}")
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

# CORS設定（Vercel + ローカル開発を許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nextchord-ui.vercel.app",
        "https://nextchord-ui-kotaros-projects-9e219ca4.vercel.app",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"https://nextchord-.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
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
            print(f"Failed to rename {src} -> {dst}: {e}")
            raise

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
    steps_done: Optional[int] = None
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
    chordpro_text: Optional[str] = None
    beat_times: Optional[list] = None
    downbeats: Optional[list] = None
    bar_positions: Optional[list] = None
    beats_per_bar: Optional[int] = None
    chordpro_line_timings: Optional[list] = None

class YouTubeRequest(BaseModel):
    url: str
    cookies: Optional[str] = None

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
    
    # メタデータ抽出 (ID3 / MP4 / FLAC tags)
    meta = extract_audio_metadata(input_path)
    display_title = meta["title"] if meta["title"] else _clean_filename(file.filename)
    display_artist = meta["artist"]  # None if not found

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
        "error": None,
        "filename": display_title,  # メタデータのtitleまたはクリーンなファイル名
        "artist": display_artist,   # メタデータのartist (なければNone)
    }
    
    # セッションを永続化してからバックグラウンドでパイプライン実行
    save_session(session_id)
    background_tasks.add_task(run_pipeline, session_id, session_dir, wav_path)
    
    return UploadResponse(
        session_id=session_id,
        message="アップロード成功。解析を開始しました。",
        status=SessionStatus.PENDING,
        audio_url=f"/files/{session_id}/converted.wav"
    )

def download_youtube_audio(url: str, output_dir: Path, cookies_content: Optional[str] = None) -> tuple:
    """Download audio from YouTube using yt-dlp. Returns (audio_path, metadata_dict)."""
    import os
    import tempfile
    
    proxy = os.getenv("YOUTUBE_PROXY")
    if not cookies_content or len(cookies_content.strip()) == 0:
        cookies_content = os.getenv("YOUTUBE_COOKIES")
    
    cookies_file = None
    if cookies_content and len(cookies_content.strip()) > 0:
        try:
            # Write cookies to a temporary file
            temp_cookies = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8')
            temp_cookies.write(cookies_content)
            temp_cookies.close()
            cookies_file = temp_cookies.name
            print(f"[YouTube] Using YOUTUBE_COOKIES from environment variable (temp file: {cookies_file})")
        except Exception as e:
            print(f"[YouTube] Failed to write temporary cookies file: {e}")
            
    try:
        # タイトルとアーティスト名を取得
        meta = {"title": "YouTube Video", "artist": ""}
        try:
            info_cmd = [
                YT_DLP_PATH, 
                "--no-playlist", 
                "--no-warnings", 
                "--no-check-certificates", 
                "--legacy-server-connect", 
                "--impersonate", "chrome",
                "--print", "%(title)s\n%(artist,uploader)s"
            ]
            if proxy:
                info_cmd.extend(["--proxy", proxy])
            if cookies_file:
                info_cmd.extend(["--cookies", cookies_file])
            info_cmd.append(url)
            
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
            "--no-check-certificates",
            "--legacy-server-connect",
            "--impersonate", "chrome",
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", "wav",
            "--audio-quality", "0",
            "-o", str(output_path) + ".%(ext)s"
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])
        if cookies_file:
            cmd.extend(["--cookies", cookies_file])
        cmd.append(url)
        
        print(f"Downloading YouTube audio (temp): {url} (Proxy={proxy is not None}, Cookies={cookies_file is not None})")
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
        
    finally:
        # Clean up temporary cookies file
        if cookies_file and os.path.exists(cookies_file):
            try:
                os.remove(cookies_file)
                print("[YouTube] Temporary cookies file cleaned up")
            except Exception as ce:
                print(f"[YouTube] Failed to remove temporary cookies file: {ce}")

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
            audio_path, yt_meta = download_youtube_audio(url, session_dir, request.cookies)
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
        steps_done=len(session.get("_steps", {})),
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
                "steps_done": len(session.get("_steps", {})),
                "filename": session.get("filename"),
                "artist": session.get("artist"),
            }

            # 変化があった場合のみ送信
            progress_key = f"{current['status']}:{current['progress']}:{current['steps_done']}"
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
         
    chordpro_text = session["result"].get("chordpro_text", "")
    
    # Generate text
    try:
        from export_utils import create_text_score
        text_score = create_text_score(chordpro_text)
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
    # ChordProテキストを最新ロジックで毎回再生成
    chordpro_text = ""
    chordpro_line_timings = result.get("chordpro_line_timings", [])
    if structured_data:
        try:
            import importlib
            import chordpro_converter
            importlib.reload(chordpro_converter)
            from chordpro_converter import structured_to_chordpro
            chordpro_text, chordpro_line_timings = structured_to_chordpro(
                structured_data,
                lyrics_phrases=result.get("lyrics_phrases"),
                display_phrases=display_phrases,
                title="",
                artist=session.get("artist", ""),
                key=session.get("key", ""),
                beats_per_bar=result.get("beats_per_bar", 4),
                bar_positions=result.get("bar_positions"),
            )
        except Exception as e:
            print(f"Warning: ChordPro conversion failed for {session_id}: {e}")
            chordpro_text = result.get("chordpro_text", "")

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
        has_notes=session.get("has_notes", False),
        chordpro_text=chordpro_text,
        chordpro_line_timings=chordpro_line_timings,
        beat_times=result.get("beat_times"),
        downbeats=result.get("downbeats"),
        bar_positions=result.get("bar_positions"),
        beats_per_bar=result.get("beats_per_bar"),
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

    print(f"[{session_id}] Updated {changed} chord(s)")
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

    print(f"[{session_id}] Updated lyrics ({len(new_phrases)} phrases)")
    return {"status": "ok", "phrases": len(new_phrases)}

@app.post("/result/{session_id}/regenerate-musicxml")
async def regenerate_musicxml(session_id: str):
    """
    編集済みのコード・歌詞でMusicXMLを再生成する
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if notes_to_musicxml is None:
        raise HTTPException(status_code=500, detail="tab_generator not available")
    
    session = sessions[session_id]
    session_dir = Path(session["session_dir"])
    
    # 1. structured_data からコード情報を読み込み
    sd_path = session_dir / "structured_data.json"
    if sd_path.exists():
        with open(sd_path, "r", encoding="utf-8") as f:
            structured = json.load(f)
    else:
        # session.json の result.structured_data から読み込み
        sj_path = session_dir / "session.json"
        if sj_path.exists():
            with open(sj_path, "r", encoding="utf-8") as f:
                sj_data = json.load(f)
            structured = sj_data.get("result", {}).get("structured_data", [])
            if not structured:
                raise HTTPException(status_code=404, detail="structured_data not found in session.json")
        else:
            raise HTTPException(status_code=404, detail="structured_data.json not found")
    
    # 2. 歌詞データを読み込み（display_phrases -> lyrics_data(bar,beat,start,end,text) に変換）
    lyrics_data = []
    
    # lyrics_split.csv がある場合はそこから読み込み
    lyrics_csv_path = session_dir / "lyrics_split.csv"
    if lyrics_csv_path.exists():
        import csv
        with open(lyrics_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                bar = int(row["bar"]) - 1   # 1-indexed -> 0-indexed
                beat = int(row["beat"]) - 1  # 1-indexed -> 0-indexed
                start = float(row["start"])
                end = float(row["end"])
                text = row["lyrics"]
                lyrics_data.append((bar, beat, start, end, text))
    
    # display_phrases はテキストビュー表示用のフレーズ単位データ。
    # MusicXMLの歌詞配置にはlyrics_split.csvのword-levelデータを使う。
    # ユーザーが歌詞テキストを編集した場合は、テキスト内容のみ更新する（位置は維持）。
    session_json_path = session_dir / "session.json"
    if session_json_path.exists() and lyrics_data:
        try:
            with open(session_json_path, "r", encoding="utf-8") as f:
                sdata = json.load(f)
            display_phrases = sdata.get("result", {}).get("display_phrases")
            if display_phrases:
                # 各フレーズの時間範囲に含まれるlyrics_dataエントリを特定し、
                # テキストが変更されていたら新テキストの文字を再分配する
                new_lyrics = list(lyrics_data)  # コピー
                for phrase in display_phrases:
                    p_start = phrase.get("start", 0)
                    p_end = phrase.get("end", p_start + 1)
                    p_text = phrase.get("text", "").strip()
                    if not p_text:
                        continue
                    
                    # このフレーズの時間範囲に含まれるlyrics_dataのインデックスを収集
                    indices = []
                    for i, lyr in enumerate(new_lyrics):
                        # lyr = (bar, beat, start, end, text)
                        if lyr[2] >= p_start - 0.3 and lyr[2] <= p_end + 0.3:
                            indices.append(i)
                    
                    if not indices:
                        continue
                    
                    # 元のテキストと比較
                    original_text = "".join(new_lyrics[i][4] for i in indices)
                    if original_text == p_text:
                        continue  # 変更なし
                    
                    # テキストが変更された -> 新テキストの文字をエントリに再分配
                    new_chars = list(p_text)
                    for j, idx in enumerate(indices):
                        bar, beat, start, end, _old_text = new_lyrics[idx]
                        if j < len(new_chars):
                            new_lyrics[idx] = (bar, beat, start, end, new_chars[j])
                        else:
                            new_lyrics[idx] = (bar, beat, start, end, "")
                    
                    # 新テキストが元のエントリ数より多い場合、余った文字を最後のエントリに結合
                    if len(new_chars) > len(indices) and indices:
                        last_idx = indices[-1]
                        bar, beat, start, end, txt = new_lyrics[last_idx]
                        extra = "".join(new_chars[len(indices):])
                        new_lyrics[last_idx] = (bar, beat, start, end, txt + extra)
                
                # 空テキストのエントリを除去
                lyrics_data = [(b, bt, s, e, t) for b, bt, s, e, t in new_lyrics if t]
                print(f"[{session_id}] [REGEN] Updated lyrics text from display_phrases: {len(lyrics_data)} entries")
        except Exception as e:
            print(f"[{session_id}] [REGEN] display_phrases update failed: {e}")
    
    # 3. notes.json からノートデータを読み込み
    notes_path = session_dir / "notes.json"
    note_events = []
    tab_source_notes = []
    song_type = "band"
    if notes_path.exists():
        with open(notes_path, "r", encoding="utf-8") as f:
            notes_data = json.load(f)
        note_events = notes_data.get("notes", [])
        song_type = notes_data.get("song_type", "band")
        tab_source = notes_data.get("tab_source", "chord_strum")
    
    # 4. ビート時刻（beats.txtから読み込み）
    beats_path = session_dir / "beats.txt"
    v_time = []
    if beats_path.exists():
        import numpy as np
        v_time = list(np.loadtxt(str(beats_path)))
    
    # 5. BPM・キー
    bpm = session.get("bpm", 120.0)
    detected_key = session.get("key", "C major")
    title = session.get("filename", session_id)
    
    # === BPM倍取り補正 ===
    # beats.txt にはBPM補正前の全ビートが保存されている場合がある。
    # structured_data のビート数と一致するようにv_timeを間引く。
    if len(v_time) > 1 and structured:
        expected_beats = max(e.get("bar", 1) for e in structured) * 4  # 大まかなビート数
        # structured_dataのビート数とbeats.txtのビート数が大きく異なる場合は倍取り補正
        if len(v_time) > expected_beats * 1.5:
            # BPMチェック
            intervals = np.diff(v_time)
            avg_interval = np.mean(intervals) if len(intervals) > 0 else 0.5
            raw_bpm = 60.0 / avg_interval if avg_interval > 0 else 120.0
            if raw_bpm > 200:
                v_time = v_time[::2]  # 半分に間引き
                bpm = raw_bpm / 2
                print(f"[{session_id}] [REGEN] BPM half-tempo correction: {raw_bpm:.1f} -> {bpm:.1f}, beats: {len(v_time)}")
    
    # 6. TABノート生成
    is_solo_guitar = song_type == "solo_guitar"
    if is_solo_guitar:
        xml_notes = note_events if note_events else []
    else:
        # コードストロークノートを再生成（編集済みstructuredを使用）
        xml_notes = generate_chord_strum_notes(structured, bpm=bpm)
    
    # 7. MusicXML再生成
    print(f"[{session_id}] Regenerating MusicXML: {len(xml_notes)} notes, {len(structured)} chords, {len(lyrics_data)} lyrics")
    xml_content = notes_to_musicxml(
        xml_notes,
        beats=v_time,
        chords=structured,
        lyrics=lyrics_data,
        key=detected_key,
        title=title,
        bpm=bpm,
    )
    
    # 8. 保存
    musicxml_path = session_dir / "sheet.musicxml"
    with open(musicxml_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    
    print(f"[{session_id}] MusicXML regenerated successfully")
    return {"status": "ok", "message": "MusicXML regenerated"}

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


@app.patch("/result/{session_id}/notes")
async def update_notes(session_id: str, request: Request):
    """
    Update notes data (fret edits, deletions, technique changes from TabEditor).
    Body: { "notes": [ {start, end, pitch, string, fret, velocity, technique, ...}, ... ] }
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    body = await request.json()
    new_notes = body.get("notes")
    if new_notes is None:
        return {"status": "no changes"}

    session = sessions[session_id]
    session_dir = Path(session["session_dir"])
    notes_path = session_dir / "notes.json"

    # Read existing notes.json to preserve metadata (song_type, tab_source, etc.)
    existing_data = {}
    if notes_path.exists():
        with open(notes_path, "r", encoding="utf-8") as f:
            existing_data = json.load(f)

    # Update only the notes array, keep other fields
    existing_data["notes"] = new_notes

    # Write back
    with open(notes_path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    # Invalidate cached GP5 if it exists
    gp5_path = session_dir / "tab.gp5"
    if gp5_path.exists():
        gp5_path.unlink()

    print(f"[{session_id}] Updated notes: {len(new_notes)} note(s)")
    return {"status": "ok", "notes_count": len(new_notes)}

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
    
    # ブラウザOOM防止: converted.wav を要求された場合、playback.mp3 があればそちらを返す
    if filename == "converted.wav":
        mp3_path = session_dir / "playback.mp3"
        if mp3_path.exists():
            return FileResponse(mp3_path, filename="playback.mp3", media_type="audio/mpeg")
    
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


@app.get("/export/{session_id}/gp5")
async def export_gp5(session_id: str):
    """ノートデータからGP5ファイルを生成してダウンロード"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    if notes_to_gp5 is None:
        raise HTTPException(status_code=500, detail="gp5_export not available")

    session = sessions[session_id]
    if session.get("status") != SessionStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Analysis not completed")

    session_dir = Path(session["session_dir"])

    # キャッシュがあればそのまま返す
    gp5_cached = session_dir / "tab.gp5"
    fname = session.get("filename", session_id)
    fname_stem = Path(fname).stem if fname else session_id

    if gp5_cached.exists():
        return FileResponse(gp5_cached, filename=f"{fname_stem}.gp5",
                            media_type="application/octet-stream")

    # notes.json 読み込み
    notes_path = session_dir / "notes.json"
    if not notes_path.exists():
        raise HTTPException(status_code=404, detail="notes.json not found -- run analysis first")

    with open(notes_path, "r", encoding="utf-8") as f:
        notes_data = json.load(f)
    note_events = notes_data.get("notes", [])

    # beats.json 読み込み
    beats_json_path = session_dir / "beats.json"
    v_time = []
    time_signature = "4/4"
    if beats_json_path.exists():
        with open(beats_json_path, "r", encoding="utf-8") as f:
            beats_info = json.load(f)
        v_time = beats_info.get("beats", [])
        time_signature = beats_info.get("time_signature", "4/4")

    bpm = session.get("bpm", 120.0)
    title = session.get("filename", session_id)

    # TABソースノートを決定（ソロギター->検出ノート、バンド->コードストラム）
    song_type = notes_data.get("song_type", "band")
    tab_source = notes_data.get("tab_source", "chord_strum")

    if song_type == "solo_guitar" or tab_source == "detected_notes":
        gp5_notes = note_events
    else:
        # コードストラムノート用にstart/end/pitch/string/fret形式に変換
        sd_path = session_dir / "structured_data.json"
        structured = None
        if sd_path.exists():
            with open(sd_path, "r", encoding="utf-8") as f:
                structured = json.load(f)
        if not structured:
            sj = session.get("result", {})
            structured = sj.get("structured_data", [])

        if structured and generate_chord_strum_notes and notes_to_tab_data:
            strum_notes = generate_chord_strum_notes(structured, bpm=bpm)
            tab_data = notes_to_tab_data(strum_notes, v_time)
            # tab_data を GP5入力形式に変換
            gp5_notes = []
            for td in tab_data:
                gp5_notes.append({
                    "start": td.get("time", 0),
                    "end": td.get("time", 0) + td.get("duration", 0.1),
                    "pitch": td.get("midi_pitch", 60),
                    "string": td.get("string", 1),
                    "fret": td.get("fret", 0),
                    "velocity": td.get("velocity", 80) / 127.0 if td.get("velocity", 80) > 1 else td.get("velocity", 0.5),
                })
        else:
            gp5_notes = note_events

    # チューニング取得（セッションに保存されていれば使用）
    tuning_list = session.get("tuning_list", None)  # [40,45,50,55,59,64]

    # GP5生成
    gp5_bytes = notes_to_gp5(
        gp5_notes,
        beats=v_time if v_time else None,
        bpm=bpm,
        title=title,
        tuning=tuning_list,
        time_signature=time_signature,
        noise_gate=session.get("noise_gate", 0.2),
    )

    # キャッシュ保存
    with open(gp5_cached, "wb") as f:
        f.write(gp5_bytes)

    return Response(
        content=gp5_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{fname_stem}.gp5"'},
    )


# ------------------------------------------------------------------
# TUNINGS dict for retune endpoint
# ------------------------------------------------------------------
TUNINGS = {
    "standard":  [40, 45, 50, 55, 59, 64],  # E2 A2 D3 G3 B3 E4
    "half_down": [39, 44, 49, 54, 58, 63],  # Eb2 Ab2 Db3 Gb3 Bb3 Eb4
    "drop_d":    [38, 45, 50, 55, 59, 64],  # D2 A2 D3 G3 B3 E4
    "open_g":    [38, 43, 50, 55, 59, 62],  # D2 G2 D3 G3 B3 D4
    "open_d":    [38, 45, 50, 54, 57, 62],  # D2 A2 D3 F#3 A3 D4
    "dadgad":    [38, 45, 50, 55, 57, 62],  # D2 A2 D3 G3 A3 D4
}


class RetuneRequest(BaseModel):
    tuning: str = "standard"
    capo: int = 0
    noise_gate: float = 0.2


@app.post("/result/{session_id}/retune")
async def retune(session_id: str, request: RetuneRequest):
    """チューニング変更 + 弦再割り当て + MusicXML/GP5再生成"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    if notes_to_tab_data is None or notes_to_musicxml is None:
        raise HTTPException(status_code=500, detail="tab_generator not available")

    session = sessions[session_id]
    session_dir = Path(session["session_dir"])

    # チューニング解決
    tuning_name = request.tuning
    base_tuning_list = TUNINGS.get(tuning_name, TUNINGS["standard"])
    # カポ適用: 各弦の開放音をカポ分だけ上げる
    tuning_list = [p + request.capo for p in base_tuning_list]
    tuning_dict = {6: tuning_list[0], 5: tuning_list[1], 4: tuning_list[2],
                   3: tuning_list[3], 2: tuning_list[4], 1: tuning_list[5]}

    # notes.json 読み込み
    notes_path = session_dir / "notes.json"
    if not notes_path.exists():
        raise HTTPException(status_code=404, detail="notes.json not found")

    with open(notes_path, "r", encoding="utf-8") as f:
        notes_data = json.load(f)
    note_events = notes_data.get("notes", [])
    song_type = notes_data.get("song_type", "band")
    tab_source = notes_data.get("tab_source", "chord_strum")

    # beats.json 読み込み
    beats_json_path = session_dir / "beats.json"
    v_time = []
    time_signature = "4/4"
    if beats_json_path.exists():
        with open(beats_json_path, "r", encoding="utf-8") as f:
            beats_info = json.load(f)
        v_time = beats_info.get("beats", [])
        time_signature = beats_info.get("time_signature", "4/4")

    bpm = session.get("bpm", 120.0)
    detected_key = session.get("key", "C major")
    title = session.get("filename", session_id)

    # structured_data 読み込み
    sd_path = session_dir / "structured_data.json"
    structured = None
    if sd_path.exists():
        with open(sd_path, "r", encoding="utf-8") as f:
            structured = json.load(f)
    if not structured:
        structured = session.get("result", {}).get("structured_data", [])

    # 歌詞読み込み
    lyrics_data = []
    lyrics_csv_path = session_dir / "lyrics_split.csv"
    if lyrics_csv_path.exists():
        with open(lyrics_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                bar = int(row["bar"]) - 1
                beat = int(row["beat"]) - 1
                start = float(row["start"])
                end = float(row["end"])
                text = row["lyrics"]
                lyrics_data.append((bar, beat, start, end, text))

    # TABソースノート決定
    is_solo = (song_type == "solo_guitar" or tab_source == "detected_notes")
    if is_solo:
        xml_notes = note_events
    else:
        xml_notes = generate_chord_strum_notes(structured, bpm=bpm) if structured else note_events

    # 1. 弦再割り当て (notes_to_tab_data)
    tab_data = notes_to_tab_data(xml_notes, v_time, tuning_dict)

    # 2. MusicXML 再生成
    xml_content = notes_to_musicxml(
        xml_notes,
        beats=v_time if v_time else None,
        chords=structured,
        lyrics=lyrics_data,
        key=detected_key,
        title=title,
        bpm=bpm,
        tuning=tuning_dict,
    )
    musicxml_path = session_dir / "sheet.musicxml"
    with open(musicxml_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    # 3. GP5 再生成
    gp5_bytes = None
    if notes_to_gp5 is not None:
        # GP5用ノート準備
        if is_solo:
            gp5_notes = note_events
        else:
            gp5_notes = []
            for td in tab_data:
                gp5_notes.append({
                    "start": td.get("time", 0),
                    "end": td.get("time", 0) + td.get("duration", 0.1),
                    "pitch": td.get("midi_pitch", 60),
                    "string": td.get("string", 1),
                    "fret": td.get("fret", 0),
                    "velocity": td.get("velocity", 80) / 127.0 if td.get("velocity", 80) > 1 else td.get("velocity", 0.5),
                })

        gp5_bytes = notes_to_gp5(
            gp5_notes,
            beats=v_time if v_time else None,
            bpm=bpm,
            title=title,
            tuning=tuning_list,
            time_signature=time_signature,
            noise_gate=request.noise_gate,
        )
        gp5_path = session_dir / "tab.gp5"
        with open(gp5_path, "wb") as f:
            f.write(gp5_bytes)

    # 4. notes.json のtabデータ更新
    notes_data["tab"] = tab_data
    with open(notes_path, "w", encoding="utf-8") as f:
        json.dump(notes_data, f, ensure_ascii=False, indent=2)

    # 5. セッション更新
    session["tuning"] = tuning_name
    session["capo"] = request.capo
    session["noise_gate"] = request.noise_gate
    session["tuning_list"] = tuning_list
    save_session(session_id)

    print(f"[{session_id}] Retune: tuning={tuning_name}, capo={request.capo}, "
          f"noise_gate={request.noise_gate}, tab_notes={len(tab_data)}")

    return {
        "status": "ok",
        "tuning": tuning_name,
        "capo": request.capo,
        "noise_gate": request.noise_gate,
        "tab_count": len(tab_data),
        "has_gp5": gp5_bytes is not None,
    }


class CutRequest(BaseModel):
    noise_gate: float = 0.0


@app.post("/result/{session_id}/cut")
async def cut_noise(session_id: str, request: CutRequest):
    """ノイズゲート変更 -- GP5のみ再生成"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    if notes_to_gp5 is None:
        raise HTTPException(status_code=500, detail="gp5_export not available")

    session = sessions[session_id]
    session_dir = Path(session["session_dir"])

    # notes.json 読み込み
    notes_path = session_dir / "notes.json"
    if not notes_path.exists():
        raise HTTPException(status_code=404, detail="notes.json not found")

    with open(notes_path, "r", encoding="utf-8") as f:
        notes_data = json.load(f)
    note_events = notes_data.get("notes", [])
    song_type = notes_data.get("song_type", "band")
    tab_source = notes_data.get("tab_source", "chord_strum")

    # beats.json 読み込み
    beats_json_path = session_dir / "beats.json"
    v_time = []
    time_signature = "4/4"
    if beats_json_path.exists():
        with open(beats_json_path, "r", encoding="utf-8") as f:
            beats_info = json.load(f)
        v_time = beats_info.get("beats", [])
        time_signature = beats_info.get("time_signature", "4/4")

    bpm = session.get("bpm", 120.0)
    title = session.get("filename", session_id)

    # GP5用ノート決定
    is_solo = (song_type == "solo_guitar" or tab_source == "detected_notes")
    if is_solo:
        gp5_notes = note_events
    else:
        structured = session.get("result", {}).get("structured_data", [])
        sd_path = session_dir / "structured_data.json"
        if sd_path.exists():
            with open(sd_path, "r", encoding="utf-8") as f:
                structured = json.load(f)
        if structured and generate_chord_strum_notes and notes_to_tab_data:
            strum = generate_chord_strum_notes(structured, bpm=bpm)
            tab_data = notes_to_tab_data(strum, v_time)
            gp5_notes = []
            for td in tab_data:
                gp5_notes.append({
                    "start": td.get("time", 0),
                    "end": td.get("time", 0) + td.get("duration", 0.1),
                    "pitch": td.get("midi_pitch", 60),
                    "string": td.get("string", 1),
                    "fret": td.get("fret", 0),
                    "velocity": td.get("velocity", 80) / 127.0 if td.get("velocity", 80) > 1 else td.get("velocity", 0.5),
                })
        else:
            gp5_notes = note_events

    tuning_list = session.get("tuning_list", None)

    # GP5再生成（noise_gateのみ変更）
    gp5_bytes = notes_to_gp5(
        gp5_notes,
        beats=v_time if v_time else None,
        bpm=bpm,
        title=title,
        tuning=tuning_list,
        time_signature=time_signature,
        noise_gate=request.noise_gate,
    )

    gp5_path = session_dir / "tab.gp5"
    with open(gp5_path, "wb") as f:
        f.write(gp5_bytes)

    # セッション更新
    session["noise_gate"] = request.noise_gate
    save_session(session_id)

    print(f"[{session_id}] Cut: noise_gate={request.noise_gate}, "
          f"gp5_size={len(gp5_bytes)} bytes")

    return {
        "status": "ok",
        "noise_gate": request.noise_gate,
        "gp5_size": len(gp5_bytes),
    }


async def _get_structured_data(session_id):
    # Re-using logic from get_result... careful with consistency.
    #Ideally we refactor. For now, copy-paste-modify slightly or call the function?
    # Calling the function `get_result` directly is okay if we change it to return Py object not response.
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


@app.get("/chord-audio/{chord_name}")
async def get_chord_audio(
    chord_name: str,
    octave: int = 4,
    duration: float = 1.8,
):
    """
    コード名から WAV 音声を生成して返す。
    例: GET /chord-audio/Am7  → Am7 の音声 WAV
    """
    from chord_synth import synthesize_chord
    from fastapi.responses import Response

    # URLエンコードされた文字列を元に戻す
    import urllib.parse
    chord_name = urllib.parse.unquote(chord_name)

    wav_bytes = synthesize_chord(chord_name, octave=octave, duration=duration)
    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f'inline; filename="{chord_name}.wav"',
        }
    )

@app.get("/chord-test", response_class=HTMLResponse)
async def chord_test_page():
    """全コード音確認ページ（CORS問題を回避するためバックエンドから配信）"""
    html_path = Path(__file__).parent / "chord_test.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/health")
async def health_check():
    """
    ヘルスチェック
    """
    return {"status": "healthy", "version": "0.4.0", "demucs": "enabled", "whisper": type(whisper_model).__name__ if whisper_model else "None"}



def run_pipeline_with_save(session_id: str, session_dir: Path, wav_path: Path):
    try:
        run_pipeline(session_id, session_dir, wav_path)
    finally:
        save_session(session_id)

# --- Frontend Static File Serving (Production / HF Spaces) ---
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend-dist"
if FRONTEND_DIR.exists():
    from starlette.responses import HTMLResponse
    # Windows Python の mimetypes が .js を text/plain と判定するバグを修正
    import mimetypes
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")
    mimetypes.add_type("text/css", ".css")
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
            import mimetypes
            mime, _ = mimetypes.guess_type(str(file_path))
            return FileResponse(str(file_path), media_type=mime or "application/octet-stream")
        return HTMLResponse((FRONTEND_DIR / "index.html").read_text())
    
    print(f"[OK] Frontend serving from: {FRONTEND_DIR}")
else:
    print(f"[INFO] No frontend-dist found at {FRONTEND_DIR} (development mode)")

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
