# 計画: バトルログ検索コマンド（US-403）

**Intent**: `/tekken filter` スラッシュコマンドを追加し、キャラ名・日付でバトルログを絞り込んで Embed 表示する。  
**Unit**: Unit 4 — スラッシュコマンド  
**関連 User Stories**: `aidlc-docs/requirements/new_features.md#US-403`

---

## 背景

現在 `/tekken vs <name>` で対戦相手名での検索はできるが、  
キャラ名や日付での絞り込みはできない。  
苦手キャラの対策研究時に「最近 Bryan と何戦したか」をすぐ確認したいニーズがある。

---

## ステップ

- [x] **Step 1: DB クエリ追加** (`bot/db.py`)
  - `get_battles_by_opp_chara` に `since_ts: int = 0` パラメータを追加（既存関数を拡張）
  - `get_battles_on_date` は既存実装をそのまま流用

- [x] **Step 2: スラッシュコマンド追加** (`bot/slash_commands.py`)
  - `/tekken filter` を `chara` / `date` / `days` の3オプションで1コマンドに統合
  - date 単独: `get_battles_on_date` → 時刻・試合種別・スコア付き一覧 Embed
  - chara + 期間: `get_battles_by_opp_chara(since_ts=...)` → 勝率・直近10試合 Embed

- [x] **Step 3: テスト追加** (`tests/test_db.py`, `tests/test_slash_commands.py`)
  - DB: `since_ts` フィルタ・ゼロ値全件返し・player_name 複合フィルタ (+3件)
  - コマンドハンドラ: 引数なし/invalid-date/no-results/embed返却/days/chara+date (+9件)

---

## 完了条件

- [x] `python -m pytest tests/` 全通過（427 passed）
- [x] mypy 0 エラー（bot/db.py, bot/slash_commands.py）
- [x] `/tekken filter` コマンドが Discord で正常動作
- [x] NAS デプロイ完了（2026-04-11, commit ef54786）

---

## 備考

- `get_battles_by_opp_chara` は既存の `search_battles_vs_opponent` と重複しないよう注意
- チャラ名は CHARA_NAMES との部分一致（大文字小文字を無視）で検索する
- 結果が0件の場合は「該当する対戦データがありません」を返す
