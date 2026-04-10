"""
bot/fetcher.py のテスト。
純粋な変換・パース関数と、requests をモックしたネットワーク層のテストを含む。
"""

import pytest
import requests
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup

from bot.fetcher import (
    get_chara_name,
    _normalize_ewgf,
    _merge_bulk,
    _parse_wank_html_row,
    fetch_battles_since,
    fetch_quick_battles_from_ewgf,
    fetch_opponent_summary,
    _learn_chara_name,
    _verify_and_learn_chara_name,
    load_learned_chara_names,
    _fetch_bulk_batch,
    _build_bulk_index,
    _enrich_from_bulk,
    CHARA_NAMES,
    _learned_chara_names,
)
import bot.fetcher as _fetcher_module


# ---------------------------------------------------------------------------
# get_chara_name
# ---------------------------------------------------------------------------

def test_get_chara_name_known_id():
    assert get_chara_name(6) == "Jin"
    assert get_chara_name(33) == "Reina"


def test_get_chara_name_unknown_id():
    assert get_chara_name(99) == "Chara#99"


def test_get_chara_name_none():
    assert get_chara_name(None) is None


def test_get_chara_name_all_defined():
    """CHARA_NAMES の全IDが文字列を返すことを確認。"""
    for cid in CHARA_NAMES:
        assert isinstance(get_chara_name(cid), str)


def test_get_chara_name_learned_takes_precedence(monkeypatch):
    """_learned_chara_names の値が CHARA_NAMES より優先される。"""
    monkeypatch.setitem(_fetcher_module._learned_chara_names, 999, "LearnedChar")
    assert get_chara_name(999) == "LearnedChar"
    monkeypatch.delitem(_fetcher_module._learned_chara_names, 999)


# ---------------------------------------------------------------------------
# _normalize_ewgf
# ---------------------------------------------------------------------------

def _ewgf_raw(p1_id: str = "pid1", p2_id: str = "pid2", winner: int = 1) -> dict:
    return {
        "p1_tekken_id":  p1_id,
        "p2_tekken_id":  p2_id,
        "winner":        winner,
        "battle_at":     "2024-01-15T12:00:00Z",
        "battle_type":   "RANKED_BATTLE",
        "game_version":  "1.0",
        "stage_id":      3,
        "p1_char":       "Jin",
        "p1_rounds_won": 2,
        "p1_dan_rank":   15,
        "p1_tekken_power": 10000,
        "p1_region":     "JP",
        "p2_char":       "Reina",
        "p2_rounds_won": 1,
        "p2_dan_rank":   12,
        "p2_tekken_power": 8000,
        "p2_region":     "US",
    }


def test_normalize_ewgf_p1_wins():
    raw = _ewgf_raw(p1_id="me", winner=1)
    result = _normalize_ewgf(raw, "me")
    assert result["won"] is True
    assert result["my_chara"] == "Jin"
    assert result["opp_chara"] == "Reina"
    assert result["my_rounds"] == 2
    assert result["opp_rounds"] == 1
    assert result["battle_type"] == "ranked"
    assert result["source"] == "ewgf"


def test_normalize_ewgf_p2_wins():
    raw = _ewgf_raw(p1_id="opp", p2_id="me", winner=2)
    result = _normalize_ewgf(raw, "me")
    assert result["won"] is True
    assert result["my_chara"] == "Reina"
    assert result["opp_chara"] == "Jin"


def test_normalize_ewgf_loss():
    raw = _ewgf_raw(p1_id="me", winner=2)
    result = _normalize_ewgf(raw, "me")
    assert result["won"] is False


def test_normalize_ewgf_timestamp():
    raw = _ewgf_raw()
    result = _normalize_ewgf(raw, "pid1")
    assert result["battle_at"] == 1705320000  # 2024-01-15T12:00:00Z


def test_normalize_ewgf_invalid_timestamp():
    raw = _ewgf_raw()
    raw["battle_at"] = "invalid"
    result = _normalize_ewgf(raw, "pid1")
    assert result["battle_at"] == 0


def test_normalize_ewgf_quick_battle_type():
    raw = _ewgf_raw()
    raw["battle_type"] = "QUICK_BATTLE"
    result = _normalize_ewgf(raw, "pid1")
    assert result["battle_type"] == "quick"


