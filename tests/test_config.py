"""
bot/config.py の validate_config テスト。
"""

from unittest.mock import patch
from bot.config import validate_config, RANK_NAMES, RANK_NAMES_EN

# 段位の英語名を番号順に並べた梯子（0-37）。
# 出典: ewgf-gg/ewgfgg-backend tekken_enums.json / elgonio/TK8-thing enums.py（一致確認済み）。
# RANK_NAMES_EN の対応ずれ（訳語の類似による誤対応）を検出するためのピン。
RANK_LADDER_EN = [
    "Beginner", "1st Dan", "2nd Dan",
    "Fighter", "Strategist", "Combatant",
    "Brawler", "Ranger", "Cavalry",
    "Warrior", "Assailant", "Dominator",
    "Vanquisher", "Destroyer", "Eliminator",
    "Garyu", "Shinryu", "Tenryu",
    "Mighty Ruler", "Flame Ruler", "Battle Ruler",
    "Fujin", "Raijin", "Kishin", "Bushin",
    "Tekken King", "Tekken Emperor", "Tekken God", "Tekken God Supreme",
    "God of Destruction",
    "God of Destruction I", "God of Destruction II", "God of Destruction III",
    "God of Destruction IV", "God of Destruction V", "God of Destruction VI",
    "God of Destruction VII", "God of Destruction ∞",
]


def test_rank_names_en_aligned_by_rank_number():
    """英日の段位対応は同じ段位番号で揃う（例: 13番 Destroyer=羅刹、翻訳類似の 戒拳 ではない）。"""
    for i, en in enumerate(RANK_LADDER_EN):
        assert RANK_NAMES_EN[en] == RANK_NAMES[i], (
            f"rank {i}: {en} は {RANK_NAMES[i]} であるべきだが "
            f"{RANK_NAMES_EN.get(en)} になっている"
        )


def test_rank_names_en_has_no_stale_entries():
    """鉄拳8に存在しない段位名（T7由来の Warlord / True Tekken God 等）が混入していない。"""
    assert set(RANK_NAMES_EN) == set(RANK_LADDER_EN)


def test_validate_config_no_errors():
    """WEBHOOK_URL と POLARIS_ID が設定済み → エラーなし。"""
    with (
        patch("bot.config.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/tok"),
        patch("bot.config.POLARIS_ID", "pid_x"),
        patch("bot.config.PLAYERS", []),
    ):
        errors = validate_config()
    assert errors == []


def test_validate_config_missing_webhook():
    """WEBHOOK_URL 未設定 → エラーリストに含まれる。"""
    with (
        patch("bot.config.DISCORD_WEBHOOK_URL", None),
        patch("bot.config.POLARIS_ID", "pid_x"),
        patch("bot.config.PLAYERS", []),
    ):
        errors = validate_config()
    assert any("DISCORD_WEBHOOK_URL" in e for e in errors)


def test_validate_config_missing_player_ids():
    """POLARIS_ID も PLAYERS も未設定 → エラーリストに含まれる。"""
    with (
        patch("bot.config.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/tok"),
        patch("bot.config.POLARIS_ID", None),
        patch("bot.config.PLAYERS", []),
    ):
        errors = validate_config()
    assert any("POLARIS_ID" in e for e in errors)


def test_validate_config_players_without_polaris_id():
    """PLAYERS が設定されていれば POLARIS_ID なしでもエラーなし。"""
    with (
        patch("bot.config.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/tok"),
        patch("bot.config.POLARIS_ID", None),
        patch("bot.config.PLAYERS", [("Alice", "pid_alice")]),
    ):
        errors = validate_config()
    assert not any("POLARIS_ID" in e for e in errors)
