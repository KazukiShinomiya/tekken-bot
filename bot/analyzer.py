"""
Ollama（ローカルLLM）を使ってバトルデータを分析するモジュール。
"""

import logging
import requests

from bot.config import OLLAMA_URL, OLLAMA_MODEL, TIMEOUT_LLM
from bot.stats import calculate_streak, aggregate_by_character, count_wins, count_losses, filter_rated_battles

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


def _build_prompt(battles: list[dict], date_str: str, player_name: str = "",
                  prev_battles: list[dict] | None = None, prev_date_str: str = "") -> str:
    stats   = _calculate_stats(battles)
    summary = _build_summary_text(stats, date_str)

    prev_section = ""
    if prev_battles:
        prev_stats   = _calculate_stats(prev_battles)
        prev_summary = _build_summary_text(prev_stats, prev_date_str)
        prev_section = f"\n【前日の成績】\n{prev_summary}\n"

    return f"""あなたは鉄拳8の対戦コーチです。
以下はプレイヤー「{player_name}」の戦績です。
{prev_section}
【本日の成績】
{summary}

この戦績を分析して、日本語で150文字以内のコーチコメントをしてください。
・全体の調子を一言で評価する
・前日と比較して変化があれば触れる（前日データがない場合は本日分だけで評価する）
・上記のデータから読み取れる次の課題または強化すべき点を一つ述べる（好成績の場合は強みを伸ばす視点でも可）
・前向きに締めくくる

【厳守】「対戦キャラ別成績」に記載されていないキャラクター名は絶対に出さない。
【厳守】データに記載されていない事実や推測は述べない。
余計な説明・挨拶・記号は不要です。コメント本文のみ出力してください。"""


def analyze(battles: list[dict], date_str: str, player_name: str = "",
            prev_battles: list[dict] | None = None) -> str | None:
    """
    バトルデータをLLMで分析してコメントを返す。
    prev_battles が渡された場合は前日比のコンテキストをプロンプトに含める。
    失敗時は None を返す（投稿自体は続行）。
    """
    if not battles:
        return None

    from datetime import datetime, timedelta
    try:
        prev_date_str = (datetime.strptime(date_str, "%Y/%m/%d") - timedelta(days=1)).strftime("%Y/%m/%d")
    except ValueError:
        prev_date_str = ""

    prompt = _build_prompt(battles, date_str, player_name, prev_battles=prev_battles, prev_date_str=prev_date_str)

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
    except Exception as e:
        logger.warning(f"[analyzer] LLM分析失敗（スキップ）: {e}")
        return None
