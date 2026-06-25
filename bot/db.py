"""
SQLite によるバトル履歴の永続化モジュール。
"""

import json
import sqlite3
import logging
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import cast

from bot.config import DB_PATH
from bot.models import Battle

logger = logging.getLogger(__name__)


def _player_filter(player_name: str | None) -> tuple[str, tuple]:
    """player_name フィルタ用の WHERE 条件フラグメントとパラメータを返す。
    戻り値を f-string の WHERE 句末尾に挿入し、params に結合して使う。
    例: sql = f"SELECT ... WHERE col = ? {pf}", params + pp
    """
    if player_name is not None:
        return "AND player_name = ?", (player_name,)
    return "", ()


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
    pf, pp = _player_filter(player_name)
    sql = f"SELECT * FROM battles WHERE {where_sql} {pf} ORDER BY battle_at"
    return conn.execute(sql, params + pp).fetchall()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """接続を確実に閉じるコンテキストマネージャ。

    `with conn:` はトランザクションの commit/rollback を行うだけで接続自体は
    閉じない（sqlite3 の仕様）。ここで内側に `with conn:` を抱えつつ
    finally で close することで、従来の commit/rollback 意味論を保ったまま
    接続リーク（GC まで開きっぱなし）を断つ。呼び出し側は変更不要。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_posts (
                date_str    TEXT NOT NULL,
                player_name TEXT NOT NULL DEFAULT 'default',
                posted_at   INTEGER NOT NULL,
                PRIMARY KEY (date_str, player_name)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS scout_cache (
                polaris_id TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                cached_at  INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                player_name   TEXT PRIMARY KEY,
                target_rating INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_eval_scores (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date_str    TEXT    NOT NULL,
                player_name TEXT    NOT NULL DEFAULT 'default',
                score       INTEGER NOT NULL,
                saved_at    INTEGER NOT NULL,
                comment     TEXT
            )
        """)
        # 既存 DB へのカラム追加（冪等）
        try:
            conn.execute("ALTER TABLE llm_eval_scores ADD COLUMN comment TEXT")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS monthly_snapshots (
                year_month   TEXT NOT NULL,
                player_name  TEXT NOT NULL DEFAULT 'default',
                wins         INTEGER NOT NULL DEFAULT 0,
                losses       INTEGER NOT NULL DEFAULT 0,
                rating_delta INTEGER NOT NULL DEFAULT 0,
                end_power    INTEGER,
                top_chara    TEXT,
                saved_at     INTEGER NOT NULL,
                PRIMARY KEY (year_month, player_name)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_status (
                job_name        TEXT PRIMARY KEY,   -- "daily" / "weekly" / "monthly"
                last_success_at INTEGER NOT NULL    -- UTC epoch 秒
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


def insert_battles(battles: list[Battle], player_name: str = "default") -> int:
    """バトルを一括挿入。既存レコードはキャラ名・未取得フィールドのみ更新する。処理件数を返す。"""
    if not battles:
        return 0
    rows = [{**b, "won": int(b["won"]), "player_name": player_name} for b in battles]
    with get_conn() as conn:
        conn.executemany(_INSERT_SQL, rows)
    return len(rows)


def get_latest_battle_at(player_name: str | None = None) -> float:
    """DB内の最新バトルのタイムスタンプを返す。なければ 0。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT MAX(battle_at) AS m FROM battles WHERE 1=1 {pf}", pp
        ).fetchone()
    return float(row["m"]) if row["m"] is not None else 0.0


def get_battles_on_date(
    date_str: str,
    tz_offset_hours: int = 9,
    player_name: str | None = None,
) -> list[Battle]:
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
    return cast(list[Battle], [dict(r) for r in rows])


def get_battles_since(since_ts: float, player_name: str | None = None) -> list[Battle]:
    """since_ts 以降の全バトルを返す（週次サマリー用）。"""
    with get_conn() as conn:
        rows = _query_battles(conn, "battle_at >= ?", (int(since_ts),), player_name)
    return cast(list[Battle], [dict(r) for r in rows])


def get_battles_between(
    start_ts: float, end_ts: float, player_name: str | None = None
) -> list[Battle]:
    """[start_ts, end_ts) の半開区間のバトルを返す（前週比など期間比較用）。"""
    with get_conn() as conn:
        rows = _query_battles(
            conn, "battle_at >= ? AND battle_at < ?", (int(start_ts), int(end_ts)), player_name
        )
    return cast(list[Battle], [dict(r) for r in rows])


# ---------------------------------------------------------------------------
# 死活監視（ジョブ正常完了の心拍）
# ---------------------------------------------------------------------------

def record_run_success(job_name: str, ts: int | None = None) -> None:
    """ジョブ（daily/weekly/monthly）の正常完了時刻を UTC epoch で記録する。

    exporter が `tekken_last_success_timestamp` として公開し、一定時間更新が
    途絶えたら Bot 停止とみなしてアラートを発火させるための心拍。
    """
    if ts is None:
        ts = int(datetime.now(timezone.utc).timestamp())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO run_status (job_name, last_success_at) VALUES (?, ?) "
            "ON CONFLICT(job_name) DO UPDATE SET last_success_at = excluded.last_success_at",
            (job_name, ts),
        )


def get_run_status() -> list[dict]:
    """全ジョブの最終正常完了時刻を返す（exporter 用）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT job_name, last_success_at FROM run_status ORDER BY job_name"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Prometheus Exporter 用集計クエリ
# ---------------------------------------------------------------------------

def get_current_rating(player_name: str | None = None) -> int | None:
    """最新バトルから現在レーティングを返す。なければ None。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        row = conn.execute(f"""
            SELECT rating_before + rating_change AS current_rating
            FROM battles
            WHERE rating_before IS NOT NULL AND rating_change IS NOT NULL {pf}
            ORDER BY battle_at DESC
            LIMIT 1
        """, pp).fetchone()
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
    btf = "AND battle_type = ?" if battle_type is not None else ""
    btp = (battle_type,) if battle_type is not None else ()
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT won, COUNT(*) AS cnt
            FROM battles WHERE battle_at >= ? {btf}
            GROUP BY won
        """, (since_ts,) + btp).fetchall()
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
) -> list[Battle]:
    """特定の相手(polaris_id)との過去対戦履歴を返す。"""
    with get_conn() as conn:
        rows = _query_battles(
            conn,
            "opp_polaris_id = ? AND battle_at >= ?",
            (opp_polaris_id, int(since_ts)),
            player_name,
        )
    return cast(list[Battle], [dict(r) for r in rows])


