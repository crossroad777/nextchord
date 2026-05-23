@echo off
chcp 65001 > nul
title NextChord 統合一発起動

echo =======================================
echo NextChord - 統合一発起動（Vite強制終了対策版）
echo =======================================
echo.
echo パイプラインをPythonベースで安定稼働させます。
echo このウィンドウを閉じると両方のプロセスが終了します。
echo.

D:\Music\nextchord\venv312\Scripts\python.exe D:\Music\nextchord\start_servers.py
pause
