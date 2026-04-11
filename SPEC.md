# Tekken Bot 機能拡張仕様書

> **[2026-04-11 以降]** このファイルは歴史的記録として保持する。
> 今後の仕様管理・機能追加は **[aidlc-docs/](aidlc-docs/)** を正とする。
> - 原則: [aidlc-docs/constitution.md](aidlc-docs/constitution.md)
> - 要件: [aidlc-docs/requirements/core_features.md](aidlc-docs/requirements/core_features.md)
> - 設計: [aidlc-docs/design-artifacts/architecture.md](aidlc-docs/design-artifacts/architecture.md)
> - 実装計画: [aidlc-docs/plans/](aidlc-docs/plans/)

---

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

### F-9. Discord スラッシュコマンド
**What**: `/tekken today/weekly/status/vs/chara/top/rival/trend` コマンドを Discord サーバーに追加
**Why**: スケジューラを待たずに任意のタイミングで戦績を投稿・確認できるようにする
**Who**: 格ゲー部メンバー
- `bot/slash_commands.py` 新規作成
- `DISCORD_BOT_TOKEN` を設定することで有効化
- `scheduler.py` で Bot スレッドとスケジューラスレッドを並行起動

| コマンド | 説明 |
|---------|-----|
| `/tekken today [date]` | 今日（または指定日）の戦績を取得・投稿 |
| `/tekken weekly` | 週次サマリーを投稿 |
| `/tekken status` | Bot 稼働状況を確認 |
| `/tekken vs <name>` | 特定の対戦相手との通算成績（名前部分一致） |
| `/tekken chara <name>` | 特定キャラクターとの対戦成績 |
| `/tekken top` | キャラ別対戦成績ランキング（2戦以上） |
| `/tekken rival <name>` | ライバル詳細分析（使用キャラ・レーティング変動・流れ） |
| `/tekken trend [days]` | レーティング推移グラフを表示（デフォルト30日） |

### B. 対戦相手スカウティング
**What**: リピート対戦相手（当日2戦以上）の wank プロフィールを自動取得し投稿に追記
**Why**: 同じ相手に負け続けているとき、相手が直近好調かどうかを把握したい
**Who**: プレイヤー
- `fetch_opponent_summary()` (fetcher.py): wank HTML から直近最大20戦を取得し集計
- `_scout_section()` (discord_post.py): メインキャラ・通算勝率・直近10戦トレンド（↑↓→）を表示
- 上位3人のみ取得（API負荷最小化）

### C. レーティングトレンド予測・停滞検知
**What**: 週次サマリーにレーティング推移の傾きと停滞日数を表示
**Why**: 「なんとなく伸び悩んでいる」を数値で可視化したい
**Who**: プレイヤー
- `predict_rating_trend()` (stats.py): numpy 線形回帰で slope/日を算出
- `_count_stagnation_days()` (stats.py): 末尾から連続して±100以内の日数をカウント
- 週次メッセージに `📈 レーティングトレンド: +42/日` と `⚠️ 停滞気味: 4日間` を表示
- numpy 未インストール時は空 dict を返して続行（依存を強要しない）

### D. LLM コーチングモード強化
**What**: Python 側でパターン分析した洞察を LLM プロンプトに渡す
**Why**: LLM が実在しないキャラ名・データにない数値を捏造する（ハルシネーション）問題を抑制する
**Who**: プレイヤー（LLM コメントの質向上）
- `_compute_coaching_insights()` (analyzer.py): 苦手キャラ・得意キャラ・時間帯・前日比トレンドを Python 側で算出
- プロンプトに事前算出済みの事実のみを渡す
- `【厳守】対戦キャラ別成績に記載されていないキャラ名は絶対に出さない` の制約を追加

### E. 部内コミュニティランキング
**What**: 週次サマリー後に複数プレイヤーの net_rating ランキングを投稿
**Why**: 格ゲー部メンバー間で競える雰囲気を作りたい
**Who**: 格ゲー部メンバー全員
- `build_community_weekly()` (discord_post.py): net_rating 降順・🥇🥈🥉メダル表示
- `post_community_weekly()` (discord_post.py): プレイヤーが2人以上の場合のみ投稿
- `weekly()` (main.py) の末尾で全プレイヤー分を集計してから呼び出す

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
| `bot/db.py` | player_name カラム・マイグレーション・フィルタ・chara_names テーブル |
| `bot/fetcher.py` | polaris_id 引数化・wank 優先順位・Session+Retry・動的キャラ名学習・スカウト取得 |
| `bot/discord_post.py` | マトリクス・weekly message・graph 添付・スカウトセクション・コミュニティランキング |
| `bot/analyzer.py` | player_name in prompt・coaching insights 事前算出・プロンプト再設計 |
| `bot/stats.py` | `predict_rating_trend`・`_count_stagnation_days`・`detect_momentum` 追加 |
| `bot/graph.py` | **新規**: matplotlib レーティンググラフ |
| `main.py` | logging・async化・threading.Lock・複数プレイヤー並列処理・スカウト取得 |
| `scheduler.py` | logging・週次ジョブ・sync エントリポイント呼び出し |
| `exporter.py` | logging |
| `Dockerfile` | healthcheck・非rootユーザー tekken:1000 |
| `docker-compose.yml` | healthcheck・TZ=Asia/Tokyo |
| `requirements.txt` | バージョンピン留め・matplotlib 追加 |
| `requirements-dev.txt` | **新規**: pytest 分離 |
| `.env.example` | PLAYERS 追加 |
| `tests/` | **新規**: pytest テストスイート（315テスト、カバレッジ76%）|
| `bot/slash_commands.py` | `/tekken trend` コマンド追加 |

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
- [x] F-9: スラッシュコマンド（bot/slash_commands.py）
  - [x] `/tekken trend` — レーティング推移グラフ（直近N日、デフォルト30日）
- [x] 段位アップ通知: 前日比でランク増加時に Discord 通知（main.py `_fire_alerts`）
- [x] B: 対戦相手スカウティング（bot/fetcher.py, bot/discord_post.py, main.py）
- [x] C: レーティングトレンド予測・停滞検知（bot/stats.py, bot/discord_post.py）
- [x] D: LLM コーチングモード強化（bot/analyzer.py）
- [x] E: 部内コミュニティランキング（bot/discord_post.py, main.py）

---

## 5. 検証方法（Checklist）

- [x] `pytest tests/` が全通過（315テスト、カバレッジ76%、mypy 0エラー）
- [x] `python main.py` が成功し `data/tekken_bot.log` に出力される
- [x] `docker compose up --build` でコンテナが HEALTHY になる
- [x] Discord Webhook に当日バトルが投稿される（マトリクス・スカウト付き）
- [x] グラフ画像が添付されている
- [x] 日曜日に週次サマリーが投稿される（スケジューラログで確認）
- [x] 週次サマリーにレーティングトレンド・コミュニティランキングが含まれる
- [x] LLM コメントが苦手キャラ・時間帯などデータに基づいた内容になっている
