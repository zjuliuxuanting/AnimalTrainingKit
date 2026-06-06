#!/usr/bin/env python3
"""Bug #6 reverse: Flow 运行时尝试启动 Mock"""
import requests
import time

BASE = "http://localhost:8001"

def test():
    print("=" * 60)
    print("BUG #6 REVERSE: Flow -> Mock mutual exclusion")
    print("=" * 60)

    # Stop any existing
    try:
        requests.post(f"{BASE}/api/experiment/stop", timeout=3)
    except:
        pass
    time.sleep(0.5)

    # Start a flow with short duration
    print("\n[Step 1] 启动 Flow（duration=8秒）...")
    flow_data = {
        "flow": {
            "name": "bug6_reverse",
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
        "duration": 8,
        "exp_name": "bug6_reverse_test"
    }
    r = requests.post(f"{BASE}/api/experiment/run-flow", json=flow_data, timeout=3)
    print(f"  run-flow: {r.status_code} - {r.text}")

    time.sleep(1)

    # Try to start mock while flow is running
    print("\n[Step 2] 尝试在 Flow 运行时启动 Mock...")
    r = requests.post(f"{BASE}/api/experiment/start-mock", params={"count": 3}, timeout=3)
    print(f"  start-mock: {r.status_code} - {r.text}")
    if r.status_code == 400 and "正在运行" in r.text:
        print("  ✅ PASS: Mock correctly rejected")
    elif r.status_code == 200:
        print("  ❌ FAIL: Mock started while Flow was running!")
    else:
        print(f"  ⚠️ Unexpected: {r.status_code}")

    # Wait for flow to finish
    time.sleep(10)

    # Stop everything
    try:
        requests.post(f"{BASE}/api/experiment/stop", timeout=3)
    except:
        pass

if __name__ == "__main__":
    test()