def get_battles_by_opp_chara(
    opp_chara: str,
    player_name: str | None = None,
    since_ts: int = 0,
) -> list[Battle]:
    """特定キャラとの対戦履歴を返す（大文字小文字無視）。since_ts > 0 の場合は期間絞り込みあり。"""
    where = "LOWER(opp_chara) = LOWER(?)"
    params: tuple = (opp_chara,)
    if since_ts > 0:
        where += " AND battle_at >= ?"
        params += (since_ts,)
    with get_conn() as conn:
        rows = _query_battles(conn, where, params, player_name)
    return cast(list[Battle], [dict(r) for r in rows])


def get_matchup_ranking(
    player_name: str | None = None,
    min_battles: int = 2,
) -> list[dict]:
    """全キャラとの通算対戦成績を試合数降順で返す（min_battles 以上のみ）。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT opp_chara,
                   SUM(won)  AS wins,
                   COUNT(*)  AS total
            FROM battles
            WHERE opp_chara IS NOT NULL {pf}
            GROUP BY opp_chara
            HAVING COUNT(*) >= ?
            ORDER BY total DESC, wins DESC
        """, pp + (min_battles,)).fetchall()
    return [dict(r) for r in rows]


def search_battles_vs_opponent(
    opp_name: str,
    player_name: str | None = None,
) -> list[Battle]:
    """相手名（部分一致、大文字小文字無視）との対戦履歴を返す。"""
    pattern = f"%{opp_name}%"
    with get_conn() as conn:
        rows = _query_battles(conn, "LOWER(opp_name) LIKE LOWER(?)", (pattern,), player_name)
    return cast(list[Battle], [dict(r) for r in rows])


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


