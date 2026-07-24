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


def test_get_battles_between_half_open_range(db):
    """[start, end) の半開区間。start は含み end は含まない。"""
    db.insert_battles([
        _make_battle("b1", battle_at=1000),
        _make_battle("b2", battle_at=2000),
        _make_battle("b3", battle_at=3000),
    ])
    result = db.get_battles_between(2000, 3000)
    ids = [r["battle_id"] for r in result]
    assert ids == ["b2"]          # 2000 含む / 1000 除外 / 3000 除外（end は排他）


def test_get_battles_between_player_filter(db):
    """player_name でフィルタされる。"""
    db.insert_battles([_make_battle("a1", battle_at=1500)], player_name="Alice")
    db.insert_battles([_make_battle("b1", battle_at=1500)], player_name="Bob")

    alice = db.get_battles_between(1000, 2000, player_name="Alice")
    assert len(alice) == 1 and alice[0]["battle_id"] == "a1"


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


def test_get_battles_by_opp_chara_since_ts_filters_old(db):
    """since_ts より古いバトルは除外される。"""
    db.insert_battles([
        _make_battle(battle_id="old", battle_at=1000, opp_chara="Bryan"),
        _make_battle(battle_id="new", battle_at=2000, opp_chara="Bryan"),
    ], "Alice")
    result = db.get_battles_by_opp_chara("Bryan", since_ts=1500)
    assert len(result) == 1
    assert result[0]["battle_id"] == "new"


def test_get_battles_by_opp_chara_since_ts_zero_returns_all(db):
    """since_ts=0（デフォルト）では全件返す。"""
    db.insert_battles([
        _make_battle(battle_id="a1", battle_at=100, opp_chara="Jin"),
        _make_battle(battle_id="a2", battle_at=200, opp_chara="Jin"),
    ], "Alice")
    result = db.get_battles_by_opp_chara("Jin", since_ts=0)
    assert len(result) == 2


def test_get_battles_by_opp_chara_since_ts_player_filter(db):
    """since_ts と player_name を組み合わせたフィルタ。"""
    db.insert_battles([_make_battle(battle_id="p1", battle_at=2000, opp_chara="Jin")], "Alice")
    db.insert_battles([_make_battle(battle_id="p2", battle_at=2000, opp_chara="Jin")], "Bob")
    result = db.get_battles_by_opp_chara("Jin", player_name="Alice", since_ts=1000)
    assert len(result) == 1
    assert result[0]["battle_id"] == "p1"


# ---------------------------------------------------------------------------
# get_known_opp_charas
# ---------------------------------------------------------------------------

def test_get_known_opp_charas_returns_distinct(db):
    """get_known_opp_charas: 重複なしでキャラ名を返す。"""
    db.insert_battles([
        _make_battle(battle_id="k1", opp_chara="Jin"),
        _make_battle(battle_id="k2", opp_chara="Jin"),
        _make_battle(battle_id="k3", opp_chara="Bryan"),
    ], "Alice")
    result = db.get_known_opp_charas()
    assert "Jin" in result
    assert "Bryan" in result
    assert result.count("Jin") == 1


def test_get_known_opp_charas_empty(db):
    """get_known_opp_charas: バトルなし → 空リスト。"""
    result = db.get_known_opp_charas()
    assert result == []


def test_get_known_opp_charas_sorted(db):
    """get_known_opp_charas: アルファベット順で返す。"""
    db.insert_battles([
        _make_battle(battle_id="s1", opp_chara="Zafina"),
        _make_battle(battle_id="s2", opp_chara="Alisa"),
    ], "Alice")
    result = db.get_known_opp_charas()
    assert result == sorted(result)


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


# ---------------------------------------------------------------------------
# insert_battles（空リスト ガード）
# ---------------------------------------------------------------------------

def test_insert_battles_empty_returns_zero(db):
    """空リストを渡すと即座に 0 を返す。"""
    assert db.insert_battles([]) == 0


# ---------------------------------------------------------------------------
# get_matchup_ranking
# ---------------------------------------------------------------------------

