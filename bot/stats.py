"""
バトルスタッツの共通計算ユーティリティ。
analyzer.py と discord_post.py で共有する純粋関数。
"""

import logging
from datetime import datetime
from typing import cast
from bot.config import (
    JST, UNKNOWN_CHARACTER, RATING_STAGNATION_THRESHOLD,
    MIN_BATTLES_FOR_TREND, MOMENTUM_THRESHOLD,
)
from bot.models import Battle

logger = logging.getLogger(__name__)


def count_wins(battles: list[Battle]) -> int:
    """バトルリストから勝利数を返す。"""
    return sum(1 for b in battles if b["won"])


def count_losses(battles: list[Battle]) -> int:
    """バトルリストから敗北数を返す。"""
    return len(battles) - count_wins(battles)


def filter_rated_battles(battles: list[Battle]) -> list[Battle]:
    """rating_change が存在するバトルのみを返す。"""
    return [b for b in battles if b.get("rating_change") is not None]


def calculate_streak(battles: list[Battle]) -> tuple[int, int]:
    """時系列順バトルリストから (最長連勝, 最長連敗) を返す。"""
    max_win = max_lose = cur_win = cur_lose = 0
    for b in battles:
        if b["won"]:
            cur_win += 1
            cur_lose = 0
        else:
            cur_lose += 1
            cur_win = 0
        max_win  = max(max_win,  cur_win)
        max_lose = max(max_lose, cur_lose)
    return max_win, max_lose


def aggregate_by_character(battles: list[Battle]) -> dict[str, list[bool]]:
    """対戦相手キャラ別に勝敗をグループ化して返す。"""
    result: dict[str, list[bool]] = {}
    for b in battles:
        c = b.get("opp_chara") or UNKNOWN_CHARACTER
        result.setdefault(c, []).append(bool(b["won"]))
    return result


def aggregate_by_my_character(battles: list[Battle]) -> dict[str, list[bool]]:
    """自分の使用キャラ別に勝敗をグループ化して返す（クイックの練習ログ用）。"""
    result: dict[str, list[bool]] = {}
    for b in battles:
        c = b.get("my_chara") or UNKNOWN_CHARACTER
        result.setdefault(c, []).append(bool(b["won"]))
    return result


def round_quality(battles: list[Battle]) -> dict[str, int | None]:
    """ラウンド単位の試合の質を集計して返す。

    Returns:
        round_wr_pct: ラウンド勝率(%)。ラウンド情報が皆無なら None
        sweep_wins:   完封勝ち（相手の取得ラウンド 0）
        sweep_losses: 完封負け（自分の取得ラウンド 0）
        close_games:  フルラウンド接戦（合計 5 ラウンド以上）
    """
    total_my  = sum(b.get("my_rounds", 0) or 0 for b in battles)
    total_opp = sum(b.get("opp_rounds", 0) or 0 for b in battles)
    total_r   = total_my + total_opp
    # 完封は勝者側にラウンドがあることを条件にする（ラウンド情報欠損の試合を誤カウントしない）
    sweep_wins   = sum(1 for b in battles
                       if b["won"] and (b.get("my_rounds") or 0) > 0 and (b.get("opp_rounds") or 0) == 0)
    sweep_losses = sum(1 for b in battles
                       if not b["won"] and (b.get("opp_rounds") or 0) > 0 and (b.get("my_rounds") or 0) == 0)
    close_games  = sum(1 for b in battles if (b.get("my_rounds") or 0) + (b.get("opp_rounds") or 0) >= 5)
    return {
        "round_wr_pct": round(total_my / total_r * 100) if total_r else None,
        "sweep_wins":   sweep_wins,
        "sweep_losses": sweep_losses,
        "close_games":  close_games,
    }


def get_most_common(battles: list[Battle], key: str) -> tuple[str, int]:
    """
    バトルリストから指定キーの最多値と出現回数を返す。
    空の場合は (UNKNOWN_CHARACTER, 0) を返す。
    key は Battle の任意フィールド名を文字列で指定する。
    """
    counts: dict[str, int] = {}
    for b in battles:
        raw: str | None = cast(dict[str, str | None], b).get(key)
        c = raw or UNKNOWN_CHARACTER
        counts[c] = counts.get(c, 0) + 1
    if not counts:
        return UNKNOWN_CHARACTER, 0
    top = max(counts, key=counts.__getitem__)
    return top, counts[top]


