import json
import requests
from datetime import date, timedelta

start = date(2026, 2, 4)
end = date(2026, 2, 19)
out = []
cur = start
while cur <= end:
    try:
        r = requests.get(f'http://127.0.0.1:8000/data/fitbit/me?start={cur.isoformat()}&metrics=sleep', timeout=15)
        j = r.json()
    except Exception:
        j = {}
    out.append({"date": cur.isoformat(), "sleep": j.get("sleep") if isinstance(j, dict) else None})
    cur = cur + timedelta(days=1)

with open("fitbit_sleep_2026-02-04_2026-02-19.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=2)

print("WROTE fitbit_sleep_2026-02-04_2026-02-19.json")
