"""
bot/fetcher.py のテスト。
純粋な変換・パース関数と、requests をモックしたネットワーク層のテストを含む。
"""

import pytest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup

from bot.fetcher import (
    get_chara_name,
    _normalize_ewgf,
    _merge_bulk,
    _parse_wank_html_row,
    fetch_battles_since,
    fetch_quick_battles_from_ewgf,
    CHARA_NAMES,
    _learned_chara_names,
)
import bot.fetcher as _fetcher_module


# ---------------------------------------------------------------------------
# get_chara_name
# ---------------------------------------------------------------------------

def test_get_chara_name_known_id():
    assert get_chara_name(7) == "Jin"
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
        "p1_chara_id":    7,        # Jin
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
    battle = _html_battle()
    result = _merge_bulk(battle, _bulk_record(p1_polaris_id="opp_pid", p2_polaris_id="me"), "me")
    assert result["my_chara"] == "Reina"
    assert result["opp_chara"] == "Jin"
    assert result["my_rank"] == 12


def test_merge_bulk_unknown_id_keeps_html_name(monkeypatch):
    """未知のキャラID（Chara#N）の場合、HTML名を保持して学習する。"""
    learned: dict = {}
    monkeypatch.setattr(_fetcher_module, "_learned_chara_names", learned)
    # DB 保存は無効化
    monkeypatch.setattr(_fetcher_module, "_learn_chara_name",
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
    mock_enrich.side_effect = Exception("bulk API down")

    result = fetch_battles_since(1000, polaris_id="me")

    assert len(result) == 1
    assert result[0]["source"] == "wank_bulk"


@patch("bot.fetcher._fetch_from_ewgf")
@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_battles_since_falls_back_to_ewgf(mock_wank, mock_ewgf):
    """wank 完全失敗 → ewgf.gg にフォールバック。"""
    mock_wank.side_effect = Exception("wank down")
    ewgf_battle = {**_mock_battle(2000), "source": "ewgf"}
    mock_ewgf.return_value = [ewgf_battle]

    result = fetch_battles_since(1000, polaris_id="me")

    assert len(result) == 1
    mock_ewgf.assert_called_once()


@patch("bot.fetcher._fetch_from_wank_html")
@patch("bot.fetcher._fetch_from_ewgf")
def test_fetch_battles_since_falls_back_to_wank_retry(mock_ewgf, mock_wank):
    """wank 失敗 + ewgf 失敗 → wank を再試行（最終フォールバック）。"""
    mock_ewgf.side_effect = Exception("ewgf also down")
    battle = _mock_battle(2000)
    mock_wank.side_effect = [Exception("first call fails"), [battle]]

    result = fetch_battles_since(1000, polaris_id="me")

    assert len(result) == 1
    assert mock_wank.call_count == 2  # 最初の失敗 + 再試行


@patch("bot.fetcher._fetch_from_wank_html")
def test_fetch_battles_since_filters_old_battles(mock_wank):
    """since_ts より古いバトルは ewgf フォールバック時に除外される。"""
    old_battle = _mock_battle(500)   # since_ts=1000 より古い
    new_battle = _mock_battle(2000)
    mock_wank.side_effect = Exception("wank down")

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
    mock_ewgf.side_effect = Exception("ewgf down")
    result = fetch_quick_battles_from_ewgf(0, polaris_id="me")
    assert result == []
