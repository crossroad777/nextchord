# NextChord 引継書

最終更新: 2026-03-03 07:50

## 新規データセット追加 (2026-03-03)

全て `datasets/` フォルダに展開済み:

| データセット | サイズ | ファイル数 | 用途 |
| --- | --- | --- | --- |
| IDMT-SMT-Guitar V2 | 1.3GB | 3,885 | テクニック付きギター音源(bend/slide/vibrato/harmonic/dead) |
| AG-PT-set | 6.4GB | 9(zip内) | 12種テクニック, 15h, 32K notes |
| GuitarSet hex-debleeded | 3.4GB | 360 | per-string弦別分離音声（弦推定学習用） |
| GuitarSet annotation | 39MB | 360 | ピッチ/弦/フレット/コード/ビートアノテーション |
| GuitarSet mono-mic | 627MB | 360 | モノラルマイク録音 |
| Lakh MIDI Full | 1.65GB | 178,561 | 176K曲MIDI（ギタートラック抽出→合成音声生成用） |
| gp-classical-guitar | ~50MB | 169 | クラシックギターGuitarProファイル |

## 今日の進捗 (2026-03-02)

### SynthTab ファインチューニング完了

- SynthTab-Pretrained.pt (TabCNN 13M params, 6700時間事前学習) を GuitarSet (1440トラック) でファインチューニング
- **結果**: TDR=0.900, Accuracy=0.887, Tablature F1=0.743
- 10 epochs, batch_size=8, NUM_FRAMES=200, RTX 4060 Ti で約5時間
- Fine-tunedモデル: `generated/synthtab_finetune/models_20260301_2346/model-11300.pt`
- `synthtab_transcriber.py` がfine-tunedモデルを自動検出・優先使用するよう修正

### FretNet 全6 fold 学習完了

- fold-0〜5 全て 2500 iterations 完了
- `run_overnight.py` による自動パイプライン（SynthTab→FretNet）で夜間実行
- 中間チェックポイント削除で 12.7GB 回復 → 空き 184.4GB

### 4モデルアンサンブル推論テスト成功

- FretNet (6fold) + SynthTab + CRNN + SynthTab-EGDB = 4モデル
- GuitarSetソロ曲で全モデル正常動作、4モデル一致ノートも検出
- FretNet の Windows cp932 エンコーディング問題を修正

### SynthTab Full JAMS データ収集

- `all_jams_midi_V2_60000_tracks.zip` (1.04GB) DL・解凍完了
- 453,315ファイル → `datasets/SynthTab_Full/jams_midi/`
- acoustic音声 (746GB) は外付けストレージが必要

### フレット111バグ修正

- 音域外ノートが `string_assigner.py` のフォールバックで fret=111 等になる問題を修正
- `max_fret` で制限し、音域外ノートは除外するよう変更

### 次世代モデル設計

- 3出力ヘッド（Onset/Fret/Technique）のアーキテクチャ設計書作成
- 13種テクニッククラス定義（hammer/slide/bend/vibrato/harmonic/tapping等）
- 無料データセット調査: IDMT-SMT-Guitar, AG-PT-set(15h/32K notes), GProTab(70K曲)

### 17ラウンドバグハント（修正6件）

1. 🔴 **pipeline.py L139-237** — Basic Pitch→アンサンブル優先順位を逆転（最重大: fine-tunedモデルが使われていなかった）
   - 変更前: Basic Pitchがメイン、アンサンブルがフォールバック
   - 変更後: アンサンブル(FretNet/SynthTab/CRNN/EGDB)がメイン、Basic Pitchがフォールバック
   - `min_models_for_accept=1` に変更（1モデルでも結果を返す）
2. 🟠 **note_filter.py L170** — `filter_position_window`のフレット上限 `24→19` に修正
   - pipeline.pyのフレット19制限をバイパスしてフレット20-24がTABに混入するのを防止
3. 🟡 **ensemble_transcriber.py L117** — `confidence = len(notes) / 3.0` → `/ 4.0`
   - 4モデル体制（FretNet/SynthTab/CRNN/EGDB）に合わせて修正
4. 🟡 **string_assigner.py L438-442, L533-534** — フレット111バグ
   - L440: 音域外ノート（`fallback_fret > max_fret`）をスキップするよう変更
   - L534: フォールバックフレットを `min(max(0, pitch - tuning[-1]), max_fret)` でクランプ
5. 🟡 **pipeline.py L45** — `open(beats.json, "w")` → `open(..., encoding="utf-8")`
   - Windowsでcp932エンコーディングになりクラッシュする可能性を防止
6. 🔵 **pipeline.py L6** — コメント `Basic Pitch フォールバック` → `アンサンブル優先`

---

## 過去の進捗 (2026-03-01)

### タブ譜タイミング精度の改善 (nextchord-solotab)

アルペジオで順次演奏されるノートが和音として不正にグループ化される問題に取り組んだ。

#### 1. Basic Pitch直接利用に切替

- FretNetアンサンブル(173ノート)からBasic Pitch直接(152ノート)に変更
- MIDI聴き比べによる最適閾値選定: `onset=0.65`, `frame=0.45`
- 10種類のパラメータでMIDIを生成し、耳で最も自然な設定を選定

