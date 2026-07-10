"""
bot/embeds.py のビュー層（Embed 構築・整形ヘルパー）テスト。
"""

import pytest
from bot.embeds import (
    _win_rate,
    _streak,
    _nemesis,
    _rating_summary,
    _matchup_matrix,
    _rank_winrate_breakdown,
    _quick_rank_chara_matrix,
    _scout_section,
    _opp_rank_label,
    _quick_rank_distribution,
    _embed_color,
    _winrate_bar,
    _daily_sparkline,
    _affinity_highlight,
    _my_chara_fields,
    build_community_weekly_embed,
    build_embed,
    build_rank_weekly_embed,
    build_quick_weekly_embed,
    build_monthly_embed,
    build_rank_change_embed,
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


def _scout_battle(opp_pid: str, opp_name: str = "Opp", battle_at: int = 1000) -> dict:
    b = _battle(True, battle_at=battle_at)
    b["opp_polaris_id"] = opp_pid
    b["opp_name"] = opp_name
    return b


def _quick_battle(won: bool, opp_rank: int | None = None, opp_chara: str = "Jin") -> dict:
    """クイックマッチ用バトルデータを生成するヘルパー。"""
    b = _battle(won=won, opp_chara=opp_chara, battle_type="quick")
    b["opp_rank"] = opp_rank
    return b


def _make_quick_mychara(my_chara: str, won: bool) -> dict:
    """自キャラ指定のクイックバトルを生成するヘルパー（使用キャラ別集計用）。"""
    b = _battle(won=won, my_chara=my_chara, battle_type="quick")
    return b


def _make_quick_round(won: bool, my_rounds: int, opp_rounds: int) -> dict:
    """ラウンド数指定のクイックバトルを生成するヘルパー（ラウンドの質用）。"""
    return _battle(won=won, my_rounds=my_rounds, opp_rounds=opp_rounds, battle_type="quick")


def _make_quick_mychara_full(my_chara: str, won: bool, opp_chara: str,
                             my_rounds: int, opp_rounds: int) -> dict:
    """自キャラ・相手キャラ・ラウンドを指定したクイックバトル（キャラ別ブロック用）。"""
    return _battle(won=won, my_chara=my_chara, opp_chara=opp_chara,
                   my_rounds=my_rounds, opp_rounds=opp_rounds, battle_type="quick")


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


def test_build_rank_weekly_embed_returns_dict():
    battles = [_battle(True, battle_type="ranked")]
    embed = build_rank_weekly_embed(battles, "2024/01/15")
    assert embed is not None
    assert isinstance(embed, dict)
    assert "ランク戦" in embed["title"]


def test_build_quick_weekly_embed_returns_dict():
    battles = [_battle(True, battle_type="quick")]
    embed = build_quick_weekly_embed(battles, "2024/01/15")
    assert embed is not None
    assert isinstance(embed, dict)
    assert "クイック" in embed["title"]


def test_build_rank_weekly_embed_none_on_empty():
    assert build_rank_weekly_embed([], "2024/01/15") is None


def test_build_quick_weekly_embed_none_on_empty():
    assert build_quick_weekly_embed([], "2024/01/15") is None


def test_build_rank_weekly_embed_none_when_only_quick():
    """クイックしかなければランク戦 Embed は None（投稿スキップ）。"""
    assert build_rank_weekly_embed([_battle(True, battle_type="quick")], "2024/01/15") is None


def test_build_quick_weekly_embed_none_when_only_ranked():
    """ランク戦しかなければクイック Embed は None（投稿スキップ）。"""
    assert build_quick_weekly_embed([_battle(True, battle_type="ranked")], "2024/01/15") is None


def test_build_rank_weekly_embed_contains_week():
    embed = build_rank_weekly_embed([_battle(True, battle_type="ranked")], "2024/01/15")
    assert "2024/01/15" in str(embed)


def test_build_rank_weekly_embed_contains_player_name():
    embed = build_rank_weekly_embed([_battle(True, battle_type="ranked")], "2024/01/15", player_name="Alice")
    assert "Alice" in str(embed)


def test_build_quick_weekly_embed_contains_player_name():
    embed = build_quick_weekly_embed([_battle(True, battle_type="quick")], "2024/01/15", player_name="Alice")
    assert "Alice" in str(embed)


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
    """複数段位 → rank_id 昇順（低段位→高段位）にスラッシュ区切りで返す。"""
    battles = (
        [_quick_battle(won=True,  opp_rank=20)] * 4 +
        [_quick_battle(won=False, opp_rank=15)] * 2
    )
    result = _quick_rank_distribution(battles)
    assert "/" in result
    # rank_id 昇順なので低い段位（15）が先頭に来る
    first, second = result.split(" / ", 1)
    assert "×2" in first
    assert "×4" in second


def test_quick_rank_distribution_no_rank_data():
    """全バトルで opp_rank が None → 空文字を返す。"""
    battles = [_quick_battle(won=True, opp_rank=None)] * 3
    assert _quick_rank_distribution(battles) == ""


def test_quick_rank_distribution_empty():
    """空リスト → 空文字。"""
    assert _quick_rank_distribution([]) == ""


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


def test_embed_color_empty_battles():
    """空リスト → Blurple (0x5865F2) を返す。"""
    assert _embed_color([]) == 0x5865F2


def test_embed_color_high_win_rate():
    """勝率60%以上 → 緑 (0x57F287)。"""
    battles = [_battle(True)] * 6 + [_battle(False)] * 4
    assert _embed_color(battles) == 0x57F287


def test_embed_color_low_win_rate():
    """勝率40%以下 → 赤 (0xED4245)。"""
    battles = [_battle(False)] * 6 + [_battle(True)] * 4
    assert _embed_color(battles) == 0xED4245


def test_embed_color_medium_win_rate():
    """勝率50% → 黄 (0xFEE75C)。"""
    battles = [_battle(True), _battle(False)]
    assert _embed_color(battles) == 0xFEE75C


def test_build_embed_ranked_with_rating():
    """ランク戦 + レーティング変動 → ランク欄にレーティング情報が含まれる。"""
    b = _battle(True, battle_type="ranked", rating_before=10000, rating_change=100, battle_at=1000)
    result = build_embed([b], "2024/01/01")
    assert result is not None
    ranked_fields = [f for f in result["fields"] if "ランク" in f["name"]]
    assert ranked_fields
    assert "10100" in ranked_fields[0]["value"]


def test_build_embed_shows_rank_name_in_power_field():
    """my_power + my_rank → 鉄拳力フィールド名に段位名が含まれる。"""
    b = _battle(True, battle_at=1000)
    b["my_power"] = 150000
    b["my_rank"]  = 20
    result = build_embed([b], "2024/01/01")
    assert result is not None
    assert "150,000" in str(result)


def test_build_embed_with_scout_data():
    """scout_data がある → Embed にスカウトフィールドが含まれる。"""
    def _b(won: bool, battle_at: int) -> dict:
        b = _battle(won=won, opp_chara="Reina", battle_at=battle_at)
        b["opp_polaris_id"] = "pid1"
        b["opp_name"] = "Scout"
        return b
    battles = [_b(True, 1000), _b(False, 2000)]
    scout_data = {
        "pid1": {"total": 30, "win_rate": 55.0, "main_chara": "Reina",
                 "recent_wins": 8, "recent_total": 10, "recent_win_rate": 80.0}
    }
    result = build_embed(battles, "2024/01/01", scout_data=scout_data)
    assert result is not None
    assert any("スカウト" in f["name"] for f in result["fields"])


def test_build_embed_with_chart():
    """has_chart=True → embed に image フィールドが含まれる。"""
    b = _battle(True, battle_at=1000)
    result = build_embed([b], "2024/01/01", has_chart=True)
    assert result is not None
    assert "image" in result
    assert result["image"]["url"] == "attachment://rating.png"


def test_rank_quick_embeds_are_separated():
    """ランクとクイックは別 Embed に完全分離される。"""
    battles = [
        _battle(True,  battle_type="ranked"),
        _battle(False, battle_type="quick"),
    ]
    rank  = build_rank_weekly_embed(battles, "2024/01/15")
    quick = build_quick_weekly_embed(battles, "2024/01/15")
    assert rank is not None and quick is not None
    # ランク Embed にクイック要素は混ざらない（タイトルのみで判定）
    assert "ランク戦" in rank["title"]
    assert "クイック" in quick["title"]


def test_build_rank_weekly_embed_net_rating_in_summary():
    """ランク戦レーティングデータあり → サマリー(description)に純変動 pt が含まれる。"""
    b = _battle(True, battle_type="ranked", rating_before=10000, rating_change=200, battle_at=1000)
    result = build_rank_weekly_embed([b], "2024/01/15")
    assert result is not None
    assert "+200pt" in result["description"]


def test_build_quick_weekly_embed_no_net_rating():
    """クイックはレートを持たない → サマリーに pt 表記は出ない。"""
    b = _battle(True, battle_type="quick", rating_change=200, battle_at=1000)
    result = build_quick_weekly_embed([b], "2024/01/15")
    assert result is not None
    assert "pt" not in result["description"]


def test_build_community_weekly_embed_returns_dict():
    """プレイヤーデータ → Embed dict を返す。"""
    players = [
        {"name": "Alice", "wins": 10, "losses": 5, "net_rating": 200},
        {"name": "Bob",   "wins": 8,  "losses": 7, "net_rating": -100},
    ]
    result = build_community_weekly_embed(players, "2024/01/15")
    assert isinstance(result, dict)
    assert "title" in result
    assert "description" in result


def test_build_community_weekly_embed_ranking_order():
    """net_rating 降順でランキングが並ぶ。"""
    players = [
        {"name": "C", "wins": 5, "losses": 5, "net_rating": 100},
        {"name": "A", "wins": 8, "losses": 2, "net_rating": 500},
        {"name": "B", "wins": 3, "losses": 7, "net_rating": 200},
    ]
    result = build_community_weekly_embed(players, "2024/01/15")
    desc = result["description"]
    assert desc.index("A") < desc.index("B") < desc.index("C")


def test_build_community_weekly_embed_medals():
    """上位3人にメダルが付く。"""
    players = [
        {"name": "A", "wins": 10, "losses": 0, "net_rating": 300},
        {"name": "B", "wins": 8,  "losses": 2, "net_rating": 200},
        {"name": "C", "wins": 6,  "losses": 4, "net_rating": 100},
    ]
    result = build_community_weekly_embed(players, "2024/01/15")
    desc = result["description"]
    assert "🥇" in desc
    assert "🥈" in desc
    assert "🥉" in desc


def test_build_quick_weekly_embed_omits_rank_distribution():
    """相手段位分布は段位別勝率と冗長なため、クイック Embed には出さない。"""
    battles = [
        _quick_battle(won=True,  opp_rank=20),
        _quick_battle(won=False, opp_rank=22),
    ]
    result = build_quick_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert not any("相手段位分布" in f["name"] for f in result["fields"])


def _ranked_battle(won: bool, opp_rank: int | None, opp_chara: str = "Jin",
                   my_rounds: int = 3, opp_rounds: int = 1) -> dict:
    """ランク戦バトル（opp_rank 付き）を生成するヘルパー。"""
    b = _battle(won=won, opp_chara=opp_chara, battle_type="ranked",
                my_rounds=my_rounds, opp_rounds=opp_rounds)
    b["opp_rank"] = opp_rank
    return b


def test_rank_winrate_breakdown_groups_and_orders_by_rank():
    """相手段位別に勝率を集計し、上位段位（格上）から並べる。"""
    battles = [
        _ranked_battle(won=True,  opp_rank=23),  # 鬼神: 1勝
        _ranked_battle(won=True,  opp_rank=20),  # 戦帝: 1勝1敗
        _ranked_battle(won=False, opp_rank=20),
    ]
    for b in battles:
        b["my_rank"] = 22  # 雷神
    result = _rank_winrate_breakdown(battles)
    assert result is not None
    lines = result.split("\n")
    kishin_i = next(i for i, l in enumerate(lines) if "鬼神" in l)
    sentei_i = next(i for i, l in enumerate(lines) if "戦帝" in l)
    assert kishin_i < sentei_i  # 格上（23）が先
    assert "✅" in lines[kishin_i]   # 100% → 勝ち越し
    assert "➖" in lines[sentei_i]   # 50% → 五分


def test_rank_winrate_breakdown_marks_above_and_below():
    """自分の段位を基準に格上🔺 / 格下🔻 を付ける。"""
    battles = [
        _ranked_battle(won=False, opp_rank=23),  # 鬼神（格上）
        _ranked_battle(won=True,  opp_rank=20),  # 戦帝（格下）
    ]
    for b in battles:
        b["my_rank"] = 22  # 雷神
    result = _rank_winrate_breakdown(battles)
    assert result is not None
    lines = result.split("\n")
    assert "🔺" in next(l for l in lines if "鬼神" in l)
    assert "🔻" in next(l for l in lines if "戦帝" in l)


def test_rank_winrate_breakdown_includes_quick():
    """クイックマッチも対象に含む（旧ランク戦専用版との違い）。"""
    b = _quick_battle(won=False, opp_rank=23)
    b["my_rank"] = 22
    result = _rank_winrate_breakdown([b])
    assert result is not None
    assert "鬼神" in result


def test_rank_winrate_breakdown_appends_avg_power():
    """opp_power が取れた段位には平均鉄拳力を併記する。"""
    b1 = _ranked_battle(won=True, opp_rank=22)
    b2 = _ranked_battle(won=False, opp_rank=22)
    b1["opp_power"] = 200000
    b2["opp_power"] = 210000
    b1["my_rank"] = b2["my_rank"] = 22
    result = _rank_winrate_breakdown([b1, b2])
    assert result is not None
    assert "平均鉄拳力 205k" in result


def test_rank_winrate_breakdown_omits_power_when_absent():
    """opp_power が無ければ平均鉄拳力の併記を省く（既存挙動を壊さない）。"""
    b = _ranked_battle(won=True, opp_rank=22)
    b["my_rank"] = 22
    result = _rank_winrate_breakdown([b])
    assert result is not None
    assert "平均鉄拳力" not in result


def test_rank_winrate_breakdown_self_rank_label():
    """同段の相手には (自分) を付ける。"""
    b = _ranked_battle(won=True, opp_rank=22)
    b["my_rank"] = 22
    result = _rank_winrate_breakdown([b])
    assert result is not None
    assert "自分" in result


def test_rank_winrate_breakdown_none_without_rank():
    """opp_rank が取れない試合のみ → None。"""
    assert _rank_winrate_breakdown([_quick_battle(won=True, opp_rank=None)]) is None


def test_rank_winrate_breakdown_normalizes_english_ranks():
    """ewgf 由来の英語文字列 rank（クイック実データの形式）も番号へ正規化して集計する。

    従来は int 前提で文字列を黙って捨てており、クイック週次の段位別勝率が
    まるごと欠損していた（2026-07-10 発見）。
    """
    b1 = _quick_battle(won=True,  opp_rank="Kishin")   # 鬼神 23
    b2 = _quick_battle(won=False, opp_rank="Fujin")    # 風神 21
    b1["my_rank"] = b2["my_rank"] = "Raijin"           # 雷神 22
    result = _rank_winrate_breakdown([b1, b2])
    assert result is not None
    lines  = result.split("\n")
    kishin = next(l for l in lines if "鬼神" in l)
    fujin  = next(l for l in lines if "風神" in l)
    assert "🔺" in kishin                              # 文字列 my_rank でも格上判定が働く
    assert "🔻" in fujin
    assert lines.index(kishin) < lines.index(fujin)    # 番号ベースの降順ソートが効く


def test_rank_winrate_breakdown_ignores_unknown_rank_string():
    """表に無い未知の段位文字列は集計対象外（誤った番号に化けない）。"""
    assert _rank_winrate_breakdown([_quick_battle(won=True, opp_rank="Warlord")]) is None


def test_my_chara_fields_includes_rank_breakdown():
    """キャラブロックに相手段位別の内訳が載る（段位不問のクイックで
    「このキャラが梯子のどこまで通用したか」を見るため）。"""
    battles = []
    for won, rank in [(True, "Kishin"), (True, "Kishin"), (False, "Fujin")]:
        b = _quick_battle(won=won, opp_rank=rank)
        b["my_chara"] = "Lee"
        battles.append(b)
    fields = _my_chara_fields(battles)
    assert len(fields) == 1
    assert "相手段位別" in fields[0]["value"]
    assert "鬼神" in fields[0]["value"]
    assert "風神" in fields[0]["value"]


def test_my_chara_fields_omits_rank_breakdown_without_ranks():
    """opp_rank が皆無なら段位内訳の見出しごと省く。"""
    battles = [_make_quick_mychara("Lee", True) for _ in range(3)]
    fields = _my_chara_fields(battles)
    assert len(fields) == 1
    assert "相手段位別" not in fields[0]["value"]


def test_build_quick_weekly_embed_rank_field_with_string_ranks():
    """実データ形式（英語文字列 rank）でも段位別勝率フィールドとキャラ別段位内訳が欠損しない。"""
    battles = []
    for i in range(3):
        b = _quick_battle(won=True, opp_rank="Tekken King")
        b["my_chara"] = "Lee"
        battles.append(b)
    result = build_quick_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert any("段位別勝率" in f["name"] for f in result["fields"])
    chara_field = next(f for f in result["fields"] if "Lee" in f["name"])
    assert "相手段位別" in chara_field["value"]
    assert "鉄拳王" in chara_field["value"]


def test_build_rank_weekly_embed_includes_rank_breakdown():
    """ランク戦に opp_rank があれば「段位別勝率」フィールドを含む。"""
    battles = [
        _ranked_battle(won=False, opp_rank=23),
        _ranked_battle(won=True,  opp_rank=20),
    ]
    for b in battles:
        b["my_rank"] = 22
    result = build_rank_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert any("段位別勝率" in f["name"] for f in result["fields"])


def test_build_rank_weekly_embed_prev_comparison_in_summary():
    """prev_battles を渡すと description に前週比（勝利数差）が含まれる。"""
    battles = [_battle(won=True), _battle(won=True)]  # 今週 2勝0敗（ranked）
    prev = [_battle(won=False)]                        # 前週 0勝1敗
    result = build_rank_weekly_embed(battles, "2024/01/15", prev_battles=prev)
    assert result is not None
    assert "前週比" in result["description"]
    assert "+2" in result["description"]   # 今週2勝 - 前週0勝


def test_build_rank_weekly_embed_no_prev_comparison_when_absent():
    """prev_battles 未指定なら description に前週比は無い（最長連勝/連敗のみ）。"""
    result = build_rank_weekly_embed([_battle(won=True)], "2024/01/15")
    assert result is not None
    assert "前週比" not in result["description"]


def test_build_rank_weekly_embed_summary_has_winrate_bar():
    """description にテキスト勝率バー（█/░）が含まれる。"""
    battles = [_battle(won=True), _battle(won=False)]
    result = build_rank_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert "█" in result["description"] or "░" in result["description"]


def test_build_rank_weekly_embed_has_affinity_highlight():
    """2戦以上のキャラがあれば「相性ハイライト」フィールドを含む。"""
    battles = [
        _battle(won=True,  opp_chara="King"), _battle(won=True,  opp_chara="King"),
        _battle(won=False, opp_chara="Jin"),  _battle(won=False, opp_chara="Jin"),
    ]
    result = build_rank_weekly_embed(battles, "2024/01/15")
    assert result is not None
    affinity = next((f for f in result["fields"] if "相性" in f["name"]), None)
    assert affinity is not None
    assert "得意" in affinity["value"]
    assert "苦手" in affinity["value"]


def test_build_quick_weekly_embed_field_count_is_small():
    """週次は要約。フィールド数は 5 以下に収まる。"""
    battles = [
        _quick_battle(won=True,   opp_rank=20),
        _quick_battle(won=False,  opp_rank=22),
    ]
    result = build_quick_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert len(result["fields"]) <= 5


# --- A: 使用キャラ別（自分） / B: ラウンドの質 -----------------------------

def test_my_chara_fields_groups_by_my_chara_in_usage_order():
    """自分の使用キャラごとに1フィールドを立て、使用数の多い順に並べる。"""
    battles = (
        [_make_quick_mychara("Reina", won=True)] * 5
        + [_make_quick_mychara("Lee", won=False)] * 3
    )
    fields = _my_chara_fields(battles)
    assert len(fields) == 2
    assert "Reina" in fields[0]["name"]   # 使用数が多い Reina が先
    assert "Lee"   in fields[1]["name"]


def test_my_chara_fields_excludes_low_sample_charas():
    """min_battles 未満のキャラはノイズとして除外する。"""
    battles = (
        [_make_quick_mychara("Reina", won=True)] * 5
        + [_make_quick_mychara("Lee", won=False)] * 1   # 1戦のみ → 除外
    )
    fields = _my_chara_fields(battles)
    assert len(fields) == 1
    assert "Reina" in fields[0]["name"]


def test_my_chara_fields_empty():
    assert _my_chara_fields([]) == []


def test_my_chara_fields_value_has_round_quality_and_affinity():
    """キャラフィールドの value にラウンドの質と相性が含まれる。"""
    battles = [
        _make_quick_mychara_full("Lee", won=True,  opp_chara="King", my_rounds=3, opp_rounds=0),
        _make_quick_mychara_full("Lee", won=True,  opp_chara="King", my_rounds=3, opp_rounds=1),
        _make_quick_mychara_full("Lee", won=False, opp_chara="Jin",  my_rounds=0, opp_rounds=3),
    ]
    fields = _my_chara_fields(battles)
    assert len(fields) == 1
    val = fields[0]["value"]
    assert "完封" in val and "接戦" in val   # ラウンドの質
    assert "得意" in val or "苦手" in val      # 相性（キャラ別）


def test_build_quick_weekly_embed_has_my_chara_fields():
    """クイック Embed に使用キャラ別フィールド（🥊）が含まれる。"""
    battles = [_make_quick_mychara("Lee", won=(i % 2 == 0)) for i in range(4)]
    result = build_quick_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert any(f["name"].startswith("🥊") for f in result["fields"])


def test_build_quick_weekly_embed_round_quality_not_in_summary():
    """ラウンドの質はキャラ別へ一本化したので description には出さない。"""
    battles = [_make_quick_round(won=True, my_rounds=3, opp_rounds=0) for _ in range(3)]
    result = build_quick_weekly_embed(battles, "2024/01/15")
    assert result is not None
    assert "完封" not in result["description"]


def test_build_rank_weekly_embed_no_round_quality_in_summary():
    """ランク Embed のサマリーにはラウンドの質を出さない（クイック専用）。"""
    result = build_rank_weekly_embed([_battle(won=True, battle_type="ranked")], "2024/01/15")
    assert result is not None
    assert "完封" not in result["description"]


def test_winrate_bar_full():
    """全勝 → バーが全て埋まる。"""
    assert _winrate_bar(10, 10, width=10) == "█" * 10


def test_winrate_bar_empty_total():
    """総数 0 → 空バー（ゼロ除算しない）。"""
    assert _winrate_bar(0, 0, width=10) == "░" * 10


def test_winrate_bar_half():
    """5割 → 半分が埋まる。"""
    bar = _winrate_bar(1, 2, width=10)
    assert bar.count("█") == 5
    assert bar.count("░") == 5


def test_daily_sparkline_marks_days_with_battles():
    """対戦のあった曜日にバー文字、無い曜日は中黒（·）。"""
    monday = 1705244400  # 2024-01-15 (月) 付近 JST
    battles = [
        _battle(won=True,  battle_at=monday + 3600),       # 月
        _battle(won=False, battle_at=monday + 86400 * 2),  # 水
    ]
    spark = _daily_sparkline(battles, "2024/01/15")
    assert spark is not None
    assert "月" in spark and "水" in spark
    assert "·" in spark  # 試合のない曜日


def test_daily_sparkline_invalid_date_returns_none():
    """週開始日のパースに失敗したら None（描画をスキップ）。"""
    assert _daily_sparkline([_battle(won=True)], "not-a-date") is None


def test_affinity_highlight_splits_strong_and_weak():
    """得意（勝ち越し）と苦手（負け越し）の両方を含む。"""
    battles = [
        _battle(won=True,  opp_chara="King"), _battle(won=True,  opp_chara="King"),
        _battle(won=False, opp_chara="Jin"),  _battle(won=False, opp_chara="Jin"),
    ]
    text = _affinity_highlight(battles)
    assert text is not None
    assert "King" in text
    assert "Jin" in text


def test_affinity_highlight_none_when_no_repeat():
    """2戦以上のキャラが無ければ None。"""
    assert _affinity_highlight([_battle(won=True, opp_chara="King")]) is None


def test_build_rank_change_embed_promotion():
    """昇格 → ゴールド色・昇格タイトル・矢印が含まれる。"""
    result = build_rank_change_embed("Alice", old_rank=15, new_rank=16)
    assert result["color"] == 0xFFD700
    assert "昇格" in result["title"]
    assert "→" in result["description"]
    assert "臥龍" in result["description"]
    assert "真龍" in result["description"]


def test_build_rank_change_embed_demotion():
    """降格 → 赤色・降格タイトルが含まれる。"""
    result = build_rank_change_embed("Bob", old_rank=16, new_rank=15)
    assert result["color"] == 0xED4245
    assert "降格" in result["title"]
    assert "真龍" in result["description"]
    assert "臥龍" in result["description"]


def test_build_rank_change_embed_unknown_rank():
    """RANK_NAMES に存在しない rank_id → Rank<N> 形式にフォールバック。"""
    result = build_rank_change_embed("Test", old_rank=999, new_rank=1000)
    assert "Rank999" in result["description"]
    assert "Rank1000" in result["description"]


def test_build_monthly_embed_returns_dict():
    """バトルあり → Embed dict を返す。"""
    battles = [_battle(True)]
    result = build_monthly_embed(battles, "2024年1月")
    assert result is not None
    assert isinstance(result, dict)
    assert "2024年1月" in result["title"]


def test_build_monthly_embed_none_on_empty():
    """バトルなし → None。"""
    assert build_monthly_embed([], "2024年1月") is None


def test_build_monthly_embed_with_prev_battles():
    """前月データあり → 前月比フィールドが含まれる。"""
    battles      = [_battle(True)] * 5 + [_battle(False)] * 3
    prev_battles = [_battle(True)] * 3 + [_battle(False)] * 5
    result = build_monthly_embed(battles, "2024年2月", prev_battles=prev_battles)
    assert result is not None
    assert any("前月比" in f["name"] for f in result["fields"])


def test_build_monthly_embed_no_prev_battles():
    """前月データなし → 前月比フィールドなし。"""
    battles = [_battle(True)]
    result  = build_monthly_embed(battles, "2024年1月", prev_battles=None)
    assert result is not None
    assert not any("前月比" in f["name"] for f in result["fields"])


def test_build_monthly_embed_with_ranked_and_quick():
    """ランク戦・クイックマッチ混在 → 両方のフィールドが含まれる。"""
    battles = [
        _battle(True,  battle_type="ranked"),
        _battle(False, battle_type="quick"),
    ]
    result = build_monthly_embed(battles, "2024年3月")
    assert result is not None
    assert any("ランク" in f["name"] for f in result["fields"])
    assert any("クイック" in f["name"] for f in result["fields"])


def test_build_monthly_embed_contains_player_name():
    """player_name → タイトルに含まれる。"""
    battles = [_battle(True)]
    result  = build_monthly_embed(battles, "2024年4月", player_name="Alice")
    assert result is not None
    assert "Alice" in result["title"]


def test_quick_rank_chara_matrix_basic():
    """クイック + opp_rank あり → 段位名とキャラ名が含まれる。"""
    battles = [
        _quick_battle(won=True,  opp_rank=22, opp_chara="Paul"),
        _quick_battle(won=False, opp_rank=22, opp_chara="Paul"),
        _quick_battle(won=True,  opp_rank=22, opp_chara="King"),
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "雷神" in result  # rank 22
    assert "Paul" in result
    assert "King" in result


def test_quick_rank_chara_matrix_rank_order_ascending():
    """段位昇順（弱い相手が上）で表示される。"""
    battles = [
        _quick_battle(won=True,  opp_rank=15, opp_chara="Jin"),   # 臥龍（弱め）
        _quick_battle(won=False, opp_rank=25, opp_chara="Law"),   # 鉄拳王（強め）
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert result.index("臥龍") < result.index("鉄拳王")


def test_quick_rank_chara_matrix_winrate_order_ascending():
    """同じ段位内で勝率昇順（苦手キャラが上）に並ぶ。"""
    battles = [
        _quick_battle(won=True,  opp_rank=20, opp_chara="Paul"),
        _quick_battle(won=True,  opp_rank=20, opp_chara="Paul"),   # Paul 100%
        _quick_battle(won=False, opp_rank=20, opp_chara="King"),
        _quick_battle(won=False, opp_rank=20, opp_chara="King"),   # King 0%
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert result.index("King") < result.index("Paul")


def test_quick_rank_chara_matrix_icons():
    """勝率に応じた ✅/❌/➖ が付く。"""
    battles = [
        _quick_battle(won=True,  opp_rank=20, opp_chara="Paul"),
        _quick_battle(won=True,  opp_rank=20, opp_chara="Paul"),   # 100% ✅
        _quick_battle(won=False, opp_rank=20, opp_chara="King"),
        _quick_battle(won=False, opp_rank=20, opp_chara="King"),   # 0%   ❌
        _quick_battle(won=True,  opp_rank=20, opp_chara="Kazuya"),
        _quick_battle(won=False, opp_rank=20, opp_chara="Kazuya"), # 50%  ➖
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "✅" in result
    assert "❌" in result
    assert "➖" in result


def test_quick_rank_chara_matrix_excludes_ranked():
    """ランク戦は除外され、クイックマッチのみ集計される。"""
    battles = [
        _battle(won=False, opp_chara="Paul", battle_type="ranked"),  # ranked → 除外
        _quick_battle(won=True, opp_rank=20, opp_chara="King"),
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "Paul" not in result
    assert "King" in result


def test_quick_rank_chara_matrix_excludes_no_rank():
    """opp_rank が None のクイック対戦は除外される。"""
    battles = [
        _quick_battle(won=False, opp_rank=None, opp_chara="Paul"),  # rank不明 → 除外
        _quick_battle(won=True,  opp_rank=20,   opp_chara="King"),
    ]
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "Paul" not in result
    assert "King" in result


def test_quick_rank_chara_matrix_all_no_rank_returns_none():
    """全バトルで opp_rank が None → None を返す。"""
    battles = [_quick_battle(won=True, opp_rank=None)] * 3
    assert _quick_rank_chara_matrix(battles) is None


def test_quick_rank_chara_matrix_empty_returns_none():
    """空リスト → None を返す。"""
    assert _quick_rank_chara_matrix([]) is None


def test_quick_rank_chara_matrix_rank_name_japanese():
    """段位名が日本語で表示される。"""
    battles = [_quick_battle(won=True, opp_rank=25, opp_chara="Jin")]  # 25 = 鉄拳王
    result = _quick_rank_chara_matrix(battles)
    assert result is not None
    assert "鉄拳王" in result


def test_build_embed_includes_quick_rank_chara_field():
    """クイック + opp_rank あり → Embed に段位別対戦成績フィールドが含まれる。"""
    battles = [
        _quick_battle(won=True,  opp_rank=22, opp_chara="Paul"),
        _quick_battle(won=False, opp_rank=22, opp_chara="King"),
    ]
    for i, b in enumerate(battles):
        b["my_chara"]  = "Lee"
        b["my_rounds"] = 2
        b["opp_rounds"] = 1
        b["battle_at"] = 1000 + i
        b["opp_polaris_id"] = f"pid{i}"
        b["opp_name"] = "Opp"
        b["my_power"] = None
    result = build_embed(battles, "2026-05-12")
    assert result is not None
    assert any("段位別" in f["name"] for f in result["fields"])


def test_build_embed_no_quick_rank_chara_field_when_no_rank():
    """クイックで全 opp_rank が None → 段位別対戦成績フィールドなし。"""
    battles = [_quick_battle(won=True, opp_rank=None, opp_chara="Paul")]
    battles[0].update({"my_chara": "Lee", "my_rounds": 2, "opp_rounds": 1,
                        "battle_at": 1000, "opp_polaris_id": "p", "opp_name": "Opp", "my_power": None})
    result = build_embed(battles, "2026-05-12")
    assert result is not None
    assert not any("段位別" in f["name"] for f in result["fields"])