def get_known_opp_charas() -> list[str]:
    """battles テーブルに存在する対戦相手キャラ名（distinct）を返す。オートコンプリート用。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT opp_chara FROM battles WHERE opp_chara IS NOT NULL ORDER BY opp_chara"
        ).fetchall()
    return [r["opp_chara"] for r in rows]


def has_posted_today(date_str: str, player_name: str = "default") -> bool:
    """指定日・プレイヤーがすでに投稿済みかを返す。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM daily_posts WHERE date_str = ? AND player_name = ?",
            (date_str, player_name),
        ).fetchone()
    return row is not None


def mark_posted_today(date_str: str, player_name: str = "default") -> None:
    """指定日・プレイヤーを投稿済みとしてマーク。"""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_posts (date_str, player_name, posted_at) VALUES (?, ?, ?)",
            (date_str, player_name, int(datetime.now(timezone.utc).timestamp())),
        )


def get_my_chara_counts(since_ts: int, player_name: str | None = None) -> list[dict]:
    """since_ts 以降の自キャラ別使用試合数を返す（Prometheus メトリクス用）。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT my_chara, COUNT(*) AS cnt
            FROM battles
            WHERE my_chara IS NOT NULL AND battle_at >= ? {pf}
            GROUP BY my_chara ORDER BY cnt DESC
        """, (since_ts,) + pp).fetchall()
    return [dict(r) for r in rows]


def backup_db(keep: int = 7) -> Path:
    """
    SQLite オンラインバックアップを data/backups/ に作成する。
    keep 件より古いバックアップは自動削除する。
    """
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    dest = backup_dir / f"battles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(dest)) as dst:
        src.backup(dst)

    backups = sorted(backup_dir.glob("battles_*.db"))
    for old in backups[:-keep]:
        old.unlink(missing_ok=True)

    logger.info(f"[db] バックアップ完了: {dest.name}（保持 {min(len(backups), keep)} 件）")
    return dest


