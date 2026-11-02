#!/usr/bin/env python3
"""Fill a running TraceLab with realistic traffic so the dashboard has something to show.

    python scripts/seed_demo.py                       # http://localhost:8080
    TRACELAB_URL=https://tracelab.example.com TRACELAB_API_KEY=... python scripts/seed_demo.py

Targets httpbin.org, so the machine running TraceLab needs outbound internet access.
Uses only the standard library.
"""

import json
import os
import random
import urllib.error
import urllib.request

BASE = os.environ.get("TRACELAB_URL", "http://localhost:8080").rstrip("/")
KEY = os.environ.get("TRACELAB_API_KEY")
HB = os.environ.get("DEMO_TARGET", "https://httpbin.org").rstrip("/")

# (weight, payload) - a mix of healthy, flaky, slow and broken endpoints
SCENARIOS = [
    (10, {"url": f"{HB}/status/200"}),
    (6, {"url": f"{HB}/get?source=tracelab", "headers": {"Accept": "application/json"}}),
    (4, {"method": "POST", "url": f"{HB}/post", "headers": {"Content-Type": "application/json"},
         "body": json.dumps({"order_id": 1042, "amount": 19.99})}),
    (3, {"url": f"{HB}/status/500,200,200", "max_attempts": 4, "backoff_base_s": 0.5}),  # flaky
    (3, {"url": f"{HB}/status/503", "max_attempts": 3, "backoff_base_s": 0.5}),           # ends in the DLQ
    (2, {"url": f"{HB}/status/429", "max_attempts": 3, "backoff_base_s": 0.5}),
    (2, {"url": f"{HB}/status/404"}),                                                       # not retried
    (2, {"url": f"{HB}/delay/5", "timeout_s": 1.5, "max_attempts": 2, "backoff_base_s": 0.5}),  # timeout
    (1, {"url": "https://this-host-does-not-exist.invalid/", "max_attempts": 2, "backoff_base_s": 0.5}),
    (1, {"url": f"{HB}/basic-auth/user/pass", "headers": {"Authorization": "Bearer demo-token"}}),
]


def post(payload: dict, idem: str) -> int:
    headers = {"Content-Type": "application/json", "Idempotency-Key": idem}
    if KEY:
        headers["X-API-Key"] = KEY
    req = urllib.request.Request(f"{BASE}/api/requests", data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        print("  rejected:", exc.code, exc.read().decode()[:200])
        return exc.code


def main(n: int = 60) -> None:
    run = random.randrange(10**6)
    weights = [w for w, _ in SCENARIOS]
    for i in range(n):
        _, payload = random.choices(SCENARIOS, weights)[0]
        post(payload, f"seed-{run}-{i}")
    print(f"queued {n} requests on {BASE}. Open the dashboard and watch them resolve.")


if __name__ == "__main__":
    main()
