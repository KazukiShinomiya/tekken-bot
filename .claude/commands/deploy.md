テスト実行 → コミット → プッシュ → NAS デプロイ を順に実行せよ。

## 手順

### 1. テスト（CI 同等検査）
CI（`.github/workflows/test.yml`）と同じ検査をローカルで先行実行し、
コミット前に mypy／カバレッジ失敗を捕まえる。

リポジトリルート（CC の作業ディレクトリ）で実行する。機によってパスが異なるため
絶対パスを書かない。リポジトリ内に `.venv` があればそちらの python を使う
（システム Python に mypy/pytest が無い機がある。`.githooks/pre-push` も同じ判断をする）。

```bash
python -m mypy bot main.py exporter.py scheduler.py
python -m pytest tests/ -q --cov=bot --cov=main --cov-fail-under=90
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
ssh tekken-nas 'cd ~/tekken_bot && git pull && docker compose up -d --build'
```

### 6. 動作確認
```bash
ssh tekken-nas 'docker ps --format "table {{.Names}}\t{{.Status}}"'
```
全コンテナが `Up` になっていることを確認してユーザーに報告する。

---

## 実行環境による差

`tekken-nas` は `~/.ssh/config` のホストエイリアス（未設定なら CLAUDE.md の
「SSH 接続」を参照して先に用意する）。

**Windows 側 CC から実行する場合のみ**、ステップ5・6 の `ssh` を
`wsl bash -c "ssh tekken-nas '...'"` と包む。WSL 内の tmux CC およびネイティブ
Linux 機では素の `ssh` でよい。判別は `/proc/version` に `microsoft` を含むか。
