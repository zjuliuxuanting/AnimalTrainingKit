#!/usr/bin/env python3
"""测试 4 条标准链路的完整脚本：创建 → 保存 → 校验 → 运行 → 采集 WS 消息"""

import asyncio
import json
import sys
import time
import httpx
import websockets

BASE = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

# ============================================================
# Flow 1: FR1 操作性条件反射
# ============================================================
FLOW1 = {
    "name": "FR1操作性条件反射",
    "nodes": {
        "s1": {"id": "s1", "node_type": "start", "label": "START", "params": {}, "x": 100, "y": 100},
        "t1": {"id": "t1", "node_type": "trigger", "label": "TRIGGER_压杆", "params": {"signal_id": "mock:trigger", "debounce_ms": 0}, "x": 250, "y": 100},
        "d1": {"id": "d1", "node_type": "delay", "label": "DELAY_1s", "params": {"duration_s": 1.0}, "x": 400, "y": 100},
        "e1": {"id": "e1", "node_type": "execute", "label": "EXECUTE_给食", "params": {"actuator_id": "feeder", "action": "high"}, "x": 550, "y": 100},
        "r1": {"id": "r1", "node_type": "record", "label": "RECORD_压杆奖励", "params": {"event_name": "lever_press_reward", "counter_name": "reward_count", "counter_op": "+1"}, "x": 700, "y": 100},
        "l1": {"id": "l1", "node_type": "loop", "label": "LOOP_10次", "params": {"max_iterations": 10, "timeout_s": 60}, "x": 850, "y": 100},
        "end1": {"id": "end1", "node_type": "end", "label": "END", "params": {}, "x": 1000, "y": 100},
    },
    "edges": [
        {"id": "e_s1_t1", "source_node": "s1", "source_port": "out", "target_node": "t1", "target_port": "in"},
        {"id": "e_t1_d1", "source_node": "t1", "source_port": "out", "target_node": "d1", "target_port": "in"},
        {"id": "e_d1_e1", "source_node": "d1", "source_port": "out", "target_node": "e1", "target_port": "in"},
        {"id": "e_e1_r1", "source_node": "e1", "source_port": "out", "target_node": "r1", "target_port": "in"},
        {"id": "e_r1_l1", "source_node": "r1", "source_port": "out", "target_node": "l1", "target_port": "in"},
        {"id": "e_l1body_t1", "source_node": "l1", "source_port": "body", "target_node": "t1", "target_port": "in"},
        {"id": "e_l1exit_end1", "source_node": "l1", "source_port": "exit", "target_node": "end1", "target_port": "in"},
    ],
}

