# Architecture — Design Artifacts

> 現行システムの設計ドキュメント（2026-04-11 時点）。
> Brown-field 開発の文脈付与（AI-DLC Construction Phase 用）。

---

## 1. 静的モデル（Static Model）

コンポーネント・責務・依存関係を示す。

### 1-1. コンポーネント一覧

| コンポーネント | ファイル | 責務 |
|---|---|---|
| **Config** | `bot/config.py` | 環境変数の一元管理。タイムアウト・プレイヤー情報・RANK_NAMES 等 |
| **Fetcher** | `bot/fetcher.py` | wank HTML / バルク API / ewgf.gg からバトルデータを取得。キャラ名動的学習。スカウト取得 |
| **DB** | `bot/db.py` | SQLite への永続化。バトル挿入・取得・集計クエリ。スカウトキャッシュ。バックアップ |
| **Analyzer** | `bot/analyzer.py` | Ollama LLM への問い合わせ。コーチングインサイト算出。プロンプト構築 |
| **Stats** | `bot/stats.py` | 集計ロジック（勝率・連勝連敗・モメンタム・トレンド予測） |
| **Graph** | `bot/graph.py` | matplotlib によるグラフ生成（レーティング折れ線・キャラ使用率積み上げ棒） |
| **DiscordPost** | `bot/discord_post.py` | Discord Webhook への投稿。メッセージ・Embed 構築。グラフ添付 |
| **SlashCommands** | `bot/slash_commands.py` | discord.py スラッシュコマンド定義（/tekken today/weekly/status/vs/chara/top/rival/trend） |
| **Exporter** | `exporter.py` | Prometheus メトリクス公開（port 9877） |
| **Main** | `main.py` | 日次・週次処理のオーケストレーション。async/await。threading.Lock |
| **Scheduler** | `scheduler.py` | cron 代替スケジューラ。Bot スレッド + スケジューラスレッドを並行起動 |
| **Models** | `bot/models.py` | `Battle` TypedDict 定義 |
| **Exceptions** | `bot/exceptions.py` | カスタム例外クラス |

### 1-2. 依存関係グラフ

```
scheduler.py
  ├── main.py
  │     ├── bot/config.py
  │     ├── bot/db.py ──────────── bot/models.py
  │     ├── bot/fetcher.py ──────── bot/config.py, bot/db.py, bot/models.py
  │     ├── bot/analyzer.py ─────── bot/config.py, bot/models.py
  │     ├── bot/discord_post.py ─── bot/config.py, bot/db.py, bot/stats.py, bot/graph.py
  │     └── bot/stats.py
  └── bot/slash_commands.py
        └── main.py（daily/weekly を呼び出し）

exporter.py
  └── bot/db.py
      bot/config.py
```

### 1-3. データストア

```
data/
  battles.db          ← メイン DB（Docker volume）
    battles           - バトル履歴（player_name, battle_id, chara_id, ...）
    chara_names       - キャラ名動的学習テーブル
    scout_cache       - 対戦相手スカウトキャッシュ（TTL 6時間）
    daily_posts       - 重複投稿防止テーブル
  backups/            ← 日次バックアップ（7世代）
```

---

## 2. 動的モデル（Dynamic Model）

主要ユースケースのシーケンスを示す。

### 2-1. 日次処理フロー（`main()` 毎朝 08:00 JST）

```
scheduler.py
  │
  ├─► main(player) × 全プレイヤー（asyncio.gather で並列）
  │     │
  │     ├─[1] fetcher.fetch_battles_since(polaris_id, since)
  │     │       ├─ wank HTML 取得（直近50件）
  │     │       ├─ wank バルク API で enrich（rank/power/battle_type）
  │     │       └─ 失敗時: ewgf.gg → wank HTML のみ
  │     │
  │     ├─[2] db.insert_battles(battles)   ← INSERT OR IGNORE
  │     │
  │     ├─[3] db.get_battles_since(since)  ← 当日分を取得
  │     │
  │     ├─[4] _compute_opponent_data()     ← リピート相手スカウト（並列取得）
  │     │       └─ fetcher.fetch_opponent_summary() × 上位3人
  │     │
  │     ├─[5] analyzer.analyze(battles)    ← LLM コーチングコメント（200秒 TO）
  │     │       └─ _compute_coaching_insights() → Ollama API
  │     │
  │     ├─[6] _fire_alerts()               ← 連勝・段位アップ通知
  │     │
  │     └─[7] discord_post.post()          ← Webhook 投稿（グラフ添付）
  │             ├─ build_message() / build_embed()
  │             └─ graph.generate_rating_chart()
  │
  └─► （全プレイヤー完了後）db.backup_db()
```

