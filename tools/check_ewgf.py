import sys, requests, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("EWGF_API_KEY")
h = {"Authorization": f"Bearer {key}"}
r = requests.get("https://api.ewgf.gg/external/battles/66aidNN9JQ2T", headers=h, timeout=10)
d = r.json()
print(f"status: {r.status_code}")
print(f"metadata: {d.get('_metadata')}")
battles = d.get("data", d.get("battles", []))
print(f"battles件数: {len(battles)}")
if battles:
    print("\n1件目のキー:", list(battles[0].keys()))
    print("\n1件目:")
    print(json.dumps(battles[0], indent=2, ensure_ascii=False))
