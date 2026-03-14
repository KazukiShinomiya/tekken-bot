"""
Tekken Bot メインスクリプト。
バトルを取得して DB に保存し、当日分を Discord に投稿する。

実行方法:
    python main.py
"""

import sys
from datetime import datetime, timezone, timedelta

import db
import fetcher
import discord_post
import analyzer

JST = timezone(timedelta(hours=9))


def main() -> None:
    now = datetime.now(JST)
    print(f"[{now.isoformat()}] Tekken Bot 起動")

    db.init_db()

    # DB の最新タイムスタンプ以降を取得
    since_ts = db.get_latest_battle_at()
    print(f"前回の最終バトル: {datetime.fromtimestamp(since_ts, JST) if since_ts else '（初回）'}")

    try:
        new_battles = fetcher.fetch_battles_since(since_ts)
    except Exception as e:
        print(f"データ取得失敗: {e}", file=sys.stderr)
        sys.exit(1)

    inserted = db.insert_battles(new_battles)
    print(f"{inserted} 件を DB に保存")

    # 当日（JST）のバトルを DB から取得して投稿
    today_battles = db.get_battles_on_date(now.strftime("%Y-%m-%d"))
    print(f"本日分: {len(today_battles)} 件")

    if not today_battles:
        print("本日の試合なし。投稿をスキップ。")
        return

    date_str = now.strftime("%Y/%m/%d")

    # LLM分析（失敗してもスキップして続行）
    llm_comment = analyzer.analyze(today_battles, date_str)

    try:
        discord_post.post(today_battles, date_str, llm_comment)
    except Exception as e:
        print(f"Discord 投稿失敗: {e}", file=sys.stderr)
        sys.exit(1)

    print("投稿完了。")


if __name__ == "__main__":
    main()
