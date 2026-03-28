"""
Ollama（ローカルLLM）を使ってバトルデータを分析するモジュール。
"""

import logging
import requests

from bot.config import OLLAMA_URL, OLLAMA_MODEL, TIMEOUT_LLM
from bot.stats import (
    calculate_streak, aggregate_by_character, count_wins, count_losses,
    filter_rated_battles, aggregate_by_hour,
)

logger = logging.getLogger(__name__)


def _calculate_stats(battles: list[dict]) -> dict:
    """バトルリストから集計値を計算して返す。"""
    wins   = count_wins(battles)
    losses = count_losses(battles)
    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    quick  = [b for b in battles if b.get("battle_type") == "quick"]

    total_my  = sum(b.get("my_rounds",  0) or 0 for b in battles)
    total_opp = sum(b.get("opp_rounds", 0) or 0 for b in battles)
    total_r   = total_my + total_opp
    round_wr  = f"{total_my / total_r * 100:.0f}%" if total_r else "-"

    rated      = filter_rated_battles(ranked)
    net_rating = sum(b["rating_change"] for b in rated) if rated else None

    sorted_b              = sorted(battles, key=lambda x: x["battle_at"])
    max_win, max_lose     = calculate_streak(sorted_b)

    chara_results = aggregate_by_character(battles)
    matchups = [
        f"  {chara}: {sum(results)}勝{len(results) - sum(results)}敗"
        for chara, results in sorted(chara_results.items())
    ]

    return {
        "wins": wins, "losses": losses,
        "ranked": ranked, "quick": quick,
        "round_wr": round_wr,
        "net_rating": net_rating,
        "max_win": max_win, "max_lose": max_lose,
        "matchups": matchups,
    }


def _build_summary_text(stats: dict, date_str: str) -> str:
    """集計値からLLMへ渡すサマリーテキストを構築する。"""
    wins, losses = stats["wins"], stats["losses"]
    ranked, quick = stats["ranked"], stats["quick"]
    total = wins + losses

    lines = [
        f"日付: {date_str}",
        f"総合: {wins}勝{losses}敗 (勝率{round(wins * 100 / total) if total else 0}%)",
        f"ランク戦: {count_wins(ranked)}勝{count_losses(ranked)}敗",
        f"クイック: {count_wins(quick)}勝{count_losses(quick)}敗",
        f"ラウンド勝率: {stats['round_wr']}",
    ]
    if stats["net_rating"] is not None:
        sign = "+" if stats["net_rating"] >= 0 else ""
        lines.append(f"レーティング変動: {sign}{stats['net_rating']}")
    if stats["max_win"] >= 2:
        lines.append(f"最長連勝: {stats['max_win']}")
    if stats["max_lose"] >= 2:
        lines.append(f"最長連敗: {stats['max_lose']}")
    lines.append("対戦キャラ別成績:")
    lines.extend(stats["matchups"])
    return "\n".join(lines)


def _compute_coaching_insights(
    battles: list[dict],
    prev_battles: list[dict] | None,
) -> dict:
    """
    Python 側でパターン分析し、LLM が推論しやすい洞察を返す。
    LLM には加工済みの事実だけを渡すことでハルシネーションを減らす。
    """
    chara_stats = aggregate_by_character(battles)

    # 不得意キャラ（2戦以上で勝率40%未満）
    weak = sorted(
        [(c, sum(r) / len(r) * 100, len(r))
         for c, r in chara_stats.items() if len(r) >= 2 and sum(r) / len(r) < 0.4],
        key=lambda x: x[1],
    )

    # 得意キャラ（2戦以上で勝率70%超）
    strong = sorted(
        [(c, sum(r) / len(r) * 100, len(r))
         for c, r in chara_stats.items() if len(r) >= 2 and sum(r) / len(r) >= 0.7],
        key=lambda x: -x[1],
    )

    # 時間帯別勝率（2戦以上の時間帯のみ）
    hourly      = aggregate_by_hour(battles)
    valid_hours = [(h, r) for h, r in hourly.items() if len(r) >= 2]
    best_hour   = max(valid_hours, key=lambda x: sum(x[1]) / len(x[1]), default=None)
    worst_hour  = min(valid_hours, key=lambda x: sum(x[1]) / len(x[1]), default=None)

    # 前日比勝率トレンド
    trend = None
    if prev_battles and battles:
        today_wr = count_wins(battles) / len(battles)
        prev_wr  = count_wins(prev_battles) / len(prev_battles)
        diff = today_wr - prev_wr
        if abs(diff) >= 0.1:
            trend = f"前日比{'↑' if diff > 0 else '↓'}{abs(diff) * 100:.0f}pt"

    return {
        "weak":       weak,
        "strong":     strong,
        "best_hour":  best_hour,
        "worst_hour": worst_hour,
        "trend":      trend,
    }


