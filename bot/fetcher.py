"""
バトルデータ取得モジュール。

戦略:
  1. wank HTML で自分のバトル一覧取得 → バルクAPIでリッチデータを付加（メイン）
  2. ewgf.gg API（wank が完全に失敗した場合のフォールバック）
  3. wank HTML のみ（バルクAPI失敗時の最終フォールバック）
"""

import logging
import re
import sqlite3
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from bot.config import (
    EWGF_API_KEY as API_KEY, POLARIS_ID, TIMEOUT_API,
    RETRY_TOTAL, RETRY_BACKOFF_FACTOR, RETRY_STATUS_CODES,
    WANK_FETCH_LIMIT, UNKNOWN_CHARACTER,
)
from bot.stats import get_most_common

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP セッション（リトライ付き）
# ---------------------------------------------------------------------------

_retry = Retry(
    total=RETRY_TOTAL,
    backoff_factor=RETRY_BACKOFF_FACTOR,
    status_forcelist=RETRY_STATUS_CODES,
    allowed_methods=["GET"],
)
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))

# ---------------------------------------------------------------------------
# 動的キャラクター名学習
# ---------------------------------------------------------------------------

# DB から起動時にロードし、enrichment で随時更新される
# 複数スレッドからアクセスされるためロックで保護する
_learned_chara_names: dict[int, str] = {}
_chara_lock = threading.Lock()

EWGF_API    = "https://api.ewgf.gg/external"
WANK_BULK   = "https://wank.wavu.wiki/api/replays"
WANK_PLAYER = "https://wank.wavu.wiki/player"

CHARA_NAMES = {
    # wank bulk API のキャラID（0-indexed）
    # ベースキャラ 0-24 はオリジナル 0-indexed（シフトなし）
    # DLC キャラは 25 以降に追加（未確認スロットあり）
    0: "Paul",
    1: "Law", 2: "King", 3: "Yoshimitsu", 4: "Hwoarang",
    5: "Xiaoyu", 6: "Jin", 7: "Kazuya", 8: "Bryan", 9: "Steve",
    10: "Jack-8", 11: "Asuka", 12: "Devil Jin", 13: "Feng", 14: "Lili",
    15: "Dragunov", 16: "Leo", 17: "Lars", 18: "Alisa", 19: "Claudio",
    20: "Shaheen", 21: "Nina", 22: "Lee", 23: "Kuma", 24: "Panda",
    # 25-27: DLC（未確認）
    28: "Zafina", 29: "Leroy",
    # 30-31: DLC（未確認）
    32: "Jun", 33: "Reina", 34: "Azucena", 35: "Victor", 36: "Raven",
    # 37: DLC（未確認）
    38: "Eddy", 39: "Lidia", 40: "Heihachi", 41: "Clive",
    42: "Anna", 43: "Fahkumram", 44: "Armor King", 45: "Miary Zo",
}

# battle_type の数値 → 文字列マッピング
# wank.wavu.wiki はランク戦（2）のみ収録。他の値は現時点で未観測。
BATTLE_TYPES = {
    2: "ranked",
}


def get_chara_name(chara_id: int | None) -> str | None:
    """キャラクターIDから名前を返す。DB学習済み名 → CHARA_NAMES → "Chara#N" の優先順。"""
    if chara_id is None:
        return None
    with _chara_lock:
        return _learned_chara_names.get(chara_id) or CHARA_NAMES.get(chara_id, f"Chara#{chara_id}")


def _learn_chara_name(chara_id: int, name: str) -> None:
    """新しいキャラクター名マッピングをメモリと DB に保存する。"""
    with _chara_lock:
        if chara_id in _learned_chara_names or chara_id in CHARA_NAMES:
            return
        _learned_chara_names[chara_id] = name
    try:
        from bot.db import save_chara_name
        save_chara_name(chara_id, name)
        logger.info(f"[fetcher] 新キャラクターを学習: ID={chara_id} → {name}")
    except sqlite3.Error as e:
        logger.warning(f"[fetcher] キャラクター名DB保存失敗: {e}")


