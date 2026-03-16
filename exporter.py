"""
Prometheus Exporter for Tekken Bot.
battles.db を読み込み、メトリクスを HTTP 経由で公開する。

実行方法:
    python exporter.py [--port 9877]
"""

import logging
import sys
import time
import sqlite3
import argparse
from datetime import datetime, timezone, timedelta

from prometheus_client import start_http_server, REGISTRY
from prometheus_client.core import GaugeMetricFamily

from main import setup_logging
import bot.db as db
from bot.config import EXPORTER_PORT

setup_logging()
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DB_PATH = db.DB_PATH


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
    def collect(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            yield from self._collect(conn)
            conn.close()
        except Exception as e:
            logger.error(f"[exporter] 収集エラー: {e}")

    def _collect(self, conn):
        # ── 1. 現在レーティング ──────────────────────────────────────────
        row = conn.execute("""
            SELECT rating_before + rating_change AS current_rating
            FROM battles
            WHERE rating_before IS NOT NULL AND rating_change IS NOT NULL
            ORDER BY battle_at DESC
            LIMIT 1
        """).fetchone()

        g = GaugeMetricFamily(
            "tekken_rating_current",
            "最新バトルから算出した現在レーティング",
        )
        if row:
            g.add_metric([], float(row["current_rating"]))
        yield g

        # ── 2. 期間別レーティング変動 (ranked のみ) ───────────────────────
        rating_change_g = GaugeMetricFamily(
            "tekken_rating_change",
            "期間内のレーティング合計変動 (ranked)",
            labels=["period"],
        )
        for period in ("today", "7d", "30d"):
            row = conn.execute("""
                SELECT COALESCE(SUM(rating_change), 0) AS delta
                FROM battles
                WHERE battle_at >= ? AND battle_type = 'ranked'
                  AND rating_change IS NOT NULL
            """, (_period_start_ts(period),)).fetchone()
            if row:
                rating_change_g.add_metric([period], float(row["delta"]))
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
                if btype == "all":
                    rows = conn.execute("""
                        SELECT won, COUNT(*) AS cnt
                        FROM battles WHERE battle_at >= ?
                        GROUP BY won
                    """, (ts,)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT won, COUNT(*) AS cnt
                        FROM battles WHERE battle_at >= ? AND battle_type = ?
                        GROUP BY won
                    """, (ts, btype)).fetchall()

                wins   = next((r["cnt"] for r in rows if r["won"]),      0)
                losses = next((r["cnt"] for r in rows if not r["won"]),  0)
                total  = wins + losses

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
            rows = conn.execute("""
                SELECT opp_chara,
                       SUM(won)  AS wins,
                       COUNT(*)  AS total
                FROM battles
                WHERE battle_at >= ? AND battle_type = 'ranked'
                  AND opp_chara IS NOT NULL
                GROUP BY opp_chara
                HAVING COUNT(*) >= 3
            """, (_period_start_ts(period),)).fetchall()

            for r in rows:
                labels = [r["opp_chara"], period]
                matchup_wr_g.add_metric(labels, r["wins"] / r["total"])
                matchup_n_g.add_metric(labels, float(r["total"]))

        yield matchup_wr_g
        yield matchup_n_g


def main():
    parser = argparse.ArgumentParser(description="Tekken Bot Prometheus Exporter")
    parser.add_argument("--port", type=int, default=EXPORTER_PORT)
    args = parser.parse_args()

    db.init_db()
    REGISTRY.register(TekkenCollector())
    start_http_server(args.port)
    logger.info(f"[exporter] http://0.0.0.0:{args.port}/metrics で待機中")
    logger.info(f"[exporter] DB: {DB_PATH}")

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
