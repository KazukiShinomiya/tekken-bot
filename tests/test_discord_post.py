"""
bot/discord_post.py の純粋関数テスト。
"""

import pytest
from bot.discord_post import (
    _win_rate,
    _streak,
    _nemesis,
    _rating_summary,
    _matchup_matrix,
    _hourly_section,
    _scout_section,
    _opp_rank_label,
    _quick_rank_distribution,
    build_message,
    build_weekly_message,
    build_community_weekly,
    build_embed,
    build_weekly_embed,
)


def _battle(won: bool, opp_chara: str = "Jin", my_chara: str = "Reina",
            rating_before: int | None = None, rating_change: int | None = None,
            my_rounds: int = 2, opp_rounds: int = 1,
            battle_type: str = "ranked", battle_at: int = 1000) -> dict:
    return {
        "won": won,
        "opp_chara": opp_chara,
        "my_chara": my_chara,
        "rating_before": rating_before,
        "rating_change": rating_change,
        "my_rounds": my_rounds,
        "opp_rounds": opp_rounds,
        "battle_type": battle_type,
        "battle_at": battle_at,
        "my_power": None,
    }


# ---------------------------------------------------------------------------
# _win_rate
# ---------------------------------------------------------------------------

def test_win_rate_all_wins():
    battles = [_battle(True), _battle(True), _battle(True)]
    assert _win_rate(battles) == "100%"


def test_win_rate_all_losses():
    battles = [_battle(False), _battle(False)]
    assert _win_rate(battles) == "0%"


def test_win_rate_mixed():
    battles = [_battle(True), _battle(False)]
    assert _win_rate(battles) == "50%"


def test_win_rate_empty():
    assert _win_rate([]) == "-"


def test_win_rate_75():
    battles = [_battle(True), _battle(True), _battle(True), _battle(False)]
    assert _win_rate(battles) == "75%"


# ---------------------------------------------------------------------------
# _streak
# ---------------------------------------------------------------------------

def test_streak_win_streak():
    battles = [_battle(True), _battle(True), _battle(True), _battle(False)]
    max_win, max_lose = _streak(battles)
    assert max_win == 3
    assert max_lose == 1


def test_streak_lose_streak():
    battles = [_battle(False), _battle(False), _battle(True)]
    max_win, max_lose = _streak(battles)
    assert max_win == 1
    assert max_lose == 2


def test_streak_no_streak():
    battles = [_battle(True), _battle(False), _battle(True)]
    max_win, max_lose = _streak(battles)
    assert max_win == 1
    assert max_lose == 1


def test_streak_empty():
    assert _streak([]) == (0, 0)


def test_streak_all_wins():
    battles = [_battle(True)] * 5
    max_win, max_lose = _streak(battles)
    assert max_win == 5
    assert max_lose == 0


# ---------------------------------------------------------------------------
# _nemesis
# ---------------------------------------------------------------------------

def test_nemesis_found():
    battles = [
        _battle(False, "Dragunov"),
        _battle(False, "Dragunov"),
        _battle(True, "Jin"),
        _battle(True, "Jin"),
    ]
    result = _nemesis(battles)
    assert result is not None
    assert "Dragunov" in result


def test_nemesis_no_nemesis_when_winning():
    battles = [
        _battle(True, "Dragunov"),
        _battle(True, "Dragunov"),
    ]
    assert _nemesis(battles) == None


def test_nemesis_not_enough_battles():
    battles = [_battle(False, "Dragunov")]
    assert _nemesis(battles) == None


def test_nemesis_empty():
    assert _nemesis([]) == None


def test_nemesis_exactly_50_percent():
    battles = [_battle(True, "Dragunov"), _battle(False, "Dragunov")]
    assert _nemesis(battles) == None  # 50% は天敵なし


# ---------------------------------------------------------------------------
# _rating_summary
# ---------------------------------------------------------------------------

def test_rating_summary_gain():
    battles = [
        _battle(True, rating_before=10000, rating_change=50, battle_at=1000),
        _battle(True, rating_before=10050, rating_change=50, battle_at=2000),
    ]
    result = _rating_summary(battles)
    assert "10100" in result
    assert "+100" in result


