#!/usr/bin/env python3
"""P1 Bugs: #7 (signal_id), #8 (no trigger node), #5 (port count), #9 (space name)"""
import requests
import time

BASE = "http://localhost:8001"

def test_all_p1():
    print("=" * 60)
    print("P1 BUGS VALIDATION")
    print("=" * 60)

    try:
        requests.post(f"{BASE}/api/experiment/stop", timeout=3)
    except:
        pass
    time.sleep(0.5)

    # === Bug #7: 校验器不检查 signal_id 合法性 ===
    print("\n" + "=" * 60)
    print("BUG #7: 校验器不检查 signal_id 合法性")
    print("=" * 60)

    flow_invalid_signal = {
        "name": "bug7_test",
        "nodes": {
            "start_1": {"id": "start_1", "node_type": "start", "label": "开始", "params": {}, "x": 0, "y": 0},
            "trigger_1": {
                "id": "trigger_1",
                "node_type": "trigger",
                "label": "触发",
                "params": {"signal_id": "nonexistent_signal_xyz"},
                "x": 200, "y": 0
            },
            "delay_1": {
                "id": "delay_1",
                "node_type": "delay",
                "label": "延时",
                "params": {"duration_s": 1.0},
                "x": 400, "y": 0
            },
            "end_1": {"id": "end_1", "node_type": "end", "label": "结束", "params": {}, "x": 600, "y": 0}
        },
        "edges": [
            {"source_node": "start_1", "source_port": "out", "target_node": "trigger_1", "target_port": "in"},
            {"source_node": "trigger_1", "source_port": "out", "target_node": "delay_1", "target_port": "in"},
            {"source_node": "delay_1", "source_port": "out", "target_node": "end_1", "target_port": "in"}
        ]
    }

    r = requests.post(f"{BASE}/api/flows/validate", json=flow_invalid_signal, timeout=3)
    result = r.json()
    print(f"  Validate response: {result}")

    if not result["valid"]:
        errors = result.get("errors", [])
        signal_errors = [e for e in errors if "signal_id" in e.lower() or "信号" in e]
        if signal_errors:
            print(f"  ✅ PASS: Validation rejected invalid signal_id")
            for e in signal_errors:
                print(f"    Error: {e}")
        else:
            print(f"  ⚠️ Flow was rejected but not for signal_id reason: {errors}")
    else:
        print("  ❌ FAIL: Validation accepted flow with non-existent signal_id!")

    # Try to run it anyway
    print("\n  Trying to run the invalid flow...")
    r = requests.post(f"{BASE}/api/experiment/run-flow", json={
        "flow": flow_invalid_signal,
        "duration": 3,
        "exp_name": "bug7_run_test"
    }, timeout=3)
    print(f"  Run response: {r.status_code} - {r.text}")
    if r.status_code == 200:
        print("  ⚠️ Flow started but will never trigger (signal_id doesn't match)")

    # === Bug #8: 校验器不检查是否包含触发节点 ===
    print("\n" + "=" * 60)
    print("BUG #8: 校验器不检查是否包含触发节点")
    print("=" * 60)

    flow_no_trigger = {
        "name": "bug8_test",
        "nodes": {
            "start_1": {"id": "start_1", "node_type": "start", "label": "开始", "params": {}, "x": 0, "y": 0},
            "delay_1": {
                "id": "delay_1",
                "node_type": "delay",
                "label": "延时",
                "params": {"duration_s": 1.0},
                "x": 200, "y": 0
            },
            "end_1": {"id": "end_1", "node_type": "end", "label": "结束", "params": {}, "x": 400, "y": 0}
        },
        "edges": [
            {"source_node": "start_1", "source_port": "out", "target_node": "delay_1", "target_port": "in"},
            {"source_node": "delay_1", "source_port": "out", "target_node": "end_1", "target_port": "in"}
        ]
    }

    r = requests.post(f"{BASE}/api/flows/validate", json=flow_no_trigger, timeout=3)
    result = r.json()
    print(f"  Validate response: {result}")

    if not result["valid"]:
        errors = result.get("errors", [])
        trigger_errors = [e for e in errors if "触发" in e or "trigger" in e.lower()]
        if trigger_errors:
            print(f"  ✅ PASS: Validation rejected flow without trigger node")
            for e in trigger_errors:
                print(f"    Error: {e}")
        else:
            print(f"  ⚠️ Flow was rejected but not for missing trigger: {errors}")
    else:
        print("  ❌ FAIL: Validation accepted flow without any TRIGGER node!")

    # === Bug #5: 校验器未检查端口合法性（CONDITION only 1 output）===
    print("\n" + "=" * 60)
    print("BUG #5: 校验器未检查 CONDITION 端口数量")
    print("=" * 60)

    flow_bad_condition = {
        "name": "bug5_test",
        "nodes": {
            "start_1": {"id": "start_1", "node_type": "start", "label": "开始", "params": {}, "x": 0, "y": 0},
            "cond_1": {
                "id": "cond_1",
                "node_type": "condition",
                "label": "条件",
                "params": {"variable": "test", "operator": "eq", "value": 1},
                "x": 200, "y": 0
            },
            "end_1": {"id": "end_1", "node_type": "end", "label": "结束", "params": {}, "x": 400, "y": 0}
        },
        "edges": [
            # Only one edge from condition (should have true AND false)
            {"source_node": "cond_1", "source_port": "true", "target_node": "end_1", "target_port": "in"}
        ]
    }

    r = requests.post(f"{BASE}/api/flows/validate", json=flow_bad_condition, timeout=3)
    result = r.json()
    print(f"  Validate response: {result}")

    if not result["valid"]:
        errors = result.get("errors", [])
        condition_errors = [e for e in errors if "条件分支" in e or "CONDITION" in e or "出边" in e]
        if condition_errors:
            print(f"  ✅ PASS: Validation rejected CONDITION with incomplete branches")
            for e in condition_errors:
                print(f"    Error: {e}")
        else:
            print(f"  ⚠️ Flow was rejected but not for port count: {errors}")
    else:
        print("  ❌ FAIL: Validation accepted CONDITION with only 1 output branch!")

    # === Bug #9: 保存 API 接受纯空格名称 ===
    print("\n" + "=" * 60)
    print("BUG #9: 保存 API 接受纯空格名称")
    print("=" * 60)

    flow_space_name = {
        "name": "   ",
        "nodes": {
            "start_1": {"id": "start_1", "node_type": "start", "label": "开始", "params": {}, "x": 0, "y": 0},
            "end_1": {"id": "end_1", "node_type": "end", "label": "结束", "params": {}, "x": 200, "y": 0}
        },
        "edges": [
            {"source_node": "start_1", "source_port": "out", "target_node": "end_1", "target_port": "in"}
        ]
    }

    r = requests.post(f"{BASE}/api/flows/save", json=flow_space_name, timeout=3)
    print(f"  Save response: {r.status_code} - {r.text}")

    if r.status_code == 400 and "名称" in r.text:
        print("  ✅ PASS: Save API rejected space-only name")
    elif r.status_code == 200:
        print("  ❌ FAIL: Save API accepted flow with space-only name!")
    else:
        print(f"  ⚠️ Unexpected response: {r.status_code}")

if __name__ == "__main__":
    test_all_p1()
