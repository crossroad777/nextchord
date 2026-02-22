# NextChord 引継ぎドキュメント

## 2026-02-22 20:22 時点のスナップショット

### Git状態

- **最新コミット**: `565e687` (main)
- **総コミット数**: 71
- **開発期間**: 2026-02-21 〜 2026-02-22
- **直近コミット履歴** (最新20件):
  - `565e687` docs: 歌詞バグ修正の記録をHANDOVER.mdに追加
  - `c04c296` fix: 歌詞ハルシネーション判定を緩和 (no_speech_prob 0.5→0.8)
  - `c45ca1a` docs: 本セッション全作業記録をHANDOVER.mdに追記
  - `6cda321` fix: scrollbar-width削除で互換性警告解消
  - `455c416` chore: scrollbar-width警告に説明コメント追加
  - `4ba374e` fix: fit-content警告解消 - white-space:nowrapで同等効果
  - `b7a568f` fix: リントエラー修正 - MD040/MD060/CSSフォールバック
  - `2cbf7d1` docs: 完了タスク更新
  - `acd7f25` feat: SSEリアルタイム進捗通知 - EventSource刷新
  - `42c8cbd` feat: InstrumentPanel全面改善 - 90+コード・フレットドット
  - `a083679` docs: テスト数を175件に更新
  - `b79a10a` test: phrase_processor.py 17件追加 (175テスト全通過)
  - `e44e285` test: lyrics_postprocess.py 23件追加 (158テスト全通過)
  - `fc7d8c7` test: export_utils.py 28件追加 (135テスト全通過)
  - `524c8dc` perf: テーマ切替トランジション最適化 (FOUC防止)
  - `18a2715` test: tab_generator.py 49件追加 (107テスト全通過)
  - `dd4aa8d` docs: HANDOVER.md全タスク完了
  - `35e0bb3` feat: リボンに楽器切替ボタン追加
  - `61579a5` feat: ダークモード/ライトモード切替、ピアノキーボード表示
  - `20dd7de` chore: 一時ファイル削除

---

## プロジェクト構成

```text
nextchord/
├── .env / .env.example / .gitignore
├── .dockerignore            # Dockerビルド最適化
├── Dockerfile               # HF Spaces用マルチステージビルド
├── README.hf.md             # HF Spaces用README (SDK=docker)
├── HANDOVER.md              # 本文書
├── README.md / RULES.md
├── requirements.txt / pyproject.toml
│
├── fastapi-backend/         # バックエンド (Python/FastAPI)
│   ├── main.py              # APIサーバー (~1,180行) + フロントエンド配信
│   ├── pipeline.py          # 解析パイプライン (825行)
│   ├── chord_processing.py  # コード処理・キー推定 (515行)
│   ├── tab_generator.py     # MusicXML/コード生成 (~1,170行)
│   ├── note_transcription.py # 音符検出・TAB生成 (1,232行)
│   ├── phrase_processor.py  # Janome形態素解析によるフレーズ分割 (221行)
│   ├── lyrics_postprocess.py # Whisper歌詞後処理・ハルシネーション除去 (134行)
│   ├── export_utils.py      # エクスポート機能 (447行)
│   └── waveform_utils.py    # 波形データ生成 (61行)
│
├── nextchord-ui/            # フロントエンド (React/Vite)
│   └── src/
│       ├── App.jsx          # メインアプリケーション (~1,172行)
│       ├── index.css        # グローバルCSS (~763行)
│       ├── index.html
│       ├── main.tsx / vite.config.ts / vite-env.d.ts
│       └── components/
│           ├── ChordLyricsView.jsx  # テキストビュー (447行)
│           ├── TabView.jsx          # TABビュー (~1,098行)
│           ├── InstrumentPanel.jsx   # 楽器パネル (~441行)
│           ├── BeatGrid.jsx         # ビートグリッド (190行)
│           ├── ScoreView.jsx        # スコアビュー (57行)
│           └── AssetChecker.jsx     # アセットチェッカー (27行)
│
├── scripts/
│   └── extract_chords.py
│
└── uploads/                 # 解析結果保存 (gitignore対象)
```

---

## 主要機能の現在の状態

### ✅ 完了・安定

