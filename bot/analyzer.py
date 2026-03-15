"""
Ollama（ローカルLLM）を使ってバトルデータを分析するモジュール。
"""

import logging
import os
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
JST          = timezone(timedelta(hours=9))


def _build_prompt(battles: list[dict], date_str: str, player_name: str = "ExodusOverseer") -> str:
    wins   = sum(1 for b in battles if b["won"])
    losses = len(battles) - wins
    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    quick  = [b for b in battles if b.get("battle_type") == "quick"]

    total_my   = sum(b.get("my_rounds",  0) or 0 for b in battles)
    total_opp  = sum(b.get("opp_rounds", 0) or 0 for b in battles)
    total_r    = total_my + total_opp
    round_wr   = f"{total_my / total_r * 100:.0f}%" if total_r else "-"

    # レーティング変動
    rated = [b for b in ranked if b.get("rating_change") is not None]
    net_rating = sum(b["rating_change"] for b in rated) if rated else None

    # 連勝・連敗
    sorted_b = sorted(battles, key=lambda x: x["battle_at"])
    max_win = max_lose = cur_win = cur_lose = 0
    for b in sorted_b:
        if b["won"]:
            cur_win += 1; cur_lose = 0
        else:
            cur_lose += 1; cur_win = 0
        max_win  = max(max_win,  cur_win)
        max_lose = max(max_lose, cur_lose)

    # 対戦キャラ集計
    chara_results: dict[str, list[bool]] = {}
    for b in battles:
        c = b.get("opp_chara") or "???"
        chara_results.setdefault(c, []).append(bool(b["won"]))

    matchups = []
    for chara, results in sorted(chara_results.items()):
        w = sum(results)
        l = len(results) - w
        matchups.append(f"  {chara}: {w}勝{l}敗")

    # サマリー構築
    lines = [
        f"日付: {date_str}",
        f"総合: {wins}勝{losses}敗 (勝率{wins*100//len(battles) if battles else 0}%)",
        f"ランク戦: {sum(1 for b in ranked if b['won'])}勝{sum(1 for b in ranked if not b['won'])}敗",
        f"クイック: {sum(1 for b in quick if b['won'])}勝{sum(1 for b in quick if not b['won'])}敗",
        f"ラウンド勝率: {round_wr}",
    ]
    if net_rating is not None:
        sign = "+" if net_rating >= 0 else ""
        lines.append(f"レーティング変動: {sign}{net_rating}")
    if max_win >= 2:
        lines.append(f"最長連勝: {max_win}")
    if max_lose >= 2:
        lines.append(f"最長連敗: {max_lose}")
    lines.append("対戦キャラ別成績:")
    lines.extend(matchups)

    summary = "\n".join(lines)

    return f"""あなたは鉄拳8の対戦コーチです。
以下は本日のプレイヤー「{player_name}」の戦績です。

{summary}

この戦績を分析して、日本語で150文字以内のコーチコメントをしてください。
・全体の調子を一言で評価する
・最も改善すべき点を一つ、具体的に指摘する
・前向きに締めくくる

余計な説明・挨拶・記号は不要です。コメント本文のみ出力してください。"""


def analyze(battles: list[dict], date_str: str, player_name: str = "ExodusOverseer") -> str | None:
    """
    バトルデータをLLMで分析してコメントを返す。
    失敗時は None を返す（投稿自体は続行）。
    """
    if not battles:
        return None

    prompt = _build_prompt(battles, date_str, player_name)

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 200},
            },
            timeout=300,  # 7bモデル対応（CPU推論で実測約2分、余裕を持って5分）
        )
        resp.raise_for_status()
        comment = resp.json().get("response", "").strip()
        logger.info(f"[analyzer] LLM分析完了: {len(comment)}文字")
        return comment if comment else None
    except Exception as e:
        logger.warning(f"[analyzer] LLM分析失敗（スキップ）: {e}")
        return None