def test_normalize_ewgf_rating_is_none():
    """ewgf.gg はレーティング情報を持たない。"""
    result = _normalize_ewgf(_ewgf_raw(), "pid1")
    assert result["rating_before"] is None
    assert result["rating_change"] is None


# ---------------------------------------------------------------------------
# _merge_bulk
# ---------------------------------------------------------------------------

def _html_battle(battle_at: int = 1000) -> dict:
    return {
        "battle_id":      f"wank_{battle_at}_opp",
        "battle_at":      battle_at,
        "battle_type":    None,
        "game_version":   None,
        "stage_id":       None,
        "source":         "wank_html",
        "won":            True,
        "my_chara":       "Jin",
        "my_chara_id":    None,
        "my_rounds":      2,
        "my_rank":        None,
        "my_power":       None,
        "my_region":      None,
        "rating_before":  10000,
        "rating_change":  50,
        "opp_name":       "TestOpp",
        "opp_polaris_id": "opp_pid",
        "opp_chara":      "Reina",
        "opp_chara_id":   None,
        "opp_rounds":     1,
        "opp_rank":       None,
        "opp_power":      None,
        "opp_region":     None,
        "opp_rating_before": None,
        "opp_rating_change": None,
    }


def _bulk_record(p1_polaris_id: str = "me", p2_polaris_id: str = "opp_pid") -> dict:
    return {
        "battle_id":      999,
        "battle_at":      1000,
        "battle_type":    2,        # ranked
        "game_version":   "1.05",
        "stage_id":       5,
        "p1_polaris_id":  p1_polaris_id,
        "p2_polaris_id":  p2_polaris_id,
        "p1_chara_id":    6,        # Jin
        "p1_rank":        15,
        "p1_power":       10500,
        "p1_region_id":   "JP",
        "p2_chara_id":    33,       # Reina
        "p2_rank":        12,
        "p2_power":       8200,
        "p2_region_id":   "US",
    }


def test_merge_bulk_enriches_battle_type():
    battle = _html_battle()
    result = _merge_bulk(battle, _bulk_record(p1_polaris_id="me"), "me")
    assert result["battle_type"] == "ranked"
    assert result["source"] == "wank_bulk"


def test_merge_bulk_enriches_chara_names():
    battle = _html_battle()
    result = _merge_bulk(battle, _bulk_record(p1_polaris_id="me"), "me")
    assert result["my_chara"] == "Jin"
    assert result["opp_chara"] == "Reina"


def test_merge_bulk_enriches_rank_power():
    battle = _html_battle()
    result = _merge_bulk(battle, _bulk_record(p1_polaris_id="me"), "me")
    assert result["my_rank"] == 15
    assert result["my_power"] == 10500
    assert result["opp_rank"] == 12
    assert result["opp_power"] == 8200


def test_merge_bulk_updates_battle_id():
    battle = _html_battle()
    result = _merge_bulk(battle, _bulk_record(p1_polaris_id="me"), "me")
    assert result["battle_id"] == "999"


def test_merge_bulk_p2_perspective():
    """自分が p2 の場合も正しくマージされる。"""
    # HTML は常に自分のキャラを my_chara に持つ。p2=自分(Reina)の場合は HTML 側も Reina になる。
    battle = {**_html_battle(), "my_chara": "Reina", "opp_chara": "Jin"}
    result = _merge_bulk(battle, _bulk_record(p1_polaris_id="opp_pid", p2_polaris_id="me"), "me")
    assert result["my_chara"] == "Reina"
    assert result["opp_chara"] == "Jin"
    assert result["my_rank"] == 12


def test_merge_bulk_unknown_id_keeps_html_name(monkeypatch):
    """未知のキャラID（Chara#N）の場合、HTML名を保持して学習する。"""
    learned: dict = {}
    # _verify_and_learn_chara_name の副作用（DB保存）を無効化しつつ学習内容を捕捉
    monkeypatch.setattr(_fetcher_module, "_verify_and_learn_chara_name",
                        lambda cid, name: learned.update({cid: name}))

    bulk = {**_bulk_record(), "p2_chara_id": 99}  # 99 は未知ID
    battle = {**_html_battle(), "opp_chara": "FutureChar"}
    result = _merge_bulk(battle, bulk, "me")

    assert result["opp_chara"] == "FutureChar"  # HTML名を保持
    assert learned.get(99) == "FutureChar"       # 学習されている


