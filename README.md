# Tekken Bot

鉄拳8の対戦履歴を自動収集し、毎朝8時に前日の戦績を Discord に投稿する Bot。
ローカル LLM によるコーチコメント生成・レーティンググラフ・豊富なスラッシュコマンド対応。

---

## スクリーンショット（投稿イメージ）

**日次投稿（Discord Embed）**

```
🎮 ExodusOverseer 本日の戦果 (2026/04/20)
──────────────────────────────────────────
⚔️ Lee vs Dragunov          ✅ 3-2
⚔️ Lee vs Jin               ✅ 3-0
⚔️ Lee vs Reina (破壊神壱)  ❌ 1-3
⚔️ Lee vs Reina (鉄拳王)    ❌ 0-3

💬 Reina対策が最優先課題だ。2連敗・勝率0%は苦手傾向を
   示している。相手の直近好調も踏まえ研究を重ねるべし。

[🏆 ランク]        [⚡ クイック]         [🎮 その他]
2勝2敗 (50%)      1勝0敗 (100%)        -
1720 (-28)        相手段位: 鉄拳王×1

[🎯 ラウンド勝率]  [🔥 ストリーク]      [😤 天敵]
60% | 接戦: 1試合  連勝: 2 | 連敗: 2   Reina (0勝2敗, 0%)

[💥 鉄拳王]        [📊 対戦成績]
1,720,000          Dragunov  1戦 100% ✅
                   Jin       1戦 100% ✅
                   Reina     2戦   0% ❌

[⚡ クイック 段位別対戦成績]
■ 鉄拳王 (1戦 100%)
  Dragunov      1戦 100% ✅

[🔍 スカウト]
RivalPlayer(Reina) 直近50戦 勝率58% | 直近10戦 7勝 (70%) ↑
```

---

## システム構成

```
┌─────────────────────────────────────────────────────┐
│                   Windows PC                         │
│  ┌──────────────────────────────────────────────┐   │
│  │              WSL2 / Docker                    │   │
│  │  (開発・テスト環境)                           │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                         │ デプロイ (git pull)
                         ▼
┌─────────────────────────────────────────────────────┐
│           Ubuntu NAS (Raspberry Pi / ARM64)          │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │  Docker Container (tekken-bot)              │    │
│  │                                             │    │
│  │  scheduler.py → main.py                    │    │
│  │       │                                    │    │
│  │       ├─ fetcher.py ──→ wank.wavu.wiki     │    │
│  │       │   (HTML + Bulk API enrichment)     │    │
│  │       │                                    │    │
│  │       ├─ db.py ──────→ SQLite (battles.db) │    │
│  │       │                                    │    │
│  │       ├─ analyzer.py ─→ Ollama (localhost) │    │
│  │       │                (qwen2.5:7b)        │    │
│  │       │                                    │    │
│  │       ├─ evaluator.py → LLM品質スコア自動計算 │  │
│  │       │                                    │    │
│  │       └─ discord_post.py → Discord Webhook │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │  Discord Bot (slash_commands.py)            │    │
│  │  /tekken today|weekly|monthly|trend|...     │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │  Docker Container (tekken-exporter)         │    │
│  │  exporter.py → Prometheus (port 9877)       │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  ┌──────────────┐                                   │
│  │ Ollama       │  qwen2.5:7b (CPU推論)             │
│  │ :11434       │                                   │
│  └──────────────┘                                   │
└─────────────────────────────────────────────────────┘
```

---

## 技術的な面白いポイント

### 1. ハイブリッドデータ取得戦略

wank.wavu.wiki は2つの異なる API を持つ。

| API | 特徴 |
|-----|------|
| HTMLプレイヤーページ | 自分の試合を直接リスト。取得は速いが、`battle_type` や `stage_id` 等の情報が含まれない |
| バルクAPI (`/api/replays`) | 全フィールドを持つが、全プレイヤーの試合が混在。自分の試合を見つけるには大量のページネーションが必要 |

両者の弱点を組み合わせて解決している:

```
HTML で自分の試合一覧を取得（高速）
  ↓
取得した battle_at タイムスタンプを使って
バルクAPIをピンポイント検索（数ページで済む）
  ↓
全フィールドをマージ
```

50試合分のenrichmentが **19リクエスト** で完了する。

### 2. フォールバック設計

