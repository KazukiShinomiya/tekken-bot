# Tekken Bot — プロジェクトガイド

## 概要

格ゲー部 Discord に鉄拳8の戦歴・スタッツを自動投稿する Bot。

- **GitHub**: https://github.com/KazukiShinomiya/tekken-bot
- **デプロイ先**: `ubuntu@10.0.0.254:~/tekken_bot/`
- **稼働状況**: SESSION_STATE.md に詳細あり

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
  analyzer.py     -- Ollama LLM コメント生成（qwen2.5:7b）
  discord_post.py -- Discord Webhook 投稿・メッセージ整形
  stats.py        -- 統計集計（キャラ別・時間帯別・連勝連敗）
  graph.py        -- レーティンググラフ（PNG 生成）
  config.py       -- 環境変数一元管理
  slash_commands.py -- Discord スラッシュコマンド（/tekken today/weekly/status）
main.py           -- メイン処理（データ取得 → 分析 → Discord 投稿）
scheduler.py      -- cron 代替スケジューラ（毎日 08:00 JST / 日曜 21:00 JST）
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
- **テスト**: `python -m pytest tests/` で 120 テスト全通過を確認してからデプロイ
- **NAS ローカル変更**: `git stash` してから `git pull` する
