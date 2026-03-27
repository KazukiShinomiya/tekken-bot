"""
Tekken Bot メインスクリプト。
バトルを取得して DB に保存し、当日分を Discord に投稿する。

実行方法:
    python main.py
"""

import asyncio
import logging
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from bot.config import PLAYERS as PLAYERS_ENV, POLARIS_ID as POLARIS_ID_ENV, TEKKEN_ID as TEKKEN_ID_ENV, LOG_PATH, JST, TIMEOUT_LLM
import bot.db as db
import bot.fetcher as fetcher
import bot.discord_post as discord_post
import bot.analyzer as analyzer

logger = logging.getLogger(__name__)

# スケジューラとスラッシュコマンドの同時実行を防ぐロック
_main_lock = threading.Lock()
_weekly_lock = threading.Lock()


def setup_logging() -> None:
    """RotatingFileHandler + StreamHandler でロギングを設定する。"""
    log_path = Path(LOG_PATH)
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
    if PLAYERS_ENV:
        result = []
        for entry in PLAYERS_ENV.split(","):
            entry = entry.strip()
            if ":" not in entry:
                continue
            name, pid = entry.split(":", 1)
            result.append((name.strip(), pid.strip()))
        return result

    # 後方互換: 単一プレイヤー設定
    if POLARIS_ID_ENV:
        return [(TEKKEN_ID_ENV or "default", POLARIS_ID_ENV)]
    return []


def _collect_rematch_data(
    today_battles: list[dict],
    player_name: str,
) -> dict:
    """今日2戦以上した相手の通算成績を DB から収集する。"""
    pid_count: Counter = Counter(
        b.get("opp_polaris_id") for b in today_battles if b.get("opp_polaris_id")
    )
    rematch_data: dict = {}
    for pid, cnt in pid_count.items():
        if cnt < 2:
            continue
        history = db.get_battles_vs_opponent(pid, player_name=player_name)
        if history:
            sample = next(b for b in today_battles if b.get("opp_polaris_id") == pid)
            rematch_data[pid] = {
                "name":    sample.get("opp_name")  or "???",
                "chara":   sample.get("opp_chara") or "???",
                "history": history,
            }
    return rematch_data


def _analyze_with_timeout(
    battles: list[dict],
    date_str: str,
    player_name: str = "",
    prev_battles: list[dict] | None = None,
    rematch_data: dict | None = None,
) -> str | None:
    """LLM 分析を別スレッドで実行し、TIMEOUT_LLM 秒以内に結果を返す。タイムアウト時は None。"""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            analyzer.analyze, battles, date_str,
            player_name, prev_battles, rematch_data,
        )
        try:
            return future.result(timeout=TIMEOUT_LLM)
        except FutureTimeoutError:
            logger.warning(f"[{player_name}] LLM分析タイムアウト（{TIMEOUT_LLM}s）、スキップ")
            discord_post.notify_error(f"[{player_name}] LLM分析タイムアウト（投稿は続行）")
            return None
        except Exception as e:
            logger.warning(f"[{player_name}] LLM分析失敗: {e}")
            return None


