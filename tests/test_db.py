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


def test_init_db_creates_chara_names_table(db):
    """init_db() が chara_names テーブルを作成することを確認。"""
    with db.get_conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chara_names'"
        ).fetchall()
    assert len(tables) == 1


def test_save_and_load_chara_name(db):
    """save_chara_name / load_chara_names の往復テスト。"""
    db.save_chara_name(99, "TestChar")
    result = db.load_chara_names()
    assert result[99] == "TestChar"


def test_save_chara_name_upsert(db):
    """同じ ID を2回 save しても最新値で上書きされる。"""
    db.save_chara_name(99, "OldName")
    db.save_chara_name(99, "NewName")
    result = db.load_chara_names()
    assert result[99] == "NewName"


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
    """同じ battle_id を2回挿入しても ON CONFLICT DO UPDATE で処理される。レコードは1件。"""
    battle = _make_battle("dup_1")
    count1 = db.insert_battles([battle], player_name="Alice")
    count2 = db.insert_battles([battle], player_name="Alice")
    assert count1 == 1
    assert count2 == 1
    with db.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM battles WHERE battle_id='dup_1'").fetchone()
    assert row[0] == 1


def test_insert_battles_chara_update(db):
    """Chara#N のキャラ名は再挿入時に実名で上書きされる。確定済みの名前は保護される。"""
    unknown = _make_battle("upd_1", my_chara="Chara#99", opp_chara="Chara#7")
    db.insert_battles([unknown], player_name="Alice")

    # 実名で再挿入 → 上書きされる
    known = _make_battle("upd_1", my_chara="Lee", opp_chara="Bryan")
    db.insert_battles([known], player_name="Alice")
    with db.get_conn() as conn:
        row = conn.execute("SELECT my_chara, opp_chara FROM battles WHERE battle_id='upd_1'").fetchone()
    assert row["my_chara"] == "Lee"
    assert row["opp_chara"] == "Bryan"

    # 未知名で再挿入 → 確定済みは保護される
    db.insert_battles([unknown], player_name="Alice")
    with db.get_conn() as conn:
        row = conn.execute("SELECT my_chara, opp_chara FROM battles WHERE battle_id='upd_1'").fetchone()
    assert row["my_chara"] == "Lee"
    assert row["opp_chara"] == "Bryan"


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


# ---------------------------------------------------------------------------
# 集計関数テスト
# ---------------------------------------------------------------------------

def test_get_current_rating_none_when_empty(db):
    assert db.get_current_rating() is None


def test_get_current_rating_returns_latest(db):
    db.insert_battles([
        _make_battle("b1", battle_at=1000, rating_before=10000, rating_change=50),
        _make_battle("b2", battle_at=2000, rating_before=10050, rating_change=-30),
    ])
    assert db.get_current_rating() == 10020  # 10050 + (-30)


def test_get_current_rating_skips_none(db):
    """rating_before/change が NULL のバトルは無視される。"""
    db.insert_battles([
        _make_battle("b1", battle_at=1000),                               # rating なし
        _make_battle("b2", battle_at=2000, rating_before=9000, rating_change=100),
    ])
    assert db.get_current_rating() == 9100


def test_get_rating_delta_zero_when_empty(db):
    assert db.get_rating_delta(0) == 0


def test_get_rating_delta_sums_ranked_only(db):
    db.insert_battles([
        _make_battle("b1", battle_at=1000, battle_type="ranked", rating_change=50),
        _make_battle("b2", battle_at=2000, battle_type="ranked", rating_change=-30),
        _make_battle("b3", battle_at=3000, battle_type="quick",  rating_change=999),  # 除外
    ])
    assert db.get_rating_delta(0) == 20  # 50 + (-30)


def test_get_rating_delta_respects_since_ts(db):
    db.insert_battles([
        _make_battle("b1", battle_at=1000, battle_type="ranked", rating_change=50),
        _make_battle("b2", battle_at=3000, battle_type="ranked", rating_change=100),
    ])
    assert db.get_rating_delta(2000) == 100  # b1 は除外


def test_get_win_loss_all_types(db):
    db.insert_battles([
        _make_battle("b1", won=True,  battle_type="ranked"),
        _make_battle("b2", won=True,  battle_type="quick"),
        _make_battle("b3", won=False, battle_type="ranked"),
    ])
    wins, losses = db.get_win_loss(0)
    assert wins == 2
    assert losses == 1


def test_get_win_loss_ranked_only(db):
    db.insert_battles([
        _make_battle("b1", won=True,  battle_type="ranked"),
        _make_battle("b2", won=True,  battle_type="quick"),
        _make_battle("b3", won=False, battle_type="ranked"),
    ])
    wins, losses = db.get_win_loss(0, battle_type="ranked")
    assert wins == 1
    assert losses == 1


def test_get_win_loss_empty(db):
    assert db.get_win_loss(0) == (0, 0)


