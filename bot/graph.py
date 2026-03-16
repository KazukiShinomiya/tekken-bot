"""
レーティング推移グラフ生成モジュール。
matplotlib がインストールされていない場合は None を返す（グラフなしで続行）。
"""

import io
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))


def generate_rating_chart(battles: list[dict], player_name: str = "Player") -> io.BytesIO | None:
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

    rated = [
        b for b in battles
        if b.get("rating_before") is not None and b.get("rating_change") is not None
    ]
    if not rated:
        return None

    rated_sorted = sorted(rated, key=lambda x: x["battle_at"])
    dates = [datetime.fromtimestamp(b["battle_at"], JST) for b in rated_sorted]
    ratings = [b["rating_before"] + b["rating_change"] for b in rated_sorted]

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
