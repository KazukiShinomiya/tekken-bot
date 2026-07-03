# Tekken Bot — プロジェクトガイド

## 概要

格ゲー部 Discord に鉄拳8の戦歴・スタッツを自動投稿する Bot。

- **GitHub**: https://github.com/KazukiShinomiya/tekken-bot
- **デプロイ先**: `ubuntu@10.0.0.254:~/tekken_bot/`
- **稼働状況**: SESSION_STATE.md に詳細あり

## 設計原則

旧 `aidlc-docs/constitution.md` から、コードに正解が無い「設計意図」のみを集約。
版数・タイムアウト等の可変値はここに書かない（`config.py` / `pyproject.toml` が真実の源）。

1. **Real-time First** — wank を優先データソースとし、ewgf.gg は wank 完全失敗時のフォールバックに限定する（ewgf は24時間遅延）
2. **Fail Gracefully** — 各取得ステップが失敗しても Bot は止めない。LLM タイムアウト・API 障害・DB エラーはログに残し、次フェーズへ継続する
3. **Multi-player Ready** — 単一 `POLARIS_ID` との後方互換を保ちつつ、`PLAYERS=Name:id,...` で複数名に対応する
4. **Test Before Deploy** — デプロイ前に `python -m pytest tests/` の全通過を必須とする
5. **No Silent Failures** — 例外は必ずログに残す。想定外のエラーは `#errors` チャンネルへの通知も検討する
6. **Data Integrity Over Speed** — バトル ID の重複は `INSERT OR IGNORE` で無視し既存データを壊さない。DB 変更は `ALTER TABLE` を使い、テーブル再作成はしない
7. **Story Over Data** — 投稿は人の言葉（LLM コメント）を最前面に。日次投稿は description 冒頭へコメントを置き、乾燥したデータ羅列より「展開の伝わりやすさ」を優先する（US-501 で確定）

## 協働の鉄則

誠実さの原則（ユーザー承認・ツール出力を捏造しない／不可逆操作は確認する）は
グローバル `~/.claude/CLAUDE.md` と `.claude/settings.json` の PreToolUse フックが担う。
ここでは重複させない。

## プレイヤー情報

| 項目 | 値 |
|------|-----|
| TEKKEN ID | ExodusOverseer |
| Polaris ID | 66aidNN9JQ2T |
| メインキャラ | Lee / Miary Zo (chara_id: 45) |

## ディレクトリ構成

```
bot/
  fetcher.py      -- データ取得（wank HTML → バルクAPI → ewgf.gg フォールバック）
  db.py           -- SQLite 永続化（data/battles.db）
  analyzer.py     -- LLM コメント生成（Ollama、完全失敗時 Gemini フォールバック。モデルは config.py）
  evaluator.py    -- LLM コメントの品質をルールベース自動評価（ハルシネーション検出）
  embeds.py       -- Discord Embed 整形（ビュー層・純粋関数。日次/週次/月次/vs 等）
  discord_post.py -- Discord Webhook 送信（I/O 層）
  stats.py        -- 統計集計（キャラ別・時間帯別・連勝連敗）
  graph.py        -- レーティンググラフ（PNG 生成）
  models.py       -- Battle 等の TypedDict 定義
  exceptions.py   -- 例外定義
  config.py       -- 環境変数一元管理
  slash_commands.py -- Discord スラッシュコマンド（/tekken today/weekly/status/trend/vs/chara/top/rival/filter）
main.py           -- メイン処理（データ取得 → 分析 → Discord 投稿）
scheduler.py      -- cron 代替スケジューラ（毎日 08:00 / 日曜 21:00 / 毎月1日 09:00 JST）
exporter.py       -- Prometheus メトリクス（port 9877）
```

## デプロイ方法

```bash
# ローカルで修正 → テスト → コミット → プッシュ
python -m pytest tests/
git add <files> && git commit -m "説明"
git push

# NAS に反映（git pull + docker compose up --build）
wsl bash -c "ssh -i ~/.ssh/tekken_deploy ubuntu@10.0.0.254 'cd ~/tekken_bot && git pull && docker compose up -d --build'"

# ログ確認
wsl bash -c "ssh -i ~/.ssh/tekken_deploy ubuntu@10.0.0.254 'docker logs -f tekken_bot-tekken-bot-1 --tail=50'"
```

`/deploy` コマンドでこの手順を自動実行できる。

### pre-push フック（再発防止の仕組み）

赤い状態の push を git レベルで物理的に拒否する防壁。`.githooks/pre-push` が
CI（`.github/workflows/test.yml`）と同一の **mypy → pytest(`--cov-fail-under=90`)**
を push 直前に実行し、いずれか失敗すれば push を中止する。

クローンごとに一度だけ有効化が必要:

```bash
git config core.hooksPath .githooks
```

検査内容は必ず CI と一致させること（CI が真実の源）。緊急回避の
`git push --no-verify` は原則使わない。

## インフラ

- **NAS**: Raspberry Pi 系 Ubuntu 24.04 aarch64 / 10.0.0.254
- **DB**: `/app/data/battles.db`（Docker volume: `./data`）
- **LLM**: Ollama（qwen2.5:7b、systemd管理、~110秒/リクエスト）
- **Grafana**: http://10.0.0.254:3000
- **Prometheus**: http://10.0.0.254:9090

## データ取得フロー

```
wank HTML（直近50件、リアルタイム）
  ↓ enrichment
wank バルクAPI（chara_id・rank・power 等補完）
  ↓ wank 完全失敗時のみ
ewgf.gg API（フォールバック、24時間遅延）
  ↓ ewgf も失敗時
wank HTML のみ（最終フォールバック）
```

## 重要な注意点

- **CHARA_NAMES**: 1-indexed（Paul=1）。Season 2 で Zafina 以降シフト済み
- **タイムゾーン**: コンテナは `TZ=Asia/Tokyo`、スケジューラは JST 表記
- **テスト**: `python -m pytest tests/` で全テスト通過を確認してからデプロイ（件数は増えるため固定しない）
- **NAS ローカル変更**: `git stash` してから `git pull` する

## 用語定義

| 用語 | 定義 |
|------|------|
| Polaris ID | wank / ewgf.gg でプレイヤーを識別する ID（例: `66aidNN9JQ2T`） |
| Battle | 1回の対戦を表す dict（`Battle` TypedDict, `bot/models.py`） |
| Daily job | 毎日 08:00 JST に実行される戦績取得・投稿処理 |
| Weekly job | 毎週月曜起算・日曜 21:00 JST 実行の週次サマリー |
| Scout | リピート対戦相手の wank プロフィール取得（キャッシュあり） |
