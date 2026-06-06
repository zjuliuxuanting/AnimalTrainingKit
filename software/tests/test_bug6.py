#!/usr/bin/env python3
"""Bug #6: 实验/流程无互斥锁验证"""
import requests
import json
import time

BASE = "http://localhost:8001"

def test():
    print("=" * 60)
    print("BUG #6: 实验/流程无互斥锁")
    print("=" * 60)

    # Step 1: Stop any existing experiment
    print("\n[Step 1] 停止已有实验...")
    try:
        r = requests.post(f"{BASE}/api/experiment/stop", timeout=3)
        print(f"  stop response: {r.status_code}")
    except Exception as e:
        print(f"  stop error (expected if nothing running): {e}")

    time.sleep(0.5)

    # Step 2: Start mock experiment
    print("\n[Step 2] 启动 Mock 实验（count=3）...")
    try:
        r = requests.post(f"{BASE}/api/experiment/start-mock", params={"count": 3}, timeout=3)
        print(f"  start-mock response: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"  start-mock error: {e}")

    time.sleep(1)

    # Step 3: Check state
    print("\n[Step 3] 检查实验状态...")
    try:
        r = requests.get(f"{BASE}/api/experiment/state", timeout=3)
        print(f"  state response: {r.json()}")
    except Exception as e:
        print(f"  state error: {e}")

    # Step 4: Try to run a flow while mock is running
    print("\n[Step 4] 尝试在 Mock 运行时启动 Flow...")
    flow_data = {
        "flow": {
            "name": "bug6_test",
            "nodes": {
                "start_1": {"id": "start_1", "node_type": "start", "label": "开始", "params": {}, "x": 0, "y": 0},
                "end_1": {"id": "end_1", "node_type": "end", "label": "结束", "params": {}, "x": 400, "y": 0}
            },
            "edges": [
                {
                    "source_node": "start_1", "source_port": "out",
                    "target_node": "end_1", "target_port": "in"
                }
            ]
        },
        "duration": 5,
        "exp_name": "bug6_flow_test"
    }
    try:
        r = requests.post(f"{BASE}/api/experiment/run-flow", json=flow_data, timeout=3)
        print(f"  run-flow response: {r.status_code} - {r.text}")
        if r.status_code == 400 and "正在运行" in r.text:
            print("  ✅ PASS: Flow correctly rejected with '实验正在运行中'")
        elif r.status_code == 200:
            print("  ❌ FAIL: Flow started while Mock was running! No mutual exclusion!")
        else:
            print(f"  ⚠️ Unexpected status code: {r.status_code}")
    except Exception as e:
        print(f"  run-flow error: {e}")

    # Step 5: Wait for mock to finish, then check sessions
    print("\n[Step 5] 等待 Mock 实验完成...")
    time.sleep(10)

    try:
        r = requests.get(f"{BASE}/api/sessions", timeout=3)
        sessions = r.json().get("sessions", [])
        print(f"  Sessions found: {len(sessions)}")
        for s in sessions:
            print(f"    - {s.get('id')}: state={s.get('state')}")
    except Exception as e:
        print(f"  sessions error: {e}")

    # Step 6: Check events count
    try:
        r = requests.get(f"{BASE}/api/sessions", timeout=3)
        sessions = r.json().get("sessions", [])
        if sessions:
            sid = sessions[0]["id"]
            r2 = requests.get(f"{BASE}/api/sessions/{sid}/events", timeout=3)
            events = r2.json().get("events", [])
            print(f"  Events in first session: {len(events)}")
    except Exception as e:
        print(f"  events error: {e}")

    # Step 7: Stop everything
    print("\n[Step 6] 停止实验...")
    try:
        r = requests.post(f"{BASE}/api/experiment/stop", timeout=3)
        print(f"  stop response: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"  stop error: {e}")

if __name__ == "__main__":
    test()
