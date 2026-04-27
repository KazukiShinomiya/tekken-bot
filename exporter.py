"""
Prometheus Exporter for Tekken Bot.
battles.db を読み込み、メトリクスを HTTP 経由で公開する。

実行方法:
    python exporter.py [--port 9877]
"""

import logging
import time
import argparse
from datetime import datetime, timedelta
from typing import Any, Iterator

from prometheus_client import start_http_server, REGISTRY
from prometheus_client.core import GaugeMetricFamily

from main import setup_logging
import bot.db as db
from bot.config import EXPORTER_PORT, JST

setup_logging()
logger = logging.getLogger(__name__)


def _period_start_ts(period: str) -> int:
    now = datetime.now(JST)
    if period == "today":
        dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "7d":
        dt = now - timedelta(days=7)
    elif period == "30d":
        dt = now - timedelta(days=30)
    else:  # "all"
        return 0
    return int(dt.timestamp())


class TekkenCollector:
    def collect(self) -> Iterator[Any]:
        try:
            yield from self._collect()
        except Exception as e:
            logger.error(f"[exporter] 収集エラー: {e}")

    def _collect(self) -> Iterator[Any]:
        # ── 1. 現在レーティング ──────────────────────────────────────────
        g = GaugeMetricFamily(
            "tekken_rating_current",
            "最新バトルから算出した現在レーティング",
        )
        current_rating = db.get_current_rating()
        if current_rating is not None:
            g.add_metric([], float(current_rating))
        yield g

        # ── 2. 期間別レーティング変動 (ranked のみ) ───────────────────────
        rating_change_g = GaugeMetricFamily(
            "tekken_rating_change",
            "期間内のレーティング合計変動 (ranked)",
            labels=["period"],
        )
        for period in ("today", "7d", "30d"):
            delta = db.get_rating_delta(_period_start_ts(period))
            rating_change_g.add_metric([period], float(delta))
        yield rating_change_g

        # ── 3. 勝率 & 試合数 ─────────────────────────────────────────────
        win_rate_g = GaugeMetricFamily(
            "tekken_win_rate",
            "期間・バトルタイプ別勝率",
            labels=["period", "battle_type"],
        )
        battles_g = GaugeMetricFamily(
            "tekken_battles_total",
            "期間・バトルタイプ・勝敗別試合数",
            labels=["period", "battle_type", "result"],
        )

        for period in ("today", "7d", "30d", "all"):
            ts = _period_start_ts(period)
            for btype in ("ranked", "all"):
                wins, losses = db.get_win_loss(ts, battle_type=None if btype == "all" else btype)
                total = wins + losses
                battles_g.add_metric([period, btype, "win"],  float(wins))
                battles_g.add_metric([period, btype, "loss"], float(losses))
                if total > 0:
                    win_rate_g.add_metric([period, btype], wins / total)

        yield win_rate_g
        yield battles_g

        # ── 4. キャラ対面別勝率 (ranked, 3試合以上) ──────────────────────
        matchup_wr_g = GaugeMetricFamily(
            "tekken_matchup_win_rate",
            "対面キャラ別勝率 (ranked, 3試合以上のみ)",
            labels=["opp_chara", "period"],
        )
        matchup_n_g = GaugeMetricFamily(
            "tekken_matchup_battles",
            "対面キャラ別試合数 (ranked)",
            labels=["opp_chara", "period"],
        )

        for period in ("7d", "30d", "all"):
            rows = db.get_matchup_stats(_period_start_ts(period), min_battles=3)
            for r in rows:
                labels = [r["opp_chara"], period]
                matchup_wr_g.add_metric(labels, r["wins"] / r["total"])
                matchup_n_g.add_metric(labels, float(r["total"]))

        yield matchup_wr_g
        yield matchup_n_g

        # ── 5. 時間帯別勝率 (today / 7d) ─────────────────────────────────
        hourly_wr_g = GaugeMetricFamily(
            "tekken_hourly_win_rate",
            "JST 時間帯別勝率",
            labels=["hour", "period"],
        )
        hourly_n_g = GaugeMetricFamily(
            "tekken_hourly_battles",
            "JST 時間帯別試合数",
            labels=["hour", "period"],
        )

        for period in ("today", "7d"):
            rows = db.get_win_loss_by_hour(_period_start_ts(period))
            for r in rows:
                total = r["wins"] + r["losses"]
                labels = [str(r["hour"]), period]
                hourly_n_g.add_metric(labels, float(total))
                if total > 0:
                    hourly_wr_g.add_metric(labels, r["wins"] / total)

        yield hourly_wr_g
        yield hourly_n_g

        # ── 6. 自キャラ使用試合数 ──────────────────────────────────────────
        chara_usage_g = GaugeMetricFamily(
            "tekken_chara_usage_total",
            "期間内の自キャラ使用試合数",
            labels=["my_chara", "period"],
        )
        for period in ("7d", "30d", "all"):
            rows = db.get_my_chara_counts(_period_start_ts(period))
            for r in rows:
                chara_usage_g.add_metric([r["my_chara"], period], float(r["cnt"]))
        yield chara_usage_g

        # ── 7. LLM 評価スコア（最新値） ───────────────────────────────────
        llm_eval_g = GaugeMetricFamily(
            "tekken_llm_eval_score",
            "LLM コメントの最新評価スコア (0-100)",
        )
        latest_eval = db.get_latest_llm_eval_score()
        if latest_eval is not None:
            llm_eval_g.add_metric([], float(latest_eval))
        yield llm_eval_g

        # ── 8. 月次スナップショット ───────────────────────────────────────
        monthly_wins_g = GaugeMetricFamily(
            "tekken_monthly_wins",
            "月間勝利数",
            labels=["year_month"],
        )
        monthly_losses_g = GaugeMetricFamily(
            "tekken_monthly_losses",
            "月間敗北数",
            labels=["year_month"],
        )
        monthly_rating_g = GaugeMetricFamily(
            "tekken_monthly_rating_delta",
            "月間レーティング変動 (ranked)",
            labels=["year_month"],
        )

        snapshots = db.get_monthly_snapshots(limit=12)
        for s in snapshots:
            ym = s["year_month"]
            monthly_wins_g.add_metric([ym],   float(s["wins"]))
            monthly_losses_g.add_metric([ym],  float(s["losses"]))
            monthly_rating_g.add_metric([ym],  float(s["rating_delta"]))
        yield monthly_wins_g
        yield monthly_losses_g
        yield monthly_rating_g


def main() -> None:
    parser = argparse.ArgumentParser(description="Tekken Bot Prometheus Exporter")
    parser.add_argument("--port", type=int, default=EXPORTER_PORT)
    args = parser.parse_args()

    db.init_db()
    REGISTRY.register(TekkenCollector())
    start_http_server(args.port)
    logger.info(f"[exporter] http://0.0.0.0:{args.port}/metrics で待機中")
    logger.info(f"[exporter] DB: {db.DB_PATH}")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
