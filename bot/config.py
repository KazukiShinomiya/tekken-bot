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
# エラー専用 Webhook。設定するとエラー通知が別チャンネルに届く（未設定=WEBHOOK_URLS に fallback）
DISCORD_ERROR_WEBHOOK_URL = os.getenv("DISCORD_ERROR_WEBHOOK_URL")
ERROR_WEBHOOK_URLS: list[str] = [
    u.strip() for u in (DISCORD_ERROR_WEBHOOK_URL or "").split(",") if u.strip()
]

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

# ── Gemini（Ollama 完全失敗時の最終フォールバックLLM） ───────────────────────────
# 無料枠: 15 RPM / 1M tokens/day。未設定=Gemini フォールバック無効。
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
# true/1/yes を設定すると Gemini を優先し、Ollama をフォールバックにする（評価・比較用）
GEMINI_FIRST   = os.getenv("GEMINI_FIRST", "").lower() in ("1", "true", "yes")

# ── ストレージ・ログ ──────────────────────────────────────────────────────────
DB_PATH  = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "battles.db")))
LOG_PATH = os.getenv("LOG_PATH", "data/tekken_bot.log")

# ── Exporter ──────────────────────────────────────────────────────────────────
EXPORTER_PORT = int(os.getenv("EXPORTER_PORT", "9877"))

# ── タイムゾーン ──────────────────────────────────────────────────────────────
JST = timezone(timedelta(hours=9))

# ── タイムアウト（秒） ────────────────────────────────────────────────────────
TIMEOUT_API           = int(os.getenv("TIMEOUT_API", "15"))    # wank / ewgf.gg API
TIMEOUT_LLM           = int(os.getenv("TIMEOUT_LLM", "900"))  # qwen2.5:7b 実測～110秒、週次はさらに長め
TIMEOUT_WEBHOOK       = int(os.getenv("TIMEOUT_WEBHOOK", "10"))        # Discord Webhook（テキストのみ）
TIMEOUT_WEBHOOK_IMAGE = int(os.getenv("TIMEOUT_WEBHOOK_IMAGE", "15"))  # Discord Webhook（画像添付）

# ── 通知設定 ──────────────────────────────────────────────────────────────────
RATING_GOAL = int(os.getenv("RATING_GOAL", "0"))  # 0=無効

