@echo off
title NextChord
setlocal EnableDelayedExpansion

echo.
echo  ========================================
echo    NextChord Launcher
echo  ========================================
echo.

echo  [1/5] Killing old processes...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo        kill PID %%a on port 8000
    taskkill /F /T /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    echo        kill PID %%a on port 5173
    taskkill /F /T /PID %%a >nul 2>&1
)
taskkill /F /FI "WINDOWTITLE eq NC-Backend" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq NC-Frontend" >nul 2>&1
echo        Done.
echo.

echo  [2/5] Checking ports...
set /a RETRY=0
:CHECK_PORTS
set PORT_BUSY=0
netstat -ano 2>nul | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if !errorlevel!==0 set PORT_BUSY=1
netstat -ano 2>nul | findstr ":5173 " | findstr "LISTENING" >nul 2>&1
if !errorlevel!==0 set PORT_BUSY=1
if "!PORT_BUSY!"=="0" goto PORTS_FREE
set /a RETRY+=1
if !RETRY! GEQ 10 (
    echo        [ERROR] Ports still busy. Aborting.
    pause
    exit /b 1
)
echo        Ports busy, retry !RETRY!...
timeout /t 1 /nobreak >nul
goto CHECK_PORTS
:PORTS_FREE
echo        Ports free.
echo.

echo  [3/5] Clearing Vite cache...
set VITE_CACHE=D:\Music\nextchord\nextchord-ui\node_modules\.vite
if exist "%VITE_CACHE%" (
    rmdir /S /Q "%VITE_CACHE%"
    echo        Cleared.
) else (
    echo        Skipped.
)
echo.

echo  [4/5] Starting Backend (port 8000)...
start /MIN "NC-Backend" "D:\Music\nextchord\_run_backend.cmd"
set /a WAIT=0
:WAIT_BACKEND
timeout /t 2 /nobreak >nul
set /a WAIT+=2
curl -sf -o nul http://localhost:8000/health >nul 2>&1
if !errorlevel!==0 (
    echo        Backend ready [!WAIT!s]
    goto BACKEND_OK
)
if !WAIT! GEQ 90 (
    echo        [WARN] Backend timeout 90s
    goto BACKEND_OK
)
echo        Waiting... [!WAIT!s]
goto WAIT_BACKEND
:BACKEND_OK
echo.

echo  [5/5] Starting Frontend (port 5173)...
start /MIN "NC-Frontend" "D:\Music\nextchord\_run_frontend.cmd"
set /a WAIT=0
:WAIT_FRONTEND
timeout /t 2 /nobreak >nul
set /a WAIT+=2
curl -sf -o nul http://localhost:5173 >nul 2>&1
if !errorlevel!==0 (
    echo        Frontend ready [!WAIT!s]
    goto FRONTEND_OK
)
if !WAIT! GEQ 30 (
    echo        [WARN] Frontend timeout
    goto FRONTEND_OK
)
goto WAIT_FRONTEND
:FRONTEND_OK
echo.

start "" http://localhost:5173

echo  ========================================
echo    NextChord is running!
echo    Backend:  http://localhost:8000
echo    Frontend: http://localhost:5173
echo    Press any key to STOP servers.
echo  ========================================
echo.
pause >nul

echo  Stopping...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /F /T /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5173 " ^| findstr "LISTENING"') do taskkill /F /T /PID %%a >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq NC-Backend" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq NC-Frontend" >nul 2>&1
echo  Stopped.
timeout /t 2 /nobreak >nul