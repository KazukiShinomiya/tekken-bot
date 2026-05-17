"""
DB 内の stage_id 一覧を表示する調査ツール。

STAGE_NAMES マッピングを埋めるために、実際の対戦データからどの stage_id が
存在するかを確認する。対戦日時と照合してステージを特定できる。

使い方:
    python tools/check_stages.py
    python tools/check_stages.py --samples    # 各 stage_id の直近3試合を表示
"""

import sys
import argparse
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from dotenv import load_dotenv
load_dotenv()

import sqlite3
from bot.config import DB_PATH, STAGE_NAMES
from bot import fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="DB 内の stage_id を一覧表示する")
    parser.add_argument("--samples", action="store_true", help="各 stage_id の直近3試合を表示")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # stage_id ごとの集計
    rows = conn.execute("""
        SELECT stage_id, COUNT(*) AS total, SUM(won) AS wins
        FROM battles
        WHERE stage_id IS NOT NULL
        GROUP BY stage_id
        ORDER BY total DESC
    """).fetchall()

    if not rows:
        print("DB に stage_id データがありません（wank バルク API 未取得の可能性）。")
        return

    print(f"{'stage_id':>10}  {'試合数':>6}  {'勝':>4}  {'敗':>4}  {'勝率':>6}  ステージ名")
    print("-" * 60)
    for r in rows:
        sid   = r["stage_id"]
        total = r["total"]
        wins  = r["wins"]
        wr    = wins / total * 100 if total else 0
        name  = STAGE_NAMES.get(sid, "（未設定）")
        print(f"{sid:>10}  {total:>6}  {wins:>4}  {total-wins:>4}  {wr:>5.1f}%  {name}")

    if args.samples:
        print()
        for r in rows:
            sid = r["stage_id"]
            samples = conn.execute("""
                SELECT battle_at, my_chara, opp_chara, won
                FROM battles
                WHERE stage_id = ?
                ORDER BY battle_at DESC
                LIMIT 3
            """, (sid,)).fetchall()

            name = STAGE_NAMES.get(sid, f"Stage #{sid}")
            print(f"\n[{name}] stage_id={sid}")
            for s in samples:
                result_str = "勝" if s["won"] == 1 else "負"
                my_c   = fetcher.CHARA_NAMES.get(s["my_chara"],  f"#{s['my_chara']}")
                opp_c  = fetcher.CHARA_NAMES.get(s["opp_chara"], f"#{s['opp_chara']}")
                print(f"  {s['battle_at']}  {my_c} vs {opp_c}  {result_str}")

    conn.close()
    print()
    print("ヒント: STAGE_NAMES を埋めるには bot/config.py の STAGE_NAMES dict に")
    print("        {stage_id: 'ステージ名', ...} 形式で追記してください。")
    print("        対戦日時と照合して stage_id ↔ ステージ名を特定できます。")


if __name__ == "__main__":
    main()