STAGE_NAMES: dict[int, str] = {
    # wank.wavu.wiki の stage_id → Tekken 8 ステージ名
    # 出典: github.com/elgonio/TK8-thing/blob/master/enums.py
    # X01 は X00 の昼夜バリアント（例: Arena Underground = Arena の夜版）
    100:  "Arena",
    101:  "Arena Underground",
    200:  "Urban Square",
    201:  "Urban Square Evening",
    300:  "Yakushima",
    400:  "Coliseum of Fate",
    500:  "Rebel Hangar",
    # 600: 名称未確認（DB に1件あり。下方の 1700 系コメント参照）
    700:  "Fallen Destiny",
    # 800: 対戦なし（未確認）
    900:  "Descent into Subconscious",
    1000: "Sanctum",
    1100: "Into the Stratosphere",
    1200: "Ortiz Farm",
    1300: "Celebration on the Seine",
    1400: "Secluded Training Ground",
    1500: "Elegant Palace",
    1600: "Midnight Siege",
    # 600, 1700, 1800/1801, 1900, 2200: 名称未確認の DLC 系ステージ。
    # 2026-07-09 調査: TK8-thing（フォーク含む）・ewgf-gg 実装とも 1600 番までしか
    # 収録せず、wank の対戦履歴ページはステージ名を表示しない＝外部ソースでは特定不能。
    # ゲーム内リプレイで該当対戦（例: 600 は 2026-03-12 21:08 JST vs hiiragi の Paul 戦）の
    # ステージを実機確認して追記する。推測での記入は禁止（CHARA_NAMES の教訓）。
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

# 未投稿日の遅延回収（backfill）。
# ewgf のクイックマッチは実測で約34時間遅れて到着するため、対戦当日の日次投稿には
# 間に合わない。取りこぼした日を後追いで投稿するために遡る日数。
BACKFILL_DAYS = 7

# スタッツ計算
MIN_BATTLES_FOR_STAT         = 2    # 対キャラ統計・時間帯統計の最低試合数
MIN_BATTLES_FOR_TREND        = 3    # レーティングトレンド回帰計算の最低試合数
MIN_TREND_SPAN_SECONDS       = 3 * 86400  # 同・最低観測窓。これ未満は「1日あたり」へ外挿しない
RATING_STAGNATION_THRESHOLD  = 100  # 停滞判定の1日あたり変動幅（±ポイント）

# 勝率判定しきい値
WIN_RATE_THRESHOLD       = 0.5   # 天敵判定・アイコン選択（50%ライン）
WEAK_CHARA_THRESHOLD     = 0.4   # 苦手キャラ判定（勝率40%未満）
STRONG_CHARA_THRESHOLD   = 0.7   # 得意キャラ判定（勝率70%以上）
TREND_WIN_RATE_THRESHOLD = 0.1   # 前日比トレンド判定（10pt 以上の差）
MOMENTUM_THRESHOLD       = 0.2   # 調子の波判定（前後半勝率差 20pt 以上）
SCOUT_TREND_THRESHOLD    = 5.0   # スカウト傾向判定（勝率差 %ポイント）
EMBED_COLOR_GOOD_WR      = 0.6   # Embed 緑カラー（勝率60%以上）
EMBED_COLOR_BAD_WR       = 0.4   # Embed 赤カラー（勝率40%以下）

# Discord
DISCORD_EMBED_MAX_FIELDS = 25
MATCHUP_MATRIX_MAX_ROWS  = 12   # 対戦成績表の最大行数。超過分は件数のみ集約表示
DESCRIPTION_CODE_LIMIT   = 3400 # 日次 description のコードブロック上限。
                                # 実上限 4096 との差は、投稿後に差し込まれる
                                # LLM コメントぶんの余白（閉じ ``` を落とさないため）

# デフォルト値
UNKNOWN_CHARACTER = "???"

# 鉄拳8段位マッピング（wank bulk API の rank 整数値 → 段位名）
# Season 3 対応（0-indexed、入門生=0）、破壊神∞(37)まで
RANK_NAMES: dict[int, str] = {
    0:  "入門生",
    1:  "初段",
    2:  "二段",
    3:  "勇士",
    4:  "策士",
    5:  "闘士",
    6:  "餓狼",
    7:  "荒鷲",
    8:  "猛象",
    9:  "剛拳",
    10: "邪拳",
    11: "戒拳",
    12: "修羅",
    13: "羅刹",
    14: "羅傑",
    15: "臥龍",
    16: "真龍",
    17: "天龍",
    18: "拳帝",
    19: "炎帝",
    20: "戦帝",
    21: "風神",
    22: "雷神",
    23: "鬼神",
    24: "武神",
    25: "鉄拳王",
    26: "鉄拳覇皇",
    27: "鉄拳神",
    28: "鉄拳神極",
    29: "破壊神",
    30: "破壊神壱",
    31: "破壊神弐",
    32: "破壊神参",
    33: "破壊神肆",
    34: "破壊神伍",
    35: "破壊神陸",
    36: "破壊神漆",
    37: "破壊神∞",
}

# wank バルクAPI が英語文字列で rank を返す場合の日本語変換テーブル
# 対応は「同じ段位番号」で取る（訳語の類似で対応させない。Fighter は3番なので勇士、
# 闘士は5番 Combatant）。出典: ewgf-gg/ewgfgg-backend tekken_enums.json と
# elgonio/TK8-thing enums.py（両者一致、2026-07-09 照合）
RANK_NAMES_EN: dict[str, str] = {
    "Beginner":               "入門生",    # 0
    "1st Dan":                "初段",      # 1
    "2nd Dan":                "二段",      # 2
    "Fighter":                "勇士",      # 3
    "Strategist":             "策士",      # 4
    "Combatant":              "闘士",      # 5
    "Brawler":                "餓狼",      # 6
    "Ranger":                 "荒鷲",      # 7
    "Cavalry":                "猛象",      # 8
    "Warrior":                "剛拳",      # 9
    "Assailant":              "邪拳",      # 10
    "Dominator":              "戒拳",      # 11
    "Vanquisher":             "修羅",      # 12
    "Destroyer":              "羅刹",      # 13
    "Eliminator":             "羅傑",      # 14
    "Garyu":                  "臥龍",      # 15
    "Shinryu":                "真龍",      # 16
    "Tenryu":                 "天龍",      # 17
    "Mighty Ruler":           "拳帝",      # 18
    "Flame Ruler":            "炎帝",      # 19
    "Battle Ruler":           "戦帝",      # 20
    "Fujin":                  "風神",      # 21
    "Raijin":                 "雷神",      # 22
    "Kishin":                 "鬼神",      # 23
    "Bushin":                 "武神",      # 24
    "Tekken King":            "鉄拳王",    # 25
    "Tekken Emperor":         "鉄拳覇皇",  # 26
    "Tekken God":             "鉄拳神",    # 27
    "Tekken God Supreme":     "鉄拳神極",  # 28
    "God of Destruction":     "破壊神",    # 29
    "God of Destruction I":   "破壊神壱",  # 30
    "God of Destruction II":  "破壊神弐",  # 31
    "God of Destruction III": "破壊神参",  # 32
    "God of Destruction IV":  "破壊神肆",  # 33
    "God of Destruction V":   "破壊神伍",  # 34
    "God of Destruction VI":  "破壊神陸",  # 35
    "God of Destruction VII": "破壊神漆",  # 36
    "God of Destruction ∞":   "破壊神∞",  # 37
}

# 段位番号の逆引き（EN 文字列 → 番号）。wank は整数・ewgf は英語文字列で rank を
# 返すため、段位の比較・ソートはこの表で番号へ正規化してから行う
_RANK_IDS_BY_JP = {jp: num for num, jp in RANK_NAMES.items()}
RANK_IDS_EN: dict[str, int] = {en: _RANK_IDS_BY_JP[jp] for en, jp in RANK_NAMES_EN.items()}


def normalize_rank(rank: int | str | None) -> int | None:
    """rank 値を段位番号へ正規化する。wank は整数・ewgf は英語文字列で返すため、
    DB には両方の型が混在する。未知の文字列（表に無い段位名）は None。"""
    if isinstance(rank, bool):  # bool は int のサブクラス。段位ではないので弾く
        return None
    if isinstance(rank, int):
        return rank
    if isinstance(rank, str):
        if rank in RANK_IDS_EN:
            return RANK_IDS_EN[rank]
        return int(rank) if rank.lstrip("-").isdigit() else None
    return None
