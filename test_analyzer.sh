#!/bin/bash
cd ~/tekken_bot
docker compose exec tekken-bot python -u -c "
import db, analyzer
db.init_db()
# 直近の試合データでテスト
battles = db.get_battles_on_date('2026-03-12')
for b in battles:
    b['won'] = bool(b['won'])
print(f'対象: {len(battles)}件')
if battles:
    comment = analyzer.analyze(battles, '2026/03/12')
    print(f'--- LLMコメント ---')
    print(comment)
"