# ---------------------------------------------------------------------------
# _parse_wank_html_row
# ---------------------------------------------------------------------------

def _make_wank_row(
    ts: int = 1705320000,
    my_chara: str = "Jin",
    opp_chara: str = "Reina",
    score: str = "2-1",
    won: bool = True,
    rating_before: int = 10000,
    rating_change: int = 50,
    opp_name: str = "TestPlayer",
    opp_polaris_id: str = "abc123",
) -> any:
    """テスト用の wank HTML テーブル行を生成する。"""
    rc_class = "win" if won else "lose"
    rc_sign  = "+" if won else ""
    html = f"""
    <tr>
      <td class="battle-at"><script>printDateTime({ts})</script></td>
      <td class="left">
        <span class="char">{my_chara}</span>
        <span class="rating">{rating_before}</span>
        <span class="{rc_class}">{rc_sign}{rating_change}</span>
      </td>
      <td class="result">{score}</td>
      <td class="right">
        <span class="char">{opp_chara}</span>
        <span class="player"><a href="/player/{opp_polaris_id}">{opp_name}</a></span>
      </td>
    </tr>
    """
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("tr")


def test_parse_wank_row_win():
    row = _make_wank_row(won=True, rating_change=50)
    result = _parse_wank_html_row(row)
    assert result is not None
    assert result["won"] is True
    assert result["rating_change"] == 50


def test_parse_wank_row_loss():
    row = _make_wank_row(won=False, rating_change=-30)
    result = _parse_wank_html_row(row)
    assert result is not None
    assert result["won"] is False
    assert result["rating_change"] == -30


def test_parse_wank_row_characters():
    row = _make_wank_row(my_chara="Jin", opp_chara="Reina")
    result = _parse_wank_html_row(row)
    assert result["my_chara"] == "Jin"
    assert result["opp_chara"] == "Reina"


def test_parse_wank_row_score():
    row = _make_wank_row(score="2-0")
    result = _parse_wank_html_row(row)
    assert result["my_rounds"] == 2
    assert result["opp_rounds"] == 0


def test_parse_wank_row_timestamp():
    row = _make_wank_row(ts=1705320000)
    result = _parse_wank_html_row(row)
    assert result["battle_at"] == 1705320000


def test_parse_wank_row_opp_info():
    row = _make_wank_row(opp_name="TestPlayer", opp_polaris_id="abc123")
    result = _parse_wank_html_row(row)
    assert result["opp_name"] == "TestPlayer"
    assert result["opp_polaris_id"] == "abc123"


def test_parse_wank_row_rating_before():
    row = _make_wank_row(rating_before=10000)
    result = _parse_wank_html_row(row)
    assert result["rating_before"] == 10000


def test_parse_wank_row_battle_type_is_none():
    """バルクAPIで補完されるまで battle_type は None。"""
    row = _make_wank_row()
    result = _parse_wank_html_row(row)
    assert result["battle_type"] is None


def test_parse_wank_row_missing_elements_returns_none():
    """必須要素が欠けている行は None を返す。"""
    soup = BeautifulSoup("<tr><td>invalid</td></tr>", "html.parser")
    result = _parse_wank_html_row(soup.find("tr"))
    assert result is None


# ---------------------------------------------------------------------------
# fetch_battles_since — フォールバックチェーンのテスト
# ---------------------------------------------------------------------------

def _mock_battle(battle_at: int = 2000) -> dict:
    return {
        "battle_id":      f"wank_{battle_at}_opp",
        "battle_at":      battle_at,
        "battle_type":    "ranked",
        "source":         "wank_bulk",
        "won":            True,
        "my_chara":       "Jin",
        "my_chara_id":    7,
        "my_rounds":      2,
        "my_rank":        15,
        "my_power":       10000,
        "my_region":      "JP",
        "rating_before":  10000,
        "rating_change":  50,
        "opp_name":       "Opp",
        "opp_polaris_id": "opp_pid",
        "opp_chara":      "Reina",
        "opp_chara_id":   33,
        "opp_rounds":     1,
        "opp_rank":       12,
        "opp_power":      8000,
        "opp_region":     "US",
        "opp_rating_before": None,
        "opp_rating_change": None,
        "game_version":   "1.0",
        "stage_id":       3,
    }


