"""
Ollama（ローカルLLM）を使ってバトルデータを分析するモジュール。

プロンプト設計方針:
  - Chat API（/api/chat）で role: system / user を分離
    - system: コーチ人格・Few-shot・制約・出力形式（静的、全リクエスト共通）
    - user  : 戦績データ・事前計算済み洞察（動的、リクエスト毎に生成）
  - Few-shot サンプルでコメントのトーンと長さを固定
  - format: "json" で出力を {"comment": "..."} に強制しハルシネーションを抑制
"""

import json
import logging
from datetime import datetime, timedelta
import requests

from bot.config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_FALLBACK_MODEL, TIMEOUT_LLM
from bot.models import Battle
from bot.stats import (
    calculate_streak, aggregate_by_character, count_wins, count_losses,
    filter_rated_battles, aggregate_by_hour,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Few-shot サンプル（プロンプトに埋め込む静的定数）
# 好調日・不調日の2パターンでコメントのトーンと長さを固定する
# ---------------------------------------------------------------------------

_FEW_SHOT_EXAMPLES = """
<example>
<battle_data>
日付: 2026/04/10 / プレイヤー: Player
総合: 3勝7敗 (勝率30%)
ランク戦: 3勝7敗 / クイック: 0勝0敗
ラウンド勝率: 38%
レーティング変動: -280
対戦キャラ別成績:
  Bryan: 0勝3敗
  Dragunov: 2勝1敗
  King: 1勝3敗
苦手キャラ: Bryan(勝率0%,3戦) / King(勝率25%,4戦)
</battle_data>
<output>{"comment": "今日はBryan・Kingに苦戦。Bryan戦はヒートスマッシュ後の二択を優先して対策しよう。Dragunov戦は安定しているので自信を持って。厳しい日だが課題が明確になったのは収穫だ。"}</output>
</example>
<example>
<battle_data>
日付: 2026/04/11 / プレイヤー: Player
総合: 8勝3敗 (勝率73%)
ランク戦: 8勝3敗 / クイック: 0勝0敗
ラウンド勝率: 68%
レーティング変動: +420
対戦キャラ別成績:
  Kazuya: 3勝0敗
  Law: 2勝1敗
  Reina: 3勝2敗
得意キャラ: Kazuya(勝率100%,3戦)
</battle_data>
<output>{"comment": "今日は絶好調、特にKazuya完封が光る。Reina戦は2敗があるのでフレーム有利からの択の精度を上げるとさらに完璧。この調子を維持していこう。"}</output>
</example>
""".strip()


# ---------------------------------------------------------------------------
# 統計計算
# ---------------------------------------------------------------------------

def _calculate_stats(battles: list[Battle]) -> dict:
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
    net_rating = sum(b.get("rating_change") or 0 for b in rated) if rated else None

    sorted_b          = sorted(battles, key=lambda x: x["battle_at"])
    max_win, max_lose = calculate_streak(sorted_b)

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
    """集計値からサマリーテキストを構築する。"""
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
    battles: list[Battle],
    prev_battles: list[Battle] | None,
) -> dict:
    """
    Python 側でパターン分析し、LLM が推論しやすい洞察を返す。
    LLM には加工済みの事実だけを渡すことでハルシネーションを減らす。
    """
    chara_stats = aggregate_by_character(battles)

    weak = sorted(
        [(c, sum(r) / len(r) * 100, len(r))
         for c, r in chara_stats.items() if len(r) >= 2 and sum(r) / len(r) < 0.4],
        key=lambda x: x[1],
    )
    strong = sorted(
        [(c, sum(r) / len(r) * 100, len(r))
         for c, r in chara_stats.items() if len(r) >= 2 and sum(r) / len(r) >= 0.7],
        key=lambda x: -x[1],
    )

    hourly      = aggregate_by_hour(battles)
    valid_hours = [(h, r) for h, r in hourly.items() if len(r) >= 2]
    best_hour   = max(valid_hours, key=lambda x: sum(x[1]) / len(x[1]), default=None)
    worst_hour  = min(valid_hours, key=lambda x: sum(x[1]) / len(x[1]), default=None)

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


