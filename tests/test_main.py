"""
main.py の純粋関数・ヘルパー関数のテスト。
非同期処理・Discord 投稿はモックで代替する。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from main import (
    _analyze_with_timeout, _compute_opponent_data, _fire_alerts, _fire_rank_alerts,
    _unknown_chara_label,
    get_players, setup_logging, _fetch_scout_data, _generate_validated_comment,
    _run_for_player, run_main_sync, run_weekly_sync, run_monthly_sync,
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

def test_fire_alerts_sends_rating_goal_notification():
    """今日目標レーティング達成（前日は未達成）→ notify が呼ばれる。"""
    today_battles = [
        _battle(battle_at=1_000_100, rating_before=9_900, rating_change=200),
    ]
    prev_battles = [
        _battle(battle_at=999_999, rating_before=9_500, rating_change=100),
    ]
    with (
        patch("main.RATING_GOAL", 10_000),
        patch("bot.db.get_goal", return_value=None),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, prev_battles, "Alice")
    mock_notify.assert_called_once()
    assert "達成" in mock_notify.call_args[0][0]


def test_fire_alerts_no_duplicate_rating_goal_notification():
    """前日すでに目標達成済み → 再通知しない。"""
    today_battles = [_battle(battle_at=1_000_100, rating_before=9_900, rating_change=200)]
    prev_battles  = [_battle(battle_at=999_999,   rating_before=9_800, rating_change=300)]
    with (
        patch("main.RATING_GOAL", 10_000),
        patch("bot.db.get_goal", return_value=None),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, prev_battles, "Alice")
    mock_notify.assert_not_called()


def test_fire_alerts_no_notification_when_goal_zero():
    """RATING_GOAL=0（無効）→ notify は呼ばれない。"""
    battles = [_battle(battle_at=1_000_100, rating_before=9_900, rating_change=200)]
    with (
        patch("main.RATING_GOAL", 0),
        patch("bot.db.get_goal", return_value=None),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(battles, [], "Alice")
    mock_notify.assert_not_called()


def test_fire_alerts_db_goal_takes_priority():
    """DB の目標が設定されていれば env var より優先される。"""
    today_battles = [_battle(battle_at=1_000_100, rating_before=19_800, rating_change=300)]
    prev_battles  = [_battle(battle_at=999_999,   rating_before=19_500, rating_change=100)]
    with (
        patch("main.RATING_GOAL", 0),        # env var は無効
        patch("bot.db.get_goal", return_value=20_000),  # DB 目標 = 20,000
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, prev_battles, "Alice")
    mock_notify.assert_called_once()
    assert "達成" in mock_notify.call_args[0][0]


def test_fire_alerts_db_goal_none_falls_back_to_env():
    """DB 目標が None → env var の RATING_GOAL を使う。"""
    today_battles = [_battle(battle_at=1_000_100, rating_before=9_900, rating_change=200)]
    prev_battles  = [_battle(battle_at=999_999,   rating_before=9_500, rating_change=100)]
    with (
        patch("main.RATING_GOAL", 10_000),
        patch("bot.db.get_goal", return_value=None),
        patch("bot.discord_post.notify") as mock_notify,
    ):
        _fire_alerts(today_battles, prev_battles, "Alice")
    mock_notify.assert_called_once()


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
# _run_for_player
# ---------------------------------------------------------------------------

def _make_battle(battle_id: str = "t1", battle_at: int = 1_000_000, won: bool = True) -> dict:
    return {
        "battle_id": battle_id, "battle_at": battle_at, "won": won,
        "battle_type": "ranked", "opp_chara": "Jin", "my_chara": "Lee",
        "my_rounds": 2, "opp_rounds": 1,
        "rating_before": 10000, "rating_change": 100,
        "my_power": None, "my_rank": None,
        "opp_polaris_id": "pid_opp", "opp_name": "Opp",
    }


def test_run_for_player_happy_path():
    """新規バトルあり → post が呼ばれて mark_posted_today が実行される。"""
    today_battles = [_make_battle()]
    mock_post_result = ([("msg1", "https://discord.com/api/webhooks/1/tok")], {"title": "t"})
    with (
        patch("bot.db.get_latest_battle_at", return_value=None),
        patch("main.fetcher.fetch_battles_since", return_value=today_battles),
        patch("bot.db.insert_battles", return_value=1),
        patch("main.fetcher.fetch_quick_battles_from_ewgf", return_value=[]),
        patch("bot.db.get_battles_on_date", return_value=today_battles),
        patch("bot.db.has_posted_today", return_value=False),
        patch("bot.db.mark_posted_today"),
        patch("main._compute_opponent_data", return_value=({}, [])),
        patch("main._fetch_scout_data", return_value={}),
        patch("main._fire_alerts"),
        patch("main._fire_rank_alerts"),
        patch("main.discord_post.post", return_value=mock_post_result) as mock_post,
        patch("bot.db.get_high_score_comments", return_value=[]),
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value=None),
        patch("main.discord_post.edit_llm_comment"),
        patch("main.discord_post.notify_error"),
    ):
        _run_for_player("Alice", "pid_alice", "2026-04-10", "2026/04/10")

    mock_post.assert_called_once()


def test_run_for_player_no_today_battles():
    """今日の試合なし → post が呼ばれない。"""
    with (
        patch("bot.db.get_latest_battle_at", return_value=None),
        patch("main.fetcher.fetch_battles_since", return_value=[]),
        patch("bot.db.insert_battles", return_value=0),
        patch("main.fetcher.fetch_quick_battles_from_ewgf", return_value=[]),
        patch("bot.db.get_battles_on_date", return_value=[]),
        patch("main.discord_post.post") as mock_post,
        patch("main.discord_post.notify_error"),
    ):
        _run_for_player("Alice", "pid_alice", "2026-04-10", "2026/04/10")

    mock_post.assert_not_called()


def test_run_for_player_skips_if_already_posted():
    """新規なし・投稿済み → post が呼ばれない。"""
    today_battles = [_make_battle()]
    with (
        patch("bot.db.get_latest_battle_at", return_value=None),
        patch("main.fetcher.fetch_battles_since", return_value=[]),
        patch("bot.db.insert_battles", return_value=0),
        patch("main.fetcher.fetch_quick_battles_from_ewgf", return_value=[]),
        patch("bot.db.get_battles_on_date", return_value=today_battles),
        patch("bot.db.has_posted_today", return_value=True),
        patch("main.discord_post.post") as mock_post,
        patch("main.discord_post.notify_error"),
    ):
        _run_for_player("Alice", "pid_alice", "2026-04-10", "2026/04/10")

    mock_post.assert_not_called()


def test_run_for_player_with_llm_comment():
    """LLM コメントあり → edit_llm_comment が呼ばれる。"""
    today_battles = [_make_battle()]
    mock_post_result = ([("msg1", "https://discord.com/api/webhooks/1/tok")], {"title": "t"})
    with (
        patch("bot.db.get_latest_battle_at", return_value=None),
        patch("main.fetcher.fetch_battles_since", return_value=today_battles),
        patch("bot.db.insert_battles", return_value=1),
        patch("main.fetcher.fetch_quick_battles_from_ewgf", return_value=[]),
        patch("bot.db.get_battles_on_date", return_value=today_battles),
        patch("bot.db.has_posted_today", return_value=False),
        patch("bot.db.mark_posted_today"),
        patch("main._compute_opponent_data", return_value=({}, [])),
        patch("main._fetch_scout_data", return_value={}),
        patch("main._fire_alerts"),
        patch("main._fire_rank_alerts"),
        patch("main.discord_post.post", return_value=mock_post_result),
        patch("bot.db.get_high_score_comments", return_value=[]),
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value="素晴らしい"),
        patch("main.discord_post.edit_llm_comment") as mock_edit,
        patch("main.discord_post.notify_error"),
    ):
        _run_for_player("Alice", "pid_alice", "2026-04-10", "2026/04/10")

    mock_edit.assert_called_once()


def test_run_for_player_llm_eval_score_saved():
    """LLM コメントあり → LLM評価スコアが DB に保存される。"""
    today_battles = [_make_battle()]
    mock_post_result = ([("msg1", "https://discord.com/api/webhooks/1/tok")], {"title": "t"})
    with (
        patch("bot.db.get_latest_battle_at", return_value=None),
        patch("main.fetcher.fetch_battles_since", return_value=today_battles),
        patch("bot.db.insert_battles", return_value=1),
        patch("main.fetcher.fetch_quick_battles_from_ewgf", return_value=[]),
        patch("bot.db.get_battles_on_date", return_value=today_battles),
        patch("bot.db.has_posted_today", return_value=False),
        patch("bot.db.mark_posted_today"),
        patch("main._compute_opponent_data", return_value=({}, [])),
        patch("main._fetch_scout_data", return_value={}),
        patch("main._fire_alerts"),
        patch("main._fire_rank_alerts"),
        patch("main.discord_post.post", return_value=mock_post_result),
        patch("bot.db.get_high_score_comments", return_value=[]),
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value="良いコメント"),
        patch("main.discord_post.edit_llm_comment"),
        patch("main.discord_post.notify_error"),
        patch(
            "bot.evaluator.evaluate_comment",
            return_value={"score": 80, "details": {"chara_valid": {"hallucinated": []}}},
        ) as mock_eval,
        patch("bot.db.save_llm_eval_score") as mock_save_score,
    ):
        _run_for_player("Alice", "pid_alice", "2026-04-10", "2026/04/10")

    mock_eval.assert_called_once()
    mock_save_score.assert_called_once_with("2026-04-10", "Alice", 80, "良いコメント")


def test_run_for_player_fetch_error_posts_error():
    """fetcher が例外を送出 → notify_error が呼ばれて処理を中断。"""
    with (
        patch("bot.db.get_latest_battle_at", return_value=None),
        patch("main.fetcher.fetch_battles_since", side_effect=RuntimeError("network error")),
        patch("main.discord_post.notify_error") as mock_notify_error,
        patch("main.discord_post.post") as mock_post,
    ):
        _run_for_player("Alice", "pid_alice", "2026-04-10", "2026/04/10")

    mock_notify_error.assert_called_once()
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# run_main_sync / run_weekly_sync
# ---------------------------------------------------------------------------

def test_run_main_sync_runs_without_error():
    """run_main_sync() が asyncio.run(main()) を呼ぶ（モック）。"""
    with patch("main.main", new=AsyncMock()):
        run_main_sync()  # should not raise


def test_run_weekly_sync_runs_without_error():
    """run_weekly_sync() が asyncio.run(weekly()) を呼ぶ（モック）。"""
    with patch("main.weekly", new=AsyncMock()):
        run_weekly_sync()  # should not raise


def test_run_for_player_with_quick_battles():
    """クイックマッチデータあり → クイック件数がログに記録される。"""
    today_battles = [_make_battle()]
    quick = [_make_battle(battle_id="q1")]
    mock_post_result = ([("msg1", "https://discord.com/api/webhooks/1/tok")], {"title": "t"})
    with (
        patch("bot.db.get_latest_battle_at", return_value=None),
        patch("main.fetcher.fetch_battles_since", return_value=today_battles),
        patch("bot.db.insert_battles", return_value=1),
        patch("main.fetcher.fetch_quick_battles_from_ewgf", return_value=quick),
        patch("bot.db.get_battles_on_date", return_value=today_battles),
        patch("bot.db.has_posted_today", return_value=False),
        patch("bot.db.mark_posted_today"),
        patch("main._compute_opponent_data", return_value=({}, [])),
        patch("main._fetch_scout_data", return_value={}),
        patch("main._fire_alerts"),
        patch("main._fire_rank_alerts"),
        patch("main.discord_post.post", return_value=mock_post_result),
        patch("bot.db.get_high_score_comments", return_value=[]),
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value=None),
        patch("main.discord_post.edit_llm_comment"),
        patch("main.discord_post.notify_error"),
    ):
        _run_for_player("Alice", "pid_alice", "2026-04-10", "2026/04/10")  # should not raise


def test_run_for_player_post_discord_exception():
    """Discord 投稿が例外 → エラーログが記録されるが処理は継続。"""
    today_battles = [_make_battle()]
    with (
        patch("bot.db.get_latest_battle_at", return_value=None),
        patch("main.fetcher.fetch_battles_since", return_value=today_battles),
        patch("bot.db.insert_battles", return_value=1),
        patch("main.fetcher.fetch_quick_battles_from_ewgf", return_value=[]),
        patch("bot.db.get_battles_on_date", return_value=today_battles),
        patch("bot.db.has_posted_today", return_value=False),
        patch("bot.db.mark_posted_today"),
        patch("main._compute_opponent_data", return_value=({}, [])),
        patch("main._fetch_scout_data", return_value={}),
        patch("main._fire_alerts"),
        patch("main._fire_rank_alerts"),
        patch("main.discord_post.post", side_effect=RuntimeError("webhook error")),
        patch("bot.db.get_high_score_comments", return_value=[]),
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value=None),
        patch("main.discord_post.edit_llm_comment"),
        patch("main.discord_post.notify_error"),
    ):
        _run_for_player("Alice", "pid_alice", "2026-04-10", "2026/04/10")  # should not raise


# ---------------------------------------------------------------------------
# _generate_validated_comment（投稿前品質ゲート）
# ---------------------------------------------------------------------------

def _eval_result(score: int = 80, hallucinated: list[str] | None = None) -> dict:
    return {"score": score, "details": {"chara_valid": {"hallucinated": hallucinated or []}}}


def _call_validated_comment() -> tuple:
    return _generate_validated_comment(
        [_make_battle()], "2026/04/10", "2026-04-10", "Alice", [], {}, [], None,
    )


def test_validated_comment_clean_first_try():
    """ハルシネーションなし → 1回の生成でそのまま採用。"""
    with (
        patch("main._analyze_with_timeout", return_value="良い試合。対策しよう。") as mock_gen,
        patch("bot.evaluator.evaluate_comment", return_value=_eval_result(80)),
    ):
        comment, result = _call_validated_comment()
    assert comment == "良い試合。対策しよう。"
    assert result["score"] == 80
    mock_gen.assert_called_once()


def test_validated_comment_none_when_generation_fails():
    """生成が None（タイムアウト等）→ (None, None) を返し評価しない。"""
    with (
        patch("main._analyze_with_timeout", return_value=None),
        patch("bot.evaluator.evaluate_comment") as mock_eval,
    ):
        assert _call_validated_comment() == (None, None)
    mock_eval.assert_not_called()


def test_validated_comment_regenerates_on_hallucination():
    """未対戦キャラを検出 → 1回だけ再生成し、クリーンなら採用。"""
    with (
        patch(
            "main._analyze_with_timeout",
            side_effect=["飛鳥対策が光る", "良い試合。対策しよう。"],
        ) as mock_gen,
        patch(
            "bot.evaluator.evaluate_comment",
            side_effect=[_eval_result(40, ["Asuka"]), _eval_result(80)],
        ),
    ):
        comment, result = _call_validated_comment()
    assert comment == "良い試合。対策しよう。"
    assert result["score"] == 80
    assert mock_gen.call_count == 2


def test_validated_comment_dropped_when_hallucination_persists():
    """再生成後もハルシネーション残存 → コメントを破棄、スコアだけ記録する。"""
    with (
        patch("main._analyze_with_timeout", side_effect=["飛鳥対策", "また飛鳥"]),
        patch(
            "bot.evaluator.evaluate_comment",
            side_effect=[_eval_result(40, ["Asuka"]), _eval_result(40, ["Asuka"])],
        ),
        patch("bot.db.save_llm_eval_score") as mock_save,
    ):
        assert _call_validated_comment() == (None, None)
    mock_save.assert_called_once_with("2026-04-10", "Alice", 40, "また飛鳥")


def test_validated_comment_none_when_regeneration_fails():
    """再生成が None → 元のハルシネーションコメントは破棄され (None, None)。"""
    with (
        patch("main._analyze_with_timeout", side_effect=["飛鳥対策", None]),
        patch("bot.evaluator.evaluate_comment", return_value=_eval_result(40, ["Asuka"])),
    ):
        assert _call_validated_comment() == (None, None)


def test_validated_comment_kept_when_evaluator_raises():
    """評価器が例外 → コメントは止めずそのまま採用（Fail Gracefully）。"""
    with (
        patch("main._analyze_with_timeout", return_value="良い試合。対策しよう。"),
        patch("bot.evaluator.evaluate_comment", side_effect=RuntimeError("eval error")),
    ):
        comment, result = _call_validated_comment()
    assert comment == "良い試合。対策しよう。"
    assert result is None


# ---------------------------------------------------------------------------
# _run_weekly_for_player
# ---------------------------------------------------------------------------

from main import _run_weekly_for_player


def test_run_weekly_for_player_returns_community_stats():
    """正常実行 → community_stats エントリを返す。"""
    battles = [_make_battle()]
    mock_post_result = ([("msg1", "https://discord.com/api/webhooks/1/tok")], {"title": "t"})
    with (
        patch("bot.db.get_battles_since", return_value=battles),
        patch("bot.db.get_battles_between", return_value=[]),
        patch("main.discord_post.post_weekly", return_value=mock_post_result),
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value=None),
        patch("main.discord_post.edit_llm_comment"),
        patch("main.discord_post.notify_error"),
    ):
        result = _run_weekly_for_player("Alice", 1000000.0, "2026/04/07")

    assert result["name"] == "Alice"
    assert "wins" in result
    assert "losses" in result
    assert "net_rating" in result


def test_run_weekly_for_player_no_battles():
    """試合なし → wins/losses 0 を返す。"""
    mock_post_result = None
    with (
        patch("bot.db.get_battles_since", return_value=[]),
        patch("bot.db.get_battles_between", return_value=[]),
        patch("main.discord_post.post_weekly", return_value=mock_post_result),
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value=None),
        patch("main.discord_post.notify_error"),
    ):
        result = _run_weekly_for_player("Bob", 1000000.0, "2026/04/07")

    assert result["wins"] == 0
    assert result["losses"] == 0


def test_run_weekly_for_player_post_exception():
    """weekly 投稿が例外 → notify_error が呼ばれる。"""
    with (
        patch("bot.db.get_battles_since", return_value=[_make_battle()]),
        patch("bot.db.get_battles_between", return_value=[]),
        patch("main.discord_post.post_weekly", side_effect=RuntimeError("webhook error")),
        patch("main.discord_post.notify_error") as mock_err,
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value=None),
    ):
        _run_weekly_for_player("Alice", 1000000.0, "2026/04/07")

    mock_err.assert_called_once()


def test_run_weekly_for_player_edits_llm_comment():
    """LLM コメントあり & 投稿成功 → edit_llm_comment が呼ばれる。"""
    battles = [_make_battle()]
    mock_post_result = ([("msg1", "https://discord.com/api/webhooks/1/tok")], {"title": "t"})
    with (
        patch("bot.db.get_battles_since", return_value=battles),
        patch("bot.db.get_battles_between", return_value=[]),
        patch("main.discord_post.post_weekly", return_value=mock_post_result),
        patch("bot.db.get_latest_comment_before", return_value=None),
        patch("main._analyze_with_timeout", return_value="LLMコメント"),
        patch("main.discord_post.edit_llm_comment") as mock_edit,
        patch("main.discord_post.notify_error"),
    ):
        _run_weekly_for_player("Alice", 1000000.0, "2026/04/07")

    mock_edit.assert_called_once()


# ---------------------------------------------------------------------------
# main() / weekly() 非同期関数
# ---------------------------------------------------------------------------

import main as _main_module


def test_main_skips_if_lock_held():
    """_main_lock 取得済みの場合 main() は即座に return する。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = False
    with (
        patch.object(_main_module, "_main_lock", mock_lock),
        patch("bot.db.init_db") as mock_init,
    ):
        asyncio.run(_main_module.main())
    mock_init.assert_not_called()


