"""
初回セットアップスクリプト。
ewgf.gg のプレイヤーページを GET してインデックス化を促す。

実行方法:
    python setup.py

24時間後に main.py を実行してデータが取得できるか確認すること。
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

TEKKEN_ID = os.getenv("TEKKEN_ID", "ExodusOverseer")
EWGF_API = "https://api.ewgf.gg/external"
API_KEY = os.getenv("EWGF_API_KEY")


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def trigger_index() -> None:
    """プレイヤーページを GET してインデックス化を促す。"""
    url = f"https://ewgf.gg/player/{TEKKEN_ID}"
    print(f"GET {url}")
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
    print(f"ステータス: {resp.status_code}")
    if resp.status_code == 403:
        print("403: Cloudflare 等のボット対策に阻まれている可能性あり。ブラウザで手動アクセスが必要かもしれない。")


def check_api() -> None:
    """API がすでに応答するか確認する（404 なら未インデックス）。"""
    url = f"{EWGF_API}/battles/{TEKKEN_ID}"
    print(f"\nAPI 確認: GET {url}")
    resp = requests.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=15)
    print(f"ステータス: {resp.status_code}")

    if resp.status_code == 200:
        print("インデックス済み。main.py を実行できます。")
    elif resp.status_code == 404:
        print("未インデックス。24時間後に再確認してください。")
    else:
        print(f"予期しないレスポンス: {resp.text[:200]}")


if __name__ == "__main__":
    trigger_index()
    check_api()
