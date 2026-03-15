"""
Ollama（ローカルLLM）を使ってバトルデータを分析するモジュール。
"""

import logging
import os
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
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

    summary = f"""日付: {date_str}
総合: {wins}勝{losses}敗 (勝率{wins*100//len(battles) if battles else 0}%)
ランク戦: {sum(1 for b in ranked if b['won'])}勝{sum(1 for b in ranked if not b['won'])}敗
クイック: {sum(1 for b in quick if b['won'])}勝{sum(1 for b in quick if not b['won'])}敗
ラウンド勝率: {round_wr}
対戦キャラ別成績:
{chr(10).join(matchups)}"""

    return f"""あなたは鉄拳8の対戦コーチです。
以下は本日のプレイヤー「{player_name}」の戦績です。

{summary}

この戦績を見て、以下の形式で日本語で100文字以内のコメントをしてください。
・今日の調子の一言評価
・一つだけ具体的なアドバイス

余計な説明や挨拶は不要です。コメントのみ出力してください。"""


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
                "options": {"temperature": 0.7, "num_predict": 150},
            },
            timeout=120,  # CPU推論（3bモデル想定）
        )
        resp.raise_for_status()
        comment = resp.json().get("response", "").strip()
        logger.info(f"[analyzer] LLM分析完了: {len(comment)}文字")
        return comment if comment else None
    except Exception as e:
        logger.warning(f"[analyzer] LLM分析失敗（スキップ）: {e}")
        return None
