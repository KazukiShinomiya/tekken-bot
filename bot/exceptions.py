"""
Tekken Bot 固有の例外クラス。
将来的な例外型の統一・キャッチ精度向上のための基盤。
"""


class TekkenBotError(Exception):
    """Tekken Bot の基底例外クラス。"""


class DataFetchError(TekkenBotError):
    """バトルデータの取得失敗。"""


class DiscordPostError(TekkenBotError):
    """Discord Webhook への投稿失敗。"""


class AnalysisError(TekkenBotError):
    """LLM 分析の失敗。"""


class DatabaseError(TekkenBotError):
    """データベース操作の失敗。"""
