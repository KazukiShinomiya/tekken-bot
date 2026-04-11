# Tekken Bot — Constitution

> このドキュメントはプロジェクトの根本原則を定める。すべての設計・実装・レビューはここに立ち返る。

---

## 1. プロジェクト目的

会社の格ゲー部 Discord に、鉄拳8の戦歴・スタッツを自動投稿する Bot を提供する。

- プレイヤーが当日の戦績をリアルタイムで把握できる
- 週単位のトレンドを可視化して上達の指針にできる
- 格ゲー部メンバー間の競争・交流を促進する

---

## 2. 設計原則

### 2-1. Real-time First
wank.wavu.wiki を優先データソースとする（リアルタイム）。ewgf.gg は wank 完全失敗時のフォールバックに限定する（24時間遅延があるため）。

### 2-2. Fail Gracefully
各取得ステップが失敗しても Bot は止まらない。LLM タイムアウト・API 障害・DB エラーはすべてログに記録し、次フェーズへ継続する。

### 2-3. Multi-player Ready
単一プレイヤー設定（`POLARIS_ID`）との後方互換を保ちながら、`PLAYERS=Name:id,...` 形式で複数名対応する。

### 2-4. Test Before Deploy
デプロイ前に `python -m pytest tests/` が全通過することを必須とする。カバレッジ目標: 76% 以上（現行値）。

### 2-5. No Silent Failures
例外はすべてログに残す。想定外のエラーは Discord の `#errors` チャンネルへの通知も検討する。

### 2-6. Data Integrity Over Speed
バトル ID の重複挿入は `INSERT OR IGNORE` で無視し、既存データを破壊しない。DB マイグレーションは `ALTER TABLE` を使い、テーブル再作成は行わない。

---

## 3. 技術スタック

| 層 | 技術 |
|---|---|
| 言語 | Python 3.11 |
| DB | SQLite（`data/battles.db`） |
| Discord | discord.py（スラッシュコマンド）+ Webhook（投稿） |
| LLM | Ollama（gemma3:4b / qwen2.5:7b フォールバック） |
| 監視 | Prometheus Exporter（port 9877）+ Grafana |
| コンテナ | Docker Compose（tekken-bot / tekken-exporter / prometheus / grafana） |
| CI | pytest + mypy（ローカル実行） |

---

## 4. 開発ルール

### 4-1. 新機能の追加フロー（AI-DLC）
1. `aidlc-docs/plans/<feature>.md` に計画を作成（チェックボックス付き）
2. 人間（ジント）が計画を承認
3. 1ステップずつ実装し、完了したらチェックボックスを更新
4. `python -m pytest tests/` で全通過を確認
5. `/deploy` でコミット → プッシュ → NAS デプロイ

### 4-2. コーディング規約
- 型注釈: `list[Battle]` 等の TypedDict を使用（mypy 0エラーを維持）
- タイムアウト: ハードコード禁止。`config.py` の定数を参照
- ログ: `[module_name]` プレフィックスを付ける
- コメント: ロジックが自明でない箇所のみ

### 4-3. テスト方針
- 純粋関数は必ずテスト対象とする
- 外部 API・Discord Webhook は `unittest.mock.patch` でモック
- DB テストは `tempfile` でインメモリ or 一時ファイル DB を使用
- カバレッジが下がる変更は原則として追加テストとセットで出す

### 4-4. デプロイ方針
- `git push` 後は必ず NAS デプロイ（`git pull + docker compose up -d --build`）まで完結させる
- NAS 上に未コミット変更がある場合は `git stash` してから `git pull`
- ログは `docker logs -f tekken_bot-tekken-bot-1 --tail=50` で確認

---

## 5. 非機能要件

| 項目 | 目標値 |
|---|---|
| LLM 応答時間 | 200秒以内（タイムアウト設定値） |
| API タイムアウト | 30秒 |
| DB バックアップ | 日次・7世代保持 |
| コンテナ再起動 | `restart: unless-stopped` |
| ログローテーション | 10MB × 3世代 |

---

## 6. 用語定義

| 用語 | 定義 |
|---|---|
| Polaris ID | wank / ewgf.gg でプレイヤーを識別するID（例: `66aidNN9JQ2T`） |
| Battle | 1回の対戦を表す dict（`Battle` TypedDict） |
| Daily job | 毎日 08:00 JST に実行される戦績取得・投稿処理 |
| Weekly job | 毎週月曜 00:00 JST 起算・日曜 21:00 JST に実行される週次サマリー |
| Scout | リピート相手の wank プロフィール取得（6時間キャッシュ） |
| Bolt | AI-DLC における最小イテレーション単位（1機能 = 1 Bolt） |