| 機能 | 状態 |
| ------ | ------ |
| YouTube URL / ファイルアップロード | 安定稼働 |
| 音声解析パイプライン (Beats/Key/Chords/Whisper/Notes) | 並列実行、約96秒 |
| TABビュー (AlphaTab) | カーソル同期・自動スクロール動作 |
| テキストビュー (U-FRETスタイル) | 等幅フォント2行表示（コード行＋歌詞行） |
| コード手動編集 | クリックで編集、バックエンド保存 |
| 歌詞手動編集 | クリックで編集、バックエンド保存 |
| キー推定 | 3手法コンセンサス投票（五度圏距離ベース） |
| コード正規化 | エンハーモニック統一のみ（強制変換廃止） |
| 日本語フレーズ分割 | Janome形態素解析、自然な行分割 |
| 歌詞後処理 | ハルシネーション除去、全角半角統一 |
| Demucs音源分離 | GPU対応、ギターソロ検出 |
| MusicXML生成 | 3パート + テクニック記号(H/P/Slide/Bend等) |
| カポ機能 | 全ビュー対応（スコア/グリッド/テキスト） |
| 転調機能 | 全ビュー対応（MusicXMLピッチ書き換え） |
| ダークモード/ライトモード | Sun/Moonトグル、CSS変数ベース、localStorage保存 |
| 楽器切替 (Guitar/Piano) | ヘッダーリボンにボタン追加 |
| InstrumentPanel | コードDB90+、スマートフォールバック、フレットドット |
| SSEリアルタイム進捗 | EventSourceベース、フォールバック付き |
| セッション永続化 | localStorage経由でブラウザリロード後も復帰 |
| エクスポート (MIDI/MusicXML/テキスト) | ドロップダウンメニュー、ファイルダウンロード |
| エクスポート (PDF) | プレミアムデザイン、FileResponse配信 |

### ⚠️ 既知の制約

1. **Whisper日本語認識**: medium モデル使用。一部誤認識あり（手動編集で対応）
2. **処理時間**: 約96秒（ボトルネック: Notes=Demucs+basic-pitch、ハードウェア依存）
3. **コード検出**: madmom依存。近い音程のコード（例: G vs F#m）の精度に限界
4. **歌詞ハルシネーション**: 閾値緩和済み(0.5→0.8)だが、音楽バックグラウンドで誤判定の可能性あり

---

## 技術スタック

### バックエンド

- **Python 3.12** + FastAPI + Uvicorn (--reload)
- **madmom**: ビート・キー・コード検出
- **Whisper medium**: 歌詞認識 (GPU/CUDA)
  - `initial_prompt`: 日本語歌詞認識精度向上
  - `condition_on_previous_text=False`: 繰り返しハルシネーション防止
- **Demucs**: 音源分離
- **basic-pitch**: 音符検出
- **Janome**: 日本語形態素解析（フレーズ分割）

### フロントエンド

- **React** (Vite) + vanilla CSS
- **AlphaTab**: TAB譜レンダリング
- **WaveSurfer.js**: 波形表示・再生

---

## サーバー起動方法

### ローカル開発

```bash
# バックエンド
cd fastapi-backend
..\venv312\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# フロントエンド
cd nextchord-ui
npm run dev
```

- フロントエンド: <http://localhost:5173/>
- バックエンドAPI: <http://localhost:8000/>

### HF Spaces デプロイ

```bash
# 1. huggingface.co/new-space で Docker SDK の Space を作成
# 2. README.hf.md を README.md としてコピー
copy README.hf.md README.md
# 3. HF Spaces リポジトリにプッシュ
git remote add hf https://huggingface.co/spaces/YOUR_USERNAME/nextchord
git add .
git commit -m "Deploy NextChord to HF Spaces"
git push hf main
```

**デプロイ構成:**

- Dockerマルチステージビルド (node:20 → python:3.12-slim)
- フロントエンド: Viteビルド → `frontend-dist/` に出力
- バックエンド: FastAPIが `frontend-dist/` を静的配信 + SPA catch-all
- API_BASE: 本番では空文字列（同一オリジン）、開発では `http://localhost:8000`
- ポート: 7860 (HF Spaces標準)

---

## セッション履歴

### セッション 2026-02-22 夜 (20:00〜)

#### エクスポート機能の修正

