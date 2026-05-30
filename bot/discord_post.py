"""
Discord Webhook にバトルサマリーを投稿する I/O モジュール。

Embed（dict）の構築は bot.embeds が担当する。このモジュールは送信・編集・
通知——HTTP を伴う副作用のみを扱う。
"""

import json
import logging
import re
import requests
from datetime import datetime
from requests.adapters import HTTPAdapter
from typing import Any
from urllib3.util.retry import Retry

from bot.config import (
    WEBHOOK_URLS, ERROR_WEBHOOK_URLS, TEKKEN_ID,
    TIMEOUT_WEBHOOK, TIMEOUT_WEBHOOK_IMAGE, JST,
    RETRY_TOTAL, RETRY_BACKOFF_FACTOR,
)
from bot.models import Battle
from bot.embeds import (
    build_embed, build_weekly_embed, build_monthly_embed,
    build_rank_change_embed, build_community_weekly_embed,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Webhook 専用 HTTP セッション（リトライ付き）
# ---------------------------------------------------------------------------

_webhook_retry = Retry(
    total=RETRY_TOTAL,
    backoff_factor=RETRY_BACKOFF_FACTOR,
    status_forcelist=[500, 502, 503],
    allowed_methods=["GET", "POST", "PATCH"],
)
_webhook_session = requests.Session()
_webhook_session.mount("https://", HTTPAdapter(max_retries=_webhook_retry))


def _parse_webhook_id_token(url: str) -> tuple[str, str] | None:
    """Webhook URL から (webhook_id, token) を抽出する。"""
    m = re.match(r"https://discord(?:app)?\.com/api/webhooks/(\d+)/([^/?]+)", url)
    return (m.group(1), m.group(2)) if m else None


# ---------------------------------------------------------------------------
# 投稿
# ---------------------------------------------------------------------------

def _send_to_webhooks(
    embed: dict,
    chart: Any | None = None,
    filename: str = "image.png",
    log_label: str = "投稿",
) -> list[tuple[str, str]]:
    """全 Webhook に Embed を送信し、成功した (message_id, url) のリストを返す。"""
    results: list[tuple[str, str]] = []
    for url in WEBHOOK_URLS:
        try:
            wait_url = url + "?wait=true"
            if chart:
                chart.seek(0)
                resp = _webhook_session.post(
                    wait_url,
                    data={"payload_json": json.dumps({"embeds": [embed]})},
                    files={"files[0]": (filename, chart, "image/png")},
                    timeout=TIMEOUT_WEBHOOK_IMAGE,
                )
            else:
                resp = _webhook_session.post(wait_url, json={"embeds": [embed]}, timeout=TIMEOUT_WEBHOOK)
            resp.raise_for_status()
            results.append((resp.json()["id"], url))
        except requests.RequestException as e:
            logger.warning(f"[discord_post] {log_label}失敗 ({url[:60]}): {e}")
    return results


def notify(message: str) -> None:
    """任意のメッセージを全 Discord Webhook に投稿する。失敗しても例外は出さない。"""
    for url in WEBHOOK_URLS:
        try:
            _webhook_session.post(url, json={"content": message}, timeout=TIMEOUT_WEBHOOK)
        except requests.RequestException as e:
            logger.warning(f"[discord_post] 通知失敗: {e}")


def notify_error(message: str) -> None:
    """エラーを Discord Webhook に通知する。失敗しても例外は出さない。
    DISCORD_ERROR_WEBHOOK_URL が設定されていればそちらへ、未設定なら通常チャンネルへ。
    """
    targets = ERROR_WEBHOOK_URLS or WEBHOOK_URLS
    for url in targets:
        try:
            _webhook_session.post(url, json={"content": f"⚠️ {message}"}, timeout=TIMEOUT_WEBHOOK)
        except requests.RequestException as e:
            logger.warning(f"[discord_post] エラー通知失敗: {e}")


def post(
    battles: list[Battle],
    date_str: str | None = None,
    player_name: str | None = None,
    scout_data: dict[str, dict] | None = None,
) -> tuple[list[tuple[str, str]], dict] | None:
    """
    全 Discord Webhook に Embed サマリーを投稿。
    成功時は ([(message_id, webhook_url), ...], embed) を返す。試合なし・全失敗時は None。
    LLM コメントは含まず、後から edit_llm_comment() で追記する。
    """
    if not WEBHOOK_URLS:
        raise ValueError("DISCORD_WEBHOOK_URL が .env に設定されていません")

    if date_str is None:
        date_str = datetime.now(JST).strftime("%Y/%m/%d")

    if not battles:
        logger.info("[discord_post] 本日の試合なし。投稿をスキップ。")
        return None

    # グラフ生成を試みる
    chart = None
    try:
        from bot.graph import generate_rating_chart
        chart = generate_rating_chart(battles, player_name or TEKKEN_ID)
    except Exception as e:
        logger.warning(f"[discord_post] グラフ生成失敗（スキップ）: {e}")

    embed = build_embed(battles, date_str, player_name, scout_data=scout_data, has_chart=bool(chart))
    if embed is None:
        return None

    results = _send_to_webhooks(embed, chart, filename="rating.png")
    return (results, embed) if results else None


def post_weekly(
    battles: list[Battle],
    week_start_str: str,
    player_name: str | None = None,
) -> tuple[list[tuple[str, str]], dict] | None:
    """
    週次サマリーを全 Discord Webhook に Embed 形式で投稿。
    成功時は ([(message_id, webhook_url), ...], embed) を返す。試合なし・全失敗時は None。
    """
    if not WEBHOOK_URLS:
        raise ValueError("DISCORD_WEBHOOK_URL が .env に設定されていません")

    embed = build_weekly_embed(battles, week_start_str, player_name)
    if embed is None:
        logger.info(f"[discord_post][{player_name}] 今週の試合なし。週次投稿をスキップ。")
        return None

    # キャラ使用率グラフ生成
    chara_chart = None
    try:
        from bot.graph import generate_chara_usage_chart
        import bot.db as _db
        weekly_data = _db.get_weekly_my_chara_counts(player_name=player_name)
        chara_chart = generate_chara_usage_chart(weekly_data, player_name or TEKKEN_ID)
    except Exception as e:
        logger.warning(f"[discord_post] キャラグラフ生成失敗（スキップ）: {e}")

    results = _send_to_webhooks(embed, chara_chart, filename="chara_usage.png", log_label="週次投稿")
    return (results, embed) if results else None


def post_monthly(
    battles: list[Battle],
    month_str: str,
    player_name: str | None = None,
    prev_battles: list[Battle] | None = None,
) -> tuple[list[tuple[str, str]], dict] | None:
    """
    月次サマリーを全 Discord Webhook に Embed 形式で投稿。
    成功時は ([(message_id, webhook_url), ...], embed) を返す。試合なし・全失敗時は None。
    """
    if not WEBHOOK_URLS:
        raise ValueError("DISCORD_WEBHOOK_URL が .env に設定されていません")

    embed = build_monthly_embed(battles, month_str, player_name, prev_battles)
    if embed is None:
        logger.info(f"[discord_post][{player_name}] 今月の試合なし。月次投稿をスキップ。")
        return None

    results = _send_to_webhooks(embed, log_label="月次投稿")
    return (results, embed) if results else None


def post_rank_change(player_name: str, old_rank: int, new_rank: int) -> None:
    """段位変化を Embed で全 Webhook に通知する。失敗しても例外は出さない。"""
    if not WEBHOOK_URLS:
        return
    embed = build_rank_change_embed(player_name, old_rank, new_rank)
    _send_to_webhooks(embed, log_label="段位変化通知")


def post_community_weekly(players_stats: list[dict], week_start_str: str) -> None:
    """部内週次ランキングを全 Discord Webhook に投稿する。2人以上いる場合のみ投稿。"""
    if not WEBHOOK_URLS or len(players_stats) < 2:
        return
    embed = build_community_weekly_embed(players_stats, week_start_str)
    for url in WEBHOOK_URLS:
        try:
            resp = _webhook_session.post(url, json={"embeds": [embed]}, timeout=TIMEOUT_WEBHOOK)
            resp.raise_for_status()
            logger.info("[discord_post] 部内ランキング投稿完了")
        except requests.RequestException as e:
            logger.warning(f"[discord_post] 部内ランキング投稿失敗: {e}")


def edit_llm_comment(
    message_ids: list[tuple[str, str]],
    embed: dict,
    llm_comment: str,
) -> None:
    """
    投稿済み Embed の description 冒頭に LLM コメントを追記する（PATCH）。
    message_ids は [(message_id, webhook_url), ...] のリスト。
    チャート添付ファイルを保持するため GET → PATCH の順で処理する。
    失敗しても例外は出さない。
    """
    import time as _time

    original_desc = embed.get("description", "")
    llm_block = f"💬 {llm_comment}\n\n"
    updated = {**embed, "description": (llm_block + original_desc)[:4096]}
    get_timeout = max(TIMEOUT_WEBHOOK * 3, 30)  # GET は余裕を持って

    for message_id, webhook_url in message_ids:
        parts = _parse_webhook_id_token(webhook_url)
        if not parts:
            continue
        webhook_id, token = parts
        msg_url = f"https://discord.com/api/webhooks/{webhook_id}/{token}/messages/{message_id}"

        # 既存の添付ファイル ID を保持するため現在のメッセージを取得（最大3回リトライ）
        attachments: list[dict] = []
        get_ok = False
        for attempt in range(3):
            try:
                get_resp = _webhook_session.get(msg_url, timeout=get_timeout)
                get_resp.raise_for_status()
                attachments = get_resp.json().get("attachments", [])
                get_ok = True
                break
            except requests.RequestException as e:
                if attempt < 2:
                    logger.warning(f"[discord_post] メッセージ取得リトライ ({attempt + 1}/3): {e}")
                    _time.sleep(5)
                else:
                    logger.warning(f"[discord_post] メッセージ取得失敗（3回失敗、スキップ）: {e}")

        if not get_ok:
            continue  # attachment ID 不明のまま PATCH すると description が反映されない場合がある

        patch_body: dict = {"embeds": [updated]}
        if attachments:
            patch_body["attachments"] = [{"id": a["id"]} for a in attachments]

        try:
            resp = _webhook_session.patch(msg_url, json=patch_body, timeout=TIMEOUT_WEBHOOK)
            resp.raise_for_status()
            # レスポンスで description が反映されたか確認
            resp_embeds = resp.json().get("embeds", [{}])
            applied_desc = resp_embeds[0].get("description", "") if resp_embeds else ""
            if llm_block[:20] in applied_desc:
                logger.info("[discord_post] LLMコメントを Embed に追記しました。")
            else:
                logger.warning(
                    f"[discord_post] LLMコメント追記: PATCH 200 だが description 未反映。"
                    f"applied={applied_desc[:80]!r}"
                )
        except requests.RequestException as e:
            logger.warning(f"[discord_post] LLMコメント追記失敗: {e}")
