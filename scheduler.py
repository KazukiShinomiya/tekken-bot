"""
Docker コンテナ用スケジューラ。
毎日 23:00 JST に main.py のロジックを実行する。
"""

import time
import schedule
from datetime import datetime, timezone, timedelta

import main as bot

JST = timezone(timedelta(hours=9))


def job():
    print(f"[scheduler] 定時実行開始 {datetime.now(JST).isoformat()}")
    try:
        bot.main()
    except SystemExit as e:
        # main() が sys.exit() しても scheduler は継続
        print(f"[scheduler] main() が終了コード {e.code} で終了")


# JST 23:00 = UTC 14:00
schedule.every().day.at("14:00").do(job)

print(f"[scheduler] 起動。毎日 23:00 JST に実行します。")
print(f"[scheduler] 現在時刻: {datetime.now(JST).isoformat()}")

while True:
    schedule.run_pending()
    time.sleep(30)
