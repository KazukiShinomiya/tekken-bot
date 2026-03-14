#!/bin/bash
set -e
echo "=== Ollama インストール ==="
curl -fsSL https://ollama.com/install.sh | sh
echo "=== バージョン確認 ==="
ollama --version
echo "=== サービス起動確認 ==="
sleep 2
curl -s http://localhost:11434/api/tags | head -c 100 || echo "API未応答"
echo ""
echo "=== done ==="
