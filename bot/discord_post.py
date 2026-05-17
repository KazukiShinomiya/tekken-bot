"""
Discord Webhook にバトルサマリーを投稿するモジュール。
"""

import json
import logging
import re
import requests
from collections import Counter
from datetime import datetime
from requests.adapters import HTTPAdapter
from typing import Any
from urllib3.util.retry import Retry

from bot.config import (
    WEBHOOK_URLS, ERROR_WEBHOOK_URLS, TEKKEN_ID,
    TIMEOUT_WEBHOOK, TIMEOUT_WEBHOOK_IMAGE, JST,
    DISCORD_EMBED_MAX_FIELDS,
    RETRY_TOTAL, RETRY_BACKOFF_FACTOR,
    RANK_NAMES, UNKNOWN_CHARACTER,
    WIN_RATE_THRESHOLD, EMBED_COLOR_GOOD_WR, EMBED_COLOR_BAD_WR,
    SCOUT_TREND_THRESHOLD,
)

from bot.models import Battle
from bot.stats import (
    calculate_streak, aggregate_by_character, count_wins, count_losses,
    filter_rated_battles, detect_momentum, predict_rating_trend,
    get_most_common,
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
# スタッツ計算
# ---------------------------------------------------------------------------

def _win_rate(battles: list[Battle]) -> str:
    if not battles:
        return "-"
    pct = count_wins(battles) / len(battles) * 100
    return f"{pct:.0f}%"


def _streak(sorted_battles: list[Battle]) -> tuple[int, int]:
    """時系列順バトルリストから (最長連勝, 最長連敗) を返す。"""
    return calculate_streak(sorted_battles)


def _nemesis(battles: list[Battle]) -> str | None:
    """2戦以上対戦したキャラの中で、最も勝率が低いキャラを返す。"""
    stats = aggregate_by_character(battles)

    candidates = [(chara, results) for chara, results in stats.items() if len(results) >= 2]
    if not candidates:
        return None

    worst_chara, worst_results = min(candidates, key=lambda x: sum(x[1]) / len(x[1]))
    wins   = sum(worst_results)
    losses = len(worst_results) - wins
    wr     = wins / len(worst_results) * 100

    if wins / len(worst_results) >= WIN_RATE_THRESHOLD:
        return None

    return f"{worst_chara} ({wins}勝{losses}敗, {wr:.0f}%)"


def _rating_summary(battles: list[Battle]) -> str:
    """当日の合計レーティング変動と最終レーティングを返す。"""
    rated = filter_rated_battles(battles)
    if not rated:
        return ""

    net_change = sum(b.get("rating_change") or 0 for b in rated)
    latest     = max(rated, key=lambda x: x["battle_at"])
    final_rating = (latest.get("rating_before") or 0) + (latest.get("rating_change") or 0)

    sign = "+" if net_change >= 0 else ""
    return f"{final_rating} ({sign}{net_change})"


def _matchup_matrix(battles: list[Battle]) -> str | None:
    """
    対戦キャラを勝率降順でリスト表示する。
    勝率 > 50% → ✅、= 50% → ➖、< 50% → ❌
    試合データがない場合は None を返す。
    """
    stats = aggregate_by_character(battles)

    rows = [(chara, results) for chara, results in stats.items() if len(results) >= 1]
    if not rows:
        return None

    rows.sort(key=lambda x: sum(x[1]) / len(x[1]), reverse=True)

    lines = ["📊 対戦成績"]
    for chara, results in rows:
        n  = len(results)
        wr = sum(results) / n
        pct = f"{wr * 100:.0f}%"
        if wr > WIN_RATE_THRESHOLD:
            icon = "✅"
        elif wr < WIN_RATE_THRESHOLD:
            icon = "❌"
        else:
            icon = "➖"
        lines.append(f"  {chara:<12} {n}戦 {pct:>4} {icon}")

    return "\n".join(lines)



def _scout_section(battles: list[Battle], scout_data: dict[str, dict]) -> str | None:
    """
    リピート対戦相手のスカウトレポートを返す。
    scout_data: {polaris_id: {win_rate, main_chara, recent_wins, recent_total, recent_win_rate}}
    """
    pid_count: Counter = Counter(
        b.get("opp_polaris_id") for b in battles if b.get("opp_polaris_id")
    )
    repeat_pids = [pid for pid, cnt in pid_count.most_common() if cnt >= 2 and pid in scout_data]
    if not repeat_pids:
        return None

    lines = ["🔍 対戦相手スカウト"]
    for pid in repeat_pids:
        s = scout_data[pid]
        opp_name  = next((b.get("opp_name") for b in battles if b.get("opp_polaris_id") == pid), "???")
        wr        = s["win_rate"]
        recent_wr = s["recent_win_rate"]
        trend_icon = "↑" if recent_wr > wr + SCOUT_TREND_THRESHOLD else ("↓" if recent_wr < wr - SCOUT_TREND_THRESHOLD else "→")
        lines.append(
            f"  {opp_name}({s['main_chara']}) "
            f"直近{s['total']}戦 勝率{wr:.0f}% | "
            f"直近{s['recent_total']}戦 {s['recent_wins']}勝 ({recent_wr:.0f}%) {trend_icon}"
        )
    return "\n".join(lines)



def _power_part(b: Battle) -> str:
    """自分と相手の鉄拳力を '(鉄拳力: 1,234,567 vs 1,100,000 [+134,567])' 形式で返す。どちらかが None なら空文字。"""
    my_p  = b.get("my_power")
    opp_p = b.get("opp_power")
    if my_p is None or opp_p is None:
        return ""
    diff = my_p - opp_p
    sign = "+" if diff >= 0 else ""
    return f"(鉄拳力: {my_p:,} vs {opp_p:,} [{sign}{diff:,}])"


def _opp_rank_label(battle: Battle) -> str:
    """クイックマッチの場合のみ相手段位名を返す。ランク戦・段位不明は空文字。"""
    if battle.get("battle_type") != "quick":
        return ""
    rank_id = battle.get("opp_rank")
    if rank_id is None:
        return ""
    name = RANK_NAMES.get(rank_id, "")
    return f"({name})" if name else ""


def _quick_rank_chara_matrix(battles: list[Battle]) -> str | None:
    """
    クイックマッチの相手段位×キャラ対戦成績を返す。
    opp_rank が不明な試合は除外。データなしは None を返す。
    段位降順（強い相手から）、段位内は勝率昇順（苦手キャラから）で表示する。
    """
    quick = [
        b for b in battles
        if b.get("battle_type") == "quick" and b.get("opp_rank") is not None
    ]
    if not quick:
        return None

    groups: dict[int, dict[str, list[bool]]] = {}
    for b in quick:
        rank_id = b["opp_rank"]
        chara   = b.get("opp_chara") or UNKNOWN_CHARACTER
        groups.setdefault(rank_id, {}).setdefault(chara, []).append(bool(b["won"]))

    lines = []
    for rank_id in sorted(groups.keys(), reverse=True):
        chara_stats = groups[rank_id]
        rank_name   = RANK_NAMES.get(rank_id, f"Rank{rank_id}")
        rank_total  = sum(len(v) for v in chara_stats.values())
        rank_wins   = sum(sum(v) for v in chara_stats.values())
        rank_wr     = f"{rank_wins / rank_total * 100:.0f}%"
        lines.append(f"■ {rank_name} ({rank_total}戦 {rank_wr})")

        for chara, results in sorted(chara_stats.items(), key=lambda x: sum(x[1]) / len(x[1])):
            n    = len(results)
            wr   = sum(results) / n
            pct  = f"{wr * 100:.0f}%"
            icon = "✅" if wr > WIN_RATE_THRESHOLD else ("❌" if wr < WIN_RATE_THRESHOLD else "➖")
            lines.append(f"  {chara:<12} {n}戦 {pct:>4} {icon}")

    return "\n".join(lines)


def _quick_rank_distribution(quick_battles: list[Battle]) -> str:
    """クイックマッチの相手段位分布を `God×4 / Kishin×3` 形式で返す。データなしは空文字。"""
    counts: Counter = Counter()
    for b in quick_battles:
        rank_id = b.get("opp_rank")
        if rank_id is not None:
            name = RANK_NAMES.get(rank_id, rank_id if isinstance(rank_id, str) else f"Rank{rank_id}")
            counts[name] += 1
    if not counts:
        return ""
    return " / ".join(f"{name}×{cnt}" for name, cnt in counts.most_common())


# ---------------------------------------------------------------------------
# Discord Embed ビルダー
# ---------------------------------------------------------------------------

def _embed_color(battles: list[Battle]) -> int:
    """勝率に基づいて Embed カラーコード（int）を返す。"""
    if not battles:
        return 0x5865F2  # Blurple
    wr = count_wins(battles) / len(battles)
    if wr >= EMBED_COLOR_GOOD_WR:
        return 0x57F287  # 緑
    if wr <= EMBED_COLOR_BAD_WR:
        return 0xED4245  # 赤
    return 0xFEE75C      # 黄


def build_embed(
    battles: list[Battle],
    date_str: str,
    player_name: str | None = None,
    scout_data: dict[str, dict] | None = None,
    has_chart: bool = False,
) -> dict | None:
    """Discord Embed 形式の dict を返す。試合なしの場合は None。LLM コメントは含まない。"""
    if not battles:
        return None

    display_name = player_name or TEKKEN_ID
    sorted_b = sorted(battles, key=lambda x: x["battle_at"])

    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    quick  = [b for b in battles if b.get("battle_type") == "quick"]
    other  = [b for b in battles if b.get("battle_type") not in ("ranked", "quick")]

    # 試合一覧（description）
    battle_lines = []
    for b in sorted_b:
        icon       = "✅" if b["won"] else "❌"
        score      = f"{b['my_rounds']}-{b['opp_rounds']}"
        chara      = b.get("my_chara") or "???"
        opp        = b.get("opp_chara") or "???"
        rank_part  = _opp_rank_label(b)
        opp_field  = f"{opp} {rank_part}".rstrip() if rank_part else opp
        power_part = _power_part(b)
        line = f"⚔️ {chara} vs {opp_field:<12} {icon} {score}"
        if power_part:
            line += f"  {power_part}"
        battle_lines.append(line)
    description = "\n".join(battle_lines)[:4096]

    fields: list[dict] = []

    def _add_type_field(icon: str, label: str, subset: list[Battle]) -> None:
        if not subset:
            return
        w   = count_wins(subset)
        l   = count_losses(subset)
        val = f"{w}勝{l}敗 ({_win_rate(subset)})"
        if label == "ランク":
            rating = _rating_summary(subset)
            if rating:
                val += f"\n{rating}"
        if label == "クイック":
            dist = _quick_rank_distribution(subset)
            if dist:
                val += f"\n相手段位: {dist}"
        fields.append({"name": f"{icon} {label}", "value": val, "inline": True})

    _add_type_field("🏆", "ランク",   ranked)
    _add_type_field("⚡", "クイック", quick)
    _add_type_field("🎮", "その他",   other)

    # ラウンド勝率・接戦
    total_my  = sum(b.get("my_rounds",  0) or 0 for b in battles)
    total_opp = sum(b.get("opp_rounds", 0) or 0 for b in battles)
    total_r   = total_my + total_opp
    round_wr  = f"{total_my / total_r * 100:.0f}%" if total_r else "-"
    close     = sum(1 for b in battles if (b.get("my_rounds") or 0) + (b.get("opp_rounds") or 0) >= 5)
    fields.append({"name": "🎯 ラウンド勝率", "value": f"{round_wr} | 接戦: {close}試合", "inline": True})

    # 連勝・連敗
    max_win, max_lose = _streak(sorted_b)
    streak_parts = []
    if max_win  >= 2: streak_parts.append(f"連勝: {max_win}")
    if max_lose >= 2: streak_parts.append(f"連敗: {max_lose}")
    if streak_parts:
        fields.append({"name": "🔥 ストリーク", "value": " | ".join(streak_parts), "inline": True})

    # 天敵
    nemesis = _nemesis(battles)
    if nemesis:
        fields.append({"name": "😤 天敵", "value": nemesis, "inline": True})

    # 調子の波
    momentum = detect_momentum(sorted_b)
    if momentum:
        fields.append({"name": "📊 調子", "value": momentum, "inline": True})

    # 鉄拳力
    latest = max(battles, key=lambda x: x["battle_at"])
    if latest.get("my_power"):
        rank_name = RANK_NAMES.get(latest.get("my_rank") or -1, "")
        power_str = f"{latest['my_power']:,}"
        field_name = f"💥 {rank_name}" if rank_name else "💥 鉄拳力"
        fields.append({"name": field_name, "value": power_str, "inline": True})

    # 対戦マトリクス（ヘッダー行を除いてフィールドに格納）
    matrix = _matchup_matrix(battles)
    if matrix:
        matrix_body = "\n".join(matrix.split("\n")[1:])
        fields.append({"name": "📊 対戦成績", "value": matrix_body[:1024], "inline": False})

    # スカウト
    if scout_data:
        scout = _scout_section(battles, scout_data)
        if scout:
            scout_body = "\n".join(scout.split("\n")[1:])
            fields.append({"name": "🔍 スカウト", "value": scout_body[:1024], "inline": False})

    # クイック 段位×キャラ対戦成績
    quick_rank_matrix = _quick_rank_chara_matrix(battles)
    if quick_rank_matrix:
        fields.append({"name": "⚡ クイック 段位別対戦成績", "value": quick_rank_matrix[:1024], "inline": False})

    embed: dict = {
        "title":       f"🎮 {display_name} 本日の戦果 ({date_str})",
        "color":       _embed_color(battles),
        "description": description,
        "fields":      fields[:DISCORD_EMBED_MAX_FIELDS],
    }
    if has_chart:
        embed["image"] = {"url": "attachment://rating.png"}

    return embed


def _build_period_stats_top(battles: list[Battle]) -> list[dict]:
    """週次・月次 Embed の共通上部フィールド（総合〜レーティング変動）を構築する。"""
    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    quick  = [b for b in battles if b.get("battle_type") == "quick"]
    rated  = filter_rated_battles(ranked)
    net_rating = sum(b.get("rating_change") or 0 for b in rated) if rated else None

    total_w = count_wins(battles)
    total_l = count_losses(battles)

    fields: list[dict] = []
    fields.append({"name": "🏆 総合", "value": f"{total_w}勝{total_l}敗 ({_win_rate(battles)})", "inline": True})
    if ranked:
        rw = count_wins(ranked)
        rl = count_losses(ranked)
        fields.append({"name": "📊 ランク", "value": f"{rw}勝{rl}敗 ({_win_rate(ranked)})", "inline": True})
    if quick:
        qw = count_wins(quick)
        ql = count_losses(quick)
        quick_val = f"{qw}勝{ql}敗 ({_win_rate(quick)})"
        dist = _quick_rank_distribution(quick)
        if dist:
            quick_val += f"\n相手段位: {dist}"
        fields.append({"name": "⚡ クイック", "value": quick_val, "inline": True})
    if net_rating is not None:
        sign = "+" if net_rating >= 0 else ""
        fields.append({"name": "📈 レーティング変動", "value": f"{sign}{net_rating}", "inline": True})
    return fields


def _build_period_stats_bottom(battles: list[Battle], power_label: str) -> list[dict]:
    """週次・月次 Embed の共通下部フィールド（最多キャラ〜対戦成績）を構築する。"""
    top_chara, top_chara_count = get_most_common(battles, "my_chara")
    top_opp,   top_opp_count   = get_most_common(battles, "opp_chara")

    fields: list[dict] = []
    fields.append({"name": "🥊 最多使用キャラ", "value": f"{top_chara} ({top_chara_count}戦)", "inline": True})
    fields.append({"name": "🎯 最多対戦相手", "value": f"{top_opp} ({top_opp_count}戦)", "inline": True})

    trend = predict_rating_trend(battles)
    if trend:
        slope = trend["slope_per_day"]
        sign  = "+" if slope >= 0 else ""
        fields.append({"name": "📈 レーティングトレンド", "value": f"{sign}{slope:.0f}/日", "inline": True})

    latest = max(battles, key=lambda x: x["battle_at"])
    if latest.get("my_power"):
        rank_name  = RANK_NAMES.get(latest.get("my_rank") or -1, "")
        power_str  = f"{latest['my_power']:,}"
        field_name = f"💥 {power_label}: {rank_name}" if rank_name else f"💥 {power_label}"
        fields.append({"name": field_name, "value": power_str, "inline": True})

    matrix = _matchup_matrix(battles)
    if matrix:
        matrix_body = "\n".join(matrix.split("\n")[1:])
        fields.append({"name": "📊 対戦成績", "value": matrix_body[:1024], "inline": False})
    return fields


def build_weekly_embed(
    battles: list[Battle],
    week_start_str: str,
    player_name: str | None = None,
) -> dict | None:
    """週次サマリーの Embed dict を返す。試合なしの場合は None。LLM コメントは含まない。"""
    if not battles:
        return None
    display_name = player_name or TEKKEN_ID
    fields = (
        _build_period_stats_top(battles)
        + _build_period_stats_bottom(battles, "週末鉄拳力")
    )
    return {
        "title":  f"📅 {display_name} 週次サマリー（{week_start_str} 週）",
        "color":  _embed_color(battles),
        "fields": fields[:DISCORD_EMBED_MAX_FIELDS],
    }


def build_rank_change_embed(player_name: str, old_rank: int, new_rank: int) -> dict:
    """段位変化通知用の Embed dict を返す。"""
    old_name = RANK_NAMES.get(old_rank, f"Rank{old_rank}")
    new_name = RANK_NAMES.get(new_rank, f"Rank{new_rank}")
    if new_rank > old_rank:
        return {
            "title":       f"🎊 {player_name} 段位昇格！",
            "color":       0xFFD700,
            "description": f"**{old_name}** → **{new_name}**",
        }
    return {
        "title":       f"📉 {player_name} 段位降格",
        "color":       0xED4245,
        "description": f"**{old_name}** → **{new_name}**",
    }


def build_monthly_embed(
    battles: list[Battle],
    month_str: str,
    player_name: str | None = None,
    prev_battles: list[Battle] | None = None,
) -> dict | None:
    """月次サマリーの Embed dict を返す。試合なしの場合は None。LLM コメントは含まない。"""
    if not battles:
        return None

    display_name = player_name or TEKKEN_ID
    fields = _build_period_stats_top(battles)

    # 前月比（レーティング変動フィールドの直後に挿入）
    if prev_battles:
        total_w = count_wins(battles)
        prev_w  = count_wins(prev_battles)
        prev_l  = count_losses(prev_battles)
        prev_rated = filter_rated_battles([b for b in prev_battles if b.get("battle_type") == "ranked"])
        prev_net   = sum(b.get("rating_change") or 0 for b in prev_rated) if prev_rated else None
        rated      = filter_rated_battles([b for b in battles if b.get("battle_type") == "ranked"])
        net_rating = sum(b.get("rating_change") or 0 for b in rated) if rated else None
        win_diff   = total_w - prev_w
        sign_w     = "+" if win_diff >= 0 else ""
        comparison = f"勝利数 {sign_w}{win_diff} | 前月: {prev_w}勝{prev_l}敗"
        if prev_net is not None and net_rating is not None:
            rating_diff = net_rating - prev_net
            sign_r = "+" if rating_diff >= 0 else ""
            comparison += f"\nレーティング差分 {sign_r}{rating_diff}"
        fields.append({"name": "📊 前月比", "value": comparison, "inline": False})

    fields += _build_period_stats_bottom(battles, "月末鉄拳力")
    return {
        "title":  f"📅 {display_name} 月次サマリー（{month_str}）",
        "color":  _embed_color(battles),
        "fields": fields[:DISCORD_EMBED_MAX_FIELDS],
    }


def build_community_weekly_embed(players_stats: list[dict], week_start_str: str) -> dict:
    """部内ランキングの Embed dict を返す。"""
    sorted_players = sorted(players_stats, key=lambda p: p["net_rating"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]

    lines = []
    for i, p in enumerate(sorted_players):
        medal  = medals[i] if i < 3 else f"{i + 1}."
        sign   = "+" if p["net_rating"] >= 0 else ""
        total  = p["wins"] + p["losses"]
        wr_str = f"{p['wins'] / total * 100:.0f}%" if total else "-"
        lines.append(f"{medal} {p['name']}: {sign}{p['net_rating']} ({p['wins']}勝{p['losses']}敗 {wr_str})")

    return {
        "title":       f"🏆 格ゲー部 週間ランキング ({week_start_str} 週)",
        "color":       0xFFD700,  # ゴールド
        "description": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# 投稿
# ---------------------------------------------------------------------------

def post_rank_change(player_name: str, old_rank: int, new_rank: int) -> None:
    """段位変化を Embed で全 Webhook に通知する。失敗しても例外は出さない。"""
    if not WEBHOOK_URLS:
        return
    embed = build_rank_change_embed(player_name, old_rank, new_rank)
    _send_to_webhooks(embed, log_label="段位変化通知")


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
    original_desc = embed.get("description", "")
    llm_block = f"💬 {llm_comment}\n\n"
    updated = {**embed, "description": (llm_block + original_desc)[:4096]}
    for message_id, webhook_url in message_ids:
        parts = _parse_webhook_id_token(webhook_url)
        if not parts:
            continue
        webhook_id, token = parts
        msg_url = f"https://discord.com/api/webhooks/{webhook_id}/{token}/messages/{message_id}"

        # 既存の添付ファイル ID を保持するため現在のメッセージを取得
        attachments: list[dict] = []
        try:
            get_resp = _webhook_session.get(msg_url, timeout=TIMEOUT_WEBHOOK)
            get_resp.raise_for_status()
            attachments = get_resp.json().get("attachments", [])
        except requests.RequestException as e:
            logger.warning(f"[discord_post] メッセージ取得失敗（添付ファイルなしで続行）: {e}")

        patch_body: dict = {"embeds": [updated]}
        if attachments:
            patch_body["attachments"] = [{"id": a["id"]} for a in attachments]

        try:
            resp = _webhook_session.patch(msg_url, json=patch_body, timeout=TIMEOUT_WEBHOOK)
            resp.raise_for_status()
            logger.info("[discord_post] LLMコメントを Embed に追記しました。")
        except requests.RequestException as e:
            logger.warning(f"[discord_post] LLMコメント追記失敗: {e}")
