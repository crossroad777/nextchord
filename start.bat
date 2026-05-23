@echo off
title NextChord

echo.
echo  ========================================
echo    NextChord  Start
echo  ========================================
echo.

:: --- Stop existing processes ---
echo [1/3] Stopping old processes...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1
timeout /t 3 /nobreak >nul
echo    Done.

:: --- Clear Vite cache ---
echo [2/3] Clearing cache...
if exist "D:\Music\nextchord\nextchord-ui\node_modules\.vite" (
    rmdir /S /Q "D:\Music\nextchord\nextchord-ui\node_modules\.vite"
)
echo    Done.

:: --- Start servers ---
echo [3/3] Starting servers...
set TORCH_CUDNN_V8_API_DISABLED=1
start /MIN "NC-Back" cmd /c "cd /d D:\Music\nextchord\fastapi-backend & set TORCH_CUDNN_V8_API_DISABLED=1 & D:\Music\nextchord\venv312\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"
timeout /t 4 /nobreak >nul
start /MIN "NC-Front" cmd /c "cd /d D:\Music\nextchord\nextchord-ui & npm run dev"

echo.
echo  Backend:  http://localhost:8000
echo  Frontend: http://localhost:5173
echo.
echo  ========================================
echo  Press any key to STOP all servers.
echo  ========================================

pause >nul

taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1
echo Stopped.
timeout /t 2 /nobreak >nul
