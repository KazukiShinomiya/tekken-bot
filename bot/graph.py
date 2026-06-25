"""
レーティング推移グラフ生成モジュール。
matplotlib がインストールされていない場合は None を返す（グラフなしで続行）。
"""

import io
import logging
from datetime import datetime

from bot.config import JST
from bot.models import Battle
from bot.stats import filter_rated_battles

logger = logging.getLogger(__name__)


def generate_rating_chart(battles: list[Battle], player_name: str = "Player") -> io.BytesIO | None:
    """
    過去バトルのレーティング推移グラフを PNG として BytesIO で返す。
    rating_before / rating_change が揃っているバトルのみ使用。
    matplotlib 未インストール時、またはデータ不足時は None を返す。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        matplotlib.rcParams["font.family"] = "Noto Sans CJK JP"
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        logger.warning("[graph] matplotlib が未インストールのためグラフをスキップ")
        return None

    rated = [b for b in filter_rated_battles(battles) if b.get("rating_before") is not None]
    if not rated:
        return None

    rated_sorted = sorted(rated, key=lambda x: x["battle_at"])
    dates = [datetime.fromtimestamp(b["battle_at"], JST) for b in rated_sorted]
    ratings = [(b.get("rating_before") or 0) + (b.get("rating_change") or 0) for b in rated_sorted]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(dates, ratings, marker="o", linewidth=2, markersize=4, color="#5865F2")
    ax.fill_between(dates, ratings, alpha=0.1, color="#5865F2")
    ax.set_title(f"{player_name} レーティング推移", fontsize=14)
    ax.set_ylabel("レーティング")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    fig.autofmt_xdate(rotation=30)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf


def _rolling_winrate(
    battles: list[Battle], window: int
) -> tuple[list[datetime], list[float]] | None:
    """時系列順に `window` 試合の勝率ローリング平均を計算する純関数（描画なし）。

    返り値は (各窓の終端日時, 勝率[0.0〜1.0]) のタプル。
    試合数が window 未満なら None。計算とPNG描画を分離してテスト可能にする。
    """
    sorted_battles = sorted(battles, key=lambda x: x["battle_at"])
    if len(sorted_battles) < window:
        return None

    wins = [1 if b.get("won") else 0 for b in sorted_battles]
    dates = [datetime.fromtimestamp(b["battle_at"], JST) for b in sorted_battles]

    rolling_wr = [
        sum(wins[i : i + window]) / window
        for i in range(len(wins) - window + 1)
    ]
    rolling_dates = dates[window - 1 :]
    return rolling_dates, rolling_wr


def generate_winrate_chart(
    battles: list[Battle],
    player_name: str = "Player",
    window: int = 7,
) -> io.BytesIO | None:
    """
    直近 `window` 試合の勝率ローリング平均グラフを PNG として返す。
    勝率 50% を基準線として、上を緑・下を赤で塗りつぶす。
    データが window 未満の場合は None を返す。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        matplotlib.rcParams["font.family"] = "Noto Sans CJK JP"
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("[graph] matplotlib が未インストールのためグラフをスキップ")
        return None

    rolled = _rolling_winrate(battles, window)
    if rolled is None:
        return None
    rolling_dates, rolling_wr = rolled

    fig, ax = plt.subplots(figsize=(10, 4))
    wr_pct = [w * 100 for w in rolling_wr]
    ax.plot(rolling_dates, wr_pct, linewidth=2, color="#43B581")
    ax.axhline(50, color="#888888", linewidth=1, linestyle="--", alpha=0.7)
    ax.fill_between(rolling_dates, wr_pct, 50, where=[w >= 50 for w in wr_pct], alpha=0.25, color="#43B581")
    ax.fill_between(rolling_dates, wr_pct, 50, where=[w < 50 for w in wr_pct], alpha=0.25, color="#ED4245")
    ax.set_title(f"{player_name} 勝率推移（直近{window}試合ローリング平均）", fontsize=14)
    ax.set_ylabel("勝率 (%)")
    ax.set_ylim(0, 100)
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate(rotation=30)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_chara_usage_chart(
    weekly_data: list[dict],
    player_name: str = "Player",
) -> io.BytesIO | None:
    """
    週別・自キャラ使用数の積み上げ棒グラフを PNG として返す。
    weekly_data は [{"week": "2026-W13", "my_chara": "Lee", "cnt": 5}, ...] 形式。
    データ不足または matplotlib 未インストール時は None を返す。
    """
    if not weekly_data:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        matplotlib.rcParams["font.family"] = "Noto Sans CJK JP"
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        logger.warning("[graph] matplotlib が未インストールのためキャラグラフをスキップ")
        return None

    # データをピボット: {week: {chara: cnt}}
    from collections import defaultdict
    pivot: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in weekly_data:
        pivot[row["week"]][row["my_chara"]] += row["cnt"]

    weeks = sorted(pivot.keys())
    if len(weeks) < 2:
        return None

    # 全期間で使用頻度が高い順にキャラを並べる
    total_by_chara: dict[str, int] = defaultdict(int)
    for week_data in pivot.values():
        for chara, cnt in week_data.items():
            total_by_chara[chara] += cnt
    charas = sorted(total_by_chara, key=total_by_chara.__getitem__, reverse=True)[:8]

    x = np.arange(len(weeks))
    width = 0.65
    colors = plt.cm.tab10.colors

    fig, ax = plt.subplots(figsize=(10, 4))
    bottoms = np.zeros(len(weeks))
    for i, chara in enumerate(charas):
        vals = np.array([pivot[w].get(chara, 0) for w in weeks], dtype=float)
        ax.bar(x, vals, width, bottom=bottoms, label=chara, color=colors[i % len(colors)])
        bottoms += vals

    ax.set_title(f"{player_name} キャラ使用数（週別）", fontsize=14)
    ax.set_ylabel("試合数")
    def _week_label(week_str: str) -> str:
        try:
            dt = datetime.strptime(f"{week_str}-1", "%Y-W%W-%w")
            return f"{dt.month}/{dt.day}〜"
        except ValueError:
            return week_str

    ax.set_xticks(x)
    ax.set_xticklabels([_week_label(w) for w in weeks], rotation=30, ha="right")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf
