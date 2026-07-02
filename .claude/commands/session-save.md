セッション終了時の状態を保存せよ。完了分は履歴へ厚く積み、SESSION_STATE.md は軽量に保つ。

## 目的

`SESSION_STATE.md` の肥大化を防ぐ運用コマンド。読む側（セッション開始時の状態確認）は
`.claude/settings.json` の SessionStart フックが自動注入する。このコマンドは**書く側**——
完了ログは `docs/session_history.md` へ退避し、`SESSION_STATE.md` は「現況・次の行動」だけに保つ。
（2026-07-02 に 748行・29Kトークンへ肥大化していたのを 50行へ分離した教訓に基づく）

## 手順

### 1. 現状確認
```bash
cd E:/work/tekken_bot && wc -l SESSION_STATE.md docs/session_history.md
```
`SESSION_STATE.md` が 60行を大きく超えていたら、古い完了ログが残留している合図。

### 2. 完了分を履歴へ追記
今セッションで完了した戦果を `docs/session_history.md` に
`### 完了（YYYY-MM-DD ○○）` 見出しで追記する。
- 追記位置は**完了ログ群の末尾**（`## データ取得アーキテクチャ` などの参照セクションの手前）＝時系列昇順を保つ
- commit ハッシュ・検証結果（tests/mypy/cov）・NAS デプロイ有無を残す
- 履歴はここに厚く積んでよい（普段は読み込まれない）

### 3. SESSION_STATE.md を軽量更新
`SESSION_STATE.md` の各節を最新化する。**新規の完了ログをここに積まない**。
- `## 最終更新` → 当日の日付
- `## 現在の状況` → 1〜3行で現状
- `## 前回の戦果` → 今セッションの完了を数行で（詳細は履歴へ）
- `## 次の行動` → 次セッションで最初にやること。★引き継ぎ警告（却下済み案・地雷）は**消さない**
- `## 次回TODO` / `## 決定事項・メモ` → 更新

**守るべき規律**:
- 全体で **50〜60行**を目安に収める（超えたら古い節を履歴へ移す）
- 版数・タイムアウト等の**可変値は書かない**（`config.py` / `pyproject.toml` が真実の源）
- ユーザーが却下した案・再発防止の経緯など「次の私への警告」は要約して残す

### 4. 検証
```bash
cd E:/work/tekken_bot && wc -l SESSION_STATE.md
```
軽量（目安 60行以内）に収まったことを確認してユーザーに報告する。

### 5. コミット（任意）
`SESSION_STATE.md` は `.gitignore` 済み（ローカル作業ファイル）。
git に乗るのは `docs/session_history.md` のみ。コミットが要るか**ユーザーに確認**してから
`git add docs/session_history.md && git commit` する（不可逆操作は明示承認を得る）。
