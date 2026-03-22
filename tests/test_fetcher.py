"""
bot/fetcher.py のテスト。
外部API呼び出しを含む関数は対象外とし、純粋な変換・パース関数のみをテストする。
"""

import pytest
from bs4 import BeautifulSoup

from bot.fetcher import (
    get_chara_name,
    _normalize_ewgf,
    _merge_bulk,
    _parse_wank_html_row,
    CHARA_NAMES,
)


# ---------------------------------------------------------------------------
# get_chara_name
# ---------------------------------------------------------------------------

def test_get_chara_name_known_id():
    assert get_chara_name(6) == "Jin"
    assert get_chara_name(28) == "Reina"


def test_get_chara_name_unknown_id():
    assert get_chara_name(99) == "Chara#99"


def test_get_chara_name_none():
    assert get_chara_name(None) is None


def test_get_chara_name_all_defined():
    """CHARA_NAMES の全IDが文字列を返すことを確認。"""
    for cid in CHARA_NAMES:
        assert isinstance(get_chara_name(cid), str)


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
        "p2_chara_id":    28,       # Reina
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
