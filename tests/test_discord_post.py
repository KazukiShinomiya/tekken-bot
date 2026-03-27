"""
bot/discord_post.py の純粋関数テスト。
"""

import pytest
from bot.discord_post import (
    _win_rate,
    _streak,
    _nemesis,
    _rating_summary,
    _matchup_matrix,
    _scout_section,
    build_message,
    build_weekly_message,
    build_community_weekly,
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
# build_message
# ---------------------------------------------------------------------------

def test_build_message_includes_player_name():
    battles = [_battle(True, battle_at=1000)]
    msg = build_message(battles, "2024/01/01", player_name="TestPlayer")
    assert "TestPlayer" in msg


def test_build_message_none_on_empty():
    assert build_message([], "2024/01/01") is None


def test_build_message_shows_streak():
    """3連勝の場合、連勝行が表示される。"""
    battles = [_battle(True, battle_at=i * 100) for i in range(3)]
    msg = build_message(battles, "2024/01/01")
    assert "連勝" in msg


def test_build_message_no_streak_when_short():
    """1連勝は表示されない。"""
    battles = [_battle(True, battle_at=1000), _battle(False, battle_at=2000)]
    msg = build_message(battles, "2024/01/01")
    assert "🔥" not in msg


def test_build_message_shows_nemesis():
    """2連敗キャラがいる場合、天敵行が表示される。"""
    battles = [
        _battle(False, "Dragunov", battle_at=1000),
        _battle(False, "Dragunov", battle_at=2000),
    ]
    msg = build_message(battles, "2024/01/01")
    assert "天敵" in msg
    assert "Dragunov" in msg


def test_build_message_shows_tekken_power():
    """鉄拳力がある場合、表示される。"""
    b = _battle(True, battle_at=1000)
    b["my_power"] = 123456
    msg = build_message([b], "2024/01/01")
    assert "鉄拳力" in msg
    assert "123,456" in msg


# ---------------------------------------------------------------------------
# build_weekly_message
# ---------------------------------------------------------------------------

def test_build_weekly_message_none_on_empty():
    assert build_weekly_message([], "2024/01/15") is None


def test_build_weekly_message_includes_player_name():
    battles = [_battle(True)]
    msg = build_weekly_message(battles, "2024/01/15", player_name="TestPlayer")
    assert "TestPlayer" in msg


def test_build_weekly_message_includes_win_loss():
    battles = [_battle(True), _battle(True), _battle(False)]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "2勝1敗" in msg


def test_build_weekly_message_includes_top_chara():
    """最多使用キャラが表示される。"""
    battles = [
        _battle(True,  my_chara="Reina"),
        _battle(False, my_chara="Reina"),
        _battle(True,  my_chara="Jin"),
    ]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "Reina" in msg  # 2戦で最多


def test_build_weekly_message_with_rating():
    """ランク戦のレーティング変動が表示される。"""
    battles = [
        _battle(True,  rating_change=50,  battle_type="ranked"),
        _battle(False, rating_change=-30, battle_type="ranked"),
    ]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "レーティング変動" in msg
    assert "+20" in msg


def test_build_weekly_message_includes_matchup_matrix():
    """2戦以上の対戦キャラがある場合、マトリクスが含まれる。"""
    battles = [
        _battle(True,  "Dragunov"), _battle(True,  "Dragunov"),
        _battle(False, "Jin"),      _battle(False, "Jin"),
    ]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "Dragunov" in msg
    assert "Jin" in msg


def test_build_weekly_message_shows_matchup_matrix_with_one_battle():
    """1戦のキャラもマトリクスに表示される（閾値1戦から表示）。"""
    battles = [_battle(True, "Jin"), _battle(False, "Dragunov")]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "📊 対戦成績" in msg
    assert "Jin" in msg
    assert "Dragunov" in msg


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
# build_community_weekly
# ---------------------------------------------------------------------------

def test_build_community_weekly_ranking_order():
    """net_rating 降順でランキングが並ぶ。"""
    players = [
        {"name": "Alice", "wins": 10, "losses": 5, "net_rating": 200},
        {"name": "Bob",   "wins": 8,  "losses": 7, "net_rating": 500},
        {"name": "Carol", "wins": 6,  "losses": 9, "net_rating": -100},
    ]
    msg = build_community_weekly(players, "2024/01/15")
    lines = [l for l in msg.split("\n") if any(p["name"] in l for p in players)]
    # Bob (500) > Alice (200) > Carol (-100)
    assert lines[0].index("Bob") < len(lines[0])
    bob_line   = next(i for i, l in enumerate(lines) if "Bob" in l)
    alice_line = next(i for i, l in enumerate(lines) if "Alice" in l)
    carol_line = next(i for i, l in enumerate(lines) if "Carol" in l)
    assert bob_line < alice_line < carol_line


def test_build_community_weekly_medals():
    """上位3人にメダル絵文字が付く。"""
    players = [
        {"name": "A", "wins": 10, "losses": 0, "net_rating": 300},
        {"name": "B", "wins": 8,  "losses": 2, "net_rating": 200},
        {"name": "C", "wins": 6,  "losses": 4, "net_rating": 100},
    ]
    msg = build_community_weekly(players, "2024/01/15")
    assert "🥇" in msg
    assert "🥈" in msg
    assert "🥉" in msg


def test_build_community_weekly_shows_net_rating():
    """net_rating が + 付きで表示される。"""
    players = [{"name": "A", "wins": 5, "losses": 5, "net_rating": 150}]
    msg = build_community_weekly(players, "2024/01/15")
    assert "+150" in msg


def test_build_community_weekly_negative_net_rating():
    """マイナスの net_rating は - 付きで表示される。"""
    players = [{"name": "A", "wins": 3, "losses": 7, "net_rating": -200}]
    msg = build_community_weekly(players, "2024/01/15")
    assert "-200" in msg


def test_build_community_weekly_contains_week():
    """週の開始日が含まれる。"""
    players = [{"name": "A", "wins": 5, "losses": 5, "net_rating": 0}]
    msg = build_community_weekly(players, "2024/01/15")
    assert "2024/01/15" in msg


# ---------------------------------------------------------------------------
# build_message with scout_data
# ---------------------------------------------------------------------------

def test_build_message_with_scout_data():
    """scout_data がある場合、スカウトセクションが表示される。"""
    b = _battle(True, battle_at=1000)
    b["opp_polaris_id"] = "pid1"
    b["opp_name"] = "ScoutOpp"
    b2 = _battle(False, battle_at=2000)
    b2["opp_polaris_id"] = "pid1"
    b2["opp_name"] = "ScoutOpp"
    scout_data = {
        "pid1": {"total": 20, "win_rate": 55.0, "main_chara": "Reina",
                 "recent_wins": 5, "recent_total": 10, "recent_win_rate": 50.0}
    }
    msg = build_message([b, b2], "2024/01/01", scout_data=scout_data)
    assert msg is not None
    assert "スカウト" in msg
    assert "ScoutOpp" in msg


def test_build_message_without_scout_data_no_scout_section():
    """scout_data なしの場合、スカウトセクションが表示されない。"""
    battles = [_battle(True, battle_at=1000)]
    msg = build_message(battles, "2024/01/01")
    assert msg is not None
    assert "スカウト" not in msg