def test_main_config_errors_exit():
    """設定エラーがある場合 sys.exit(1) → SystemExit(1) を送出する。"""
    import pytest
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    with (
        patch.object(_main_module, "_main_lock", mock_lock),
        patch("main.validate_config", return_value=["ERROR: 設定値が不正"]),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(_main_module.main())
    assert exc_info.value.code == 1


def test_main_no_players_exits():
    """プレイヤー未設定時は sys.exit(1) を呼ぶ。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    with (
        patch.object(_main_module, "_main_lock", mock_lock),
        patch("main.validate_config", return_value=[]),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("bot.db.repair_unknown_chara_names", return_value=0),
        patch("bot.db.get_unknown_chara_battles", return_value=[]),
        patch("main.get_players", return_value=[]),
        patch("bot.db.record_run_success"),
        patch("main.sys.exit") as mock_exit,
    ):
        asyncio.run(_main_module.main())
    mock_exit.assert_called_once_with(1)


def test_main_happy_path():
    """正常実行 → _run_for_player と backup_db が呼ばれる。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    backup_mock = MagicMock()
    backup_mock.name = "battles_20260412.db"
    with (
        patch.object(_main_module, "_main_lock", mock_lock),
        patch("main.validate_config", return_value=[]),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("bot.db.repair_unknown_chara_names", return_value=0),
        patch("bot.db.get_unknown_chara_battles", return_value=[]),
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("main._run_for_player") as mock_run,
        patch("bot.db.backup_db", return_value=backup_mock),
        patch("bot.db.record_run_success") as mock_heartbeat,
    ):
        asyncio.run(_main_module.main(target_date="2026-04-12"))
    mock_run.assert_called_once_with("Alice", "pid_a", "2026-04-12", "2026/04/12")
    mock_heartbeat.assert_called_once_with("daily")


def test_main_unknown_chara_logs_warning():
    """未学習キャラが存在する場合、警告ログを出力して処理を続行する。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    backup_mock = MagicMock()
    backup_mock.name = "battles_20260412.db"
    unknown = [
        {"my_chara_id": 99, "opp_chara_id": None, "my_chara": "Chara#99", "opp_chara": None},
    ]
    with (
        patch.object(_main_module, "_main_lock", mock_lock),
        patch("main.validate_config", return_value=[]),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("bot.db.repair_unknown_chara_names", return_value=0),
        patch("bot.db.get_unknown_chara_battles", return_value=unknown),
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("main._run_for_player"),
        patch("bot.db.backup_db", return_value=backup_mock),
        patch("bot.db.record_run_success"),
    ):
        asyncio.run(_main_module.main(target_date="2026-04-12"))  # should not raise


def test_unknown_chara_label_picks_opponent_side():
    """相手側が Chara#N なら、相手の ID と名前を組にして返す。"""
    row = {"my_chara_id": 45, "my_chara": "Miary Zo",
           "opp_chara_id": 43, "opp_chara": "Chara#43"}
    assert _unknown_chara_label(row) == "ID=43 (Chara#43)"


def test_unknown_chara_label_picks_self_side():
    """自分側が Chara#N なら、自分の ID と名前を組にして返す。"""
    row = {"my_chara_id": 47, "my_chara": "Chara#47",
           "opp_chara_id": 6, "opp_chara": "Jin"}
    assert _unknown_chara_label(row) == "ID=47 (Chara#47)"


def test_main_repaired_chara_names_logs_count():
    """Chara#N レコードを修復した場合、件数をログに残して処理を続行する。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    backup_mock = MagicMock()
    backup_mock.name = "battles_20260412.db"
    with (
        patch.object(_main_module, "_main_lock", mock_lock),
        patch("main.validate_config", return_value=[]),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("bot.db.repair_unknown_chara_names", return_value=8),
        patch("bot.db.get_unknown_chara_battles", return_value=[]),
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("main._run_for_player"),
        patch("bot.db.backup_db", return_value=backup_mock),
        patch("bot.db.record_run_success"),
    ):
        asyncio.run(_main_module.main(target_date="2026-04-12"))  # should not raise


def test_main_backup_failure_does_not_raise():
    """DB バックアップ失敗時も例外を伝播させない。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    with (
        patch.object(_main_module, "_main_lock", mock_lock),
        patch("main.validate_config", return_value=[]),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("bot.db.repair_unknown_chara_names", return_value=0),
        patch("bot.db.get_unknown_chara_battles", return_value=[]),
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("main._run_for_player"),
        patch("bot.db.backup_db", side_effect=OSError("disk full")),
        patch("bot.db.record_run_success"),
    ):
        asyncio.run(_main_module.main(target_date="2026-04-12"))  # should not raise


def test_weekly_skips_if_lock_held():
    """_weekly_lock 取得済みの場合 weekly() は即座に return する。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = False
    with (
        patch.object(_main_module, "_weekly_lock", mock_lock),
        patch("bot.db.init_db") as mock_init,
    ):
        asyncio.run(_main_module.weekly())
    mock_init.assert_not_called()


def test_weekly_no_players_returns_early():
    """プレイヤー未設定時は post_community_weekly を呼ばない。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    with (
        patch.object(_main_module, "_weekly_lock", mock_lock),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("main.get_players", return_value=[]),
        patch("main.discord_post.post_community_weekly") as mock_community,
    ):
        asyncio.run(_main_module.weekly())
    mock_community.assert_not_called()


def test_weekly_happy_path():
    """正常実行 → _run_weekly_for_player と post_community_weekly が呼ばれる。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    weekly_result = {"name": "Alice", "wins": 5, "losses": 3, "net_rating": 200}
    with (
        patch.object(_main_module, "_weekly_lock", mock_lock),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("main._run_weekly_for_player", return_value=weekly_result),
        patch("main.discord_post.post_community_weekly") as mock_community,
        patch("bot.db.record_run_success"),
    ):
        asyncio.run(_main_module.weekly())
    mock_community.assert_called_once()


# ---------------------------------------------------------------------------
# _fire_rank_alerts
# ---------------------------------------------------------------------------

def test_fire_rank_alerts_no_battles():
    """バトルなし → 何もしない。"""
    with patch("bot.discord_post.post_rank_change") as mock_post:
        _fire_rank_alerts([], "2026-04-10", "Alice")
    mock_post.assert_not_called()


def test_fire_rank_alerts_no_rank_in_latest():
    """最新バトルに my_rank がない → 何もしない。"""
    b = _battle(battle_at=1_000_000)
    # my_rank 未設定
    with patch("bot.discord_post.post_rank_change") as mock_post:
        _fire_rank_alerts([b], "2026-04-10", "Alice")
    mock_post.assert_not_called()


def test_fire_rank_alerts_no_previous_rank():
    """前回の段位が DB にない → 何もしない。"""
    b = dict(_battle(battle_at=1_000_000), my_rank=15)
    with (
        patch("bot.db.get_last_rank_before_date", return_value=None),
        patch("bot.discord_post.post_rank_change") as mock_post,
    ):
        _fire_rank_alerts([b], "2026-04-10", "Alice")
    mock_post.assert_not_called()


def test_fire_rank_alerts_same_rank():
    """段位変化なし → 通知しない。"""
    b = dict(_battle(battle_at=1_000_000), my_rank=15)
    with (
        patch("bot.db.get_last_rank_before_date", return_value=15),
        patch("bot.discord_post.post_rank_change") as mock_post,
    ):
        _fire_rank_alerts([b], "2026-04-10", "Alice")
    mock_post.assert_not_called()


def test_fire_rank_alerts_promotion():
    """昇格 → post_rank_change が呼ばれる。"""
    b = dict(_battle(battle_at=1_000_000), my_rank=16)
    with (
        patch("bot.db.get_last_rank_before_date", return_value=15),
        patch("bot.discord_post.post_rank_change") as mock_post,
    ):
        _fire_rank_alerts([b], "2026-04-10", "Alice")
    mock_post.assert_called_once_with("Alice", 15, 16)


def test_fire_rank_alerts_demotion():
    """降格 → post_rank_change が呼ばれる。"""
    b = dict(_battle(battle_at=1_000_000), my_rank=14)
    with (
        patch("bot.db.get_last_rank_before_date", return_value=15),
        patch("bot.discord_post.post_rank_change") as mock_post,
    ):
        _fire_rank_alerts([b], "2026-04-10", "Alice")
    mock_post.assert_called_once_with("Alice", 15, 14)


def test_fire_rank_alerts_uses_latest_battle():
    """複数バトルがある場合、最新（battle_at 最大）の my_rank を使う。"""
    b_old = dict(_battle(battle_id="old", battle_at=1_000_000), my_rank=15)
    b_new = dict(_battle(battle_id="new", battle_at=2_000_000), my_rank=16)
    with (
        patch("bot.db.get_last_rank_before_date", return_value=15),
        patch("bot.discord_post.post_rank_change") as mock_post,
    ):
        _fire_rank_alerts([b_old, b_new], "2026-04-10", "Alice")
    mock_post.assert_called_once_with("Alice", 15, 16)


# ---------------------------------------------------------------------------
# _run_monthly_for_player
# ---------------------------------------------------------------------------

from main import _run_monthly_for_player


def test_run_monthly_for_player_happy_path():
    """正常実行 → post_monthly が呼ばれる。"""
    battles = [_make_battle()]
    mock_post_result = ([("msg1", "https://discord.com/api/webhooks/1/tok")], {"title": "t"})
    with (
        patch("bot.db.get_battles_in_month", return_value=battles),
        patch("main.discord_post.post_monthly", return_value=mock_post_result) as mock_post,
        patch("main._analyze_with_timeout", return_value=None),
        patch("main.discord_post.edit_llm_comment"),
        patch("main.discord_post.notify_error"),
    ):
        _run_monthly_for_player("Alice", 2026, 3, "2026年3月")
    mock_post.assert_called_once()


def test_run_monthly_for_player_no_battles():
    """試合なし → post_monthly が None を返してもエラーなし。"""
    with (
        patch("bot.db.get_battles_in_month", return_value=[]),
        patch("main.discord_post.post_monthly", return_value=None),
        patch("main._analyze_with_timeout", return_value=None),
        patch("main.discord_post.notify_error"),
    ):
        _run_monthly_for_player("Alice", 2026, 3, "2026年3月")  # should not raise


def test_run_monthly_for_player_post_exception():
    """投稿失敗 → notify_error が呼ばれる。"""
    with (
        patch("bot.db.get_battles_in_month", return_value=[_make_battle()]),
        patch("main.discord_post.post_monthly", side_effect=RuntimeError("error")),
        patch("main.discord_post.notify_error") as mock_err,
        patch("main._analyze_with_timeout", return_value=None),
    ):
        _run_monthly_for_player("Alice", 2026, 3, "2026年3月")
    mock_err.assert_called_once()


def test_run_monthly_for_player_with_llm():
    """LLM コメントあり → edit_llm_comment が呼ばれる。"""
    battles = [_make_battle()]
    mock_post_result = ([("msg1", "https://discord.com/api/webhooks/1/tok")], {"title": "t"})
    with (
        patch("bot.db.get_battles_in_month", return_value=battles),
        patch("main.discord_post.post_monthly", return_value=mock_post_result),
        patch("main._analyze_with_timeout", return_value="月次コメント"),
        patch("main.discord_post.edit_llm_comment") as mock_edit,
        patch("main.discord_post.notify_error"),
    ):
        _run_monthly_for_player("Alice", 2026, 3, "2026年3月")
    mock_edit.assert_called_once()


def test_run_monthly_for_player_january_prev_month():
    """1月の場合、前月は前年12月になる。"""
    calls = []
    def _mock_get_battles_in_month(year, month, player_name=None):
        calls.append((year, month))
        return []
    with (
        patch("bot.db.get_battles_in_month", side_effect=_mock_get_battles_in_month),
        patch("main.discord_post.post_monthly", return_value=None),
        patch("main._analyze_with_timeout", return_value=None),
        patch("main.discord_post.notify_error"),
    ):
        _run_monthly_for_player("Alice", 2026, 1, "2026年1月")
    # 当月(2026,1) と 前月(2025,12) の2回呼ばれるはず
    assert (2026, 1) in calls
    assert (2025, 12) in calls


# ---------------------------------------------------------------------------
# monthly() / run_monthly_sync
# ---------------------------------------------------------------------------

def test_monthly_skips_if_lock_held():
    """_monthly_lock 取得済み → monthly() は即座に return する。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = False
    with (
        patch.object(_main_module, "_monthly_lock", mock_lock),
        patch("bot.db.init_db") as mock_init,
    ):
        asyncio.run(_main_module.monthly())
    mock_init.assert_not_called()


def test_monthly_no_players_returns_early():
    """プレイヤー未設定 → _run_monthly_for_player を呼ばない。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    with (
        patch.object(_main_module, "_monthly_lock", mock_lock),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("main.get_players", return_value=[]),
        patch("main._run_monthly_for_player") as mock_run,
    ):
        asyncio.run(_main_module.monthly())
    mock_run.assert_not_called()


def test_monthly_happy_path():
    """正常実行 → _run_monthly_for_player が呼ばれる。"""
    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True
    with (
        patch.object(_main_module, "_monthly_lock", mock_lock),
        patch("bot.db.init_db"),
        patch("main.fetcher.load_learned_chara_names"),
        patch("main.get_players", return_value=[("Alice", "pid_a")]),
        patch("main._run_monthly_for_player") as mock_run,
        patch("bot.db.record_run_success"),
    ):
        asyncio.run(_main_module.monthly(month="2026-03"))
    mock_run.assert_called_once()
    args = mock_run.call_args[0]
    assert args[0] == "Alice"
    assert args[1] == 2026
    assert args[2] == 3


def test_run_monthly_sync_runs_without_error():
    """run_monthly_sync() が asyncio.run(monthly()) を呼ぶ（モック）。"""
    with patch("main.monthly", new=AsyncMock()):
        run_monthly_sync()  # should not raise