### 2-2. 週次処理フロー（`weekly()` 毎週日曜 21:00 JST）

```
scheduler.py
  │
  ├─► weekly(player) × 全プレイヤー（asyncio.gather で並列）
  │     ├─[1] db.get_battles_since(week_start)
  │     ├─[2] analyzer.analyze(battles)
  │     ├─[3] stats.predict_rating_trend()
  │     └─[4] discord_post.post_weekly()
  │             ├─ build_weekly_message() / build_weekly_embed()
  │             ├─ graph.generate_rating_chart()
  │             └─ graph.generate_chara_usage_chart()
  │
  └─► post_community_weekly()  ← プレイヤー2人以上の場合のみ
```

### 2-3. スラッシュコマンドフロー（`/tekken today` 等）

```
Discord サーバー
  │
  └─► bot/slash_commands.py（discord.py Bot スレッド）
        ├─ threading.Lock 取得（スケジューラと排他）
        ├─ main() / weekly() を asyncio.run() で実行
        └─ 完了後 Lock 解放
```

### 2-4. Prometheus メトリクス取得フロー

```
Prometheus（10秒ごと scrape）
  │
  └─► exporter.py:9877/metrics
        └─ db.get_battles_since() 等で集計 → Gauge 更新
```

---

## 3. 外部依存

| サービス | 用途 | 制約 |
|---|---|---|
| wank.wavu.wiki | バトルデータ取得（HTML + バルク API） | 非公式 API、変更リスクあり |
| ewgf.gg API | フォールバック取得 | 100 req/日、24時間遅延 |
| Ollama（gemma3:4b） | LLM コーチングコメント | 約95秒/req、RAM 7.6GB 制約 |
| Discord Webhook | 投稿（テキスト・Embed・画像） | Rate limit 注意 |
| discord.py Bot | スラッシュコマンド | `DISCORD_BOT_TOKEN` 必要 |

---

## 4. ADR（Architecture Decision Records）

### ADR-001: wank 優先・ewgf.gg フォールバック
- **決定**: wank HTML + バルク API を優先、ewgf.gg は完全失敗時のみ
- **理由**: ewgf.gg は 24 時間以上のインデックス遅延があり、当日戦績に使えない
- **結果**: wank の非公式 API 仕様変更リスクを受け入れる

### ADR-002: SQLite 採用
- **決定**: PostgreSQL でなく SQLite を採用
- **理由**: Raspberry Pi 上の単一コンテナ構成でオーバースペック。Docker volume でデータ永続化
- **結果**: 並行書き込みは発生しないため問題なし

### ADR-003: Ollama をホストで動作させ `network_mode: host` で接続
- **決定**: Ollama は systemd 管理、Bot コンテナは host ネットワークで localhost 接続
- **理由**: Raspberry Pi の RAM 制約上、Ollama をコンテナ化するとメモリ競合が起きる
- **結果**: コンテナ分離は犠牲になるが安定稼働を優先

### ADR-004: gemma3:4b を主モデルに採用
- **決定**: qwen2.5:7b から gemma3:4b に変更（フォールバック: qwen2.5:3b）
- **理由**: gemma3:4b は約 95秒/req で qwen2.5:7b（約 103秒）より高速
- **結果**: Gemma 4 は NAS の RAM 不足（7.3GB 必要）で不可。RPi 5 16GB 導入後に再検討
