"""
SQLite によるバトル履歴の永続化モジュール。
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from bot.config import DB_PATH

logger = logging.getLogger(__name__)


def _query_battles(
    conn: sqlite3.Connection,
    where_sql: str,
    params: tuple,
    player_name: str | None,
) -> list[sqlite3.Row]:
    """
    WHERE 句に player_name フィルタを条件付きで追加して SELECT * FROM battles を実行する。
    ORDER BY battle_at は常に付与する。
    """
    if player_name is not None:
        sql = f"SELECT * FROM battles WHERE {where_sql} AND player_name = ? ORDER BY battle_at"
        return conn.execute(sql, params + (player_name,)).fetchall()
    sql = f"SELECT * FROM battles WHERE {where_sql} ORDER BY battle_at"
    return conn.execute(sql, params).fetchall()


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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chara_names (
                chara_id  INTEGER PRIMARY KEY,
                name      TEXT NOT NULL
            )
        """)

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


_INSERT_SQL = """
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
    ON CONFLICT(battle_id) DO UPDATE SET
        my_chara    = CASE WHEN my_chara  IS NULL OR my_chara  LIKE 'Chara#%'
                          THEN excluded.my_chara  ELSE my_chara  END,
        opp_chara   = CASE WHEN opp_chara IS NULL OR opp_chara LIKE 'Chara#%'
                          THEN excluded.opp_chara ELSE opp_chara END,
        my_chara_id  = COALESCE(my_chara_id,  excluded.my_chara_id),
        opp_chara_id = COALESCE(opp_chara_id, excluded.opp_chara_id),
        my_rank      = COALESCE(my_rank,  excluded.my_rank),
        my_power     = COALESCE(my_power, excluded.my_power),
        opp_rank     = COALESCE(opp_rank,  excluded.opp_rank),
        opp_power    = COALESCE(opp_power, excluded.opp_power),
        opp_rating_before  = COALESCE(opp_rating_before,  excluded.opp_rating_before),
        opp_rating_change  = COALESCE(opp_rating_change,  excluded.opp_rating_change)
"""


def insert_battles(battles: list[dict], player_name: str = "default") -> int:
    """バトルを一括挿入。既存レコードはキャラ名・未取得フィールドのみ更新する。処理件数を返す。"""
    if not battles:
        return 0
    rows = [{**b, "won": int(b["won"]), "player_name": player_name} for b in battles]
    with get_conn() as conn:
        conn.executemany(_INSERT_SQL, rows)
    return len(rows)


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
        rows = _query_battles(
            conn,
            "battle_at >= ? AND battle_at < ?",
            (int(day_start.timestamp()), int(day_end.timestamp())),
            player_name,
        )
    return [dict(r) for r in rows]


def get_battles_since(since_ts: float, player_name: str | None = None) -> list[dict]:
    """since_ts 以降の全バトルを返す（週次サマリー用）。"""
    with get_conn() as conn:
        rows = _query_battles(conn, "battle_at >= ?", (int(since_ts),), player_name)
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


def get_battles_vs_opponent(
    opp_polaris_id: str,
    since_ts: float = 0,
    player_name: str | None = None,
) -> list[dict]:
    """特定の相手(polaris_id)との過去対戦履歴を返す。"""
    with get_conn() as conn:
        rows = _query_battles(
            conn,
            "opp_polaris_id = ? AND battle_at >= ?",
            (opp_polaris_id, int(since_ts)),
            player_name,
        )
    return [dict(r) for r in rows]


def get_battles_by_opp_chara(
    opp_chara: str,
    player_name: str | None = None,
) -> list[dict]:
    """特定キャラとの全期間対戦履歴を返す（大文字小文字無視）。"""
    with get_conn() as conn:
        rows = _query_battles(conn, "LOWER(opp_chara) = LOWER(?)", (opp_chara,), player_name)
    return [dict(r) for r in rows]


def get_matchup_ranking(
    player_name: str | None = None,
    min_battles: int = 2,
) -> list[dict]:
    """全キャラとの通算対戦成績を試合数降順で返す（min_battles 以上のみ）。"""
    with get_conn() as conn:
        if player_name is not None:
            rows = conn.execute("""
                SELECT opp_chara,
                       SUM(won)  AS wins,
                       COUNT(*)  AS total
                FROM battles
                WHERE player_name = ? AND opp_chara IS NOT NULL
                GROUP BY opp_chara
                HAVING COUNT(*) >= ?
                ORDER BY total DESC, wins DESC
            """, (player_name, min_battles)).fetchall()
        else:
            rows = conn.execute("""
                SELECT opp_chara,
                       SUM(won)  AS wins,
                       COUNT(*)  AS total
                FROM battles
                WHERE opp_chara IS NOT NULL
                GROUP BY opp_chara
                HAVING COUNT(*) >= ?
                ORDER BY total DESC, wins DESC
            """, (min_battles,)).fetchall()
    return [dict(r) for r in rows]


def search_battles_vs_opponent(
    opp_name: str,
    player_name: str | None = None,
) -> list[dict]:
    """相手名（部分一致、大文字小文字無視）との対戦履歴を返す。"""
    pattern = f"%{opp_name}%"
    with get_conn() as conn:
        rows = _query_battles(conn, "LOWER(opp_name) LIKE LOWER(?)", (pattern,), player_name)
    return [dict(r) for r in rows]


def save_chara_name(chara_id: int, name: str) -> None:
    """動的に学習したキャラクター名マッピングを永続化する。"""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO chara_names (chara_id, name) VALUES (?, ?)",
            (chara_id, name),
        )


def load_chara_names() -> dict[int, str]:
    """DB に保存された動的キャラクター名マッピングを返す。"""
    with get_conn() as conn:
        try:
            rows = conn.execute("SELECT chara_id, name FROM chara_names").fetchall()
            return {r["chara_id"]: r["name"] for r in rows}
        except sqlite3.Error as e:
            logger.warning(f"[db] キャラクター名ロード失敗: {e}")
            return {}


def get_unknown_chara_battles(limit: int = 10) -> list[dict]:
    """Chara#N のままのバトルを返す（未学習キャラの検出・ログ警告用）。"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT battle_id, battle_at, my_chara, my_chara_id, opp_chara, opp_chara_id
            FROM battles
            WHERE my_chara LIKE 'Chara#%' OR opp_chara LIKE 'Chara#%'
            ORDER BY battle_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_win_loss_by_hour(since_ts: int) -> list[dict]:
    """since_ts 以降の JST 時間帯別 (hour, wins, losses) を返す。"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                CAST(strftime('%H', datetime(battle_at, 'unixepoch', '+9 hours')) AS INTEGER) AS hour,
                SUM(won)           AS wins,
                COUNT(*) - SUM(won) AS losses
            FROM battles
            WHERE battle_at >= ?
            GROUP BY hour
            ORDER BY hour
        """, (since_ts,)).fetchall()
    return [dict(r) for r in rows]