def _build_battle_data_section(
    stats: dict,
    date_str: str,
    player_name: str,
    insights: dict,
    rematch_data: dict | None,
) -> str:
    """<battle_data> タグ内のテキストを構築する。"""
    wins, losses = stats["wins"], stats["losses"]
    ranked, quick = stats["ranked"], stats["quick"]
    total = wins + losses
    wr = round(wins * 100 / total) if total else 0

    lines = [
        f"日付: {date_str} / プレイヤー: {player_name}",
        f"総合: {wins}勝{losses}敗 (勝率{wr}%)",
        f"ランク戦: {count_wins(ranked)}勝{count_losses(ranked)}敗 / "
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

    lines.append("対戦キャラ別成績:")
    lines.extend(stats["matchups"])

    return "\n".join(lines)


def _build_insights_section(insights: dict, rematch_data: dict | None) -> str:
    """<insights> タグ内の事前分析済み洞察を構築する。"""
    lines = []

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
        lines.append("繰り返し対戦した相手:")
        for data in rematch_data.values():
            history = data["history"]
            rw = sum(1 for b in history if b["won"])
            rt = len(history)
            lines.append(
                f"  {data['name']}({data['chara']}): "
                f"{rw}勝{rt - rw}敗 ({rw / rt * 100:.0f}%)"
            )

    return "\n".join(lines) if lines else "（特記事項なし）"


def _build_system_prompt() -> str:
    """
    コーチとしての役割・Few-shot・制約・出力形式を定義するシステムプロンプト（静的）。
    全リクエストで共通。
    """
    return f"""あなたは鉄拳8の対戦コーチです。プレイヤーのデータを分析して、具体的で前向きなコーチングコメントを提供します。

<examples>
{_FEW_SHOT_EXAMPLES}
</examples>

<constraints>
- 「対戦キャラ別成績」に記載されていないキャラ名は絶対に出さない
- データにない事実・数値・推測は述べない
- 挨拶・記号・余計な説明は不要
- 日本語150文字以内で回答する
</constraints>

<output_format>
以下の JSON 形式のみで回答してください。他のテキストは一切含めないこと。
{{"comment": "コーチングコメント（150文字以内）"}}
</output_format>"""


def _build_user_message(
    battles: list[Battle],
    date_str: str,
    player_name: str = "",
    prev_battles: list[Battle] | None = None,
    rematch_data: dict | None = None,
) -> str:
    """
    今日の戦績データと事前計算済み洞察を含むユーザーメッセージ（動的）。
    リクエスト毎に生成する。
    """
    stats    = _calculate_stats(battles)
    insights = _compute_coaching_insights(battles, prev_battles)

    battle_data   = _build_battle_data_section(stats, date_str, player_name, insights, rematch_data)
    insights_text = _build_insights_section(insights, rematch_data)

    return f"""<battle_data>
{battle_data}
</battle_data>

<insights>
{insights_text}
</insights>"""


def _build_messages(
    battles: list[Battle],
    date_str: str,
    player_name: str = "",
    prev_battles: list[Battle] | None = None,
    rematch_data: dict | None = None,
) -> list[dict]:
    """
    Ollama Chat API 用の messages リストを構築する。

      messages[0]: {"role": "system"} — コーチ人格・Few-shot・制約（静的）
      messages[1]: {"role": "user"}   — 今日の戦績・洞察（動的）
    """
    return [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user",   "content": _build_user_message(
            battles, date_str, player_name, prev_battles, rematch_data,
        )},
    ]


def _call_ollama(model: str, messages: list[dict]) -> str | None:
    """
    指定モデルで Ollama Chat API（/api/chat）を呼び出し、コーチングコメント文字列を返す。

    format: "json" で出力を {"comment": "..."} に強制する。
    レスポンスは resp["message"]["content"] から取り出す（/api/generate の "response" とは異なる）。
    JSON 解析失敗時は生テキストにフォールバックして返す。
    失敗時は例外を再送出。
    """
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model":    model,
            "messages": messages,
            "stream":   False,
            "format":   "json",
            "options":  {"temperature": 0.7, "num_predict": 300},
        },
        timeout=TIMEOUT_LLM,
    )
    resp.raise_for_status()
    raw = resp.json().get("message", {}).get("content", "").strip()
    if not raw:
        return None

    try:
        data = json.loads(raw)
        comment = data.get("comment", "").strip()
        return comment or None
    except (json.JSONDecodeError, AttributeError):
        logger.warning("[analyzer] JSON解析失敗、生テキストにフォールバック")
        return raw or None


def analyze(
    battles: list[Battle],
    date_str: str,
    player_name: str = "",
    prev_battles: list[Battle] | None = None,
    rematch_data: dict | None = None,
) -> str | None:
    """
    バトルデータをLLMで分析してコメントを返す。
    prev_battles が渡された場合は前日比のコンテキストをプロンプトに含める。
    rematch_data が渡された場合はリピート対戦相手の通算成績をプロンプトに含める。
    失敗時は None を返す（投稿自体は続行）。
    OLLAMA_FALLBACK_MODEL が設定されている場合、プライマリ失敗時に自動でフォールバック。
    """
    if not battles:
        return None

    messages = _build_messages(
        battles, date_str, player_name,
        prev_battles=prev_battles,
        rematch_data=rematch_data,
    )

    try:
        comment = _call_ollama(OLLAMA_MODEL, messages)
        logger.info(f"[analyzer] LLM分析完了({OLLAMA_MODEL}): {len(comment or '')}文字")
        return comment
    except requests.RequestException as e:
        logger.warning(f"[analyzer] プライマリモデル失敗({OLLAMA_MODEL}): {e}")

    if OLLAMA_FALLBACK_MODEL:
        try:
            comment = _call_ollama(OLLAMA_FALLBACK_MODEL, messages)
            logger.info(f"[analyzer] フォールバックモデル成功({OLLAMA_FALLBACK_MODEL}): {len(comment or '')}文字")
            return comment
        except requests.RequestException as e:
            logger.warning(f"[analyzer] フォールバックモデルも失敗({OLLAMA_FALLBACK_MODEL}): {e}")

    return None