def _verify_and_learn_chara_name(chara_id: int, html_name: str) -> None:
    """HTML スクレイプ名と既知マッピングを照合し、不一致ならログ警告・上書き学習する。

    HTML名は wank サイトから直接取得した正確な名前として扱う。
    CHARA_NAMES との差異を検出することで、マッピング誤りを自動観測できる。
    """
    should_save = False
    is_mismatch = False
    is_new = False

    with _chara_lock:
        if _learned_chara_names.get(chara_id) == html_name:
            return
        known_static = CHARA_NAMES.get(chara_id)
        if known_static == html_name and chara_id not in _learned_chara_names:
            return  # 静的マッピングと一致、学習不要
        is_new = known_static is None and chara_id not in _learned_chara_names
        is_mismatch = known_static is not None and known_static != html_name
        _learned_chara_names[chara_id] = html_name
        should_save = True

    if not should_save:
        return
    if is_mismatch:
        logger.warning(
            f"[fetcher] キャラID不一致検出: ID={chara_id} "
            f"CHARA_NAMES={CHARA_NAMES.get(chara_id)!r} HTML={html_name!r} → HTML名を優先"
        )
    elif is_new:
        logger.info(f"[fetcher] 新キャラクターを学習: ID={chara_id} → {html_name}")
    try:
        from bot.db import save_chara_name
        save_chara_name(chara_id, html_name)
    except sqlite3.Error as e:
        logger.warning(f"[fetcher] キャラクター名DB保存失敗: {e}")


def load_learned_chara_names() -> None:
    """DB から学習済みキャラクター名をロードする（起動時・init_db 後に呼ぶ）。"""
    global _learned_chara_names
    try:
        from bot.db import load_chara_names
        loaded = load_chara_names()
        with _chara_lock:
            _learned_chara_names = loaded
        if loaded:
            logger.info(f"[fetcher] 学習済みキャラ名 {len(loaded)} 件をロード: {loaded}")
    except Exception as e:
        logger.warning(f"[fetcher] 学習済みキャラ名ロード失敗: {e}")


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
    resp = _session.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=TIMEOUT_API)
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

def _fetch_from_wank_html(since_ts: float, polaris_id: str, limit: int = WANK_FETCH_LIMIT) -> list[dict]:
    resp = _session.get(f"{WANK_PLAYER}/{polaris_id}", timeout=TIMEOUT_API)
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
    resp = _session.get(
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
        html_name = battle.get("my_chara")
        if html_name:
            # HTML名が正 → chara_id との対応を検証・学習し、HTML名をそのまま維持
            _verify_and_learn_chara_name(battle["my_chara_id"], html_name)
        else:
            # HTML名なし → CHARA_NAMES から補完
            mapped = get_chara_name(battle["my_chara_id"])
            if mapped and not mapped.startswith("Chara#"):
                battle["my_chara"] = mapped

    if battle["opp_chara_id"] is not None:
        html_name = battle.get("opp_chara")
        if html_name:
            _verify_and_learn_chara_name(battle["opp_chara_id"], html_name)
        else:
            mapped = get_chara_name(battle["opp_chara_id"])
            if mapped and not mapped.startswith("Chara#"):
                battle["opp_chara"] = mapped

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
        except requests.RequestException as e:
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

def fetch_opponent_summary(polaris_id: str, limit: int = 20) -> dict | None:
    """
    対戦相手の直近バトル履歴（wank HTML）を取得してサマリーを返す。
    失敗時は None を返す（投稿は続行）。
    """
    try:
        battles = _fetch_from_wank_html(since_ts=0, polaris_id=polaris_id, limit=limit)
        if not battles:
            return None

        wins  = sum(1 for b in battles if b["won"])
        total = len(battles)

        # メインキャラ（最多使用）— 相手視点なので my_chara が相手のキャラ
        main_chara, _ = get_most_common(battles, "my_chara")

        # 直近10戦の調子（wank HTML は新着順）
        recent       = battles[:10]
        recent_wins  = sum(1 for b in recent if b["won"])
        recent_total = len(recent)

        return {
            "total":            total,
            "win_rate":         wins / total * 100,
            "main_chara":       main_chara,
            "recent_wins":      recent_wins,
            "recent_total":     recent_total,
            "recent_win_rate":  recent_wins / recent_total * 100 if recent_total else 0,
        }
    except requests.RequestException as e:
        logger.warning(f"[fetcher] 対戦相手スカウト失敗 ({polaris_id}): {e}")
        return None


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
    except requests.RequestException as e:
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
    except requests.RequestException as e:
        logger.warning(f"[fetcher] wank HTML 失敗 ({e})")

    if wank_ok:
        if html_battles:
            try:
                return _enrich_from_bulk(html_battles, pid)
            except requests.RequestException as e:
                logger.warning(f"[fetcher] enrichment 失敗（HTMLデータのみで続行）: {e}")
        return html_battles

    # 2. ewgf.gg（wank が完全失敗した場合のフォールバック）
    try:
        battles = _fetch_from_ewgf(pid)
        result = [b for b in battles if b["battle_at"] > since_ts]
        logger.info(f"[fetcher] ewgf.gg フォールバック: {len(result)} 件")
        return result
    except requests.RequestException as e:
        logger.warning(f"[fetcher] ewgf.gg 失敗 ({e})")

    # 3. wank HTML のみ（最終手段）
    logger.warning("[fetcher] wank HTML 再試行（最終フォールバック）")
    return _fetch_from_wank_html(since_ts, pid)
