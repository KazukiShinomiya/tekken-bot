"""
LLM コメントの品質をルールベースで自動評価するモジュール。

評価軸 (合計 100点):
  length      (40点): コメントが 150 文字以内か
  chara_valid (40点): 対戦していないキャラクターを言及していないか（ハルシネーション検出）
  has_action  (20点): 具体的な改善提案（アクションワード）が含まれるか

使い方:
  from bot.evaluator import evaluate_comment
  result = evaluate_comment(comment, battles)
  print(result["score"], result["details"])
"""

from __future__ import annotations

from bot.fetcher import CHARA_NAMES
from bot.models import Battle

# アクションワード: 改善提案・次の行動を示す語句
_ACTION_KEYWORDS = [
    "対策", "意識", "練習", "狙う", "試す", "磨く", "改善",
    "注意", "確認", "抑える", "強化", "鍛え", "気をつけ",
    "覚え", "混ぜ", "崩し", "徹底", "重点", "優先",
]

MAX_COMMENT_LENGTH = 150


def evaluate_comment(comment: str, battles: list[Battle]) -> dict:
    """
    コメントの品質を評価する。

    Args:
        comment:  評価対象のコメント文字列
        battles:  対戦データのリスト（ハルシネーション検出に使用）

    Returns:
        {
            "score": int,           # 合計スコア (0-100)
            "details": {
                "length":      {"score": int, "max": 40, "message": str},
                "chara_valid": {"score": int, "max": 40, "message": str, "hallucinated": list[str]},
                "has_action":  {"score": int, "max": 20, "message": str, "found": list[str]},
            },
        }
    """
    length_result      = _check_length(comment)
    chara_valid_result = _check_chara_validity(comment, battles)
    action_result      = _check_action_presence(comment)

    total = length_result["score"] + chara_valid_result["score"] + action_result["score"]

    return {
        "score": total,
        "details": {
            "length":      length_result,
            "chara_valid": chara_valid_result,
            "has_action":  action_result,
        },
    }


def _check_length(comment: str) -> dict:
    """コメント長チェック。150文字以内なら 40点。"""
    length = len(comment)
    if length <= MAX_COMMENT_LENGTH:
        return {
            "score": 40,
            "max": 40,
            "message": f"OK ({length}文字)",
        }
    return {
        "score": 0,
        "max": 40,
        "message": f"超過 ({length}文字 > {MAX_COMMENT_LENGTH}文字)",
    }


def _check_chara_validity(comment: str, battles: list[Battle]) -> dict:
    """
    ハルシネーション検出。対戦していないキャラクター名がコメントに含まれていたら 0点。

    自分のキャラ（my_chara）と相手キャラ（opp_chara）の両方を「対戦済み」として扱う。
    """
    battle_charas: set[str] = set()
    for b in battles:
        if b.get("opp_chara"):
            battle_charas.add(b["opp_chara"])
        if b.get("my_chara"):
            battle_charas.add(b["my_chara"])

    all_chara_names = set(CHARA_NAMES.values())
    non_battle_charas = all_chara_names - battle_charas

    hallucinated = [name for name in non_battle_charas if name in comment]

    if not hallucinated:
        return {
            "score": 40,
            "max": 40,
            "message": "OK (未対戦キャラなし)",
            "hallucinated": [],
        }
    return {
        "score": 0,
        "max": 40,
        "message": f"ハルシネーション検出: {', '.join(sorted(hallucinated))}",
        "hallucinated": sorted(hallucinated),
    }


def _check_action_presence(comment: str) -> dict:
    """アクションワード検出。改善提案を示す語句が 1つ以上含まれていれば 20点。"""
    found = [kw for kw in _ACTION_KEYWORDS if kw in comment]

    if found:
        display = found[:3]
        suffix = "..." if len(found) > 3 else ""
        return {
            "score": 20,
            "max": 20,
            "message": f"OK (検出: {', '.join(display)}{suffix})",
            "found": found,
        }
    return {
        "score": 0,
        "max": 20,
        "message": "アクションワードなし",
        "found": [],
    }
