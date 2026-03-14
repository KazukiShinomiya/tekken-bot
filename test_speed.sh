#!/bin/bash
echo "=== qwen2.5:7b 速度テスト ==="
START=$(date +%s)
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen2.5:7b","prompt":"鉄拳8で勝率90%の一言評価","stream":false,"options":{"num_predict":50}}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('response','')); print(f'eval_duration: {d.get(\"eval_duration\",0)/1e9:.1f}s')"
END=$(date +%s)
echo "合計: $((END-START))秒"
