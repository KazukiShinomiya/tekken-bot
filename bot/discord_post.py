"""
Discord Webhook にバトルサマリーを投稿するモジュール。
"""

import json
import logging
import os
import requests
from collections import defaultdict
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
TEKKEN_ID   = os.getenv("TEKKEN_ID", "ExodusOverseer")
JST         = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# スタッツ計算
# ---------------------------------------------------------------------------

def _win_rate(battles: list[dict]) -> str:
    if not battles:
        return "-"
    pct = sum(1 for b in battles if b["won"]) / len(battles) * 100
    return f"{pct:.0f}%"


def _streak(sorted_battles: list[dict]) -> tuple[int, int]:
    """時系列順バトルリストから (最長連勝, 最長連敗) を返す。"""
    max_win = max_lose = cur_win = cur_lose = 0
    for b in sorted_battles:
        if b["won"]:
            cur_win += 1
            cur_lose = 0
        else:
            cur_lose += 1
            cur_win = 0
        max_win  = max(max_win,  cur_win)
        max_lose = max(max_lose, cur_lose)
    return max_win, max_lose


def _nemesis(battles: list[dict]) -> str | None:
    """2戦以上対戦したキャラの中で、最も勝率が低いキャラを返す。"""
    stats: dict[str, list[bool]] = defaultdict(list)
    for b in battles:
        chara = b.get("opp_chara") or "???"
        stats[chara].append(bool(b["won"]))

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
    rated = [b for b in battles if b.get("rating_change") is not None]
    if not rated:
        return ""

    net_change = sum(b["rating_change"] for b in rated)
    latest     = max(rated, key=lambda x: x["battle_at"])
    final_rating = (latest.get("rating_before") or 0) + (latest.get("rating_change") or 0)

    sign = "+" if net_change >= 0 else ""
    return f"{final_rating} ({sign}{net_change})"


def _matchup_matrix(battles: list[dict]) -> str | None:
    """
    2戦以上の対戦キャラを勝率降順でリスト表示する。
    勝率 > 50% → ✅、= 50% → ➖、< 50% → ❌
    試合数が足りない場合は None を返す。
    """
    stats: dict[str, list[bool]] = defaultdict(list)
    for b in battles:
        chara = b.get("opp_chara") or "???"
        stats[chara].append(bool(b["won"]))

    rows = [(chara, results) for chara, results in stats.items() if len(results) >= 2]
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
        w = sum(1 for b in subset if b["won"])
        l = len(subset) - w
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

    # テッケンパワー（ある場合）
    latest = max(battles, key=lambda x: x["battle_at"])
    if latest.get("my_power"):
        lines.append(f"💥 テッケンパワー: {latest['my_power']:,}")

    # --- 対戦マトリクス ---
    matrix = _matchup_matrix(battles)
    if matrix:
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(matrix)

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

    # レーティング変動
    rated = [b for b in ranked if b.get("rating_change") is not None]
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

    total_w = sum(1 for b in battles if b["won"])
    total_l = len(battles) - total_w

    lines = [f"📅 **{display_name}** 週次サマリー（{week_start_str} 週）"]
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"🏆 総合: {total_w}勝{total_l}敗 ({_win_rate(battles)})")

    if ranked:
        rw = sum(1 for b in ranked if b["won"])
        rl = len(ranked) - rw
        lines.append(f"📊 ランク: {rw}勝{rl}敗 ({_win_rate(ranked)})")

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
        logger.info("本日の試合なし。投稿をスキップ。")
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
            timeout=15,
        )
    else:
        resp = requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)

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
        logger.info(f"[{player_name}] 今週の試合なし。週次投稿をスキップ。")
        return False

    if llm_comment:
        message += f"\n\n🤖 {llm_comment}"

    resp = requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)
    resp.raise_for_status()
    return True
