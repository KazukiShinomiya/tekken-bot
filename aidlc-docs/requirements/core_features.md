# Core Features — Requirements

> 実装済み機能の要件スナップショット（2026-04-11 時点）。
> User Story 形式: `As a <who>, I want <what>, so that <why>`

---

## Unit 1: データ取得（Fetching）

### US-101: リアルタイム戦績取得
**As a** プレイヤー,  
**I want** 当日の対戦結果を数分以内に Bot が把握できること,  
**So that** 当日中に戦績投稿が届く。

**Acceptance Criteria:**
- wank.wavu.wiki HTML から直近50件を取得できる
- wank バルク API で `my_rank / opp_rank / battle_type` を補完できる
- wank が完全失敗した場合のみ ewgf.gg にフォールバックする

**Status:** ✅ Implemented (`bot/fetcher.py`)

---

### US-102: データ永続化
**As a** Bot,  
**I want** 取得したバトルデータを SQLite に保存すること,  
**So that** 重複投稿を防ぎ、週次集計に使える。

**Acceptance Criteria:**
- `battle_id` で重複を検知し `INSERT OR IGNORE` で無視する
- `player_name` カラムで複数プレイヤーを識別できる
- `data/backups/` に日次バックアップ（7世代）が保存される

**Status:** ✅ Implemented (`bot/db.py`)

---

### US-103: キャラ名動的学習
**As a** Bot,  
**I want** wank API から新キャラの名前を自動学習すること,  
**So that** Season アップデートで `Chara#N` 表示が残らない。

**Acceptance Criteria:**
- `chara_names` テーブルに未知キャラを保存する
- 起動時に `Chara#N` が残っている場合はログ警告を出す

**Status:** ✅ Implemented (`bot/db.py`, `bot/fetcher.py`)

---

### US-104: 対戦相手スカウティング
**As a** プレイヤー,  
**I want** リピート相手（当日2戦以上）の使用キャラと勝率を自動取得すること,  
**So that** 同じ相手に当たり続けるときに相手の傾向を把握できる。

**Acceptance Criteria:**
- 当日2戦以上の相手のみ対象（API 負荷最小化）
- 結果は6時間 TTL でキャッシュする（`scout_cache` テーブル）
- 直近10戦のトレンド（↑↓→）を表示する

**Status:** ✅ Implemented (`bot/fetcher.py`, `bot/db.py`)

---

## Unit 2: Discord 投稿（Posting）

### US-201: 日次戦績投稿
**As a** 格ゲー部メンバー,  
**I want** 毎朝 Discord に昨日の戦績サマリーが届くこと,  
**So that** 部員全員の活動状況を把握できる。

**Acceptance Criteria:**
- 勝率・対戦数・レーティング変動を含む
- 対戦相手キャラ別マトリクス（1戦以上）を含む
- 新規バトルなし & 当日投稿済みの場合はスキップする

**Status:** ✅ Implemented (`bot/discord_post.py`, `main.py`)

---

### US-202: 週次サマリー投稿
**As a** 格ゲー部メンバー,  
**I want** 毎週日曜 21:00 に週間成績サマリーが届くこと,  
**So that** 週の振り返りができる。

**Acceptance Criteria:**
- 月曜 00:00 JST 起算の週次集計
- レーティンググラフ（PNG）を添付する
- キャラ使用率グラフ（積み上げ棒）を添付する
- `predict_rating_trend()` によるトレンド予測・停滞検知を含む

**Status:** ✅ Implemented (`bot/discord_post.py`, `bot/graph.py`, `bot/stats.py`)

---

### US-203: 部内コミュニティランキング
**As a** 格ゲー部メンバー,  
**I want** 週次サマリー後に部員間のランキングが投稿されること,  
**So that** 部内で競い合う動機づけになる。

**Acceptance Criteria:**
- プレイヤーが2人以上の場合のみ投稿する
- net_rating 降順で 🥇🥈🥉 メダル表示

**Status:** ✅ Implemented (`bot/discord_post.py`)