def test_rating_summary_loss():
    battles = [
        _battle(False, rating_before=10000, rating_change=-30, battle_at=1000),
    ]
    result = _rating_summary(battles)
    assert "9970" in result
    assert "-30" in result


def test_rating_summary_no_data():
    battles = [_battle(True)]
    assert _rating_summary(battles) == ""


def test_rating_summary_empty():
    assert _rating_summary([]) == ""


# ---------------------------------------------------------------------------
# _matchup_matrix
# ---------------------------------------------------------------------------

def test_matchup_matrix_basic():
    battles = [
        _battle(True, "Dragunov"), _battle(True, "Dragunov"),
        _battle(False, "Jin"), _battle(False, "Jin"),
    ]
    result = _matchup_matrix(battles)
    assert result is not None
    assert "Dragunov" in result
    assert "Jin" in result
    assert "✅" in result
    assert "❌" in result


def test_matchup_matrix_50_percent():
    battles = [_battle(True, "Jin"), _battle(False, "Jin")]
    result = _matchup_matrix(battles)
    assert result is not None
    assert "➖" in result


def test_matchup_matrix_not_enough_battles():
    battles = [_battle(True, "Jin")]  # 1戦のみ（閾値1戦から表示）
    result = _matchup_matrix(battles)
    assert result is not None
    assert "Jin" in result


def test_matchup_matrix_sorted_by_win_rate():
    battles = [
        _battle(True, "Dragunov"), _battle(True, "Dragunov"),   # 100%
        _battle(False, "Jin"), _battle(False, "Jin"),            # 0%
    ]
    result = _matchup_matrix(battles)
    assert result is not None
    lines = result.split("\n")
    # Dragunov（100%）が Jin（0%）より先に来るはず
    dragunov_idx = next(i for i, l in enumerate(lines) if "Dragunov" in l)
    jin_idx = next(i for i, l in enumerate(lines) if "Jin" in l)
    assert dragunov_idx < jin_idx


def test_matchup_matrix_empty():
    assert _matchup_matrix([]) is None


# ---------------------------------------------------------------------------
# build_message
# ---------------------------------------------------------------------------

def test_build_message_includes_player_name():
    battles = [_battle(True, battle_at=1000)]
    msg = build_message(battles, "2024/01/01", player_name="TestPlayer")
    assert "TestPlayer" in msg


def test_build_message_none_on_empty():
    assert build_message([], "2024/01/01") is None


def test_build_message_shows_streak():
    """3連勝の場合、連勝行が表示される。"""
    battles = [_battle(True, battle_at=i * 100) for i in range(3)]
    msg = build_message(battles, "2024/01/01")
    assert "連勝" in msg


def test_build_message_no_streak_when_short():
    """1連勝は表示されない。"""
    battles = [_battle(True, battle_at=1000), _battle(False, battle_at=2000)]
    msg = build_message(battles, "2024/01/01")
    assert "🔥" not in msg


def test_build_message_shows_nemesis():
    """2連敗キャラがいる場合、天敵行が表示される。"""
    battles = [
        _battle(False, "Dragunov", battle_at=1000),
        _battle(False, "Dragunov", battle_at=2000),
    ]
    msg = build_message(battles, "2024/01/01")
    assert "天敵" in msg
    assert "Dragunov" in msg


def test_build_message_shows_tekken_power():
    """鉄拳力がある場合、表示される。"""
    b = _battle(True, battle_at=1000)
    b["my_power"] = 123456
    msg = build_message([b], "2024/01/01")
    assert "鉄拳力" in msg
    assert "123,456" in msg


# ---------------------------------------------------------------------------
# build_weekly_message
# ---------------------------------------------------------------------------

def test_build_weekly_message_none_on_empty():
    assert build_weekly_message([], "2024/01/15") is None


def test_build_weekly_message_includes_player_name():
    battles = [_battle(True)]
    msg = build_weekly_message(battles, "2024/01/15", player_name="TestPlayer")
    assert "TestPlayer" in msg


def test_build_weekly_message_includes_win_loss():
    battles = [_battle(True), _battle(True), _battle(False)]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "2勝1敗" in msg


def test_build_weekly_message_includes_top_chara():
    """最多使用キャラが表示される。"""
    battles = [
        _battle(True,  my_chara="Reina"),
        _battle(False, my_chara="Reina"),
        _battle(True,  my_chara="Jin"),
    ]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "Reina" in msg  # 2戦で最多


