#!/usr/bin/env python3
"""
LLM コメント自動評価スクリプト。

評価軸:
  length      (40点): コメントが 150 文字以内か
  chara_valid (40点): ハルシネーション（未対戦キャラ言及）がないか
  has_action  (20点): 具体的な改善提案が含まれるか

使い方:
  python tools/eval_comment.py --date 2026-04-11
  python tools/eval_comment.py --date 2026-04-11 --player ExodusOverseer
  python tools/eval_comment.py --date 2026-04-11 --runs 3
  python tools/eval_comment.py --date 2026-04-11 --runs 3 --json
"""

import argparse
import json
import sys
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from bot import db, analyzer, evaluator  # noqa: E402


def run_evaluation(date_str: str, player: str | None = None) -> dict:
    """1回分の評価を実行して結果を返す。戦績なし・LLM失敗時は空 dict。"""
    battles = db.get_battles_on_date(date_str, player_name=player)

    if not battles:
        print(f"[eval] {date_str} の戦績が見つかりません", file=sys.stderr)
        return {}

    comment = analyzer.analyze(battles, date_str, player_name=player or "")
    if not comment:
        print("[eval] LLM コメント生成失敗", file=sys.stderr)
        return {}

    result = evaluator.evaluate_comment(comment, battles)
    result["comment"]  = comment
    result["battles"]  = len(battles)
    result["date"]     = date_str
    result["player"]   = player or ""
    return result


def _print_result(result: dict, run_num: int | None = None) -> None:
    prefix = f"[Run {run_num}] " if run_num is not None else ""
    score   = result.get("score", 0)
    comment = result.get("comment", "")
    details = result.get("details", {})

    print(f"\n{prefix}{'━' * 42}")
    print(f"{prefix}スコア: {score}/100  (対戦数: {result.get('battles', 0)}件)")
    print(f"{prefix}コメント: {comment}")
    print(f"{prefix}{'─' * 42}")
    for axis, detail in details.items():
        print(f"{prefix}  [{axis:12}] {detail['score']:2}/{detail['max']}点  {detail['message']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM コメント品質評価ツール")
    parser.add_argument("--date",   required=True, help="対象日付 (YYYY-MM-DD)")
    parser.add_argument("--player", default=None,  help="プレイヤー名（省略時は全プレイヤー）")
    parser.add_argument("--runs",   type=int, default=1, help="評価回数 (default: 1)")
    parser.add_argument("--json",   action="store_true", help="JSON 形式で出力")
    args = parser.parse_args()

    results = []
    for i in range(1, args.runs + 1):
        label = f"{i}/{args.runs}" if args.runs > 1 else "1/1"
        print(f"[eval] 評価 {label} 実行中...", file=sys.stderr)

        result = run_evaluation(args.date, args.player)
        if result:
            results.append(result)
            if not args.json:
                _print_result(result, run_num=i if args.runs > 1 else None)

    if not results:
        sys.exit(1)

    # 複数回実行時の集計表示
    if args.runs > 1 and not args.json:
        scores = [r["score"] for r in results]
        print(f"\n{'━' * 42}")
        print(
            f"集計 ({len(scores)}回): "
            f"平均 {sum(scores) / len(scores):.1f}点 / "
            f"最低 {min(scores)}点 / 最高 {max(scores)}点"
        )

    if args.json:
        output = results if args.runs > 1 else results[0]
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
