"""
バトルデータ取得モジュール。

戦略:
  1. wank HTML で自分のバトル一覧取得 → バルクAPIでリッチデータを付加（メイン）
  2. ewgf.gg API（wank が完全に失敗した場合のフォールバック）
  3. wank HTML のみ（バルクAPI失敗時の最終フォールバック）
"""

import logging
import re
import requests
from bs4 import BeautifulSoup

from bot.config import EWGF_API_KEY as API_KEY, POLARIS_ID, TIMEOUT_API

logger = logging.getLogger(__name__)

EWGF_API    = "https://api.ewgf.gg/external"
WANK_BULK   = "https://wank.wavu.wiki/api/replays"
WANK_PLAYER = "https://wank.wavu.wiki/player"

CHARA_NAMES = {
    # wank bulk API のキャラID（1-indexed。0 も Paul として記録される場合あり）
    # Season 2 DLC 追加により Zafina 以降がシフト: Zafina/Leroy +2、Jun 以降 +4、
    # Season1 DLC（Eddy-Clive）は +5、Season2 末尾に Anna/Fahkumram/Armor King/Miary Zo
    0: "Paul",
    1: "Paul", 2: "Law", 3: "King", 4: "Yoshimitsu", 5: "Hwoarang",
    6: "Xiaoyu", 7: "Jin", 8: "Bryan", 9: "Kazuya", 10: "Steve",
    11: "Jack-8", 12: "Asuka", 13: "Devil Jin", 14: "Feng", 15: "Lili",
    16: "Dragunov", 17: "Leo", 18: "Lars", 19: "Alisa", 20: "Claudio",
    21: "Shaheen", 22: "Nina", 23: "Lee", 24: "Kuma", 25: "Panda",
    # 26-27: Season 2 DLC（未確認）
    28: "Zafina", 29: "Leroy",
    # 30-31: Season 2 DLC（未確認）
    32: "Jun", 33: "Reina", 34: "Azucena", 35: "Victor", 36: "Raven",
    # 37: Season 2 DLC（未確認）
    38: "Eddy", 39: "Lidia", 40: "Heihachi", 41: "Clive",
    42: "Anna", 43: "Fahkumram", 44: "Armor King", 45: "Miary Zo",
}

# battle_type の数値 → 文字列マッピング
# wank.wavu.wiki はランク戦（2）のみ収録。他の値は現時点で未観測。
BATTLE_TYPES = {
    2: "ranked",
}


def get_chara_name(chara_id: int | None) -> str | None:
    if chara_id is None:
        return None
    return CHARA_NAMES.get(chara_id, f"Chara#{chara_id}")


# ---------------------------------------------------------------------------
# ewgf.gg
# ---------------------------------------------------------------------------

EWGF_BATTLE_TYPES = {
    "RANKED_BATTLE":  "ranked",
    "QUICK_BATTLE":   "quick",
    "PLAYER_BATTLE":  "player",
}


def _fetch_from_ewgf(polaris_id: str) -> list[dict]:
    url = f"{EWGF_API}/battles/{polaris_id}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=TIMEOUT_API)
    resp.raise_for_status()
    data = resp.json()
    raw_list = data.get("data", data.get("battles", []))
    return [_normalize_ewgf(raw, polaris_id) for raw in raw_list]


