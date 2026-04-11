# AI-DLC Prompts — 使用プロンプト履歴

> AI-DLC Appendix A に準拠。各セッションで使用したセットアッププロンプトと主要プロンプトを記録する。
> 新しいプロンプトは末尾に追記すること。

---

## Setup Prompt（初回セッション: 2026-04-11）

```
このプロジェクトは AI-DLC (AI-Driven Development Lifecycle) + spec-kit に従って開発を進める。

ドキュメント構成:
- aidlc-docs/constitution.md       ← プロジェクト原則（変更禁止）
- aidlc-docs/plans/<feature>.md    ← 機能ごとの実装計画（チェックボックス付き）
- aidlc-docs/requirements/         ← 機能要件・User Stories
- aidlc-docs/story-artifacts/      ← Unit 定義（Inception Phase の成果物）
- aidlc-docs/design-artifacts/     ← コンポーネント設計・ADR
- aidlc-docs/prompts.md            ← このファイル（プロンプト履歴）

作業ルール:
1. 新機能の実装前に aidlc-docs/plans/<feature>.md を作成し、チェックボックス付き計画を立てる
2. 人間（ジント）が計画を承認してから実装を開始する
3. 1ステップずつ実装し、完了したらチェックボックスを更新する
4. 実装完了後に python -m pytest tests/ で全通過を確認する
5. /deploy でコミット → プッシュ → NAS デプロイを実行する

理解したらその旨を確認してください。
```

---

## Inception Phase — 新機能追加時のテンプレート

### User Stories 作成プロンプト

```
あなたは経験豊富なプロダクトマネージャーです。
以下の高レベル要件に対して Well-defined な User Stories を作成してください。

作業前に aidlc-docs/plans/us_<feature>.md に計画（チェックボックス付き）を作成してください。
各ステップで確認が必要な場合はその旨を記載し、私の承認を得てから次に進んでください。
計画が完成したら私にレビューを求めてください。承認後に実行してください。

要件: << 機能の説明をここに記述 >>

成果物: aidlc-docs/story-artifacts/<unit_name>.md に保存してください。
```

### Unit 定義プロンプト

```
あなたは経験豊富なソフトウェアアーキテクトです。
以下の User Stories を、独立してビルドできる Unit にグループ化してください。

作業前に aidlc-docs/plans/units_<feature>.md に計画（チェックボックス付き）を作成してください。
計画を私にレビューしてもらい、承認後に実行してください。

参照: aidlc-docs/story-artifacts/<file>.md

条件:
- 各 Unit は高凝集・疎結合であること
- 1チームが独立してビルドできる単位であること

成果物: aidlc-docs/story-artifacts/units/ フォルダに Unit ごとのファイルを作成してください。
```

---

## Construction Phase — 実装時のテンプレート

### コンポーネント設計プロンプト

```
あなたは経験豊富なソフトウェアエンジニアです。
以下の User Stories を実装するためのコンポーネント設計を作成してください。

作業前に aidlc-docs/plans/design_<feature>.md に計画（チェックボックス付き）を作成してください。
計画を私にレビューしてもらい、承認後に実行してください。

参照: aidlc-docs/story-artifacts/<unit>.md
既存アーキテクチャ: aidlc-docs/design-artifacts/architecture.md

条件:
- コードは生成しないこと（設計のみ）
- 既存コンポーネントへの影響範囲を明示すること

成果物: aidlc-docs/design-artifacts/<feature>_design.md
```

### コード生成プロンプト

```
あなたは経験豊富なソフトウェアエンジニアです。
以下の設計に基づいてコードを実装してください。

作業前に aidlc-docs/plans/impl_<feature>.md に計画（チェックボックス付き）を作成してください。
計画を私にレビューしてもらい、承認後に1ステップずつ実装してください。
各ステップ完了後にチェックボックスを更新してください。

参照設計: aidlc-docs/design-artifacts/<feature>_design.md
原則: aidlc-docs/constitution.md

条件:
- 型注釈を付けること（mypy 0エラーを維持）
- 対応するテストを tests/ に追加すること
- 既存の命名規則・コーディングスタイルに従うこと
```