def test_get_matchup_ranking_with_player_name(db):
    """player_name 指定時は該当プレイヤーの対面キャラ別集計を返す。"""
    db.insert_battles([
        _make_battle("r1", won=True,  opp_chara="Jin"),
        _make_battle("r2", battle_at=1700000001, won=False, opp_chara="Jin"),
        _make_battle("r3", battle_at=1700000002, won=True,  opp_chara="Bryan"),
    ], player_name="Alice")
    rows = db.get_matchup_ranking(player_name="Alice", min_battles=2)
    assert len(rows) == 1
    assert rows[0]["opp_chara"] == "Jin"
    assert rows[0]["wins"] == 1
    assert rows[0]["total"] == 2


def test_get_matchup_ranking_without_player_name(db):
    """player_name 未指定 → 全プレイヤーの集計。"""
    db.insert_battles([
        _make_battle("r4", battle_at=1700000003, won=True,  opp_chara="Law"),
        _make_battle("r5", battle_at=1700000004, won=True,  opp_chara="Law"),
    ], player_name="Alice")
    db.insert_battles([
        _make_battle("r6", battle_at=1700000005, won=False, opp_chara="Law"),
        _make_battle("r7", battle_at=1700000006, won=False, opp_chara="Law"),
    ], player_name="Bob")
    rows = db.get_matchup_ranking(min_battles=2)
    assert any(r["opp_chara"] == "Law" for r in rows)
    law_row = next(r for r in rows if r["opp_chara"] == "Law")
    assert law_row["total"] == 4


def test_get_matchup_ranking_excludes_below_min(db):
    """min_battles 未満のキャラは結果に含まれない。"""
    db.insert_battles([_make_battle("r8", opp_chara="Reina")], player_name="Alice")
    rows = db.get_matchup_ranking(min_battles=2)
    assert all(r["opp_chara"] != "Reina" for r in rows)


# ---------------------------------------------------------------------------
# load_chara_names（SQLite エラーパス）
# ---------------------------------------------------------------------------

def test_load_chara_names_returns_empty_on_sqlite_error(db, monkeypatch):
    """sqlite3.Error 発生時は空 dict を返す（ログ警告のみ）。"""
    import sqlite3
    import contextlib

    @contextlib.contextmanager
    def _broken_conn():
        class _C:
            def execute(self, *a, **kw):
                raise sqlite3.Error("テストエラー")
        yield _C()

    monkeypatch.setattr(db, "get_conn", _broken_conn)
    result = db.load_chara_names()
    assert result == {}


# ---------------------------------------------------------------------------
# get_my_chara_counts
# ---------------------------------------------------------------------------

def test_get_my_chara_counts_with_player_name(db):
    """player_name 指定時は該当プレイヤーの my_chara 別カウントを返す。"""
    db.insert_battles([
        _make_battle("m1", my_chara="Lee"),
        _make_battle("m2", battle_at=1700000001, my_chara="Lee"),
        _make_battle("m3", battle_at=1700000002, my_chara="Jin"),
    ], player_name="Alice")
    rows = db.get_my_chara_counts(since_ts=0, player_name="Alice")
    assert any(r["my_chara"] == "Lee" and r["cnt"] == 2 for r in rows)


def test_get_my_chara_counts_without_player_name(db):
    """player_name 未指定 → 全プレイヤー集計。"""
    db.insert_battles([
        _make_battle("m4", my_chara="Lee"),
        _make_battle("m5", battle_at=1700000001, my_chara="Lee"),
    ], player_name="Alice")
    rows = db.get_my_chara_counts(since_ts=0)
    assert any(r["my_chara"] == "Lee" for r in rows)


# ---------------------------------------------------------------------------
# get_win_loss_by_hour
# ---------------------------------------------------------------------------

def test_get_win_loss_by_hour_returns_rows(db):
    """since_ts 以降の JST 時間帯別勝敗行を返す。"""
    db.insert_battles([
        _make_battle("h1", battle_at=1700000000, won=True),
        _make_battle("h2", battle_at=1700000100, won=False),
    ], player_name="Alice")
    rows = db.get_win_loss_by_hour(since_ts=0)
    assert len(rows) >= 1
    assert all("hour" in r and "wins" in r and "losses" in r for r in rows)


def test_get_win_loss_by_hour_empty(db):
    """バトルなし → 空リスト。"""
    rows = db.get_win_loss_by_hour(since_ts=0)
    assert rows == []


# ---------------------------------------------------------------------------
# get_last_rank_before_date
# ---------------------------------------------------------------------------