- **問題**: エクスポートドロップダウンが表示されない、クリックが効かない
- **原因1**: `.nc-ribbon` の `overflow-x: auto` がabsolute配置のドロップダウンを切り取っていた
- **原因2**: ドロップダウン内のクリックが親要素にバブルアップしてメニューが即閉じ
- **修正**: `.nc-ribbon` overflow → `visible`、`stopPropagation()` 追加、外部クリックで閉じる `useEffect` 追加
- **結果**: MIDI/MusicXML/テキスト/PDFエクスポートが正常動作

#### InstrumentPanel修正

- **問題**: 楽器パネルが表示されない、「No Diagram」が出続ける
- **原因**: `InstrumentPanel` がJSXでレンダリングされていなかった。`currentChord` が再生中のみ更新されていた
- **修正**: App.jsx に右サイドバーとして追加、`useEffect` で `currentTime` ベースの常時更新を追加
- **結果**: ギター/ピアノ切替、リアルタイムコード表示が動作

#### ギターコード図の水平化

- **問題**: ギターコード図が縦向き表示
- **修正**: `GuitarDiagram` コンポーネントを書き直し、弦が水平・フレットが垂直のレイアウトに変更
- **結果**: 演奏者目線の自然な横向き表示

#### HF Spaces デプロイ準備

| ファイル | 内容 |
| ------ | ------ |
| `Dockerfile` | マルチステージビルド (node:20 + python:3.12-slim)、フロントエンドビルド → FastAPI静的配信 |
| `README.hf.md` | HF Spaces メタデータ (SDK=docker, port=7860) |
| `.dockerignore` | node_modules/venv/uploads等を除外 |
| `requirements.txt` | 本番用依存リスト更新 |
| `main.py` | フロントエンド静的配信 + SPA catch-all ルート追加 |
| `App.jsx` / `TabView.jsx` | `API_BASE` を同一オリジン対応 (`VITE_API_URL=""` で空文字許容) |

**デプロイ手順:**

1. `huggingface.co/new-space` で Docker SDK の Space 作成
2. `README.hf.md` → `README.md` にコピー
3. `git push hf main` でデプロイ (ビルド10-15分)

#### 未解決: スコアの休符表示

- **問題**: TABスコア表示で不要な休符記号が表示される
- **試行1**: TABトラックのみ表示 → コード記号・歌詞・五線譜が消失（Part 1に含まれるため）
- **試行2**: コード/歌詞をPart 2（TAB）にも追加する修正 → AlphaTabがTABスタッフ上でharmony/lyricsを表示しない
- **状態**: 元の全トラック表示に戻し、休符は残存。根本対処は `_build_melody_measure` の `<forward>` 要素とAlphaTabの表示挙動の調査が必要
- **考えられるアプローチ**: AlphaTabのnotation設定で休符非表示にする、またはMusicXMLのPart 1構造を変更

### セッション 2026-02-22 夕方 (17:00〜)

#### バグ修正: 歌詞が出ない問題

- **原因**: `pipeline.py` のハルシネーション検出で `no_speech_prob > 0.5` の全セグメント一致で歌詞全削除していた。音楽バックグラウンドがあると `no_speech_prob` が高くなり、正常な歌詞も削除されていた
- **修正1** (`c04c296`): 閾値を `0.5 → 0.8` に緩和、全セグメント一致 → `90%以上` に変更
- **修正2**: 上記修正のコードが後続の編集で消失していたため復元。セグメント単位マーカー除去の後に `no_speech_prob` 全体判定を追加
- **確認待ち**: 再アップロードで歌詞表示を確認予定

### セッション 2026-02-22 昼 (13:56)

#### 1. バックエンドリファクタリング

| 項目 | 詳細 |
| ------ | ------ |
| `run_pipeline` 分離 | `main.py` → `pipeline.py` に抽出。グローバル変数を `_ctx` 辞書で受け渡し |
| main.py 行数削減 | 2,300行 → 1,047行 (**55%削減**) |

#### 2. ユニットテスト (58 → 175テスト: 3倍増)

| テストファイル | テスト数 | 対象モジュール |
| ------ | ------ | ------ |
| test_chord_processing.py | 36 | コード処理・キー正規化 |
| test_note_transcription.py | 22 | ノート検出・MIDI変換 |
| test_tab_generator.py | 49 | TAB譜生成・MusicXML・ギターポジション |
| test_export_utils.py | 28 | MIDI/PDF/テキストエクスポート |
| test_lyrics_postprocess.py | 23 | 歌詞後処理・ハルシネーション除去 |
| test_phrase_processor.py | 17 | Janome形態素解析・フレーズ分割 |
| **合計** | **175** | **全テスト通過** |