def _build_rematch_section(rematch_data: dict) -> str:
    """リピート対戦相手の通算成績セクションを構築する。"""
    lines = []
    for data in rematch_data.values():
        history = data["history"]
        wins  = sum(1 for b in history if b["won"])
        total = len(history)
        wr    = wins / total * 100 if total else 0
        lines.append(f"  {data['name']}({data['chara']}): 通算{wins}勝{total - wins}敗 ({wr:.0f}%)")
    if not lines:
        return ""
    return "【繰り返し対戦した相手の通算成績】\n" + "\n".join(lines)


def _build_prompt(battles: list[dict], date_str: str, player_name: str = "",
                  prev_battles: list[dict] | None = None, prev_date_str: str = "",
                  rematch_data: dict | None = None) -> str:
    stats    = _calculate_stats(battles)
    insights = _compute_coaching_insights(battles, prev_battles)

    wins, losses = stats["wins"], stats["losses"]
    ranked, quick = stats["ranked"], stats["quick"]
    total = wins + losses
    wr = round(wins * 100 / total) if total else 0

    lines = [
        "あなたは鉄拳8の対戦コーチです。",
        f"プレイヤー「{player_name}」 / {date_str}",
        "",
        "【戦績】",
        f"総合: {wins}勝{losses}敗 (勝率{wr}%)",
        f"ランク戦: {count_wins(ranked)}勝{count_losses(ranked)}敗",
        f"クイック: {count_wins(quick)}勝{count_losses(quick)}敗",
        f"ラウンド勝率: {stats['round_wr']}",
    ]

    if stats["net_rating"] is not None:
        sign = "+" if stats["net_rating"] >= 0 else ""
        lines.append(f"レーティング変動: {sign}{stats['net_rating']}")

    if stats["max_win"] >= 2:
        lines.append(f"最長連勝: {stats['max_win']}")
    if stats["max_lose"] >= 2:
        lines.append(f"最長連敗: {stats['max_lose']}")

    if insights["trend"]:
        lines.append(f"調子: {insights['trend']}")

    lines.append("")
    lines.append("【対戦キャラ別成績】")
    lines.extend(stats["matchups"])

    # 事前分析済み洞察（LLMのハルシネーション抑止）
    if insights["weak"]:
        weak_str = " / ".join(
            f"{c}(勝率{w:.0f}%,{n}戦)" for c, w, n in insights["weak"][:3]
        )
        lines.append(f"苦手キャラ: {weak_str}")

    if insights["strong"]:
        str_str = " / ".join(
            f"{c}(勝率{w:.0f}%,{n}戦)" for c, w, n in insights["strong"][:2]
        )
        lines.append(f"得意キャラ: {str_str}")

    if insights["best_hour"] and insights["worst_hour"]:
        bh, br = insights["best_hour"]
        wh, wr_ = insights["worst_hour"]
        lines.append(
            f"時間帯: 好調={bh}時({sum(br)/len(br)*100:.0f}%) "
            f"低調={wh}時({sum(wr_)/len(wr_)*100:.0f}%)"
        )

    if rematch_data:
        lines.append("")
        lines.append("【繰り返し対戦した相手の通算成績】")
        for data in rematch_data.values():
            history = data["history"]
            rw = sum(1 for b in history if b["won"])
            rt = len(history)
            lines.append(
                f"  {data['name']}({data['chara']}): "
                f"{rw}勝{rt - rw}敗 ({rw / rt * 100:.0f}%)"
            )

    lines.extend([
        "",
        "上記データに基づき、日本語150文字以内でコーチコメントを書いてください。",
        "①今日の総評 ②最優先の改善点（データに基づく具体的な1点） ③前向きな締め",
        "【厳守】「対戦キャラ別成績」に記載されていないキャラ名は絶対に出さない。",
        "【厳守】データにない事実・推測は述べない。余計な説明・挨拶・記号は不要。",
    ])

    return "\n".join(lines)


def analyze(battles: list[dict], date_str: str, player_name: str = "",
            prev_battles: list[dict] | None = None,
            rematch_data: dict | None = None) -> str | None:
    """
    バトルデータをLLMで分析してコメントを返す。
    prev_battles が渡された場合は前日比のコンテキストをプロンプトに含める。
    rematch_data が渡された場合はリピート対戦相手の通算成績をプロンプトに含める。
    失敗時は None を返す（投稿自体は続行）。
    """
    if not battles:
        return None

    from datetime import datetime, timedelta
    try:
        prev_date_str = (datetime.strptime(date_str, "%Y/%m/%d") - timedelta(days=1)).strftime("%Y/%m/%d")
    except ValueError:
        prev_date_str = ""

    prompt = _build_prompt(
        battles, date_str, player_name,
        prev_battles=prev_battles, prev_date_str=prev_date_str,
        rematch_data=rematch_data,
    )

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 200},
            },
            timeout=TIMEOUT_LLM,
        )
        resp.raise_for_status()
        comment = resp.json().get("response", "").strip()
        logger.info(f"[analyzer] LLM分析完了: {len(comment)}文字")
        return comment if comment else None
    except requests.RequestException as e:
        logger.warning(f"[analyzer] LLM分析失敗（スキップ）: {e}")
        return None