@patch("bot.fetcher._enrich_from_bulk")
@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_battles_since_normal_path(mock_wank, mock_enrich):
    """wank 成功 → enrich して返す。"""
    battle = _mock_battle(2000)
    mock_wank.return_value  = [battle]
    mock_enrich.return_value = [battle]

    result = fetch_battles_since(1000, polaris_id="me")

    assert len(result) == 1
    mock_wank.assert_called_once()
    mock_enrich.assert_called_once()


@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_battles_since_wank_empty(mock_wank):
    """wank 成功だが試合なし → enrich せず空リストを返す。"""
    mock_wank.return_value = []

    result = fetch_battles_since(1000, polaris_id="me")

    assert result == []


@patch("bot.fetcher._enrich_from_bulk")
@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_battles_since_enrich_fails_returns_html(mock_wank, mock_enrich):
    """enrich 失敗 → HTMLデータのみで続行。"""
    battle = _mock_battle(2000)
    mock_wank.return_value = [battle]
    mock_enrich.side_effect = requests.RequestException("bulk API down")

    result = fetch_battles_since(1000, polaris_id="me")

    assert len(result) == 1
    assert result[0]["source"] == "wank_bulk"


@patch("bot.fetcher._fetch_from_ewgf")
@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_battles_since_falls_back_to_ewgf(mock_wank, mock_ewgf):
    """wank 完全失敗 → ewgf.gg にフォールバック。"""
    mock_wank.side_effect = requests.RequestException("wank down")
    ewgf_battle = {**_mock_battle(2000), "source": "ewgf"}
    mock_ewgf.return_value = [ewgf_battle]

    result = fetch_battles_since(1000, polaris_id="me")

    assert len(result) == 1
    mock_ewgf.assert_called_once()


@patch("bot.fetcher._fetch_from_wank_html")
@patch("bot.fetcher._fetch_from_ewgf")
def test_fetch_battles_since_falls_back_to_wank_retry(mock_ewgf, mock_wank):
    """wank 失敗 + ewgf 失敗 → wank を再試行（最終フォールバック）。"""
    mock_ewgf.side_effect = requests.RequestException("ewgf also down")
    battle = _mock_battle(2000)
    mock_wank.side_effect = [requests.RequestException("first call fails"), [battle]]

    result = fetch_battles_since(1000, polaris_id="me")

    assert len(result) == 1
    assert mock_wank.call_count == 2  # 最初の失敗 + 再試行


@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_battles_since_filters_old_battles(mock_wank):
    """since_ts より古いバトルは ewgf フォールバック時に除外される。"""
    old_battle = _mock_battle(500)   # since_ts=1000 より古い
    new_battle = _mock_battle(2000)
    mock_wank.side_effect = requests.RequestException("wank down")

    with patch("bot.fetcher._fetch_from_ewgf") as mock_ewgf:
        mock_ewgf.return_value = [old_battle, new_battle]
        result = fetch_battles_since(1000, polaris_id="me")

    assert len(result) == 1
    assert result[0]["battle_at"] == 2000


# ---------------------------------------------------------------------------
# fetch_quick_battles_from_ewgf
# ---------------------------------------------------------------------------

@patch("bot.fetcher._fetch_from_ewgf")
def test_fetch_quick_battles_returns_only_quick(mock_ewgf):
    """quick タイプのみ返す。"""
    mock_ewgf.return_value = [
        {**_mock_battle(2000), "battle_type": "quick"},
        {**_mock_battle(3000), "battle_type": "ranked"},  # 除外
    ]
    result = fetch_quick_battles_from_ewgf(1000, polaris_id="me")
    assert len(result) == 1
    assert result[0]["battle_type"] == "quick"


@patch("bot.fetcher._fetch_from_ewgf")
def test_fetch_quick_battles_filters_old(mock_ewgf):
    """since_ts より古いバトルは除外される。"""
    mock_ewgf.return_value = [
        {**_mock_battle(500),  "battle_type": "quick"},  # 古い
        {**_mock_battle(2000), "battle_type": "quick"},
    ]
    result = fetch_quick_battles_from_ewgf(1000, polaris_id="me")
    assert len(result) == 1
    assert result[0]["battle_at"] == 2000


