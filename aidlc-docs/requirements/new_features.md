# New Features — Requirements

> 2026-04-11 以降に追加予定の機能要件。
> 実装済みになったら `core_features.md` に移動する。

---

## Unit 4: スラッシュコマンド（Commands）追加

### US-403: バトルログ検索コマンド
**As a** プレイヤー,  
**I want** キャラ名・日付でバトルログを絞り込んで確認できること,  
**So that** 特定のキャラとの対戦傾向を詳しく分析できる。

**Acceptance Criteria:**
- `/tekken filter chara <名前>` — 指定キャラとの全対戦を最新20件表示
- `/tekken filter date <YYYY-MM-DD>` — 指定日の全バトル一覧を表示
- `/tekken filter chara <名前> date <YYYY-MM-DD>` — 組み合わせフィルタ
- 結果は Embed 形式（勝率・試合一覧）で返す

**Status:** ⬜ Not started

---

## Unit 6: 分析強化（Advanced Analytics）

### US-601: セッション別勝率分析
**As a** プレイヤー,  
**I want** ゲームセッション単位での勝率推移を確認できること,  
**So that** 何局目から勝率が落ちるか（疲労・集中力低下）を把握できる。

**Acceptance Criteria:**
- 30分以上の空白を「セッション区切り」と定義する
- セッション番号・試合数・勝率をまとめてテキスト表示
- 週次サマリーに「今週のベストセッション」を追加する
- `/tekken sessions [days]` コマンドでオンデマンド確認可能

**Status:** ⬜ Not started

---

### US-602: 目標到達プロセス可視化
**As a** プレイヤー,  
**I want** 段位やレーティング目標への進捗をグラフで確認できること,  
**So that** モチベーション維持と進捗確認がしやすくなる。

**Acceptance Criteria:**
- `RATING_GOAL` に対する現在の達成率をパーセントで表示する
- 現在のトレンドが継続した場合の予測到達日を計算して表示する
- `/tekken goal` コマンドで専用グラフを Discord に投稿する

**Status:** ⬜ Not started

---

## Unit 7: インフラ強化（Infrastructure）

### US-701: Prometheus アラートルール
**As a** 運用担当,  
**I want** 勝率の急落や長期停滞を Prometheus Alertmanager で検知できること,  
**So that** Bot の状態変化を Grafana 外でも把握できる。

**Acceptance Criteria:**
- 7日間勝率が 40% を下回った場合にアラートを発火する
- 5日以上新規バトルがない場合に「長期非活動」アラートを発火する
- `prometheus/alerts.yml` に定義し `docker-compose.yml` に組み込む

**Status:** ⬜ Not started
