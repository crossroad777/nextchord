@echo off
title NextChord Stop
echo Stopping NextChord...
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1
echo Done.
timeout /t 2 /nobreak >nul