# ============================================================
# Flow 2: 社会性自我给药选择模型
# ============================================================
FLOW2 = {
    "name": "社交自我给药选择",
    "nodes": {
        "s1": {"id": "s1", "node_type": "start", "label": "START", "params": {}, "x": 50, "y": 150},
        "d_iti": {"id": "d_iti", "node_type": "delay", "label": "DELAY_ITI_5s", "params": {"duration_s": 5.0}, "x": 180, "y": 150},
        "e_trial": {"id": "e_trial", "node_type": "execute", "label": "EXECUTE_试次开始", "params": {"actuator_id": "light", "action": "high"}, "x": 330, "y": 150},
        "f1": {"id": "f1", "node_type": "fork", "label": "FORK_选择", "params": {}, "x": 480, "y": 150},
        # continue branch: 社交
        "t_social": {"id": "t_social", "node_type": "trigger", "label": "TRIGGER_社交鼻触", "params": {"signal_id": "mock:trigger"}, "x": 630, "y": 50},
        "d_social": {"id": "d_social", "node_type": "delay", "label": "DELAY_0.5s社交", "params": {"duration_s": 0.5}, "x": 780, "y": 50},
        "e_door": {"id": "e_door", "node_type": "execute", "label": "EXECUTE_开门见同伴", "params": {"actuator_id": "door", "action": "high"}, "x": 930, "y": 50},
        # stop branch: 食物
        "t_food": {"id": "t_food", "node_type": "trigger", "label": "TRIGGER_食物鼻触", "params": {"signal_id": "mock:timer"}, "x": 630, "y": 250},
        "d_food": {"id": "d_food", "node_type": "delay", "label": "DELAY_0.5s食物", "params": {"duration_s": 0.5}, "x": 780, "y": 250},
        "e_feeder": {"id": "e_feeder", "node_type": "execute", "label": "EXECUTE_给食", "params": {"actuator_id": "feeder", "action": "high"}, "x": 930, "y": 250},
        # convergence
        "r_choice": {"id": "r_choice", "node_type": "record", "label": "RECORD_选择事件", "params": {"event_name": "choice_made"}, "x": 1080, "y": 150},
        "l1": {"id": "l1", "node_type": "loop", "label": "LOOP_5次", "params": {"max_iterations": 5, "timeout_s": 60}, "x": 1230, "y": 150},
        "end1": {"id": "end1", "node_type": "end", "label": "END", "params": {}, "x": 1380, "y": 150},
    },
    "edges": [
        {"id": "e_s1_diti", "source_node": "s1", "source_port": "out", "target_node": "d_iti", "target_port": "in"},
        {"id": "e_diti_etrial", "source_node": "d_iti", "source_port": "out", "target_node": "e_trial", "target_port": "in"},
        {"id": "e_etrial_f1", "source_node": "e_trial", "source_port": "out", "target_node": "f1", "target_port": "in"},
        {"id": "e_f1c_tsocial", "source_node": "f1", "source_port": "continue", "target_node": "t_social", "target_port": "in"},
        {"id": "e_f1s_tfood", "source_node": "f1", "source_port": "stop", "target_node": "t_food", "target_port": "in"},
        {"id": "e_tsocial_dsocial", "source_node": "t_social", "source_port": "out", "target_node": "d_social", "target_port": "in"},
        {"id": "e_dsocial_edoor", "source_node": "d_social", "source_port": "out", "target_node": "e_door", "target_port": "in"},
        {"id": "e_edoor_rchoice", "source_node": "e_door", "source_port": "out", "target_node": "r_choice", "target_port": "in"},
        {"id": "e_tfood_dfood", "source_node": "t_food", "source_port": "out", "target_node": "d_food", "target_port": "in"},
        {"id": "e_dfood_efeeder", "source_node": "d_food", "source_port": "out", "target_node": "e_feeder", "target_port": "in"},
        {"id": "e_efeeder_rchoice", "source_node": "e_feeder", "source_port": "out", "target_node": "r_choice", "target_port": "in"},
        {"id": "e_rchoice_l1", "source_node": "r_choice", "source_port": "out", "target_node": "l1", "target_port": "in"},
        {"id": "e_l1body_diti", "source_node": "l1", "source_port": "body", "target_node": "d_iti", "target_port": "in"},
        {"id": "e_l1exit_end1", "source_node": "l1", "source_port": "exit", "target_node": "end1", "target_port": "in"},
    ],
}