def test_get_last_rank_before_date_returns_rank(db):
    """指定日より前の最新 my_rank を返す。"""
    b = _make_battle("rr1", battle_at=int(datetime(2024, 1, 14, 12, 0, 0, tzinfo=JST).timestamp()))
    b["my_rank"] = 15
    db.insert_battles([b], "Alice")
    result = db.get_last_rank_before_date("2024-01-15", player_name="Alice")
    assert result == 15


def test_get_last_rank_before_date_returns_none_when_no_rank(db):
    """my_rank が NULL のバトルのみ → None を返す。"""
    ts = int(datetime(2024, 1, 14, 12, 0, 0, tzinfo=JST).timestamp())
    db.insert_battles([_make_battle("rr2", battle_at=ts)], "Alice")
    result = db.get_last_rank_before_date("2024-01-15", player_name="Alice")
    assert result is None


def test_get_last_rank_before_date_ignores_same_day(db):
    """指定日当日のバトルは含まれない。"""
    ts = int(datetime(2024, 1, 15, 12, 0, 0, tzinfo=JST).timestamp())
    b = _make_battle("rr3", battle_at=ts)
    b["my_rank"] = 20
    db.insert_battles([b], "Alice")
    result = db.get_last_rank_before_date("2024-01-15", player_name="Alice")
    assert result is None


def test_get_last_rank_before_date_returns_latest(db):
    """複数バトルがある場合、最も新しい my_rank を返す。"""
    b1 = _make_battle("rr4", battle_at=int(datetime(2024, 1, 10, 12, 0, 0, tzinfo=JST).timestamp()))
    b1["my_rank"] = 10
    b2 = _make_battle("rr5", battle_at=int(datetime(2024, 1, 12, 12, 0, 0, tzinfo=JST).timestamp()))
    b2["my_rank"] = 15
    db.insert_battles([b1, b2], "Alice")
    result = db.get_last_rank_before_date("2024-01-15", player_name="Alice")
    assert result == 15


def test_get_last_rank_before_date_no_player_filter(db):
    """player_name=None → 全プレイヤーから最新 my_rank を返す。"""
    b = _make_battle("rr6", battle_at=int(datetime(2024, 1, 14, 12, 0, 0, tzinfo=JST).timestamp()))
    b["my_rank"] = 25
    db.insert_battles([b], "Bob")
    result = db.get_last_rank_before_date("2024-01-15")
    assert result == 25


def test_get_last_rank_before_date_accepts_english_rank(db):
    """ewgf.gg 由来の英語段位名（文字列）でも段位番号を返す（int() で落ちない）。"""
    b = _make_battle("rr7", battle_at=int(datetime(2024, 1, 14, 12, 0, 0, tzinfo=JST).timestamp()))
    b["my_rank"] = "Raijin"  # type: ignore[typeddict-item]
    db.insert_battles([b], "Alice")
    result = db.get_last_rank_before_date("2024-01-15", player_name="Alice")
    assert result == 22


def test_get_last_rank_before_date_unknown_rank_string_returns_none(db):
    """表にない段位名は例外にせず None を返す。"""
    b = _make_battle("rr8", battle_at=int(datetime(2024, 1, 14, 12, 0, 0, tzinfo=JST).timestamp()))
    b["my_rank"] = "Unknown Rank"  # type: ignore[typeddict-item]
    db.insert_battles([b], "Alice")
    result = db.get_last_rank_before_date("2024-01-15", player_name="Alice")
    assert result is None


# ---------------------------------------------------------------------------
# get_battles_in_month
# ---------------------------------------------------------------------------

def test_get_battles_in_month_returns_battles(db):
    """指定月のバトルを返す。"""
    ts = int(datetime(2024, 1, 15, 12, 0, 0, tzinfo=JST).timestamp())
    db.insert_battles([_make_battle("im1", battle_at=ts)], "Alice")
    result = db.get_battles_in_month(2024, 1, player_name="Alice")
    assert len(result) == 1
    assert result[0]["battle_id"] == "im1"


def test_get_battles_in_month_excludes_other_month(db):
    """他の月のバトルは含まれない。"""
    ts_jan = int(datetime(2024, 1, 15, 12, 0, 0, tzinfo=JST).timestamp())
    ts_feb = int(datetime(2024, 2, 15, 12, 0, 0, tzinfo=JST).timestamp())
    db.insert_battles([_make_battle("im2", battle_at=ts_jan)], "Alice")
    db.insert_battles([_make_battle("im3", battle_at=ts_feb)], "Alice")
    result = db.get_battles_in_month(2024, 1, player_name="Alice")
    assert len(result) == 1
    assert result[0]["battle_id"] == "im2"


