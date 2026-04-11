# Story Artifacts

> Inception Phase の成果物を置くフォルダ。
> User Stories・Unit 定義・受け入れ基準を格納する。

## 構成

```
story-artifacts/
  README.md          ← このファイル
  units/             ← Unit ごとの User Stories（新機能追加時に作成）
```

## 既存 Unit 一覧（実装済み）

実装済み機能の User Stories は `aidlc-docs/requirements/core_features.md` を参照。

| Unit | 概要 |
|---|---|
| Unit 1: Fetching | wank / ewgf.gg からのデータ取得、DB 永続化 |
| Unit 2: Posting | Discord への日次・週次投稿 |
| Unit 3: Analytics | LLM コーチング・統計分析 |
| Unit 4: Commands | スラッシュコマンド |
| Unit 5: Infrastructure | Prometheus / Docker / ヘルスチェック |

## 新機能追加時の手順

1. `units/<unit_name>.md` に User Stories を作成（Inception Phase）
2. AI-DLC Mob Elaboration に従い、AI が提案 → 人間が承認・修正
3. 承認された User Stories を `aidlc-docs/plans/` の実装計画に紐付ける