def test_build_weekly_message_with_rating():
    """ランク戦のレーティング変動が表示される。"""
    battles = [
        _battle(True,  rating_change=50,  battle_type="ranked"),
        _battle(False, rating_change=-30, battle_type="ranked"),
    ]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "レーティング変動" in msg
    assert "+20" in msg


def test_build_weekly_message_includes_matchup_matrix():
    """2戦以上の対戦キャラがある場合、マトリクスが含まれる。"""
    battles = [
        _battle(True,  "Dragunov"), _battle(True,  "Dragunov"),
        _battle(False, "Jin"),      _battle(False, "Jin"),
    ]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "Dragunov" in msg
    assert "Jin" in msg


def test_build_weekly_message_shows_matchup_matrix_with_one_battle():
    """1戦のキャラもマトリクスに表示される（閾値1戦から表示）。"""
    battles = [_battle(True, "Jin"), _battle(False, "Dragunov")]
    msg = build_weekly_message(battles, "2024/01/15")
    assert "📊 対戦成績" in msg
    assert "Jin" in msg
    assert "Dragunov" in msg


# ---------------------------------------------------------------------------
# _scout_section
# ---------------------------------------------------------------------------

def _scout_battle(opp_pid: str, opp_name: str = "Opp", battle_at: int = 1000) -> dict:
    b = _battle(True, battle_at=battle_at)
    b["opp_polaris_id"] = opp_pid
    b["opp_name"] = opp_name
    return b


def test_scout_section_shows_repeat_opponent():
    """2戦以上した相手のスカウト情報が表示される。"""
    battles = [_scout_battle("pid1", "TestOpp"), _scout_battle("pid1", "TestOpp")]
    scout_data = {
        "pid1": {
            "total": 20, "win_rate": 60.0, "main_chara": "Jin",
            "recent_wins": 6, "recent_total": 10, "recent_win_rate": 60.0,
        }
    }
    result = _scout_section(battles, scout_data)
    assert result is not None
    assert "スカウト" in result
    assert "TestOpp" in result
    assert "Jin" in result
    assert "60%" in result


def test_scout_section_no_repeat_opponent():
    """リピートなし → None。"""
    battles = [_scout_battle("pid1"), _scout_battle("pid2")]
    scout_data = {"pid1": {"total": 20, "win_rate": 50.0, "main_chara": "Jin",
                            "recent_wins": 5, "recent_total": 10, "recent_win_rate": 50.0}}
    assert _scout_section(battles, scout_data) is None


def test_scout_section_empty_scout_data():
    """scout_data にないPIDは表示されない。"""
    battles = [_scout_battle("pid1"), _scout_battle("pid1")]
    assert _scout_section(battles, {}) is None


def test_scout_section_trend_up():
    """直近勝率が全体より5%以上高い場合 ↑ を表示。"""
    battles = [_scout_battle("pid1"), _scout_battle("pid1")]
    scout_data = {
        "pid1": {"total": 20, "win_rate": 40.0, "main_chara": "Jin",
                 "recent_wins": 8, "recent_total": 10, "recent_win_rate": 80.0}
    }
    result = _scout_section(battles, scout_data)
    assert result is not None
    assert "↑" in result


def test_scout_section_trend_down():
    """直近勝率が全体より5%以上低い場合 ↓ を表示。"""
    battles = [_scout_battle("pid1"), _scout_battle("pid1")]
    scout_data = {
        "pid1": {"total": 20, "win_rate": 80.0, "main_chara": "Jin",
                 "recent_wins": 2, "recent_total": 10, "recent_win_rate": 20.0}
    }
    result = _scout_section(battles, scout_data)
    assert result is not None
    assert "↓" in result


# ---------------------------------------------------------------------------
# build_community_weekly
# ---------------------------------------------------------------------------

