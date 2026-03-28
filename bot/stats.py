"""
バトルスタッツの共通計算ユーティリティ。
analyzer.py と discord_post.py で共有する純粋関数。
"""

from datetime import datetime
from bot.config import JST, UNKNOWN_CHARACTER, RATING_STAGNATION_THRESHOLD


def count_wins(battles: list[dict]) -> int:
    """バトルリストから勝利数を返す。"""
    return sum(1 for b in battles if b["won"])


def count_losses(battles: list[dict]) -> int:
    """バトルリストから敗北数を返す。"""
    return len(battles) - count_wins(battles)


def filter_rated_battles(battles: list[dict]) -> list[dict]:
    """rating_change が存在するバトルのみを返す。"""
    return [b for b in battles if b.get("rating_change") is not None]


def calculate_streak(battles: list[dict]) -> tuple[int, int]:
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


def aggregate_by_character(battles: list[dict]) -> dict[str, list[bool]]:
    """対戦相手キャラ別に勝敗をグループ化して返す。"""
    result: dict[str, list[bool]] = {}
    for b in battles:
        c = b.get("opp_chara") or UNKNOWN_CHARACTER
        result.setdefault(c, []).append(bool(b["won"]))
    return result


def get_most_common(battles: list[dict], key: str) -> tuple[str, int]:
    """
    バトルリストから指定キーの最多値と出現回数を返す。
    空の場合は (UNKNOWN_CHARACTER, 0) を返す。
    """
    counts: dict[str, int] = {}
    for b in battles:
        c = b.get(key) or UNKNOWN_CHARACTER
        counts[c] = counts.get(c, 0) + 1
    if not counts:
        return UNKNOWN_CHARACTER, 0
    top = max(counts, key=counts.__getitem__)
    return top, counts[top]


def detect_losing_streak(sorted_battles: list[dict]) -> int:
    """時系列順バトルリストの末尾から連続敗北数を返す。"""
    streak = 0
    for b in reversed(sorted_battles):
        if not b["won"]:
            streak += 1
        else:
            break
    return streak


def aggregate_by_hour(battles: list[dict]) -> dict[int, list[bool]]:
    """バトル開始時刻(JST時)別に勝敗をグループ化して返す。"""
    result: dict[int, list[bool]] = {}
    for b in battles:
        ts = b.get("battle_at")
        if ts is None:
            continue
        hour = datetime.fromtimestamp(ts, JST).hour
        result.setdefault(hour, []).append(bool(b["won"]))
    return result


def predict_rating_trend(battles: list[dict]) -> dict:
    """
    レーティングの推移を線形回帰で分析する。
    numpy が必要（不在の場合は空 dict を返す）。

    Returns:
        slope_per_day: 1日あたりの平均レーティング変動（正=上昇傾向）
        stagnation_days: 末尾から連続して停滞（±100/日以内）した日数
    """
    ranked_rated = filter_rated_battles([b for b in battles if b.get("battle_type") == "ranked"])
    if len(ranked_rated) < 3:
        return {}

    sorted_rated = sorted(ranked_rated, key=lambda b: b["battle_at"])

    try:
        import numpy as np
        cumulative = 0.0
        xs, ys = [], []
        for b in sorted_rated:
            cumulative += b["rating_change"]
            xs.append(b["battle_at"])
            ys.append(cumulative)

        slope, _ = np.polyfit(xs, ys, 1)
        slope_per_day = float(slope) * 86400  # 秒 → 日

        stagnation_days = _count_stagnation_days(sorted_rated)

        return {"slope_per_day": slope_per_day, "stagnation_days": stagnation_days}
    except Exception:
        return {}


def _count_stagnation_days(sorted_rated: list[dict]) -> int:
    """末尾から連続して1日の変動が ±RATING_STAGNATION_THRESHOLD 以内の日数を返す。"""
    from collections import defaultdict

    daily: dict[str, int] = defaultdict(int)
    for b in sorted_rated:
        day = datetime.fromtimestamp(b["battle_at"], JST).strftime("%Y-%m-%d")
        daily[day] += b["rating_change"]

    stagnation = 0
    for delta in reversed(list(daily.values())):
        if abs(delta) <= RATING_STAGNATION_THRESHOLD:
            stagnation += 1
        else:
            break
    return stagnation


def detect_momentum(sorted_battles: list[dict]) -> str | None:
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
    if diff >= 0.2:
        return "📈 後半に調子が上向いた"
    if diff <= -0.2:
        return "📉 後半に調子が落ちた"
    return None
