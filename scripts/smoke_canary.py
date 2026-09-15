#!/usr/bin/env python3
"""Smoke tests for canary deployment with report generation.

Usage:
    OLD_BASE=https://api.old.example.com/api \
    NEW_BASE=https://api.new.example.com/api \
    JOB_ID=REEMPLAZAR_AQUI \
    python scripts/smoke_canary.py
"""

import os, sys, time, json, urllib.request, urllib.error
from datetime import datetime

OLD_BASE = os.getenv("OLD_BASE", "REEMPLAZAR_AQUI")
NEW_BASE = os.getenv("NEW_BASE", "REEMPLAZAR_AQUI")
JOB_ID = os.getenv("JOB_ID", "REEMPLAZAR_AQUI")
TIMEOUT = int(os.getenv("TIMEOUT", "10"))
MAX_RETRIES = 3
RETRY_DELAY = 2

results = []
start_time = time.time()


def request(method, url, data=None, retries=MAX_RETRIES):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, method=method, data=data)
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode()
                return resp.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            return e.code, {}
        except Exception:
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            return 0, {}
    return 0, {}


def check(label, url, method="GET", expected_status=200, expected_keys=None):
    t0 = time.time()
    status, body = request(method, url)
    elapsed = round(time.time() - t0, 3)
    ok = status == expected_status
    if expected_keys and ok:
        ok = all(k in body for k in expected_keys)
    result = "PASS" if ok else "FAIL"
    results.append({"label": label, "status": status, "result": result, "time": elapsed})
    icon = "+" if ok else "X"
    print(f"  [{icon}] {label} — HTTP {status} ({elapsed}s)")
    return ok


def write_report():
    os.makedirs("reports", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"reports/smoke_canary_report_{ts}.md"
    passed = sum(1 for r in results if r["result"] == "PASS")
    failed = sum(1 for r in results if r["result"] == "FAIL")
    elapsed = round(time.time() - start_time, 2)
    with open(path, "w") as f:
        f.write(f"# Smoke Canary Report — {ts}\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| OLD_BASE | `{OLD_BASE}` |\n| NEW_BASE | `{NEW_BASE}` |\n")
        f.write(f"| JOB_ID | `{JOB_ID}` |\n| Duration | {elapsed}s |\n")
        f.write(f"| Passed | {passed} |\n| Failed | {failed} |\n\n")
        f.write("## Results\n\n")
        f.write("| Test | Status | HTTP | Time |\n|------|--------|------|------|\n")
        for r in results:
            f.write(f"| {r['label']} | {r['result']} | {r['status']} | {r['time']}s |\n")
    print(f"\nReport: {path}")


def main():
    print("=" * 60)
    print("  Smoke Tests — Canary Deployment")
    print("=" * 60)
    all_ok = True
    print("\n[1] Health checks")
    all_ok &= check("OLD /health", f"{OLD_BASE}/health")
    all_ok &= check("NEW /health", f"{NEW_BASE}/health")
    print("\n[2] GET ranking")
    all_ok &= check("OLD GET ranking", f"{OLD_BASE}/jobs/{JOB_ID}/ranking",
                     expected_keys=["candidates", "ranking_generated_at", "ranking_version"])
    all_ok &= check("NEW GET ranking", f"{NEW_BASE}/jobs/{JOB_ID}/ranking",
                     expected_keys=["candidates", "ranking_generated_at", "ranking_version"])
    print("\n[3] POST recalculate")
    all_ok &= check("NEW POST incremental", f"{NEW_BASE}/jobs/{JOB_ID}/ranking/recalculate?mode=incremental",
                     method="POST", expected_keys=["ranking_version", "mode"])
    all_ok &= check("NEW POST full", f"{NEW_BASE}/jobs/{JOB_ID}/ranking/recalculate?mode=full",
                     method="POST", expected_keys=["ranking_version", "mode"])
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r["result"] == "PASS")
    failed = sum(1 for r in results if r["result"] == "FAIL")
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)
    write_report()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