def _normalize_ewgf(raw: dict, polaris_id: str) -> dict:
    from datetime import datetime

    me  = "p1" if raw.get("p1_tekken_id") == polaris_id else "p2"
    opp = "p2" if me == "p1" else "p1"

    winner = raw.get("winner")
    won = (winner == (1 if me == "p1" else 2))

    # ISO 8601 → unix timestamp
    battle_at_str = raw.get("battle_at", "")
    try:
        dt = datetime.fromisoformat(battle_at_str.replace("Z", "+00:00"))
        battle_at = int(dt.timestamp())
    except Exception:
        battle_at = 0

    battle_type_raw = raw.get("battle_type", "")
    battle_type = EWGF_BATTLE_TYPES.get(battle_type_raw, battle_type_raw.lower() if battle_type_raw else None)

    opp_tid = raw.get(f"{opp}_tekken_id", "")
    battle_id = f"ewgf_{battle_at}_{opp_tid}"

    return {
        "battle_id":         battle_id,
        "battle_at":         battle_at,
        "battle_type":       battle_type,
        "game_version":      raw.get("game_version"),
        "stage_id":          raw.get("stage_id"),
        "source":            "ewgf",
        "won":               won,
        "my_chara":          raw.get(f"{me}_char"),
        "my_chara_id":       None,
        "my_rounds":         raw.get(f"{me}_rounds_won", 0),
        "my_rank":           raw.get(f"{me}_dan_rank"),
        "my_power":          raw.get(f"{me}_tekken_power"),
        "my_region":         raw.get(f"{me}_region"),
        "rating_before":     None,
        "rating_change":     None,
        "opp_name":          raw.get(f"{opp}_name"),
        "opp_polaris_id":    raw.get(f"{opp}_tekken_id"),
        "opp_chara":         raw.get(f"{opp}_char"),
        "opp_chara_id":      None,
        "opp_rounds":        raw.get(f"{opp}_rounds_won", 0),
        "opp_rank":          raw.get(f"{opp}_dan_rank"),
        "opp_power":         raw.get(f"{opp}_tekken_power"),
        "opp_region":        raw.get(f"{opp}_region"),
        "opp_rating_before": None,
        "opp_rating_change": None,
    }


# ---------------------------------------------------------------------------
# wank HTML スクレイパー
# ---------------------------------------------------------------------------

def _fetch_from_wank_html(since_ts: float, polaris_id: str, limit: int = 50) -> list[dict]:
    resp = requests.get(f"{WANK_PLAYER}/{polaris_id}", timeout=TIMEOUT_API)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for row in soup.select("tr"):
        battle = _parse_wank_html_row(row)
        if battle and battle["battle_at"] > since_ts:
            results.append(battle)
        if len(results) >= limit:
            break
    return results


def _parse_wank_html_row(row) -> dict | None:
    td_at     = row.select_one("td.battle-at")
    td_left   = row.select_one("td.left")
    td_result = row.select_one("td.result")
    td_right  = row.select_one("td.right")

    if not (td_at and td_left and td_result and td_right):
        return None

    ts_match = re.search(r"printDateTime\((\d+)\)", td_at.decode_contents())
    if not ts_match:
        return None
    battle_at = int(ts_match.group(1))

    my_chara_tag  = td_left.select_one(".char")
    my_rating_tag = td_left.select_one(".rating")
    win_span      = td_left.select_one(".win")
    lose_span     = td_left.select_one(".lose")

    won = win_span is not None
    rc_text = (win_span or lose_span).get_text(strip=True) if (win_span or lose_span) else "0"
    try:
        rating_change = int(rc_text.replace("+", ""))
    except ValueError:
        rating_change = 0

    rating_before = None
    if my_rating_tag:
        m = re.search(r"(\d+)", my_rating_tag.get_text(separator=" ", strip=True))
        if m:
            rating_before = int(m.group(1))

    opp_chara_tag  = td_right.select_one(".char")
    opp_player_tag = td_right.select_one(".player a")
    opp_rating_tag = td_right.select_one(".rating")

    opp_name       = opp_player_tag.get_text(strip=True) if opp_player_tag else "???"
    opp_polaris_id = None
    if opp_player_tag and opp_player_tag.get("href"):
        m = re.search(r"/player/([^/]+)", opp_player_tag["href"])
        if m:
            opp_polaris_id = m.group(1)

    opp_rating_before, opp_rating_change = None, None
    if opp_rating_tag:
        m = re.search(r"(\d+)", opp_rating_tag.get_text(separator=" ", strip=True))
        if m:
            opp_rating_before = int(m.group(1))
        opp_rc_span = opp_rating_tag.select_one(".win, .lose")
        if opp_rc_span:
            try:
                opp_rating_change = int(opp_rc_span.get_text(strip=True).replace("+", ""))
            except ValueError:
                pass

    result_text = td_result.get_text(strip=True)
    my_rounds, opp_rounds = 0, 0
    rm = re.match(r"(\d+)-(\d+)", result_text)
    if rm:
        my_rounds, opp_rounds = int(rm.group(1)), int(rm.group(2))

    return {
        "battle_id":         f"wank_{battle_at}_{opp_polaris_id or opp_name}",
        "battle_at":         battle_at,
        "battle_type":       None,   # バルクAPIで補完
        "game_version":      None,
        "stage_id":          None,
        "source":            "wank_html",
        "won":               won,
        "my_chara":          my_chara_tag.get_text(strip=True) if my_chara_tag else None,
        "my_chara_id":       None,   # バルクAPIで補完
        "my_rounds":         my_rounds,
        "my_rank":           None,
        "my_power":          None,
        "my_region":         None,
        "rating_before":     rating_before,
        "rating_change":     rating_change,
        "opp_name":          opp_name,
        "opp_polaris_id":    opp_polaris_id,
        "opp_chara":         opp_chara_tag.get_text(strip=True) if opp_chara_tag else None,
        "opp_chara_id":      None,
        "opp_rounds":        opp_rounds,
        "opp_rank":          None,
        "opp_power":         None,
        "opp_region":        None,
        "opp_rating_before": opp_rating_before,
        "opp_rating_change": opp_rating_change,
    }


