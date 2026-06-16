"""
NextChord V1.0 — Modal デプロイメント
====================================
NextChord の FastAPI バックエンドを Modal クラウド上で動かす設定。

使い方:
  $env:PYTHONUTF8=1; python -m modal deploy _modal/modal_app.py
"""

import modal
import os

nextchord_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libsndfile1", "fonts-noto-cjk", "git", "curl", "unzip")
    .run_commands(
        # Install Deno for yt-dlp EJS
        "curl -fsSL https://deno.land/install.sh | sh",
        "ln -sf /root/.deno/bin/deno /usr/local/bin/deno",
        # Install Node.js for yt-dlp JS challenges + ensure in PATH
        "curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs",
        "ln -sf /usr/bin/node /usr/local/bin/node",
        # Install bgutil-ytdlp-pot-provider scripts for PO Token generation
        "git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /root/bgutil-ytdlp-pot-provider"
        " && cd /root/bgutil-ytdlp-pot-provider/server && npm ci && npx tsc",
    )
    .pip_install(
        "numpy<2.0",
        "librosa==0.10.2",
        "scipy",
        "soundfile",
        "fastapi[standard]",
        "uvicorn[standard]",
        "python-multipart",
        "pydantic",
        "midiutil",
        "reportlab",
        "cython",
        "pyguitarpro",
        "faster-whisper",
        "python-dotenv",
        "mido",
        "pydub",
        "mir_eval",
        "music21",
        "demucs",
        "yt-dlp[default]",
        "bgutil-ytdlp-pot-provider",
    )
    .pip_install(
        "torch==2.5.1",
        "torchaudio==2.5.1",
        extra_index_url="https://download.pytorch.org/whl/cu121",
    )
    .pip_install(
        "madmom @ git+https://github.com/CPJKU/madmom.git",
    )
    # Add nextchord fastapi-backend
    .add_local_dir(
        r"D:\Music\nextchord\fastapi-backend",
        remote_path="/app/nextchord/fastapi-backend",
        copy=True,
        ignore=lambda p: any(x in __import__('pathlib').Path(p).parts for x in ["__pycache__", "uploads", "logs"]) or \
                         str(p).endswith(".pyc") or \
                         __import__('pathlib').Path(p).name.startswith("test_") or \
                         __import__('pathlib').Path(p).name.startswith("eval_"),
    )
    # Add nextchord BTC-ISMIR19
    .add_local_dir(
        r"D:\Music\nextchord\BTC-ISMIR19",
        remote_path="/app/nextchord/BTC-ISMIR19",
        copy=True,
        ignore=lambda p: any(x in __import__('pathlib').Path(p).parts for x in ["__pycache__", "uploads", "logs"]) or str(p).endswith(".pyc"),
    )
    # Add nextchord step0_separate_sources.py
    .add_local_file(
        r"D:\Music\nextchord\step0_separate_sources.py",
        remote_path="/app/nextchord/step0_separate_sources.py",
        copy=True,
    )
)

app = modal.App("nextchord", image=nextchord_image)
session_vol = modal.Volume.from_name("nextchord-sessions", create_if_missing=True)

