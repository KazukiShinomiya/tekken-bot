"""
bot/graph.py のテスト。
matplotlib を使って PNG 生成を検証する。matplotlib 未インストール時はスキップ。
ImportError パスのテストのみ sys.modules パッチで matplotlib を隠す。
"""

import io
import sys
import pytest
from unittest.mock import patch

pytest.importorskip("matplotlib")

from bot.graph import (
    generate_chara_usage_chart,
    generate_rating_chart,
    generate_winrate_chart,
    _rolling_winrate,
)


def _battle(
    battle_at: int = 1_000_000,
    won: bool = True,
    rating_before: int | None = 10_000,
    rating_change: int | None = 100,
) -> dict:
    return {
        "battle_id":     "t1",
        "battle_at":     battle_at,
        "won":           won,
        "battle_type":   "ranked",
        "rating_before": rating_before,
        "rating_change": rating_change,
    }


def _week_row(week: str, chara: str, cnt: int) -> dict:
    return {"week": week, "my_chara": chara, "cnt": cnt}


# ---------------------------------------------------------------------------
# _rolling_winrate（純関数・勝率計算）
# ---------------------------------------------------------------------------

def test_rolling_winrate_none_when_below_window():
    """試合数が window 未満なら None。"""
    assert _rolling_winrate([_battle(won=True)], window=7) is None


def test_rolling_winrate_all_wins():
    """全勝なら全窓 1.0。"""
    battles = [_battle(battle_at=i, won=True) for i in range(7)]
    rolled = _rolling_winrate(battles, window=7)
    assert rolled is not None
    _dates, wr = rolled
    assert wr == [1.0]


def test_rolling_winrate_all_losses():
    """全敗なら全窓 0.0。"""
    battles = [_battle(battle_at=i, won=False) for i in range(7)]
    rolled = _rolling_winrate(battles, window=7)
    assert rolled is not None
    _dates, wr = rolled
    assert wr == [0.0]


def test_rolling_winrate_counts_wins_not_constant():
    """回帰: won を正しく数え、全敗扱い（常に0%）にならない。

    かつて b.get("result")=="win"（result カラムは存在しない）を読んでいたため
    勝率系列が常に 0.0 になっていた。won を見ていることをこのテストで固定する。
    """
    # 4勝3敗（window=7）→ 勝率 4/7
    wins = [True, True, False, True, False, True, False]
    battles = [_battle(battle_at=i, won=w) for i, w in enumerate(wins)]
    rolled = _rolling_winrate(battles, window=7)
    assert rolled is not None
    _dates, wr = rolled
    assert wr == [4 / 7]
    assert wr != [0.0]  # バグ時はここで 0.0 になっていた


def test_rolling_winrate_sliding_window():
    """窓がスライドし、窓ごとに異なる勝率を返す。"""
    # 8試合: 最初の窓[0:7]=6勝, 次の窓[1:8]=5勝（先頭の勝ちが抜け末尾の負けが入る）
    wins = [True, True, True, True, True, True, False, False]
    battles = [_battle(battle_at=i, won=w) for i, w in enumerate(wins)]
    rolled = _rolling_winrate(battles, window=7)
    assert rolled is not None
    dates, wr = rolled
    assert wr == [6 / 7, 5 / 7]
    assert len(dates) == 2


def test_generate_winrate_chart_returns_png():
    """7試合以上 → PNG（BytesIO）を返す。"""
    battles = [_battle(battle_at=i, won=(i % 2 == 0)) for i in range(8)]
    result = generate_winrate_chart(battles, player_name="TestPlayer")
    assert isinstance(result, io.BytesIO)
    assert result.read(8).startswith(b"\x89PNG")


def test_generate_winrate_chart_none_below_window():
    """window 未満 → None。"""
    assert generate_winrate_chart([_battle()], window=7) is None


# ---------------------------------------------------------------------------
# generate_rating_chart
# ---------------------------------------------------------------------------

def test_rating_chart_returns_bytesio():
    """レーティングデータが揃っているバトルがあれば BytesIO を返す。"""
    battles = [
        _battle(battle_at=1_000_000, rating_before=10_000, rating_change=100),
        _battle(battle_at=1_000_100, rating_before=10_100, rating_change=-50),
        _battle(battle_at=1_000_200, rating_before=10_050, rating_change=80),
    ]
    result = generate_rating_chart(battles, player_name="TestPlayer")
    assert isinstance(result, io.BytesIO)


def test_rating_chart_is_png():
    """返される BytesIO の内容が PNG フォーマットである。"""
    battles = [_battle(battle_at=1_000_000 + i * 100) for i in range(3)]
    result = generate_rating_chart(battles)
    assert result is not None
    header = result.read(4)
    assert header == b"\x89PNG"


