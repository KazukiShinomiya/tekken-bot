"""
バトルデータから Discord Embed（dict）を構築するビュー層。

I/O（Webhook 送信）は bot.discord_post が担当する。このモジュールは
純粋関数のみ——データを受け取り整形済みの dict / 文字列を返す。副作用なし。
"""

import unicodedata
from collections import Counter
from datetime import datetime

from bot.config import (
    TEKKEN_ID, DISCORD_EMBED_MAX_FIELDS, MATCHUP_MATRIX_MAX_ROWS,
    DESCRIPTION_CODE_LIMIT, JST,
    RANK_NAMES, RANK_NAMES_EN, normalize_rank, UNKNOWN_CHARACTER,
    WIN_RATE_THRESHOLD, EMBED_COLOR_GOOD_WR, EMBED_COLOR_BAD_WR,
    SCOUT_TREND_THRESHOLD,
)
from bot.models import Battle
from bot.stats import (
    calculate_streak, aggregate_by_character, count_wins, count_losses,
    filter_rated_battles, detect_momentum, predict_rating_trend,
    get_most_common, round_quality,
)


# ---------------------------------------------------------------------------
# 整形ヘルパー（表の桁合わせ）
# ---------------------------------------------------------------------------

def _disp_width(s: str) -> int:
    """端末表示上の桁数を返す。全角（East Asian Wide/Fullwidth）は2桁として数える。

    段位名やキャラ名に日本語が混ざるため、len() では桁が合わない。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    """表示幅ベースで右側を空白詰めする。f"{s:<12}" の全角対応版。"""
    return s + " " * max(0, width - _disp_width(s))


def _code_block(text: str, limit: int = 1024) -> str:
    """テキストを Discord のコードブロックで囲む。

    Embed 本文はプロポーショナルフォントで描画されるため、空白で桁を揃えても
    そのままでは列が崩れる。等幅で表示させるにはコードブロックに入れるしかない。
    limit は囲んだ後の全長（Discord のフィールド値上限は 1024）。
    """
    fence_cost = 8  # "```\n" と "\n```"
    return "```\n" + text[: max(0, limit - fence_cost)] + "\n```"


# ---------------------------------------------------------------------------
# スタッツ計算
# ---------------------------------------------------------------------------

def _rank_name(rank_id: int | str | None) -> str:
    """整数または英語文字列の rank_id を日本語段位名に変換する。"""
    if rank_id is None:
        return ""
    if isinstance(rank_id, int):
        return RANK_NAMES.get(rank_id, "")
    return RANK_NAMES_EN.get(rank_id, rank_id)


def _rank_id(rank: int | str | None) -> int | None:
    """rank 値を段位番号へ正規化する。wank は整数・ewgf は英語文字列で返す。
    未知の文字列（表に無い段位名）は None。"""
    return normalize_rank(rank)


def _win_rate(battles: list[Battle]) -> str:
    if not battles:
        return "-"
    pct = count_wins(battles) / len(battles) * 100
    return f"{pct:.0f}%"


def _streak(sorted_battles: list[Battle]) -> tuple[int, int]:
    """時系列順バトルリストから (最長連勝, 最長連敗) を返す。"""
    return calculate_streak(sorted_battles)


def _nemesis(battles: list[Battle]) -> str | None:
    """2戦以上対戦したキャラの中で、最も勝率が低いキャラを返す。"""
    stats = aggregate_by_character(battles)

    candidates = [(chara, results) for chara, results in stats.items() if len(results) >= 2]
    if not candidates:
        return None

    worst_chara, worst_results = min(candidates, key=lambda x: sum(x[1]) / len(x[1]))
    wins   = sum(worst_results)
    losses = len(worst_results) - wins
    wr     = wins / len(worst_results) * 100

    if wins / len(worst_results) >= WIN_RATE_THRESHOLD:
        return None

    return f"{worst_chara} ({wins}勝{losses}敗, {wr:.0f}%)"


def _rating_summary(battles: list[Battle]) -> str:
    """当日の合計レーティング変動と最終レーティングを返す。"""
    rated = filter_rated_battles(battles)
    if not rated:
        return ""

    net_change = sum(b.get("rating_change") or 0 for b in rated)
    latest     = max(rated, key=lambda x: x["battle_at"])
    final_rating = (latest.get("rating_before") or 0) + (latest.get("rating_change") or 0)

    sign = "+" if net_change >= 0 else ""
    return f"{final_rating} ({sign}{net_change})"


def _matchup_matrix(battles: list[Battle], max_rows: int = MATCHUP_MATRIX_MAX_ROWS) -> str | None:
    """
    対戦キャラを対戦数の多い順にリスト表示する。
    勝率 > 50% → ✅、= 50% → ➖、< 50% → ❌
    試合データがない場合は None を返す。

    並びは対戦数降順（同数なら勝率昇順＝苦手なほうが上）。勝率降順にすると
    1〜2戦で100%のキャラが上位を占め、月次では最多対戦相手が下に沈んで
    「よく当たる相手にどう戦えたか」が読めなくなるため。
    max_rows を超えた分は末尾に件数だけ残して省く（黙って切り落とさない）。
    """
    stats = aggregate_by_character(battles)

    rows = [(chara, results) for chara, results in stats.items() if len(results) >= 1]
    if not rows:
        return None

    rows.sort(key=lambda x: (-len(x[1]), sum(x[1]) / len(x[1])))

    lines = ["📊 対戦成績"]
    for chara, results in rows[:max_rows]:
        n  = len(results)
        wr = sum(results) / n
        pct = f"{wr * 100:.0f}%"
        if wr > WIN_RATE_THRESHOLD:
            icon = "✅"
        elif wr < WIN_RATE_THRESHOLD:
            icon = "❌"
        else:
            icon = "➖"
        lines.append(f"  {_pad(chara, 12)} {n}戦 {pct:>4} {icon}")

    hidden = len(rows) - max_rows
    if hidden > 0:
        hidden_battles = sum(len(r[1]) for r in rows[max_rows:])
        lines.append(f"  ほか {hidden} キャラ（計 {hidden_battles} 戦）")

    return "\n".join(lines)


def _rank_winrate_breakdown(battles: list[Battle]) -> str | None:
    """相手段位別の勝率を、格上🔺 / 格下🔻 マーカー付きで返す。

    opp_rank が取れた全試合（クイック・ランク両方）が対象。クイックは自分より
    大きく上下する相手と当たるため、「負けたが相手は格上だった」という文脈を
    振り返りに残すのが狙い。自分の段位は最新試合の my_rank を基準にする。
    対象がなければ None。上位段位（格上）から順に並べる。
    勝率 > 50% → ✅、= 50% → ➖、< 50% → ❌
    opp_power が取れた段位には平均鉄拳力を併記し、同段位でも「どれくらいの
    地力の相手だったか」の文脈を残す。取れなければ省略する。
    """
    agg: dict[int, list[int]] = {}
    powers: dict[int, list[int]] = {}
    for b in battles:
        rank_id = _rank_id(b.get("opp_rank"))
        if rank_id is None:
            continue
        agg.setdefault(rank_id, []).append(1 if b.get("won") else 0)
        p = b.get("opp_power")
        if isinstance(p, int) and p > 0:
            powers.setdefault(rank_id, []).append(p)
    if not agg:
        return None

    # 自分の段位 = 最新試合の my_rank（格上／格下の基準。取れなければマーカー省略）
    latest  = max(battles, key=lambda x: x["battle_at"])
    my_rank = _rank_id(latest.get("my_rank"))

    def _marker(rank_id: int) -> str:
        if not isinstance(my_rank, int):
            return ""
        if rank_id > my_rank:
            return "🔺"
        if rank_id < my_rank:
            return "🔻"
        return "(自分)"

    lines = []
    for rank_id in sorted(agg, reverse=True):  # 上位段位（格上）から
        results = agg[rank_id]
        n   = len(results)
        wr  = sum(results) / n
        pct = f"{wr * 100:.0f}%"
        if wr > WIN_RATE_THRESHOLD:
            icon = "✅"
        elif wr < WIN_RATE_THRESHOLD:
            icon = "❌"
        else:
            icon = "➖"
        name   = _rank_name(rank_id) or f"Rank{rank_id}"
        marker = _marker(rank_id)
        label  = f"{name}{marker}" if marker else name
        line   = f"  {_pad(label, 14)} {n}戦 {pct:>4} {icon}"
        ps = powers.get(rank_id)
        if ps:
            avg_k = round(sum(ps) / len(ps) / 1000)
            line += f" (平均鉄拳力 {avg_k}k)"
        lines.append(line)

    return "\n".join(lines)


def _scout_section(battles: list[Battle], scout_data: dict[str, dict]) -> str | None:
    """
    リピート対戦相手のスカウトレポートを返す。
    scout_data: {polaris_id: {win_rate, main_chara, recent_wins, recent_total, recent_win_rate}}
    """
    pid_count: Counter = Counter(
        b.get("opp_polaris_id") for b in battles if b.get("opp_polaris_id")
    )
    repeat_pids = [pid for pid, cnt in pid_count.most_common() if cnt >= 2 and pid in scout_data]
    if not repeat_pids:
        return None

    lines = ["🔍 対戦相手スカウト"]
    for pid in repeat_pids:
        s = scout_data[pid]
        opp_name  = next((b.get("opp_name") for b in battles if b.get("opp_polaris_id") == pid), "???")
        wr        = s["win_rate"]
        recent_wr = s["recent_win_rate"]
        trend_icon = "↑" if recent_wr > wr + SCOUT_TREND_THRESHOLD else ("↓" if recent_wr < wr - SCOUT_TREND_THRESHOLD else "→")
        lines.append(
            f"  {opp_name}({s['main_chara']}) "
            f"直近{s['total']}戦 勝率{wr:.0f}% | "
            f"直近{s['recent_total']}戦 {s['recent_wins']}勝 ({recent_wr:.0f}%) {trend_icon}"
        )
    return "\n".join(lines)


def _power_part(b: Battle) -> str:
    """相手との鉄拳力差を '(鉄拳力差 +134,567)' 形式で返す。どちらかが None なら空文字。

    自分の鉄拳力は同一日でほぼ動かないため、全試合行に絶対値を並べると同じ数字の
    繰り返しになる（実測: 22戦の日に同じ値が22回）。自分の絶対値は 💥 フィールドに
    一度だけ出るので、行では差分だけを見せる。正=自分が上。
    """
    my_p  = b.get("my_power")
    opp_p = b.get("opp_power")
    if my_p is None or opp_p is None:
        return ""
    diff = my_p - opp_p
    sign = "+" if diff >= 0 else ""
    return f"(鉄拳力差 {sign}{diff:,})"


def _opp_rank_label(battle: Battle) -> str:
    """クイックマッチの場合のみ相手段位名を返す。ランク戦・段位不明は空文字。"""
    if battle.get("battle_type") != "quick":
        return ""
    rank_id = battle.get("opp_rank")
    if rank_id is None:
        return ""
    name = _rank_name(rank_id)
    return f"({name})" if name else ""


def _quick_rank_chara_matrix(battles: list[Battle]) -> str | None:
    """
    クイックマッチの相手段位×キャラ対戦成績を返す。
    opp_rank が不明な試合は除外。データなしは None を返す。
    段位昇順（弱い相手から）、段位内は勝率昇順（苦手キャラから）で表示する。
    """
    quick = [
        b for b in battles
        if b.get("battle_type") == "quick" and b.get("opp_rank") is not None
    ]
    if not quick:
        return None

    groups: dict[int, dict[str, list[bool]]] = {}
    for b in quick:
        rank_id = b["opp_rank"]
        if rank_id is None:   # 上の内包表記で除外済みだが型を絞り込む
            continue
        chara   = b.get("opp_chara") or UNKNOWN_CHARACTER
        groups.setdefault(rank_id, {}).setdefault(chara, []).append(bool(b["won"]))

    lines = []
    for rank_id in sorted(groups.keys()):
        chara_stats = groups[rank_id]
        rank_name   = _rank_name(rank_id) or f"Rank{rank_id}"
        rank_total  = sum(len(v) for v in chara_stats.values())
        rank_wins   = sum(sum(v) for v in chara_stats.values())
        rank_wr     = f"{rank_wins / rank_total * 100:.0f}%"
        lines.append(f"■ {rank_name} ({rank_total}戦 {rank_wr})")

        for chara, results in sorted(chara_stats.items(), key=lambda x: sum(x[1]) / len(x[1])):
            n    = len(results)
            wr   = sum(results) / n
            pct  = f"{wr * 100:.0f}%"
            icon = "✅" if wr > WIN_RATE_THRESHOLD else ("❌" if wr < WIN_RATE_THRESHOLD else "➖")
            lines.append(f"  {_pad(chara, 12)} {n}戦 {pct:>4} {icon}")

    return "\n".join(lines)


def _quick_rank_distribution(quick_battles: list[Battle]) -> str:
    """クイックマッチの相手段位分布を `God×4 / Kishin×3` 形式で返す。データなしは空文字。"""
    counts: dict[int | str, int] = {}
    for b in quick_battles:
        rank_id = b.get("opp_rank")
        if rank_id is not None:
            counts[rank_id] = counts.get(rank_id, 0) + 1
    if not counts:
        return ""
    def _sort_key(rank_id: int | str) -> int:
        return rank_id if isinstance(rank_id, int) else 999
    return " / ".join(
        f"{_rank_name(rid) or (rid if isinstance(rid, str) else f'Rank{rid}')}×{cnt}"
        for rid, cnt in sorted(counts.items(), key=lambda x: _sort_key(x[0]))
    )


# ---------------------------------------------------------------------------
# 週次サマリー（要約ビュー）専用ヘルパー
# ---------------------------------------------------------------------------

def _winrate_bar(wins: int, total: int, width: int = 10) -> str:
    """勝率をテキストバー（█ 埋め / ░ 空き）で表す。total<=0 は空バー（ゼロ除算しない）。"""
    if total <= 0:
        return "░" * width
    filled = max(0, min(width, round(wins / total * width)))
    return "█" * filled + "░" * (width - filled)


def _daily_sparkline(battles: list[Battle], week_start_str: str) -> str | None:
    """週の各曜日の勝率を 1 行のスパークラインで返す。

    week_start_str は "YYYY/MM/DD"（週の月曜）。パース不可なら None。
    試合のない曜日は中黒（·）、ある曜日は勝率を ▁〜█ の高さで表す。
    """
    try:
        start = datetime.strptime(week_start_str, "%Y/%m/%d").replace(tzinfo=JST)
    except (ValueError, TypeError):
        return None

    bars   = " ▁▂▃▄▅▆▇█"
    labels = "月火水木金土日"
    by_day: dict[int, list[bool]] = {}
    for b in battles:
        ts = b.get("battle_at")
        if ts is None:
            continue
        offset = (datetime.fromtimestamp(ts, JST).date() - start.date()).days
        if 0 <= offset < 7:
            by_day.setdefault(offset, []).append(bool(b["won"]))

    cells = []
    for d in range(7):
        res = by_day.get(d)
        if not res:
            cells.append(f"{labels[d]}·")
        else:
            idx = round(sum(res) / len(res) * 8)
            cells.append(f"{labels[d]}{bars[idx]}")
    return " ".join(cells)


def _affinity_highlight(battles: list[Battle]) -> str | None:
    """2戦以上対戦したキャラを、得意（勝ち越し）と苦手（負け越し）に分けて返す。

    各最大3キャラ。五分（=50%）はどちらにも含めない。対象がなければ None。
    """
    stats = aggregate_by_character(battles)
    rows = [(c, sum(r), len(r)) for c, r in stats.items() if len(r) >= 2]
    if not rows:
        return None

    strong = sorted((r for r in rows if r[1] / r[2] > WIN_RATE_THRESHOLD),
                    key=lambda x: -x[1] / x[2])[:3]
    weak   = sorted((r for r in rows if r[1] / r[2] < WIN_RATE_THRESHOLD),
                    key=lambda x: x[1] / x[2])[:3]

    def _fmt(items: list[tuple[str, int, int]]) -> str:
        return " / ".join(f"{c} {w}-{n - w}" for c, w, n in items)

    lines = []
    if strong:
        lines.append(f"得意  {_fmt(strong)}")
    if weak:
        lines.append(f"苦手  {_fmt(weak)}")
    return "\n".join(lines) if lines else None


# ---------------------------------------------------------------------------
# Discord Embed ビルダー
# ---------------------------------------------------------------------------

def _embed_color(battles: list[Battle]) -> int:
    """勝率に基づいて Embed カラーコード（int）を返す。"""
    if not battles:
        return 0x5865F2  # Blurple
    wr = count_wins(battles) / len(battles)
    if wr >= EMBED_COLOR_GOOD_WR:
        return 0x57F287  # 緑
    if wr <= EMBED_COLOR_BAD_WR:
        return 0xED4245  # 赤
    return 0xFEE75C      # 黄


def build_embed(
    battles: list[Battle],
    date_str: str,
    player_name: str | None = None,
    scout_data: dict[str, dict] | None = None,
    has_chart: bool = False,
) -> dict | None:
    """Discord Embed 形式の dict を返す。試合なしの場合は None。LLM コメントは含まない。"""
    if not battles:
        return None

    display_name = player_name or TEKKEN_ID
    sorted_b = sorted(battles, key=lambda x: x["battle_at"])

    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    quick  = [b for b in battles if b.get("battle_type") == "quick"]
    other  = [b for b in battles if b.get("battle_type") not in ("ranked", "quick")]

    # 試合一覧（description）
    # 列幅は固定せず、その日の最長に合わせる。固定幅だと "Yoshimitsu (武神)" のような
    # 長い組み合わせがはみ出し、以降の列が行ごとにずれる。
    rows = []
    for b in sorted_b:
        chara     = b.get("my_chara") or "???"
        opp       = b.get("opp_chara") or "???"
        rank_part = _opp_rank_label(b)
        opp_field = f"{opp} {rank_part}".rstrip() if rank_part else opp
        rows.append((chara, opp_field, b))

    w_chara = max((_disp_width(r[0]) for r in rows), default=0)
    w_opp   = max((_disp_width(r[1]) for r in rows), default=0)

    battle_lines = []
    for chara, opp_field, b in rows:
        icon       = "✅" if b["won"] else "❌"
        score      = f"{b['my_rounds']}-{b['opp_rounds']}"
        power_part = _power_part(b)
        line = f"{_pad(chara, w_chara)} vs {_pad(opp_field, w_opp)} {icon} {score}"
        if power_part:
            line += f"  {power_part}"
        battle_lines.append(line)
    # コードブロックで囲って等幅にする（プロポーショナルだと桁が揃わない）。
    # 上限に余裕を持たせるのは、投稿後に edit_llm_comment が description 冒頭へ
    # コメントを差し込み、全体を 4096 で切るため。閉じ側の ``` が落ちると崩れる。
    description = _code_block("\n".join(battle_lines), limit=DESCRIPTION_CODE_LIMIT)

    fields: list[dict] = []

    def _add_type_field(icon: str, label: str, subset: list[Battle]) -> None:
        if not subset:
            return
        w   = count_wins(subset)
        l   = count_losses(subset)
        val = f"{w}勝{l}敗 ({_win_rate(subset)})"
        if label == "ランク":
            rating = _rating_summary(subset)
            if rating:
                val += f"\n{rating}"
        if label == "クイック":
            dist = _quick_rank_distribution(subset)
            if dist:
                val += f"\n相手段位: {dist}"
        fields.append({"name": f"{icon} {label}", "value": val, "inline": True})

    _add_type_field("🏆", "ランク",   ranked)
    _add_type_field("⚡", "クイック", quick)
    _add_type_field("🎮", "その他",   other)

    # ラウンド勝率・接戦
    total_my  = sum(b.get("my_rounds",  0) or 0 for b in battles)
    total_opp = sum(b.get("opp_rounds", 0) or 0 for b in battles)
    total_r   = total_my + total_opp
    round_wr  = f"{total_my / total_r * 100:.0f}%" if total_r else "-"
    close     = sum(1 for b in battles if (b.get("my_rounds") or 0) + (b.get("opp_rounds") or 0) >= 5)
    fields.append({"name": "🎯 ラウンド勝率", "value": f"{round_wr} | 接戦: {close}試合", "inline": True})

    # 連勝・連敗
    max_win, max_lose = _streak(sorted_b)
    streak_parts = []
    if max_win  >= 2: streak_parts.append(f"連勝: {max_win}")
    if max_lose >= 2: streak_parts.append(f"連敗: {max_lose}")
    if streak_parts:
        fields.append({"name": "🔥 ストリーク", "value": " | ".join(streak_parts), "inline": True})

    # 天敵
    nemesis = _nemesis(battles)
    if nemesis:
        fields.append({"name": "😤 天敵", "value": nemesis, "inline": True})

    # 調子の波
    momentum = detect_momentum(sorted_b)
    if momentum:
        fields.append({"name": "📊 調子", "value": momentum, "inline": True})

    # 鉄拳力
    latest = max(battles, key=lambda x: x["battle_at"])
    if latest.get("my_power"):
        rank_name = _rank_name(latest.get("my_rank"))
        power_str = f"{latest['my_power']:,}"
        field_name = f"💥 {rank_name}" if rank_name else "💥 鉄拳力"
        fields.append({"name": field_name, "value": power_str, "inline": True})

    # 対戦マトリクス（ヘッダー行を除いてフィールドに格納）
    matrix = _matchup_matrix(battles)
    if matrix:
        matrix_body = "\n".join(matrix.split("\n")[1:])
        fields.append({"name": "📊 対戦成績", "value": _code_block(matrix_body), "inline": False})

    # スカウト
    if scout_data:
        scout = _scout_section(battles, scout_data)
        if scout:
            scout_body = "\n".join(scout.split("\n")[1:])
            fields.append({"name": "🔍 スカウト", "value": scout_body[:1024], "inline": False})

    # クイック 段位×キャラ対戦成績
    quick_rank_matrix = _quick_rank_chara_matrix(battles)
    if quick_rank_matrix:
        fields.append({"name": "⚡ クイック 段位別対戦成績",
                       "value": _code_block(quick_rank_matrix), "inline": False})

    embed: dict = {
        "title":       f"🎮 {display_name} 本日の戦果 ({date_str})",
        "color":       _embed_color(battles),
        "description": description,
        "fields":      fields[:DISCORD_EMBED_MAX_FIELDS],
    }
    if has_chart:
        embed["image"] = {"url": "attachment://rating.png"}

    return embed


def _build_period_stats_top(battles: list[Battle]) -> list[dict]:
    """週次・月次 Embed の共通上部フィールド（総合〜レーティング変動）を構築する。"""
    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    quick  = [b for b in battles if b.get("battle_type") == "quick"]
    rated  = filter_rated_battles(ranked)
    net_rating = sum(b.get("rating_change") or 0 for b in rated) if rated else None

    total_w = count_wins(battles)
    total_l = count_losses(battles)

    fields: list[dict] = []
    fields.append({"name": "🏆 総合", "value": f"{total_w}勝{total_l}敗 ({_win_rate(battles)})", "inline": True})
    if ranked:
        rw = count_wins(ranked)
        rl = count_losses(ranked)
        fields.append({"name": "📊 ランク", "value": f"{rw}勝{rl}敗 ({_win_rate(ranked)})", "inline": True})
    if quick:
        qw = count_wins(quick)
        ql = count_losses(quick)
        quick_val = f"{qw}勝{ql}敗 ({_win_rate(quick)})"
        dist = _quick_rank_distribution(quick)
        if dist:
            quick_val += f"\n相手段位: {dist}"
        fields.append({"name": "⚡ クイック", "value": quick_val, "inline": True})
    if net_rating is not None:
        sign = "+" if net_rating >= 0 else ""
        fields.append({"name": "📈 レーティング変動", "value": f"{sign}{net_rating}", "inline": True})
    return fields


def _build_prev_comparison(
    battles: list[Battle],
    prev_battles: list[Battle],
    label: str,
) -> dict:
    """前期間比較フィールド（前週比/前月比）を構築する。
    label は "前週" / "前月"。

    勝利数の差だけを出すと母数の違いが消える。実測例では 138戦→76戦 と試合数が
    半減した月に「勝利数 -49」とだけ出て、勝率は 71.7%→65.8%（-6pt）でしかない
    のに実力が急落したように読めた。試合数と勝率を併記し、差は勝率ポイントで示す。
    """
    total_w, total_l = count_wins(battles), count_losses(battles)
    prev_w,  prev_l  = count_wins(prev_battles), count_losses(prev_battles)
    cur_label  = f"今{label[1]}"

    lines = [
        f"{cur_label} {total_w}勝{total_l}敗 ({_win_rate(battles)})　{len(battles)}戦",
        f"{label} {prev_w}勝{prev_l}敗 ({_win_rate(prev_battles)})　{len(prev_battles)}戦",
    ]

    bits = []
    if battles and prev_battles:
        wr_diff = total_w / len(battles) * 100 - prev_w / len(prev_battles) * 100
        bits.append(f"勝率 {'+' if wr_diff >= 0 else ''}{wr_diff:.1f}pt")

    prev_rated = filter_rated_battles([b for b in prev_battles if b.get("battle_type") == "ranked"])
    prev_net   = sum(b.get("rating_change") or 0 for b in prev_rated) if prev_rated else None
    rated      = filter_rated_battles([b for b in battles if b.get("battle_type") == "ranked"])
    net_rating = sum(b.get("rating_change") or 0 for b in rated) if rated else None
    if prev_net is not None and net_rating is not None:
        rating_diff = net_rating - prev_net
        bits.append(f"レーティング差分 {'+' if rating_diff >= 0 else ''}{rating_diff}")

    if bits:
        lines.append(" ・ ".join(bits))
    return {"name": f"📊 {label}比", "value": "\n".join(lines), "inline": False}


def _build_period_stats_bottom(battles: list[Battle], power_label: str) -> list[dict]:
    """週次・月次 Embed の共通下部フィールド（最多キャラ〜対戦成績）を構築する。"""
    top_chara, top_chara_count = get_most_common(battles, "my_chara")
    top_opp,   top_opp_count   = get_most_common(battles, "opp_chara")

    fields: list[dict] = []
    fields.append({"name": "🥊 最多使用キャラ", "value": f"{top_chara} ({top_chara_count}戦)", "inline": True})
    fields.append({"name": "🎯 最多対戦相手", "value": f"{top_opp} ({top_opp_count}戦)", "inline": True})

    trend = predict_rating_trend(battles)
    if trend:
        slope = trend["slope_per_day"]
        sign  = "+" if slope >= 0 else ""
        fields.append({"name": "📈 レーティングトレンド", "value": f"{sign}{slope:.0f}/日", "inline": True})

    latest = max(battles, key=lambda x: x["battle_at"])
    if latest.get("my_power"):
        rank_name  = _rank_name(latest.get("my_rank"))
        power_str  = f"{latest['my_power']:,}"
        field_name = f"💥 {power_label}: {rank_name}" if rank_name else f"💥 {power_label}"
        fields.append({"name": field_name, "value": power_str, "inline": True})

    matrix = _matchup_matrix(battles)
    if matrix:
        matrix_body = "\n".join(matrix.split("\n")[1:])
        fields.append({"name": "📊 対戦成績", "value": _code_block(matrix_body), "inline": False})
    return fields


def _weekly_summary_lines(
    battles: list[Battle],
    week_start_str: str,
    prev_battles: list[Battle] | None,
    *,
    include_rating: bool,
) -> list[str]:
    """週次サマリーの description（一望できる要約）を行リストで返す。

    include_rating=True（ランク戦）: 1行目に純レート変動、前週比にレート差を含める。
    include_rating=False（クイック）: レートを持たないので勝敗のみで構成する。

    1行目: 純レート変動（ランク）・通算成績・勝率バー
    2行目: 前週比（prev あり）／最長連勝・連敗（prev なし）
    3行目: 曜日別スパークライン（週開始日がパースできた場合）
    """
    sorted_b = sorted(battles, key=lambda x: x["battle_at"])
    w, l = count_wins(battles), count_losses(battles)
    total = w + l
    max_win, max_lose = calculate_streak(sorted_b)

    net: int | None = None
    if include_rating:
        rated = filter_rated_battles([b for b in battles if b.get("battle_type") == "ranked"])
        net   = sum(b.get("rating_change") or 0 for b in rated) if rated else None

    def _streak_bits() -> list[str]:
        bits = []
        if max_win  >= 2: bits.append(f"最長{max_win}連勝")
        if max_lose >= 2: bits.append(f"最長{max_lose}連敗")
        return bits

    lines: list[str] = []

    head = ""
    if net is not None:
        head = f"**{'📈' if net >= 0 else '📉'} {'+' if net >= 0 else ''}{net}pt**　"
    lines.append(f"{head}{w}勝{l}敗　`{_winrate_bar(w, total)}` **{_win_rate(battles)}**")

    if prev_battles:
        prev_w = count_wins(prev_battles)
        diff_w = w - prev_w
        comp = f"前週比 {'▲' if diff_w >= 0 else '▼'} 勝利数 {'+' if diff_w >= 0 else ''}{diff_w}"
        if include_rating and net is not None:
            prev_rated = filter_rated_battles([b for b in prev_battles if b.get("battle_type") == "ranked"])
            prev_net   = sum(b.get("rating_change") or 0 for b in prev_rated) if prev_rated else None
            if prev_net is not None:
                rdiff = net - prev_net
                comp += f" ・ レート差 {'+' if rdiff >= 0 else ''}{rdiff}"
        bits = _streak_bits()
        if bits:
            comp += " ・ " + " ".join(bits)
        lines.append(comp)
    else:
        bits = _streak_bits()
        if bits:
            lines.append(" ・ ".join(bits))

    spark = _daily_sparkline(battles, week_start_str)
    if spark:
        lines.append(f"日別 ▏{spark}")

    return lines


def _my_chara_fields(
    battles: list[Battle], top_n: int = 4, min_battles: int = 3
) -> list[dict]:
    """自分の使用キャラごとに「戦績・ラウンドの質・相性・相手段位別」を1フィールドにまとめて返す。

    使用数の多い順。合算では像がぼけるため、相性・ラウンド質・段位内訳をキャラ単位へ下ろす。
    min_battles 未満のキャラは少数試行のノイズとして除外する。
    """
    groups: dict[str, list[Battle]] = {}
    for b in battles:
        groups.setdefault(b.get("my_chara") or UNKNOWN_CHARACTER, []).append(b)

    fields: list[dict] = []
    for mc, bs in sorted(groups.items(), key=lambda x: -len(x[1]))[:top_n]:
        if len(bs) < min_battles:
            continue
        cw, cl = count_wins(bs), count_losses(bs)
        name   = f"🥊 {mc}  {cw}勝{cl}敗 ({_win_rate(bs)})"

        rq = round_quality(bs)
        rq_bits = []
        if rq["round_wr_pct"] is not None:
            rq_bits.append(f"ラウンド {rq['round_wr_pct']}%")
        rq_bits.append(f"完封 {rq['sweep_wins']}勝{rq['sweep_losses']}敗")
        rq_bits.append(f"接戦 {rq['close_games']}")
        body = [f"`{_winrate_bar(cw, cw + cl, width=8)}`  " + " ・ ".join(rq_bits)]

        affinity = _affinity_highlight(bs)
        if affinity:
            body.append(affinity.replace("\n", " ／ "))

        # クイックは段位不問＝このキャラが梯子のどこまで通用したかが学びになる
        # （US: 2026-07-10 ユーザー提起「段位ごとにサブキャラとの結果が学び」）
        rank_lines = _rank_winrate_breakdown(bs)
        if rank_lines:
            # コードブロックぶんの余白を残して本体を組む（閉じ ``` を落とさないため）
            head = "\n".join(body) + "\n🏅 相手段位別\n"
            body = [head.rstrip("\n"), _code_block(rank_lines, limit=1024 - len(head))]

        fields.append({"name": name[:256], "value": "\n".join(body)[:1024], "inline": False})
    return fields


def build_rank_weekly_embed(
    battles: list[Battle],
    week_start_str: str,
    player_name: str | None = None,
    prev_battles: list[Battle] | None = None,
) -> dict | None:
    """ランク戦のみの週次振り返り Embed を返す。ランク戦が無ければ None。

    レートを持つランク戦に特化: 純レート変動・前週比（レート差含む）・段位別勝率・
    相性・週末鉄拳力。LLM コメントは呼び出し側が後追いで追記する。
    """
    ranked = [b for b in battles if b.get("battle_type") == "ranked"]
    if not ranked:
        return None
    display_name = player_name or TEKKEN_ID
    prev_ranked  = [b for b in (prev_battles or []) if b.get("battle_type") == "ranked"] or None

    description = "\n".join(
        _weekly_summary_lines(ranked, week_start_str, prev_ranked, include_rating=True)
    )[:4096]

    fields: list[dict] = []

    latest = max(ranked, key=lambda x: x["battle_at"])
    if latest.get("my_power"):
        rank_name  = _rank_name(latest.get("my_rank"))
        field_name = f"💥 週末鉄拳力: {rank_name}" if rank_name else "💥 週末鉄拳力"
        fields.append({"name": field_name, "value": f"{latest['my_power']:,}", "inline": True})

    rank_breakdown = _rank_winrate_breakdown(ranked)
    if rank_breakdown:
        fields.append({"name": "🏅 段位別勝率（🔺格上 / 🔻格下）",
                       "value": _code_block(rank_breakdown), "inline": False})

    affinity = _affinity_highlight(ranked)
    if affinity:
        fields.append({"name": "🎯 相性ハイライト（得意↑ / 苦手↓）", "value": affinity[:1024], "inline": False})

    return {
        "title":       f"📅 {display_name} 今週のランク戦（{week_start_str} 週）",
        "color":       _embed_color(ranked),
        "description": description,
        "fields":      fields[:DISCORD_EMBED_MAX_FIELDS],
    }


def build_quick_weekly_embed(
    battles: list[Battle],
    week_start_str: str,
    player_name: str | None = None,
    prev_battles: list[Battle] | None = None,
) -> dict | None:
    """クイックのみの週次振り返り Embed を返す。クイックが無ければ None。

    練習場としての色を出す: 概要は週全体の一望、その下に使用キャラごとの統計ブロック
    （戦績・ラウンドの質・相性）を積む。合算では消える「どのキャラで苦戦したか」を残す。
    クイックはレートを持たないため純レート/トレンド/LLM コメントは載せない。
    """
    quick = [b for b in battles if b.get("battle_type") == "quick"]
    if not quick:
        return None
    display_name = player_name or TEKKEN_ID
    prev_quick   = [b for b in (prev_battles or []) if b.get("battle_type") == "quick"] or None

    description = "\n".join(
        _weekly_summary_lines(quick, week_start_str, prev_quick, include_rating=False)
    )[:4096]

    fields: list[dict] = _my_chara_fields(quick)

    # 使用キャラが1体しかいない週は、キャラ別の「相手段位別」が全体の内訳と
    # 完全に一致する。同じ表を二度出しても情報は増えないので全体側を省く。
    used_charas = {b.get("my_chara") or UNKNOWN_CHARACTER for b in quick}
    if len(used_charas) >= 2:
        rank_breakdown = _rank_winrate_breakdown(quick)
        if rank_breakdown:
            fields.append({"name": "🏅 段位別勝率（🔺格上 / 🔻格下）",
                           "value": _code_block(rank_breakdown), "inline": False})

    return {
        "title":       f"⚡ {display_name} 今週のクイック（{week_start_str} 週）",
        "color":       _embed_color(quick),
        "description": description,
        "fields":      fields[:DISCORD_EMBED_MAX_FIELDS],
    }


def build_rank_change_embed(player_name: str, old_rank: int, new_rank: int) -> dict:
    """段位変化通知用の Embed dict を返す。"""
    old_name = RANK_NAMES.get(old_rank, f"Rank{old_rank}")
    new_name = RANK_NAMES.get(new_rank, f"Rank{new_rank}")
    if new_rank > old_rank:
        return {
            "title":       f"🎊 {player_name} 段位昇格！",
            "color":       0xFFD700,
            "description": f"**{old_name}** → **{new_name}**",
        }
    return {
        "title":       f"📉 {player_name} 段位降格",
        "color":       0xED4245,
        "description": f"**{old_name}** → **{new_name}**",
    }


def build_monthly_embed(
    battles: list[Battle],
    month_str: str,
    player_name: str | None = None,
    prev_battles: list[Battle] | None = None,
) -> dict | None:
    """月次サマリーの Embed dict を返す。試合なしの場合は None。LLM コメントは含まない。"""
    if not battles:
        return None

    display_name = player_name or TEKKEN_ID
    fields = _build_period_stats_top(battles)

    # 前月比（レーティング変動フィールドの直後に挿入）
    if prev_battles:
        fields.append(_build_prev_comparison(battles, prev_battles, "前月"))

    fields += _build_period_stats_bottom(battles, "月末鉄拳力")
    return {
        "title":  f"📅 {display_name} 月次サマリー（{month_str}）",
        "color":  _embed_color(battles),
        "fields": fields[:DISCORD_EMBED_MAX_FIELDS],
    }


def build_community_weekly_embed(players_stats: list[dict], week_start_str: str) -> dict:
    """部内ランキングの Embed dict を返す。"""
    sorted_players = sorted(players_stats, key=lambda p: p["net_rating"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]

    lines = []
    for i, p in enumerate(sorted_players):
        medal  = medals[i] if i < 3 else f"{i + 1}."
        sign   = "+" if p["net_rating"] >= 0 else ""
        total  = p["wins"] + p["losses"]
        wr_str = f"{p['wins'] / total * 100:.0f}%" if total else "-"
        lines.append(f"{medal} {p['name']}: {sign}{p['net_rating']} ({p['wins']}勝{p['losses']}敗 {wr_str})")

    return {
        "title":       f"🏆 格ゲー部 週間ランキング ({week_start_str} 週)",
        "color":       0xFFD700,  # ゴールド
        "description": "\n".join(lines),
    }
