"""
bot/stats.py の単体テスト。
"""

from bot.stats import calculate_streak, aggregate_by_character


# ---------------------------------------------------------------------------
# calculate_streak
# ---------------------------------------------------------------------------

def test_calculate_streak_basic():
    battles = [{"won": True}, {"won": True}, {"won": False}]
    assert calculate_streak(battles) == (2, 1)


def test_calculate_streak_empty():
    assert calculate_streak([]) == (0, 0)


def test_calculate_streak_all_wins():
    battles = [{"won": True}] * 4
    assert calculate_streak(battles) == (4, 0)


def test_calculate_streak_all_losses():
    battles = [{"won": False}] * 3
    assert calculate_streak(battles) == (0, 3)


def test_calculate_streak_alternating():
    battles = [{"won": True}, {"won": False}, {"won": True}, {"won": False}]
    assert calculate_streak(battles) == (1, 1)


def test_calculate_streak_resets_correctly():
    # 2連勝 → 3連敗 → 1勝 の順
    battles = [
        {"won": True}, {"won": True},
        {"won": False}, {"won": False}, {"won": False},
        {"won": True},
    ]
    max_win, max_lose = calculate_streak(battles)
    assert max_win == 2
    assert max_lose == 3


# ---------------------------------------------------------------------------
# aggregate_by_character
# ---------------------------------------------------------------------------

def test_aggregate_by_character_basic():
    battles = [
        {"won": True,  "opp_chara": "Jin"},
        {"won": False, "opp_chara": "Jin"},
        {"won": True,  "opp_chara": "Reina"},
    ]
    result = aggregate_by_character(battles)
    assert result["Jin"]   == [True, False]
    assert result["Reina"] == [True]


def test_aggregate_by_character_empty():
    assert aggregate_by_character([]) == {}


def test_aggregate_by_character_none_chara_becomes_unknown():
    battles = [{"won": True, "opp_chara": None}]
    result = aggregate_by_character(battles)
    assert "???" in result
    assert result["???"] == [True]


def test_aggregate_by_character_missing_key_becomes_unknown():
    battles = [{"won": False}]
    result = aggregate_by_character(battles)
    assert "???" in result


def test_aggregate_by_character_multiple_same_chara():
    battles = [{"won": True, "opp_chara": "Dragunov"}] * 3
    result = aggregate_by_character(battles)
    assert result["Dragunov"] == [True, True, True]
