# Tekken Bot 機能拡張仕様書

## 1. プロジェクト概要（Constitution）

会社の格ゲー部向け Tekken 8 Discord Bot。
wank.wavu.wiki からバトルデータをリアルタイムで取得し、日次・週次で Discord に戦績を投稿する。
Prometheus Exporter で監視基盤（Grafana）にメトリクスを公開する。

### 設計原則
- **Real-time First**: wank を優先、ewgf.gg はフォールバック
- **Fail Gracefully**: 各取得ステップが失敗しても Bot は動き続ける
- **Multi-player Ready**: 単一プレイヤー設定との後方互換を保ちながら複数名対応

---

## 2. 機能要件（Specify）

### F-1. ログローテーション
**What**: `print()` を `logging.RotatingFileHandler` に置換
**Why**: Dockerコンテナ長期稼働時にディスクを埋めないため
**Who**: 運用担当（ログ確認・監視）
- ファイル: `/app/data/tekken_bot.log`（環境変数 `LOG_PATH` で変更可）
- 10MB × 3世代ローテーション
- `setup_logging()` を `main.py` に定義し `scheduler.py`・`exporter.py` で import

### F-2. Docker healthcheck
**What**: コンテナの生存確認
**Why**: `restart: unless-stopped` と組み合わせて異常時に自動復旧するため
**Who**: 運用担当（Docker監視）
- `tekken-bot`: SQLite に接続できるか確認（1時間毎）
- `tekken-exporter`: `/metrics` エンドポイントに HTTP GET（1時間毎）

### F-3. ewgf.gg 優先順位見直し
**What**: データソース優先順位を wank → ewgf に変更
**Why**: ewgf.gg は24時間以上のインデックス遅延がある。wank はリアルタイム
**Who**: プレイヤー（当日中に戦績を確認したい）
- 優先順位: wank HTML + bulk enrichment → ewgf.gg（wank 失敗時のみ）→ wank HTML単体

### F-4. 対戦マトリクス表示
**What**: 日次投稿に対面キャラ別勝率を追加
**Why**: どのキャラが苦手か一目で分かるようにする
**Who**: プレイヤー（対策キャラ選定）
- 2戦以上のキャラのみ表示、勝率降順
- 勝率 > 50% → ✅、= 50% → ➖、< 50% → ❌

### F-5. 複数プレイヤー対応
**What**: 複数の Polaris ID を設定して全員の戦績を投稿
**Why**: 格ゲー部のメンバー全員の戦績を1つの Bot で管理したい
**Who**: 格ゲー部メンバー全員
- `.env`: `PLAYERS=Name1:id1,Name2:id2`
- `POLARIS_ID` 単体設定との後方互換あり
- DB に `player_name` カラム追加（マイグレーション対応）

### F-6. 週次サマリー投稿
**What**: 毎週日曜 JST 21:00 に週間成績を投稿
**Why**: 週の振り返りに使いたい
**Who**: 格ゲー部メンバー
- 内容: 勝率・レーティング変動・最多使用キャラ・対戦マトリクス・LLMコメント

### F-7. レーティンググラフ画像
**What**: 日次投稿にレーティング推移グラフ（PNG）を添付
**Why**: 数字だけより視覚的にレーティングの推移が分かりやすい
**Who**: プレイヤー
- matplotlib で折れ線グラフ生成（メモリ上 BytesIO）
- matplotlib 未インストール時はグラフなしで続行

### F-8. pytest ユニットテスト
**What**: 純粋関数中心のテストスイートを追加
**Why**: リグレッション防止と仕様の文書化
**Who**: 開発者
- `tests/test_discord_post.py`, `tests/test_db.py`, `tests/test_analyzer.py`

---

## 3. 技術アーキテクチャ（Plan）

### 依存関係
```
scheduler.py
  └── main.py (setup_logging, get_players, main, weekly)
        ├── bot/db.py     (init_db, insert_battles, get_battles_*)
        ├── bot/fetcher.py (fetch_battles_since)
        ├── bot/discord_post.py (post, build_weekly_message)
        └── bot/analyzer.py (analyze)

exporter.py
  └── bot/db.py

bot/discord_post.py
  └── bot/graph.py (generate_rating_chart)
```

### 変更ファイル一覧

| ファイル | 変更種別 |
|---------|---------|
| `bot/db.py` | player_name カラム・マイグレーション・フィルタ |
| `bot/fetcher.py` | polaris_id 引数化・wank 優先順位 |
| `bot/discord_post.py` | マトリクス・weekly message・graph 添付・player name |
| `bot/analyzer.py` | player_name in prompt |
| `bot/graph.py` | **新規**: matplotlib レーティンググラフ |
| `main.py` | logging・複数プレイヤーループ・weekly 関数 |
| `scheduler.py` | logging・週次ジョブ |
| `exporter.py` | logging |
| `Dockerfile` | healthcheck |
| `docker-compose.yml` | healthcheck |
| `requirements.txt` | matplotlib, pytest 追加 |
| `.env.example` | PLAYERS 追加 |
| `tests/` | **新規**: pytest テストスイート |

---

## 4. 実装タスク（Tasks）

- [x] F-1: ログローテーション（main.py, scheduler.py, exporter.py）
- [x] F-2: Docker healthcheck（Dockerfile, docker-compose.yml）
- [x] F-3: wank 優先順位（bot/fetcher.py）
- [x] F-4: 対戦マトリクス（bot/discord_post.py）
- [x] F-5: 複数プレイヤー（bot/db.py, bot/fetcher.py, bot/discord_post.py, bot/analyzer.py, main.py）
- [x] F-6: 週次サマリー（scheduler.py, bot/discord_post.py）
- [x] F-7: レーティンググラフ（bot/graph.py, bot/discord_post.py, requirements.txt）
- [x] F-8: pytest テスト（tests/）

---

## 5. 検証方法（Checklist）

- [ ] `pytest tests/` が全通過
- [ ] `python main.py` が成功し `data/tekken_bot.log` に出力される
- [ ] `docker compose up --build` でコンテナが HEALTHY になる
- [ ] Discord Webhook に当日バトルが投稿される（マトリクス付き）
- [ ] グラフ画像が添付されている
- [ ] 日曜日に週次サマリーが投稿される（スケジューラログで確認）
