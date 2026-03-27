"""
bot/analyzer.py の純粋関数テスト。
"""

import pytest
from bot.analyzer import _build_prompt, _compute_coaching_insights


def _battle(won: bool, opp_chara: str = "Jin", battle_type: str = "ranked",
            battle_at: int = 0) -> dict:
    return {
        "won": won,
        "opp_chara": opp_chara,
        "battle_type": battle_type,
        "my_rounds": 2,
        "opp_rounds": 1,
        "battle_at": battle_at,
    }


def test_build_prompt_contains_date():
    battles = [_battle(True)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "2024/01/15" in prompt


def test_build_prompt_contains_player_name():
    battles = [_battle(True)]
    prompt = _build_prompt(battles, "2024/01/15", player_name="TestPlayer")
    assert "TestPlayer" in prompt


def test_build_prompt_default_player_name():
    """player_name 未指定時でも例外を出さず、有効な文字列を返す。"""
    battles = [_battle(True)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert isinstance(prompt, str)
    assert len(prompt) > 0
    assert "ExodusOverseer" not in prompt


def test_build_prompt_contains_win_loss():
    battles = [_battle(True), _battle(True), _battle(False)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "2勝1敗" in prompt


def test_build_prompt_contains_opp_chara():
    battles = [_battle(True, "Dragunov"), _battle(False, "Dragunov")]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "Dragunov" in prompt


def test_build_prompt_ranked_quick_split():
    battles = [
        _battle(True, battle_type="ranked"),
        _battle(False, battle_type="quick"),
    ]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "ランク戦" in prompt
    assert "クイック" in prompt


def test_build_prompt_empty_battles():
    """空のバトルリストでも例外を出さない。"""
    prompt = _build_prompt([], "2024/01/15")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_prompt_round_win_rate():
    battles = [_battle(True)]  # my_rounds=2, opp_rounds=1
    prompt = _build_prompt(battles, "2024/01/15")
    assert "ラウンド勝率" in prompt


def test_build_prompt_150_chars_instruction():
    battles = [_battle(True)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "150文字以内" in prompt


def test_build_prompt_shows_streak():
    """3連勝の場合、最長連勝がプロンプトに含まれる。"""
    battles = [_battle(True, battle_at=i) for i in range(3)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "最長連勝: 3" in prompt


def test_build_prompt_omits_streak_when_less_than_2():
    """1連勝は表示されない。"""
    battles = [_battle(True, battle_at=1), _battle(False, battle_at=2)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "最長連勝" not in prompt
    assert "最長連敗" not in prompt


def test_build_prompt_with_rating_change():
    """ランク戦にレーティング変動がある場合、プロンプトに含まれる。"""
    battle = _battle(True, battle_type="ranked")
    battle["rating_change"] = 50
    prompt = _build_prompt([battle], "2024/01/15")
    assert "レーティング変動" in prompt
    assert "+50" in prompt


# ---------------------------------------------------------------------------
# _compute_coaching_insights
# ---------------------------------------------------------------------------

def _battle_with_ts(won: bool, opp_chara: str = "Jin", battle_at: int = 0) -> dict:
    return {
        "won": won,
        "opp_chara": opp_chara,
        "battle_type": "ranked",
        "my_rounds": 2,
        "opp_rounds": 1,
        "battle_at": battle_at,
    }


def test_coaching_insights_weak_chara():
    """2戦以上で勝率 40% 未満のキャラが weak に入る。"""
    battles = [
        _battle_with_ts(False, "Dragunov", 0),
        _battle_with_ts(False, "Dragunov", 1),
        _battle_with_ts(False, "Dragunov", 2),
    ]
    insights = _compute_coaching_insights(battles, None)
    weak_charas = [c for c, _, _ in insights["weak"]]
    assert "Dragunov" in weak_charas


def test_coaching_insights_strong_chara():
    """2戦以上で勝率 70% 以上のキャラが strong に入る。"""
    battles = [
        _battle_with_ts(True, "Jin", 0),
        _battle_with_ts(True, "Jin", 1),
        _battle_with_ts(True, "Jin", 2),
    ]
    insights = _compute_coaching_insights(battles, None)
    strong_charas = [c for c, _, _ in insights["strong"]]
    assert "Jin" in strong_charas


def test_coaching_insights_no_weak_when_few_battles():
    """1戦のみのキャラは weak/strong に入らない。"""
    battles = [_battle_with_ts(False, "Dragunov", 0)]
    insights = _compute_coaching_insights(battles, None)
    assert insights["weak"] == []
    assert insights["strong"] == []


def test_coaching_insights_trend_positive():
    """前日比勝率が10pt以上上昇した場合、trend に ↑ が含まれる。"""
    today    = [_battle_with_ts(True, "Jin", i) for i in range(8)] + \
               [_battle_with_ts(False, "Jin", 100 + i) for i in range(2)]  # 80%
    prev     = [_battle_with_ts(False, "Jin", i) for i in range(6)] + \
               [_battle_with_ts(True, "Jin", 100 + i) for i in range(4)]   # 40%
    insights = _compute_coaching_insights(today, prev)
    assert insights["trend"] is not None
    assert "↑" in insights["trend"]


def test_coaching_insights_trend_negative():
    """前日比勝率が10pt以上低下した場合、trend に ↓ が含まれる。"""
    today    = [_battle_with_ts(False, "Jin", i) for i in range(6)] + \
               [_battle_with_ts(True, "Jin", 100 + i) for i in range(4)]   # 40%
    prev     = [_battle_with_ts(True, "Jin", i) for i in range(8)] + \
               [_battle_with_ts(False, "Jin", 100 + i) for i in range(2)]  # 80%
    insights = _compute_coaching_insights(today, prev)
    assert insights["trend"] is not None
    assert "↓" in insights["trend"]


def test_coaching_insights_trend_none_when_small_diff():
    """前日比の差が小さい場合は trend が None。"""
    today = [_battle_with_ts(True, "Jin", i) for i in range(5)] + \
            [_battle_with_ts(False, "Jin", 100 + i) for i in range(5)]  # 50%
    prev  = [_battle_with_ts(True, "Jin", i) for i in range(5)] + \
            [_battle_with_ts(False, "Jin", 100 + i) for i in range(5)]  # 50%
    insights = _compute_coaching_insights(today, prev)
    assert insights["trend"] is None


def test_coaching_insights_no_trend_without_prev():
    """prev_battles が None の場合、trend は None。"""
    battles = [_battle_with_ts(True, "Jin", i) for i in range(5)]
    insights = _compute_coaching_insights(battles, None)
    assert insights["trend"] is None


def test_build_prompt_includes_weak_chara():
    """苦手キャラがあればプロンプトに '苦手キャラ' が含まれる。"""
    battles = [_battle(False, "Dragunov", battle_at=i) for i in range(3)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "苦手キャラ" in prompt
    assert "Dragunov" in prompt


def test_build_prompt_includes_strong_chara():
    """得意キャラがあればプロンプトに '得意キャラ' が含まれる。"""
    battles = [_battle(True, "Jin", battle_at=i) for i in range(3)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "得意キャラ" in prompt
    assert "Jin" in prompt


def test_build_prompt_includes_rematch_data():
    """rematch_data があれば通算成績がプロンプトに含まれる。"""
    battles = [_battle(True)]
    rematch = {
        "pid1": {
            "name": "RivalPlayer",
            "chara": "Paul",
            "history": [{"won": True}, {"won": False}, {"won": True}],
        }
    }
    prompt = _build_prompt(battles, "2024/01/15", rematch_data=rematch)
    assert "繰り返し対戦" in prompt
    assert "RivalPlayer" in prompt