# ============================================================
# Flow 3: 5-CSRTT (5选择连续反应时间任务)
# ============================================================
FLOW3 = {
    "name": "5-CSRTT注意力任务",
    "nodes": {
        "s1": {"id": "s1", "node_type": "start", "label": "START", "params": {}, "x": 50, "y": 200},
        "d_iti": {"id": "d_iti", "node_type": "delay", "label": "DELAY_ITI_5s", "params": {"duration_s": 5.0}, "x": 200, "y": 200},
        "e_light": {"id": "e_light", "node_type": "execute", "label": "EXECUTE_随机亮灯", "params": {"actuator_id": "light_hole", "action": "high"}, "x": 350, "y": 200},
        "f1": {"id": "f1", "node_type": "fork", "label": "FORK", "params": {}, "x": 500, "y": 200},
        # continue branch
        "t_nose": {"id": "t_nose", "node_type": "trigger", "label": "TRIGGER_鼻触", "params": {"signal_id": "mock:trigger"}, "x": 650, "y": 100},
        "c1": {"id": "c1", "node_type": "condition", "label": "CONDITION_正确孔?", "params": {"source": "counter", "counter_name": "trial_count", "operator": "lt", "value": 999}, "x": 800, "y": 100},
        # true branch (正确)
        "d_correct": {"id": "d_correct", "node_type": "delay", "label": "DELAY_0.1s", "params": {"duration_s": 0.1}, "x": 950, "y": 20},
        "e_reward": {"id": "e_reward", "node_type": "execute", "label": "EXECUTE_给食", "params": {"actuator_id": "feeder", "action": "high"}, "x": 1100, "y": 20},
        "r_correct": {"id": "r_correct", "node_type": "record", "label": "RECORD_正确", "params": {"event_name": "correct_choice", "counter_name": "correct_count", "counter_op": "+1"}, "x": 1250, "y": 20},
        # false branch (错误)
        "e_punish_false": {"id": "e_punish_false", "node_type": "execute", "label": "EXECUTE_惩罚", "params": {"actuator_id": "buzzer", "action": "high"}, "x": 950, "y": 120},
        "r_error": {"id": "r_error", "node_type": "record", "label": "RECORD_错误", "params": {"event_name": "incorrect_choice", "counter_name": "error_count", "counter_op": "+1"}, "x": 1100, "y": 120},
        # stop branch (遗漏)
        "d_timeout": {"id": "d_timeout", "node_type": "delay", "label": "DELAY_超时5s", "params": {"duration_s": 5.0}, "x": 650, "y": 300},
        "e_punish_stop": {"id": "e_punish_stop", "node_type": "execute", "label": "EXECUTE_惩罚", "params": {"actuator_id": "buzzer", "action": "high"}, "x": 800, "y": 300},
        "r_omission": {"id": "r_omission", "node_type": "record", "label": "RECORD_遗漏", "params": {"event_name": "omission", "counter_name": "omission_count", "counter_op": "+1"}, "x": 950, "y": 300},
        # convergence — 3 paths converge to one delay
        "d_trial_end": {"id": "d_trial_end", "node_type": "delay", "label": "DELAY_试次结束", "params": {"duration_s": 1.0}, "x": 1400, "y": 200},
        "l1": {"id": "l1", "node_type": "loop", "label": "LOOP_5次", "params": {"max_iterations": 5, "timeout_s": 60}, "x": 1550, "y": 200},
        "end1": {"id": "end1", "node_type": "end", "label": "END", "params": {}, "x": 1700, "y": 200},
    },
    "edges": [
        {"id": "e_s1_diti", "source_node": "s1", "source_port": "out", "target_node": "d_iti", "target_port": "in"},
        {"id": "e_diti_elight", "source_node": "d_iti", "source_port": "out", "target_node": "e_light", "target_port": "in"},
        {"id": "e_elight_f1", "source_node": "e_light", "source_port": "out", "target_node": "f1", "target_port": "in"},
        # FORK → continue: nose poke → condition
        {"id": "e_f1c_tnose", "source_node": "f1", "source_port": "continue", "target_node": "t_nose", "target_port": "in"},
        # FORK → stop: timeout → punish → record omission
        {"id": "e_f1s_dtimeout", "source_node": "f1", "source_port": "stop", "target_node": "d_timeout", "target_port": "in"},
        {"id": "e_dtimeout_epunish", "source_node": "d_timeout", "source_port": "out", "target_node": "e_punish_stop", "target_port": "in"},
        {"id": "e_epunish_romission", "source_node": "e_punish_stop", "source_port": "out", "target_node": "r_omission", "target_port": "in"},
        # continue path: trigger → condition
        {"id": "e_tnose_c1", "source_node": "t_nose", "source_port": "out", "target_node": "c1", "target_port": "in"},
        # condition true: correct
        {"id": "e_c1t_dcorrect", "source_node": "c1", "source_port": "true", "target_node": "d_correct", "target_port": "in"},
        {"id": "e_dcorrect_ereward", "source_node": "d_correct", "source_port": "out", "target_node": "e_reward", "target_port": "in"},
        {"id": "e_ereward_rcorrect", "source_node": "e_reward", "source_port": "out", "target_node": "r_correct", "target_port": "in"},
        # condition false: error
        {"id": "e_c1f_epunish", "source_node": "c1", "source_port": "false", "target_node": "e_punish_false", "target_port": "in"},
        {"id": "e_epunish_reror", "source_node": "e_punish_false", "source_port": "out", "target_node": "r_error", "target_port": "in"},
        # 3 converging paths → DELAY(试次结束) → LOOP
        {"id": "e_rcorrect_dtrialend", "source_node": "r_correct", "source_port": "out", "target_node": "d_trial_end", "target_port": "in"},
        {"id": "e_reror_dtrialend", "source_node": "r_error", "source_port": "out", "target_node": "d_trial_end", "target_port": "in"},
        {"id": "e_romission_dtrialend", "source_node": "r_omission", "source_port": "out", "target_node": "d_trial_end", "target_port": "in"},
        # DELAY(试次结束) → LOOP
        {"id": "e_dtrialend_l1", "source_node": "d_trial_end", "source_port": "out", "target_node": "l1", "target_port": "in"},
        # LOOP body → DELAY(ITI), exit → END
        {"id": "e_l1body_diti", "source_node": "l1", "source_port": "body", "target_node": "d_iti", "target_port": "in"},
        {"id": "e_l1exit_end1", "source_node": "l1", "source_port": "exit", "target_node": "end1", "target_port": "in"},
    ],
}

