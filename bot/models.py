"""
バトルデータの型定義。
TypedDict を使うことで IDE の補完と静的解析（mypy/pyright）が機能する。
"""

from typing import TypedDict


class Battle(TypedDict, total=False):
    """1バトル分のデータ。全フィールドは Optional（ソースによって欠損あり）。"""
    # 識別
    battle_id:    str
    battle_at:    int
    battle_type:  str | None   # "ranked" / "quick" / "player"
    game_version: str | None
    stage_id:     int | None
    source:       str | None   # "wank_bulk" / "ewgf" / "wank_html"

    # 自分側
    won:           bool
    my_chara:      str | None
    my_chara_id:   int | None
    my_rounds:     int
    my_rank:       int | None
    my_power:      int | None
    my_region:     str | None
    rating_before: int | None
    rating_change: int | None

    # 相手側
    opp_name:          str | None
    opp_polaris_id:    str | None
    opp_chara:         str | None
    opp_chara_id:      int | None
    opp_rounds:        int
    opp_rank:          int | None
    opp_power:         int | None
    opp_region:        str | None
    opp_rating_before: int | None
    opp_rating_change: int | None

    # プレイヤー識別
    player_name: str
