# Plans

> 機能ごとの実装計画を置くフォルダ。

## 命名規則

```
impl_<feature>.md    ← 実装計画
design_<feature>.md  ← 設計計画
us_<feature>.md      ← User Stories 作成計画
```

## 計画ファイルの形式

```markdown
# 計画: <機能名>

**Intent**: <何を・なぜ実装するか>
**Unit**: <どの Unit に属するか>
**関連 User Stories**: <aidlc-docs/story-artifacts/ のファイル>

## ステップ

- [ ] Step 1: ...
- [ ] Step 2: ...
- [ ] Step 3: ...

## 完了条件

- [ ] `python -m pytest tests/` 全通過
- [ ] mypy 0 エラー
- [ ] NAS デプロイ完了
```

## 運用ルール

1. 実装開始前にこのフォルダに計画ファイルを作成する
2. 人間（ジント）の承認後に実装を開始する
3. 各ステップ完了後にチェックボックスを更新する
4. 完了した計画は `done/` サブフォルダに移動する
