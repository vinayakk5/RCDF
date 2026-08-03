import json
import requests

base = "http://127.0.0.1:8000/api"
res = requests.get(base + "/deals", timeout=20)
print("GET /deals", res.status_code)
try:
    deals = res.json()
except Exception:
    deals = None
print("deals_count", len(deals) if isinstance(deals, list) else deals)

if isinstance(deals, list) and deals:
    d = deals[0]
    body = {
        "broker_id": d.get("broker_id"),
        "deal_mt": d.get("deal_mt"),
        "rate_per_mt": d.get("rate_per_mt"),
        "status": d.get("status"),
    }
    r = requests.patch(base + f"/deals/{d.get('id')}", json=body, timeout=20)
    print("PATCH", r.status_code)
    print(r.text[:800])
