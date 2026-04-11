"""
bot/stats.py の単体テスト。
"""

from bot.stats import (
    calculate_streak, aggregate_by_character,
    predict_rating_trend, detect_momentum,
    detect_winning_streak, detect_losing_streak,
)


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


# ---------------------------------------------------------------------------
# predict_rating_trend
# ---------------------------------------------------------------------------

def _ranked_rated(battle_at: int, rating_change: int) -> dict:
    return {
        "won": rating_change > 0,
        "battle_type": "ranked",
        "battle_at": battle_at,
        "rating_change": rating_change,
    }


def test_predict_rating_trend_upward():
    """連続プラス変動 → slope_per_day が正。"""
    battles = [_ranked_rated(i * 3600, 50) for i in range(5)]
    result = predict_rating_trend(battles)
    assert "slope_per_day" in result
    assert result["slope_per_day"] > 0


def test_predict_rating_trend_downward():
    """連続マイナス変動 → slope_per_day が負。"""
    battles = [_ranked_rated(i * 3600, -30) for i in range(5)]
    result = predict_rating_trend(battles)
    assert "slope_per_day" in result
    assert result["slope_per_day"] < 0


def test_predict_rating_trend_too_few_battles():
    """2戦以下は空 dict を返す。"""
    battles = [_ranked_rated(i * 3600, 50) for i in range(2)]
    assert predict_rating_trend(battles) == {}


def test_predict_rating_trend_no_rated_battles():
    """rating_change なしのバトルは空 dict。"""
    battles = [{"won": True, "battle_type": "ranked", "battle_at": i * 3600, "rating_change": None}
               for i in range(5)]
    assert predict_rating_trend(battles) == {}


def test_predict_rating_trend_quick_battles_excluded():
    """クイックマッチは trend 計算に含まれない。"""
    quick = [{"won": True, "battle_type": "quick", "battle_at": i * 3600, "rating_change": 50}
             for i in range(5)]
    assert predict_rating_trend(quick) == {}


def test_predict_rating_trend_stagnation_days():
    """連続±100以内の日が3日あれば stagnation_days >= 3。"""
    # 各バトルは別々の日に0変動
    battles = [_ranked_rated(i * 86400, 10) for i in range(5)]
    result = predict_rating_trend(battles)
    assert result.get("stagnation_days", 0) >= 3


# ---------------------------------------------------------------------------
# detect_momentum
# ---------------------------------------------------------------------------

def _b(won: bool, battle_at: int = 0) -> dict:
    return {"won": won, "battle_at": battle_at}


def test_detect_momentum_upswing():
    """前半負け越し → 後半勝ち越しで ↑ を返す。"""
    battles = [_b(False), _b(False), _b(True), _b(True), _b(True), _b(True)]
    result = detect_momentum(battles)
    assert result is not None
    assert "上" in result  # 後半に調子が上向いた


def test_detect_momentum_downswing():
    """前半勝ち越し → 後半負け越しで ↓ を返す。"""
    battles = [_b(True), _b(True), _b(True), _b(False), _b(False), _b(False)]
    result = detect_momentum(battles)
    assert result is not None
    assert "落ち" in result  # 後半に調子が落ちた


def test_detect_momentum_stable():
    """前後半の差が小さい場合は None。"""
    battles = [_b(True), _b(False), _b(True), _b(False)]
    assert detect_momentum(battles) is None


def test_detect_momentum_too_few():
    """3戦以下は None。"""
    assert detect_momentum([_b(True), _b(False), _b(True)]) is None


def test_detect_momentum_empty():
    assert detect_momentum([]) is None


# ---------------------------------------------------------------------------
# detect_winning_streak / detect_losing_streak
# ---------------------------------------------------------------------------

def test_detect_winning_streak_basic():
    battles = [{"won": False}, {"won": True}, {"won": True}, {"won": True}]
    assert detect_winning_streak(battles) == 3


def test_detect_winning_streak_broken():
    battles = [{"won": True}, {"won": True}, {"won": False}, {"won": True}]
    assert detect_winning_streak(battles) == 1


def test_detect_winning_streak_none():
    battles = [{"won": True}, {"won": False}]
    assert detect_winning_streak(battles) == 0


def test_detect_winning_streak_empty():
    assert detect_winning_streak([]) == 0


def test_detect_losing_streak_basic():
    battles = [{"won": True}, {"won": False}, {"won": False}]
    assert detect_losing_streak(battles) == 2


def test_detect_losing_streak_empty():
    assert detect_losing_streak([]) == 0


# ---------------------------------------------------------------------------
# get_most_common (bot/stats.py line 66)
# ---------------------------------------------------------------------------

from bot.stats import get_most_common, aggregate_by_hour
from bot.config import UNKNOWN_CHARACTER


def test_get_most_common_empty_returns_unknown():
    """バトルなし → UNKNOWN_CHARACTER と 0 を返す。"""
    result = get_most_common([], "my_chara")
    assert result == (UNKNOWN_CHARACTER, 0)


def test_get_most_common_basic():
    """最多キャラを正しく返す。"""
    battles = [
        {"my_chara": "Lee"},
        {"my_chara": "Lee"},
        {"my_chara": "Jin"},
    ]
    name, cnt = get_most_common(battles, "my_chara")
    assert name == "Lee"
    assert cnt == 2


# ---------------------------------------------------------------------------
# aggregate_by_hour (bot/stats.py line 99)
# ---------------------------------------------------------------------------

def test_aggregate_by_hour_skips_none_battle_at():
    """battle_at が None のバトルはスキップされる。"""
    battles = [
        {"battle_at": None, "won": True},
        {"battle_at": 1000, "won": True},
    ]
    result = aggregate_by_hour(battles)
    # None のバトルはスキップ → キーが1つだけ
    assert len(result) == 1


# ---------------------------------------------------------------------------
# predict_rating_trend exception branches (lines 135-140)
# ---------------------------------------------------------------------------

from unittest.mock import patch


def test_predict_rating_trend_returns_empty_on_import_error():
    """numpy が見つからない場合は空 dict を返す。"""
    import sys
    battles = [
        {"battle_at": 1000, "won": True,  "battle_type": "ranked", "rating_before": 10000, "rating_change": 100},
        {"battle_at": 2000, "won": True,  "battle_type": "ranked", "rating_before": 10100, "rating_change": 80},
        {"battle_at": 3000, "won": False, "battle_type": "ranked", "rating_before": 10180, "rating_change": -50},
    ]
    # numpy を一時的に見つからなくする
    with patch.dict(sys.modules, {"numpy": None}):
        result = predict_rating_trend(battles)
    assert result == {}


def test_predict_rating_trend_returns_empty_on_exception():
    """計算中に例外が発生した場合は空 dict を返す��"""
    battles = [
        {"battle_at": 1000, "won": True,  "battle_type": "ranked", "rating_before": 10000, "rating_change": 100},
        {"battle_at": 2000, "won": True,  "battle_type": "ranked", "rating_before": 10100, "rating_change": 80},
        {"battle_at": 3000, "won": False, "battle_type": "ranked", "rating_before": 10180, "rating_change": -50},
    ]
    with patch("numpy.polyfit", side_effect=ValueError("bad fit")):
        result = predict_rating_trend(battles)
    assert result == {}
