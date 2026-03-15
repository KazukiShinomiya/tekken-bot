"""
Tekken Bot メインスクリプト。
バトルを取得して DB に保存し、当日分を Discord に投稿する。

実行方法:
    python main.py
"""

import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import bot.db as db
import bot.fetcher as fetcher
import bot.discord_post as discord_post
import bot.analyzer as analyzer

JST = timezone(timedelta(hours=9))

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """RotatingFileHandler + StreamHandler でロギングを設定する。"""
    log_path = Path(os.getenv("LOG_PATH", "data/tekken_bot.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=3,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def get_players() -> list[tuple[str, str]]:
    """
    設定から (player_name, polaris_id) のリストを返す。
    PLAYERS=Name1:id1,Name2:id2 または TEKKEN_ID + POLARIS_ID の後方互換に対応。
    """
    players_env = os.getenv("PLAYERS", "").strip()
    if players_env:
        result = []
        for entry in players_env.split(","):
            entry = entry.strip()
            if ":" not in entry:
                continue
            name, pid = entry.split(":", 1)
            result.append((name.strip(), pid.strip()))
        return result

    # 後方互換: 単一プレイヤー設定
    polaris_id = os.getenv("POLARIS_ID")
    tekken_id  = os.getenv("TEKKEN_ID", "default")
    if polaris_id:
        return [(tekken_id, polaris_id)]
    return []


def _run_for_player(player_name: str, polaris_id: str, today_str: str, date_str: str) -> None:
    """1プレイヤー分のバトル取得・保存・投稿を実行する。"""
    logger.info(f"[{player_name}] 処理開始")

    since_ts = db.get_latest_battle_at(player_name=player_name)
    logger.info(f"[{player_name}] 前回の最終バトル: "
                f"{datetime.fromtimestamp(since_ts, JST).isoformat() if since_ts else '（初回）'}")

    try:
        new_battles = fetcher.fetch_battles_since(since_ts, polaris_id=polaris_id)
    except Exception as e:
        logger.error(f"[{player_name}] データ取得失敗: {e}")
        return

    inserted = db.insert_battles(new_battles, player_name=player_name)
    logger.info(f"[{player_name}] {inserted} 件を DB に保存")

    today_battles = db.get_battles_on_date(today_str, player_name=player_name)
    logger.info(f"[{player_name}] 本日分: {len(today_battles)} 件")

    if not today_battles:
        logger.info(f"[{player_name}] 本日の試合なし。投稿をスキップ。")
        return

    llm_comment = analyzer.analyze(today_battles, date_str, player_name=player_name)

    try:
        discord_post.post(today_battles, date_str, llm_comment, player_name=player_name)
        logger.info(f"[{player_name}] 投稿完了。")
    except Exception as e:
        logger.error(f"[{player_name}] Discord 投稿失敗: {e}")


def main() -> None:
    now = datetime.now(JST)
    logger.info(f"Tekken Bot 起動 {now.isoformat()}")

    db.init_db()

    players = get_players()
    if not players:
        logger.error("プレイヤーが設定されていません。PLAYERS または POLARIS_ID を .env に設定してください。")
        sys.exit(1)

    today_str = now.strftime("%Y-%m-%d")
    date_str  = now.strftime("%Y/%m/%d")

    for player_name, polaris_id in players:
        _run_for_player(player_name, polaris_id, today_str, date_str)


def weekly() -> None:
    """週次サマリーを全プレイヤー分投稿する（日曜 JST 21:00 実行想定）。"""
    now = datetime.now(JST)
    logger.info(f"Tekken Bot 週次サマリー開始 {now.isoformat()}")

    db.init_db()

    players = get_players()
    if not players:
        logger.warning("プレイヤーが設定されていません。週次サマリーをスキップ。")
        return

    since_ts = (now - timedelta(days=7)).timestamp()
    week_start_str = (now - timedelta(days=6)).strftime("%Y/%m/%d")

    for player_name, _ in players:
        battles = db.get_battles_since(since_ts, player_name=player_name)
        logger.info(f"[{player_name}] 週間バトル: {len(battles)} 件")

        llm_comment = analyzer.analyze(battles, week_start_str, player_name=player_name)

        try:
            discord_post.post_weekly(battles, week_start_str, llm_comment, player_name=player_name)
            logger.info(f"[{player_name}] 週次サマリー投稿完了。")
        except Exception as e:
            logger.error(f"[{player_name}] 週次サマリー投稿失敗: {e}")


if __name__ == "__main__":
    setup_logging()
    main()
