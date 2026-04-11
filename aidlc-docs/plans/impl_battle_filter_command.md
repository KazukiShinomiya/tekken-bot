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

- [ ] **Step 1: DB クエリ追加** (`bot/db.py`)
  - `get_battles_by_opp_chara(chara_name: str, since_ts: int = 0, player_name: str | None = None) -> list[Battle]`
  - `get_battles_on_date_and_chara(date_str: str, chara_name: str, player_name: str | None = None) -> list[Battle]`

- [ ] **Step 2: スラッシュコマンド追加** (`bot/slash_commands.py`)
  - `/tekken filter chara <name>` → `cmd_filter_chara`
  - `/tekken filter date <YYYY-MM-DD>` → `cmd_filter_date`
  - 組み合わせは `chara` + `date` 両方のオプションで1コマンドに統合
  - 結果は `build_embed()` を流用して Embed 表示

- [ ] **Step 3: テスト追加** (`tests/test_db.py`, `tests/test_slash_commands.py`)
  - DB クエリのユニットテスト（キャラ名部分一致・日付フィルタ）
  - コマンドハンドラの mock テスト

---

## 完了条件

- [ ] `python -m pytest tests/` 全通過
- [ ] mypy 0 エラー
- [ ] `/tekken filter` コマンドが Discord で正常動作
- [ ] NAS デプロイ完了

---

## 備考

- `get_battles_by_opp_chara` は既存の `search_battles_vs_opponent` と重複しないよう注意
- チャラ名は CHARA_NAMES との部分一致（大文字小文字を無視）で検索する
- 結果が0件の場合は「該当する対戦データがありません」を返す