# ---------------------------------------------------------------------------
# wank バルクAPI（ピンポイントenrichment用）
# ---------------------------------------------------------------------------

def _fetch_bulk_batch(before: int) -> list[dict]:
    resp = requests.get(
        WANK_BULK,
        params={"before": before},
        headers={"Accept-Encoding": "gzip"},
        timeout=TIMEOUT_API,
    )
    resp.raise_for_status()
    return resp.json()


def _merge_bulk(battle: dict, bulk: dict, polaris_id: str) -> dict:
    """バルクAPIレコードをHTMLバトルにマージして返す。"""
    me  = "p1" if bulk.get("p1_polaris_id") == polaris_id else "p2"
    opp = "p2" if me == "p1" else "p1"

    bt_raw = bulk.get("battle_type")
    battle["battle_id"]         = str(bulk.get("battle_id", battle["battle_id"]))
    battle["battle_type"]       = BATTLE_TYPES.get(bt_raw, str(bt_raw) if bt_raw else None)
    battle["game_version"]      = bulk.get("game_version")
    battle["stage_id"]          = bulk.get("stage_id")
    battle["source"]            = "wank_bulk"
    battle["my_chara_id"]       = bulk.get(f"{me}_chara_id")
    battle["my_rank"]           = bulk.get(f"{me}_rank")
    battle["my_power"]          = bulk.get(f"{me}_power")
    battle["my_region"]         = bulk.get(f"{me}_region_id")
    battle["opp_chara_id"]      = bulk.get(f"{opp}_chara_id")
    battle["opp_rank"]          = bulk.get(f"{opp}_rank")
    battle["opp_power"]         = bulk.get(f"{opp}_power")
    battle["opp_region"]        = bulk.get(f"{opp}_region_id")
    if battle["my_chara_id"] is not None:
        battle["my_chara"] = get_chara_name(battle["my_chara_id"])
    if battle["opp_chara_id"] is not None:
        battle["opp_chara"] = get_chara_name(battle["opp_chara_id"])
    return battle