def test_get_battles_in_month_december(db):
    """12月 → 翌年1月を境界として正しく処理する。"""
    ts_dec = int(datetime(2024, 12, 31, 12, 0, 0, tzinfo=JST).timestamp())
    ts_jan = int(datetime(2025,  1,  1, 12, 0, 0, tzinfo=JST).timestamp())
    db.insert_battles([_make_battle("im4", battle_at=ts_dec)], "Alice")
    db.insert_battles([_make_battle("im5", battle_at=ts_jan)], "Alice")
    result = db.get_battles_in_month(2024, 12, player_name="Alice")
    assert len(result) == 1
    assert result[0]["battle_id"] == "im4"


def test_get_battles_in_month_empty(db):
    """バトルなし → 空リスト。"""
    result = db.get_battles_in_month(2024, 1, player_name="Alice")
    assert result == []


def test_get_battles_in_month_no_player_filter(db):
    """player_name=None → 全プレイヤーのバトルを返す。"""
    ts = int(datetime(2024, 3, 1, 12, 0, 0, tzinfo=JST).timestamp())
    db.insert_battles([_make_battle("im6", battle_at=ts)], "Alice")
    db.insert_battles([_make_battle("im7", battle_at=ts + 1)], "Bob")
    result = db.get_battles_in_month(2024, 3)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# get_personal_records
# ---------------------------------------------------------------------------

def test_get_personal_records_empty(db):
    """バトルなし → 空 dict を返す。"""
    assert db.get_personal_records() == {}


def test_get_personal_records_basic(db):
    """通算試合数・勝敗・初対戦日が返る。"""
    b1 = {**_make_battle("pr1", battle_at=1700000000, won=True),  "rating_before": 10000, "rating_change": 100}
    b2 = {**_make_battle("pr2", battle_at=1700001000, won=False), "rating_before": 10100, "rating_change": -100}
    db.insert_battles([b1, b2], "Alice")
    rec = db.get_personal_records("Alice")
    assert rec["total"] == 2
    assert rec["wins"] == 1
    assert rec["losses"] == 1
    assert rec["first_date"] is not None


def test_get_personal_records_max_rating(db):
    """最高レーティングが正しく計算される。"""
    b1 = {**_make_battle("pr3", battle_at=1700000000, won=True),  "rating_before": 50000, "rating_change": 500}
    b2 = {**_make_battle("pr4", battle_at=1700001000, won=False), "rating_before": 50500, "rating_change": -500}
    db.insert_battles([b1, b2], "Alice")
    rec = db.get_personal_records("Alice")
    assert rec["max_rating"] == 50500
    assert rec["max_rating_date"] is not None


def test_get_personal_records_win_streak(db):
    """連勝記録が正しく計算される（3連勝→2連敗）。"""
    battles = [
        _make_battle("pr5", battle_at=1700000000, won=True),
        _make_battle("pr6", battle_at=1700000100, won=True),
        _make_battle("pr7", battle_at=1700000200, won=True),
        _make_battle("pr8", battle_at=1700000300, won=False),
        _make_battle("pr9", battle_at=1700000400, won=False),
    ]
    db.insert_battles(battles, "Alice")
    rec = db.get_personal_records("Alice")
    assert rec["max_win_streak"] == 3
    assert rec["max_lose_streak"] == 2


def test_get_personal_records_no_rating(db):
    """rating_before/change が NULL でも空 dict 以外を返す。"""
    db.insert_battles([_make_battle("pr10", won=True)], "Alice")
    rec = db.get_personal_records("Alice")
    assert rec["total"] == 1
    assert rec["max_rating"] is None


# ---------------------------------------------------------------------------
# get_stage_stats
# ---------------------------------------------------------------------------

def test_get_stage_stats_basic(db):
    """stage_id 別の勝敗集計が返る。"""
    b1 = {**_make_battle("ss1", won=True),  "stage_id": 5}
    b2 = {**_make_battle("ss2", battle_at=1700000001, won=False), "stage_id": 5}
    b3 = {**_make_battle("ss3", battle_at=1700000002, won=True),  "stage_id": 5}
    db.insert_battles([b1, b2, b3], "Alice")
    rows = db.get_stage_stats(player_name="Alice", min_battles=2)
    assert len(rows) == 1
    assert rows[0]["stage_id"] == 5
    assert rows[0]["wins"] == 2
    assert rows[0]["total"] == 3


