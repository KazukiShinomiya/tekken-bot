"""
bot/discord_post.py の純粋関数テスト。
"""

import pytest
from unittest.mock import MagicMock, patch
from bot.discord_post import (
    _win_rate,
    _streak,
    _nemesis,
    _rating_summary,
    _matchup_matrix,
    _quick_rank_chara_matrix,
    _scout_section,
    _opp_rank_label,
    _quick_rank_distribution,
    _parse_webhook_id_token,
    _embed_color,
    build_community_weekly_embed,
    build_embed,
    build_weekly_embed,
    build_rank_change_embed,
    build_monthly_embed,
    post,
    post_weekly,
    post_monthly,
    post_rank_change,
    post_community_weekly,
    edit_llm_comment,
    notify,
    notify_error,
)


def _battle(won: bool, opp_chara: str = "Jin", my_chara: str = "Reina",
            rating_before: int | None = None, rating_change: int | None = None,
            my_rounds: int = 2, opp_rounds: int = 1,
            battle_type: str = "ranked", battle_at: int = 1000) -> dict:
    return {
        "won": won,
        "opp_chara": opp_chara,
        "my_chara": my_chara,
        "rating_before": rating_before,
        "rating_change": rating_change,
        "my_rounds": my_rounds,
        "opp_rounds": opp_rounds,
        "battle_type": battle_type,
        "battle_at": battle_at,
        "my_power": None,
    }


# ---------------------------------------------------------------------------
# _win_rate
# ---------------------------------------------------------------------------

def test_win_rate_all_wins():
    battles = [_battle(True), _battle(True), _battle(True)]
    assert _win_rate(battles) == "100%"


def test_win_rate_all_losses():
    battles = [_battle(False), _battle(False)]
    assert _win_rate(battles) == "0%"


def test_win_rate_mixed():
    battles = [_battle(True), _battle(False)]
    assert _win_rate(battles) == "50%"


def test_win_rate_empty():
    assert _win_rate([]) == "-"


def test_win_rate_75():
    battles = [_battle(True), _battle(True), _battle(True), _battle(False)]
    assert _win_rate(battles) == "75%"


# ---------------------------------------------------------------------------
# _streak
# ---------------------------------------------------------------------------

def test_streak_win_streak():
    battles = [_battle(True), _battle(True), _battle(True), _battle(False)]
    max_win, max_lose = _streak(battles)
    assert max_win == 3
    assert max_lose == 1


def test_streak_lose_streak():
    battles = [_battle(False), _battle(False), _battle(True)]
    max_win, max_lose = _streak(battles)
    assert max_win == 1
    assert max_lose == 2


def test_streak_no_streak():
    battles = [_battle(True), _battle(False), _battle(True)]
    max_win, max_lose = _streak(battles)
    assert max_win == 1
    assert max_lose == 1


def test_streak_empty():
    assert _streak([]) == (0, 0)


def test_streak_all_wins():
    battles = [_battle(True)] * 5
    max_win, max_lose = _streak(battles)
    assert max_win == 5
    assert max_lose == 0


# ---------------------------------------------------------------------------
# _nemesis
# ---------------------------------------------------------------------------

def test_nemesis_found():
    battles = [
        _battle(False, "Dragunov"),
        _battle(False, "Dragunov"),
        _battle(True, "Jin"),
        _battle(True, "Jin"),
    ]
    result = _nemesis(battles)
    assert result is not None
    assert "Dragunov" in result


def test_nemesis_no_nemesis_when_winning():
    battles = [
        _battle(True, "Dragunov"),
        _battle(True, "Dragunov"),
    ]
    assert _nemesis(battles) == None


def test_nemesis_not_enough_battles():
    battles = [_battle(False, "Dragunov")]
    assert _nemesis(battles) == None


def test_nemesis_empty():
    assert _nemesis([]) == None


def test_nemesis_exactly_50_percent():
    battles = [_battle(True, "Dragunov"), _battle(False, "Dragunov")]
    assert _nemesis(battles) == None  # 50% は天敵なし


# ---------------------------------------------------------------------------
# _rating_summary
# ---------------------------------------------------------------------------

def test_rating_summary_gain():
    battles = [
        _battle(True, rating_before=10000, rating_change=50, battle_at=1000),
        _battle(True, rating_before=10050, rating_change=50, battle_at=2000),
    ]
    result = _rating_summary(battles)
    assert "10100" in result
    assert "+100" in result


def test_rating_summary_loss():
    battles = [
        _battle(False, rating_before=10000, rating_change=-30, battle_at=1000),
    ]
    result = _rating_summary(battles)
    assert "9970" in result
    assert "-30" in result


def test_rating_summary_no_data():
    battles = [_battle(True)]
    assert _rating_summary(battles) == ""


def test_rating_summary_empty():
    assert _rating_summary([]) == ""


# ---------------------------------------------------------------------------
# _matchup_matrix
# ---------------------------------------------------------------------------

def test_matchup_matrix_basic():
    battles = [
        _battle(True, "Dragunov"), _battle(True, "Dragunov"),
        _battle(False, "Jin"), _battle(False, "Jin"),
    ]
    result = _matchup_matrix(battles)
    assert result is not None
    assert "Dragunov" in result
    assert "Jin" in result
    assert "✅" in result
    assert "❌" in result


def test_matchup_matrix_50_percent():
    battles = [_battle(True, "Jin"), _battle(False, "Jin")]
    result = _matchup_matrix(battles)
    assert result is not None
    assert "➖" in result


def test_matchup_matrix_not_enough_battles():
    battles = [_battle(True, "Jin")]  # 1戦のみ（閾値1戦から表示）
    result = _matchup_matrix(battles)
    assert result is not None
    assert "Jin" in result


