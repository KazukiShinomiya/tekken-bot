---
name: health-check
description: プロジェクトの健全性を一手で点検する。テスト・型検査・カバレッジ・秘匿情報スキャン・git衛生を順に確認し、Anthropic ベストプラクティスへの適合を報告する。リリース前やセッション開始時の索敵に使う。
---

# プロジェクト健全性点検

テスト品質・秘匿情報・git 衛生を順に索敵し、最後に表で総括する。
各ステップの結果を解釈して報告すること。失敗は隠さず、事実をそのまま伝える。

## 手順

### 1. テスト + 型検査 + カバレッジ
CI と同じ基準で回す（`.github/workflows/test.yml` 準拠）。
```bash
python -m mypy bot main.py exporter.py scheduler.py
python -m pytest tests/ -q --cov=bot --cov=main --cov-fail-under=90
```
- mypy エラー、テスト失敗、カバレッジ90%未満があれば**要修正**として報告。

### 2. 秘匿情報スキャン（最重要）
追跡ファイル・設定にキーやトークンが平文で混入していないか走査する。
```bash
# git 追跡対象に .env / DB / キーが紛れていないか
git ls-files | grep -iE '\.env$|\.db$|secret|credential' || echo "OK: 追跡対象に秘匿ファイルなし"
# API キー・Bearer トークンの平文（.git ディレクトリは除外）
grep -rnE '(api[_-]?key|bearer|token|password)\s*[=:]\s*["a-zA-Z0-9]{12,}' . \
  --include='*.py' --include='*.json' --include='*.md' 2>/dev/null \
  | grep -viE '\.example|getenv|os\.environ|config\.' || echo "OK: 平文の秘匿情報なし"
# git 履歴へのキー流出（疑わしい文字列があれば差し替えて実行）
# git log --all -p -S '<疑わしいキー>' --oneline | head
```
- ヒットしたら**深刻**として即報告。`.env` から読む形になっているかを必ず確認する。

### 3. git 衛生
無視すべき生成物が追跡対象・未無視で残っていないか確認する。
```bash
git status --short
git check-ignore .coverage *.db .pytest_cache .mypy_cache bot/backups/ 2>/dev/null
```
- 生成物（DB・キャッシュ・カバレッジ・バックアップ）が `?? ` で出るなら `.gitignore` 補強を提案。

### 4. 設定ファイルの衛生
`settings.local.json` が一回限りのデバッグコマンドで肥大化していないか。
```bash
grep -cE '"(WebFetch|Bash|Read|PowerShell)' .claude/settings.local.json
```
- 概ね50を超え、巨大なワンライナーが目立つなら、汎用パターンへの集約を提案。
- プロジェクト無関係の許可はグローバル `~/.claude/settings.local.json` への移設を提案。

### 5. 総括
以下の形式で報告する。

| 点検項目 | 結果 | 備考 |
|---------|------|------|
| テスト/型/カバレッジ | ✅/❌ | |
| 秘匿情報 | ✅/❌ | |
| git 衛生 | ✅/❌ | |
| 設定衛生 | ✅/❌ | |

問題があれば深刻度順に並べ、修正の着手順を提案する。
取り消せない操作（削除・上書き）の前には必ずバックアップを取り、実行後に再検証する。
