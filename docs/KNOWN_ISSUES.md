# 既知の問題・調査ナレッジ（コミット対象外）

## 1. キャラ名誤表示バグ（2026-03-16 修正済み）

### 症状
- wank_bulk でenrichmentされたバトルの `my_chara` が実際と異なるキャラ名になる
- 例: Leeでプレイしたのに "Nina" と表示される

### 原因
`CHARA_NAMES` が **1-indexed**（Paul=1）で定義されていたが、wank bulk API は **0-indexed**（Paul=0）でキャラIDを返す。

- 例: Leeは wank bulk API では `chara_id=22`、CHARA_NAMES では `22: "Nina"` → 誤変換
- 例: Paulは wank bulk API では `chara_id=0`、Pythonの `if 0:` が falsy なため上書きされず HTML の値が使われていた（結果的に正しく表示されていたため気づきにくかった）

### 修正内容
`bot/fetcher.py` の `CHARA_NAMES` を 0-indexed に変更:
```python
# 変更前
1: "Paul", 22: "Nina", 23: "Lee", ...

# 変更後
0: "Paul", 21: "Nina", 22: "Lee", ...
```

あわせて `_merge_bulk` 内の `if battle["my_chara_id"]:` を `if battle["my_chara_id"] is not None:` に修正（Paul=0 が falsy になる問題を防止）。

### 調査方法
```bash
# wank HTMLパース結果 vs バルクenrichment後を比較
PYTHONPATH=/app python3 test_fetch.py

# バルクAPIの実レスポンスを確認
# p1_polaris_id / p2_polaris_id が POLARIS_ID と一致するか確認
# p1_chara_id=0 (Paul) p2_chara_id=22 (Lee) → 0-indexedが確認できた
```

---

## 2. 投稿時刻が常に UTC 23:00 になる（仕様）

### 症状
Discord メッセージのタイムスタンプが常に 23:xx (UTC) / 08:xx (JST) になる

### 原因
`scheduler.py` で `schedule.every().day.at("23:00")` と設定。コンテナは UTC で動作しているため UTC 23:00 = JST 翌 08:00 に実行される（意図通りの動作）。

### 補足
`main.py` の `yesterday = now - timedelta(days=1)` により、JST 08:00 に実行された場合の "yesterday" = 当日 JST 日付となる設計。ユーザーが UTC でDiscordを見ている場合は "23:xx" と表示されるが、JST では "08:xx"。
