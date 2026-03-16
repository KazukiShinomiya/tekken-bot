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
    build_message,
    build_weekly_message,
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
    battles = [_battle(True, "Jin")]  # 1戦のみ
    assert _matchup_matrix(battles) is None


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
    """テッケンパワーがある場合、表示される。"""
    b = _battle(True, battle_at=1000)
    b["my_power"] = 123456
    msg = build_message([b], "2024/01/01")
    assert "テッケンパワー" in msg
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


def test_build_weekly_message_no_matchup_matrix_when_insufficient():
    """1戦しかないキャラはマトリクスに出ない。"""
    battles = [_battle(True, "Jin"), _battle(False, "Dragunov")]
    msg = build_weekly_message(battles, "2024/01/15")
    # マトリクスセクションが存在しない（各キャラ1戦のみ）
    assert "📊 対戦成績" not in msg