#### 3. フロントエンドUI改善

| 機能 | 詳細 |
| ------ | ------ |
| ダークモード/ライトモード | Sun/Moonトグル、CSS変数ベース、localStorage保存 |
| テーマ切替パフォーマンス | `data-theme-transitioning` 属性で切替時のみトランジション適用、FOUC防止 |
| 楽器切替 (Guitar/Piano) | ヘッダーリボンにボタン追加 |
| InstrumentPanel全面改善 | コードDB 14→90+、スマートフォールバック(異名同音)、フレットドット(3/5/7/9/12fr)、バレー幅自動計算、弦太さグラデーション |
| ピアノコード動的生成 | 15種のコードフォーミュラで任意コード自動生成 (固定DBから脱却) |

#### 4. SSEリアルタイム進捗通知

| 項目 | 詳細 |
| ------ | ------ |
| バックエンド | `/status/{sid}/stream` SSEエンドポイント追加 (asyncio + StreamingResponse) |
| フロントエンド | `EventSource` ベース、0.8秒間隔でリアルタイム更新 |
| フォールバック | SSE切断時は自動でレガシーポーリングに切替 |
| 既存API維持 | `/status/{sid}` (GET) はそのまま残存 |

#### 5. リントエラー全解消

| 修正 | ファイル | 内容 |
| ------ | ------ | ------ |
| MD040 | HANDOVER.md | コードブロックに `text` 言語指定 |
| MD060 | HANDOVER.md | テーブルパイプ周りのスペース統一 |
| compat-api/css | index.css | `fit-content` → `white-space: nowrap` に置換 |
| compat-api/css | index.css | `scrollbar-width` 削除 (`::-webkit-scrollbar` でカバー) |

### セッション 2026-02-22 朝 (10:45)

#### カポ・転調機能の実装

- カポUI: ◀▶ボタンで0-9の範囲で増減
- **全ビュー対応**: スコア/グリッド/テキストでカポ・転調が動作
- スコアビュー: MusicXMLの`<pitch>`, `<fret>`, `<harmony>`, `<fifths>`を正規表現で直接書き換え
- グリッド/テキスト: `transpose - capo` で実効値を計算し渡す
- ヘッダーのKey表示にもカポ反映 (`Key: Am (Capo 3)`)

#### キー推定の大幅改善

- **HPSS倍音分離**: `librosa.effects.harmonic()` でアタック音を除去
- **チューニング推定**: `librosa.estimate_tuning()` でYouTube音源のピッチずれを補正
- **CQT+STFT統合**: 両方のchromaを50:50で統合
- **冒頭/終結部重み付け**: トニックが強い区間を2倍重み
- **3手法コンセンサス投票**: 五度圏距離ベース（平行調考慮）
  - madmom + chord が五度圏で近い場合、chromaの外れ値を排除
  - 結果: F# major → **D minor** に改善（正解Cmから2半音差）

#### テクニック記号の有効化

- `_add_technique_notations` を実装（以前は `return` で空だった）
- ハンマリング(H), プルオフ(P), スライド, ベンド, ビブラート, ハーモニクス, タッピング(T), パームミュート(P.M.), アクセント, スタッカート, トレモロ
- テスト曲(Anji)で215個のテクニック要素がMusicXMLに出力

#### エクスポート強化

- MIDI: 実BPM+ギターノート第2トラック
- PDF: プレミアムデザイン

#### ノート精度向上

- BPM連動ノート長: 高BPM/低BPMで動的調整
- 5度倍音除去: 基音と同時に鳴る偽ノートを信頼度比較で除去
- ゴーストノート除去: 前後音量比較で微弱ノイズ除去
- ピッチベンド情報活用: basic-pitchのbendデータをflagとして付加
- ベンチマーク結果: 715→584ノート(-18.3%), 信頼度+0.67%

#### コード検出精度向上

- テンプレート8種、CQT/STFT統合、メディアンフィルタ
- madmom+librosaアンサンブル
- レアコード統合: 出現率2%未満で同ルート類似コードがあれば多数派に統合

