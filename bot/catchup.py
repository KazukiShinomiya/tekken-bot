"""
起動時キャッチアップ。

コンテナがスケジュール時刻（毎日 08:00 / 日曜 21:00 / 毎月1日 09:00 JST）に
停止していた場合（停電・再起動・ビルド中）、その日のジョブは丸ごと欠ける。
scheduler.py の起動時に run_status の心拍と直近のスケジュール時刻を照合し、
取り逃したジョブを実行して穴を塞ぐ。

各ジョブの集計対象は「実行時刻からの相対」で決まるため、キャッチアップが
正しい結果を生む猶予はジョブごとに異なる:
  daily   — main() は常に「昨日」を投稿する。当日 08:00 を逃しても日内なら正しい
  weekly  — weekly() は「今週（月曜起算）」を集計する。週を跨ぐと対象週が変わる
            ため、日曜 21:00 の取り逃しは同じ日曜のうちしか救済できない
  monthly — monthly() は「先月」を投稿する。1日 09:00 を逃しても月内なら正しい
"""

import logging
from datetime import datetime

from bot.config import JST

logger = logging.getLogger(__name__)


def _current_slots(now: datetime) -> dict[str, datetime]:
    """「今キャッチアップしても集計対象が正しい」直近スケジュール時刻を返す。

    猶予を過ぎたジョブ（例: 月曜以降の weekly）はここに含めない＝救済しない。
    """
    slots = {
        "daily":   now.replace(hour=8, minute=0, second=0, microsecond=0),
        "monthly": now.replace(day=1, hour=9, minute=0, second=0, microsecond=0),
    }
    if now.weekday() == 6:  # 日曜
        slots["weekly"] = now.replace(hour=21, minute=0, second=0, microsecond=0)
    return slots


def missed_jobs(run_status: dict[str, int], now: datetime | None = None) -> list[str]:
    """取り逃したジョブ名のリストを返す（純ロジック）。

    Args:
        run_status: job_name → 最終正常完了時刻（UTC epoch 秒）
        now:        現在時刻（JST aware）。省略時は現在

    run_status に記録が無いジョブは初回セットアップと区別できないため対象外。
    """
    if now is None:
        now = datetime.now(JST)
    missed: list[str] = []
    for job, slot in _current_slots(now).items():
        last = run_status.get(job)
        if last is None:
            continue
        if now >= slot and last < slot.timestamp():
            missed.append(job)
    return missed


def run_catch_up() -> list[str]:
    """起動時に呼び、取り逃したジョブを実行する。実行に成功したジョブ名を返す。

    1つのジョブが失敗しても残りは継続する（Fail Gracefully）。
    """
    # main は import 時に dotenv 読込等の副作用を持つため、循環を避けて遅延 import する
    import bot.db as db
    import main as bot_main

    db.init_db()
    status = {r["job_name"]: r["last_success_at"] for r in db.get_run_status()}
    if not status:
        logger.info("[catchup] run_status が空（初回起動）。キャッチアップをスキップ。")
        return []

    jobs = missed_jobs(status)
    if not jobs:
        logger.info("[catchup] 取り逃したジョブなし。")
        return []

    runners = {
        "daily":   bot_main.run_main_sync,
        "weekly":  bot_main.run_weekly_sync,
        "monthly": bot_main.run_monthly_sync,
    }
    executed: list[str] = []
    for job in jobs:
        logger.info(f"[catchup] {job} ジョブの取り逃しを検出。キャッチアップを実行する。")
        try:
            runners[job]()
            executed.append(job)
        except Exception as e:
            logger.error(f"[catchup] {job} のキャッチアップ失敗: {e}")
    return executed