def test_build_community_weekly_ranking_order():
    """net_rating 降順でランキングが並ぶ。"""
    players = [
        {"name": "Alice", "wins": 10, "losses": 5, "net_rating": 200},
        {"name": "Bob",   "wins": 8,  "losses": 7, "net_rating": 500},
        {"name": "Carol", "wins": 6,  "losses": 9, "net_rating": -100},
    ]
    msg = build_community_weekly(players, "2024/01/15")
    lines = [l for l in msg.split("\n") if any(p["name"] in l for p in players)]
    # Bob (500) > Alice (200) > Carol (-100)
    assert lines[0].index("Bob") < len(lines[0])
    bob_line   = next(i for i, l in enumerate(lines) if "Bob" in l)
    alice_line = next(i for i, l in enumerate(lines) if "Alice" in l)
    carol_line = next(i for i, l in enumerate(lines) if "Carol" in l)
    assert bob_line < alice_line < carol_line


def test_build_community_weekly_medals():
    """上位3人にメダル絵文字が付く。"""
    players = [
        {"name": "A", "wins": 10, "losses": 0, "net_rating": 300},
        {"name": "B", "wins": 8,  "losses": 2, "net_rating": 200},
        {"name": "C", "wins": 6,  "losses": 4, "net_rating": 100},
    ]
    msg = build_community_weekly(players, "2024/01/15")
    assert "🥇" in msg
    assert "🥈" in msg
    assert "🥉" in msg


def test_build_community_weekly_shows_net_rating():
    """net_rating が + 付きで表示される。"""
    players = [{"name": "A", "wins": 5, "losses": 5, "net_rating": 150}]
    msg = build_community_weekly(players, "2024/01/15")
    assert "+150" in msg


def test_build_community_weekly_negative_net_rating():
    """マイナスの net_rating は - 付きで表示される。"""
    players = [{"name": "A", "wins": 3, "losses": 7, "net_rating": -200}]
    msg = build_community_weekly(players, "2024/01/15")
    assert "-200" in msg


def test_build_community_weekly_contains_week():
    """週の開始日が含まれる。"""
    players = [{"name": "A", "wins": 5, "losses": 5, "net_rating": 0}]
    msg = build_community_weekly(players, "2024/01/15")
    assert "2024/01/15" in msg


# ---------------------------------------------------------------------------
# build_message with scout_data
# ---------------------------------------------------------------------------

def test_build_message_with_scout_data():
    """scout_data がある場合、スカウトセクションが表示される。"""
    b = _battle(True, battle_at=1000)
    b["opp_polaris_id"] = "pid1"
    b["opp_name"] = "ScoutOpp"
    b2 = _battle(False, battle_at=2000)
    b2["opp_polaris_id"] = "pid1"
    b2["opp_name"] = "ScoutOpp"
    scout_data = {
        "pid1": {"total": 20, "win_rate": 55.0, "main_chara": "Reina",
                 "recent_wins": 5, "recent_total": 10, "recent_win_rate": 50.0}
    }
    msg = build_message([b, b2], "2024/01/01", scout_data=scout_data)
    assert msg is not None
    assert "スカウト" in msg
    assert "ScoutOpp" in msg


def test_build_message_without_scout_data_no_scout_section():
    """scout_data なしの場合、スカウトセクションが表示されない。"""
    battles = [_battle(True, battle_at=1000)]
    msg = build_message(battles, "2024/01/01")
    assert msg is not None
    assert "スカウト" not in msg


# ---------------------------------------------------------------------------
# build_embed
# ---------------------------------------------------------------------------

def test_build_embed_returns_dict():
    battles = [_battle(True, battle_at=1000)]
    embed = build_embed(battles, "2024/01/01")
    assert embed is not None
    assert isinstance(embed, dict)


def test_build_embed_none_on_empty():
    assert build_embed([], "2024/01/01") is None


def test_build_embed_contains_date():
    battles = [_battle(True, battle_at=1000)]
    embed = build_embed(battles, "2024/01/01")
    embed_str = str(embed)
    assert "2024/01/01" in embed_str


def test_build_embed_contains_player_name():
    battles = [_battle(True, battle_at=1000)]
    embed = build_embed(battles, "2024/01/01", player_name="TestPlayer")
    embed_str = str(embed)
    assert "TestPlayer" in embed_str


def test_build_embed_has_color():
    battles = [_battle(True, battle_at=1000)]
    embed = build_embed(battles, "2024/01/01")
    assert "color" in embed


