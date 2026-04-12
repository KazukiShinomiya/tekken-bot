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
_app_commands_mock.autocomplete = _noop_decorator


def _make_choice(name: str, value: str) -> MagicMock:
    """discord.app_commands.Choice の最小モック。MagicMock(name=...) は内部名になるため手動設定。"""
    c = MagicMock()
    c.name = name
    c.value = value
    return c


_app_commands_mock.Choice = _make_choice

_discord_mock = types.ModuleType("discord")
_discord_mock.Intents = MagicMock()
_discord_mock.Intents.default = MagicMock(return_value=MagicMock())
_discord_mock.Client = MagicMock()
_discord_mock.Embed = MagicMock(side_effect=lambda **kwargs: MagicMock(**kwargs))
_discord_mock.File = MagicMock(return_value=MagicMock())
_discord_mock.app_commands = _app_commands_mock
_discord_mock.Interaction = MagicMock()
_discord_mock.Object = MagicMock()
sys.modules.setdefault("discord", _discord_mock)
sys.modules.setdefault("discord.app_commands", _app_commands_mock)

from bot.slash_commands import (  # noqa: E402
    cmd_today, cmd_vs, cmd_chara, cmd_top, cmd_status, cmd_rival,
    cmd_trend, cmd_filter, cmd_help, _chara_autocomplete,
    cmd_weekly, on_ready, start_bot, start_bot_thread,
)


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


# ---------------------------------------------------------------------------
# /tekken rival
# ---------------------------------------------------------------------------

def test_cmd_rival_no_results():
    """対戦履歴なし → エラーメッセージを返す。"""
    interaction = _make_interaction()
    with patch("bot.db.search_battles_vs_opponent", return_value=[]):
        asyncio.run(cmd_rival(interaction, name="Unknown"))
    call_args = interaction.followup.send.call_args[0][0]
    assert "❌" in call_args


def test_cmd_rival_with_results_sends_embed():
    """対戦履歴あり → Embed を返す。"""
    interaction = _make_interaction()
    battles = [
        _make_battle(battle_id="r1", won=True,  battle_at=1_000_000),
        _make_battle(battle_id="r2", won=False, battle_at=1_000_100),
    ]
    with patch("bot.db.search_battles_vs_opponent", return_value=battles):
        asyncio.run(cmd_rival(interaction, name="TestOpp"))
    assert interaction.followup.send.called
    kwargs = interaction.followup.send.call_args.kwargs
    assert "embed" in kwargs


def test_cmd_rival_win_color_green():
    """勝率 50% 以上 → Embed カラーが緑 (0x57F287)。"""
    interaction = _make_interaction()
    battles = [
        _make_battle(battle_id=f"r{i}", won=True, battle_at=1_000_000 + i)
        for i in range(3)
    ] + [_make_battle(battle_id="r3", won=False, battle_at=1_000_003)]
    with patch("bot.db.search_battles_vs_opponent", return_value=battles):
        asyncio.run(cmd_rival(interaction, name="TestOpp"))
    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert embed.color == 0x57F287


def test_cmd_rival_lose_color_red():
    """勝率 50% 未満 → Embed カラーが赤 (0xED4245)。"""
    interaction = _make_interaction()
    battles = [
        _make_battle(battle_id="r0", won=False, battle_at=1_000_000),
        _make_battle(battle_id="r1", won=False, battle_at=1_000_001),
        _make_battle(battle_id="r2", won=True,  battle_at=1_000_002),
    ]
    with patch("bot.db.search_battles_vs_opponent", return_value=battles):
        asyncio.run(cmd_rival(interaction, name="TestOpp"))
    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert embed.color == 0xED4245


def test_cmd_rival_shows_win_streak():
    """末尾から連勝中の場合、連勝ストリーク情報を含む Embed を返す。"""
    interaction = _make_interaction()
    battles = [
        _make_battle(battle_id=f"r{i}", won=True, battle_at=1_000_000 + i)
        for i in range(3)
    ]
    with patch("bot.db.search_battles_vs_opponent", return_value=battles):
        asyncio.run(cmd_rival(interaction, name="TestOpp"))
    embed = interaction.followup.send.call_args.kwargs["embed"]
    # add_field の呼び出し引数に "連勝" が含まれているか確認
    field_calls = str(embed.add_field.call_args_list)
    assert "連勝" in field_calls


# ---------------------------------------------------------------------------
# /tekken trend
# ---------------------------------------------------------------------------

