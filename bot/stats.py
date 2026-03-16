"""
バトルスタッツの共通計算ユーティリティ。
analyzer.py と discord_post.py で共有する純粋関数。
"""


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