def test_get_stage_stats_excludes_null_stage(db):
    """stage_id が NULL のバトルは除外される。"""
    db.insert_battles([_make_battle("ss4", won=True)], "Alice")  # stage_id=None
    rows = db.get_stage_stats(player_name="Alice", min_battles=1)
    assert rows == []


def test_get_stage_stats_min_battles_filter(db):
    """min_battles 未満のステージは除外される。"""
    b = {**_make_battle("ss5", won=True), "stage_id": 99}
    db.insert_battles([b], "Alice")
    rows = db.get_stage_stats(player_name="Alice", min_battles=2)
    assert all(r["stage_id"] != 99 for r in rows)


# ---------------------------------------------------------------------------
# goal CRUD
# ---------------------------------------------------------------------------

def test_goal_set_and_get(db):
    """set_goal → get_goal で値を取得できる。"""
    db.set_goal("Alice", 200000)
    assert db.get_goal("Alice") == 200000


def test_goal_get_none_when_unset(db):
    """未設定のプレイヤーは None を返す。"""
    assert db.get_goal("NoPlayer") is None


def test_goal_overwrite(db):
    """同じプレイヤーへの二度目の set_goal は上書き。"""
    db.set_goal("Alice", 100000)
    db.set_goal("Alice", 200000)
    assert db.get_goal("Alice") == 200000


def test_goal_clear(db):
    """clear_goal → get_goal が None を返す。"""
    db.set_goal("Alice", 150000)
    db.clear_goal("Alice")
    assert db.get_goal("Alice") is None


def test_goal_clear_nonexistent(db):
    """存在しないプレイヤーの clear_goal はエラーなし。"""
    db.clear_goal("Ghost")  # should not raise


# ---------------------------------------------------------------------------
# llm_eval_score
# ---------------------------------------------------------------------------

def test_save_and_get_llm_eval_score(db):
    """save → get で評価スコアが取得できる。"""
    db.save_llm_eval_score("2026-04-01", "Alice", 80)
    rows = db.get_llm_eval_scores("Alice", days=30)
    assert len(rows) == 1
    assert rows[0]["score"] == 80
    assert rows[0]["date_str"] == "2026-04-01"


def test_get_llm_eval_scores_empty(db):
    """データなし → 空リスト。"""
    assert db.get_llm_eval_scores("Alice") == []


def test_get_latest_llm_eval_score(db):
    """最新スコアを返す。"""
    db.save_llm_eval_score("2026-04-01", "Alice", 60)
    db.save_llm_eval_score("2026-04-02", "Alice", 90)
    assert db.get_latest_llm_eval_score("Alice") == 90


def test_get_latest_llm_eval_score_none_when_empty(db):
    """データなし → None。"""
    assert db.get_latest_llm_eval_score() is None


# ---------------------------------------------------------------------------
# monthly_snapshot
# ---------------------------------------------------------------------------

def test_upsert_and_get_monthly_snapshot(db):
    """upsert → get でスナップショットが取得できる。"""
    db.upsert_monthly_snapshot("2026-03", "Alice", wins=20, losses=10,
                               rating_delta=5000, end_power=1200000, top_chara="Lee")
    rows = db.get_monthly_snapshots("Alice")
    assert len(rows) == 1
    assert rows[0]["year_month"] == "2026-03"
    assert rows[0]["wins"] == 20
    assert rows[0]["top_chara"] == "Lee"


def test_monthly_snapshot_overwrite(db):
    """同じ year_month + player_name への再 upsert は上書き。"""
    db.upsert_monthly_snapshot("2026-03", "Alice", wins=5, losses=5,
                               rating_delta=0, end_power=None, top_chara=None)
    db.upsert_monthly_snapshot("2026-03", "Alice", wins=20, losses=10,
                               rating_delta=3000, end_power=1000000, top_chara="Lee")
    rows = db.get_monthly_snapshots("Alice")
    assert len(rows) == 1
    assert rows[0]["wins"] == 20


def test_monthly_snapshot_limit(db):
    """limit 引数が機能する。"""
    for i in range(5):
        db.upsert_monthly_snapshot(f"2026-0{i+1}", "Alice", wins=i, losses=i,
                                   rating_delta=0, end_power=None, top_chara=None)
    rows = db.get_monthly_snapshots("Alice", limit=3)
    assert len(rows) == 3