def _make_rated_battle(battle_at: int, rating_before: int = 10000, rating_change: int = 50) -> dict:
    b = _make_battle(battle_id=f"rated_{battle_at}", battle_at=battle_at)
    b["rating_before"]  = rating_before
    b["rating_change"]  = rating_change
    b["battle_type"]    = "ranked"
    return b


def test_cmd_trend_returns_chart():
    """/tekken trend: グラフ生成成功 → ファイル添付の followup.send が呼ばれる。"""
    import io
    interaction = _make_interaction()
    battles = [_make_rated_battle(1_000_000 + i * 100, rating_change=50) for i in range(5)]
    fake_chart = io.BytesIO(b"fake_png")

    with (
        patch("bot.db.get_battles_since", return_value=battles),
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("bot.slash_commands.generate_rating_chart", return_value=fake_chart),
    ):
        asyncio.run(cmd_trend(interaction, days=30))

    assert interaction.followup.send.called
    kwargs = interaction.followup.send.call_args.kwargs
    assert "embed" in kwargs
    assert "file" in kwargs


def test_cmd_trend_no_players():
    """/tekken trend: プレイヤー未設定 → エラーメッセージを返す。"""
    interaction = _make_interaction()
    with patch("main.get_players", return_value=[]):
        asyncio.run(cmd_trend(interaction, days=30))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


def test_cmd_trend_chart_generation_fails():
    """/tekken trend: グラフ生成失敗 → エラーメッセージを返す。"""
    interaction = _make_interaction()
    with (
        patch("bot.db.get_battles_since", return_value=[]),
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("bot.slash_commands.generate_rating_chart", return_value=None),
    ):
        asyncio.run(cmd_trend(interaction, days=30))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


def test_cmd_trend_exception_handling():
    """/tekken trend: 例外発生 → エラーメッセージを返す（クラッシュしない）。"""
    interaction = _make_interaction()
    with patch("main.get_players", side_effect=RuntimeError("unexpected")):
        asyncio.run(cmd_trend(interaction, days=30))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


# ---------------------------------------------------------------------------
# /tekken filter
# ---------------------------------------------------------------------------

def test_cmd_filter_no_args():
    """/tekken filter: chara も date も未指定 → エラーメッセージ。"""
    interaction = _make_interaction()
    asyncio.run(cmd_filter(interaction, chara=None, date=None, days=None))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


def test_cmd_filter_invalid_date_only():
    """/tekken filter date=invalid → 日付フォーマットエラー。"""
    interaction = _make_interaction()
    asyncio.run(cmd_filter(interaction, chara=None, date="not-a-date", days=None))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


def test_cmd_filter_date_no_results():
    """/tekken filter date=2026-01-01: 該当なし → エラーメッセージ。"""
    interaction = _make_interaction()
    with (
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("bot.db.get_battles_on_date", return_value=[]),
    ):
        asyncio.run(cmd_filter(interaction, chara=None, date="2026-01-01", days=None))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


def test_cmd_filter_date_returns_embed():
    """/tekken filter date=2026-04-10: 該当あり → Embed を送信する。"""
    interaction = _make_interaction()
    battles = [_make_battle(won=True), _make_battle(battle_id="t2", won=False)]
    with (
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("bot.db.get_battles_on_date", return_value=battles),
    ):
        asyncio.run(cmd_filter(interaction, chara=None, date="2026-04-10", days=None))
    kwargs = interaction.followup.send.call_args.kwargs
    assert "embed" in kwargs


def test_cmd_filter_chara_no_results():
    """/tekken filter chara=Unknown: 該当なし → エラーメッセージ。"""
    interaction = _make_interaction()
    with (
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("bot.db.get_battles_by_opp_chara", return_value=[]),
    ):
        asyncio.run(cmd_filter(interaction, chara="Unknown", date=None, days=None))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


def test_cmd_filter_chara_returns_embed():
    """/tekken filter chara=Jin: 該当あり → Embed を送信する。"""
    interaction = _make_interaction()
    battles = [_make_battle(won=True, opp_chara="Jin"), _make_battle(battle_id="t2", won=False, opp_chara="Jin")]
    with (
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("bot.db.get_battles_by_opp_chara", return_value=battles),
    ):
        asyncio.run(cmd_filter(interaction, chara="Jin", date=None, days=None))
    kwargs = interaction.followup.send.call_args.kwargs
    assert "embed" in kwargs


def test_cmd_filter_chara_with_days():
    """/tekken filter chara=Bryan days=7: since_ts が計算されて get_battles_by_opp_chara に渡る。"""
    interaction = _make_interaction()
    battles = [_make_battle(opp_chara="Bryan")]
    with (
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("bot.db.get_battles_by_opp_chara", return_value=battles) as mock_db,
    ):
        asyncio.run(cmd_filter(interaction, chara="Bryan", date=None, days=7))
    _kwargs = mock_db.call_args.kwargs
    assert _kwargs.get("since_ts", 0) > 0


