"""
環境変数による設定の一元管理。
各モジュールに散在していた os.getenv() をここに集約する。
"""

import os
from datetime import timezone, timedelta
from pathlib import Path

# ── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN")

# ── プレイヤー設定 ─────────────────────────────────────────────────────────
TEKKEN_ID  = os.getenv("TEKKEN_ID", "")
POLARIS_ID = os.getenv("POLARIS_ID")
PLAYERS    = os.getenv("PLAYERS", "").strip()

# ── API ───────────────────────────────────────────────────────────────────────
EWGF_API_KEY = os.getenv("EWGF_API_KEY")

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# ── ストレージ・ログ ──────────────────────────────────────────────────────────
DB_PATH  = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "battles.db")))
LOG_PATH = os.getenv("LOG_PATH", "data/tekken_bot.log")

# ── Exporter ──────────────────────────────────────────────────────────────────
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "9877"))

# ── タイムゾーン ──────────────────────────────────────────────────────────────
JST = timezone(timedelta(hours=9))

# ── タイムアウト（秒） ────────────────────────────────────────────────────────
TIMEOUT_API           = 15   # wank / ewgf.gg API
TIMEOUT_LLM           = 300  # Ollama（7bモデル、CPU推論で実測約2分）
TIMEOUT_WEBHOOK       = 10   # Discord Webhook（テキストのみ）
TIMEOUT_WEBHOOK_IMAGE = 15   # Discord Webhook（画像添付）