def get_weekly_my_chara_counts(
    weeks: int = 8,
    player_name: str | None = None,
) -> list[dict]:
    """過去 N 週の JST 週別・自キャラ使用数を返す（週次グラフ用）。"""
    since_ts = int((datetime.now(timezone.utc) - timedelta(weeks=weeks)).timestamp())
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT
                strftime('%Y-W%W', datetime(battle_at, 'unixepoch', '+9 hours')) AS week,
                my_chara,
                COUNT(*) AS cnt
            FROM battles
            WHERE my_chara IS NOT NULL AND battle_at >= ? {pf}
            GROUP BY week, my_chara
            ORDER BY week, cnt DESC
        """, (since_ts,) + pp).fetchall()
    return [dict(r) for r in rows]


def get_scout_cache(polaris_id: str, ttl_seconds: int = 21600) -> dict | None:
    """スカウトキャッシュを返す（TTL内ならキャッシュデータ、期限切れ・未登録なら None）。
    テーブル未作成（テスト環境等）は OperationalError を握りつぶして None を返す。
    """
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT data, cached_at FROM scout_cache WHERE polaris_id = ?",
                (polaris_id,),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    age = int(datetime.now(timezone.utc).timestamp()) - row["cached_at"]
    if age > ttl_seconds:
        return None
    return cast(dict, json.loads(row["data"]))


def set_scout_cache(polaris_id: str, data: dict) -> None:
    """スカウトキャッシュを保存・更新する。テーブル未作成時は静かにスキップ。"""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scout_cache (polaris_id, data, cached_at) VALUES (?, ?, ?)",
                (polaris_id, json.dumps(data), int(datetime.now(timezone.utc).timestamp())),
            )
    except sqlite3.OperationalError as e:
        logger.warning(f"[db] スカウトキャッシュ保存失敗（テーブル未作成?）: {e}")


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


def get_last_rank_before_date(date_str: str, player_name: str | None = None) -> int | None:
    """指定日より前の最新バトルの my_rank を返す。なければ None。"""
    tz = timezone(timedelta(hours=9))
    day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        row = conn.execute(f"""
            SELECT my_rank FROM battles
            WHERE battle_at < ? AND my_rank IS NOT NULL {pf}
            ORDER BY battle_at DESC LIMIT 1
        """, (int(day_start.timestamp()),) + pp).fetchone()
    return int(row["my_rank"]) if row else None


def get_battles_in_month(year: int, month: int, player_name: str | None = None) -> list[Battle]:
    """指定月（JST）のバトルを返す。"""
    tz = timezone(timedelta(hours=9))
    month_start = datetime(year, month, 1, tzinfo=tz)
    next_year  = year + 1 if month == 12 else year
    next_month = 1       if month == 12 else month + 1
    month_end  = datetime(next_year, next_month, 1, tzinfo=tz)
    with get_conn() as conn:
        rows = _query_battles(
            conn,
            "battle_at >= ? AND battle_at < ?",
            (int(month_start.timestamp()), int(month_end.timestamp())),
            player_name,
        )
    return cast(list[Battle], [dict(r) for r in rows])


def get_personal_records(player_name: str | None = None) -> dict:
    """全期間の個人最高記録を返す。データなしなら空 dict。"""
    with get_conn() as conn:
        rows = _query_battles(conn, "1=1", (), player_name)
    battles = cast(list[Battle], [dict(r) for r in rows])
    if not battles:
        return {}

    sorted_b = sorted(battles, key=lambda b: b["battle_at"])
    total = len(battles)
    wins  = sum(1 for b in battles if b["won"])

    first_dt = datetime.fromtimestamp(sorted_b[0]["battle_at"],
                                       timezone(timedelta(hours=9))).strftime("%Y/%m/%d")

    # 最高レーティング
    max_rating: int | None = None
    max_rating_date: str | None = None
    for b in sorted_b:
        if b.get("rating_before") is not None and b.get("rating_change") is not None:
            r = (b["rating_before"] or 0) + (b["rating_change"] or 0)
            if max_rating is None or r > max_rating:
                max_rating = r
                max_rating_date = datetime.fromtimestamp(
                    b["battle_at"], timezone(timedelta(hours=9))
                ).strftime("%Y/%m/%d")

    # 最長連勝・連敗（時系列順に走査）
    max_win = max_lose = cur_win = cur_lose = 0
    best_win_start = best_win_end = best_lose_start = best_lose_end = None
    cur_win_start: str | None = None
    cur_lose_start: str | None = None

    for b in sorted_b:
        dt_str = datetime.fromtimestamp(
            b["battle_at"], timezone(timedelta(hours=9))
        ).strftime("%Y/%m/%d")
        if b["won"]:
            cur_win += 1
            if cur_win == 1:
                cur_win_start = dt_str
            cur_lose = 0
            cur_lose_start = None
            if cur_win > max_win:
                max_win = cur_win
                best_win_start = cur_win_start
                best_win_end = dt_str
        else:
            cur_lose += 1
            if cur_lose == 1:
                cur_lose_start = dt_str
            cur_win = 0
            cur_win_start = None
            if cur_lose > max_lose:
                max_lose = cur_lose
                best_lose_start = cur_lose_start
                best_lose_end = dt_str

    return {
        "total":           total,
        "wins":            wins,
        "losses":          total - wins,
        "first_date":      first_dt,
        "max_rating":      max_rating,
        "max_rating_date": max_rating_date,
        "max_win_streak":  max_win,
        "max_win_start":   best_win_start,
        "max_win_end":     best_win_end,
        "max_lose_streak": max_lose,
        "max_lose_start":  best_lose_start,
        "max_lose_end":    best_lose_end,
    }


def get_stage_stats(
    player_name: str | None = None,
    min_battles: int = 2,
) -> list[dict]:
    """ステージ別の勝敗集計を返す（stage_id IS NOT NULL かつ min_battles 以上のみ）。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT stage_id,
                   SUM(won)  AS wins,
                   COUNT(*)  AS total
            FROM battles
            WHERE stage_id IS NOT NULL {pf}
            GROUP BY stage_id
            HAVING COUNT(*) >= ?
            ORDER BY total DESC
        """, pp + (min_battles,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# goal CRUD
# ---------------------------------------------------------------------------

def get_goal(player_name: str = "default") -> int | None:
    """プレイヤーの目標レーティングを返す。未設定なら None。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT target_rating FROM goals WHERE player_name = ?", (player_name,)
        ).fetchone()
    return int(row["target_rating"]) if row else None


