#!/usr/bin/env python3
"""Bug #10: 运行中刷新后监控态丢失 - 验证后端是否有恢复机制"""
import requests
import time

BASE = "http://localhost:8001"

def test():
    print("=" * 60)
    print("BUG #10: 运行中刷新后监控态丢失")
    print("=" * 60)

    try:
        requests.post(f"{BASE}/api/experiment/stop", timeout=3)
    except:
        pass
    time.sleep(0.5)

    # Step 1: Start a flow experiment (longer duration for testing)
    print("\n[Step 1] 启动 Flow 实验（duration=20秒）...")
    flow_data = {
        "flow": {
            "name": "bug10_test",
            "nodes": {
                "start_1": {"id": "start_1", "node_type": "start", "label": "开始", "params": {}, "x": 0, "y": 0},
                "end_1": {"id": "end_1", "node_type": "end", "label": "结束", "params": {}, "x": 200, "y": 0}
            },
            "edges": [
                {"source_node": "start_1", "source_port": "out", "target_node": "end_1", "target_port": "in"}
            ]
        },
        "duration": 20,
        "exp_name": "bug10_refresh_test"
    }

    r = requests.post(f"{BASE}/api/experiment/run-flow", json=flow_data, timeout=3)
    print(f"  run-flow: {r.status_code} - {r.text}")

    if r.status_code != 200:
        print("  ❌ FAIL: Could not start flow")
        return

    session_id = r.json().get("session_id", "")
    print(f"  Session ID: {session_id}")

    # Step 2: Check state immediately (simulates what browser would see before refresh)
    time.sleep(1)
    r = requests.get(f"{BASE}/api/experiment/state", timeout=3)
    state_before = r.json()
    print(f"\n[Step 2] State BEFORE simulated refresh: {state_before}")

    # Step 3: Check if there's any API to "restore" monitor state after page reload
    print("\n[Step 3] 检查是否有恢复监控态的 API...")

    # Try common restore endpoints
    restore_endpoints = [
        f"/api/experiment/restore",
        f"/api/experiment/resume",
        f"/api/experiment/recover",
        f"/api/monitor/state",
        f"/api/monitor/restore",
    ]

    for endpoint in restore_endpoints:
        try:
            r = requests.get(f"{BASE}{endpoint}", timeout=2)
            print(f"  GET {endpoint}: {r.status_code} - {r.text[:100]}")
        except Exception as e:
            pass

        try:
            r = requests.post(f"{BASE}{endpoint}", timeout=2)
            print(f"  POST {endpoint}: {r.status_code} - {r.text[:100]}")
        except Exception as e:
            pass

    # Step 4: Check if experiment state API returns enough info to resume monitoring
    r = requests.get(f"{BASE}/api/experiment/state", timeout=3)
    state_after = r.json()
    print(f"\n[Step 4] State (simulating post-refresh): {state_after}")

    # The key question: does the API return enough info for the frontend to resume monitoring?
    if state_after.get("session_id") and state_after.get("engine") == "running":
        print("\n  ⚠️ Partial: API returns session_id and running state")
        print("  But there's no 'restoreMonitor' endpoint - frontend must re-call startMonitorPoll()")
        print("  After page refresh, the JS context is gone, so monitoring is lost.")
    else:
        print("\n  ❌ FAIL: API doesn't provide enough info to resume monitoring")

    # Step 5: Check if sessions API can be used to find running session
    r = requests.get(f"{BASE}/api/sessions", timeout=3)
    sessions = r.json().get("sessions", [])
    running_sessions = [s for s in sessions if s.get('state') == 'running']
    print(f"\n[Step 5] Running sessions: {len(running_sessions)}")

    # Step 6: Wait for experiment to finish naturally (simulates user waiting after refresh)
    print("\n[Step 6] 等待实验完成...")
    time.sleep(20)

    r = requests.get(f"{BASE}/api/experiment/state", timeout=3)
    final_state = r.json()
    print(f"  Final state: {final_state}")

    # Stop everything
    try:
        requests.post(f"{BASE}/api/experiment/stop", timeout=3)
    except:
        pass

if __name__ == "__main__":
    test()
