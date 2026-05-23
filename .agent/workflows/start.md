---
description: nextchordプロジェクトの起動と開発再開
---

## 起動手順

// turbo-all

1. HANDOVER.md を読んで前回の作業状態を把握する

```
cat c:\Users\kotan\Desktop\nextchord\HANDOVER.md
```

1. 既存プロセスをクリーンアップする（前回セッションの残留プロセスがポートを占有して起動失敗するため）

```
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
```

1. バックエンドを起動する（`--reload`付きでコード変更時は自動リロード）

```
cd c:\Users\kotan\Desktop\nextchord\fastapi-backend
..\venv312\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> ⚠️ 注意: fastapi-backend/venv (Python 3.13) ではなく venv312 (Python 3.12) を使用すること。
> madmomの `RNNBeatProcessor` がPython 3.13の `collections.MutableSequence` 削除により動作しないため。

> ⚠️ 重要: `--reload` により `main.py`, `tab_generator.py`, `pipeline.py` 等の変更は自動反映されます。
> サーバーの手動再起動は通常不要です。再起動が必要な場合は必ず先にポート8000のプロセスをキルしてください。

1. フロントエンドを起動する

```
cd c:\Users\kotan\Desktop\nextchord\nextchord-ui
npm run dev
```

1. ブラウザで <http://localhost:5173> を開いて動作確認する

## サーバー再起動（必要な場合のみ）

> 通常は `--reload` で自動反映されるため不要。依存パッケージの追加やライフスパンの変更時のみ必要。

// turbo-all

1. 既存のバックエンドプロセスをすべて停止する

```
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
```

1. 新しいバックエンドを起動する

```
cd c:\Users\kotan\Desktop\nextchord\fastapi-backend
..\venv312\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