def test_matchup_matrix_sorted_by_win_rate():
    battles = [
        _battle(True, "Dragunov"), _battle(True, "Dragunov"),   # 100%
        _battle(False, "Jin"), _battle(False, "Jin"),            # 0%
    ]
    result = _matchup_matrix(battles)
    assert result is not None
    lines = result.split("\n")
    # Dragunov（100%）が Jin（0%）より先に来るはず
    dragunov_idx = next(i for i, l in enumerate(lines) if "Dragunov" in l)
    jin_idx = next(i for i, l in enumerate(lines) if "Jin" in l)
    assert dragunov_idx < jin_idx


def test_matchup_matrix_empty():
    assert _matchup_matrix([]) is None


# ---------------------------------------------------------------------------
# _scout_section
# ---------------------------------------------------------------------------

def _scout_battle(opp_pid: str, opp_name: str = "Opp", battle_at: int = 1000) -> dict:
    b = _battle(True, battle_at=battle_at)
    b["opp_polaris_id"] = opp_pid
    b["opp_name"] = opp_name
    return b


def test_scout_section_shows_repeat_opponent():
    """2戦以上した相手のスカウト情報が表示される。"""
    battles = [_scout_battle("pid1", "TestOpp"), _scout_battle("pid1", "TestOpp")]
    scout_data = {
        "pid1": {
            "total": 20, "win_rate": 60.0, "main_chara": "Jin",
            "recent_wins": 6, "recent_total": 10, "recent_win_rate": 60.0,
        }
    }
    result = _scout_section(battles, scout_data)
    assert result is not None
    assert "スカウト" in result
    assert "TestOpp" in result
    assert "Jin" in result
    assert "60%" in result


def test_scout_section_no_repeat_opponent():
    """リピートなし → None。"""
    battles = [_scout_battle("pid1"), _scout_battle("pid2")]
    scout_data = {"pid1": {"total": 20, "win_rate": 50.0, "main_chara": "Jin",
                            "recent_wins": 5, "recent_total": 10, "recent_win_rate": 50.0}}
    assert _scout_section(battles, scout_data) is None


def test_scout_section_empty_scout_data():
    """scout_data にないPIDは表示されない。"""
    battles = [_scout_battle("pid1"), _scout_battle("pid1")]
    assert _scout_section(battles, {}) is None


def test_scout_section_trend_up():
    """直近勝率が全体より5%以上高い場合 ↑ を表示。"""
    battles = [_scout_battle("pid1"), _scout_battle("pid1")]
    scout_data = {
        "pid1": {"total": 20, "win_rate": 40.0, "main_chara": "Jin",
                 "recent_wins": 8, "recent_total": 10, "recent_win_rate": 80.0}
    }
    result = _scout_section(battles, scout_data)
    assert result is not None
    assert "↑" in result


def test_scout_section_trend_down():
    """直近勝率が全体より5%以上低い場合 ↓ を表示。"""
    battles = [_scout_battle("pid1"), _scout_battle("pid1")]
    scout_data = {
        "pid1": {"total": 20, "win_rate": 80.0, "main_chara": "Jin",
                 "recent_wins": 2, "recent_total": 10, "recent_win_rate": 20.0}
    }
    result = _scout_section(battles, scout_data)
    assert result is not None
    assert "↓" in result


# ---------------------------------------------------------------------------
# build_embed
# ---------------------------------------------------------------------------

def test_build_embed_returns_dict():
    battles = [_battle(True, battle_at=1000)]
    embed = build_embed(battles, "2024/01/01")
    assert embed is not None
    assert isinstance(embed, dict)


def test_build_embed_none_on_empty():
    assert build_embed([], "2024/01/01") is None


def test_build_embed_contains_date():
    battles = [_battle(True, battle_at=1000)]
    embed = build_embed(battles, "2024/01/01")
    embed_str = str(embed)
    assert "2024/01/01" in embed_str


def test_build_embed_contains_player_name():
    battles = [_battle(True, battle_at=1000)]
    embed = build_embed(battles, "2024/01/01", player_name="TestPlayer")
    embed_str = str(embed)
    assert "TestPlayer" in embed_str


def test_build_embed_has_color():
    battles = [_battle(True, battle_at=1000)]
    embed = build_embed(battles, "2024/01/01")
    assert "color" in embed


def test_build_embed_win_color_vs_loss_color():
    """勝ち越しと負け越しで color が異なる。"""
    win_battles  = [_battle(True)]  * 3 + [_battle(False)]
    lose_battles = [_battle(False)] * 3 + [_battle(True)]
    embed_win  = build_embed(win_battles,  "2024/01/01")
    embed_lose = build_embed(lose_battles, "2024/01/01")
    assert embed_win["color"] != embed_lose["color"]


# ---------------------------------------------------------------------------
# build_weekly_embed
# ---------------------------------------------------------------------------

def test_build_weekly_embed_returns_dict():
    battles = [_battle(True)]
    embed = build_weekly_embed(battles, "2024/01/15")
    assert embed is not None
    assert isinstance(embed, dict)


def test_build_weekly_embed_none_on_empty():
    assert build_weekly_embed([], "2024/01/15") is None


def test_build_weekly_embed_contains_week():
    battles = [_battle(True)]
    embed = build_weekly_embed(battles, "2024/01/15")
    assert "2024/01/15" in str(embed)


def test_build_weekly_embed_contains_player_name():
    battles = [_battle(True)]
    embed = build_weekly_embed(battles, "2024/01/15", player_name="Alice")
    assert "Alice" in str(embed)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# _opp_rank_label / _quick_rank_distribution
# ---------------------------------------------------------------------------

