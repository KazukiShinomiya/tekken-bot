"""
bot/catchup.py（起動時キャッチアップ）のテスト。
missed_jobs は純ロジックとして時刻を固定して検証し、
run_catch_up は DB・main の各エントリポイントをモックして検証する。
"""

from datetime import datetime
from unittest.mock import patch

from bot.catchup import missed_jobs, run_catch_up
from bot.config import JST


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> int:
    """JST の日時を UTC epoch 秒に変換する（run_status の記録形式）。"""
    return int(datetime(y, m, d, hh, mm, tzinfo=JST).timestamp())


def _now(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=JST)


# 2026-04-08 は水曜、2026-04-12 は日曜、2026-04-13 は月曜
WED = (2026, 4, 8)
SUN = (2026, 4, 12)
MON = (2026, 4, 13)


def test_calendar_assumptions():
    """テストで前提とする曜日が正しいことを固定する。"""
    assert datetime(*WED, tzinfo=JST).weekday() == 2  # 水
    assert datetime(*SUN, tzinfo=JST).weekday() == 6  # 日
    assert datetime(*MON, tzinfo=JST).weekday() == 0  # 月


# ---------------------------------------------------------------------------
# missed_jobs — daily
# ---------------------------------------------------------------------------

def test_daily_missed_when_last_success_is_yesterday():
    """08:00 を過ぎて心拍が前日のまま → daily を取り逃している。"""
    status = {"daily": _ts(2026, 4, 7, 8, 5), "monthly": _ts(2026, 4, 1, 9, 5)}
    assert missed_jobs(status, _now(*WED, 10)) == ["daily"]


def test_daily_not_missed_after_todays_run():
    """今日 08:00 の実行が記録済み → 取り逃しなし。"""
    status = {"daily": _ts(2026, 4, 8, 8, 1), "monthly": _ts(2026, 4, 1, 9, 5)}
    assert missed_jobs(status, _now(*WED, 10)) == []


def test_daily_not_missed_before_8am():
    """今日の 08:00 がまだ来ていない → 取り逃し扱いしない。"""
    status = {"daily": _ts(2026, 4, 7, 8, 5), "monthly": _ts(2026, 4, 1, 9, 5)}
    assert missed_jobs(status, _now(*WED, 7)) == []


def test_job_without_record_is_skipped():
    """run_status に記録が無いジョブは初回と区別できないため対象外。"""
    assert missed_jobs({}, _now(*WED, 10)) == []


# ---------------------------------------------------------------------------
# missed_jobs — weekly（日曜 21:00、同じ日曜のうちのみ救済可能）
# ---------------------------------------------------------------------------

def test_weekly_missed_on_sunday_night():
    """日曜 21:00 を過ぎて心拍が前週のまま → weekly を取り逃している。"""
    status = {
        "daily":   _ts(2026, 4, 12, 8, 5),
        "weekly":  _ts(2026, 4, 5, 21, 5),
        "monthly": _ts(2026, 4, 1, 9, 5),
    }
    assert missed_jobs(status, _now(*SUN, 22)) == ["weekly"]


def test_weekly_not_missed_before_9pm_sunday():
    """日曜でも 21:00 前なら取り逃しではない。"""
    status = {
        "daily":   _ts(2026, 4, 12, 8, 5),
        "weekly":  _ts(2026, 4, 5, 21, 5),
        "monthly": _ts(2026, 4, 1, 9, 5),
    }
    assert missed_jobs(status, _now(*SUN, 20)) == []


def test_weekly_not_caught_up_after_week_boundary():
    """月曜以降は weekly() の集計対象が翌週に変わるため救済しない。"""
    status = {
        "daily":   _ts(2026, 4, 13, 8, 5),
        "weekly":  _ts(2026, 4, 5, 21, 5),
        "monthly": _ts(2026, 4, 1, 9, 5),
    }
    assert missed_jobs(status, _now(*MON, 10)) == []


# ---------------------------------------------------------------------------
# missed_jobs — monthly（1日 09:00、月内なら救済可能）
# ---------------------------------------------------------------------------

def test_monthly_missed_within_month():
    """月初 09:00 の心拍が先月のまま → 月内はいつでも救済する。"""
    status = {"daily": _ts(2026, 4, 8, 8, 5), "monthly": _ts(2026, 3, 1, 9, 5)}
    assert missed_jobs(status, _now(*WED, 10)) == ["monthly"]


def test_multiple_missed_jobs():
    """daily と monthly を同時に取り逃した場合は両方返る。"""
    status = {"daily": _ts(2026, 4, 7, 8, 5), "monthly": _ts(2026, 3, 1, 9, 5)}
    assert missed_jobs(status, _now(*WED, 10)) == ["daily", "monthly"]


# ---------------------------------------------------------------------------
# run_catch_up
# ---------------------------------------------------------------------------

def test_run_catch_up_skips_on_empty_status():
    """run_status が空（初回起動）→ 何も実行しない。"""
    with (
        patch("bot.db.init_db"),
        patch("bot.db.get_run_status", return_value=[]),
        patch("main.run_main_sync") as mock_daily,
    ):
        assert run_catch_up() == []
    mock_daily.assert_not_called()


def test_run_catch_up_skips_when_nothing_missed():
    """取り逃しなし → 何も実行しない。"""
    rows = [{"job_name": "daily", "last_success_at": _ts(2026, 4, 8, 8, 1)}]
    with (
        patch("bot.db.init_db"),
        patch("bot.db.get_run_status", return_value=rows),
        patch("bot.catchup.missed_jobs", return_value=[]),
        patch("main.run_main_sync") as mock_daily,
    ):
        assert run_catch_up() == []
    mock_daily.assert_not_called()


def test_run_catch_up_runs_missed_jobs():
    """取り逃した daily / weekly を実行し、実行済みリストを返す。"""
    rows = [{"job_name": "daily", "last_success_at": 1}]
    with (
        patch("bot.db.init_db"),
        patch("bot.db.get_run_status", return_value=rows),
        patch("bot.catchup.missed_jobs", return_value=["daily", "weekly"]),
        patch("main.run_main_sync") as mock_daily,
        patch("main.run_weekly_sync") as mock_weekly,
        patch("main.run_monthly_sync") as mock_monthly,
    ):
        assert run_catch_up() == ["daily", "weekly"]
    mock_daily.assert_called_once()
    mock_weekly.assert_called_once()
    mock_monthly.assert_not_called()


def test_run_catch_up_continues_after_job_failure():
    """1つのジョブが失敗しても残りは継続する（Fail Gracefully）。"""
    rows = [{"job_name": "daily", "last_success_at": 1}]
    with (
        patch("bot.db.init_db"),
        patch("bot.db.get_run_status", return_value=rows),
        patch("bot.catchup.missed_jobs", return_value=["daily", "monthly"]),
        patch("main.run_main_sync", side_effect=RuntimeError("boom")),
        patch("main.run_monthly_sync") as mock_monthly,
    ):
        assert run_catch_up() == ["monthly"]
    mock_monthly.assert_called_once()