def test_get_matchup_stats_returns_ranked_only(db):
    db.insert_battles([
        _make_battle("b1", won=True,  opp_chara="Jin",  battle_type="ranked"),
        _make_battle("b2", won=True,  opp_chara="Jin",  battle_type="ranked"),
        _make_battle("b3", won=True,  opp_chara="Jin",  battle_type="ranked"),
        _make_battle("b4", won=False, opp_chara="Jin",  battle_type="quick"),  # 除外
    ])
    rows = db.get_matchup_stats(0, min_battles=3)
    assert len(rows) == 1
    assert rows[0]["opp_chara"] == "Jin"
    assert rows[0]["wins"] == 3
    assert rows[0]["total"] == 3


def test_get_matchup_stats_min_battles_filter(db):
    db.insert_battles([
        _make_battle("b1", opp_chara="Jin",    battle_type="ranked"),
        _make_battle("b2", opp_chara="Jin",    battle_type="ranked"),
        _make_battle("b3", opp_chara="Reina",  battle_type="ranked"),  # 1戦のみ
    ])
    rows = db.get_matchup_stats(0, min_battles=2)
    charas = [r["opp_chara"] for r in rows]
    assert "Jin" in charas
    assert "Reina" not in charas


def test_get_matchup_stats_empty(db):
    assert db.get_matchup_stats(0) == []


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


# ---------------------------------------------------------------------------
# has_posted_today / mark_posted_today
# ---------------------------------------------------------------------------

def test_has_posted_today_false_initially(db):
    assert db.has_posted_today("2024-01-15", "Alice") is False


def test_mark_and_has_posted_today(db):
    db.mark_posted_today("2024-01-15", "Alice")
    assert db.has_posted_today("2024-01-15", "Alice") is True


def test_has_posted_today_different_player(db):
    db.mark_posted_today("2024-01-15", "Alice")
    assert db.has_posted_today("2024-01-15", "Bob") is False


def test_has_posted_today_different_date(db):
    db.mark_posted_today("2024-01-15", "Alice")
    assert db.has_posted_today("2024-01-16", "Alice") is False


def test_mark_posted_today_idempotent(db):
    """2回呼んでもエラーにならない（INSERT OR REPLACE）。"""
    db.mark_posted_today("2024-01-15", "Alice")
    db.mark_posted_today("2024-01-15", "Alice")
    assert db.has_posted_today("2024-01-15", "Alice") is True


# ---------------------------------------------------------------------------
# get_battles_vs_opponent
# ---------------------------------------------------------------------------

def test_get_battles_vs_opponent_basic(db):
    """指定 polaris_id との対戦履歴を返す。"""
    b1 = _make_battle(battle_id="a1"); b1["opp_polaris_id"] = "pid_target"
    b2 = _make_battle(battle_id="a2"); b2["opp_polaris_id"] = "pid_other"
    db.insert_battles([b1, b2], "Alice")
    result = db.get_battles_vs_opponent("pid_target")
    assert len(result) == 1
    assert result[0]["battle_id"] == "a1"


def test_get_battles_vs_opponent_player_filter(db):
    """player_name フィルタが機能する。"""
    b1 = _make_battle(battle_id="b1"); b1["opp_polaris_id"] = "pid_x"
    b2 = _make_battle(battle_id="b2"); b2["opp_polaris_id"] = "pid_x"
    db.insert_battles([b1], "Alice")
    db.insert_battles([b2], "Bob")
    result = db.get_battles_vs_opponent("pid_x", player_name="Alice")
    assert len(result) == 1
    assert result[0]["battle_id"] == "b1"


def test_get_battles_vs_opponent_empty(db):
    """該当なし → 空リスト。"""
    assert db.get_battles_vs_opponent("nonexistent_pid") == []


# ---------------------------------------------------------------------------
# get_battles_by_opp_chara
# ---------------------------------------------------------------------------

def test_get_battles_by_opp_chara_basic(db):
    """指定キャラとの対戦履歴を返す。"""
    db.insert_battles([
        _make_battle(battle_id="c1", opp_chara="Jin"),
        _make_battle(battle_id="c2", opp_chara="Bryan"),
    ], "Alice")
    result = db.get_battles_by_opp_chara("Jin")
    assert len(result) == 1
    assert result[0]["battle_id"] == "c1"


def test_get_battles_by_opp_chara_case_insensitive(db):
    """大文字小文字を無視してマッチする。"""
    db.insert_battles([_make_battle(battle_id="c3", opp_chara="jin")], "Alice")
    assert len(db.get_battles_by_opp_chara("JIN")) == 1


def test_get_battles_by_opp_chara_empty(db):
    """該当なし → 空リスト。"""
    assert db.get_battles_by_opp_chara("Unknown") == []


# ---------------------------------------------------------------------------
# search_battles_vs_opponent (部分一致)
# ---------------------------------------------------------------------------

def test_search_battles_vs_opponent_partial_match(db):
    """名前の部分一致で対戦履歴を返す。"""
    b = _make_battle(battle_id="s1")
    b["opp_name"] = "SomePlayer123"
    db.insert_battles([b], "Alice")
    result = db.search_battles_vs_opponent("SomePlayer")
    assert len(result) == 1
    assert result[0]["battle_id"] == "s1"