def _quick_battle(won: bool, opp_rank: int | None = None, opp_chara: str = "Jin") -> dict:
    """クイックマッチ用バトルデータを生成するヘルパー。"""
    b = _battle(won=won, opp_chara=opp_chara, battle_type="quick")
    b["opp_rank"] = opp_rank
    return b


def test_opp_rank_label_quick_with_rank():
    """クイックマッチで opp_rank あり → 段位名を括弧付きで返す。"""
    b = _quick_battle(won=False, opp_rank=25)  # 25 = God of Destruction
    label = _opp_rank_label(b)
    assert label.startswith("(")
    assert label.endswith(")")
    assert len(label) > 2  # 括弧の中身が空でない


def test_opp_rank_label_quick_no_rank():
    """クイックマッチで opp_rank なし → 空文字。"""
    b = _quick_battle(won=False, opp_rank=None)
    assert _opp_rank_label(b) == ""


def test_opp_rank_label_ranked_battle():
    """ランク戦では段位を持っていても空文字を返す。"""
    b = _battle(won=True, battle_type="ranked")
    b["opp_rank"] = 20
    assert _opp_rank_label(b) == ""


def test_opp_rank_label_unknown_rank_id():
    """存在しない rank_id → 空文字（RANK_NAMES に登録なし）。"""
    b = _quick_battle(won=True, opp_rank=9999)
    assert _opp_rank_label(b) == ""


def test_quick_rank_distribution_single():
    """単一段位 → `<名前>×N` 形式を返す。"""
    battles = [_quick_battle(won=True, opp_rank=20)] * 3
    result = _quick_rank_distribution(battles)
    assert "×3" in result


def test_quick_rank_distribution_multiple():
    """複数段位 → 多い順にスラッシュ区切りで返す。"""
    battles = (
        [_quick_battle(won=True,  opp_rank=20)] * 4 +
        [_quick_battle(won=False, opp_rank=15)] * 2
    )
    result = _quick_rank_distribution(battles)
    assert "/" in result
    # 多い段位が先頭に来る
    first, second = result.split(" / ", 1)
    assert "×4" in first
    assert "×2" in second


def test_quick_rank_distribution_no_rank_data():
    """全バトルで opp_rank が None → 空文字を返す。"""
    battles = [_quick_battle(won=True, opp_rank=None)] * 3
    assert _quick_rank_distribution(battles) == ""


def test_quick_rank_distribution_empty():
    """空リスト → 空文字。"""
    assert _quick_rank_distribution([]) == ""


def test_build_embed_shows_rank_for_quick():
    """build_embed: クイックマッチの試合一覧に相手段位が表示される。"""
    b = _quick_battle(won=False, opp_rank=20, opp_chara="Bryan")
    b["my_chara"] = "Lee"
    b["my_rounds"] = 1
    b["opp_rounds"] = 2
    b["battle_at"] = 1000
    b["opp_polaris_id"] = "pid"
    b["opp_name"] = "Opp"
    b["my_power"] = None
    result = build_embed([b], "2026-04-10")
    assert result is not None
    assert "(" in result["description"]


def test_build_embed_quick_field_includes_rank_dist():
    """build_embed: クイック欄に相手段位分布が含まれる。"""
    battles = [_quick_battle(won=True, opp_rank=20), _quick_battle(won=False, opp_rank=20)]
    for i, b in enumerate(battles):
        b["my_chara"] = "Lee"
        b["my_rounds"] = 2
        b["opp_rounds"] = 1
        b["battle_at"] = 1000 + i
        b["opp_polaris_id"] = f"pid{i}"
        b["opp_name"] = "Opp"
        b["my_power"] = None
    result = build_embed(battles, "2026-04-10")
    assert result is not None
    quick_fields = [f for f in result["fields"] if "クイック" in f["name"]]
    assert quick_fields
    assert "相手段位" in quick_fields[0]["value"]


# ---------------------------------------------------------------------------
# _parse_webhook_id_token
# ---------------------------------------------------------------------------

def test_parse_webhook_id_token_valid():
    """正しい Discord Webhook URL から (id, token) を返す。"""
    url = "https://discord.com/api/webhooks/123456789/abcdefghijk"
    result = _parse_webhook_id_token(url)
    assert result == ("123456789", "abcdefghijk")


def test_parse_webhook_id_token_discordapp_valid():
    """discordapp.com の URL も解析できる。"""
    url = "https://discordapp.com/api/webhooks/999/mytoken"
    result = _parse_webhook_id_token(url)
    assert result == ("999", "mytoken")


def test_parse_webhook_id_token_invalid():
    """不正な URL → None を返す。"""
    assert _parse_webhook_id_token("https://example.com/not/a/webhook") is None


def test_parse_webhook_id_token_empty():
    """空文字 → None を返す。"""
    assert _parse_webhook_id_token("") is None


# ---------------------------------------------------------------------------
# _embed_color
# ---------------------------------------------------------------------------

def test_embed_color_empty_battles():
    """空リスト → Blurple (0x5865F2) を返す。"""
    assert _embed_color([]) == 0x5865F2


def test_embed_color_high_win_rate():
    """勝率60%以上 → 緑 (0x57F287)。"""
    battles = [_battle(True)] * 6 + [_battle(False)] * 4
    assert _embed_color(battles) == 0x57F287


def test_embed_color_low_win_rate():
    """勝率40%以下 → 赤 (0xED4245)。"""
    battles = [_battle(False)] * 6 + [_battle(True)] * 4
    assert _embed_color(battles) == 0xED4245


def test_embed_color_medium_win_rate():
    """勝率50% → 黄 (0xFEE75C)。"""
    battles = [_battle(True), _battle(False)]
    assert _embed_color(battles) == 0xFEE75C


