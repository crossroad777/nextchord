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

1. バックエンドを起動する

```
cd c:\Users\kotan\Desktop\nextchord\fastapi-backend
..\venv312\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> ⚠️ 注意: fastapi-backend/venv (Python 3.13) ではなく venv312 (Python 3.12) を使用すること。
> madmomの `RNNBeatProcessor` がPython 3.13の `collections.MutableSequence` 削除により動作しないため。

1. フロントエンドを起動する

```
cd c:\Users\kotan\Desktop\nextchord\nextchord-ui
npm run dev
```

1. ブラウザで <http://localhost:5173> を開いて動作確認する
