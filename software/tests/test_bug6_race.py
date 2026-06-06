#!/usr/bin/env python3
"""Bug #6 edge case: rapid double start - does it kill the first experiment?"""
import requests
import time

BASE = "http://localhost:8001"

def test():
    print("=" * 60)
    print("BUG #6 EDGE CASE: Rapid double start")
    print("=" * 60)

    try:
        requests.post(f"{BASE}/api/experiment/stop", timeout=3)
    except:
        pass
    time.sleep(0.5)

    # Start first mock with count=1 (will finish quickly ~2s)
    print("\n[Step 1] 启动 Mock 1（count=1）...")
    r1 = requests.post(f"{BASE}/api/experiment/start-mock", params={"count": 1}, timeout=3)
    print(f"  start-mock #1: {r1.status_code} - {r1.text}")

    time.sleep(0.2)

    # Immediately try to start second mock (should be rejected by mutex check)
    print("\n[Step 2] 立即尝试启动 Mock 2...")
    r2 = requests.post(f"{BASE}/api/experiment/start-mock", params={"count": 1}, timeout=3)
    print(f"  start-mock #2: {r2.status_code} - {r2.text}")

    if r2.status_code == 400 and "正在运行" in r2.text:
        print("  ✅ PASS: Second mock correctly rejected")
    elif r2.status_code == 200:
        print("  ❌ FAIL: Two experiments running simultaneously!")

    # Wait for both to finish
    time.sleep(15)

    # Check sessions
    r = requests.get(f"{BASE}/api/sessions", timeout=3)
    sessions = r.json().get("sessions", [])
    print(f"\n[Step 3] Sessions after completion: {len(sessions)}")
    for s in sessions[:5]:
        print(f"    - {s.get('id')}: state={s.get('state')}")

if __name__ == "__main__":
    test()