# ---------------------------------------------------------------------------
# build_embed 追加ブランチ
# ---------------------------------------------------------------------------

def test_build_embed_ranked_with_rating():
    """ランク戦 + レーティング変動 → ランク欄にレーティング情報が含まれる。"""
    b = _battle(True, battle_type="ranked", rating_before=10000, rating_change=100, battle_at=1000)
    result = build_embed([b], "2024/01/01")
    assert result is not None
    ranked_fields = [f for f in result["fields"] if "ランク" in f["name"]]
    assert ranked_fields
    assert "10100" in ranked_fields[0]["value"]


def test_build_embed_shows_rank_name_in_power_field():
    """my_power + my_rank → 鉄拳力フィールド名に段位名が含まれる。"""
    b = _battle(True, battle_at=1000)
    b["my_power"] = 150000
    b["my_rank"]  = 20
    result = build_embed([b], "2024/01/01")
    assert result is not None
    assert "150,000" in str(result)


def test_build_embed_with_scout_data():
    """scout_data がある → Embed にスカウトフィールドが含まれる。"""
    def _b(won: bool, battle_at: int) -> dict:
        b = _battle(won=won, opp_chara="Reina", battle_at=battle_at)
        b["opp_polaris_id"] = "pid1"
        b["opp_name"] = "Scout"
        return b
    battles = [_b(True, 1000), _b(False, 2000)]
    scout_data = {
        "pid1": {"total": 30, "win_rate": 55.0, "main_chara": "Reina",
                 "recent_wins": 8, "recent_total": 10, "recent_win_rate": 80.0}
    }
    result = build_embed(battles, "2024/01/01", scout_data=scout_data)
    assert result is not None
    assert any("スカウト" in f["name"] for f in result["fields"])


def test_build_embed_with_chart():
    """has_chart=True → embed に image フィールドが含まれる。"""
    b = _battle(True, battle_at=1000)
    result = build_embed([b], "2024/01/01", has_chart=True)
    assert result is not None
    assert "image" in result
    assert result["image"]["url"] == "attachment://rating.png"


# ---------------------------------------------------------------------------
# build_weekly_embed 追加ブランチ
# ---------------------------------------------------------------------------

def test_build_weekly_embed_with_quick():
    """クイックマッチがある → クイック欄が含まれる。"""
    battles = [
        _battle(True,  battle_type="ranked"),
        _battle(False, battle_type="quick"),
    ]
    result = build_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert any("クイック" in f["name"] for f in result["fields"])


def test_build_weekly_embed_with_net_rating():
    """ランク戦レーティングデータあり → レーティング変動フィールドが含まれる。"""
    b = _battle(True, battle_type="ranked", rating_before=10000, rating_change=200, battle_at=1000)
    result = build_weekly_embed([b], "2024/01/15")
    assert result is not None
    assert any("レーティング変動" in f["name"] for f in result["fields"])


def test_build_weekly_embed_with_trend():
    """3戦以上のランク戦レーティングデータ → トレンドフィールドが含まれる。"""
    battles = [
        _battle(True,  battle_type="ranked", rating_before=10000, rating_change=100, battle_at=1000),
        _battle(True,  battle_type="ranked", rating_before=10100, rating_change=80,  battle_at=2000),
        _battle(False, battle_type="ranked", rating_before=10180, rating_change=-50, battle_at=3000),
    ]
    result = build_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert any("トレンド" in f["name"] for f in result["fields"])


# ---------------------------------------------------------------------------
# build_community_weekly_embed
# ---------------------------------------------------------------------------

def test_build_community_weekly_embed_returns_dict():
    """プレイヤーデータ → Embed dict を返す。"""
    players = [
        {"name": "Alice", "wins": 10, "losses": 5, "net_rating": 200},
        {"name": "Bob",   "wins": 8,  "losses": 7, "net_rating": -100},
    ]
    result = build_community_weekly_embed(players, "2024/01/15")
    assert isinstance(result, dict)
    assert "title" in result
    assert "description" in result


def test_build_community_weekly_embed_ranking_order():
    """net_rating 降順でランキングが並ぶ。"""
    players = [
        {"name": "C", "wins": 5, "losses": 5, "net_rating": 100},
        {"name": "A", "wins": 8, "losses": 2, "net_rating": 500},
        {"name": "B", "wins": 3, "losses": 7, "net_rating": 200},
    ]
    result = build_community_weekly_embed(players, "2024/01/15")
    desc = result["description"]
    assert desc.index("A") < desc.index("B") < desc.index("C")


def test_build_community_weekly_embed_medals():
    """上位3人にメダルが付く。"""
    players = [
        {"name": "A", "wins": 10, "losses": 0, "net_rating": 300},
        {"name": "B", "wins": 8,  "losses": 2, "net_rating": 200},
        {"name": "C", "wins": 6,  "losses": 4, "net_rating": 100},
    ]
    result = build_community_weekly_embed(players, "2024/01/15")
    desc = result["description"]
    assert "🥇" in desc
    assert "🥈" in desc
    assert "🥉" in desc


# ---------------------------------------------------------------------------
# post_community_weekly, notify, notify_error
# ---------------------------------------------------------------------------

def test_post_community_weekly_skips_when_one_player():
    """プレイヤーが1人以下 → 投稿しない。"""
    players = [{"name": "Solo", "wins": 5, "losses": 3, "net_rating": 100}]
    with patch("bot.discord_post._webhook_session") as mock_sess:
        post_community_weekly(players, "2024/01/15")
    mock_sess.post.assert_not_called()