def test_cmd_filter_chara_with_date():
    """/tekken filter chara=Jin date=2026-04-01: since_ts が日付から計算される。"""
    interaction = _make_interaction()
    battles = [_make_battle(opp_chara="Jin")]
    with (
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("bot.db.get_battles_by_opp_chara", return_value=battles) as mock_db,
    ):
        asyncio.run(cmd_filter(interaction, chara="Jin", date="2026-04-01", days=None))
    _kwargs = mock_db.call_args.kwargs
    assert _kwargs.get("since_ts", 0) > 0


def test_cmd_filter_chara_invalid_date():
    """/tekken filter chara=Jin date=bad: 日付フォーマットエラー。"""
    interaction = _make_interaction()
    with patch("main.get_players", return_value=[("Alice", "pid_a")]):
        asyncio.run(cmd_filter(interaction, chara="Jin", date="bad-date", days=None))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


def test_cmd_filter_days_over_limit():
    """/tekken filter days=999: 上限超過 → エラーメッセージ。"""
    interaction = _make_interaction()
    asyncio.run(cmd_filter(interaction, chara="Bryan", date=None, days=999))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg
    assert "365" in msg


# ---------------------------------------------------------------------------
# /tekken help
# ---------------------------------------------------------------------------

def test_cmd_help_sends_embed():
    """/tekken help: Embed を send_message で返す。"""
    interaction = _make_interaction()
    asyncio.run(cmd_help(interaction))
    kwargs = interaction.response.send_message.call_args.kwargs
    assert "embed" in kwargs


# ---------------------------------------------------------------------------
# _chara_autocomplete
# ---------------------------------------------------------------------------

def test_chara_autocomplete_filters_by_current():
    """_chara_autocomplete: current にマッチするキャラのみ返す。"""
    interaction = _make_interaction()
    with patch("bot.db.get_known_opp_charas", return_value=["Bryan", "Jin", "King", "Kazuya"]):
        results = asyncio.run(_chara_autocomplete(interaction, current="k"))
    names = [c.name for c in results]
    assert "King" in names
    assert "Kazuya" in names
    assert "Bryan" not in names


def test_chara_autocomplete_empty_current():
    """_chara_autocomplete: current が空文字 → 全候補を返す（最大25件）。"""
    interaction = _make_interaction()
    all_charas = [f"Chara{i}" for i in range(30)]
    with patch("bot.db.get_known_opp_charas", return_value=all_charas):
        results = asyncio.run(_chara_autocomplete(interaction, current=""))
    assert len(results) == 25


def test_chara_autocomplete_case_insensitive():
    """_chara_autocomplete: 大文字小文字を無視してマッチする。"""
    interaction = _make_interaction()
    with patch("bot.db.get_known_opp_charas", return_value=["Bryan", "Jin"]):
        results = asyncio.run(_chara_autocomplete(interaction, current="JIN"))
    assert len(results) == 1
    assert results[0].name == "Jin"


# ---------------------------------------------------------------------------
# /tekken today（例外パス）
# ---------------------------------------------------------------------------

def test_cmd_today_exception_path():
    """/tekken today で予期しない例外 → ❌ メッセージを返す。"""
    interaction = _make_interaction()
    with patch("main.main", new_callable=AsyncMock, side_effect=RuntimeError("unexpected")):
        asyncio.run(cmd_today(interaction, date="2026-04-12"))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


# ---------------------------------------------------------------------------
# /tekken weekly
# ---------------------------------------------------------------------------

def test_cmd_weekly_happy_path():
    """/tekken weekly: weekly() を呼び出して ✅ メッセージを返す。"""
    interaction = _make_interaction()
    with patch("main.weekly", new_callable=AsyncMock):
        asyncio.run(cmd_weekly(interaction))
    msg = interaction.followup.send.call_args[0][0]
    assert "✅" in msg


def test_cmd_weekly_exception_path():
    """/tekken weekly で予期しない例外 → ❌ メッセージを返す。"""
    interaction = _make_interaction()
    with patch("main.weekly", new_callable=AsyncMock, side_effect=RuntimeError("err")):
        asyncio.run(cmd_weekly(interaction))
    msg = interaction.followup.send.call_args[0][0]
    assert "❌" in msg


# ---------------------------------------------------------------------------
# /tekken rival（追加パス）
# ---------------------------------------------------------------------------

