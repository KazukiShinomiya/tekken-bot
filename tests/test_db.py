"""
bot/db.py のテスト（インメモリ SQLite を使用）。
"""

import pytest
from datetime import datetime
from pathlib import Path

from bot.config import JST


def _make_battle(
    battle_id: str = "test_1",
    battle_at: int = 1700000000,
    won: bool = True,
    opp_chara: str = "Jin",
    my_chara: str = "Reina",
    battle_type: str = "ranked",
    rating_before: int | None = None,
    rating_change: int | None = None,
) -> dict:
    return {
        "battle_id":         battle_id,
        "battle_at":         battle_at,
        "battle_type":       battle_type,
        "game_version":      None,
        "stage_id":          None,
        "source":            "test",
        "won":               won,
        "my_chara":          my_chara,
        "my_chara_id":       None,
        "my_rounds":         2,
        "my_rank":           None,
        "my_power":          None,
        "my_region":         None,
        "rating_before":     rating_before,
        "rating_change":     rating_change,
        "opp_name":          "TestOpp",
        "opp_polaris_id":    "opp_pid",
        "opp_chara":         opp_chara,
        "opp_chara_id":      None,
        "opp_rounds":        1,
        "opp_rank":          None,
        "opp_power":         None,
        "opp_region":        None,
        "opp_rating_before": None,
        "opp_rating_change": None,
    }


@pytest.fixture
def db(tmp_path, monkeypatch):
    """テスト用の一時 DB を持つ db モジュールを返す。"""
    import bot.db as _db
    monkeypatch.setattr(_db, "DB_PATH", tmp_path / "test.db")
    _db.init_db()
    return _db


def test_init_db_creates_table(db):
    """init_db() が battles テーブルを作成することを確認。"""
    with db.get_conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='battles'"
        ).fetchall()
    assert len(tables) == 1


def test_init_db_adds_player_name_column(db):
    """player_name カラムが存在することを確認。"""
    with db.get_conn() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(battles)")}
    assert "player_name" in cols


def test_insert_battles_returns_count(db):
    battles = [_make_battle("b1"), _make_battle("b2")]
    count = db.insert_battles(battles, player_name="Alice")
    assert count == 2


def test_insert_battles_dedup(db):
    """同じ battle_id を2回挿入しても2件目はスキップされる。"""
    battle = _make_battle("dup_1")
    count1 = db.insert_battles([battle], player_name="Alice")
    count2 = db.insert_battles([battle], player_name="Alice")
    assert count1 == 1
    assert count2 == 0


def test_insert_battles_stores_player_name(db):
    db.insert_battles([_make_battle("b1")], player_name="Alice")
    with db.get_conn() as conn:
        row = conn.execute("SELECT player_name FROM battles WHERE battle_id = 'b1'").fetchone()
    assert row["player_name"] == "Alice"


def test_get_latest_battle_at_empty(db):
    assert db.get_latest_battle_at() == 0.0


def test_get_latest_battle_at_returns_max(db):
    db.insert_battles([
        _make_battle("b1", battle_at=1000),
        _make_battle("b2", battle_at=2000),
    ])
    assert db.get_latest_battle_at() == 2000.0


def test_get_latest_battle_at_filtered_by_player(db):
    db.insert_battles([_make_battle("b1", battle_at=1000)], player_name="Alice")
    db.insert_battles([_make_battle("b2", battle_at=3000)], player_name="Bob")
    assert db.get_latest_battle_at(player_name="Alice") == 1000.0
    assert db.get_latest_battle_at(player_name="Bob") == 3000.0


def test_get_battles_on_date(db):
    # 2024-01-15 JST 12:00 = UTC 03:00 = timestamp 1705284000
    jst_noon = datetime(2024, 1, 15, 12, 0, 0, tzinfo=JST)
    ts = int(jst_noon.timestamp())

    db.insert_battles([_make_battle("b1", battle_at=ts)])
    result = db.get_battles_on_date("2024-01-15")
    assert len(result) == 1
    assert result[0]["battle_id"] == "b1"


def test_get_battles_on_date_excludes_other_day(db):
    jst_noon_15 = datetime(2024, 1, 15, 12, 0, 0, tzinfo=JST)
    jst_noon_16 = datetime(2024, 1, 16, 12, 0, 0, tzinfo=JST)
    db.insert_battles([
        _make_battle("b1", battle_at=int(jst_noon_15.timestamp())),
        _make_battle("b2", battle_at=int(jst_noon_16.timestamp())),
    ])
    result = db.get_battles_on_date("2024-01-15")
    assert len(result) == 1
    assert result[0]["battle_id"] == "b1"


def test_get_battles_on_date_player_filter(db):
    ts = int(datetime(2024, 1, 15, 12, 0, 0, tzinfo=JST).timestamp())
    db.insert_battles([_make_battle("b1", battle_at=ts)], player_name="Alice")
    db.insert_battles([_make_battle("b2", battle_at=ts)], player_name="Bob")

    alice = db.get_battles_on_date("2024-01-15", player_name="Alice")
    bob   = db.get_battles_on_date("2024-01-15", player_name="Bob")
    assert len(alice) == 1 and alice[0]["battle_id"] == "b1"
    assert len(bob)   == 1 and bob[0]["battle_id"] == "b2"


def test_get_battles_since(db):
    db.insert_battles([
        _make_battle("b1", battle_at=1000),
        _make_battle("b2", battle_at=2000),
        _make_battle("b3", battle_at=3000),
    ])
    result = db.get_battles_since(since_ts=1500)
    ids = [r["battle_id"] for r in result]
    assert "b1" not in ids
    assert "b2" in ids
    assert "b3" in ids


def test_get_battles_since_player_filter(db):
    """player_name を指定すると、そのプレイヤーのバトルのみ返る。"""
    db.insert_battles([_make_battle("a1", battle_at=2000)], player_name="Alice")
    db.insert_battles([_make_battle("b1", battle_at=3000)], player_name="Bob")

    alice = db.get_battles_since(1000, player_name="Alice")
    bob   = db.get_battles_since(1000, player_name="Bob")

    assert len(alice) == 1 and alice[0]["battle_id"] == "a1"
    assert len(bob)   == 1 and bob[0]["battle_id"]   == "b1"


def test_migration_adds_player_name(tmp_path, monkeypatch):
    """
    player_name カラムがないテーブルに対して init_db() が
    マイグレーションを実行することを確認。
    """
    import sqlite3
    import bot.db as _db

    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(_db, "DB_PATH", db_path)

    # player_name なしで古いテーブルを作成
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE battles (
            battle_id TEXT PRIMARY KEY,
            battle_at INTEGER NOT NULL,
            won INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # init_db() を実行してマイグレーション
    _db.init_db()

    with _db.get_conn() as c:
        cols = {row[1] for row in c.execute("PRAGMA table_info(battles)")}
    assert "player_name" in cols