#### 自動スクロール改善

- ユーザーの手動スクロール(wheel/touch)を検知して3秒間一時停止→自動復帰
- 再生開始時にリセット

#### main.py リファクタリング

- `chord_processing.py` を新規作成（約515行）
- `pipeline.py` を新規作成（約825行）
- main.py: 2,300行 → 1,047行（**55%削減**）

### セッション 2026-02-22 深夜 (02:04)

#### コード検出の修正

- `_CHORD_CORRECTION` (強制ダイアトニック変換) を完全廃止
- `standardize_chord` をエンハーモニック統一 + チャタリング除去のみに変更
- `estimate_key_from_chords` に冒頭コードのトニックボーナス追加
- 正規化パイプラインの二重実行を1回に統合
- G→F#m 等の誤変換を解消

#### 日本語歌詞の強化

- Whisper設定: `initial_prompt`, `condition_on_previous_text=False`, `no_speech_threshold=0.4`
- `lyrics_postprocess.py` 新規作成（ハルシネーション除去、全角半角統一）
- `phrase_processor.py` 新規作成（Janome形態素解析によるフレーズ分割）
  - 接続助詞(から/けど)の前で切らないペナルティ
  - 非自立形容詞(よ)の前で切らないペナルティ
  - target_chars 25→30に拡大
- 歌詞インライン編集機能追加

#### 不要ファイル掃除

- デバッグスクリプト、旧パイプライン(step0〜5)、未使用モデル等 36ファイル削除
- uploads 全クリア (3.2GB解放)

### セッション 2026-02-21 夜 (22:55)

#### カーソル同期の修正 (TabView.jsx)

- **問題**: TABスコアの青カーソルの開始位置がずれていた
- **原因**: `tickToMs` が固定テンポ計算を使用しており、beat_times（実際のオーディオビート検出結果）を使っていなかった
- **修正内容**:
  - `tickToMs` をbeat_timesベースの計算に変更
  - AlphaTabの内部BeatBoundsからtickを直接抽出するように変更
  - `firstBeatRef` の不要な減算を除去
  - `main.py` の `StatusResponse` に `beat_times` と `first_beat_time` フィールドを追加

#### ChordLyricsView の U-FRETスタイル化

- **問題**: コードが歌詞の間に混ざる、間延びする、不自然な位置で歌詞が分割される
- **修正内容**:
  - 等幅フォント（BIZ UDGothic）による2行表示方式に変更
    - 行1: コード行（半角スペースで位置合わせ、`white-space: pre`）
    - 行2: 歌詞行（自然なテキスト）
  - 全角文字=2カラム、半角文字=1カラムの法則で位置合わせ
  - `lyrics_phrases` のテキストをそのまま使用（ビート単位の再構築をやめた）

#### 日本語フレーズの自然分割 (`processPhrasesForDisplay`)

- **問題**: Whisperの出力フレーズ境界が日本語の単語境界と一致しない（例: 「やがて」→「やが|て」に分割）
- **修正内容**: 2パス方式を実装
  - **Pass 1**: gap < 1秒の連続フレーズを全て結合してブロック化
  - **Pass 2**: 長いブロック（30文字超）を `findSplitPoint` で自然な日本語位置で再分割
    - 高優先: 句読点の後
    - 中優先: 助詞・て形の後（は、が、を、に、で、と、も、の、て等）
    - 低優先: カタカナ→ひらがな/漢字の境界

### セッション 2026-02-21 日中〜夕方

#### 基盤構築 (v1.0.0 〜 v1.0.2)

- basic-pitch ONNX修正、GPUパイプライン構築、包括的ログ追加
- **クリティカル修正**: reanalyzeがother.wavに対してWhisper/Beats/Key実行していたバグ修正

#### TAB譜生成 (v1.1.x)

- **v1.1.0**: コードベースのTAB譜生成 + コード進行からのキー推定
- **v1.1.1**: 歌詞/ノートの小節アラインメント修正（ビートカウント基準）
- **v1.1.2**: 単語レベル歌詞タイムスタンプ（Whisper word_timestamps）
- **v1.1.3**: コードハーモニー配置修正（小節頭ではなく正確なビート位置に配置）

#### 3ビューモード実装 (v1.2.x)