def test_get_monthly_snapshots_empty(db):
    """データなし → 空リスト。"""
    assert db.get_monthly_snapshots("Alice") == []


# ---------------------------------------------------------------------------
# get_latest_comment_before
# ---------------------------------------------------------------------------

def test_get_latest_comment_before_returns_comment(db):
    """before_ts より前の最新コメントを返す。"""
    db.save_llm_eval_score("2026-05-25", "Alice", 80, "Bryan対策が課題だ。")
    result = db.get_latest_comment_before(before_ts=9999999999, player_name="Alice")
    assert result == "Bryan対策が課題だ。"


def test_get_latest_comment_before_excludes_after_ts(db):
    """before_ts より後に保存されたコメントは除外される。"""
    db.save_llm_eval_score("2026-05-25", "Alice", 80, "Bryan対策が課題だ。")
    result = db.get_latest_comment_before(before_ts=0, player_name="Alice")
    assert result is None


def test_get_latest_comment_before_returns_most_recent(db):
    """複数コメントがある場合、最後に挿入された（id が大きい）ものを返す。"""
    db.save_llm_eval_score("2026-05-24", "Alice", 70, "古いコメント")
    db.save_llm_eval_score("2026-05-25", "Alice", 85, "新しいコメント")
    result = db.get_latest_comment_before(before_ts=9999999999, player_name="Alice")
    assert result == "新しいコメント"


def test_get_latest_comment_before_player_filter(db):
    """player_name フィルタが機能する。"""
    db.save_llm_eval_score("2026-05-25", "Alice", 80, "Aliceのコメント")
    db.save_llm_eval_score("2026-05-25", "Bob",   80, "Bobのコメント")
    result = db.get_latest_comment_before(before_ts=9999999999, player_name="Alice")
    assert result == "Aliceのコメント"


def test_get_latest_comment_before_none_when_no_comment(db):
    """comment が NULL の行は除外される。"""
    db.save_llm_eval_score("2026-05-25", "Alice", 80, None)
    result = db.get_latest_comment_before(before_ts=9999999999, player_name="Alice")
    assert result is None


def test_get_latest_comment_before_no_data(db):
    """データなし → None を返す。"""
    result = db.get_latest_comment_before(before_ts=9999999999)
    assert result is None


# ---------------------------------------------------------------------------
# 死活監視（run_status）
# ---------------------------------------------------------------------------

def test_init_db_creates_run_status_table(db):
    """init_db() が run_status テーブルを作成することを確認。"""
    with db.get_conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='run_status'"
        ).fetchall()
    assert len(tables) == 1


def test_record_run_success_with_explicit_ts(db):
    """明示した ts で正常完了時刻を記録できる。"""
    db.record_run_success("daily", ts=1700000000)
    rows = db.get_run_status()
    assert rows == [{"job_name": "daily", "last_success_at": 1700000000}]


def test_record_run_success_defaults_to_now(db):
    """ts 省略時は現在時刻（UTC epoch）が記録される。"""
    from datetime import datetime, timezone
    before = int(datetime.now(timezone.utc).timestamp())
    db.record_run_success("weekly")
    after = int(datetime.now(timezone.utc).timestamp())
    rows = db.get_run_status()
    assert len(rows) == 1
    assert rows[0]["job_name"] == "weekly"
    assert before <= rows[0]["last_success_at"] <= after


def test_record_run_success_upserts(db):
    """同じ job_name は最新時刻で上書きされる（行は増えない）。"""
    db.record_run_success("daily", ts=1700000000)
    db.record_run_success("daily", ts=1700009999)
    rows = db.get_run_status()
    assert rows == [{"job_name": "daily", "last_success_at": 1700009999}]


def test_get_run_status_multiple_jobs_sorted(db):
    """複数ジョブが job_name 昇順で返る。"""
    db.record_run_success("weekly", ts=2)
    db.record_run_success("daily", ts=1)
    db.record_run_success("monthly", ts=3)
    rows = db.get_run_status()
    assert [r["job_name"] for r in rows] == ["daily", "monthly", "weekly"]


def test_get_run_status_empty(db):
    """記録がなければ空リストを返す。"""
    assert db.get_run_status() == []