# ============================================================
# Flow 4: Sign-Tracking / Goal-Tracking
# ============================================================
FLOW4 = {
    "name": "SignTracking目标追踪",
    "nodes": {
        "s1": {"id": "s1", "node_type": "start", "label": "START", "params": {}, "x": 50, "y": 100},
        # ITI variable 5s
        "d_iti": {"id": "d_iti", "node_type": "delay", "label": "DELAY_ITI_5s", "params": {"duration_s": 5.0}, "x": 200, "y": 100},
        # lever extension + light
        "e_lever": {"id": "e_lever", "node_type": "execute", "label": "EXECUTE_插入杠杆亮灯", "params": {"actuator_id": "lever_actuator", "action": "high"}, "x": 350, "y": 100},
        # 8s CS-US interval
        "d_cs": {"id": "d_cs", "node_type": "delay", "label": "DELAY_CS_8s", "params": {"duration_s": 8.0}, "x": 500, "y": 100},
        # food delivery
        "e_food": {"id": "e_food", "node_type": "execute", "label": "EXECUTE_给食", "params": {"actuator_id": "feeder", "action": "high"}, "x": 650, "y": 100},
        # record trial end
        "r_trial": {"id": "r_trial", "node_type": "record", "label": "RECORD_试次结束", "params": {"event_name": "trial_end", "counter_name": "trial_count", "counter_op": "+1"}, "x": 800, "y": 100},
        # loop
        "l1": {"id": "l1", "node_type": "loop", "label": "LOOP_5次", "params": {"max_iterations": 5, "timeout_s": 60}, "x": 950, "y": 100},
        "end1": {"id": "end1", "node_type": "end", "label": "END", "params": {}, "x": 1100, "y": 100},
        # SNIFFER nodes (standalone)
        "sniff_lever": {"id": "sniff_lever", "node_type": "sniffer", "label": "SNIFFER_杠杆接近", "params": {"signal_id": "mock:timer", "event_name": "lever_approach"}, "x": 350, "y": 250},
        "sniff_feeder": {"id": "sniff_feeder", "node_type": "sniffer", "label": "SNIFFER_食槽接近", "params": {"signal_id": "mock:random", "event_name": "feeder_approach"}, "x": 650, "y": 250},
    },
    "edges": [
        {"id": "e_s1_diti", "source_node": "s1", "source_port": "out", "target_node": "d_iti", "target_port": "in"},
        {"id": "e_diti_elever", "source_node": "d_iti", "source_port": "out", "target_node": "e_lever", "target_port": "in"},
        {"id": "e_elever_dcs", "source_node": "e_lever", "source_port": "out", "target_node": "d_cs", "target_port": "in"},
        {"id": "e_dcs_efood", "source_node": "d_cs", "source_port": "out", "target_node": "e_food", "target_port": "in"},
        {"id": "e_efood_rtrial", "source_node": "e_food", "source_port": "out", "target_node": "r_trial", "target_port": "in"},
        {"id": "e_rtrial_l1", "source_node": "r_trial", "source_port": "out", "target_node": "l1", "target_port": "in"},
        {"id": "e_l1body_diti", "source_node": "l1", "source_port": "body", "target_node": "d_iti", "target_port": "in"},
        {"id": "e_l1exit_end1", "source_node": "l1", "source_port": "exit", "target_node": "end1", "target_port": "in"},
        # SNIFFER nodes have no edges
    ],
}


async def collect_ws_messages(duration_s: int = 35):
    """连接 WebSocket，收集所有消息"""
    messages = []
    try:
        async with websockets.connect(WS_URL) as ws:
            start = time.time()
            while time.time() - start < duration_s:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    messages.append(data)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
    except Exception as e:
        print(f"  WS 连接异常: {e}")
    return messages