def test_post_community_weekly_posts_when_two_players():
    """プレイヤーが2人以上 → Webhook に POST する。"""
    players = [
        {"name": "A", "wins": 5, "losses": 3, "net_rating": 100},
        {"name": "B", "wins": 3, "losses": 5, "net_rating": -50},
    ]
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/token"]),
    ):
        mock_sess.post.return_value = mock_resp
        post_community_weekly(players, "2024/01/15")
    mock_sess.post.assert_called_once()


def test_notify_posts_message():
    """notify → content を含む POST が行われる。"""
    mock_resp = MagicMock()
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/token"]),
    ):
        mock_sess.post.return_value = mock_resp
        notify("テスト通知")
    mock_sess.post.assert_called_once()
    call_kwargs = mock_sess.post.call_args[1]
    assert "テスト通知" in call_kwargs["json"]["content"]


def test_notify_error_prepends_warning():
    """notify_error → ⚠️ プレフィックス付きで投稿される（ERROR_WEBHOOK_URLS 未設定時は WEBHOOK_URLS へ）。"""
    mock_resp = MagicMock()
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.ERROR_WEBHOOK_URLS", []),
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/token"]),
    ):
        mock_sess.post.return_value = mock_resp
        notify_error("エラーメッセージ")
    call_kwargs = mock_sess.post.call_args[1]
    assert "⚠️" in call_kwargs["json"]["content"]
    assert "エラーメッセージ" in call_kwargs["json"]["content"]


def test_notify_error_uses_error_webhook_when_set():
    """notify_error → ERROR_WEBHOOK_URLS が設定されていればそちらへ投稿する。"""
    error_url  = "https://discord.com/api/webhooks/error/token"
    normal_url = "https://discord.com/api/webhooks/normal/token"
    mock_resp = MagicMock()
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.ERROR_WEBHOOK_URLS", [error_url]),
        patch("bot.discord_post.WEBHOOK_URLS", [normal_url]),
    ):
        mock_sess.post.return_value = mock_resp
        notify_error("エラーメッセージ")
    posted_url = mock_sess.post.call_args[0][0]
    assert posted_url == error_url


def test_notify_ignores_request_exception():
    """Webhook 投稿失敗しても例外を出さない。"""
    import requests
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/token"]),
    ):
        mock_sess.post.side_effect = requests.RequestException("network error")
        notify("test")  # should not raise


# ---------------------------------------------------------------------------
# post()
# ---------------------------------------------------------------------------

def _full_battle(battle_at: int = 1000, won: bool = True) -> dict:
    """post() テスト用の完全なバトルデータ。"""
    return {
        "battle_id": f"t{battle_at}",
        "battle_at": battle_at,
        "won": won,
        "battle_type": "ranked",
        "opp_chara": "Jin",
        "my_chara": "Lee",
        "my_rounds": 2,
        "opp_rounds": 1,
        "rating_before": 10000,
        "rating_change": 100,
        "my_power": None,
        "my_rank": None,
        "opp_polaris_id": "pid_opp",
        "opp_name": "Opp",
    }


def test_post_returns_none_when_no_battles():
    """試合なし → None を返す。"""
    with patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]):
        result = post([], "2024/01/01")
    assert result is None


def test_post_returns_none_when_no_webhook_urls():
    """WEBHOOK_URLS 未設定 → ValueError を送出する。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", []),
        pytest.raises(ValueError),
    ):
        post([_full_battle()], "2024/01/01")


def test_post_success_returns_message_ids():
    """投稿成功 → (message_ids, embed) タプルを返す。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "msg123"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", return_value=None),
    ):
        mock_sess.post.return_value = mock_resp
        result = post(battles, "2024/01/01")

    assert result is not None
    message_ids, embed = result
    assert len(message_ids) == 1
    assert message_ids[0][0] == "msg123"
    assert isinstance(embed, dict)


def test_post_returns_none_when_all_webhooks_fail():
    """全 Webhook が RequestException → None を返す。"""
    import requests
    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", return_value=None),
    ):
        mock_sess.post.side_effect = requests.RequestException("error")
        result = post(battles, "2024/01/01")
    assert result is None


def test_post_with_chart():
    """グラフあり → files 付きで POST する。"""
    import io
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "msg456"}

    fake_chart = io.BytesIO(b"\x89PNGdata")
    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", return_value=fake_chart),
    ):
        mock_sess.post.return_value = mock_resp
        result = post(battles, "2024/01/01")

    assert result is not None
    # files= で POST が呼ばれているはず
    call_kwargs = mock_sess.post.call_args[1]
    assert "files" in call_kwargs


# ---------------------------------------------------------------------------
# post_weekly()
# ---------------------------------------------------------------------------

def test_post_weekly_returns_none_when_no_battles():
    """試合なし → None を返す。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.graph.generate_chara_usage_chart", return_value=None),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        result = post_weekly([], "2024/01/15")
    assert result is None


def test_post_weekly_success():
    """投稿成功 → (message_ids, embed) を返す。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "weekly123"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", return_value=None),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.return_value = mock_resp
        result = post_weekly(battles, "2024/01/15")

    assert result is not None
    message_ids, embed = result
    assert message_ids[0][0] == "weekly123"


