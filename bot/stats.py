"""
バトルスタッツの共通計算ユーティリティ。
analyzer.py と discord_post.py で共有する純粋関数。
"""

from datetime import datetime
from bot.config import JST


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
        c = b.get("opp_chara") or "???"
        result.setdefault(c, []).append(bool(b["won"]))
    return result


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