データソースを3段階で試みる。wank をリアルタイム優先とし、ewgf.gg は完全失敗時のフォールバックとして使用する。

```
wank HTML + バルクAPI enrichment（リアルタイム・優先）
  ↓ 失敗
ewgf.gg API（24時間遅延あり・フォールバック）
  ↓ 失敗
wank HTML のみ（最低限の情報で継続）
```

外部サービスの障害でボットが止まらない。

### 3. SQLiteによる全フィールド蓄積

取得できる全データをそのままDBに保存している。

```sql
battles: battle_type, game_version, stage_id,
         my_chara_id, my_rank, my_power, my_region,
         opp_chara_id, opp_rank, opp_power, opp_region,
         rating_before, rating_change, opp_rating_before ...
```

「今は使わないが将来役に立つかもしれないデータ」を捨てない設計。ローカルLLMへの入力素材としても活用できる。

### 4. ARM64 上のローカルLLM

自宅サーバー（Raspberry Pi 系、8GB RAM）で Ollama を動かし、**外部APIに一切頼らず** 日本語コメントを生成する。

- モデル: `qwen2.5:7b`（Apache 2.0、商用利用可）
- 推論速度: 約100〜120秒（CPU のみ）
- Docker コンテナからは `network_mode: host` で localhost に直接接続

毎日1回しか動かないボットなので、CPUの遅さは問題にならない。

### 5. LLM コーチングモード（ハルシネーション抑止 + 自動評価）

LLM に丸投げするのではなく、**Python 側で事前にパターン分析**してから LLM に渡す。

```python
# Python 側で算出済みの洞察をプロンプトに含める
苦手キャラ: Reina(勝率0%,2戦) / Dragunov(勝率33%,3戦)
得意キャラ: Jin(勝率80%,5戦)
時間帯: 好調=22時(75%) 低調=0時(25%)
調子: 前日比↓15pt
```

「データにないキャラ名は絶対に出すな」という制約と組み合わせることで、存在しないキャラや数値の捏造を防ぐ。

さらに `evaluator.py` がコメントの品質を3軸（文字数・ハルシネーション・改善提案）で 0〜100点で自動採点し、スコアをDBに蓄積する。

### 6. 対戦相手スカウティング

同じ相手と2戦以上した場合、その相手の wank プロフィールも自動取得する。

```
RivalPlayer(Reina) 直近50戦 勝率58% | 直近10戦 7勝 (70%) ↑
```

「相手が直近好調かどうか」がひと目で分かる。フェッチは上位3人のみに絞り、API 負荷を最小限に抑える。スカウトデータは SQLite にキャッシュされ、6時間以内は再取得しない。

---

## セットアップ

### 必要なもの

- Python 3.13+
- Docker / Docker Compose
- Discord Webhook URL
- Discord Bot Token（スラッシュコマンドを使う場合）
- wank.wavu.wiki の Polaris ID（プロフィールURLから確認）
- （任意）ewgf.gg API Key
- （任意）Ollama + qwen2.5:7b

### .env 設定

```env
TEKKEN_ID=YourTekkenID
POLARIS_ID=YourPolarisID
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=your_guild_id_here   # 省略するとグローバル登録（反映に最大1時間）

# 複数プレイヤー設定（POLARIS_ID より優先される）
# PLAYERS=Player1:polaris_id1,Player2:polaris_id2

EWGF_API_KEY=your_key_here
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
LOG_PATH=/app/data/tekken_bot.log
RATING_GOAL=200000   # 目標レーティング（/tekken goal でも設定可）
```

### ローカルで実行

```bash
pip install -r requirements.txt
python main.py
```

### Docker で実行（推奨）

```bash
docker compose up -d --build
```

毎朝8時 JST に前日分の戦績を自動投稿する。
週次サマリーは毎週日曜 21:00 JST に投稿される。
月次サマリーは毎月1日 09:00 JST に投稿される。

---

## スラッシュコマンド

Discord Bot Token を設定することで、以下のスラッシュコマンドが使用できる。

### 📊 戦績確認

| コマンド | 動作 |
|----------|------|
| `/tekken today [date]` | 当日または指定日（YYYY-MM-DD）の戦績を取得・投稿 |
| `/tekken weekly` | 週次サマリーを即時投稿 |
| `/tekken monthly [month]` | 月次サマリーを投稿（省略すると先月） |
| `/tekken trend [days]` | レーティング推移グラフを表示（デフォルト30日） |