def set_goal(player_name: str, target_rating: int) -> None:
    """プレイヤーの目標レーティングを保存・更新する。"""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO goals (player_name, target_rating) VALUES (?, ?)",
            (player_name, target_rating),
        )


def clear_goal(player_name: str) -> None:
    """プレイヤーの目標レーティングを削除する。"""
    with get_conn() as conn:
        conn.execute("DELETE FROM goals WHERE player_name = ?", (player_name,))


# ---------------------------------------------------------------------------
# LLM eval score
# ---------------------------------------------------------------------------

def save_llm_eval_score(
    date_str: str, player_name: str, score: int, comment: str | None = None
) -> None:
    """LLM コメントの評価スコアを保存する。"""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO llm_eval_scores (date_str, player_name, score, saved_at, comment)"
            " VALUES (?, ?, ?, ?, ?)",
            (date_str, player_name, score, int(datetime.now(timezone.utc).timestamp()), comment),
        )


def get_latest_comment_before(before_ts: float, player_name: str | None = None) -> str | None:
    """before_ts より前に保存された最新の LLM コメントを返す（継続コーチング用）。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        row = conn.execute(f"""
            SELECT comment FROM llm_eval_scores
            WHERE saved_at < ? AND comment IS NOT NULL {pf}
            ORDER BY saved_at DESC, id DESC LIMIT 1
        """, (int(before_ts),) + pp).fetchone()
    return row["comment"] if row else None


def get_high_score_comments(
    player_name: str | None = None, min_score: int = 80, limit: int = 3
) -> list[str]:
    """高スコア（min_score 以上）の LLM コメントを新しい順で最大 limit 件返す。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT comment FROM llm_eval_scores
            WHERE score >= ? AND comment IS NOT NULL {pf}
            ORDER BY score DESC, saved_at DESC
            LIMIT ?
        """, (min_score,) + pp + (limit,)).fetchall()
    return [r["comment"] for r in rows]


def get_llm_eval_scores(player_name: str | None = None, days: int = 30) -> list[dict]:
    """直近 N 日の LLM 評価スコア一覧を返す（新しい順）。"""
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT date_str, score, saved_at
            FROM llm_eval_scores
            WHERE saved_at >= ? {pf}
            ORDER BY saved_at DESC
        """, (since_ts,) + pp).fetchall()
    return [dict(r) for r in rows]


def get_latest_llm_eval_score(player_name: str | None = None) -> int | None:
    """最新の LLM 評価スコアを返す（Prometheus exporter 用）。なければ None。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        row = conn.execute(f"""
            SELECT score FROM llm_eval_scores
            WHERE 1=1 {pf}
            ORDER BY saved_at DESC, id DESC LIMIT 1
        """, pp).fetchone()
    return int(row["score"]) if row else None


# ---------------------------------------------------------------------------
# monthly snapshot
# ---------------------------------------------------------------------------

def upsert_monthly_snapshot(
    year_month: str,
    player_name: str,
    wins: int,
    losses: int,
    rating_delta: int,
    end_power: int | None,
    top_chara: str | None,
) -> None:
    """月次スナップショットを保存・更新する（year_month='YYYY-MM'）。"""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO monthly_snapshots
                (year_month, player_name, wins, losses, rating_delta, end_power, top_chara, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            year_month, player_name, wins, losses, rating_delta,
            end_power, top_chara,
            int(datetime.now(timezone.utc).timestamp()),
        ))


def get_monthly_snapshots(
    player_name: str | None = None,
    limit: int = 12,
) -> list[dict]:
    """月次スナップショットを新しい順で最大 limit 件返す。"""
    pf, pp = _player_filter(player_name)
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT year_month, wins, losses, rating_delta, end_power, top_chara
            FROM monthly_snapshots
            WHERE 1=1 {pf}
            ORDER BY year_month DESC
            LIMIT ?
        """, pp + (limit,)).fetchall()
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