def test_post_weekly_raises_when_no_webhook():
    """WEBHOOK_URLS 未設定 → ValueError を送出する。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", []),
        pytest.raises(ValueError),
    ):
        post_weekly([_full_battle()], "2024/01/15")


def test_post_weekly_with_chart():
    """キャラグラフあり → files 付きで POST する。"""
    import io
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "w789"}

    fake_chart = io.BytesIO(b"\x89PNGdata")
    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", return_value=fake_chart),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.return_value = mock_resp
        result = post_weekly(battles, "2024/01/15")

    assert result is not None
    call_kwargs = mock_sess.post.call_args[1]
    assert "files" in call_kwargs


# ---------------------------------------------------------------------------
# edit_llm_comment()
# ---------------------------------------------------------------------------

def test_edit_llm_comment_patches_embed():
    """正常ケース → PATCH リクエストが発行され、LLM コメントが description 冒頭に追加される。"""
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.json.return_value = {"attachments": []}

    patch_resp = MagicMock()
    patch_resp.raise_for_status.return_value = None

    message_ids = [("msg123", "https://discord.com/api/webhooks/1/tok")]
    embed = {"title": "test", "color": 0, "description": "試合一覧"}

    with patch("bot.discord_post._webhook_session") as mock_sess:
        mock_sess.get.return_value  = get_resp
        mock_sess.patch.return_value = patch_resp
        edit_llm_comment(message_ids, embed, "LLM コメントです")

    mock_sess.patch.assert_called_once()
    patch_call = mock_sess.patch.call_args[1]
    updated_embed = patch_call["json"]["embeds"][0]
    assert "LLM コメントです" in updated_embed["description"]
    assert updated_embed["description"].startswith("💬")


def test_edit_llm_comment_preserves_attachments():
    """添付ファイルがある場合 → PATCH ボディに attachments を含める。"""
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.json.return_value = {"attachments": [{"id": "att1"}]}

    patch_resp = MagicMock()
    patch_resp.raise_for_status.return_value = None

    message_ids = [("msg123", "https://discord.com/api/webhooks/1/tok")]
    embed = {"title": "test", "color": 0}

    with patch("bot.discord_post._webhook_session") as mock_sess:
        mock_sess.get.return_value  = get_resp
        mock_sess.patch.return_value = patch_resp
        edit_llm_comment(message_ids, embed, "コメント")

    patch_call = mock_sess.patch.call_args[1]
    assert "attachments" in patch_call["json"]


def test_edit_llm_comment_skips_invalid_url():
    """Webhook URL が不正 → PATCH を発行しない。"""
    message_ids = [("msg123", "https://invalid.example.com/not/webhook")]
    embed = {"title": "test", "color": 0}
    with patch("bot.discord_post._webhook_session") as mock_sess:
        edit_llm_comment(message_ids, embed, "コメント")
    mock_sess.patch.assert_not_called()


def test_edit_llm_comment_skips_patch_on_get_error():
    """GET が3回すべて失敗した場合は PATCH をスキップする（attachment 不明のまま PATCH すると description が反映されない）。"""
    import requests
    get_resp = MagicMock()
    get_resp.raise_for_status.side_effect = requests.RequestException("timeout")

    message_ids = [("msg123", "https://discord.com/api/webhooks/1/tok")]
    embed = {"title": "test", "color": 0}

    with patch("bot.discord_post._webhook_session") as mock_sess, \
         patch("time.sleep"):
        mock_sess.get.return_value = get_resp
        edit_llm_comment(message_ids, embed, "コメント")

    mock_sess.patch.assert_not_called()


def test_edit_llm_comment_ignores_patch_error():
    """PATCH が失敗しても例外を出さない。"""
    import requests
    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.json.return_value = {"attachments": []}

    message_ids = [("msg123", "https://discord.com/api/webhooks/1/tok")]
    embed = {"title": "test", "color": 0}

    with patch("bot.discord_post._webhook_session") as mock_sess:
        mock_sess.get.return_value = get_resp
        mock_sess.patch.return_value = MagicMock(
            raise_for_status=MagicMock(side_effect=requests.RequestException("patch error"))
        )
        edit_llm_comment(message_ids, embed, "コメント")  # should not raise


# ---------------------------------------------------------------------------
# post() - date_str なし・グラフ例外
# ---------------------------------------------------------------------------

def test_post_uses_today_when_date_str_none():
    """date_str=None → 現在日付が使われて ValueError なし。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "msg_today"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", return_value=None),
    ):
        mock_sess.post.return_value = mock_resp
        result = post(battles)  # date_str 省略

    assert result is not None


def test_post_continues_when_chart_raises():
    """グラフ生成が例外 → chart=None で続行する。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "msg_exc"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_rating_chart", side_effect=RuntimeError("graph error")),
    ):
        mock_sess.post.return_value = mock_resp
        result = post(battles, "2024/01/01")

    assert result is not None  # グラフなしで続行


# ---------------------------------------------------------------------------
# post_community_weekly - エラーハンドリング
# ---------------------------------------------------------------------------

def test_post_community_weekly_handles_request_error():
    """Webhook 投稿失敗しても例外を出さない。"""
    import requests
    players = [
        {"name": "A", "wins": 5, "losses": 3, "net_rating": 100},
        {"name": "B", "wins": 3, "losses": 5, "net_rating": -50},
    ]
    with (
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
    ):
        mock_sess.post.side_effect = requests.RequestException("error")
        post_community_weekly(players, "2024/01/15")  # should not raise


# ---------------------------------------------------------------------------
# post_weekly() - RequestException ハンドリング
# ---------------------------------------------------------------------------

def test_post_weekly_returns_none_when_all_fail():
    """全 Webhook が RequestException → None を返す。"""
    import requests
    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", return_value=None),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.side_effect = requests.RequestException("network")
        result = post_weekly(battles, "2024/01/15")
    assert result is None


def test_post_weekly_continues_when_chara_chart_raises():
    """キャラグラフ生成が例外 → chart=None で続行する。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "weekly_exc"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
        patch("bot.graph.generate_chara_usage_chart", side_effect=RuntimeError("chart error")),
        patch("bot.db.get_weekly_my_chara_counts", return_value=[]),
    ):
        mock_sess.post.return_value = mock_resp
        result = post_weekly(battles, "2024/01/15")

    assert result is not None