@patch("bot.fetcher._fetch_from_ewgf")
def test_fetch_quick_battles_returns_empty_on_error(mock_ewgf):
    """ewgf 失敗時は空リストを返す（例外を出さない）。"""
    mock_ewgf.side_effect = requests.RequestException("ewgf down")
    result = fetch_quick_battles_from_ewgf(0, polaris_id="me")
    assert result == []


# ---------------------------------------------------------------------------
# fetch_opponent_summary
# ---------------------------------------------------------------------------

def _opp_battle(won: bool, my_chara: str = "Jin", battle_at: int = 1000) -> dict:
    """fetch_opponent_summary 内で使う（opponent 視点）の HTML バトル。"""
    return {
        "won": won,
        "my_chara": my_chara,
        "opp_chara": "Lee",
        "battle_at": battle_at,
        "battle_type": "ranked",
        "my_rounds": 2,
        "opp_rounds": 1,
        "rating_before": None,
        "rating_change": None,
        "opp_polaris_id": "target",
        "opp_name": "target",
        "my_chara_id": None,
        "opp_chara_id": None,
        "my_rank": None,
        "my_power": None,
        "opp_rank": None,
        "opp_power": None,
        "my_region": None,
        "opp_region": None,
        "opp_rating_before": None,
        "opp_rating_change": None,
        "battle_id": f"wank_{battle_at}_target",
        "source": "wank_html",
        "game_version": None,
        "stage_id": None,
    }


@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_opponent_summary_basic(mock_wank):
    """正常系: 20戦取得して勝率・メインキャラを集計。"""
    battles = [_opp_battle(True, "Jin", i * 100) for i in range(12)] + \
              [_opp_battle(False, "Jin", i * 100 + 50) for i in range(8)]
    mock_wank.return_value = battles

    result = fetch_opponent_summary("target_pid")

    assert result is not None
    assert result["total"] == 20
    assert abs(result["win_rate"] - 60.0) < 1.0
    assert result["main_chara"] == "Jin"
    mock_wank.assert_called_once()


@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_opponent_summary_empty(mock_wank):
    """試合なし → None を返す。"""
    mock_wank.return_value = []
    assert fetch_opponent_summary("target_pid") is None


@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_opponent_summary_error(mock_wank):
    """取得失敗 → None を返す（例外を出さない）。"""
    mock_wank.side_effect = requests.RequestException("wank down")
    assert fetch_opponent_summary("target_pid") is None


@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_opponent_summary_recent_win_rate(mock_wank):
    """直近10戦の勝率が計算される。"""
    # HTML は新しい順（降順）で返す → 最初の10件が直近
    # 直近10戦は全勝、古い10戦は全敗
    battles = [_opp_battle(True, "Jin", 1000 + i * 100) for i in range(10)] + \
              [_opp_battle(False, "Jin", i * 100) for i in range(10)]
    mock_wank.return_value = battles

    result = fetch_opponent_summary("target_pid")

    assert result is not None
    # battles[:10] が直近 → 全勝
    assert result["recent_wins"] == 10
    assert result["recent_total"] == 10
    assert result["recent_win_rate"] == 100.0


@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_opponent_summary_main_chara_most_common(mock_wank):
    """最多使用キャラが main_chara になる。"""
    battles = [_opp_battle(True, "Jin")] * 3 + [_opp_battle(True, "Reina")] * 7
    mock_wank.return_value = battles

    result = fetch_opponent_summary("target_pid")

    assert result is not None
    assert result["main_chara"] == "Reina"


# ---------------------------------------------------------------------------
# _learn_chara_name
# ---------------------------------------------------------------------------

def test_learn_chara_name_new_chara(monkeypatch):
    """未知IDは学習してDBに保存する。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    with patch("bot.db.save_chara_name") as mock_save:
        _learn_chara_name(997, "FutureChar")
    assert _fetcher_module._learned_chara_names.get(997) == "FutureChar"
    mock_save.assert_called_once_with(997, "FutureChar")


def test_learn_chara_name_skips_known_static(monkeypatch):
    """CHARA_NAMES に既存のIDは保存しない。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    with patch("bot.db.save_chara_name") as mock_save:
        _learn_chara_name(6, "Jin")  # 6 は CHARA_NAMES に存在
    mock_save.assert_not_called()


