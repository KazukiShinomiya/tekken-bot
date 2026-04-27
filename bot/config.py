"""
環境変数による設定の一元管理。
各モジュールに散在していた os.getenv() をここに集約する。
"""

import os
from datetime import timezone, timedelta
from pathlib import Path

# ── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
# カンマ区切りで複数 Webhook URL をサポート（例: "https://...,...,https://..."）
WEBHOOK_URLS: list[str] = [
    u.strip() for u in (DISCORD_WEBHOOK_URL or "").split(",") if u.strip()
]
DISCORD_BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN")
# ギルドIDを設定するとスラッシュコマンドが即時反映（未設定=グローバル同期、最大1時間）
DISCORD_GUILD_ID    = os.getenv("DISCORD_GUILD_ID")

# ── プレイヤー設定 ─────────────────────────────────────────────────────────
TEKKEN_ID  = os.getenv("TEKKEN_ID", "")
POLARIS_ID = os.getenv("POLARIS_ID")
PLAYERS    = os.getenv("PLAYERS", "").strip()

# ── API ───────────────────────────────────────────────────────────────────────
EWGF_API_KEY = os.getenv("EWGF_API_KEY")

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_URL            = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL          = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
# プライマリモデルが失敗・タイムアウトした場合に試みるフォールバックモデル（空文字=無効）
# 例: OLLAMA_FALLBACK_MODEL=gemma3:4b  または  phi4
OLLAMA_FALLBACK_MODEL = os.getenv("OLLAMA_FALLBACK_MODEL", "")

# ── ストレージ・ログ ──────────────────────────────────────────────────────────
DB_PATH  = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "battles.db")))
LOG_PATH = os.getenv("LOG_PATH", "data/tekken_bot.log")

# ── Exporter ──────────────────────────────────────────────────────────────────
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "9877"))

# ── タイムゾーン ──────────────────────────────────────────────────────────────
JST = timezone(timedelta(hours=9))

# ── タイムアウト（秒） ────────────────────────────────────────────────────────
TIMEOUT_API           = int(os.getenv("TIMEOUT_API", "15"))    # wank / ewgf.gg API
TIMEOUT_LLM           = int(os.getenv("TIMEOUT_LLM", "600"))  # qwen2.5:7b 実測～110秒、週次はさらに長め
TIMEOUT_WEBHOOK       = int(os.getenv("TIMEOUT_WEBHOOK", "10"))        # Discord Webhook（テキストのみ）
TIMEOUT_WEBHOOK_IMAGE = int(os.getenv("TIMEOUT_WEBHOOK_IMAGE", "15"))  # Discord Webhook（画像添付）

# ── 通知設定 ──────────────────────────────────────────────────────────────────
RATING_GOAL = int(os.getenv("RATING_GOAL", "0"))  # 0=無効

STAGE_NAMES: dict[int, str] = {
    # wank.wavu.wiki の stage_id → Tekken 8 ステージ名
    # 実データで確認できた ID のみ記載。不明 ID は "Stage #N" にフォールバック。
    # 実際の対戦ログで ID が判明したら随時追記してください。
}


def validate_config() -> list[str]:
    """
    設定の問題点をリストで返す。空リストなら問題なし。
    main() の冒頭で呼んで sys.exit() する想定。
    """
    errors: list[str] = []
    if not DISCORD_WEBHOOK_URL:
        errors.append("DISCORD_WEBHOOK_URL が未設定（Discord 投稿不可）")
    if not POLARIS_ID and not PLAYERS:
        errors.append("POLARIS_ID または PLAYERS が未設定（プレイヤーデータ取得不可）")
    return errors


# ── マジックナンバー定数 ──────────────────────────────────────────────────────
# HTTP リトライ設定
RETRY_TOTAL          = 3
RETRY_BACKOFF_FACTOR = 1.0
RETRY_STATUS_CODES   = [429, 500, 502, 503, 504]

# バトル取得
WANK_FETCH_LIMIT = 50

# スタッツ計算
MIN_BATTLES_FOR_STAT         = 2
RATING_STAGNATION_THRESHOLD  = 100

# Discord
DISCORD_EMBED_MAX_FIELDS = 25

# デフォルト値
UNKNOWN_CHARACTER = "???"

# 鉄拳8段位マッピング（wank bulk API の rank 整数値 → 段位名）
# Season 2 対応（0-indexed、Beginner=0）
RANK_NAMES: dict[int, str] = {
    0:  "Beginner",
    1:  "1st Dan",
    2:  "2nd Dan",
    3:  "Fighter",
    4:  "Strategist",
    5:  "Combatant",
    6:  "Brawler",
    7:  "Ranger",
    8:  "Cavalry",
    9:  "Warrior",
    10: "Assailant",
    11: "Dominator",
    12: "Vanquisher",
    13: "Destroyer",
    14: "Eliminator",
    15: "Garyu",
    16: "Shinryu",
    17: "Tenryu",
    18: "Mighty Ruler",
    19: "Flame Ruler",
    20: "Battle Ruler",
    21: "Fujin",
    22: "Raijin",
    23: "Kishin",
    24: "Bushin",
    25: "Tekken King",
    26: "Tekken Emperor",
    27: "Tekken God",
    28: "Tekken God Supreme",
    29: "God of Destruction",
}
