#!/bin/bash
cd ~/tekken_bot
docker compose up -d --build
sleep 3
docker compose logs