# ---------------------------------------------------------------------------
# 週次サマリーの相手段位表示
# ---------------------------------------------------------------------------

def test_build_weekly_embed_quick_includes_rank_distribution():
    """クイックマッチに opp_rank があれば Embed の クイック フィールドに相手段位を表示する。"""
    battles = [
        _quick_battle(won=True,  opp_rank=20),   # Kishin
        _quick_battle(won=False, opp_rank=20),   # Kishin
        _quick_battle(won=True,  opp_rank=22),   # Fujin
    ]
    result = build_weekly_embed(battles, "2024/01/15")
    assert result is not None
    quick_field = next((f for f in result["fields"] if "クイック" in f["name"]), None)
    assert quick_field is not None
    assert "相手段位" in quick_field["value"]


def test_build_weekly_embed_quick_no_rank_omits_distribution():
    """opp_rank がない場合は相手段位を表示しない。"""
    battles = [
        _quick_battle(won=True,  opp_rank=None),
        _quick_battle(won=False, opp_rank=None),
    ]
    result = build_weekly_embed(battles, "2024/01/15")
    assert result is not None
    quick_field = next((f for f in result["fields"] if "クイック" in f["name"]), None)
    assert quick_field is not None
    assert "相手段位" not in quick_field["value"]


# ---------------------------------------------------------------------------
# build_rank_change_embed
# ---------------------------------------------------------------------------

def test_build_rank_change_embed_promotion():
    """昇格 → ゴールド色・昇格タイトル・矢印が含まれる。"""
    result = build_rank_change_embed("Alice", old_rank=15, new_rank=16)
    assert result["color"] == 0xFFD700
    assert "昇格" in result["title"]
    assert "→" in result["description"]
    assert "臥龍" in result["description"]
    assert "真龍" in result["description"]


def test_build_rank_change_embed_demotion():
    """降格 → 赤色・降格タイトルが含まれる。"""
    result = build_rank_change_embed("Bob", old_rank=16, new_rank=15)
    assert result["color"] == 0xED4245
    assert "降格" in result["title"]
    assert "真龍" in result["description"]
    assert "臥龍" in result["description"]


def test_build_rank_change_embed_unknown_rank():
    """RANK_NAMES に存在しない rank_id → Rank<N> 形式にフォールバック。"""
    result = build_rank_change_embed("Test", old_rank=999, new_rank=1000)
    assert "Rank999" in result["description"]
    assert "Rank1000" in result["description"]


# ---------------------------------------------------------------------------
# post_rank_change
# ---------------------------------------------------------------------------

def test_post_rank_change_no_webhook_urls():
    """WEBHOOK_URLS 未設定 → 何も送信しない（例外も出さない）。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", []),
        patch("bot.discord_post._send_to_webhooks") as mock_send,
    ):
        post_rank_change("Alice", 15, 16)
    mock_send.assert_not_called()


def test_post_rank_change_sends_embed():
    """WEBHOOK_URLS 設定済み → _send_to_webhooks が呼ばれる。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._send_to_webhooks") as mock_send,
    ):
        post_rank_change("Alice", 15, 16)
    mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# build_monthly_embed
# ---------------------------------------------------------------------------

def test_build_monthly_embed_returns_dict():
    """バトルあり → Embed dict を返す。"""
    battles = [_battle(True)]
    result = build_monthly_embed(battles, "2024年1月")
    assert result is not None
    assert isinstance(result, dict)
    assert "2024年1月" in result["title"]


def test_build_monthly_embed_none_on_empty():
    """バトルなし → None。"""
    assert build_monthly_embed([], "2024年1月") is None


def test_build_monthly_embed_with_prev_battles():
    """前月データあり → 前月比フィールドが含まれる。"""
    battles      = [_battle(True)] * 5 + [_battle(False)] * 3
    prev_battles = [_battle(True)] * 3 + [_battle(False)] * 5
    result = build_monthly_embed(battles, "2024年2月", prev_battles=prev_battles)
    assert result is not None
    assert any("前月比" in f["name"] for f in result["fields"])


def test_build_monthly_embed_no_prev_battles():
    """前月データなし → 前月比フィールドなし。"""
    battles = [_battle(True)]
    result  = build_monthly_embed(battles, "2024年1月", prev_battles=None)
    assert result is not None
    assert not any("前月比" in f["name"] for f in result["fields"])


def test_build_monthly_embed_with_ranked_and_quick():
    """ランク戦・クイックマッチ混在 → 両方のフィールドが含まれる。"""
    battles = [
        _battle(True,  battle_type="ranked"),
        _battle(False, battle_type="quick"),
    ]
    result = build_monthly_embed(battles, "2024年3月")
    assert result is not None
    assert any("ランク" in f["name"] for f in result["fields"])
    assert any("クイック" in f["name"] for f in result["fields"])


def test_build_monthly_embed_contains_player_name():
    """player_name → タイトルに含まれる。"""
    battles = [_battle(True)]
    result  = build_monthly_embed(battles, "2024年4月", player_name="Alice")
    assert result is not None
    assert "Alice" in result["title"]


# ---------------------------------------------------------------------------
# _quick_rank_chara_matrix
# ---------------------------------------------------------------------------

