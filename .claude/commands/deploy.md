テスト実行 → コミット → プッシュ → NAS デプロイ を順に実行せよ。

## 手順

### 1. テスト（CI 同等検査）
CI（`.github/workflows/test.yml`）と同じ検査をローカルで先行実行し、
コミット前に mypy／カバレッジ失敗を捕まえる。

```bash
cd E:/work/tekken_bot && python -m mypy bot main.py exporter.py scheduler.py
cd E:/work/tekken_bot && python -m pytest tests/ -q --cov=bot --cov=main --cov-fail-under=90
```
いずれか失敗したら中止してユーザーに報告する。
（push 段では `.githooks/pre-push` が同検査を再度強制する＝二重の防壁）

### 2. 変更確認
```bash
git status && git diff --stat
```
コミットすべき変更がなければステップ3をスキップ。

### 3. コミット
ステージングされていないファイルがあれば `git add` し、
コミットメッセージを考えて `git commit` する。

### 4. プッシュ
```bash
git push origin master
```

### 5. NAS デプロイ
```bash
wsl bash -c "ssh -i ~/.ssh/tekken_deploy ubuntu@10.0.0.254 'cd ~/tekken_bot && git pull && docker compose up -d --build'"
```

### 6. 動作確認
```bash
wsl bash -c "ssh -i ~/.ssh/tekken_deploy ubuntu@10.0.0.254 'docker ps --format \"table {{.Names}}\t{{.Status}}\"'"
```
全コンテナが `Up` になっていることを確認してユーザーに報告する。
