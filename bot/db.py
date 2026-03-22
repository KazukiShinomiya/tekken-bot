"""
SQLite によるバトル履歴の永続化モジュール。
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bot.config import DB_PATH

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """テーブルがなければ作成し、マイグレーションを適用する。"""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS battles (
                -- 識別
                battle_id         TEXT PRIMARY KEY,
                battle_at         INTEGER NOT NULL,
                battle_type       TEXT,       -- "ranked" / "quick" / "player"
                game_version      TEXT,       -- パッチバージョン
                stage_id          INTEGER,    -- ステージID
                source            TEXT,       -- "wank_bulk" / "ewgf" / "wank_html"

                -- 自分側
                won               INTEGER NOT NULL,  -- 1=勝, 0=負
                my_chara          TEXT,
                my_chara_id       INTEGER,
                my_rounds         INTEGER,
                my_rank           INTEGER,
                my_power          INTEGER,
                my_region         TEXT,
                rating_before     INTEGER,
                rating_change     INTEGER,

                -- 相手側
                opp_name          TEXT,
                opp_polaris_id    TEXT,
                opp_chara         TEXT,
                opp_chara_id      INTEGER,
                opp_rounds        INTEGER,
                opp_rank          INTEGER,
                opp_power         INTEGER,
                opp_region        TEXT,
                opp_rating_before INTEGER,
                opp_rating_change INTEGER,

                -- プレイヤー識別
                player_name       TEXT DEFAULT 'default'
            )
        """)

        # マイグレーション: player_name カラムが既存テーブルにない場合は追加
        cols = {row[1] for row in conn.execute("PRAGMA table_info(battles)")}
        if "player_name" not in cols:
            conn.execute("ALTER TABLE battles ADD COLUMN player_name TEXT DEFAULT 'default'")
            logger.info("[db] マイグレーション: player_name カラムを追加")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_battle_at ON battles(battle_at)"
        )
        # 列が存在する場合のみインデックスを作成（レガシーDBマイグレーション対応）
        cols = {row[1] for row in conn.execute("PRAGMA table_info(battles)")}
        if "battle_type" in cols:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_battle_type ON battles(battle_type)"
            )
        if "player_name" in cols:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_player_name ON battles(player_name)"
            )


def insert_battles(battles: list[dict], player_name: str = "default") -> int:
    """新規バトルを挿入。重複はスキップ。挿入件数を返す。"""
    inserted = 0
    with get_conn() as conn:
        for b in battles:
            try:
                conn.execute("""
                    INSERT INTO battles (
                        battle_id, battle_at, battle_type, game_version, stage_id, source,
                        won, my_chara, my_chara_id, my_rounds, my_rank, my_power, my_region,
                        rating_before, rating_change,
                        opp_name, opp_polaris_id, opp_chara, opp_chara_id,
                        opp_rounds, opp_rank, opp_power, opp_region,
                        opp_rating_before, opp_rating_change,
                        player_name
                    ) VALUES (
                        :battle_id, :battle_at, :battle_type, :game_version, :stage_id, :source,
                        :won, :my_chara, :my_chara_id, :my_rounds, :my_rank, :my_power, :my_region,
                        :rating_before, :rating_change,
                        :opp_name, :opp_polaris_id, :opp_chara, :opp_chara_id,
                        :opp_rounds, :opp_rank, :opp_power, :opp_region,
                        :opp_rating_before, :opp_rating_change,
                        :player_name
                    )
                """, {**b, "won": int(b["won"]), "player_name": player_name})
                inserted += 1
            except sqlite3.IntegrityError:
                pass  # 重複スキップ
    return inserted


def get_latest_battle_at(player_name: str | None = None) -> float:
    """DB内の最新バトルのタイムスタンプを返す。なければ 0。"""
    with get_conn() as conn:
        if player_name is not None:
            row = conn.execute(
                "SELECT MAX(battle_at) AS m FROM battles WHERE player_name = ?",
                (player_name,),
            ).fetchone()
        else:
            row = conn.execute("SELECT MAX(battle_at) AS m FROM battles").fetchone()
        return float(row["m"]) if row["m"] is not None else 0.0


def get_battles_on_date(
    date_str: str,
    tz_offset_hours: int = 9,
    player_name: str | None = None,
) -> list[dict]:
    """指定日（JST、'YYYY-MM-DD' 形式）のバトルを返す。"""
    tz = timezone(timedelta(hours=tz_offset_hours))
    day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    with get_conn() as conn:
        if player_name is not None:
            rows = conn.execute(
                "SELECT * FROM battles WHERE battle_at >= ? AND battle_at < ? AND player_name = ? ORDER BY battle_at",
                (int(day_start.timestamp()), int(day_end.timestamp()), player_name),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM battles WHERE battle_at >= ? AND battle_at < ? ORDER BY battle_at",
                (int(day_start.timestamp()), int(day_end.timestamp())),
            ).fetchall()
    return [dict(r) for r in rows]


def get_battles_since(since_ts: float, player_name: str | None = None) -> list[dict]:
    """since_ts 以降の全バトルを返す（週次サマリー用）。"""
    with get_conn() as conn:
        if player_name is not None:
            rows = conn.execute(
                "SELECT * FROM battles WHERE battle_at >= ? AND player_name = ? ORDER BY battle_at",
                (int(since_ts), player_name),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM battles WHERE battle_at >= ? ORDER BY battle_at",
                (int(since_ts),),
            ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Prometheus Exporter 用集計クエリ
# ---------------------------------------------------------------------------

def get_current_rating() -> int | None:
    """最新バトルから現在レーティングを返す。なければ None。"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT rating_before + rating_change AS current_rating
            FROM battles
            WHERE rating_before IS NOT NULL AND rating_change IS NOT NULL
            ORDER BY battle_at DESC
            LIMIT 1
        """).fetchone()
    return int(row["current_rating"]) if row else None


def get_rating_delta(since_ts: int) -> int:
    """since_ts 以降のランク戦レーティング合計変動を返す。"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COALESCE(SUM(rating_change), 0) AS delta
            FROM battles
            WHERE battle_at >= ? AND battle_type = 'ranked'
              AND rating_change IS NOT NULL
        """, (since_ts,)).fetchone()
    return int(row["delta"]) if row else 0


def get_win_loss(since_ts: int, battle_type: str | None = None) -> tuple[int, int]:
    """since_ts 以降の (勝数, 敗数) を返す。battle_type=None で全種別。"""
    with get_conn() as conn:
        if battle_type is None:
            rows = conn.execute("""
                SELECT won, COUNT(*) AS cnt
                FROM battles WHERE battle_at >= ?
                GROUP BY won
            """, (since_ts,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT won, COUNT(*) AS cnt
                FROM battles WHERE battle_at >= ? AND battle_type = ?
                GROUP BY won
            """, (since_ts, battle_type)).fetchall()
    wins   = next((r["cnt"] for r in rows if r["won"]),     0)
    losses = next((r["cnt"] for r in rows if not r["won"]), 0)
    return wins, losses


def get_matchup_stats(since_ts: int, min_battles: int = 3) -> list[dict]:
    """since_ts 以降のランク戦キャラ対面別集計を返す（min_battles 以上のみ）。"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT opp_chara,
                   SUM(won)  AS wins,
                   COUNT(*)  AS total
            FROM battles
            WHERE battle_at >= ? AND battle_type = 'ranked'
              AND opp_chara IS NOT NULL
            GROUP BY opp_chara
            HAVING COUNT(*) >= ?
        """, (since_ts, min_battles)).fetchall()
    return [dict(r) for r in rows]
