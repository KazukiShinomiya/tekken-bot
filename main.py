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
    LOG_PATH, JST, TIMEOUT_LLM, TIMEOUT_API, RATING_GOAL, RANK_NAMES,
    normalize_rank, validate_config,
)
import bot.db as db
import bot.fetcher as fetcher
import bot.discord_post as discord_post
import bot.analyzer as analyzer
from bot.models import Battle
from bot.stats import count_wins, count_losses, filter_rated_battles, get_most_common

logger = logging.getLogger(__name__)

# スケジューラとスラッシュコマンドの同時実行を防ぐロック
_main_lock    = threading.Lock()
_weekly_lock  = threading.Lock()
_monthly_lock = threading.Lock()


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


def _compute_opponent_data(
    today_battles: list[Battle],
    player_name: str,
) -> tuple[dict, list[str]]:
    """
    今日の対戦相手データを一元計算する。
    Counter を1回だけ作成し、rematch_data と pids_to_scout を同時に返す。
    """
    pid_count: Counter[str] = Counter(
        pid
        for b in today_battles
        if (pid := b.get("opp_polaris_id")) is not None
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

    pids_to_scout = [
        pid for pid, cnt in pid_count.most_common(3)
        if cnt >= 2
    ]
    return rematch_data, pids_to_scout


def _fetch_scout_data(
    pids_to_scout: list[str],
    player_name: str,
) -> dict:
    """スカウト対象の対戦相手サマリーを並列取得する。"""
    if not pids_to_scout:
        return {}

    scout_data: dict = {}
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
    return scout_data


def _fire_alerts(
    today_battles: list[Battle],
    prev_battles: list[Battle],
    player_name: str,
) -> None:
    """目標レーティング達成通知を送信する。目標は DB 優先・env var フォールバック。"""
    goal = db.get_goal(player_name) or RATING_GOAL
    if goal > 0:
        rated_today = [
            b for b in today_battles
            if b.get("rating_before") is not None and b.get("rating_change") is not None
        ]
        if rated_today:
            latest_rated = max(rated_today, key=lambda x: x["battle_at"])
            current_rating = (latest_rated.get("rating_before") or 0) + (latest_rated.get("rating_change") or 0)
            if current_rating >= goal:
                prev_rated = [
                    b for b in prev_battles
                    if b.get("rating_before") is not None and b.get("rating_change") is not None
                ]
                prev_rating = 0
                if prev_rated:
                    prev_latest = max(prev_rated, key=lambda x: x["battle_at"])
                    prev_rating = (prev_latest.get("rating_before") or 0) + (prev_latest.get("rating_change") or 0)
                if prev_rating < goal:
                    discord_post.notify(
                        f"🎉 [{player_name}] 目標レーティング **{goal:,}** 達成！現在: **{current_rating:,}**"
                    )
                    logger.info(f"[{player_name}] 目標レーティング達成通知: {current_rating}")


def _fire_rank_alerts(today_battles: list[Battle], today_str: str, player_name: str) -> None:
    """段位変化を検知して Discord に通知する。"""
    if not today_battles:
        return
    latest = max(today_battles, key=lambda x: x["battle_at"])
    # ewgf.gg 由来は英語段位名で入るため段位番号へ正規化してから比較する
    current_rank = normalize_rank(latest.get("my_rank"))
    if current_rank is None:
        return
    prev_rank = db.get_last_rank_before_date(today_str, player_name=player_name)
    if prev_rank is None or prev_rank == current_rank:
        return
    prev_name = RANK_NAMES.get(prev_rank, f"Rank{prev_rank}")
    curr_name = RANK_NAMES.get(current_rank, f"Rank{current_rank}")
    discord_post.post_rank_change(player_name, prev_rank, current_rank)
    logger.info(f"[{player_name}] 段位変化: {prev_name} → {curr_name}")


def _analyze_with_timeout(
    battles: list[Battle],
    date_str: str,
    player_name: str = "",
    prev_battles: list[Battle] | None = None,
    rematch_data: dict | None = None,
    high_score_comments: list[str] | None = None,
    prev_comment: str | None = None,
) -> str | None:
    """
    LLM 分析を別スレッドで実行し、TIMEOUT_LLM 秒以内に結果を返す。
    タイムアウト時は None を返し、スレッドはバックグラウンドで終了させる。
    （with ブロックの shutdown(wait=True) ではなく明示的に wait=False で解放する）
    """
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(
        analyzer.analyze, battles, date_str,
        player_name, prev_battles, rematch_data, high_score_comments, prev_comment,
    )
    try:
        result = future.result(timeout=TIMEOUT_LLM)
        pool.shutdown(wait=False)
        return result
    except FutureTimeoutError:
        future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        logger.warning(f"[{player_name}] LLM分析タイムアウト（{TIMEOUT_LLM}s）、スキップ")
        discord_post.notify_error(f"[{player_name}] LLM分析タイムアウト（投稿は続行）")
        return None
    except Exception as e:
        pool.shutdown(wait=False)
        logger.warning(f"[{player_name}] LLM分析失敗: {e}")
        return None


def _save_eval_score(today_str: str, player_name: str, score: int, comment: str) -> None:
    """LLM 評価スコアを DB に保存する。失敗しても処理は止めない。"""
    try:
        db.save_llm_eval_score(today_str, player_name, score, comment)
        logger.info(f"[{player_name}] LLM評価スコア: {score}/100")
    except Exception as e:
        logger.warning(f"[{player_name}] LLM評価スコア保存失敗: {e}")


def _generate_validated_comment(
    today_battles: list[Battle],
    date_str: str,
    today_str: str,
    player_name: str,
    prev_battles: list[Battle],
    rematch_data: dict,
    high_score_comments: list[str],
    prev_comment: str | None,
) -> tuple[str | None, dict | None]:
    """LLM コメントを生成し、投稿前に品質ゲートを通す。

    未対戦キャラへの言及（ハルシネーション）を検出したら1回だけ再生成し、
    それでも残る場合はコメントを破棄する（スコアは観測用に記録だけ残す）。
    評価器自体の失敗ではコメントを止めない（Fail Gracefully）。

    Returns:
        (投稿するコメント or None, その評価結果 or None)
    """
    from bot.evaluator import evaluate_comment

    def generate() -> str | None:
        return _analyze_with_timeout(
            today_battles, date_str, player_name=player_name,
            prev_battles=prev_battles, rematch_data=rematch_data or None,
            high_score_comments=high_score_comments or None,
            prev_comment=prev_comment,
        )

    comment = generate()
    if not comment:
        return None, None
    try:
        result = evaluate_comment(comment, today_battles)
    except Exception as e:
        logger.warning(f"[{player_name}] LLM評価失敗（コメントはそのまま採用）: {e}")
        return comment, None

    hallucinated = result["details"]["chara_valid"]["hallucinated"]
    if not hallucinated:
        return comment, result

    logger.warning(
        f"[{player_name}] 未対戦キャラへの言及を検出（{', '.join(hallucinated)}）。再生成する。"
    )
    comment = generate()
    if not comment:
        return None, None
    try:
        result = evaluate_comment(comment, today_battles)
    except Exception as e:
        logger.warning(f"[{player_name}] LLM評価失敗（コメントはそのまま採用）: {e}")
        return comment, None

    hallucinated = result["details"]["chara_valid"]["hallucinated"]
    if hallucinated:
        logger.warning(
            f"[{player_name}] 再生成後も未対戦キャラへの言及が残存（{', '.join(hallucinated)}）。"
            "コメントを破棄する。"
        )
        _save_eval_score(today_str, player_name, result["score"], comment)
        return None, None
    return comment, result


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

    # 新規バトルがなく既に投稿済みなら重複投稿しない
    if inserted == 0 and db.has_posted_today(today_str, player_name=player_name):
        logger.info(f"[{player_name}] 新規バトルなし・投稿済みのためスキップ。")
        return

    prev_date_str = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_battles  = db.get_battles_on_date(prev_date_str, player_name=player_name)
    logger.info(f"[{player_name}] 前日分: {len(prev_battles)} 件")

    # 対戦相手データをまとめて計算（Counter は1回のみ）
    rematch_data, pids_to_scout = _compute_opponent_data(today_battles, player_name)
    logger.info(f"[{player_name}] リピート対戦相手: {len(rematch_data)} 人")

    scout_data = _fetch_scout_data(pids_to_scout, player_name)

    # 目標レーティング・段位変化アラート
    _fire_alerts(today_battles, prev_battles, player_name)
    _fire_rank_alerts(today_battles, today_str, player_name)

    # Discord に即時投稿（LLM コメントなし）
    post_result = None
    try:
        post_result = discord_post.post(
            today_battles, date_str,
            player_name=player_name,
            scout_data=scout_data or None,
        )
        if post_result:
            db.mark_posted_today(today_str, player_name=player_name)
        logger.info(f"[{player_name}] 投稿完了。")
    except Exception as e:
        logger.error(f"[{player_name}] Discord 投稿失敗: {e}")

    # LLM 分析（投稿後に実行することで Discord でのレスポンスタイムを改善）
    # DB から高スコアコメントを few-shot として、前回コメントを継続コーチング用に取得する
    high_score_comments = db.get_high_score_comments(player_name=player_name)
    today_start_ts = datetime.strptime(today_str, "%Y-%m-%d").replace(tzinfo=JST).timestamp()
    prev_comment = db.get_latest_comment_before(today_start_ts, player_name=player_name)
    if prev_comment:
        logger.info(f"[{player_name}] 前回コメントを継続コーチング用に取得: {len(prev_comment)}文字")
    llm_comment, eval_result = _generate_validated_comment(
        today_battles, date_str, today_str, player_name,
        prev_battles, rematch_data, high_score_comments, prev_comment,
    )

    # LLM コメントを Embed フッターとして追記
    if llm_comment and post_result:
        message_ids, embed = post_result
        discord_post.edit_llm_comment(message_ids, embed, llm_comment)
        logger.info(f"[{player_name}] LLMコメント追記完了。")

    # LLM コメントの品質評価スコアをDBに保存
    if llm_comment and eval_result:
        _save_eval_score(today_str, player_name, eval_result["score"], llm_comment)


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

        # 未学習キャラ(Chara#N)の残存チェック
        unknown_chara = db.get_unknown_chara_battles()
        if unknown_chara:
            ids = ", ".join(
                f"ID={r['my_chara_id'] or r['opp_chara_id']} ({r['my_chara'] or r['opp_chara']})"
                for r in unknown_chara[:5]
            )
            logger.warning(f"[main] 未学習キャラが {len(unknown_chara)} 件存在: {ids}")

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

        # 日次バックアップ（全プレイヤー処理後）
        try:
            dest = db.backup_db()
            logger.info(f"[main] DB バックアップ完了: {dest.name}")
        except Exception as e:
            logger.warning(f"[main] DB バックアップ失敗: {e}")

        # 死活監視の心拍を刻む（正常完了時のみ）
        db.record_run_success("daily")
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

    # 前週（[since_ts-7日, since_ts)）を前週比用に取得
    prev_battles = db.get_battles_between(
        since_ts - 7 * 86400, since_ts, player_name=player_name
    )
    logger.info(f"[{player_name}] 前週バトル: {len(prev_battles)} 件")

    # Discord に即時投稿（LLM コメントなし）
    post_result = None
    try:
        post_result = discord_post.post_weekly(
            battles, week_start_str, player_name=player_name, prev_battles=prev_battles
        )
        logger.info(f"[{player_name}] 週次サマリー投稿完了。")
    except Exception as e:
        msg = f"[{player_name}] 週次サマリー投稿失敗: {e}"
        logger.error(msg)
        discord_post.notify_error(msg)

    # LLM 分析（投稿後）。コーチングが意味を持つのは真剣勝負のランク戦のみ。
    # ランク戦が無ければ Ollama 呼び出し自体をスキップする。
    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    llm_comment = None
    if ranked:
        # since_ts より前の最新コメントを継続コーチング用に取得する
        prev_comment = db.get_latest_comment_before(since_ts, player_name=player_name)
        if prev_comment:
            logger.info(f"[{player_name}] 週次: 前回コメントを取得: {len(prev_comment)}文字")
        llm_comment = _analyze_with_timeout(
            ranked, week_start_str, player_name=player_name, prev_comment=prev_comment,
        )

    # LLM コメントをランク戦 Embed の冒頭へ追記（post_result はランク戦投稿）
    if llm_comment and post_result:
        message_ids, embed = post_result
        discord_post.edit_llm_comment(message_ids, embed, llm_comment)
        logger.info(f"[{player_name}] 週次LLMコメント追記完了。")

    rated  = filter_rated_battles(ranked)
    return {
        "name":       player_name,
        "wins":       count_wins(battles),
        "losses":     count_losses(battles),
        "net_rating": sum(b.get("rating_change") or 0 for b in rated) if rated else 0,
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

        # 当週の月曜0時JST起算（月〜日の標準週）
        days_since_monday = now.weekday()  # 月=0 … 日=6
        week_start = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        since_ts       = week_start.timestamp()
        week_start_str = week_start.strftime("%Y/%m/%d")

        # 複数プレイヤーを並列処理
        results = await asyncio.gather(*(
            asyncio.to_thread(_run_weekly_for_player, name, since_ts, week_start_str)
            for name, _ in players
        ), return_exceptions=True)

        community_stats = [r for r in results if isinstance(r, dict)]

        # 2人以上のとき部内ランキングを投稿
        discord_post.post_community_weekly(community_stats, week_start_str)

        # 死活監視の心拍を刻む（正常完了時のみ）
        db.record_run_success("weekly")
    finally:
        _weekly_lock.release()


def _run_monthly_for_player(
    player_name: str,
    year: int,
    month: int,
    month_str: str,
) -> None:
    """1プレイヤー分の月次サマリー処理（DB取得・LLM・投稿）。"""
    battles = db.get_battles_in_month(year, month, player_name=player_name)
    logger.info(f"[{player_name}] 月間バトル ({month_str}): {len(battles)} 件")

    prev_year  = year - 1 if month == 1 else year
    prev_month = 12       if month == 1 else month - 1
    prev_battles = db.get_battles_in_month(prev_year, prev_month, player_name=player_name)

    post_result = None
    try:
        post_result = discord_post.post_monthly(
            battles, month_str,
            player_name=player_name,
            prev_battles=prev_battles or None,
        )
        logger.info(f"[{player_name}] 月次サマリー投稿完了。")
    except Exception as e:
        msg = f"[{player_name}] 月次サマリー投稿失敗: {e}"
        logger.error(msg)
        discord_post.notify_error(msg)

    llm_comment = _analyze_with_timeout(battles, month_str, player_name=player_name)

    if llm_comment and post_result:
        message_ids, embed = post_result
        discord_post.edit_llm_comment(message_ids, embed, llm_comment)
        logger.info(f"[{player_name}] 月次LLMコメント追記完了。")

    # 月次スナップショットをDBに保存（Prometheus exporter / Grafana 用）
    try:
        ranked = [b for b in battles if b.get("battle_type") == "ranked"]
        rated  = filter_rated_battles(ranked)
        rating_delta = sum(b.get("rating_change") or 0 for b in rated)
        end_power: int | None = None
        power_battles = [b for b in sorted(battles, key=lambda x: x["battle_at"])
                         if b.get("my_power") is not None]
        if power_battles:
            end_power = power_battles[-1]["my_power"]
        top_chara, _ = get_most_common(battles, "my_chara")
        year_month = f"{year:04d}-{month:02d}"
        db.upsert_monthly_snapshot(
            year_month, player_name,
            count_wins(battles), count_losses(battles),
            rating_delta, end_power,
            top_chara if top_chara != "???" else None,
        )
        logger.info(f"[{player_name}] 月次スナップショット保存完了 ({year_month})")
    except Exception as e:
        logger.warning(f"[{player_name}] 月次スナップショット保存失敗: {e}")


async def monthly(month: str | None = None) -> None:
    """
    月次サマリーを全プレイヤー分投稿する。
    month: 'YYYY-MM' 形式（省略時は先月）。スラッシュコマンドから月指定も可。
    """
    if not _monthly_lock.acquire(blocking=False):
        logger.warning("monthly() は既に実行中のためスキップ")
        return
    try:
        now = datetime.now(JST)
        logger.info(f"Tekken Bot 月次サマリー開始 {now.isoformat()}")

        db.init_db()
        fetcher.load_learned_chara_names()

        players = get_players()
        if not players:
            logger.warning("プレイヤーが設定されていません。月次サマリーをスキップ。")
            return

        if month is not None:
            dt           = datetime.strptime(month, "%Y-%m").replace(tzinfo=JST)
            target_year  = dt.year
            target_month = dt.month
        else:
            first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month     = first_of_month - timedelta(days=1)
            target_year    = last_month.year
            target_month   = last_month.month

        month_str = f"{target_year}年{target_month}月"

        await asyncio.gather(*(
            asyncio.to_thread(_run_monthly_for_player, name, target_year, target_month, month_str)
            for name, _ in players
        ))

        # 死活監視の心拍を刻む（正常完了時のみ）
        db.record_run_success("monthly")
    finally:
        _monthly_lock.release()


def run_main_sync() -> None:
    """スケジューラ・スラッシュコマンドから呼ぶ同期エントリポイント。"""
    asyncio.run(main())


def run_weekly_sync() -> None:
    """スケジューラ・スラッシュコマンドから呼ぶ同期エントリポイント（週次）。"""
    asyncio.run(weekly())


def run_monthly_sync() -> None:
    """スケジューラ・スラッシュコマンドから呼ぶ同期エントリポイント（月次）。"""
    asyncio.run(monthly())


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