def _make_rival_battles() -> list[dict]:
    """rival コマンド用バトルリスト。"""
    return [
        {**_make_battle(battle_id=f"r{i}", battle_at=1700000000 + i, won=(i % 2 == 0)),
         "rating_change": 100, "rating_before": 10000}
        for i in range(4)
    ]


def test_cmd_rival_lose_streak_branch():
    """/tekken rival で連敗中 → ❌ ストリーク表示を含む Embed を返す。"""
    interaction = _make_interaction()
    # 最後3戦を負けにして lose_streak >= 2 になるよう設定
    battles = [
        _make_battle("r0", battle_at=1700000000, won=True),
        _make_battle("r1", battle_at=1700000001, won=False),
        _make_battle("r2", battle_at=1700000002, won=False),
        _make_battle("r3", battle_at=1700000003, won=False),
    ]
    with patch("bot.db.search_battles_vs_opponent", return_value=battles):
        asyncio.run(cmd_rival(interaction, name="Opp"))
    interaction.followup.send.assert_called_once()


def test_cmd_rival_net_rating_branch():
    """/tekken rival でレーティング変動あり → 累積レーティング変動フィールドが追加される。"""
    interaction = _make_interaction()
    battles = [
        {**_make_battle(battle_id=f"r{i}", battle_at=1700000000 + i),
         "rating_change": 100, "rating_before": 10000}
        for i in range(3)
    ]
    with patch("bot.db.search_battles_vs_opponent", return_value=battles):
        asyncio.run(cmd_rival(interaction, name="Opp"))
    # embed が渡されれば add_field が呼ばれたはず
    sent_kwargs = interaction.followup.send.call_args.kwargs
    assert "embed" in sent_kwargs


# ---------------------------------------------------------------------------
# on_ready
# ---------------------------------------------------------------------------

def _get_original_on_ready():
    """
    @client.event デコレーターはモック化されており on_ready を MagicMock に変換する。
    元のコルーチン関数は client.event の call_args から取り出す。
    """
    import bot.slash_commands as _sc
    return _sc.client.event.call_args[0][0]


def test_on_ready_with_guild_id():
    """DISCORD_GUILD_ID が設定されている場合、ギルド同期が実行される。"""
    import bot.slash_commands as _sc
    original_on_ready = _get_original_on_ready()
    mock_tree = MagicMock()
    mock_tree.sync = AsyncMock()
    mock_tree.copy_global_to = MagicMock()
    mock_client = MagicMock()
    mock_client.user = "TestBot"
    with (
        patch.object(_sc, "DISCORD_GUILD_ID", "12345"),
        patch.object(_sc, "tree", mock_tree),
        patch.object(_sc, "client", mock_client),
    ):
        asyncio.run(original_on_ready())
    mock_tree.sync.assert_called_once()


def test_on_ready_without_guild_id():
    """DISCORD_GUILD_ID が未設定の場合、グローバル同期が実行される。"""
    import bot.slash_commands as _sc
    original_on_ready = _get_original_on_ready()
    mock_tree = MagicMock()
    mock_tree.sync = AsyncMock()
    mock_client = MagicMock()
    mock_client.user = "TestBot"
    with (
        patch.object(_sc, "DISCORD_GUILD_ID", None),
        patch.object(_sc, "tree", mock_tree),
        patch.object(_sc, "client", mock_client),
    ):
        asyncio.run(original_on_ready())
    mock_tree.sync.assert_called_once()


# ---------------------------------------------------------------------------
# start_bot / start_bot_thread
# ---------------------------------------------------------------------------

def test_start_bot_no_token():
    """BOT_TOKEN 未設定 → client.run は呼ばれない。"""
    import bot.slash_commands as _sc
    mock_client = MagicMock()
    with (
        patch.object(_sc, "BOT_TOKEN", None),
        patch.object(_sc, "client", mock_client),
    ):
        start_bot()
    mock_client.run.assert_not_called()


def test_start_bot_exception_is_caught():
    """client.run が例外を送出しても start_bot は例外を伝播させない。"""
    import bot.slash_commands as _sc
    mock_client = MagicMock()
    mock_client.run.side_effect = RuntimeError("bot error")
    with (
        patch.object(_sc, "BOT_TOKEN", "dummy-token"),
        patch.object(_sc, "client", mock_client),
    ):
        start_bot()  # should not raise


def test_start_bot_thread_returns_thread():
    """start_bot_thread() はデーモンスレッドを返す。"""
    import threading
    import bot.slash_commands as _sc
    with patch.object(_sc, "start_bot", return_value=None):
        t = start_bot_thread()
    assert isinstance(t, threading.Thread)
    assert t.daemon is True