def test_learn_chara_name_skips_already_learned(monkeypatch):
    """既に学習済みIDは再保存しない。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {997: "FutureChar"})
    with patch("bot.db.save_chara_name") as mock_save:
        _learn_chara_name(997, "FutureChar")
    mock_save.assert_not_called()


def test_learn_chara_name_db_error_does_not_raise(monkeypatch):
    """DB 保存失敗時も例外を出さない。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    import sqlite3
    with patch("bot.db.save_chara_name", side_effect=sqlite3.Error("DB error")):
        _learn_chara_name(996, "ErrorChar")  # should not raise


# ---------------------------------------------------------------------------
# _verify_and_learn_chara_name
# ---------------------------------------------------------------------------

def test_verify_static_match_no_save(monkeypatch):
    """静的マッピングと HTML名が一致 → 何もしない。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    with patch("bot.db.save_chara_name") as mock_save:
        _verify_and_learn_chara_name(6, "Jin")  # 6=Jin, 一致
    mock_save.assert_not_called()


def test_verify_already_learned_same_no_save(monkeypatch):
    """既に同名で学習済み → 何もしない。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {997: "LearnedChar"})
    with patch("bot.db.save_chara_name") as mock_save:
        _verify_and_learn_chara_name(997, "LearnedChar")
    mock_save.assert_not_called()


def test_verify_new_chara_learns_and_saves(monkeypatch):
    """未知IDの新キャラ → 学習してDBに保存。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    with patch("bot.db.save_chara_name") as mock_save:
        _verify_and_learn_chara_name(995, "BrandNewChar")
    assert _fetcher_module._learned_chara_names.get(995) == "BrandNewChar"
    mock_save.assert_called_once_with(995, "BrandNewChar")


def test_verify_mismatch_html_takes_priority(monkeypatch):
    """静的マッピングと不一致 → HTML名を優先して学習。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    with patch("bot.db.save_chara_name") as mock_save:
        _verify_and_learn_chara_name(6, "Jin_v2")  # 6=Jin but HTML says "Jin_v2"
    assert _fetcher_module._learned_chara_names.get(6) == "Jin_v2"
    mock_save.assert_called_once_with(6, "Jin_v2")


# ---------------------------------------------------------------------------
# load_learned_chara_names
# ---------------------------------------------------------------------------

def test_load_learned_chara_names_success(monkeypatch):
    """DB からキャラ名をロードして _learned_chara_names に格納する。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    with patch("bot.db.load_chara_names", return_value={999: "TestChar", 998: "AnotherChar"}):
        load_learned_chara_names()
    assert _fetcher_module._learned_chara_names.get(999) == "TestChar"
    assert _fetcher_module._learned_chara_names.get(998) == "AnotherChar"


def test_load_learned_chara_names_failure_graceful(monkeypatch):
    """DB 読み込み失敗時は例外を出さない。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    with patch("bot.db.load_chara_names", side_effect=Exception("DB error")):
        load_learned_chara_names()  # should not raise


def test_load_learned_chara_names_empty_db(monkeypatch):
    """DB が空の場合、_learned_chara_names は変わらない（空）。"""
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", {})
    with patch("bot.db.load_chara_names", return_value={}):
        load_learned_chara_names()
    assert _fetcher_module._learned_chara_names == {}


# ---------------------------------------------------------------------------
# _fetch_from_ewgf（内部関数）
# ---------------------------------------------------------------------------

def test_fetch_from_ewgf_success():
    """正常系: API レスポンスをパースしてバトルリストを返す。"""
    from bot.fetcher import _fetch_from_ewgf
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": [
        {
            "p1_tekken_id": "me", "p2_tekken_id": "opp",
            "winner": 1,
            "battle_at": "2024-01-15T12:00:00Z",
            "battle_type": "RANKED_BATTLE",
            "p1_char": "Jin", "p2_char": "Reina",
            "p1_rounds_won": 2, "p2_rounds_won": 1,
            "p1_dan_rank": 15, "p1_tekken_power": 10000,
            "p2_dan_rank": 12, "p2_tekken_power": 8000,
        }
    ]}
    mock_resp.raise_for_status.return_value = None
    mock_resp.headers = {}
    with patch.object(_fetcher_module._session, "get", return_value=mock_resp):
        result = _fetch_from_ewgf("me")
    assert len(result) == 1
    assert result[0]["won"] is True
    assert result[0]["my_chara"] == "Jin"