# ---------------------------------------------------------------------------
# バックグラウンド解析タスク (Modal Function)
# ---------------------------------------------------------------------------
@app.function(
    timeout=600,
    memory=4096,
    gpu="L4",
    volumes={"/data": session_vol},
    secrets=[modal.Secret.from_name("youtube-cookies", required_keys=[], environment_name="main")],
)
def run_pipeline_modal(session_id: str, session_data: dict, is_youtube: bool = False, youtube_url: str = None, cookies_content: str = None):
    import sys
    import os
    import numpy as np
    import subprocess
    import shutil
    import json
    from pathlib import Path

    for attr in ('int','float','complex','bool'):
        if not hasattr(np, attr):
            setattr(np, attr, eval(attr))

    sys.path.insert(0, "/app/nextchord/fastapi-backend")
    sys.path.insert(0, "/app/nextchord/BTC-ISMIR19")
    os.environ["FFMPEG_PATH"] = "ffmpeg"

    UPLOAD_DIR = Path("/data/sessions")
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # ボリューム同期待ち（別コンテナからのファイル書き込み反映を最大15秒待つ）
    import time
    wav_path = session_dir / "converted.wav"
    for i in range(15):
        if wav_path.exists():
            break
        print(f"[Modal] Waiting for converted.wav to sync... ({i+1}/15)")
        try:
            session_vol.reload()
        except Exception as e:
            print(f"[Modal] Volume reload warning: {e}")
        time.sleep(1.0)


    def save_session_local(commit=True):
        (session_dir / "session.json").write_text(json.dumps(session_data, ensure_ascii=False, indent=2), encoding="utf-8")
        if commit:
            try:
                session_vol.commit()
            except Exception as e:
                print(f"[save local] Volume commit warning: {e}")

    try:
        session_data["status"] = "processing"
        save_session_local(commit=False)

        if is_youtube:
            import tempfile
            session_data["progress"] = "YouTube動画をダウンロード中..."
            save_session_local(commit=False)

            output_path = session_dir / "download_temp"

            # Start Node.js PO Token HTTP server
            import time as _time
            pot_proc = None
            try:
                pot_proc = subprocess.Popen(
                    ["node", "/root/bgutil-ytdlp-pot-provider/server/build/main.js",
                     "--port", "4416"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                _time.sleep(5)
                poll = pot_proc.poll()
                if poll is not None:
                    stderr_out = pot_proc.stderr.read().decode() if pot_proc.stderr else ""
                    print(f"[YouTube] POT server exited (code={poll}): {stderr_out[:500]}", flush=True)
                    pot_proc = None
                else:
                    print(f"[YouTube] POT server running (pid={pot_proc.pid})", flush=True)
            except Exception as e:
                print(f"[YouTube] POT server error: {e}", flush=True)

            # Check for cookies file (local first, then reload volume)
            cookies_path = Path("/data/cookies.txt")
            has_cookies = cookies_path.exists()
            if not has_cookies:
                try:
                    session_vol.reload()
                    has_cookies = cookies_path.exists()
                except: pass
            print(f"[YouTube] Cookies found: {has_cookies}", flush=True)

            cmd = [
                "yt-dlp",
                "--verbose",
                "--no-playlist",
                "--no-warnings",
                "--no-check-certificates",
                "--legacy-server-connect",
                "--impersonate", "chrome",
                "--js-runtimes", "deno:/usr/local/bin/deno",
                "--extractor-args", "youtube:player-client=mweb,default",
                "-f", "bestaudio*/best",
                "-x",
                "--audio-format", "wav",
                "--audio-quality", "0",
                "-o", str(output_path) + ".%(ext)s",
                youtube_url,
            ]
            
            download_success = False
            result = None

            # Try 1: with cookies (if they exist)
            if has_cookies:
                print(f"[YouTube] Attempting download with cookies: {youtube_url}", flush=True)
                cmd_cookies = list(cmd)
                # We need to insert --cookies before youtube_url which is the last element
                cmd_cookies.insert(-1, "--cookies")
                cmd_cookies.insert(-1, str(cookies_path))
                result = subprocess.run(cmd_cookies, capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    download_success = True
                    print(f"[YouTube] Download with cookies succeeded!", flush=True)
                else:
                    print(f"[YouTube] Download with cookies failed (exited {result.returncode}): {result.stderr[-300:]}", flush=True)
            
            # Try 2: with PO Token (if cookies failed or don't exist)
            if not download_success:
                if pot_proc and pot_proc.poll() is None:
                    print(f"[YouTube] Attempting download with PO Token: {youtube_url}", flush=True)
                    cmd_pot = list(cmd)
                    # Add PO Token extractor args
                    cmd_pot.insert(-1, "--extractor-args")
                    cmd_pot.insert(-1, "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416")
                    result = subprocess.run(cmd_pot, capture_output=True, text=True, timeout=300)
                    if result.returncode == 0:
                        download_success = True
                        print(f"[YouTube] Download with PO Token succeeded!", flush=True)
                    else:
                        print(f"[YouTube] Download with PO Token failed (exited {result.returncode}): {result.stderr[-300:]}", flush=True)
                else:
                    print(f"[YouTube] POT server is not running, skipping PO Token fallback.", flush=True)
            
            # Try 3: without auth (if all else failed)
            if not download_success:
                print(f"[YouTube] Attempting download without auth: {youtube_url}", flush=True)
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    download_success = True
                    print(f"[YouTube] Download without auth succeeded!", flush=True)
                else:
                    print(f"[YouTube] Download without auth failed (exited {result.returncode}): {result.stderr[-300:]}", flush=True)

            # Stop POT server
            if pot_proc:
                try:
                    pot_proc.terminate()
                    pot_proc.wait(timeout=5)
                except: pass

            if not download_success:
                print(f"[YouTube] yt-dlp stderr (last 600 chars): {result.stderr[-600:] if result else 'No result'}")
                raise Exception(f"YouTube download failed after trying cookies, PO Token, and no-auth: {result.stderr if result else 'No output'}")
            else:
                print(f"[YouTube] Download succeeded!")
            
            downloaded_file = None
            for f in session_dir.glob("download_temp.*"):
                if f.suffix.lower() in [".mp3", ".m4a", ".webm", ".wav", ".opus", ".ogg"]:
                    downloaded_file = f
                    break
            
            if not downloaded_file:
                raise FileNotFoundError("Downloaded file not found")
                
            wav_path = session_dir / "converted.wav"
            subprocess.run(["ffmpeg", "-y", "-i", str(downloaded_file), str(wav_path)], check=True, capture_output=True)
            session_data["wav_path"] = str(wav_path)
            
            session_data["filename"] = session_data.get("title", "YouTube Video")
            if session_data["filename"] == "YouTube Video":
                try:
                    info_cmd = ["yt-dlp", "--no-playlist", "--no-check-certificates", "--print", "%(title)s",
                                "--extractor-args", "youtube:player_client=web", youtube_url]
                    title_res = subprocess.run(info_cmd, capture_output=True, text=True, timeout=15)
                    if title_res.returncode == 0 and title_res.stdout.strip():
                        session_data["filename"] = title_res.stdout.strip()
                except Exception:
                    pass
        else:
            wav_path = Path(session_data["wav_path"])

        session_data["progress"] = "解析を開始します..."
        save_session_local(commit=False)

        import main as nextchord_main
        nextchord_main.init_models_lazy()
        
        nextchord_main.sessions[session_id] = session_data

        def save_session_dummy(sid):
            (session_dir / "session.json").write_text(json.dumps(nextchord_main.sessions[sid], ensure_ascii=False, indent=2), encoding="utf-8")

        ctx = {
            "sessions": nextchord_main.sessions,
            "save_session": save_session_dummy,
            "SessionStatus": nextchord_main.SessionStatus,
            "beat_processor": nextchord_main.beat_processor,
            "beat_tracker": nextchord_main.beat_tracker,
            "key_processor": nextchord_main.key_processor,
            "chroma_processor": nextchord_main.chroma_processor,
            "chord_processor": nextchord_main.chord_processor,
            "whisper_model": nextchord_main.whisper_model,
            "transcribe_notes": nextchord_main.transcribe_notes,
            "notes_to_tab_data": nextchord_main.notes_to_tab_data,
            "notes_to_musicxml": nextchord_main.notes_to_musicxml,
            "estimate_key_from_chords": nextchord_main.estimate_key_from_chords,
            "generate_chord_strum_notes": nextchord_main.generate_chord_strum_notes,
        }

        from pipeline import run_pipeline as _run_pipeline_impl
        _run_pipeline_impl(session_id, session_dir, wav_path, ctx)

        session_data.update(nextchord_main.sessions[session_id])
        session_data["status"] = "completed"
        session_data["progress"] = "解析完了"
        save_session_local(commit=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        session_data["status"] = "failed"
        session_data["error"] = str(e)
        session_data["progress"] = "エラーにより失敗"
        save_session_local(commit=True)


@app.function(
    timeout=600,
    memory=4096,
    gpu="L4",
    volumes={"/data": session_vol},
)
def run_separation_modal(session_id: str, session_data: dict):
    import sys
    import os
    import numpy as np
    import subprocess
    import json
    from pathlib import Path

    for attr in ('int','float','complex','bool'):
        if not hasattr(np, attr):
            setattr(np, attr, eval(attr))

    sys.path.insert(0, "/app/nextchord/fastapi-backend")
    sys.path.insert(0, "/app/nextchord/BTC-ISMIR19")
    os.environ["FFMPEG_PATH"] = "ffmpeg"

    UPLOAD_DIR = Path("/data/sessions")
    session_dir = UPLOAD_DIR / session_id
    wav_path = Path(session_data["wav_path"])
    clean_wav_path = session_dir / "clean.wav"

    def save_session_local(commit=True):
        (session_dir / "session.json").write_text(json.dumps(session_data, ensure_ascii=False, indent=2), encoding="utf-8")
        if commit:
            try:
                session_vol.commit()
            except Exception as e:
                print(f"[save local separation] Volume commit warning: {e}")

    try:
        session_data["is_separating"] = True
        session_data["separation_progress"] = "AI音源分離中 (Demucs)..."
        save_session_local(commit=True)

        # 1. Run Demucs
        cmd = [
            sys.executable,
            "/app/nextchord/step0_separate_sources.py",
            str(wav_path),
            str(session_dir),
            str(clean_wav_path)
        ]
        print(f"[Modal Separation] Executing: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Demucs separation failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

        # 2. Re-run chord detection
        session_data["separation_progress"] = "コード再解析中..."
        save_session_local(commit=True)

        import main as nextchord_main
        nextchord_main.init_models_lazy()
        nextchord_main.sessions[session_id] = session_data

        def save_session_dummy(sid):
            (session_dir / "session.json").write_text(json.dumps(nextchord_main.sessions[sid], ensure_ascii=False, indent=2), encoding="utf-8")

        ctx = {
            "sessions": nextchord_main.sessions,
            "save_session": save_session_dummy,
            "SessionStatus": nextchord_main.SessionStatus,
            "beat_processor": nextchord_main.beat_processor,
            "beat_tracker": nextchord_main.beat_tracker,
            "key_processor": nextchord_main.key_processor,
            "chroma_processor": nextchord_main.chroma_processor,
            "chord_processor": nextchord_main.chord_processor,
            "whisper_model": nextchord_main.whisper_model,
            "transcribe_notes": nextchord_main.transcribe_notes,
            "notes_to_tab_data": nextchord_main.notes_to_tab_data,
            "notes_to_musicxml": nextchord_main.notes_to_musicxml,
            "estimate_key_from_chords": nextchord_main.estimate_key_from_chords,
            "generate_chord_strum_notes": nextchord_main.generate_chord_strum_notes,
        }

        from pipeline import reanalyze_chords_with_stems
        reanalyze_chords_with_stems(session_id, session_dir, ctx)

        # メモリから最新状態を反映して保存
        session_data.update(nextchord_main.sessions[session_id])
        session_data["separation_progress"] = "分離完了"
        session_data["is_separating"] = False
        session_data["has_clean_audio"] = True
        save_session_local(commit=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        session_data["is_separating"] = False
        session_data["separation_error"] = str(e)
        session_data["separation_progress"] = "分離失敗"
        save_session_local(commit=True)


# ---------------------------------------------------------------------------
# FastAPI API Server (Modal Web Endpoint)
# ---------------------------------------------------------------------------
@app.function(
    timeout=180,
    volumes={"/data": session_vol},
)
@modal.asgi_app()
def nextchord_api():
    import sys
    import os
    import numpy as np

    for attr in ('int','float','complex','bool'):
        if not hasattr(np, attr):
            setattr(np, attr, eval(attr))

    sys.path.insert(0, "/app/nextchord/fastapi-backend")
    sys.path.insert(0, "/app/nextchord/BTC-ISMIR19")
    os.environ["FFMPEG_PATH"] = "ffmpeg"

    from fastapi import FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks, Response, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from pydantic import BaseModel
    from contextlib import asynccontextmanager
    import json, shutil, subprocess, datetime as dt, uuid
    from typing import Optional
    from pathlib import Path

    UPLOAD_DIR = Path("/data/sessions")
    UPLOAD_DIR.mkdir(exist_ok=True)

    sessions = {}

    recent_writes = {} # sid -> float (timestamp)

    async def save_session_async(sid):
        sd = UPLOAD_DIR / sid
        (sd/"session.json").write_text(json.dumps(sessions[sid], ensure_ascii=False, indent=2), encoding="utf-8")
        import time
        recent_writes[sid] = time.time()
        try:
            await session_vol.commit.aio()
        except Exception as e:
            print(f"[save async] Volume commit warning: {e}")

    def load_session(sid):
        sd = UPLOAD_DIR / sid
        sp = sd / "session.json"
        if sp.exists():
            try:
                s = json.loads(sp.read_text(encoding="utf-8"))
                sessions[sid] = s
                return s
            except Exception:
                pass
        if sid in sessions:
            return sessions[sid]
        return None

    async def safe_reload_async(sid=None):
        import time
        saved_backups = {}
        now = time.time()
        for active_sid, write_time in list(recent_writes.items()):
            if now - write_time < 15.0:
                sd = UPLOAD_DIR / active_sid
                if sd.exists():
                    backup = {}
                    session_file = sd / "session.json"
                    struct_file = sd / "structured_data.json"
                    notes_file = sd / "notes.json"
                    
                    if session_file.exists():
                        backup["session.json"] = session_file.read_bytes()
                    if struct_file.exists():
                        backup["structured_data.json"] = struct_file.read_bytes()
                    if notes_file.exists():
                        backup["notes.json"] = notes_file.read_bytes()
                    
                    if backup:
                        saved_backups[active_sid] = backup

        try:
            await session_vol.reload.aio()
        except Exception as e:
            print(f"[safe_reload] Volume reload warning: {e}")

        for active_sid, backup in saved_backups.items():
            sd = UPLOAD_DIR / active_sid
            sd.mkdir(parents=True, exist_ok=True)
            for fname, content in backup.items():
                (sd / fname).write_bytes(content)
            print(f"[safe_reload] Restored backup for recently written session {active_sid} after reload")

    def load_all_sessions():
        if not UPLOAD_DIR.exists():
            return
        for d in UPLOAD_DIR.iterdir():
            if d.is_dir():
                sp = d / "session.json"
                if sp.exists():
                    try:
                        s = json.loads(sp.read_text(encoding="utf-8"))
                        sessions[d.name] = s
                    except Exception:
                        pass

    load_all_sessions()

    @asynccontextmanager
    async def lifespan(_): yield

    fa = FastAPI(title="NextChord API", version="2.0.0", lifespan=lifespan)
    fa.add_middleware(
        CORSMiddleware,
        allow_origins=["https://nextchord.vercel.app", "http://localhost:5173", "http://localhost:3000", "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class YouTubeRequest(BaseModel):
        url: str
        cookies: Optional[str] = None

    @fa.get("/sessions")
    async def get_sessions_list():
        try:
            await safe_reload_async()
        except Exception:
            pass
        load_all_sessions()
        res = []
        for sid, s in sorted(sessions.items(), key=lambda x: x[0], reverse=True):
            res.append({
                "id": sid,
                "filename": s.get("filename", "Untitled"),
                "status": s.get("status"),
                "artist": s.get("artist"),
                "created_at": sid.split("-")[0] if "-" in sid else ""
            })
        return res

    @fa.post("/upload")
    async def upload_audio(file: UploadFile = File(...)):
        session_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(uuid.uuid4().hex)[:4]
        session_dir = UPLOAD_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        audio_path = session_dir / file.filename
        audio_path.write_bytes(await file.read())

        wav_path = session_dir / "converted.wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio_path), str(wav_path)],
                check=True, capture_output=True
            )
        except Exception:
            shutil.copy2(str(audio_path), str(wav_path))

        sessions[session_id] = {
            "session_dir": str(session_dir),
            "filename": file.filename,
            "wav_path": str(wav_path),
            "status": "pending",
            "progress": "アップロード完了",
            "error": None,
        }
        await save_session_async(session_id)
        await run_pipeline_modal.spawn.aio(session_id, sessions[session_id])

        return {
            "session_id": session_id,
            "message": "解析を開始しました",
            "status": "pending",
            "audio_url": f"/files/{session_id}/converted.wav"
        }

    @fa.post("/upload/youtube")
    async def upload_youtube(request: YouTubeRequest):
        session_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-yt-" + str(uuid.uuid4().hex)[:4]
        session_dir = UPLOAD_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        sessions[session_id] = {
            "session_dir": str(session_dir),
            "filename": "YouTube Video",
            "url": request.url,
            "status": "pending",
            "progress": "YouTube動画をロード中...",
            "error": None,
        }
        await save_session_async(session_id)

        await run_pipeline_modal.spawn.aio(session_id, sessions[session_id], is_youtube=True, youtube_url=request.url, cookies_content=request.cookies)
        return {
            "session_id": session_id,
            "message": "YouTube解析を開始しました",
            "status": "pending",
        }

    @fa.post("/upload/cookies")
    async def upload_cookies(file: UploadFile = File(...)):
        """Upload YouTube cookies.txt for authenticated downloads"""
        cookies_path = Path("/data/cookies.txt")
        content = await file.read()
        cookies_path.write_bytes(content)
        session_vol.commit()
        return {"message": "Cookies uploaded successfully", "size": len(content)}

    @fa.get("/status/{session_id}")
    async def get_status(session_id: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id": session_id,
            "status": s["status"],
            "progress": s.get("progress"),
            "error": s.get("error"),
            "filename": s.get("filename"),
            "artist": s.get("artist"),
            "steps_done": len(s.get("_steps", {})),
            "completed_steps": list(s.get("_steps", {}).keys())
        }

    @fa.get("/status/{session_id}/stream")
    async def stream_status(session_id: str):
        import asyncio
        from fastapi.responses import StreamingResponse

        async def event_generator():
            last_progress = None
            while True:
                try:
                    await safe_reload_async(session_id)
                except Exception:
                    pass
                s = load_session(session_id)
                if s is None:
                    yield f"data: {json.dumps({'status': 'not_found', 'error': 'セッションが見つかりません'})}\n\n"
                    return

                current = {
                    "status": s.get("status", "pending"),
                    "progress": s.get("progress", ""),
                    "steps_done": len(s.get("_steps", {})),
                    "completed_steps": list(s.get("_steps", {}).keys()),
                    "filename": s.get("filename"),
                    "artist": s.get("artist"),
                }

                steps_key = ",".join(sorted(current['completed_steps']))
                progress_key = f"{current['status']}:{current['progress']}:{current['steps_done']}:{steps_key}"
                if progress_key != last_progress:
                    yield f"data: {json.dumps(current, ensure_ascii=False)}\n\n"
                    last_progress = progress_key
                else:
                    yield ": keep-alive\n\n"

                if current["status"] in ("completed", "failed"):
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

    @fa.get("/result/{session_id}")
    async def get_result(session_id: str):
        s = load_session(session_id)
        if s is None:
            try:
                await safe_reload_async(session_id)
            except Exception:
                pass
            s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if s["status"] != "completed":
            raise HTTPException(status_code=202, detail="Analysis in progress")

        session_dir = Path(s["session_dir"])
        structured_file = session_dir / "structured_data.json"
        structured_data = []
        if structured_file.exists():
            try:
                structured_data = json.loads(structured_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        result = s.get("result", {})

        return {
            "session_id": session_id,
            "status": s["status"],
            "key": s.get("key"),
            "bpm": s.get("bpm"),
            "filename": s.get("filename"),
            "artist": s.get("artist"),
            "chord_sheet": s.get("chord_sheet"),
            "structured_data": structured_data or result.get("structured_data", []),
            "lyrics_phrases": result.get("lyrics_phrases", []),
            "display_phrases": result.get("display_phrases", []),
            "chordpro_text": result.get("chordpro_text"),
            "beat_times": result.get("beat_times"),
            "downbeats": result.get("downbeats"),
            "bar_positions": result.get("bar_positions"),
            "beats_per_bar": result.get("beats_per_bar"),
            "chordpro_line_timings": result.get("chordpro_line_timings"),
            "tab_source": result.get("tab_source") or s.get("tab_source"),
            "song_type": result.get("song_type") or s.get("song_type")
        }

    @fa.get("/files/{session_id}/{filename:path}")
    async def get_file(session_id: str, filename: str):
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session_dir = Path(s["session_dir"])
        file_path = session_dir / filename
        if not file_path.exists():
            try:
                await safe_reload_async(session_id)
            except Exception:
                pass
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        media_type = "audio/wav" if filename.endswith(".wav") else "application/octet-stream"
        return FileResponse(str(file_path), media_type=media_type)

    @fa.post("/separate/{session_id}")
    async def trigger_separation(session_id: str, force: bool = False):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません")
        
        session_dir = Path(s["session_dir"])
        clean_wav_path = session_dir / "clean.wav"

        if clean_wav_path.exists() and not force:
            return {"session_id": session_id, "status": "exists", "message": "すでに分離済みです"}
        
        if s.get("is_separating") and not force:
            return {"session_id": session_id, "status": "processing", "message": "分離処理中です"}

        s["is_separating"] = True
        s["separation_progress"] = "分離開始..."
        s["separation_error"] = None
        await save_session_async(session_id)
        
        await run_separation_modal.spawn.aio(session_id, s)
        
        return {"session_id": session_id, "status": "started", "message": "音源分離を開始しました"}

    @fa.get("/status/separation/{session_id}")
    async def get_separation_status(session_id: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません")
        
        session_dir = Path(s["session_dir"])
        has_clean = (session_dir / "htdemucs_6s").exists() or (session_dir / "htdemucs").exists() or (session_dir / "clean.wav").exists()
        
        return {
            "session_id": session_id,
            "is_separating": s.get("is_separating", False),
            "progress": s.get("separation_progress", "未開始"),
            "has_clean_audio": has_clean,
            "error": s.get("separation_error"),
        }

    @fa.post("/reanalyze/{session_id}")
    async def trigger_reanalysis(session_id: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません")
        
        s["status"] = "pending"
        s["progress"] = "再解析キューに入りました..."
        s["error"] = None
        await save_session_async(session_id)
        await run_pipeline_modal.spawn.aio(session_id, s)
        return {"status": "started", "session_id": session_id}

    class ChordEdit(BaseModel):
        index: int
        chord: str

    class ChordEditsRequest(BaseModel):
        edits: list[ChordEdit]

    @fa.patch("/result/{session_id}/chords")
    async def update_chords(session_id: str, request: ChordEditsRequest):
        s = load_session(session_id)
        if s is None:
            try:
                await safe_reload_async(session_id)
            except Exception:
                pass
            s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")

        session_dir = Path(s["session_dir"])
        sd_path = session_dir / "structured_data.json"
        
        structured_data = []
        if sd_path.exists():
            structured_data = json.loads(sd_path.read_text(encoding="utf-8"))
        else:
            structured_data = s.get("result", {}).get("structured_data", [])

        if not structured_data:
            raise HTTPException(status_code=404, detail="No structured data found")

        changed = 0
        for edit in request.edits:
            idx = edit.index
            new_chord = edit.chord
            if 0 <= idx < len(structured_data):
                structured_data[idx]["chord"] = new_chord
                changed += 1

        sd_path.write_text(json.dumps(structured_data, ensure_ascii=False, indent=2), encoding="utf-8")
        
        if "result" not in s:
            s["result"] = {}
        s["result"]["structured_data"] = structured_data

        if s["result"].get("chordpro_text"):
            try:
                import main as nextchord_main
                nextchord_main.init_models_lazy()
                from chordpro_converter import structured_to_chordpro
                
                title = s.get("filename", session_id)
                artist = s.get("artist", "")
                key = s.get("key", "C major")
                
                display_phrases = s["result"].get("display_phrases", [])
                lyrics_phrases = s["result"].get("lyrics_phrases", [])
                bar_positions = s["result"].get("bar_positions", [])
                beats_per_bar = s["result"].get("beats_per_bar", 4)
                
                new_cp_text, new_cp_timings = structured_to_chordpro(
                    structured_data,
                    lyrics_phrases=lyrics_phrases,
                    display_phrases=display_phrases,
                    title=title,
                    artist=artist,
                    key=key,
                    beats_per_bar=beats_per_bar,
                    bar_positions=bar_positions
                )
                s["result"]["chordpro_text"] = new_cp_text
                s["result"]["chordpro_line_timings"] = new_cp_timings
                print(f"[{session_id}] Regenerated ChordPro text ({len(new_cp_text)} chars)")
            except Exception as cp_err:
                print(f"[{session_id}] Failed to regenerate ChordPro: {cp_err}")
        
        await save_session_async(session_id)
        
        print(f"[{session_id}] Updated {changed} chord(s)")
        return {"status": "ok", "changed": changed}

    @fa.patch("/result/{session_id}/lyrics")
    async def update_lyrics(session_id: str, request: Request):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")

        body = await request.json()
        new_phrases = body.get("display_phrases", [])
        if not new_phrases:
            return {"status": "no changes"}

        if "result" not in s:
            s["result"] = {}
        s["result"]["display_phrases"] = new_phrases

        # ChordProテキストを再生成
        session_dir = Path(s["session_dir"])
        sd_path = session_dir / "structured_data.json"
        structured_data = []
        if sd_path.exists():
            structured_data = json.loads(sd_path.read_text(encoding="utf-8"))
        else:
            structured_data = s["result"].get("structured_data", [])

        if structured_data:
            try:
                import main as nextchord_main
                nextchord_main.init_models_lazy()
                from chordpro_converter import structured_to_chordpro
                
                title = s.get("filename", session_id)
                artist = s.get("artist", "")
                key = s.get("key", "C major")
                
                lyrics_phrases = s["result"].get("lyrics_phrases", [])
                bar_positions = s["result"].get("bar_positions", [])
                beats_per_bar = s["result"].get("beats_per_bar", 4)
                
                new_cp_text, new_cp_timings = structured_to_chordpro(
                    structured_data,
                    lyrics_phrases=lyrics_phrases,
                    display_phrases=new_phrases,
                    title=title,
                    artist=artist,
                    key=key,
                    beats_per_bar=beats_per_bar,
                    bar_positions=bar_positions
                )
                s["result"]["chordpro_text"] = new_cp_text
                s["result"]["chordpro_line_timings"] = new_cp_timings
                print(f"[{session_id}] Regenerated ChordPro text in update_lyrics ({len(new_cp_text)} chars)")
            except Exception as cp_err:
                print(f"[{session_id}] Failed to regenerate ChordPro in update_lyrics: {cp_err}")

        await save_session_async(session_id)
        print(f"[{session_id}] Updated lyrics ({len(new_phrases)} phrases)")
        return {"status": "ok", "phrases": len(new_phrases)}

    @fa.patch("/result/{session_id}/chordpro")
    async def update_chordpro(session_id: str, request: Request):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
            
        body = await request.json()
        chordpro_text = body.get("chordpro_text")
        if not chordpro_text:
            raise HTTPException(status_code=400, detail="chordpro_text is required")
            
        session_dir = Path(s["session_dir"])
        
        # 1. structured_data 読み込み
        sd_path = session_dir / "structured_data.json"
        structured = []
        if sd_path.exists():
            structured = json.loads(sd_path.read_text(encoding="utf-8"))
        else:
            structured = s.get("result", {}).get("structured_data", [])
            
        if not structured:
            raise HTTPException(status_code=404, detail="No structured data found")
            
        result = s.get("result", {})
        display_phrases = result.get("display_phrases", [])
        if not display_phrases:
            display_phrases = result.get("lyrics_phrases", [])
            
        beats_path = session_dir / "beats.txt"
        v_time = []
        if beats_path.exists():
            v_time = list(np.loadtxt(str(beats_path)))
            
        bar_positions = result.get("bar_positions", [])
        
        # 2. マージ
        try:
            from chordpro_parser import merge_chordpro_changes
            new_structured, new_display_phrases = merge_chordpro_changes(
                chordpro_text,
                structured,
                display_phrases,
                v_time,
                bar_positions
            )
        except Exception as e:
            print(f"ChordPro merge failed: {e}")
            raise HTTPException(status_code=500, detail=f"ChordProのパースに失敗しました: {e}")
            
        # 3. 保存
        sd_path.write_text(json.dumps(new_structured, ensure_ascii=False, indent=2), encoding="utf-8")
        
        if "result" not in s:
            s["result"] = {}
        s["result"]["structured_data"] = new_structured
        s["result"]["display_phrases"] = new_display_phrases
        s["result"]["chordpro_text"] = chordpro_text
        
        await save_session_async(session_id)
        
        # 4. MusicXML 再生成
        try:
            import main as nextchord_main
            nextchord_main.init_models_lazy()
            
            bpm = s.get("bpm", 120.0)
            detected_key = s.get("key", "C major")
            title = s.get("filename", session_id)
            
            beats_json_path = session_dir / "beats.json"
            v_time_beats = []
            if beats_json_path.exists():
                beats_info = json.loads(beats_json_path.read_text(encoding="utf-8"))
                v_time_beats = beats_info.get("beats", [])
                
            notes_path = session_dir / "notes.json"
            if notes_path.exists():
                notes_data = json.loads(notes_path.read_text(encoding="utf-8"))
                note_events = notes_data.get("notes", [])
            else:
                note_events = []
                
            lyrics_data = []
            lyrics_csv_path = session_dir / "lyrics_split.csv"
            import csv
            if lyrics_csv_path.exists():
                with open(lyrics_csv_path, "r", encoding="utf-8") as f_lyrics:
                    reader = csv.DictReader(f_lyrics)
                    for row in reader:
                        bar = int(row["bar"]) - 1
                        beat = int(row["beat"]) - 1
                        start = float(row["start"])
                        end = float(row["end"])
                        text = row["lyrics"]
                        lyrics_data.append((bar, beat, start, end, text))
                        
            capo = s.get("capo", 0)
            tuning_name = s.get("tuning", "standard")
            base_tuning_list = nextchord_main.TUNINGS.get(tuning_name, nextchord_main.TUNINGS["standard"])
            tuning_list = [p + capo for p in base_tuning_list]
            tuning_dict = {6: tuning_list[0], 5: tuning_list[1], 4: tuning_list[2],
                           3: tuning_list[3], 2: tuning_list[4], 1: tuning_list[5]}
                           
            tab_source = s.get("tab_source", "chord_strum")
            is_solo = (tab_source == "detected_notes")
            if is_solo:
                xml_notes = note_events
            else:
                xml_notes = nextchord_main.generate_chord_strum_notes(new_structured, bpm=bpm) if new_structured else note_events
                
            xml_content = nextchord_main.notes_to_musicxml(
                xml_notes,
                beats=v_time_beats if v_time_beats else None,
                chords=new_structured,
                lyrics=lyrics_data,
                key=detected_key,
                title=title,
                bpm=bpm,
                tuning=tuning_dict,
            )
            musicxml_path = session_dir / "sheet.musicxml"
            musicxml_path.write_text(xml_content, encoding="utf-8")
            
            if nextchord_main.notes_to_gp5 is not None:
                if is_solo:
                    gp5_notes = note_events
                else:
                    tab_data = nextchord_main.notes_to_tab_data(xml_notes, v_time_beats, tuning_dict)
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
                gp5_bytes = nextchord_main.notes_to_gp5(
                    gp5_notes,
                    beats=v_time_beats if v_time_beats else None,
                    bpm=bpm,
                    title=title,
                    tuning=tuning_list,
                    time_signature="4/4",
                    noise_gate=s.get("noise_gate", 0.2),
                )
                gp5_path = session_dir / "tab.gp5"
                gp5_path.write_bytes(gp5_bytes)
                
            await session_vol.commit.aio()
        except Exception as e:
            print(f"[{session_id}] MusicXML regeneration failed: {e}")
            raise HTTPException(status_code=500, detail=f"MusicXMLの再生成に失敗しました: {e}")
            
        return {"status": "ok", "message": "ChordPro updated and score regenerated"}

    @fa.post("/result/{session_id}/regenerate-musicxml")
    async def regenerate_musicxml_endpoint(session_id: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
            
        session_dir = Path(s["session_dir"])
        
        sd_path = session_dir / "structured_data.json"
        structured = []
        if sd_path.exists():
            structured = json.loads(sd_path.read_text(encoding="utf-8"))
        else:
            structured = s.get("result", {}).get("structured_data", [])
            
        try:
            import main as nextchord_main
            nextchord_main.init_models_lazy()
            
            bpm = s.get("bpm", 120.0)
            detected_key = s.get("key", "C major")
            title = s.get("filename", session_id)
            
            beats_json_path = session_dir / "beats.json"
            v_time_beats = []
            if beats_json_path.exists():
                beats_info = json.loads(beats_json_path.read_text(encoding="utf-8"))
                v_time_beats = beats_info.get("beats", [])
                
            notes_path = session_dir / "notes.json"
            if notes_path.exists():
                notes_data = json.loads(notes_path.read_text(encoding="utf-8"))
                note_events = notes_data.get("notes", [])
            else:
                note_events = []
                
            lyrics_data = []
            lyrics_csv_path = session_dir / "lyrics_split.csv"
            import csv
            if lyrics_csv_path.exists():
                with open(lyrics_csv_path, "r", encoding="utf-8") as f_lyrics:
                    reader = csv.DictReader(f_lyrics)
                    for row in reader:
                        bar = int(row["bar"]) - 1
                        beat = int(row["beat"]) - 1
                        start = float(row["start"])
                        end = float(row["end"])
                        text = row["lyrics"]
                        lyrics_data.append((bar, beat, start, end, text))
                        
            capo = s.get("capo", 0)
            tuning_name = s.get("tuning", "standard")
            base_tuning_list = nextchord_main.TUNINGS.get(tuning_name, nextchord_main.TUNINGS["standard"])
            tuning_list = [p + capo for p in base_tuning_list]
            tuning_dict = {6: tuning_list[0], 5: tuning_list[1], 4: tuning_list[2],
                           3: tuning_list[3], 2: tuning_list[4], 1: tuning_list[5]}
                           
            tab_source = s.get("tab_source", "chord_strum")
            is_solo = (tab_source == "detected_notes")
            if is_solo:
                xml_notes = note_events
            else:
                xml_notes = nextchord_main.generate_chord_strum_notes(structured, bpm=bpm) if structured else note_events
                
            xml_content = nextchord_main.notes_to_musicxml(
                xml_notes,
                beats=v_time_beats if v_time_beats else None,
                chords=structured,
                lyrics=lyrics_data,
                key=detected_key,
                title=title,
                bpm=bpm,
                tuning=tuning_dict,
            )
            musicxml_path = session_dir / "sheet.musicxml"
            musicxml_path.write_text(xml_content, encoding="utf-8")
            
            await session_vol.commit.aio()
            return {"status": "ok", "message": "MusicXML regenerated"}
        except Exception as e:
            print(f"MusicXML regeneration failed: {e}")
            raise HTTPException(status_code=500, detail=f"MusicXML再生成失敗: {e}")

    @fa.get("/result/{session_id}/notes")
    async def get_notes(session_id: str):
        s = load_session(session_id)
        if s is None:
            try:
                await safe_reload_async(session_id)
            except Exception:
                pass
            s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session_dir = Path(s["session_dir"])
        notes_path = session_dir / "notes.json"
        if notes_path.exists():
            return JSONResponse(content=json.loads(notes_path.read_text(encoding="utf-8")))
        return {"notes": [], "tab_source": "chord_strum"}

    @fa.patch("/result/{session_id}/notes")
    async def update_notes(session_id: str, request: Request):
        s = load_session(session_id)
        if s is None:
            try:
                await safe_reload_async(session_id)
            except Exception:
                pass
            s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        body = await request.json()
        new_notes = body.get("notes", [])
        
        session_dir = Path(s["session_dir"])
        notes_path = session_dir / "notes.json"
        if notes_path.exists():
            notes_data = json.loads(notes_path.read_text(encoding="utf-8"))
        else:
            notes_data = {"notes": []}
            
        notes_data["notes"] = new_notes
        notes_path.write_text(json.dumps(notes_data, ensure_ascii=False, indent=2), encoding="utf-8")
        
        await save_session_async(session_id)
        return {"status": "ok", "count": len(new_notes)}

    @fa.get("/result/{session_id}/musicxml")
    @fa.get("/export/{session_id}/musicxml")
    async def get_musicxml(session_id: str):
        s = load_session(session_id)
        if s is None:
            try:
                await safe_reload_async(session_id)
            except Exception:
                pass
            s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session_dir = Path(s["session_dir"])
        xml_path = session_dir / "sheet.musicxml"
        if not xml_path.exists():
            await regenerate_musicxml_endpoint(session_id)
        if xml_path.exists():
            return Response(content=xml_path.read_text(encoding="utf-8"), media_type="application/xml")
        raise HTTPException(status_code=404, detail="MusicXML not found")

    @fa.get("/result/{session_id}/stems/{stem_name}")
    async def get_stem_file(session_id: str, stem_name: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session_dir = Path(s["session_dir"])
        
        for sub in ["htdemucs_6s/converted", "htdemucs/converted", "htdemucs_6s", "htdemucs"]:
            p = session_dir / sub / f"{stem_name}.wav"
            if p.exists():
                return FileResponse(str(p), media_type="audio/wav")
                
        raise HTTPException(status_code=404, detail=f"Stem {stem_name} not found")

    @fa.get("/export/{session_id}/midi")
    async def get_midi(session_id: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session_dir = Path(s["session_dir"])
        midi_path = session_dir / "output.mid"
        if not midi_path.exists():
            try:
                import main as nextchord_main
                nextchord_main.init_models_lazy()
                
                notes_path = session_dir / "notes.json"
                if notes_path.exists():
                    notes_data = json.loads(notes_path.read_text(encoding="utf-8"))
                    note_events = notes_data.get("notes", [])
                else:
                    note_events = []
                    
                bpm = s.get("bpm", 120.0)
                
                from export_utils import create_midi_from_notes
                midi_bytes = create_midi_from_notes(note_events, bpm=bpm)
                midi_path.write_bytes(midi_bytes)
                await session_vol.commit.aio()
            except Exception as e:
                print(f"Failed to generate MIDI: {e}")
                raise HTTPException(status_code=500, detail="MIDI generation failed")
                
        if midi_path.exists():
            return FileResponse(str(midi_path), media_type="audio/midi", filename=f"{s.get('filename', session_id)}.mid")
        raise HTTPException(status_code=404, detail="MIDI not found")

    @fa.get("/export/{session_id}/pdf")
    async def get_pdf(session_id: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session_dir = Path(s["session_dir"])
        
        pdf_path = session_dir / "sheet.pdf"
        if not pdf_path.exists():
            try:
                import main as nextchord_main
                nextchord_main.init_models_lazy()
                
                sd_path = session_dir / "structured_data.json"
                if sd_path.exists():
                    structured = json.loads(sd_path.read_text(encoding="utf-8"))
                else:
                    structured = s.get("result", {}).get("structured_data", [])
                    
                display_phrases = s.get("result", {}).get("display_phrases", [])
                if not display_phrases:
                    display_phrases = s.get("result", {}).get("lyrics_phrases", [])
                    
                title = s.get("filename", session_id)
                artist = s.get("artist", "")
                
                from export_utils import create_pdf_from_chordpro_data
                pdf_bytes = create_pdf_from_chordpro_data(title, artist, structured, display_phrases)
                pdf_path.write_bytes(pdf_bytes)
                await session_vol.commit.aio()
            except Exception as e:
                print(f"Failed to generate PDF: {e}")
                raise HTTPException(status_code=500, detail="PDF generation failed")
                
        if pdf_path.exists():
            return FileResponse(str(pdf_path), media_type="application/pdf", filename=f"{s.get('filename', session_id)}.pdf")
        raise HTTPException(status_code=404, detail="PDF not found")

    @fa.get("/export/{session_id}/gp5")
    async def get_gp5(session_id: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
        session_dir = Path(s["session_dir"])
        gp5_path = session_dir / "tab.gp5"
        
        if gp5_path.exists():
            return FileResponse(str(gp5_path), media_type="application/octet-stream", filename=f"{s.get('filename', session_id)}.gp5")
        raise HTTPException(status_code=404, detail="GP5 file not found")

    class RetuneRequest(BaseModel):
        tuning: str = "standard"
        capo: int = 0
        noise_gate: float = 0.2
        tab_source: Optional[str] = None

    @fa.post("/result/{session_id}/retune")
    async def retune(session_id: str, request: RetuneRequest):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
            
        import main as nextchord_main
        nextchord_main.init_models_lazy()
        
        session_dir = Path(s["session_dir"])
        
        tuning_name = request.tuning
        base_tuning_list = nextchord_main.TUNINGS.get(tuning_name, nextchord_main.TUNINGS["standard"])
        tuning_list = [p + request.capo for p in base_tuning_list]
        tuning_dict = {6: tuning_list[0], 5: tuning_list[1], 4: tuning_list[2],
                       3: tuning_list[3], 2: tuning_list[4], 1: tuning_list[5]}
                       
        notes_path = session_dir / "notes.json"
        if not notes_path.exists():
            raise HTTPException(status_code=404, detail="notes.json not found")
            
        notes_data = json.loads(notes_path.read_text(encoding="utf-8"))
        note_events = notes_data.get("notes", [])
        tab_source = request.tab_source if request.tab_source is not None else notes_data.get("tab_source", "chord_strum")
        notes_data["tab_source"] = tab_source
        
        beats_json_path = session_dir / "beats.json"
        v_time = []
        time_signature = "4/4"
        if beats_json_path.exists():
            beats_info = json.loads(beats_json_path.read_text(encoding="utf-8"))
            v_time = beats_info.get("beats", [])
            time_signature = beats_info.get("time_signature", "4/4")
            
        bpm = s.get("bpm", 120.0)
        detected_key = s.get("key", "C major")
        title = s.get("filename", session_id)
        
        sd_path = session_dir / "structured_data.json"
        structured = None
        if sd_path.exists():
            structured = json.loads(sd_path.read_text(encoding="utf-8"))
        if not structured:
            structured = s.get("result", {}).get("structured_data", [])
            
        lyrics_data = []
        lyrics_csv_path = session_dir / "lyrics_split.csv"
        import csv
        if lyrics_csv_path.exists():
            with open(lyrics_csv_path, "r", encoding="utf-8") as f_lyrics:
                reader = csv.DictReader(f_lyrics)
                for row in reader:
                    bar = int(row["bar"]) - 1
                    beat = int(row["beat"]) - 1
                    start = float(row["start"])
                    end = float(row["end"])
                    text = row["lyrics"]
                    lyrics_data.append((bar, beat, start, end, text))
                    
        is_solo = (tab_source == "detected_notes")
        if is_solo:
            xml_notes = note_events
        else:
            xml_notes = nextchord_main.generate_chord_strum_notes(structured, bpm=bpm) if structured else note_events
            
        tab_data = nextchord_main.notes_to_tab_data(xml_notes, v_time, tuning_dict)
        
        xml_content = nextchord_main.notes_to_musicxml(
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
        musicxml_path.write_text(xml_content, encoding="utf-8")
        
        gp5_bytes = None
        if nextchord_main.notes_to_gp5 is not None:
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
            gp5_bytes = nextchord_main.notes_to_gp5(
                gp5_notes,
                beats=v_time if v_time else None,
                bpm=bpm,
                title=title,
                tuning=tuning_list,
                time_signature=time_signature,
                noise_gate=request.noise_gate,
            )
            gp5_path = session_dir / "tab.gp5"
            gp5_path.write_bytes(gp5_bytes)
            
        notes_data["tab"] = tab_data
        notes_path.write_text(json.dumps(notes_data, ensure_ascii=False, indent=2), encoding="utf-8")
        
        s["tuning"] = tuning_name
        s["capo"] = request.capo
        s["noise_gate"] = request.noise_gate
        s["tuning_list"] = tuning_list
        await save_session_async(session_id)
        
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

    @fa.post("/result/{session_id}/cut")
    async def cut_noise(session_id: str, request: CutRequest):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
            
        import main as nextchord_main
        nextchord_main.init_models_lazy()
        
        session_dir = Path(s["session_dir"])
        
        notes_path = session_dir / "notes.json"
        if not notes_path.exists():
            raise HTTPException(status_code=404, detail="notes.json not found")
            
        notes_data = json.loads(notes_path.read_text(encoding="utf-8"))
        note_events = notes_data.get("notes", [])
        tab_source = notes_data.get("tab_source", "chord_strum")
        
        beats_json_path = session_dir / "beats.json"
        v_time = []
        time_signature = "4/4"
        if beats_json_path.exists():
            beats_info = json.loads(beats_json_path.read_text(encoding="utf-8"))
            v_time = beats_info.get("beats", [])
            time_signature = beats_info.get("time_signature", "4/4")
            
        bpm = s.get("bpm", 120.0)
        title = s.get("filename", session_id)
        tuning_list = s.get("tuning_list", [40, 45, 50, 55, 59, 64])
        
        is_solo = (tab_source == "detected_notes")
        gp5_bytes = None
        if nextchord_main.notes_to_gp5 is not None:
            if is_solo:
                gp5_notes = note_events
            else:
                tab_data = notes_data.get("tab", [])
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
            gp5_bytes = nextchord_main.notes_to_gp5(
                gp5_notes,
                beats=v_time if v_time else None,
                bpm=bpm,
                title=title,
                tuning=tuning_list,
                time_signature=time_signature,
                noise_gate=request.noise_gate,
            )
            gp5_path = session_dir / "tab.gp5"
            gp5_path.write_bytes(gp5_bytes)
            
        s["noise_gate"] = request.noise_gate
        await save_session_async(session_id)
        
        return {
            "status": "ok",
            "noise_gate": request.noise_gate,
            "gp5_size": len(gp5_bytes) if gp5_bytes else 0,
        }

    @fa.get("/result/{session_id}/waveform")
    async def get_waveform(session_id: str):
        try:
            await safe_reload_async(session_id)
        except Exception:
            pass
        s = load_session(session_id)
        if s is None:
            raise HTTPException(status_code=404, detail="Session not found")
            
        import main as nextchord_main
        nextchord_main.init_models_lazy()
        
        wav_path = Path(s["wav_path"])
        
        from waveform_utils import generate_waveform
        data = generate_waveform(str(wav_path), n_points=2000)
        return data

    @fa.get("/chord-audio/{chord_name}")
    async def get_chord_audio(
        chord_name: str,
        octave: int = 4,
        duration: float = 1.8,
    ):
        import main as nextchord_main
        nextchord_main.init_models_lazy()
        from chord_synth import synthesize_chord
        import urllib.parse
        chord_name = urllib.parse.unquote(chord_name)
        wav_bytes = synthesize_chord(chord_name, octave=octave, duration=duration)
        return Response(content=wav_bytes, media_type="audio/wav")

    @fa.get("/health")
    async def health_check():
        return {"status": "ok", "environment": "modal"}

    return fa
