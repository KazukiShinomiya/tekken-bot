直近の CI 失敗を索敵し、原因を特定して修復まで導け。

CI が落ちた時の反応的・診断特化フロー。`deploy`（前進）や `health-check`
（予防的総合点検）とは役割が違う。検査内容の真実の源は
`.github/workflows/test.yml`。

## 手順

### 1. 直近の失敗を特定
```bash
gh run list --limit 5
```
最新の `failure` を見つける。直近 push が緑なら「現在 CI は通っている」と
報告して終了する（落ちていないものを直さない）。

### 2. 失敗ログから原因を抽出
```bash
gh run view <run-id> --log-failed
```
どのステップ（mypy / pytest / coverage 等）で、どのファイル:行が原因かを
読み取る。「何が起きたか」→「なぜ起きたか」の順で root cause を掴む。

### 3. 原因の提示と修正
- 該当ファイルを `Read` し、原因行を確認する
- 修正方針をユーザーに説明してから `Edit` する
- 型エラー対応では特に「型を通すために挙動を変えていないか」を疑う
  （narrowing が既存テストの想定挙動を壊す例があった）

### 4. ローカルで CI 同等検査（実際に実行する）
```bash
python -m mypy bot main.py exporter.py scheduler.py
python -m pytest tests/ -q --cov=bot --cov=main --cov-fail-under=90
```
**報告は必ず実際のツール戻り値に基づく。** mypy クリーン＋テスト全通過＋
カバレッジ達成の3点が揃って初めて「直った」と言える。揃わなければ 3 へ戻る。

### 5. 報告
原因・修正内容・ローカル検証結果（実数）をまとめて報告する。
コミット／プッシュ／デプロイへ進むかはユーザーに確認する
（push 時は `.githooks/pre-push` が同検査を再強制する）。