- **v1.2.0**: Grid/Score/Text の3ビューモード追加、U-FRETスタイルテキストビュー
- **v1.2.1**: テキストビューからセクション除去、タイトル/アーティストヘッダー追加
- **v1.2.2**: テキストビュー書き直し（小節レベルデータマッピング、自動スクロール、アクティブハイライト）
- **v1.2.3**: Whisperフレーズセグメントによる自然な日本語テキスト表示
- **v1.2.4**: 4小節フレーズグルーピングで日本語テキスト分断を防止

#### スコアビュー修正

- スコア上部パディング調整（コードシンボル切れ防止）
- Guitar Standard Tuning / トラック名をスコアヘッダーから非表示化
- クロスメジャーのコード重複排除、歌詞-ノート間隔拡大
- AlphaTabカーソル/選択アーティファクト非表示化
- 休符ノートを `<forward>` 要素に置換（休符記号の非表示化）
- カーソル座標アラインメントのためのパディング内部移動

#### その他の機能追加

- セッション永続化: localStorage経由でブラウザリロード後も復帰
- インラインコード編集: クリックで編集、空欄で削除、バックエンド自動保存
- タイトル表示改善: 長いタイトルの切り詰め解消、Key/BPMバッジ右寄せ
- 冗長アップロードボタン削除

---

## 残タスク

### 完了済み ✅

- ~~自動スクロール改善~~ → ユーザー手動スクロール3秒一時停止
- ~~レアコード統合~~ → 出現2%未満を多数派に吸収
- ~~倍音除去フィルタ~~ → 1/2oct + 5度倍音除去
- ~~エクスポート強化~~ → MIDI実BPM+ギターノート第2トラック、PDFプレミアムデザイン
- ~~main.py分割~~ → 2,300→1,047行 **(55%削減)** chord_processing+pipeline分離
- ~~BPM連動ノート長~~ → 高BPM/低BPMで動的調整
- ~~ゴーストノート除去~~ → 前後音量比較で微弱ノイズ除去
- ~~ピッチベンド情報活用~~ → basic-pitchのbendデータをflagとして付加
- ~~ノート精度検証~~ → ベンチマーク実行: 715→584ノート(-18.3%), 信頼度+0.67%
- ~~コード検出精度~~ → テンプレート8種、CQT/STFT統合、madmom+librosaアンサンブル
- ~~テスト追加~~ → **175テスト全通過** (chord_processing 36 + note_transcription 22 + tab_generator 49 + export_utils 28 + lyrics_postprocess 23 + phrase_processor 17)
- ~~run_pipeline分離~~ → pipeline.py (ctx辞書パターン)
- ~~UI/UX改善~~ → ダークモード/ライトモード切替、楽器切替(ギター/ピアノ)、コードDB60+、ピアノキーボード表示
- ~~パフォーマンス~~ → Demucsキャッシュ実装済み、GPU順序最適化(Whisper→Demucs)
- ~~ギター指板改善~~ → スマートフォールバック(異名同音対応)、コードDB90+、フレットドット、バレー幅自動計算
- ~~リアルタイム進捗~~ → SSE(Server-Sent Events)でポーリング廃止、フォールバック付き
- ~~カーソル同期~~ → beat_timesベースのtickToMs、BeatBounds直接抽出
- ~~U-FRETスタイル~~ → 等幅2行表示、全角/半角カラム計算
- ~~日本語フレーズ分割~~ → 2パス方式(結合→自然分割)、形態素解析ペナルティ
- ~~スコアビュー修正~~ → パディング、カーソル非表示、休符→forward置換
- ~~セッション永続化~~ → localStorage
- ~~歌詞ハルシネーション~~ → 閾値0.5→0.8緩和、90%以上一致に変更

### 今後の改善候補

1. **HF Spacesデプロイ**: 準備完了、プッシュ待ち
2. **スコア休符修正**: AlphaTabの休符表示を根本対処
3. **フレット精度の微調整**: 特殊なコード（add9/テンション系）の指板表示
4. **WebSocket双方向通信**: リアルタイムストリーミング解析（現SSEの発展型）
5. **歌詞表示の再確認**: ハルシネーション閾値緩和後の動作確認
6. **Whisperモデルサイズ最適化**: HF Spaces無料枠(16GB RAM)でmediumモデルが動くか要確認
