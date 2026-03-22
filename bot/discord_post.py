"""
Discord Webhook にバトルサマリーを投稿するモジュール。
"""

import json
import logging
import requests
from collections import defaultdict
from datetime import datetime

from bot.config import DISCORD_WEBHOOK_URL as WEBHOOK_URL, TEKKEN_ID, TIMEOUT_WEBHOOK, TIMEOUT_WEBHOOK_IMAGE, JST
from bot.stats import (
    calculate_streak, aggregate_by_character, count_wins, count_losses,
    filter_rated_battles, aggregate_by_hour, detect_momentum,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# スタッツ計算
# ---------------------------------------------------------------------------

def _win_rate(battles: list[dict]) -> str:
    if not battles:
        return "-"
    pct = count_wins(battles) / len(battles) * 100
    return f"{pct:.0f}%"


def _streak(sorted_battles: list[dict]) -> tuple[int, int]:
    """時系列順バトルリストから (最長連勝, 最長連敗) を返す。"""
    return calculate_streak(sorted_battles)


def _nemesis(battles: list[dict]) -> str | None:
    """2戦以上対戦したキャラの中で、最も勝率が低いキャラを返す。"""
    stats = aggregate_by_character(battles)

    candidates = [(chara, results) for chara, results in stats.items() if len(results) >= 2]
    if not candidates:
        return None

    worst_chara, worst_results = min(candidates, key=lambda x: sum(x[1]) / len(x[1]))
    wins   = sum(worst_results)
    losses = len(worst_results) - wins
    wr     = wins / len(worst_results) * 100

    # 勝率50%以上なら天敵なし
    if wins / len(worst_results) >= 0.5:
        return None

    return f"{worst_chara} ({wins}勝{losses}敗, {wr:.0f}%)"


def _rating_summary(battles: list[dict]) -> str:
    """当日の合計レーティング変動と最終レーティングを返す。"""
    rated = filter_rated_battles(battles)
    if not rated:
        return ""

    net_change = sum(b["rating_change"] for b in rated)
    latest     = max(rated, key=lambda x: x["battle_at"])
    final_rating = (latest.get("rating_before") or 0) + (latest.get("rating_change") or 0)

    sign = "+" if net_change >= 0 else ""
    return f"{final_rating} ({sign}{net_change})"


def _matchup_matrix(battles: list[dict]) -> str | None:
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
        if wr > 0.5:
            icon = "✅"
        elif wr < 0.5:
            icon = "❌"
        else:
            icon = "➖"
        lines.append(f"  {chara:<12} {n}戦 {pct:>4} {icon}")

    return "\n".join(lines)


def _hourly_section(battles: list[dict]) -> str | None:
    """JST 時間帯別勝率セクションを返す。2試合以上の時間帯のみ表示。"""
    hourly = aggregate_by_hour(battles)
    rows = [(h, results) for h, results in hourly.items() if len(results) >= 2]
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    lines = ["🕐 時間帯別"]
    for hour, results in rows:
        w   = sum(results)
        l   = len(results) - w
        wr  = w / len(results) * 100
        icon = "✅" if wr > 50 else ("❌" if wr < 50 else "➖")
        lines.append(f"  {hour:02d}時 {w}勝{l}敗 ({wr:.0f}%) {icon}")
    return "\n".join(lines)


def _rematch_section(battles: list[dict]) -> str | None:
    """同一対戦相手と2戦以上した場合に今日の対面成績をまとめて返す。"""
    from collections import Counter
    pid_count: Counter = Counter(
        b.get("opp_polaris_id") for b in battles if b.get("opp_polaris_id")
    )
    repeat_pids = {pid for pid, cnt in pid_count.items() if cnt >= 2}
    if not repeat_pids:
        return None

    lines = ["🔄 リピート対戦"]
    for pid in sorted(repeat_pids):
        subset = [b for b in battles if b.get("opp_polaris_id") == pid]
        opp_name  = subset[0].get("opp_name") or "???"
        opp_chara = subset[0].get("opp_chara") or "???"
        w  = sum(1 for b in subset if b["won"])
        l  = len(subset) - w
        wr = w / len(subset) * 100
        lines.append(f"  {opp_name}({opp_chara}) {w}勝{l}敗 ({wr:.0f}%)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# メッセージ構築
# ---------------------------------------------------------------------------

def build_message(battles: list[dict], date_str: str, player_name: str | None = None) -> str | None:
    if not battles:
        return None

    display_name = player_name or TEKKEN_ID
    sorted_b = sorted(battles, key=lambda x: x["battle_at"])

    # battle_type 別に分類
    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    quick  = [b for b in battles if b.get("battle_type") == "quick"]
    other  = [b for b in battles if b.get("battle_type") not in ("ranked", "quick")]

    lines = [f"🎮 **{display_name}** 本日の戦果 ({date_str})"]
    lines.append("━━━━━━━━━━━━━━━")

    # --- 試合一覧 ---
    for b in sorted_b:
        icon  = "✅" if b["won"] else "❌"
        score = f"{b['my_rounds']}-{b['opp_rounds']}"
        chara = b.get("my_chara") or "???"
        opp   = b.get("opp_chara") or "???"
        lines.append(f"⚔️  {chara} vs {opp:<12} {icon} {score}")

    lines.append("━━━━━━━━━━━━━━━")

    # --- タイプ別スタッツ ---
    def _type_line(icon: str, label: str, subset: list[dict]) -> str | None:
        if not subset:
            return None
        w = count_wins(subset)
        l = count_losses(subset)
        wr = _win_rate(subset)
        base = f"{icon} {label:<5} {w}勝{l}敗 ({wr})"
        if label == "ランク":
            rating = _rating_summary(subset)
            if rating:
                base += f" | {rating}"
        return base

    for line in filter(None, [
        _type_line("🏆", "ランク",   ranked),
        _type_line("⚡", "クイック", quick),
        _type_line("🎮", "その他",   other),
    ]):
        lines.append(line)

    lines.append("━━━━━━━━━━━━━━━")

    # --- 詳細スタッツ ---
    total_my_rounds  = sum(b.get("my_rounds",  0) or 0 for b in battles)
    total_opp_rounds = sum(b.get("opp_rounds", 0) or 0 for b in battles)
    total_rounds     = total_my_rounds + total_opp_rounds
    round_wr = f"{total_my_rounds / total_rounds * 100:.0f}%" if total_rounds else "-"

    close = sum(1 for b in battles
                if (b.get("my_rounds") or 0) + (b.get("opp_rounds") or 0) >= 5)  # 3-2 or 2-3

    max_win, max_lose = _streak(sorted_b)

    lines.append(f"🎯 ラウンド勝率: {round_wr} | 接戦(3-2): {close}試合")

    streak_parts = []
    if max_win  >= 2: streak_parts.append(f"連勝: {max_win}")
    if max_lose >= 2: streak_parts.append(f"連敗: {max_lose}")
    if streak_parts:
        lines.append("🔥 " + " | ".join(streak_parts))

    nemesis = _nemesis(battles)
    if nemesis:
        lines.append(f"😤 天敵: {nemesis}")

    # 調子の波
    momentum = detect_momentum(sorted_b)
    if momentum:
        lines.append(momentum)

    # 鉄拳力（ある場合）
    latest = max(battles, key=lambda x: x["battle_at"])
    if latest.get("my_power"):
        lines.append(f"💥 鉄拳力: {latest['my_power']:,}")

    # --- 対戦マトリクス ---
    matrix = _matchup_matrix(battles)
    if matrix:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(matrix)

    # --- 時間帯別勝率 ---
    hourly = _hourly_section(battles)
    if hourly:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(hourly)

    # --- リピート対戦 ---
    rematch = _rematch_section(battles)
    if rematch:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(rematch)

    return "\n".join(lines)


def build_weekly_message(
    battles: list[dict],
    week_start_str: str,
    player_name: str | None = None,
) -> str | None:
    """週次サマリーメッセージを構築する。"""
    if not battles:
        return None

    display_name = player_name or TEKKEN_ID
    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    quick  = [b for b in battles if b.get("battle_type") == "quick"]

    # レーティング変動
    rated = filter_rated_battles(ranked)
    net_rating = sum(b["rating_change"] for b in rated) if rated else None

    # 最多使用キャラ
    my_chara_count: dict[str, int] = defaultdict(int)
    for b in battles:
        c = b.get("my_chara") or "???"
        my_chara_count[c] += 1
    top_chara = max(my_chara_count, key=my_chara_count.__getitem__) if my_chara_count else "???"

    # 最多対戦相手
    opp_count: dict[str, int] = defaultdict(int)
    for b in battles:
        c = b.get("opp_chara") or "???"
        opp_count[c] += 1
    top_opp = max(opp_count, key=opp_count.__getitem__) if opp_count else "???"

    total_w = count_wins(battles)
    total_l = count_losses(battles)

    lines = [f"📅 **{display_name}** 週次サマリー（{week_start_str} 週）"]
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"🏆 総合: {total_w}勝{total_l}敗 ({_win_rate(battles)})")

    if ranked:
        rw = count_wins(ranked)
        rl = count_losses(ranked)
        lines.append(f"📊 ランク: {rw}勝{rl}敗 ({_win_rate(ranked)})")

    if quick:
        qw = count_wins(quick)
        ql = count_losses(quick)
        lines.append(f"⚡ クイック: {qw}勝{ql}敗 ({_win_rate(quick)})")

    if net_rating is not None:
        sign = "+" if net_rating >= 0 else ""
        lines.append(f"📈 レーティング変動: {sign}{net_rating}")

    lines.append(f"🥊 最多使用キャラ: {top_chara} ({my_chara_count.get(top_chara, 0)}戦)")
    lines.append(f"🎯 最多対戦相手: {top_opp} ({opp_count.get(top_opp, 0)}戦)")

    matrix = _matchup_matrix(battles)
    if matrix:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(matrix)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 投稿
# ---------------------------------------------------------------------------

def notify_error(message: str) -> None:
    """エラーを Discord Webhook に通知する。失敗しても例外は出さない。"""
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={"content": f"⚠️ {message}"}, timeout=TIMEOUT_WEBHOOK)
    except Exception as e:
        logger.warning(f"[discord_post] エラー通知失敗: {e}")