def _run_for_player(player_name: str, polaris_id: str, today_str: str, date_str: str) -> None:
    """1プレイヤー分のバトル取得・保存・投稿を実行する。"""
    logger.info(f"[{player_name}] 処理開始")

    since_ts = db.get_latest_battle_at(player_name=player_name)
    logger.info(f"[{player_name}] 前回の最終バトル: "
                f"{datetime.fromtimestamp(since_ts, JST).isoformat() if since_ts else '（初回）'}")

    try:
        new_battles = fetcher.fetch_battles_since(since_ts, polaris_id=polaris_id)
    except Exception as e:
        msg = f"[{player_name}] データ取得失敗: {e}"
        logger.error(msg)
        discord_post.notify_error(msg)
        return

    inserted = db.insert_battles(new_battles, player_name=player_name)
    logger.info(f"[{player_name}] {inserted} 件を DB に保存")

    # ewgf.gg からクイックマッチを補完（24時間遅延のため日次投稿には使わず週次サマリー用）
    quick_battles = fetcher.fetch_quick_battles_from_ewgf(since_ts, polaris_id=polaris_id)
    if quick_battles:
        inserted_quick = db.insert_battles(quick_battles, player_name=player_name)
        logger.info(f"[{player_name}] クイックマッチ {inserted_quick} 件を DB に保存 (ewgf.gg)")

    today_battles = db.get_battles_on_date(today_str, player_name=player_name)
    logger.info(f"[{player_name}] 本日分: {len(today_battles)} 件")

    if not today_battles:
        logger.info(f"[{player_name}] 本日の試合なし。投稿をスキップ。")
        return

    prev_date_str = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_battles  = db.get_battles_on_date(prev_date_str, player_name=player_name)
    logger.info(f"[{player_name}] 前日分: {len(prev_battles)} 件")

    rematch_data = _collect_rematch_data(today_battles, player_name)
    logger.info(f"[{player_name}] リピート対戦相手: {len(rematch_data)} 人")

    llm_comment = _analyze_with_timeout(
        today_battles, date_str, player_name=player_name,
        prev_battles=prev_battles, rematch_data=rematch_data or None,
    )

    try:
        discord_post.post(today_battles, date_str, llm_comment, player_name=player_name)
        logger.info(f"[{player_name}] 投稿完了。")
    except Exception as e:
        logger.error(f"[{player_name}] Discord 投稿失敗: {e}")


async def main() -> None:
    if not _main_lock.acquire(blocking=False):
        logger.warning("main() は既に実行中のためスキップ")
        return
    try:
        now = datetime.now(JST)
        logger.info(f"Tekken Bot 起動 {now.isoformat()}")

        db.init_db()
        fetcher.load_learned_chara_names()

        players = get_players()
        if not players:
            logger.error("プレイヤーが設定されていません。PLAYERS または POLARIS_ID を .env に設定してください。")
            sys.exit(1)

        yesterday = now - timedelta(days=1)
        today_str = yesterday.strftime("%Y-%m-%d")
        date_str  = yesterday.strftime("%Y/%m/%d")

        # 複数プレイヤーを並列処理
        await asyncio.gather(*(
            asyncio.to_thread(_run_for_player, name, pid, today_str, date_str)
            for name, pid in players
        ))
    finally:
        _main_lock.release()


async def weekly() -> None:
    """週次サマリーを全プレイヤー分投稿する（日曜 JST 21:00 実行想定）。"""
    if not _weekly_lock.acquire(blocking=False):
        logger.warning("weekly() は既に実行中のためスキップ")
        return
    try:
        now = datetime.now(JST)
        logger.info(f"Tekken Bot 週次サマリー開始 {now.isoformat()}")

        db.init_db()
        fetcher.load_learned_chara_names()

        players = get_players()
        if not players:
            logger.warning("プレイヤーが設定されていません。週次サマリーをスキップ。")
            return

        since_ts = (now - timedelta(days=7)).timestamp()
        week_start_str = (now - timedelta(days=6)).strftime("%Y/%m/%d")

        for player_name, _ in players:
            battles = db.get_battles_since(since_ts, player_name=player_name)
            logger.info(f"[{player_name}] 週間バトル: {len(battles)} 件")

            llm_comment = _analyze_with_timeout(battles, week_start_str, player_name=player_name)

            try:
                discord_post.post_weekly(battles, week_start_str, llm_comment, player_name=player_name)
                logger.info(f"[{player_name}] 週次サマリー投稿完了。")
            except Exception as e:
                msg = f"[{player_name}] 週次サマリー投稿失敗: {e}"
                logger.error(msg)
                discord_post.notify_error(msg)
    finally:
        _weekly_lock.release()


def run_main_sync() -> None:
    """スケジューラ・スラッシュコマンドから呼ぶ同期エントリポイント。"""
    asyncio.run(main())


def run_weekly_sync() -> None:
    """スケジューラ・スラッシュコマンドから呼ぶ同期エントリポイント（週次）。"""
    asyncio.run(weekly())


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