def test_build_embed_win_color_vs_loss_color():
    """勝ち越しと負け越しで color が異なる。"""
    win_battles  = [_battle(True)]  * 3 + [_battle(False)]
    lose_battles = [_battle(False)] * 3 + [_battle(True)]
    embed_win  = build_embed(win_battles,  "2024/01/01")
    embed_lose = build_embed(lose_battles, "2024/01/01")
    assert embed_win["color"] != embed_lose["color"]


# ---------------------------------------------------------------------------
# build_weekly_embed
# ---------------------------------------------------------------------------

def test_build_weekly_embed_returns_dict():
    battles = [_battle(True)]
    embed = build_weekly_embed(battles, "2024/01/15")
    assert embed is not None
    assert isinstance(embed, dict)


def test_build_weekly_embed_none_on_empty():
    assert build_weekly_embed([], "2024/01/15") is None


def test_build_weekly_embed_contains_week():
    battles = [_battle(True)]
    embed = build_weekly_embed(battles, "2024/01/15")
    assert "2024/01/15" in str(embed)


def test_build_weekly_embed_contains_player_name():
    battles = [_battle(True)]
    embed = build_weekly_embed(battles, "2024/01/15", player_name="Alice")
    assert "Alice" in str(embed)


# ---------------------------------------------------------------------------
# _hourly_section
# ---------------------------------------------------------------------------
# battle_at=1000 は JST で 1970-01-01 09:16:40 → hour=9
# battle_at=4000 は JST で 1970-01-01 10:06:40 → hour=10

def test_hourly_section_shows_hours_with_2plus_battles():
    """2試合以上の時間帯のみ表示される。"""
    battles = [
        _battle(won=True,  battle_at=1000),
        _battle(won=False, battle_at=1010),  # 同じ時間帯
        _battle(won=True,  battle_at=4000),  # 別の時間帯、1試合のみ
    ]
    result = _hourly_section(battles)
    assert result is not None
    # hour=9 は2試合あるので表示される
    assert "9" in result
    # hour=10 は1試合のみなので表示されない
    assert "10" not in result


def test_hourly_section_none_when_all_single():
    """全時間帯が1試合のみ → None を返す。"""
    battles = [
        _battle(won=True,  battle_at=1000),
        _battle(won=False, battle_at=4000),
    ]
    assert _hourly_section(battles) is None


def test_hourly_section_none_when_empty():
    """空リスト → None を返す。"""
    assert _hourly_section([]) is None


def test_hourly_section_shows_win_rate():
    """勝率が表示される（%が含まれる）。"""
    battles = [
        _battle(won=True,  battle_at=1000),
        _battle(won=True,  battle_at=1010),
        _battle(won=False, battle_at=1020),
    ]
    result = _hourly_section(battles)
    assert result is not None
    assert "%" in result


# ---------------------------------------------------------------------------
# _opp_rank_label / _quick_rank_distribution
# ---------------------------------------------------------------------------

def _quick_battle(won: bool, opp_rank: int | None = None, opp_chara: str = "Jin") -> dict:
    """クイックマッチ用バトルデータを生成するヘルパー。"""
    b = _battle(won=won, opp_chara=opp_chara, battle_type="quick")
    b["opp_rank"] = opp_rank
    return b


def test_opp_rank_label_quick_with_rank():
    """クイックマッチで opp_rank あり → 段位名を括弧付きで返す。"""
    b = _quick_battle(won=False, opp_rank=25)  # 25 = God of Destruction
    label = _opp_rank_label(b)
    assert label.startswith("(")
    assert label.endswith(")")
    assert len(label) > 2  # 括弧の中身が空でない


def test_opp_rank_label_quick_no_rank():
    """クイックマッチで opp_rank なし → 空文字。"""
    b = _quick_battle(won=False, opp_rank=None)
    assert _opp_rank_label(b) == ""


def test_opp_rank_label_ranked_battle():
    """ランク戦では段位を持っていても空文字を返す。"""
    b = _battle(won=True, battle_type="ranked")
    b["opp_rank"] = 20
    assert _opp_rank_label(b) == ""


def test_opp_rank_label_unknown_rank_id():
    """存在しない rank_id → 空文字（RANK_NAMES に登録なし）。"""
    b = _quick_battle(won=True, opp_rank=9999)
    assert _opp_rank_label(b) == ""