def test_search_battles_vs_opponent_no_match(db):
    """一致なし → 空リスト。"""
    assert db.search_battles_vs_opponent("nobody") == []


def test_search_battles_vs_opponent_case_insensitive(db):
    """大文字小文字を無視してマッチする。"""
    b = _make_battle(battle_id="s2")
    b["opp_name"] = "TestOpp"
    db.insert_battles([b], "Alice")
    assert len(db.search_battles_vs_opponent("testopp")) == 1


# ---------------------------------------------------------------------------
# get_unknown_chara_battles
# ---------------------------------------------------------------------------

def test_get_unknown_chara_battles_finds_chara_hash(db):
    """Chara#N のバトルを検出する。"""
    b1 = _make_battle(battle_id="u1", opp_chara="Chara#99")
    b2 = _make_battle(battle_id="u2", opp_chara="Jin")
    db.insert_battles([b1, b2], "Alice")
    result = db.get_unknown_chara_battles()
    assert len(result) == 1
    assert result[0]["battle_id"] == "u1"


def test_get_unknown_chara_battles_empty_when_all_known(db):
    """既知キャラのみなら空リスト。"""
    db.insert_battles([_make_battle(opp_chara="Jin")], "Alice")
    assert db.get_unknown_chara_battles() == []


def test_get_unknown_chara_battles_respects_limit(db):
    """limit 引数が機能する。"""
    for i in range(5):
        b = _make_battle(battle_id=f"ul{i}", battle_at=1_000_000 + i, opp_chara="Chara#99")
        db.insert_battles([b], "Alice")
    result = db.get_unknown_chara_battles(limit=2)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# get_weekly_my_chara_counts
# ---------------------------------------------------------------------------

def test_get_weekly_my_chara_counts_returns_data(db):
    """週別・自キャラ使用数が返る。"""
    from datetime import datetime, timezone
    now_ts = int(datetime.now(timezone.utc).timestamp())
    db.insert_battles([
        _make_battle(battle_id="w1", my_chara="Lee",   battle_at=now_ts - 100),
        _make_battle(battle_id="w2", my_chara="Lee",   battle_at=now_ts - 50),
        _make_battle(battle_id="w3", my_chara="Reina", battle_at=now_ts - 10),
    ], "Alice")
    result = db.get_weekly_my_chara_counts(weeks=1, player_name="Alice")
    assert len(result) > 0
    charas = {r["my_chara"] for r in result}
    assert "Lee" in charas


def test_get_weekly_my_chara_counts_empty(db):
    """データなし → 空リスト。"""
    assert db.get_weekly_my_chara_counts() == []


# ---------------------------------------------------------------------------
# get_scout_cache / set_scout_cache
# ---------------------------------------------------------------------------

def test_get_scout_cache_miss(db):
    """未登録の polaris_id → None を返す。"""
    assert db.get_scout_cache("unknown_pid") is None


def test_set_and_get_scout_cache(db):
    """保存したデータをキャッシュヒットで取得できる。"""
    data = {"win_rate": 55.0, "main_chara": "Jin"}
    db.set_scout_cache("pid_abc", data)
    result = db.get_scout_cache("pid_abc")
    assert result is not None
    assert result["win_rate"] == 55.0
    assert result["main_chara"] == "Jin"


def test_get_scout_cache_expired(db):
    """TTL を超えたキャッシュ → None を返す。"""
    data = {"win_rate": 40.0}
    db.set_scout_cache("pid_old", data)
    # ttl_seconds=-1 にすると age(>=0) > -1 が常に True → 期限切れ扱い
    result = db.get_scout_cache("pid_old", ttl_seconds=-1)
    assert result is None


def test_set_scout_cache_overwrites(db):
    """同じ polaris_id への上書きが正常に動作する。"""
    db.set_scout_cache("pid_dup", {"win_rate": 40.0})
    db.set_scout_cache("pid_dup", {"win_rate": 60.0})
    result = db.get_scout_cache("pid_dup")
    assert result is not None
    assert result["win_rate"] == 60.0


# ---------------------------------------------------------------------------
# backup_db
# ---------------------------------------------------------------------------

def test_backup_db_creates_file(db, tmp_path, monkeypatch):
    """バックアップファイルが生成される。"""
    import bot.db as _db
    db.insert_battles([_make_battle()], "Alice")
    dest = db.backup_db()
    assert dest.exists()
    assert dest.suffix == ".db"


def test_backup_db_keeps_n_copies(db):
    """keep 件より古いバックアップは削除される。"""
    import bot.db as _db
    backup_dir = _db.DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    # 古いバックアップファイルを5件手動作成
    for i in range(5):
        (backup_dir / f"battles_20240101_00000{i}.db").touch()
    # backup_db(keep=3) → 合計6件から古い4件を削除して3件以下になる
    db.backup_db(keep=3)
    backups = sorted(backup_dir.glob("battles_*.db"))
    assert len(backups) <= 3
