"""
Docker コンテナ用スケジューラ。
毎日 23:00 JST に main.py のロジックを実行する。
毎週日曜 21:00 JST に週次サマリーを投稿する。
"""

import time
import schedule
from datetime import datetime, timezone, timedelta

from main import setup_logging
import main as bot

setup_logging()

import logging
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def job():
    logger.info(f"[scheduler] 定時実行開始 {datetime.now(JST).isoformat()}")
    try:
        bot.main()
    except SystemExit as e:
        # main() が sys.exit() しても scheduler は継続
        logger.warning(f"[scheduler] main() が終了コード {e.code} で終了")
    except Exception as e:
        logger.error(f"[scheduler] main() で予期しないエラー: {e}")


def weekly_job():
    logger.info(f"[scheduler] 週次サマリー実行開始 {datetime.now(JST).isoformat()}")
    try:
        bot.weekly()
    except Exception as e:
        logger.error(f"[scheduler] weekly() で予期しないエラー: {e}")


# JST 23:00 = UTC 14:00
schedule.every().day.at("14:00").do(job)

# JST 21:00 (日曜) = UTC 12:00 (日曜)
schedule.every().sunday.at("12:00").do(weekly_job)

logger.info("スケジューラ起動。毎日 23:00 JST に実行、毎週日曜 21:00 JST に週次サマリーを実行します。")
logger.info(f"現在時刻: {datetime.now(JST).isoformat()}")

while True:
    schedule.run_pending()
    time.sleep(30)