def detect_losing_streak(sorted_battles: list[Battle]) -> int:
    """時系列順バトルリストの末尾から連続敗北数を返す。"""
    streak = 0
    for b in reversed(sorted_battles):
        if not b["won"]:
            streak += 1
        else:
            break
    return streak


def detect_winning_streak(sorted_battles: list[Battle]) -> int:
    """時系列順バトルリストの末尾から連続勝利数を返す。"""
    streak = 0
    for b in reversed(sorted_battles):
        if b["won"]:
            streak += 1
        else:
            break
    return streak


def aggregate_by_hour(battles: list[Battle]) -> dict[int, list[bool]]:
    """バトル開始時刻(JST時)別に勝敗をグループ化して返す。"""
    result: dict[int, list[bool]] = {}
    for b in battles:
        ts = b.get("battle_at")
        if ts is None:
            continue
        hour = datetime.fromtimestamp(ts, JST).hour
        result.setdefault(hour, []).append(bool(b["won"]))
    return result


def predict_rating_trend(battles: list[Battle]) -> dict[str, float]:
    """
    レーティングの推移を線形回帰で分析する。
    numpy が必要（不在の場合は空 dict を返す）。

    Returns:
        slope_per_day: 1日あたりの平均レーティング変動（正=上昇傾向）
        stagnation_days: 末尾から連続して停滞（±100/日以内）した日数
    """
    ranked_rated = filter_rated_battles([b for b in battles if b.get("battle_type") == "ranked"])
    if len(ranked_rated) < MIN_BATTLES_FOR_TREND:
        return {}

    sorted_rated = sorted(ranked_rated, key=lambda b: b["battle_at"])

    try:
        import numpy as np
        cumulative = 0.0
        xs, ys = [], []
        for b in sorted_rated:
            cumulative += b.get("rating_change") or 0
            xs.append(b["battle_at"])
            ys.append(cumulative)

        slope, _ = np.polyfit(xs, ys, 1)
        slope_per_day = float(slope) * 86400  # 秒 → 日

        stagnation_days = _count_stagnation_days(sorted_rated)

        return {"slope_per_day": slope_per_day, "stagnation_days": float(stagnation_days)}
    except ImportError:
        logger.warning("[stats] numpy が見つからないため predict_rating_trend をスキップ（pip install numpy で解決）")
        return {}
    except Exception as e:
        logger.warning(f"[stats] レーティングトレンド計算失敗: {e}")
        return {}


def _count_stagnation_days(sorted_rated: list[Battle]) -> int:
    """末尾から連続して1日の変動が ±RATING_STAGNATION_THRESHOLD 以内の日数を返す。"""
    from collections import defaultdict

    daily: dict[str, int] = defaultdict(int)
    for b in sorted_rated:
        day = datetime.fromtimestamp(b["battle_at"], JST).strftime("%Y-%m-%d")
        daily[day] += b.get("rating_change") or 0

    stagnation = 0
    for delta in reversed(list(daily.values())):
        if abs(delta) <= RATING_STAGNATION_THRESHOLD:
            stagnation += 1
        else:
            break
    return stagnation


def detect_momentum(sorted_battles: list[Battle]) -> str | None:
    """
    時系列順バトルリストの前半・後半を比較し、調子の波を文字列で返す。
    バトル数が4未満、または変化が小さい場合は None を返す。
    """
    n = len(sorted_battles)
    if n < 4:
        return None
    half = n // 2
    first_wr  = count_wins(sorted_battles[:half])  / half
    second_wr = count_wins(sorted_battles[half:]) / (n - half)
    diff = second_wr - first_wr
    if diff >= MOMENTUM_THRESHOLD:
        return "📈 後半に調子が上向いた"
    if diff <= -MOMENTUM_THRESHOLD:
        return "📉 後半に調子が落ちた"
    return None
