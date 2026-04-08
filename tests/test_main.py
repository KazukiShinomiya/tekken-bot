"""
main.py の純粋関数・ヘルパー関数のテスト。
非同期処理・Discord 投稿はモックで代替する。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from main import _analyze_with_timeout, _compute_opponent_data, _fire_alerts


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _battle(
    battle_id: str = "t1",
    battle_at: int = 1_000_000,
    won: bool = True,
    opp_polaris_id: str = "pid_a",
    rating_before: int | None = None,
    rating_change: int | None = None,
) -> dict:
    return {
        "battle_id":        battle_id,
        "battle_at":        battle_at,
        "won":              won,
        "opp_polaris_id":   opp_polaris_id,
        "opp_name":         "TestOpp",
        "opp_chara":        "Jin",
        "battle_type":      "ranked",
        "rating_before":    rating_before,
        "rating_change":    rating_change,
    }


# ---------------------------------------------------------------------------
# _compute_opponent_data
# ---------------------------------------------------------------------------

def test_compute_opponent_data_empty():
    """バトルなし → 空 dict と空リストを返す。"""
    with patch("bot.db.get_battles_vs_opponent", return_value=[]):
        rematch_data, pids_to_scout = _compute_opponent_data([], "Alice")
    assert rematch_data == {}
    assert pids_to_scout == []


def test_compute_opponent_data_no_rematch_for_single_battle():
    """同一相手との対戦が1回のみ → rematch_data に含まれない。"""
    battles = [_battle(opp_polaris_id="pid_x")]
    with patch("bot.db.get_battles_vs_opponent", return_value=battles):
        rematch_data, pids_to_scout = _compute_opponent_data(battles, "Alice")
    assert "pid_x" not in rematch_data
    assert pids_to_scout == []


def test_compute_opponent_data_rematch_for_two_battles():
    """同一相手との対戦が2回 → rematch_data に含まれ、スカウト対象にも入る。"""
    battles = [
        _battle(battle_id="t1", opp_polaris_id="pid_y"),
        _battle(battle_id="t2", opp_polaris_id="pid_y"),
    ]
    history = [_battle(opp_polaris_id="pid_y")] * 2
    with patch("bot.db.get_battles_vs_opponent", return_value=history):
        rematch_data, pids_to_scout = _compute_opponent_data(battles, "Alice")
    assert "pid_y" in rematch_data
    assert "pid_y" in pids_to_scout


def test_compute_opponent_data_pids_to_scout_capped_at_3():
    """スカウト対象は最大3人（most_common(3) で絞る）。"""
    battles = []
    for i in range(5):
        pid = f"pid_{i}"
        for j in range(2):
            battles.append(_battle(battle_id=f"t{i}{j}", opp_polaris_id=pid))

    with patch("bot.db.get_battles_vs_opponent", return_value=[_battle()]):
        _, pids_to_scout = _compute_opponent_data(battles, "Alice")
    assert len(pids_to_scout) <= 3


def test_compute_opponent_data_skips_none_polaris_id():
    """opp_polaris_id が None のバトルは Counter から除外される。"""
    b = _battle()
    b["opp_polaris_id"] = None
    with patch("bot.db.get_battles_vs_opponent", return_value=[]):
        rematch_data, pids_to_scout = _compute_opponent_data([b, b], "Alice")
    assert rematch_data == {}
    assert pids_to_scout == []


# ---------------------------------------------------------------------------
# _fire_alerts
# ---------------------------------------------------------------------------

def test_fire_alerts_sends_losing_streak_notification():
    """連敗数が閾値以上 → notify が呼ばれる。"""
    battles = [_battle(won=False)] * 5
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 3),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 0),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(battles, battles, [], "Alice")
    mock_notify.assert_called_once()
    assert "連敗" in mock_notify.call_args[0][0]


def test_fire_alerts_no_losing_streak_below_threshold():
    """連敗数が閾値未満 → notify は呼ばれない。"""
    battles = [_battle(won=False)] * 2
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 5),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 0),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(battles, battles, [], "Alice")
    mock_notify.assert_not_called()


def test_fire_alerts_sends_winning_streak_notification():
    """連勝数が閾値以上 → notify が呼ばれる。"""
    battles = [_battle(won=True)] * 5
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 0),
        patch("main.WIN_ALERT_THRESHOLD", 3),
        patch("main.RATING_GOAL", 0),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(battles, battles, [], "Alice")
    mock_notify.assert_called_once()
    assert "連勝" in mock_notify.call_args[0][0]


def test_fire_alerts_sends_rating_goal_notification():
    """今日目標レーティング達成（前日は未達成）→ notify が呼ばれる。"""
    today_battles = [
        _battle(battle_at=1_000_100, rating_before=9_900, rating_change=200),
    ]
    prev_battles = [
        _battle(battle_at=999_999, rating_before=9_500, rating_change=100),
    ]
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 0),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 10_000),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, today_battles, prev_battles, "Alice")
    mock_notify.assert_called_once()
    assert "達成" in mock_notify.call_args[0][0]


def test_fire_alerts_no_duplicate_rating_goal_notification():
    """前日すでに目標達成済み → 再通知しない。"""
    today_battles = [_battle(battle_at=1_000_100, rating_before=9_900, rating_change=200)]
    prev_battles  = [_battle(battle_at=999_999,   rating_before=9_800, rating_change=300)]
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 0),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 10_000),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, today_battles, prev_battles, "Alice")
    mock_notify.assert_not_called()


def test_fire_alerts_disabled_when_all_thresholds_zero():
    """全閾値 0 → notify は一切呼ばれない。"""
    battles = [_battle(won=False)] * 10
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 0),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 0),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(battles, battles, [], "Alice")
    mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# _analyze_with_timeout
# ---------------------------------------------------------------------------

def test_analyze_with_timeout_returns_result():
    """LLM が時間内に応答 → コメント文字列を返す。"""
    battles = [_battle()]
    with patch("bot.analyzer.analyze", return_value="コメントです"):
        result = _analyze_with_timeout(battles, "2026/04/08", "Alice")
    assert result == "コメントです"


def test_analyze_with_timeout_returns_none_on_timeout():
    """LLM がタイムアウト → None を返す（ボットは止まらない）。"""
    import time
    from concurrent.futures import ThreadPoolExecutor

    def slow_analyze(*args, **kwargs):
        time.sleep(10)
        return "遅い"

    battles = [_battle()]
    with (
        patch("bot.analyzer.analyze", side_effect=slow_analyze),
        patch("main.TIMEOUT_LLM", 0.1),
        patch("bot.discord_post.notify_error"),
    ):
        result = _analyze_with_timeout(battles, "2026/04/08", "Alice")
    assert result is None


def test_analyze_with_timeout_returns_none_on_exception():
    """LLM が例外を送出 → None を返す。"""
    battles = [_battle()]
    with patch("bot.analyzer.analyze", side_effect=RuntimeError("LLM error")):
        result = _analyze_with_timeout(battles, "2026/04/08", "Alice")
    assert result is None