def test_fetch_from_ewgf_with_rate_limit_headers():
    """レート制限ヘッダーがあっても正常動作する。"""
    from bot.fetcher import _fetch_from_ewgf
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status.return_value = None
    mock_resp.headers = {
        "X-RateLimit-Remaining": "95",
        "X-RateLimit-Reset": "1234567890",
    }
    with patch.object(_fetcher_module._session, "get", return_value=mock_resp):
        result = _fetch_from_ewgf("me")
    assert result == []


def test_fetch_from_ewgf_uses_battles_fallback_key():
    """data キーがなく battles キーがある場合も動作する。"""
    from bot.fetcher import _fetch_from_ewgf
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"battles": []}
    mock_resp.raise_for_status.return_value = None
    mock_resp.headers = {}
    with patch.object(_fetcher_module._session, "get", return_value=mock_resp):
        result = _fetch_from_ewgf("me")
    assert result == []


# ---------------------------------------------------------------------------
# _fetch_from_wank_html（内部関数）
# ---------------------------------------------------------------------------

def _make_wank_html(ts: int, won: bool = True) -> str:
    rc_class = "win" if won else "lose"
    rc_sign  = "+" if won else ""
    rc_val   = 50 if won else -30
    return f"""
    <table><tbody><tr>
      <td class="battle-at"><script>printDateTime({ts})</script></td>
      <td class="left">
        <span class="char">Jin</span>
        <span class="rating">10000</span>
        <span class="{rc_class}">{rc_sign}{rc_val}</span>
      </td>
      <td class="result">2-1</td>
      <td class="right">
        <span class="char">Reina</span>
        <span class="player"><a href="/player/opp123">TestOpp</a></span>
      </td>
    </tr></tbody></table>
    """


def test_fetch_from_wank_html_returns_new_battles():
    """since_ts より新しいバトルを返す。"""
    from bot.fetcher import _fetch_from_wank_html
    ts = 1705320000
    mock_resp = MagicMock()
    mock_resp.text = _make_wank_html(ts + 100)
    mock_resp.raise_for_status.return_value = None
    with patch.object(_fetcher_module._session, "get", return_value=mock_resp):
        result = _fetch_from_wank_html(ts, "me")
    assert len(result) == 1
    assert result[0]["my_chara"] == "Jin"
    assert result[0]["won"] is True


def test_fetch_from_wank_html_filters_old():
    """since_ts 以前のバトルは含まない。"""
    from bot.fetcher import _fetch_from_wank_html
    ts = 1705320000
    mock_resp = MagicMock()
    mock_resp.text = _make_wank_html(ts - 100)
    mock_resp.raise_for_status.return_value = None
    with patch.object(_fetcher_module._session, "get", return_value=mock_resp):
        result = _fetch_from_wank_html(ts, "me")
    assert result == []


# ---------------------------------------------------------------------------
# _fetch_bulk_batch（内部関数）
# ---------------------------------------------------------------------------

def test_fetch_bulk_batch_returns_list():
    """正常系: バルクAPIのレスポンスを返す。"""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"battle_id": 123, "battle_at": 1000, "p1_polaris_id": "me"},
    ]
    mock_resp.raise_for_status.return_value = None
    with patch.object(_fetcher_module._session, "get", return_value=mock_resp):
        result = _fetch_bulk_batch(1010)
    assert len(result) == 1
    assert result[0]["battle_id"] == 123


def test_fetch_bulk_batch_raises_on_error():
    """HTTP エラー時は例外を再送出する。"""
    with patch.object(_fetcher_module._session, "get", side_effect=requests.RequestException("down")):
        with pytest.raises(requests.RequestException):
            _fetch_bulk_batch(1010)


# ---------------------------------------------------------------------------
# _build_bulk_index（内部関数）
# ---------------------------------------------------------------------------

