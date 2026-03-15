"""
bot/analyzer.py の純粋関数テスト。
"""

import pytest
from bot.analyzer import _build_prompt


def _battle(won: bool, opp_chara: str = "Jin", battle_type: str = "ranked") -> dict:
    return {
        "won": won,
        "opp_chara": opp_chara,
        "battle_type": battle_type,
        "my_rounds": 2,
        "opp_rounds": 1,
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
    battles = [_battle(True)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "ExodusOverseer" in prompt


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


def test_build_prompt_100_chars_instruction():
    battles = [_battle(True)]
    prompt = _build_prompt(battles, "2024/01/15")
    assert "100文字以内" in prompt
