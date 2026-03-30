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

from bot.config import (
    PLAYERS as PLAYERS_ENV, POLARIS_ID as POLARIS_ID_ENV, TEKKEN_ID as TEKKEN_ID_ENV,
    LOG_PATH, JST, TIMEOUT_LLM, TIMEOUT_API, RATING_GOAL, LOSS_ALERT_THRESHOLD,
    validate_config,
)
import bot.db as db
import bot.fetcher as fetcher
import bot.discord_post as discord_post
import bot.analyzer as analyzer
from bot.stats import count_wins, count_losses, filter_rated_battles, detect_losing_streak

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

    # リピート相手（上位3人）のスカウト情報を並列取得
    pid_count = Counter(
        b.get("opp_polaris_id") for b in today_battles if b.get("opp_polaris_id")
    )
    pids_to_scout = [pid for pid, cnt in pid_count.most_common(3) if cnt >= 2]
    scout_data: dict = {}
    if pids_to_scout:
        with ThreadPoolExecutor(max_workers=len(pids_to_scout)) as pool:
            futures = {pid: pool.submit(fetcher.fetch_opponent_summary, pid) for pid in pids_to_scout}
            for pid, future in futures.items():
                try:
                    summary = future.result(timeout=TIMEOUT_API)
                    if summary:
                        scout_data[pid] = summary
                except Exception as e:
                    logger.warning(f"[{player_name}] スカウト取得失敗 ({pid}): {e}")
    if scout_data:
        logger.info(f"[{player_name}] スカウト取得: {len(scout_data)} 人")

    # 連敗アラート（末尾から連続敗北を検出）
    if LOSS_ALERT_THRESHOLD > 0:
        sorted_today = sorted(today_battles, key=lambda x: x["battle_at"])
        streak = detect_losing_streak(sorted_today)
        if streak >= LOSS_ALERT_THRESHOLD:
            discord_post.notify(
                f"⚠️ [{player_name}] 現在 **{streak} 連敗中** です。少し休憩しましょう！"
            )
            logger.info(f"[{player_name}] 連敗アラート送信: {streak} 連敗")

    # 目標レーティング達成通知
    if RATING_GOAL > 0:
        rated_today = [b for b in today_battles if b.get("rating_before") is not None and b.get("rating_change") is not None]
        if rated_today:
            latest_rated = max(rated_today, key=lambda x: x["battle_at"])
            current_rating = latest_rated["rating_before"] + latest_rated["rating_change"]
            if current_rating >= RATING_GOAL:
                discord_post.notify(
                    f"🎉 [{player_name}] 目標レーティング **{RATING_GOAL:,}** 達成！現在: **{current_rating:,}**"
                )
                logger.info(f"[{player_name}] 目標レーティング達成通知: {current_rating}")

    # Discord に即時投稿（LLM コメントなし）
    post_result = None
    try:
        post_result = discord_post.post(
            today_battles, date_str,
            player_name=player_name,
            scout_data=scout_data or None,
        )
        logger.info(f"[{player_name}] 投稿完了。")
    except Exception as e:
        logger.error(f"[{player_name}] Discord 投稿失敗: {e}")

    # LLM 分析（投稿後に実行することで Discord でのレスポンスタイムを改善）
    llm_comment = _analyze_with_timeout(
        today_battles, date_str, player_name=player_name,
        prev_battles=prev_battles, rematch_data=rematch_data or None,
    )

    # LLM コメントを Embed フッターとして追記
    if llm_comment and post_result:
        message_ids, embed = post_result
        discord_post.edit_llm_comment(message_ids, embed, llm_comment)
        logger.info(f"[{player_name}] LLMコメント追記完了。")


async def main(target_date: str | None = None) -> None:
    """
    target_date: 対象日を 'YYYY-MM-DD' 形式で指定。None の場合は前日（スケジューラ 08:00 実行用）。
    スラッシュコマンドからは今日の日付を渡す。
    """
    if not _main_lock.acquire(blocking=False):
        logger.warning("main() は既に実行中のためスキップ")
        return
    try:
        now = datetime.now(JST)
        logger.info(f"Tekken Bot 起動 {now.isoformat()}")

        config_errors = validate_config()
        if config_errors:
            for err in config_errors:
                logger.error(f"設定エラー: {err}")
            sys.exit(1)

        db.init_db()
        fetcher.load_learned_chara_names()

        players = get_players()
        if not players:
            logger.error("プレイヤーが設定されていません。PLAYERS または POLARIS_ID を .env に設定してください。")
            sys.exit(1)

        if target_date is not None:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=JST)
            today_str = target_date
            date_str  = target_dt.strftime("%Y/%m/%d")
        else:
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


def _run_weekly_for_player(
    player_name: str,
    since_ts: float,
    week_start_str: str,
) -> dict:
    """1プレイヤー分の週次サマリー処理（DB取得・LLM・投稿）。community_stats エントリを返す。"""
    battles = db.get_battles_since(since_ts, player_name=player_name)
    logger.info(f"[{player_name}] 週間バトル: {len(battles)} 件")

    # Discord に即時投稿（LLM コメントなし）
    post_result = None
    try:
        post_result = discord_post.post_weekly(battles, week_start_str, player_name=player_name)
        logger.info(f"[{player_name}] 週次サマリー投稿完了。")
    except Exception as e:
        msg = f"[{player_name}] 週次サマリー投稿失敗: {e}"
        logger.error(msg)
        discord_post.notify_error(msg)

    # LLM 分析（投稿後）
    llm_comment = _analyze_with_timeout(battles, week_start_str, player_name=player_name)

    # LLM コメントを Embed フッターとして追記
    if llm_comment and post_result:
        message_ids, embed = post_result
        discord_post.edit_llm_comment(message_ids, embed, llm_comment)
        logger.info(f"[{player_name}] 週次LLMコメント追記完了。")

    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    rated  = filter_rated_battles(ranked)
    return {
        "name":       player_name,
        "wins":       count_wins(battles),
        "losses":     count_losses(battles),
        "net_rating": sum(b["rating_change"] for b in rated) if rated else 0,
    }


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

        since_ts       = (now - timedelta(days=7)).timestamp()
        week_start_str = (now - timedelta(days=6)).strftime("%Y/%m/%d")

        # 複数プレイヤーを並列処理
        results = await asyncio.gather(*(
            asyncio.to_thread(_run_weekly_for_player, name, since_ts, week_start_str)
            for name, _ in players
        ), return_exceptions=True)

        community_stats = [r for r in results if isinstance(r, dict)]

        # 2人以上のとき部内ランキングを投稿
        discord_post.post_community_weekly(community_stats, week_start_str)
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
