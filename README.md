# Tekken Bot

鉄拳8の対戦履歴を自動収集し、毎朝8時に前日の戦績を Discord に投稿する Bot。
ローカル LLM によるコーチコメント生成・レーティンググラフ・スラッシュコマンド対応。

---

## スクリーンショット（投稿イメージ）

```
🎮 YourTekkenID 本日の戦果 (2026/03/14)
━━━━━━━━━━━━━━━
⚔️  Lee vs Dragunov     ✅ 3-2
⚔️  Lee vs Jin          ✅ 3-0
⚔️  Lee vs Reina        ❌ 1-3
⚔️  Lee vs Reina        ❌ 0-3
━━━━━━━━━━━━━━━
🏆 ランク  2勝2敗 (50%) | 1720 (-28)
━━━━━━━━━━━━━━━
🎯 ラウンド勝率: 60% | 接戦(3-2): 1試合
🔥 連勝: 2 | 連敗: 2
😤 天敵: Reina (0勝2敗, 0%)
📉 後半に調子が落ちた
💥 鉄拳力: 185,000
━━━━━━━━━━━━━━━
📊 対戦成績
  Dragunov     1戦  100% ✅
  Jin          1戦  100% ✅
  Reina        2戦    0% ❌
━━━━━━━━━━━━━━━
🔄 リピート対戦
  RivalPlayer(Reina) 0勝2敗 (0%)
━━━━━━━━━━━━━━━
🔍 対戦相手スカウト
  RivalPlayer(Reina) 直近50戦 勝率58% | 直近10戦 7勝 (70%) ↑

🤖 今日はReina対策が最優先課題だ。
   2連敗と通算勝率0%が示す通り、苦手キャラに
   なっている。相手の直近好調も踏まえ研究を。
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
│  │       └─ discord_post.py → Discord Webhook │    │
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

### 5. LLM コーチングモード（ハルシネーション抑止）

LLM に丸投げするのではなく、**Python 側で事前にパターン分析**してから LLM に渡す。

```python
# Python 側で算出済みの洞察をプロンプトに含める
苦手キャラ: Reina(勝率0%,2戦) / Dragunov(勝率33%,3戦)
得意キャラ: Jin(勝率80%,5戦)
時間帯: 好調=22時(75%) 低調=0時(25%)
調子: 前日比↓15pt
```

「データにないキャラ名は絶対に出すな」という制約と組み合わせることで、存在しないキャラや数値の捏造を防ぐ。

### 6. 対戦相手スカウティング

同じ相手と2戦以上した場合、その相手の wank プロフィールも自動取得する。

```
RivalPlayer(Reina) 直近50戦 勝率58% | 直近10戦 7勝 (70%) ↑
```

「相手が直近好調かどうか」がひと目で分かる。フェッチは上位3人のみに絞り、API 負荷を最小限に抑えている。

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

# 複数プレイヤー設定（POLARIS_ID より優先される）
# PLAYERS=Player1:polaris_id1,Player2:polaris_id2

EWGF_API_KEY=your_key_here
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
LOG_PATH=/app/data/tekken_bot.log
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

---

## スラッシュコマンド

Discord Bot Token を設定することで、以下のスラッシュコマンドが使用できる。

| コマンド | 動作 |
|----------|------|
| `/tekken today` | 前日の戦績を即時取得・投稿 |
| `/tekken weekly` | 週次サマリーを即時投稿 |
| `/tekken status` | Bot の稼働状況を確認 |

Bot をサーバーに招待する際は、Discord Developer Portal の OAuth2 URL Generator で `bot` と `applications.commands` スコープを選択すること。

---

## ファイル構成

```
tekken_bot/
├── main.py              # エントリポイント・複数プレイヤー対応
├── scheduler.py         # 定時実行スケジューラ（Docker用）+ Bot スレッド起動
├── exporter.py          # Prometheus メトリクス公開（port 9877）
├── bot/
│   ├── config.py        # 環境変数・タイムアウト設定の一元管理
│   ├── fetcher.py       # データ取得（wank HTML + バルクAPI / ewgf.gg フォールバック）
│   ├── db.py            # SQLite永続化（player_nameカラム対応）
│   ├── stats.py         # 共通統計計算（連勝・キャラ別集計）
│   ├── discord_post.py  # Discord投稿・メッセージ整形・グラフ添付
│   ├── graph.py         # matplotlibレーティンググラフ生成
│   ├── analyzer.py      # ローカルLLM分析（Ollama）
│   └── slash_commands.py  # Discord スラッシュコマンド定義
├── tests/               # pytest テストスイート（163テスト）
├── SPEC.md              # 仕様書
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                 # 秘匿情報（gitignore対象）
└── data/
    └── battles.db       # SQLiteデータベース（Dockerボリューム）
```

---

## デプロイ

```bash
# ローカルで修正 → コミット → プッシュ
git add <ファイル>
git commit -m "説明"
git push

# サーバーに反映
wsl -e bash -c "ssh -i ~/.ssh/tekken_deploy ubuntu@10.0.0.254 \
  'cd ~/tekken_bot && git pull && docker compose up -d --build'"
```

---

## データソース

- **[wank.wavu.wiki](https://wank.wavu.wiki)** — 鉄拳8のリプレイデータを公開しているコミュニティサイト。認証不要。
- **[ewgf.gg](https://ewgf.gg)** — 鉄拳8専門の統計サービス。Bearer token 認証。プレイヤーが手動でインデックス登録する必要あり。24時間の遅延がある。