def _simple_battle(battle_at: int) -> dict:
    return {
        "battle_id": f"wank_{battle_at}_opp",
        "battle_at": battle_at,
        "battle_type": None, "game_version": None, "stage_id": None,
        "source": "wank_html", "won": True,
        "my_chara": "Jin", "my_chara_id": None, "my_rounds": 2,
        "my_rank": None, "my_power": None, "my_region": None,
        "rating_before": 10000, "rating_change": 50,
        "opp_name": "Opp", "opp_polaris_id": "opp_pid",
        "opp_chara": "Reina", "opp_chara_id": None, "opp_rounds": 1,
        "opp_rank": None, "opp_power": None, "opp_region": None,
        "opp_rating_before": None, "opp_rating_change": None,
    }


def test_build_bulk_index_matches_battle():
    """バルクAPIにマッチするバトルがインデックスに登録される。"""
    battle = _simple_battle(1000)
    bulk_record = {
        "battle_id": 99, "battle_at": 1000,
        "p1_polaris_id": "me", "p2_polaris_id": "opp_pid",
    }
    with patch.object(_fetcher_module, "_fetch_bulk_batch", return_value=[bulk_record]):
        bulk_index, requests_made = _build_bulk_index([battle], "me")
    assert 1000 in bulk_index
    assert requests_made == 1


def test_build_bulk_index_empty_batch():
    """バルクAPIが空を返す → インデックスは空。"""
    battle = _simple_battle(1000)
    with patch.object(_fetcher_module, "_fetch_bulk_batch", return_value=[]):
        bulk_index, _ = _build_bulk_index([battle], "me")
    assert bulk_index == {}


def test_build_bulk_index_api_error_skips():
    """API エラー → そのバトルをスキップして続行。"""
    battle = _simple_battle(1000)
    with patch.object(_fetcher_module, "_fetch_bulk_batch",
                      side_effect=requests.RequestException("error")):
        bulk_index, _ = _build_bulk_index([battle], "me")
    assert bulk_index == {}


def test_build_bulk_index_skips_unrelated_records():
    """自分の polaris_id を含まないレコードはインデックスに入らない。"""
    battle = _simple_battle(1000)
    bulk_record = {
        "battle_id": 99, "battle_at": 1000,
        "p1_polaris_id": "other1", "p2_polaris_id": "other2",
    }
    with patch.object(_fetcher_module, "_fetch_bulk_batch", return_value=[bulk_record]):
        bulk_index, _ = _build_bulk_index([battle], "me")
    assert bulk_index == {}


# ---------------------------------------------------------------------------
# _enrich_from_bulk（内部関数）
# ---------------------------------------------------------------------------

def test_enrich_from_bulk_empty():
    """空のバトルリストは空のまま返す。"""
    result = _enrich_from_bulk([], "me")
    assert result == []


def test_enrich_from_bulk_enriches_matched_battle():
    """バルクAPIにマッチするバトルが ranked に変換される。"""
    battle = _simple_battle(1000)
    bulk_record = {
        "battle_id": 99, "battle_at": 1000,
        "battle_type": 2, "game_version": "1.0", "stage_id": 3,
        "p1_polaris_id": "me", "p2_polaris_id": "opp_pid",
        "p1_chara_id": 6, "p1_rank": 15, "p1_power": 10000, "p1_region_id": "JP",
        "p2_chara_id": 33, "p2_rank": 12, "p2_power": 8000, "p2_region_id": "US",
    }
    with patch.object(_fetcher_module, "_build_bulk_index",
                      return_value=({1000: bulk_record}, 1)):
        result = _enrich_from_bulk([battle], "me")
    assert len(result) == 1
    assert result[0]["battle_type"] == "ranked"
    assert result[0]["source"] == "wank_bulk"


def test_enrich_from_bulk_unmatched_battle_returns_as_is():
    """バルクAPIにマッチしないバトルはそのまま返す。"""
    battle = _simple_battle(9999)
    bulk_record = {
        "battle_id": 99, "battle_at": 1000,
        "battle_type": 2, "game_version": "1.0", "stage_id": 3,
        "p1_polaris_id": "me", "p2_polaris_id": "opp_pid",
        "p1_chara_id": 6, "p1_rank": 15, "p1_power": 10000, "p1_region_id": "JP",
        "p2_chara_id": 33, "p2_rank": 12, "p2_power": 8000, "p2_region_id": "US",
    }
    with patch.object(_fetcher_module, "_build_bulk_index",
                      return_value=({1000: bulk_record}, 1)):
        result = _enrich_from_bulk([battle], "me")
    assert result[0]["source"] == "wank_html"  # unchanged