def test_quick_rank_distribution_single():
    """単一段位 → `<名前>×N` 形式を返す。"""
    battles = [_quick_battle(won=True, opp_rank=20)] * 3
    result = _quick_rank_distribution(battles)
    assert "×3" in result


def test_quick_rank_distribution_multiple():
    """複数段位 → 多い順にスラッシュ区切りで返す。"""
    battles = (
        [_quick_battle(won=True,  opp_rank=20)] * 4 +
        [_quick_battle(won=False, opp_rank=15)] * 2
    )
    result = _quick_rank_distribution(battles)
    assert "/" in result
    # 多い段位が先頭に来る
    first, second = result.split(" / ", 1)
    assert "×4" in first
    assert "×2" in second


def test_quick_rank_distribution_no_rank_data():
    """全バトルで opp_rank が None → 空文字を返す。"""
    battles = [_quick_battle(won=True, opp_rank=None)] * 3
    assert _quick_rank_distribution(battles) == ""


def test_quick_rank_distribution_empty():
    """空リスト → 空文字。"""
    assert _quick_rank_distribution([]) == ""


def test_build_message_shows_rank_for_quick():
    """build_message: クイックマッチの試合一覧に相手段位が表示される。"""
    b = _quick_battle(won=False, opp_rank=20, opp_chara="Bryan")
    b["my_chara"] = "Lee"
    b["my_rounds"] = 1
    b["opp_rounds"] = 2
    b["battle_at"] = 1000
    b["opp_polaris_id"] = "pid"
    b["opp_name"] = "Opp"
    b["my_power"] = None
    msg = build_message([b], "2026-04-10")
    assert msg is not None
    # 段位名が括弧付きで含まれているか
    assert "(" in msg


def test_build_message_no_rank_for_ranked():
    """build_message: ランク戦の試合一覧には相手段位が付かない。"""
    b = _battle(won=True, opp_chara="Jin", battle_type="ranked")
    b["opp_rank"] = 20
    b["opp_polaris_id"] = "pid"
    b["opp_name"] = "Opp"
    msg = build_message([b], "2026-04-10")
    assert msg is not None
    # ランク戦の対面行に括弧は付かない
    battle_lines = [line for line in msg.splitlines() if "⚔️" in line]
    assert all("(" not in line for line in battle_lines)


def test_build_message_quick_summary_includes_rank_dist():
    """build_message: クイック集計行に相手段位分布が含まれる。"""
    battles = [_quick_battle(won=True, opp_rank=20), _quick_battle(won=False, opp_rank=20)]
    for i, b in enumerate(battles):
        b["my_chara"] = "Lee"
        b["my_rounds"] = 2
        b["opp_rounds"] = 1
        b["battle_at"] = 1000 + i
        b["opp_polaris_id"] = f"pid{i}"
        b["opp_name"] = "Opp"
        b["my_power"] = None
    msg = build_message(battles, "2026-04-10")
    assert msg is not None
    assert "相手段位" in msg


def test_build_embed_shows_rank_for_quick():
    """build_embed: クイックマッチの試合一覧に相手段位が表示される。"""
    b = _quick_battle(won=False, opp_rank=20, opp_chara="Bryan")
    b["my_chara"] = "Lee"
    b["my_rounds"] = 1
    b["opp_rounds"] = 2
    b["battle_at"] = 1000
    b["opp_polaris_id"] = "pid"
    b["opp_name"] = "Opp"
    b["my_power"] = None
    result = build_embed([b], "2026-04-10")
    assert result is not None
    assert "(" in result["description"]


def test_build_embed_quick_field_includes_rank_dist():
    """build_embed: クイック欄に相手段位分布が含まれる。"""
    battles = [_quick_battle(won=True, opp_rank=20), _quick_battle(won=False, opp_rank=20)]
    for i, b in enumerate(battles):
        b["my_chara"] = "Lee"
        b["my_rounds"] = 2
        b["opp_rounds"] = 1
        b["battle_at"] = 1000 + i
        b["opp_polaris_id"] = f"pid{i}"
        b["opp_name"] = "Opp"
        b["my_power"] = None
    result = build_embed(battles, "2026-04-10")
    assert result is not None
    quick_fields = [f for f in result["fields"] if "クイック" in f["name"]]
    assert quick_fields
    assert "相手段位" in quick_fields[0]["value"]
