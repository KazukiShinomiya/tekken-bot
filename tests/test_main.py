"""
main.py の純粋関数・ヘルパー関数のテスト。
非同期処理・Discord 投稿はモックで代替する。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from main import (
    _analyze_with_timeout, _compute_opponent_data, _fire_alerts,
    get_players, setup_logging, _fetch_scout_data,
)


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


# ---------------------------------------------------------------------------
# get_players
# ---------------------------------------------------------------------------

def test_get_players_from_players_env():
    """PLAYERS=Name:pid 形式をパースしてリストで返す。"""
    with patch("main.PLAYERS_ENV", "Alice:pid_alice,Bob:pid_bob"):
        players = get_players()
    assert players == [("Alice", "pid_alice"), ("Bob", "pid_bob")]


def test_get_players_with_spaces():
    """エントリ前後のスペースをトリムする。"""
    with patch("main.PLAYERS_ENV", " Alice : pid_alice , Bob : pid_bob "):
        players = get_players()
    assert players == [("Alice", "pid_alice"), ("Bob", "pid_bob")]


def test_get_players_single_fallback():
    """PLAYERS 未設定時は POLARIS_ID + TEKKEN_ID の単一エントリを返す。"""
    with (
        patch("main.PLAYERS_ENV", ""),
        patch("main.POLARIS_ID_ENV", "pid_x"),
        patch("main.TEKKEN_ID_ENV", "PlayerX"),
    ):
        players = get_players()
    assert players == [("PlayerX", "pid_x")]


def test_get_players_single_fallback_default_name():
    """TEKKEN_ID が空の場合は 'default' をプレイヤー名とする。"""
    with (
        patch("main.PLAYERS_ENV", ""),
        patch("main.POLARIS_ID_ENV", "pid_x"),
        patch("main.TEKKEN_ID_ENV", ""),
    ):
        players = get_players()
    assert players == [("default", "pid_x")]


def test_get_players_empty():
    """PLAYERS も POLARIS_ID も未設定 → 空リスト。"""
    with (
        patch("main.PLAYERS_ENV", ""),
        patch("main.POLARIS_ID_ENV", None),
    ):
        players = get_players()
    assert players == []


def test_get_players_skips_invalid_entries():
    """':' を含まないエントリはスキップされる。"""
    with patch("main.PLAYERS_ENV", "Alice:pid_alice,invalid_entry,Bob:pid_bob"):
        players = get_players()
    assert len(players) == 2
    assert ("Alice", "pid_alice") in players
    assert ("Bob", "pid_bob") in players


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

def test_setup_logging_creates_log_dir(tmp_path):
    """setup_logging() がログディレクトリを作成する。"""
    log_file = tmp_path / "logs" / "bot.log"
    with patch("main.LOG_PATH", str(log_file)):
        setup_logging()
    assert log_file.parent.exists()


def test_setup_logging_does_not_raise(tmp_path):
    """setup_logging() は例外を出さない。"""
    log_file = tmp_path / "bot.log"
    with patch("main.LOG_PATH", str(log_file)):
        setup_logging()  # should not raise


# ---------------------------------------------------------------------------
# _fetch_scout_data
# ---------------------------------------------------------------------------

def test_fetch_scout_data_empty_pids():
    """スカウト対象なし → 空 dict を返す。"""
    result = _fetch_scout_data([], "Alice")
    assert result == {}


def test_fetch_scout_data_returns_summary():
    """スカウト成功 → pid をキーにサマリーを返す。"""
    summary = {
        "total": 20, "win_rate": 60.0, "main_chara": "Jin",
        "recent_wins": 12, "recent_total": 20, "recent_win_rate": 60.0,
    }
    with patch("main.fetcher.fetch_opponent_summary", return_value=summary):
        result = _fetch_scout_data(["pid_a"], "Alice")
    assert "pid_a" in result
    assert result["pid_a"]["win_rate"] == 60.0


def test_fetch_scout_data_ignores_none_results():
    """スカウト結果が None → dict に含まれない。"""
    with patch("main.fetcher.fetch_opponent_summary", return_value=None):
        result = _fetch_scout_data(["pid_a"], "Alice")
    assert result == {}


def test_fetch_scout_data_handles_exception():
    """スカウト中に例外 → 例外を出さず空 dict を返す。"""
    with patch("main.fetcher.fetch_opponent_summary", side_effect=RuntimeError("network error")):
        result = _fetch_scout_data(["pid_a"], "Alice")
    assert result == {}


def test_fetch_scout_data_multiple_pids():
    """複数 pid を並列処理して全サマリーを返す。"""
    summary_a = {"total": 10, "win_rate": 50.0, "main_chara": "Jin",
                 "recent_wins": 5, "recent_total": 10, "recent_win_rate": 50.0}
    summary_b = {"total": 20, "win_rate": 70.0, "main_chara": "Lee",
                 "recent_wins": 14, "recent_total": 20, "recent_win_rate": 70.0}

    def side_effect(pid: str):
        return summary_a if pid == "pid_a" else summary_b

    with patch("main.fetcher.fetch_opponent_summary", side_effect=side_effect):
        result = _fetch_scout_data(["pid_a", "pid_b"], "Alice")
    assert "pid_a" in result
    assert "pid_b" in result


# ---------------------------------------------------------------------------
# _fire_alerts — 段位アップ通知
# ---------------------------------------------------------------------------

def _battle_with_rank(
    battle_at: int,
    won: bool = True,
    my_rank: int | None = None,
    rating_before: int | None = None,
    rating_change: int | None = None,
) -> dict:
    return {
        "battle_id":     f"t{battle_at}",
        "battle_at":     battle_at,
        "won":           won,
        "opp_polaris_id": "pid_opp",
        "opp_name":      "Opp",
        "opp_chara":     "Jin",
        "battle_type":   "ranked",
        "my_rank":       my_rank,
        "rating_before": rating_before,
        "rating_change": rating_change,
    }


def test_fire_alerts_sends_rank_up_notification():
    """今日の最終ランクが前日より高い → 段位アップ通知が飛ぶ。"""
    today_battles = [_battle_with_rank(1_000_100, my_rank=22)]   # Raijin
    prev_battles  = [_battle_with_rank(999_999,   my_rank=21)]   # Fujin
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 0),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 0),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, today_battles, prev_battles, "Alice")
    mock_notify.assert_called_once()
    assert "段位アップ" in mock_notify.call_args[0][0]
    assert "Raijin" in mock_notify.call_args[0][0]


def test_fire_alerts_no_rank_up_when_same():
    """前日と同じランク → 段位アップ通知しない。"""
    today_battles = [_battle_with_rank(1_000_100, my_rank=22)]
    prev_battles  = [_battle_with_rank(999_999,   my_rank=22)]
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 0),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 0),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, today_battles, prev_battles, "Alice")
    mock_notify.assert_not_called()


def test_fire_alerts_no_rank_up_without_prev():
    """前日データなし → 段位アップ通知しない。"""
    today_battles = [_battle_with_rank(1_000_100, my_rank=22)]
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 0),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 0),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, today_battles, [], "Alice")
    mock_notify.assert_not_called()


def test_fire_alerts_no_rank_up_when_rank_missing():
    """my_rank が None のバトルは段位アップ判定から除外される。"""
    today_battles = [_battle_with_rank(1_000_100, my_rank=None)]
    prev_battles  = [_battle_with_rank(999_999,   my_rank=21)]
    with (
        patch("main.LOSS_ALERT_THRESHOLD", 0),
        patch("main.WIN_ALERT_THRESHOLD", 0),
        patch("main.RATING_GOAL", 0),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, today_battles, prev_battles, "Alice")
    mock_notify.assert_not_called()
