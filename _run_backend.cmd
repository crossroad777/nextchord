@echo off
set TORCH_CUDNN_V8_API_DISABLED=1
cd /d D:\Music\nextchord\fastapi-backend
D:\Music\nextchord\venv312\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