def _build_bulk_index(sorted_battles: list[dict], polaris_id: str) -> tuple[dict[int, dict], int]:
    """
    新しい順にソートされたバトルリストを最小 API リクエスト数でカバーし、
    タイムスタンプ → バルクレコードの辞書と総リクエスト数を返す。
    """
    bulk_by_ts: dict[int, dict] = {}
    requests_made = 0
    i = 0

    while i < len(sorted_battles):
        ts = sorted_battles[i]["battle_at"]
        try:
            batch = _fetch_bulk_batch(ts + 10)
            requests_made += 1
        except Exception as e:
            logger.warning(f"[fetcher] enrichment失敗 ts={ts}: {e}")
            i += 1
            continue

        if not batch:
            i += 1
            continue

        oldest = min(b["battle_at"] for b in batch)
        for r in batch:
            if r.get("p1_polaris_id") == polaris_id or r.get("p2_polaris_id") == polaris_id:
                bulk_by_ts[r["battle_at"]] = r

        # このバッチ範囲に含まれる全バトルをスキップ
        while i < len(sorted_battles) and sorted_battles[i]["battle_at"] >= oldest:
            i += 1

    return bulk_by_ts, requests_made


def _enrich_from_bulk(battles: list[dict], polaris_id: str) -> list[dict]:
    """
    HTMLバトルリストをバルクAPIでenrichする。

    バトルを700秒ウィンドウでグループ化し、1グループ=1リクエストで済ませる。
    1ゲームセッション分なら通常1〜3リクエスト。
    """
    if not battles:
        return battles

    sorted_battles = sorted(battles, key=lambda x: x["battle_at"], reverse=True)
    bulk_by_ts, requests_made = _build_bulk_index(sorted_battles, polaris_id)

    matched = sum(1 for b in battles if b["battle_at"] in bulk_by_ts)
    logger.info(f"[fetcher] enrichment完了: {requests_made}リクエスト, {matched}/{len(battles)} 件マッチ")

    return [_merge_bulk(b, bulk_by_ts[b["battle_at"]], polaris_id) if b["battle_at"] in bulk_by_ts else b
            for b in battles]


# ---------------------------------------------------------------------------
# 公開インターフェース
# ---------------------------------------------------------------------------

def fetch_quick_battles_from_ewgf(since_ts: float, polaris_id: str | None = None) -> list[dict]:
    """
    ewgf.gg からクイックマッチのみを取得する（週次サマリー補完用）。
    24時間遅延があるため日次投稿には使わず、DBへの保存のみを目的とする。
    """
    pid = polaris_id or POLARIS_ID
    try:
        battles = _fetch_from_ewgf(pid)
        result = [b for b in battles if b["battle_at"] > since_ts and b.get("battle_type") == "quick"]
        logger.info(f"[fetcher] ewgf.gg クイックマッチ: {len(result)} 件取得")
        return result
    except Exception as e:
        logger.warning(f"[fetcher] ewgf.gg クイックマッチ取得失敗: {e}")
        return []


def fetch_battles_since(since_ts: float, polaris_id: str | None = None) -> list[dict]:
    """
    since_ts より新しいバトルを返す。
    wank HTML + バルクenrichment → ewgf.gg（wank 失敗時）→ wank HTML のみ の順で試みる。
    """
    pid = polaris_id or POLARIS_ID

    # 1. wank HTML + バルクAPI enrichment（メイン・リアルタイム）
    wank_ok = False
    html_battles: list[dict] = []
    try:
        html_battles = _fetch_from_wank_html(since_ts, pid)
        wank_ok = True
        logger.info(f"[fetcher] wank HTML: {len(html_battles)} 件取得")
    except Exception as e:
        logger.warning(f"[fetcher] wank HTML 失敗 ({e})")

    if wank_ok:
        if html_battles:
            try:
                return _enrich_from_bulk(html_battles, pid)
            except Exception as e:
                logger.warning(f"[fetcher] enrichment 失敗（HTMLデータのみで続行）: {e}")
        return html_battles

    # 2. ewgf.gg（wank が完全失敗した場合のフォールバック）
    try:
        battles = _fetch_from_ewgf(pid)
        result = [b for b in battles if b["battle_at"] > since_ts]
        logger.info(f"[fetcher] ewgf.gg フォールバック: {len(result)} 件")
        return result
    except Exception as e:
        logger.warning(f"[fetcher] ewgf.gg 失敗 ({e})")

    # 3. wank HTML のみ（最終手段）
    logger.warning("[fetcher] wank HTML 再試行（最終フォールバック）")
    return _fetch_from_wank_html(since_ts, pid)