def post(
    battles: list[dict],
    date_str: str | None = None,
    llm_comment: str | None = None,
    player_name: str | None = None,
) -> bool:
    """Discord Webhook にサマリーを投稿。投稿した場合 True を返す。"""
    if not WEBHOOK_URL:
        raise ValueError("DISCORD_WEBHOOK_URL が .env に設定されていません")

    if date_str is None:
        date_str = datetime.now(JST).strftime("%Y/%m/%d")

    message = build_message(battles, date_str, player_name)
    if message is None:
        logger.info("[discord_post] 本日の試合なし。投稿をスキップ。")
        return False

    if llm_comment:
        message += f"\n\n🤖 {llm_comment}"

    # グラフ生成を試みる
    chart = None
    try:
        from bot.graph import generate_rating_chart
        chart = generate_rating_chart(battles, player_name or TEKKEN_ID)
    except Exception as e:
        logger.warning(f"[discord_post] グラフ生成失敗（スキップ）: {e}")

    if chart:
        resp = requests.post(
            WEBHOOK_URL,
            data={"payload_json": json.dumps({"content": message})},
            files={"files[0]": ("rating.png", chart, "image/png")},
            timeout=TIMEOUT_WEBHOOK_IMAGE,
        )
    else:
        resp = requests.post(WEBHOOK_URL, json={"content": message}, timeout=TIMEOUT_WEBHOOK)

    resp.raise_for_status()
    return True


def post_weekly(
    battles: list[dict],
    week_start_str: str,
    llm_comment: str | None = None,
    player_name: str | None = None,
) -> bool:
    """週次サマリーを Discord Webhook に投稿。"""
    if not WEBHOOK_URL:
        raise ValueError("DISCORD_WEBHOOK_URL が .env に設定されていません")

    message = build_weekly_message(battles, week_start_str, player_name)
    if message is None:
        logger.info(f"[discord_post][{player_name}] 今週の試合なし。週次投稿をスキップ。")
        return False

    if llm_comment:
        message += f"\n\n🤖 {llm_comment}"

    resp = requests.post(WEBHOOK_URL, json={"content": message}, timeout=TIMEOUT_WEBHOOK)
    resp.raise_for_status()
    return True
