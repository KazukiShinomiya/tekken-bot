"""
bot/config.py の validate_config テスト。
"""

from unittest.mock import patch
from bot.config import validate_config


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