def test_rating_chart_seek_at_zero():
    """返される BytesIO はシーク位置が先頭にある。"""
    battles = [_battle(battle_at=1_000_000 + i * 100) for i in range(3)]
    result = generate_rating_chart(battles)
    assert result is not None
    assert result.tell() == 0


def test_rating_chart_none_when_no_rated():
    """rating_change / rating_before がないバトルのみ → None を返す。"""
    battles = [
        _battle(rating_before=None, rating_change=None),
        _battle(rating_before=None, rating_change=None),
    ]
    assert generate_rating_chart(battles) is None


def test_rating_chart_none_when_rating_before_missing():
    """rating_change はあるが rating_before が None → None を返す。"""
    battles = [_battle(rating_before=None, rating_change=100)]
    assert generate_rating_chart(battles) is None


def test_rating_chart_none_when_empty():
    """空リスト → None を返す。"""
    assert generate_rating_chart([]) is None


def test_rating_chart_single_battle():
    """レーティングデータが1件だけでも BytesIO を返す。"""
    battles = [_battle(rating_before=10_000, rating_change=100)]
    result = generate_rating_chart(battles)
    assert isinstance(result, io.BytesIO)


# ---------------------------------------------------------------------------
# generate_chara_usage_chart
# ---------------------------------------------------------------------------

def test_chara_chart_returns_bytesio():
    """2週以上のデータ → BytesIO を返す。"""
    data = [
        _week_row("2026-W13", "Lee",   5),
        _week_row("2026-W13", "Reina", 2),
        _week_row("2026-W14", "Lee",   4),
        _week_row("2026-W14", "Bryan", 1),
    ]
    result = generate_chara_usage_chart(data, player_name="TestPlayer")
    assert isinstance(result, io.BytesIO)


def test_chara_chart_is_png():
    """返される BytesIO の内容が PNG フォーマットである。"""
    data = [
        _week_row("2026-W13", "Lee", 5),
        _week_row("2026-W14", "Lee", 4),
    ]
    result = generate_chara_usage_chart(data)
    assert result is not None
    assert result.read(4) == b"\x89PNG"


def test_chara_chart_seek_at_zero():
    """返される BytesIO はシーク位置が先頭にある。"""
    data = [
        _week_row("2026-W13", "Lee", 5),
        _week_row("2026-W14", "Lee", 4),
    ]
    result = generate_chara_usage_chart(data)
    assert result is not None
    assert result.tell() == 0


def test_chara_chart_none_when_empty():
    """空リスト → None を返す。"""
    assert generate_chara_usage_chart([]) is None


def test_chara_chart_none_when_single_week():
    """1週分のみ → None を返す（推移グラフ不成立）。"""
    data = [_week_row("2026-W13", "Lee", 5)]
    assert generate_chara_usage_chart(data) is None


def test_chara_chart_handles_many_charas():
    """8キャラを超えるデータも上位8キャラのみで正常にグラフ生成できる。"""
    charas = [f"Chara{i}" for i in range(12)]
    data = []
    for w in ["2026-W13", "2026-W14"]:
        for i, c in enumerate(charas):
            data.append(_week_row(w, c, i + 1))
    result = generate_chara_usage_chart(data)
    assert isinstance(result, io.BytesIO)


# ---------------------------------------------------------------------------
# matplotlib ImportError パス（sys.modules パッチで再現）
# ---------------------------------------------------------------------------

_MOCKED_ABSENT = {k: None for k in [
    "matplotlib", "matplotlib.pyplot", "matplotlib.dates",
    "matplotlib.rcParams", "numpy",
]}


def test_rating_chart_returns_none_when_matplotlib_missing():
    """matplotlib 未インストール環境では None を返す。"""
    with patch.dict(sys.modules, _MOCKED_ABSENT):
        result = generate_rating_chart([_battle()], player_name="Test")
    assert result is None


def test_chara_chart_returns_none_when_matplotlib_missing():
    """matplotlib 未インストール環境では None を返す。"""
    data = [_week_row("2026-W13", "Lee", 5), _week_row("2026-W14", "Lee", 4)]
    with patch.dict(sys.modules, _MOCKED_ABSENT):
        result = generate_chara_usage_chart(data, player_name="Test")
    assert result is None


# ---------------------------------------------------------------------------
# _week_label の ValueError パス
# ---------------------------------------------------------------------------

def test_chara_chart_handles_invalid_week_format():
    """無効な週文字列（strptime が ValueError）でも例外なくグラフを生成する。"""
    data = [
        _week_row("bad-week",  "Lee", 5),
        _week_row("bad-week2", "Lee", 4),
    ]
    result = generate_chara_usage_chart(data)
    assert isinstance(result, io.BytesIO)