### 🔍 検索・分析

| コマンド | 動作 |
|----------|------|
| `/tekken vs <name>` | 対戦相手（部分一致）との通算成績を確認 |
| `/tekken rival <name>` | ライバルの詳細分析（使用キャラ・累積レーティング・連続傾向） |
| `/tekken chara <name>` | 特定キャラとの対戦成績（オートコンプリート対応） |
| `/tekken top` | キャラ別対戦成績ランキング（全期間、試合数順） |
| `/tekken stage` | ステージ別勝率一覧 |
| `/tekken filter [chara] [date] [days]` | バトルログをキャラ名・日付で絞り込んで表示 |

### 🏆 記録・目標

| コマンド | 動作 |
|----------|------|
| `/tekken records` | 全期間の個人最高記録（最高レーティング・最長連勝連敗）を表示 |
| `/tekken goal [rating] [clear]` | 目標レーティングを設定・確認・解除 |

### ⚙️ その他

| コマンド | 動作 |
|----------|------|
| `/tekken status` | Bot の稼働状況を確認 |
| `/tekken help` | コマンド一覧を表示 |

Bot をサーバーに招待する際は、Discord Developer Portal の OAuth2 URL Generator で `bot` と `applications.commands` スコープを選択すること。

---

## ファイル構成

```
tekken_bot/
├── main.py              # エントリポイント・複数プレイヤー対応
├── scheduler.py         # 定時実行スケジューラ（日次・週次・月次）+ Bot スレッド起動
├── exporter.py          # Prometheus メトリクス公開（port 9877）
├── bot/
│   ├── config.py        # 環境変数・定数の一元管理
│   ├── models.py        # Battle TypedDict 型定義
│   ├── exceptions.py    # 固有例外クラス（TekkenBotError 他）
│   ├── fetcher.py       # データ取得（wank HTML + バルクAPI / ewgf.gg フォールバック）
│   ├── db.py            # SQLite 永続化（battles・goals・月次スナップショット等）
│   ├── stats.py         # 共通統計計算（連勝・キャラ別集計・トレンド予測）
│   ├── discord_post.py  # Discord 投稿・Embed 整形（日次・週次・月次・段位変化・部内ランキング）
│   ├── graph.py         # matplotlib グラフ生成（レーティング推移・キャラ使用率）
│   ├── analyzer.py      # ローカル LLM 分析（Ollama）
│   ├── evaluator.py     # LLM コメント品質自動評価（0-100点、ハルシネーション検出）
│   └── slash_commands.py  # Discord スラッシュコマンド（14コマンド）
├── tests/               # pytest テストスイート（548テスト）
├── SPEC.md              # 仕様書
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                 # 秘匿情報（gitignore対象）
└── data/
    ├── battles.db       # SQLiteデータベース（Dockerボリューム）
    └── backups/         # 自動バックアップ（直近7件保持）
```

### DB テーブル

| テーブル | 用途 |
|---------|------|
| `battles` | 全対戦データ（全フィールド保存） |
| `daily_posts` | 投稿済み日付の重複防止 |
| `scout_cache` | 対戦相手スカウトデータ（6時間 TTL） |
| `goals` | プレイヤーごとの目標レーティング |
| `llm_eval_scores` | LLM コメントの自動評価スコア履歴 |
| `monthly_snapshots` | 月次スナップショット（前月比計算用） |
| `chara_names` | 動的学習したキャラクター名マッピング |

---

## デプロイ

```bash
# ローカルで修正 → コミット → プッシュ
git add <ファイル>
git commit -m "説明"
git push

# サーバーに反映
ssh ubuntu@<NAS_IP> 'cd ~/tekken_bot && git pull && docker compose up -d --build'
```

`/deploy` コマンドでこの手順を自動実行できる。

---

## データソース

- **[wank.wavu.wiki](https://wank.wavu.wiki)** — 鉄拳8のリプレイデータを公開しているコミュニティサイト。認証不要。
- **[ewgf.gg](https://ewgf.gg)** — 鉄拳8専門の統計サービス。Bearer token 認証。プレイヤーが手動でインデックス登録する必要あり。24時間の遅延がある。
