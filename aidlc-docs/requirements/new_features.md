# New Features — Requirements

> 2026-04-11 以降に追加予定の機能要件。
> 実装済みになったら `core_features.md` に移動する。

---

## Unit 4: スラッシュコマンド（Commands）追加

### US-403: バトルログ検索コマンド
**As a** プレイヤー,  
**I want** キャラ名・日付でバトルログを絞り込んで確認できること,  
**So that** 特定のキャラとの対戦傾向を詳しく分析できる。

**Acceptance Criteria:**
- `/tekken filter chara <名前>` — 指定キャラとの全対戦を最新20件表示
- `/tekken filter date <YYYY-MM-DD>` — 指定日の全バトル一覧を表示
- `/tekken filter chara <名前> date <YYYY-MM-DD>` — 組み合わせフィルタ
- 結果は Embed 形式（勝率・試合一覧）で返す

**Status:** ✅ Done（2026-04-11, commit ef54786）

---

## Unit 5: 投稿体験改善（Engagement）

### US-501: 投稿の可読性向上
**As a** Discord メンバー（鉄拳未プレイを含む）,  
**I want** 投稿を見て「今日どんな展開だったか」が直感的に伝わること,  
**So that** 鉄拳に興味を持ったり、活動を応援したりしやすくなる。

**設計方針（2026-04-14 確定）:**
- 人の言葉（LLM コメント）を最前面に出す → description 冒頭に配置
- データ量より「ドラマ」を重視する → 乾燥した分析セクションは削除
- 削除対象: 時間帯別勝率（`_hourly_section`）、リピート対戦（`_rematch_section`）、週次停滞警告

**Status:** ✅ Done（2026-04-14）