#### 2. 開放弦ピッチ強制割り当て

- E2/A2/D3/G3/B3/E4に一致するノートは、スコアリング無関係に常にfret=0に上書き
- `string_assigner.py`に実装

#### 3. ポジション一貫性強化

- 押弦同士で4フレット超のジャンプにペナルティを追加
- Viterbiアルゴリズムのコスト関数を改善
- `string_assigner.py`に実装

#### 検証結果

- テスト曲: **禁じられた遊び** (Romance de Amor)
- 冒頭のアルペジオパターン（1弦7/2弦0/3弦0/6弦0）が正しく表示
- ユーザー評価:「近い」

### TAB品質の深層分析レポート作成

業界リーダー（Ultimate Guitar、Songsterr、Guitar Pro）との比較分析を実施:

- **現状の課題を4段階で整理**: ノート検出精度、ノート密度、リズム精度、フィンガリング
- **品質改善ロードマップ策定**: Phase A（ノート密度削減）→ Phase D（構造認識）
- **核心的発見**: Songsterrですら「AI転写=出発点」であり、TABエディター機能が最も実用的な改善策

---

## SoloTab CRNN学習完了

- `resume_training.py` で学習を再開し、Epoch 120でEarly Stopping (ベスト TDR F1=0.8179, Epoch 95)
- CRNNモデル (`best_model.pth`) は推論テスト済み — 2306ノート検出, フレット0-8
- `pipeline.py` がCRNNモデルを自動検出し、Basic Pitchからの切替を行う
- SoloTabプロジェクト: バックエンド port 8001, フロントエンド port 5174

## 現在の状態

アプリケーションは正常に動作中。以下の修正を完了：

### 過去のセッションで完了した修正

1. **休符記号の除去** — `tab_generator.py`
   - `<forward>`要素と`_insert_invisible_rest`（`print-object="no"`）はAlphaTabで休符記号として表示されてしまう問題
   - **解決策**: ノートの長さを次のノートの位置まで伸ばして**ギャップをゼロ**にする方式に変更
   - Melody/TABパート両方で適用済み
   - `_insert_invisible_rest`ヘルパー関数は空小節用に残存（N.C.区間など）

2. **歌詞ビートマッピングの修正** — `pipeline.py`
   - `np.searchsorted(v_time, t) - 1` → 最も近いビートにスナップ
   - 歌詞が1拍前にずれる問題を修正

3. **1ノート1歌詞の強制** — `tab_generator.py`
   - 歌詞の重複を防止、最も近いノートに1つだけ割り当て

4. **CORSにPATCHメソッド追加** — `main.py` L176
   - 歌詞編集API (`PATCH /result/{id}/lyrics`) がCORSエラーになっていた

5. **`logger`参照エラーの修正** — `main.py`
   - 4箇所で未定義の`logger.info()`を`print()`に置換
   - L922, L972, L1088, L1104

6. **`structured_data.json`読み込みフォールバック** — `main.py` L979-994
   - 単体ファイルが存在しない場合、`session.json`の`result.structured_data`から読み込むよう修正

### 未テスト・要確認

- [ ] 歌詞編集 → 「譜面に反映」ボタンの動作 (500エラー修正後、ブラウザからのテスト未完了)
- [ ] 歌詞PATCH APIの動作確認

## 次にやるべきこと

### 短期（即効性あり）

- [ ] ノート密度の大幅削減（velocity閾値で弱い音を除去）
- [ ] 倍音フィルタ（基音のみ残す）
- [ ] ノイズゲート強化（Demucs分離後の残留ノイズ除去）

### 中期

- [ ] SynthTab大規模学習（Phase 1: dadaGPフィンガースタイル曲抽出→FretNet再学習）
- [ ] リズムの高度化（3連符対応、音価推定）
- [ ] TABエディター機能の追加

## 起動方法

```bash
/start
```

> ⚠️ サーバーは `--reload` 付きで起動するため、コード変更は自動反映されます。手動再起動は通常不要。

## アーキテクチャ概要

```text
nextchord/
├── fastapi-backend/
│   ├── main.py            # FastAPI エンドポイント
│   ├── pipeline.py        # 解析パイプライン（ビート、コード、歌詞）
│   ├── tab_generator.py   # MusicXML生成（五線譜+TAB）
│   ├── chord_processing.py # コード解析
│   └── phrase_processor.py # 歌詞フレーズ分割
├── nextchord-ui/
│   └── src/
│       ├── App.jsx        # メインアプリ
│       └── components/
│           ├── TabView.jsx        # AlphaTab楽譜表示
│           └── ChordLyricsView.jsx # コード・歌詞テキスト表示
└── uploads/               # セッションデータ
```

## 既知の制限

- AlphaTabは`print-object="no"`を無視するため、休符表示の制御にはギャップをゼロにする方式を使用
- 高速パッセージ（ラップ等）では歌詞がノートより多い場合に一部欠落する可能性
- コードストラム方式では意図的な休符（ブレイク等）の検出は未実装