def test_quick_rank_chara_matrix_basic():
    """クイック + opp_rank あり → 段位名とキャラ名が含まれる。"""
    battles = [
        _quick_battle(won=True,  opp_rank=22, opp_chara="Paul"),
        _quick_battle(won=False, opp_rank=22, opp_chara="Paul"),
        _quick_battle(won=True,  opp_rank=22, opp_chara="King"),
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "雷神" in result  # rank 22
    assert "Paul" in result
    assert "King" in result


def test_quick_rank_chara_matrix_rank_order_descending():
    """段位降順（強い相手が上）で表示される。"""
    battles = [
        _quick_battle(won=True,  opp_rank=15, opp_chara="Jin"),   # 臥龍（弱め）
        _quick_battle(won=False, opp_rank=25, opp_chara="Law"),   # 鉄拳王（強め）
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert result.index("鉄拳王") < result.index("臥龍")


def test_quick_rank_chara_matrix_winrate_order_ascending():
    """同じ段位内で勝率昇順（苦手キャラが上）に並ぶ。"""
    battles = [
        _quick_battle(won=True,  opp_rank=20, opp_chara="Paul"),
        _quick_battle(won=True,  opp_rank=20, opp_chara="Paul"),   # Paul 100%
        _quick_battle(won=False, opp_rank=20, opp_chara="King"),
        _quick_battle(won=False, opp_rank=20, opp_chara="King"),   # King 0%
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert result.index("King") < result.index("Paul")


def test_quick_rank_chara_matrix_icons():
    """勝率に応じた ✅/❌/➖ が付く。"""
    battles = [
        _quick_battle(won=True,  opp_rank=20, opp_chara="Paul"),
        _quick_battle(won=True,  opp_rank=20, opp_chara="Paul"),   # 100% ✅
        _quick_battle(won=False, opp_rank=20, opp_chara="King"),
        _quick_battle(won=False, opp_rank=20, opp_chara="King"),   # 0%   ❌
        _quick_battle(won=True,  opp_rank=20, opp_chara="Kazuya"),
        _quick_battle(won=False, opp_rank=20, opp_chara="Kazuya"), # 50%  ➖
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "✅" in result
    assert "❌" in result
    assert "➖" in result


def test_quick_rank_chara_matrix_excludes_ranked():
    """ランク戦は除外され、クイックマッチのみ集計される。"""
    battles = [
        _battle(won=False, opp_chara="Paul", battle_type="ranked"),  # ranked → 除外
        _quick_battle(won=True, opp_rank=20, opp_chara="King"),
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "Paul" not in result
    assert "King" in result


def test_quick_rank_chara_matrix_excludes_no_rank():
    """opp_rank が None のクイック対戦は除外される。"""
    battles = [
        _quick_battle(won=False, opp_rank=None, opp_chara="Paul"),  # rank不明 → 除外
        _quick_battle(won=True,  opp_rank=20,   opp_chara="King"),
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "Paul" not in result
    assert "King" in result


def test_quick_rank_chara_matrix_all_no_rank_returns_none():
    """全バトルで opp_rank が None → None を返す。"""
    battles = [_quick_battle(won=True, opp_rank=None)] * 3
    assert _quick_rank_chara_matrix(battles) is None


def test_quick_rank_chara_matrix_empty_returns_none():
    """空リスト → None を返す。"""
    assert _quick_rank_chara_matrix([]) is None


def test_quick_rank_chara_matrix_rank_name_japanese():
    """段位名が日本語で表示される。"""
    battles = [_quick_battle(won=True, opp_rank=25, opp_chara="Jin")]  # 25 = 鉄拳王
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "鉄拳王" in result


def test_build_embed_includes_quick_rank_chara_field():
    """クイック + opp_rank あり → Embed に段位別対戦成績フィールドが含まれる。"""
    battles = [
        _quick_battle(won=True,  opp_rank=22, opp_chara="Paul"),
        _quick_battle(won=False, opp_rank=22, opp_chara="King"),
    ]
    for i, b in enumerate(battles):
        b["my_chara"]  = "Lee"
        b["my_rounds"] = 2
        b["opp_rounds"] = 1
        b["battle_at"] = 1000 + i
        b["opp_polaris_id"] = f"pid{i}"
        b["opp_name"] = "Opp"
        b["my_power"] = None
    result = build_embed(battles, "2026-05-12")
    assert result is not None
    assert any("段位別" in f["name"] for f in result["fields"])


def test_build_embed_no_quick_rank_chara_field_when_no_rank():
    """クイックで全 opp_rank が None → 段位別対戦成績フィールドなし。"""
    battles = [_quick_battle(won=True, opp_rank=None, opp_chara="Paul")]
    battles[0].update({"my_chara": "Lee", "my_rounds": 2, "opp_rounds": 1,
                        "battle_at": 1000, "opp_polaris_id": "p", "opp_name": "Opp", "my_power": None})
    result = build_embed(battles, "2026-05-12")
    assert result is not None
    assert not any("段位別" in f["name"] for f in result["fields"])


# ---------------------------------------------------------------------------
# post_monthly
# ---------------------------------------------------------------------------

def test_post_monthly_returns_none_when_no_battles():
    """試合なし → None を返す。"""
    with patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]):
        result = post_monthly([], "2024年1月")
    assert result is None


def test_post_monthly_raises_when_no_webhook():
    """WEBHOOK_URLS 未設定 → ValueError を送出する。"""
    with (
        patch("bot.discord_post.WEBHOOK_URLS", []),
        pytest.raises(ValueError),
    ):
        post_monthly([_full_battle()], "2024年1月")


def test_post_monthly_success():
    """投稿成功 → (message_ids, embed) タプルを返す。"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"id": "monthly123"}

    battles = [_full_battle()]
    with (
        patch("bot.discord_post.WEBHOOK_URLS", ["https://discord.com/api/webhooks/1/tok"]),
        patch("bot.discord_post._webhook_session") as mock_sess,
    ):
        mock_sess.post.return_value = mock_resp
        result = post_monthly(battles, "2024年1月")

    assert result is not None
    message_ids, embed = result
    assert message_ids[0][0] == "monthly123"
    assert isinstance(embed, dict)