---

### US-204: クイックマッチ相手段位表示
**As a** プレイヤー,  
**I want** クイックマッチの対戦相手の段位を試合一覧で確認できること,  
**So that** 対戦相手のレベル感を把握できる。

**Acceptance Criteria:**
- 試合一覧: `⚔️ Lee vs Bryan (Kishin) ❌ 1-2` 形式
- クイック集計欄: `相手段位: God×4 / Kishin×3` 形式

**Status:** ✅ Implemented (`bot/discord_post.py`)

---

## Unit 3: 分析・AI（Analytics）

### US-301: LLM コーチングコメント
**As a** プレイヤー,  
**I want** 戦績データに基づいた具体的なコーチングコメントを受け取ること,  
**So that** 改善すべきポイントが分かる。

**Acceptance Criteria:**
- `_compute_coaching_insights()` で苦手キャラ・時間帯を Python 側で算出してプロンプトに渡す
- LLM がデータにないキャラ名・数値を生成しないよう制約プロンプトを含む
- タイムアウト（200秒）時は LLM コメントなしで戦績のみ投稿する

**Status:** ✅ Implemented (`bot/analyzer.py`)

---

### US-302: 調子の波検知
**As a** プレイヤー,  
**I want** 連勝・連敗・モメンタムを自動検知して通知を受けること,  
**So that** 好調時・不調時を意識した立ち回りができる。

**Acceptance Criteria:**
- 連勝アラート: `WIN_ALERT_THRESHOLD` 以上で 🔥 通知
- 段位アップ検知: 前日比でランク増加時に 🏆 通知
- `detect_momentum()` でモメンタム状態を判定する

**Status:** ✅ Implemented (`bot/stats.py`, `main.py`)

---

## Unit 4: スラッシュコマンド（Commands）

### US-401: オンデマンド戦績確認
**As a** 格ゲー部メンバー,  
**I want** スケジューラを待たずに任意のタイミングで戦績を取得できること,  
**So that** 対戦後すぐに結果を確認できる。

**Acceptance Criteria:**
- `/tekken today [date]` — 当日または指定日の戦績
- `/tekken weekly` — 週次サマリー
- `/tekken status` — Bot 稼働状況
- `/tekken trend [days]` — レーティング推移グラフ（デフォルト30日）

**Status:** ✅ Implemented (`bot/slash_commands.py`)

---

### US-402: 対戦相手・キャラ分析コマンド
**As a** プレイヤー,  
**I want** 特定の対戦相手やキャラとの通算成績を即座に確認できること,  
**So that** 対策の優先度を判断できる。

**Acceptance Criteria:**
- `/tekken vs <name>` — 名前部分一致で通算成績を表示
- `/tekken chara <name>` — キャラ別対戦成績
- `/tekken top` — キャラ別対戦成績ランキング（2戦以上）
- `/tekken rival <name>` — ライバル詳細（使用キャラ・累積レーティング・流れ）

**Status:** ✅ Implemented (`bot/slash_commands.py`)

---

## Unit 5: インフラ・監視（Infrastructure）

### US-501: Prometheus メトリクス公開
**As a** 運用担当,  
**I want** Bot のメトリクスを Prometheus で収集できること,  
**So that** Grafana ダッシュボードで状態を可視化できる。

**Acceptance Criteria:**
- port 9877 で `/metrics` エンドポイントを公開する
- 勝率・レーティング・キャラ使用率・時間帯別成績を公開する

**Status:** ✅ Implemented (`exporter.py`)

---

### US-502: コンテナ化・自動復旧
**As a** 運用担当,  
**I want** Bot が Docker で稼働し、障害時に自動復旧すること,  
**So that** 手動介入なしで継続稼働できる。

**Acceptance Criteria:**
- `restart: unless-stopped` で自動再起動
- HEALTHCHECK で異常を検知する（1時間毎）
- 非 root ユーザー `tekken:1000` で動作する

**Status:** ✅ Implemented (`Dockerfile`, `docker-compose.yml`)
