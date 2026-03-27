"""
Docker コンテナ用スケジューラ。
毎日 08:00 JST に前日分のバトルを集計して投稿する。
毎週日曜 21:00 JST に週次サマリーを投稿する。
"""

import time
import schedule
from datetime import datetime

from main import setup_logging
import main as bot
from bot.config import JST

setup_logging()

from bot.slash_commands import start_bot_thread
start_bot_thread()

import logging
logger = logging.getLogger(__name__)

def job():
    logger.info(f"[scheduler] 定時実行開始 {datetime.now(JST).isoformat()}")
    try:
        bot.run_main_sync()
    except SystemExit as e:
        # main() が sys.exit() しても scheduler は継続
        logger.warning(f"[scheduler] main() が終了コード {e.code} で終了")
    except Exception as e:
        logger.error(f"[scheduler] main() で予期しないエラー: {e}")


def weekly_job():
    logger.info(f"[scheduler] 週次サマリー実行開始 {datetime.now(JST).isoformat()}")
    try:
        bot.run_weekly_sync()
    except Exception as e:
        logger.error(f"[scheduler] weekly() で予期しないエラー: {e}")


schedule.every().day.at("08:00").do(job)
schedule.every().sunday.at("21:00").do(weekly_job)

logger.info("スケジューラ起動。毎日 08:00 JST に前日分を投稿、毎週日曜 21:00 JST に週次サマリーを実行します。")
logger.info(f"現在時刻: {datetime.now(JST).isoformat()}")

while True:
    schedule.run_pending()
    time.sleep(30)
