# Tekken Bot

鉄拳8の対戦履歴を自動収集し、毎日 Discord に投稿する Bot。
ローカル LLM によるコーチコメント生成機能付き。

---

## スクリーンショット（投稿イメージ）

```
🎮 YourTekkenID 本日の戦果 (2026/03/14)
━━━━━━━━━━━━━━━
⚔️  Lee vs Dragunov     ✅ 3-2
⚔️  Lee vs Jin          ✅ 3-0
⚔️  Lee vs Reina        ❌ 1-3
━━━━━━━━━━━━━━━
🏆 ランク  2勝1敗 (67%) | 1751 (+2)
━━━━━━━━━━━━━━━
🎯 ラウンド勝率: 72% | 接戦(3-2): 1試合
🔥 連勝: 2
😤 天敵: Reina (0勝1敗, 0%)
💥 テッケンパワー: 185,000

🤖 今日はランク戦で安定した成績を収めた。
   Reina戦は接近戦での対応が課題。次回は
   距離管理を意識すると勝率が上がるだろう。
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
                         │ デプロイ (scp)
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
│  │       │                (qwen2.5:3b)        │    │
│  │       │                                    │    │
│  │       └─ discord_post.py → Discord Webhook │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  ┌──────────────┐                                   │
│  │ Ollama       │  qwen2.5:3b (CPU推論)             │
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

データソースを3段階で試みる。

```
ewgf.gg API（最もリッチ・現在インデックス待ち）
  ↓ 失敗
wank HTML + バルクAPI enrichment（フルフィールド）
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

- モデル: `qwen2.5:3b`（Apache 2.0、商用利用可）
- 推論速度: 約30〜60秒（CPU のみ）
- Docker コンテナからは `network_mode: host` で localhost に直接接続

毎日1回しか動かないボットなので、CPUの遅さは問題にならない。

---

## セットアップ

### 必要なもの

- Python 3.13+
- Docker / Docker Compose
- Discord Webhook URL
- wank.wavu.wiki の Polaris ID（プロフィールURLから確認）
- （任意）ewgf.gg API Key
- （任意）Ollama + qwen2.5:3b

### .env 設定

```env
TEKKEN_ID=YourTekkenID
POLARIS_ID=YourPolarisID
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
EWGF_API_KEY=your_key_here
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
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

毎日 23:00 JST に自動実行される。

---

## ファイル構成

```
tekken_bot/
├── main.py          # エントリポイント
├── scheduler.py     # 定時実行スケジューラ（Docker用）
├── fetcher.py       # データ取得（ewgf.gg / wank HTML + バルクAPI）
├── db.py            # SQLite永続化
├── discord_post.py  # Discord投稿・メッセージ整形
├── analyzer.py      # ローカルLLM分析（Ollama）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env             # 秘匿情報（gitignore推奨）
└── data/
    └── battles.db   # SQLiteデータベース（Dockerボリューム）
```

---

## データソース

- **[wank.wavu.wiki](https://wank.wavu.wiki)** — 鉄拳8のリプレイデータを公開しているコミュニティサイト。認証不要。
- **[ewgf.gg](https://ewgf.gg)** — 鉄拳8専門の統計サービス。Bearer token 認証。プレイヤーが手動でインデックス登録する必要あり。