async def run_test():
    async with httpx.AsyncClient(timeout=30) as client:
        # =========================================
        # Step 1: Create 4 experiments
        # =========================================
        exp_names = [
            ("B1", "B1_FR1操作条件反射", "fr1_subject", "仓鼠"),
            ("B2", "B2_社交自我给药", "social_subject", "小鼠"),
            ("B3", "B3_5CSRTT注意任务", "csrtt_subject", "大鼠"),
            ("B4", "B4_SignTracking", "sign_subject", "仓鼠"),
        ]
        exp_ids = {}

        print("=" * 60)
        print("Step 1: 创建 4 个实验")
        for tag, name, subj, species in exp_names:
            resp = await client.post(f"{BASE}/api/experiments", json={
                "name": name,
                "subject_id": subj,
                "species": species,
                "max_duration_min": 30,
                "max_trigger_count": 50,
            })
            data = resp.json()
            if resp.status_code == 200:
                eid = data["id"]
                exp_ids[tag] = eid
                print(f"  {tag} → {eid}: {name}")
            else:
                print(f"  {tag} 创建失败: {data}")
                # Try to get existing experiments
                list_resp = await client.get(f"{BASE}/api/experiments")
                exps = list_resp.json().get("experiments", [])
                for exp in exps:
                    if name in exp.get("name", ""):
                        exp_ids[tag] = exp["id"]
                        print(f"  {tag} → 使用已有: {exp['id']}")

        if len(exp_ids) < 4:
            print(f"  ERROR: 只有 {len(exp_ids)} 个实验创建成功")
            # List all existing experiments
            list_resp = await client.get(f"{BASE}/api/experiments")
            print(f"  现有实验: {json.dumps(list_resp.json(), indent=2, ensure_ascii=False)[:500]}")
            sys.exit(1)

        # =========================================
        # Step 2: 保存流程 + 校验
        # =========================================
        flows = [
            ("B1", FLOW1),
            ("B2", FLOW2),
            ("B3", FLOW3),
            ("B4", FLOW4),
        ]
        val_results = {}

        print("\n" + "=" * 60)
        print("Step 2: 保存流程 + 校验")

        for tag, flow in flows:
            exp_id = exp_ids[tag]

            # 2a. 保存
            resp = await client.post(
                f"{BASE}/api/experiments/{exp_id}/flow/save",
                json={"flow": flow}
            )
            if resp.status_code == 200:
                print(f"  {tag} 流程已保存 ✓", end="")
            else:
                print(f"  {tag} 保存失败: {resp.text}", end="")
                continue

            # 2b. 校验
            resp = await client.post(
                f"{BASE}/api/flows/validate",
                json=flow
            )
            val_result = resp.json()
            val_results[tag] = val_result
            if val_result.get("valid"):
                print(f"  校验通过 ✓")
            else:
                print(f"  校验失败: {val_result.get('errors', [])}")
                print(f"  Flow: {json.dumps(flow, indent=2, ensure_ascii=False)[:300]}...")

        # =========================================
        # Step 3: 运行流程 + 收集 WS 消息
        # =========================================
        print("\n" + "=" * 60)
        print("Step 3: 逐个运行流程")

        run_results = {}
        ws_logs = {}

        for tag, flow in flows:
            exp_id = exp_ids[tag]

            print(f"\n--- {tag}: {flow['name']} ---")

            # Start WS listener
            ws_task = asyncio.create_task(collect_ws_messages(35))

            # Wait a moment for WS to connect
            await asyncio.sleep(0.5)

            # Stop any running experiment first
            try:
                await client.post(f"{BASE}/api/experiment/stop")
                await asyncio.sleep(0.3)
            except Exception:
                pass

            # Set duration based on flow type
            durations = {"B1": 30, "B2": 30, "B3": 30, "B4": 60}
            duration = durations.get(tag, 30)

            # Run flow
            try:
                resp = await client.post(f"{BASE}/api/experiment/run-flow", json={
                    "experiment_id": exp_id,
                    "duration": duration,
                })
                if resp.status_code == 200:
                    result = resp.json()
                    print(f"  启动: session_id={result.get('session_id', '?')[:20]}...")
                    run_results[tag] = {"status": "started", "session_id": result.get("session_id")}
                else:
                    print(f"  启动失败: {resp.text}")
                    # Try running with flow data directly
                    resp2 = await client.post(f"{BASE}/api/experiment/run-flow", json={
                        "flow": flow,
                        "duration": duration,
                    })
                    print(f"  直接运行结果: {resp2.status_code} {resp2.text[:200]}")
                    run_results[tag] = {"status": "started_direct", "session_id": resp2.json().get("session_id", "") if resp2.status_code == 200 else ""}
            except Exception as e:
                print(f"  运行异常: {e}")
                run_results[tag] = {"status": "error", "error": str(e)}

            # Wait for flow to complete
            await asyncio.sleep(duration + 3)

            # Collect WS messages
            ws_messages = await ws_task
            ws_logs[tag] = ws_messages

            # Analyze messages
            engine_events = [m for m in ws_messages if m.get("type") == "engine_event"]
            flow_complete = [m for m in ws_messages if m.get("type") == "flow_complete"]
            signals = [m for m in ws_messages if m.get("type") == "signal"]

            print(f"  WS 消息: 共 {len(ws_messages)} 条, engine_event={len(engine_events)}, signal={len(signals)}, flow_complete={len(flow_complete)}")
            if flow_complete:
                print(f"  flow_complete: event_count={flow_complete[0].get('event_count')}, record_count={flow_complete[0].get('record_count')}")

            # Print key engine events
            for ev in engine_events[:20]:  # First 20
                kind = ev.get("kind", "")
                data = ev.get("data", {})
                if kind == "node_executed":
                    print(f"    [{kind}] type={data.get('type')} event_name={data.get('event_name', '')} iteration={data.get('iteration', '')}")
                elif kind in ("loop_iteration", "loop_exit", "loop_timeout"):
                    print(f"    [{kind}] iteration={data.get('iteration', '')} reason={data.get('reason', '')}")
                elif kind == "sniffer_captured":
                    print(f"    [{kind}] signal={data.get('signal_id', '')} event={data.get('event_name', '')}")
                elif kind == "node_triggered":
                    print(f"    [{kind}] node_id={data.get('node_id', '')}")

            # Store results
            run_results[tag]["event_count"] = flow_complete[0].get("event_count", 0) if flow_complete else 0
            run_results[tag]["record_count"] = flow_complete[0].get("record_count", 0) if flow_complete else 0
            run_results[tag]["engine_events"] = len(engine_events)
            run_results[tag]["signals"] = len(signals)

        # =========================================
        # Summary
        # =========================================
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        for tag in ["B1", "B2", "B3", "B4"]:
            v = val_results.get(tag, {})
            r = run_results.get(tag, {})
            print(f"\n{tag}:"  )
            print(f"  校验: {'PASS' if v.get('valid') else 'FAIL'} errors={v.get('errors', [])} warnings={v.get('warnings', [])}")
            print(f"  运行: status={r.get('status', 'N/A')} event_count={r.get('event_count', 'N/A')} record_count={r.get('record_count', 'N/A')} engine_events={r.get('engine_events', 'N/A')} signals={r.get('signals', 'N/A')}")

            # Detailed event breakdown
            msgs = ws_logs.get(tag, [])
            event_types = {}
            for m in msgs:
                if m.get("type") == "engine_event":
                    kind = m.get("kind", "unknown")
                    data = m.get("data", {})
                    if kind == "node_executed":
                        key = f"node_executed:{data.get('type', 'unknown')}"
                    else:
                        key = kind
                    event_types[key] = event_types.get(key, 0) + 1
                elif m.get("type") == "flow_complete":
                    event_types["flow_complete"] = event_types.get("flow_complete", 0) + 1
                elif m.get("type") == "signal":
                    event_types["signal"] = event_types.get("signal", 0) + 1

            for et, count in sorted(event_types.items()):
                print(f"    {et}: {count}")

        # Output full JSON for further analysis
        print("\n" + "=" * 60)
        print("FULL WS LOGS (JSON)")
        print("=" * 60)
        for tag in ["B1", "B2", "B3", "B4"]:
            print(f"\n--- {tag} ---")
            msgs = ws_logs.get(tag, [])
            print(json.dumps(msgs, indent=2, ensure_ascii=False))

        # Also dump to file for easy reading
        with open("/tmp/test_chains_results.json", "w") as f:
            json.dump({
                "exp_ids": exp_ids,
                "val_results": val_results,
                "run_results": run_results,
                "ws_logs": ws_logs,
            }, f, indent=2, ensure_ascii=False, default=str)

        print("\n结果已写入 /tmp/test_chains_results.json")


if __name__ == "__main__":
    asyncio.run(run_test())
