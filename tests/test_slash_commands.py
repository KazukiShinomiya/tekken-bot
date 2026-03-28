"""
bot/slash_commands.py のテスト。
Discord Interaction をモックして各コマンドハンドラの動作を検証する。
"""

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# discord モジュールをモックしてインポートエラーを回避する
# デコレーターは関数をそのまま返すパススルー型にする
def _noop_decorator(*args, **kwargs):
    """全引数を受け取り、対象の関数をそのまま返すデコレーター。"""
    def wrapper(f):
        return f
    return wrapper


_group_instance = MagicMock()
_group_instance.command = _noop_decorator

_app_commands_mock = types.ModuleType("discord.app_commands")
_app_commands_mock.CommandTree = MagicMock()
_app_commands_mock.Group = MagicMock(return_value=_group_instance)
_app_commands_mock.describe = _noop_decorator

_discord_mock = types.ModuleType("discord")
_discord_mock.Intents = MagicMock()
_discord_mock.Intents.default = MagicMock(return_value=MagicMock())
_discord_mock.Client = MagicMock()
_discord_mock.Embed = MagicMock(side_effect=lambda **kwargs: MagicMock(**kwargs))
_discord_mock.app_commands = _app_commands_mock
_discord_mock.Interaction = MagicMock()
sys.modules.setdefault("discord", _discord_mock)
sys.modules.setdefault("discord.app_commands", _app_commands_mock)

from bot.slash_commands import cmd_today, cmd_vs, cmd_chara, cmd_top, cmd_status  # noqa: E402


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _make_interaction() -> MagicMock:
    """Discord Interaction のモックを生成する。"""
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_battle(
    battle_id: str = "t1",
    battle_at: int = 1700000000,
    won: bool = True,
    opp_chara: str = "Jin",
    my_chara: str = "Lee",
) -> dict:
    return {
        "battle_id": battle_id,
        "battle_at": battle_at,
        "won": won,
        "my_chara": my_chara,
        "opp_chara": opp_chara,
        "opp_name": "TestOpp",
        "opp_polaris_id": "opp_pid",
        "my_rounds": 2,
        "opp_rounds": 1,
        "battle_type": "ranked",
        "rating_before": None,
        "rating_change": None,
    }


# ---------------------------------------------------------------------------
# /tekken today
# ---------------------------------------------------------------------------

def test_cmd_today_invalid_date():
    """無効な日付形式 → エラーメッセージを返す。"""
    interaction = _make_interaction()
    asyncio.run(cmd_today(interaction, date="not-a-date"))
    call_args = interaction.followup.send.call_args[0][0]
    assert "❌" in call_args


def test_cmd_today_valid_date():
    """有効な日付 → main() を呼び出して成功メッセージを返す。"""
    interaction = _make_interaction()
    with patch("main.main", new_callable=AsyncMock) as mock_main:
        asyncio.run(cmd_today(interaction, date="2026-03-01"))
        mock_main.assert_called_once_with(target_date="2026-03-01")
    call_args = interaction.followup.send.call_args[0][0]
    assert "✅" in call_args


def test_cmd_today_no_date():
    """日付省略 → 今日の日付で main() を呼び出す。"""
    interaction = _make_interaction()
    with patch("main.main", new_callable=AsyncMock) as mock_main:
        asyncio.run(cmd_today(interaction, date=None))
        mock_main.assert_called_once()
        target = mock_main.call_args.kwargs.get("target_date") or mock_main.call_args[1].get("target_date")
        assert target is not None


# ---------------------------------------------------------------------------
# /tekken vs
# ---------------------------------------------------------------------------

def test_cmd_vs_no_results():
    """対戦履歴なし → エラーメッセージを返す。"""
    interaction = _make_interaction()
    with patch("bot.db.search_battles_vs_opponent", return_value=[]):
        asyncio.run(cmd_vs(interaction, name="Unknown"))
    call_args = interaction.followup.send.call_args[0][0]
    assert "❌" in call_args


def test_cmd_vs_with_results():
    """対戦履歴あり → Embed を返す。"""
    interaction = _make_interaction()
    battles = [_make_battle(won=True), _make_battle(battle_id="t2", won=False)]
    with patch("bot.db.search_battles_vs_opponent", return_value=battles):
        asyncio.run(cmd_vs(interaction, name="TestOpp"))
    # followup.send が embed kwargs で呼ばれていることを確認
    assert interaction.followup.send.called
    kwargs = interaction.followup.send.call_args.kwargs
    assert "embed" in kwargs


def test_cmd_vs_win_rate_calculation():
    """3勝1敗なら勝率75%の Embed タイトルが生成される。"""
    interaction = _make_interaction()
    battles = [_make_battle(battle_id=f"t{i}", won=(i < 3)) for i in range(4)]
    with patch("bot.db.search_battles_vs_opponent", return_value=battles):
        asyncio.run(cmd_vs(interaction, name="TestOpp"))
    embed_arg = interaction.followup.send.call_args.kwargs["embed"]
    # 勝率 75% → color は緑 (0x57F287)
    assert embed_arg.color == 0x57F287


# ---------------------------------------------------------------------------
# /tekken chara
# ---------------------------------------------------------------------------

def test_cmd_chara_no_results():
    """対戦履歴なし → エラーメッセージを返す。"""
    interaction = _make_interaction()
    with patch("bot.db.get_battles_by_opp_chara", return_value=[]):
        asyncio.run(cmd_chara(interaction, name="Xiaoyu"))
    assert "❌" in interaction.followup.send.call_args[0][0]


def test_cmd_chara_with_results():
    """対戦履歴あり → Embed を返す。"""
    interaction = _make_interaction()
    battles = [_make_battle(opp_chara="Bryan")] * 5
    with patch("bot.db.get_battles_by_opp_chara", return_value=battles):
        asyncio.run(cmd_chara(interaction, name="Bryan"))
    assert interaction.followup.send.called
    assert "embed" in interaction.followup.send.call_args.kwargs


# ---------------------------------------------------------------------------
# /tekken top
# ---------------------------------------------------------------------------

def test_cmd_top_no_data():
    """データなし → エラーメッセージを返す。"""
    interaction = _make_interaction()
    with patch("bot.db.get_matchup_ranking", return_value=[]):
        asyncio.run(cmd_top(interaction))
    assert "❌" in interaction.followup.send.call_args[0][0]


def test_cmd_top_with_data():
    """ランキングデータあり → Embed を返す。"""
    interaction = _make_interaction()
    stats = [
        {"opp_chara": "Jin",   "wins": 5, "total": 8},
        {"opp_chara": "Bryan", "wins": 3, "total": 5},
    ]
    with patch("bot.db.get_matchup_ranking", return_value=stats):
        asyncio.run(cmd_top(interaction))
    assert "embed" in interaction.followup.send.call_args.kwargs


# ---------------------------------------------------------------------------
# /tekken status
# ---------------------------------------------------------------------------

def test_cmd_status_returns_online():
    """status コマンド → Bot 稼働中メッセージを返す。"""
    interaction = _make_interaction()
    asyncio.run(cmd_status(interaction))
    call_args = interaction.response.send_message.call_args[0][0]
    assert "✅" in call_args
    assert "Bot" in call_args
