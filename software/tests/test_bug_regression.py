"""
Bug 回归测试 — G3 第7轮 8 个 Bug 修复验证

覆盖 Bug #2, #3, #5, #6, #7, #8, #9, #10

注意：Bug #10 是前端问题，此文件只测后端。
前端 Bug #10 需浏览器验证。
"""

import os
import json
import time
import asyncio

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """创建 TestClient，使用 tmp_path 隔离数据。"""
    import server as srv

    original_root = srv.PROJECT_ROOT
    srv.PROJECT_ROOT = str(tmp_path)

    os.makedirs(str(tmp_path / "data_store" / "experiments"), exist_ok=True)
    os.makedirs(str(tmp_path / "web"), exist_ok=True)

    with open(str(tmp_path / "web" / "index.html"), "w", encoding="utf-8") as f:
        f.write("<html><body><h1>行为学训练盒 Behavior Box</h1></body></html>")

    with TestClient(srv.app) as c:
        yield c

    srv.db = None
    srv.event_store = None
    srv._experiment_active = False
    srv.bus = None
    srv.engine = None
    srv.session = None
    srv.PROJECT_ROOT = original_root


# ============================================================================
# Bug #6: 互斥锁 — Mock 运行中 run-flow 应拒绝
# ============================================================================

class TestBug6Mutex:
    """P0-A: 实验/流程无互斥锁"""

    def test_mock_then_run_flow_rejected(self, client):
        """Mock 运行中调用 run-flow → 400"""
        resp = client.post("/api/experiment/start-mock", json={"count": 5})
        assert resp.status_code == 200, f"start-mock 失败: {resp.text}"

        # 尝试 run-flow（应被拒绝）
        flow_data = _make_minimal_flow()
        resp2 = client.post("/api/experiment/run-flow", json={
            "flow": flow_data, "duration": 10
        })
        assert resp2.status_code == 400, f"应返回 400，但得到 {resp2.status_code}: {resp2.text}"
        assert "正在运行" in resp2.text, f"应提示正在运行: {resp2.text}"

        # 清理
        client.post("/api/experiment/stop")

    def test_flow_then_mock_rejected(self, client):
        """Flow 运行中调用 start-mock → 400"""
        flow_data = _make_minimal_flow()
        resp = client.post("/api/experiment/run-flow", json={
            "flow": flow_data, "duration": 10
        })
        assert resp.status_code == 200, f"run-flow 失败: {resp.text}"

        # 尝试 start-mock（应被拒绝）
        resp2 = client.post("/api/experiment/start-mock", json={"count": 1})
        assert resp2.status_code == 400, f"应返回 400，但得到 {resp2.status_code}: {resp2.text}"
        assert "正在运行" in resp2.text, f"应提示正在运行: {resp2.text}"

        client.post("/api/experiment/stop")

    def test_stop_then_start_ok(self, client):
        """停止后可以重新启动"""
        resp = client.post("/api/experiment/start-mock", json={"count": 1})
        assert resp.status_code == 200
        client.post("/api/experiment/stop")

        resp2 = client.post("/api/experiment/start-mock", json={"count": 1})
        assert resp2.status_code == 200, f"停止后应能重新启动: {resp2.text}"
        client.post("/api/experiment/stop")


# ============================================================================
# Bug #2: AND 节点 NameError
# ============================================================================

class TestBug2AndNode:
    """P0-B: AND 节点 _execute_and NameError"""

    def test_and_node_basic(self):
        """AND 节点收到所有输入后触发输出（单 TRIGGER → AND → RECORD）"""
        from session.engine import Engine
        from session.session import Session, ExperimentConfig
        from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection

        # 单 TRIGGER → AND → RECORD：TRIGGER 触发后 AND 收到信号并输出
        graph = FlowGraph(name="test_and")
        n_start = graph.add_node(FlowNode(node_type=NodeType.START, label="START"))
        n_trig = graph.add_node(FlowNode(node_type=NodeType.TRIGGER, label="TRIG", params={"trigger": "rising", "signal_id": "mock:default"}))
        n_and = graph.add_node(FlowNode(node_type=NodeType.AND, label="AND"))
        n_rec = graph.add_node(FlowNode(node_type=NodeType.RECORD, label="REC", params={"event_name": "and_fired"}))

        graph.add_edge(Edge(source=NodePort(n_start.id, "out", PortDirection.OUT), target=NodePort(n_trig.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_trig.id, "out", PortDirection.OUT), target=NodePort(n_and.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_and.id, "out", PortDirection.OUT), target=NodePort(n_rec.id, "in", PortDirection.IN)))

        from protocol.signal_source import SignalEvent, SourceType

        events = []
        def on_evt(kind, data):
            events.append((kind, data))

        async def run_test():
            engine = Engine()
            engine.set_on_engine_event(on_evt)
            session = Session()
            config = ExperimentConfig(name="test_and", flow=graph)
            session.load(config)
            await engine.start(session)
            await asyncio.sleep(0.1)

            # Feed signal matching TRIG's signal_id
            sig = SignalEvent(source_id="mock:0", signal_id="mock:default", value=1, ts_ms=int(time.time()*1000), source_type=SourceType.MOCK)
            await engine.feed_signal(sig)
            await asyncio.sleep(0.5)

            await engine.stop()

            # AND should have fired and executed RECORD
            and_events = [e for e in events if e[0] == "node_executed" and e[1].get("type") == "and"]
            assert len(and_events) >= 1, f"AND 应触发输出，但事件: {events}"

            return True

        asyncio.run(run_test())

    def test_and_node_no_nameerror(self):
        """AND 节点不应抛出 NameError"""
        from session.engine import Engine
        from session.session import Session, ExperimentConfig
        from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection
        from protocol.signal_source import SignalEvent, SourceType

        graph = FlowGraph(name="test_and_noerr")
        n_start = graph.add_node(FlowNode(node_type=NodeType.START, label="START"))
        n_trig = graph.add_node(FlowNode(node_type=NodeType.TRIGGER, label="TRIG", params={"trigger": "rising", "signal_id": "mock:default"}))
        n_and = graph.add_node(FlowNode(node_type=NodeType.AND, label="AND"))
        graph.add_edge(Edge(source=NodePort(n_start.id, "out", PortDirection.OUT), target=NodePort(n_trig.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_trig.id, "out", PortDirection.OUT), target=NodePort(n_and.id, "in", PortDirection.IN)))

        errors = []
        def on_evt(kind, data):
            pass

        async def run_test():
            engine = Engine()
            engine.set_on_engine_event(on_evt)
            session = Session()
            config = ExperimentConfig(name="test_and_noerr", flow=graph)
            session.load(config)
            await engine.start(session)
            await asyncio.sleep(0.2)

            sig = SignalEvent(source_id="mock:0", signal_id="mock:default", value=1, ts_ms=int(time.time()*1000), source_type=SourceType.MOCK)
            try:
                await engine.feed_signal(sig)
                await asyncio.sleep(0.3)
            except Exception as e:
                errors.append(str(e))
            await engine.stop()
            return True

        asyncio.run(run_test())
        assert len(errors) == 0, f"AND 节点不应抛出异常: {errors}"


# ============================================================================
# Bug #3: LOOP 节点迭代
# ============================================================================

class TestBug3LoopIteration:
    """P0-C: LOOP 节点多次迭代"""

    def test_loop_multiple_iterations(self):
        """LOOP(max_iterations=3) → 应记录 3 次事件"""
        from session.engine import Engine
        from session.session import Session, ExperimentConfig
        from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection
        from protocol.signal_source import SignalEvent, SourceType

        # LOOP → RECORD (body path) — exit path not connected
        graph = FlowGraph(name="test_loop3")
        n_start = graph.add_node(FlowNode(node_type=NodeType.START, label="START"))
        n_trig = graph.add_node(FlowNode(node_type=NodeType.TRIGGER, label="TRIG", params={"trigger": "rising", "signal_id": "mock:default"}))
        n_loop = graph.add_node(FlowNode(node_type=NodeType.LOOP, label="LOOP", params={
            "max_iterations": 3, "timeout_s": 60
        }))
        n_rec = graph.add_node(FlowNode(node_type=NodeType.RECORD, label="REC", params={"event_name": "loop_iter"}))

        graph.add_edge(Edge(source=NodePort(n_start.id, "out", PortDirection.OUT), target=NodePort(n_trig.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_trig.id, "out", PortDirection.OUT), target=NodePort(n_loop.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_loop.id, "body", PortDirection.OUT), target=NodePort(n_rec.id, "in", PortDirection.IN)))

        record_count = [0]

        def on_engine_evt(kind, data):
            if kind == "node_executed" and data.get("type") == "record":
                record_count[0] += 1

        async def run_test():
            engine = Engine()
            engine.set_on_engine_event(on_engine_evt)
            session = Session()
            config = ExperimentConfig(name="test_loop3", flow=graph)
            session.load(config)
            await engine.start(session)
            await asyncio.sleep(0.1)

            sig = SignalEvent(source_id="mock:0", signal_id="mock:default", value=1, ts_ms=int(time.time()*1000), source_type=SourceType.MOCK)
            await engine.feed_signal(sig)

            # Wait for 3 iterations to complete
            await asyncio.sleep(1.0)
            await engine.stop()

        asyncio.run(run_test())
        assert record_count[0] >= 3, f"LOOP 应迭代 3 次，但只记录了 {record_count[0]} 次"


# ============================================================================
# Bug #7: signal_id 合法性校验
# ============================================================================

class TestBug7SignalIdValidation:
    """P1-A: 校验器 signal_id 合法性"""

    def test_invalid_signal_id(self, client):
        """不存在的 signal_id → 校验拒绝"""
        flow = _make_flow_with_signal_id("nonexistent_signal_xyz")
        resp = client.post("/api/flows/validate", json=flow)
        data = resp.json()
        assert data["valid"] == False, f"应校验失败: {data}"
        # Should mention signal_id issue

    def test_valid_signal_id(self, client):
        """manual:trigger 是用户主路径有效的 signal_id → 校验通过"""
        flow = _make_flow_with_signal_id("manual:trigger")
        resp = client.post("/api/flows/validate", json=flow)
        data = resp.json()
        assert data["valid"] == True, f"应校验通过: {data}"


# ============================================================================
# Bug #8: 触发节点存在性校验
# ============================================================================

class TestBug8NoTriggerValidation:
    """P1-B: 校验器检查是否包含触发节点"""

    def test_no_trigger_rejected(self, client):
        """无 TRIGGER 节点的流程 → 校验通过但带警告（纯定时器/NOT/逻辑流程不需要触发节点）"""
        flow = _make_flow_without_trigger()
        resp = client.post("/api/flows/validate", json=flow)
        data = resp.json()
        assert data["valid"] == True, f"应校验通过（仅warning非error）: {data}"
        has_trigger_msg = any("触发" in w for w in data.get("warnings", []))
        assert has_trigger_msg, f"应有触发节点警告: {data}"

    def test_with_trigger_ok(self, client):
        """有 TRIGGER 节点的流程 → 校验通过"""
        flow = _make_minimal_flow()
        resp = client.post("/api/flows/validate", json=flow)
        data = resp.json()
        assert data["valid"] == True, f"应校验通过: {data}"


# ============================================================================
# Bug #5: 端口合法性校验
# ============================================================================

class TestBug5PortValidation:
    """P1-D: 端口合法性校验"""

    def test_start_as_target_rejected(self, client):
        """START 节点不能作为连线目标"""
        from session.flow_model import FlowGraph, FlowNode, NodeType
        graph = _make_flow_dict_with_start_as_target()
        resp = client.post("/api/flows/validate", json=graph)
        data = resp.json()
        assert data["valid"] == False, f"START 作为目标应校验失败: {data}"

    def test_end_as_source_rejected(self, client):
        """END 节点不能作为连线来源"""
        graph = _make_flow_dict_with_end_as_source()
        resp = client.post("/api/flows/validate", json=graph)
        data = resp.json()
        assert data["valid"] == False, f"END 作为来源应校验失败: {data}"

    def test_condition_two_outputs(self, client):
        """CONDITION 必须有 2 个输出"""
        graph = _make_flow_dict_with_condition_one_output()
        resp = client.post("/api/flows/validate", json=graph)
        data = resp.json()
        assert data["valid"] == False, f"CONDITION 只有一个输出应校验失败: {data}"

    def test_normal_flow_ok(self, client):
        """正常流程端口校验通过"""
        flow = _make_minimal_flow()
        resp = client.post("/api/flows/validate", json=flow)
        data = resp.json()
        assert data["valid"] == True, f"正常流程应校验通过: {data}"


# ============================================================================
# Bug #9: 空格名称
# ============================================================================

class TestBug9WhitespaceName:
    """P2-A: 保存 API 拒绝纯空格名称"""

    def test_whitespace_name_rejected(self, client):
        """纯空格名称 → 400"""
        resp = client.post("/api/flows/save", json={
            "name": "   ",
            "flow": {"nodes": {}, "edges": []}
        })
        assert resp.status_code == 400, f"纯空格应返回 400: {resp.text}"
        # May contain the error message

    def test_normal_name_ok(self, client):
        """正常名称 → 保存成功"""
        resp = client.post("/api/flows/save", json={
            "name": "测试流程",
            "flow": {"nodes": {}, "edges": []}
        })
        assert resp.status_code == 200, f"正常名称应保存成功: {resp.text}"


# ============================================================================
# Helper 函数
# ============================================================================

def _make_minimal_flow():
    """创建一个最小有效流程：START → TRIGGER → END"""
    return {
        "id": "test_flow_001",
        "name": "测试流程",
        "nodes": {
            "n1": {"id": "n1", "node_type": "start", "label": "开始", "params": {}, "x": 100, "y": 100},
            "n2": {"id": "n2", "node_type": "trigger", "label": "触发", "params": {"signal_id": "manual:trigger"}, "x": 250, "y": 100},
            "n3": {"id": "n3", "node_type": "end", "label": "结束", "params": {}, "x": 400, "y": 100},
        },
        "edges": [
            {"id": "e1", "source_node": "n1", "source_port": "out", "target_node": "n2", "target_port": "in", "condition": ""},
            {"id": "e2", "source_node": "n2", "source_port": "out", "target_node": "n3", "target_port": "in", "condition": ""},
        ],
    }


def _make_flow_with_signal_id(signal_id):
    """创建流程并指定 signal_id"""
    flow = _make_minimal_flow()
    flow["nodes"]["n2"]["params"]["signal_id"] = signal_id
    return flow


def _make_flow_without_trigger():
    """创建无 TRIGGER 节点的流程：START → DELAY → END"""
    return {
        "id": "test_no_trigger",
        "name": "无触发流程",
        "nodes": {
            "n1": {"id": "n1", "node_type": "start", "label": "开始", "params": {}, "x": 100, "y": 100},
            "n2": {"id": "n2", "node_type": "delay", "label": "延时", "params": {"duration_s": 1}, "x": 250, "y": 100},
            "n3": {"id": "n3", "node_type": "end", "label": "结束", "params": {}, "x": 400, "y": 100},
        },
        "edges": [
            {"id": "e1", "source_node": "n1", "source_port": "out", "target_node": "n2", "target_port": "in", "condition": ""},
            {"id": "e2", "source_node": "n2", "source_port": "out", "target_node": "n3", "target_port": "in", "condition": ""},
        ],
    }


def _make_flow_dict_with_start_as_target():
    """创建 START 节点作为连线目标的流程"""
    return {
        "id": "test_start_target",
        "name": "START作为目标",
        "nodes": {
            "n1": {"id": "n1", "node_type": "start", "label": "开始", "params": {}, "x": 100, "y": 100},
            "n2": {"id": "n2", "node_type": "trigger", "label": "触发", "params": {"signal_id": "manual:trigger"}, "x": 250, "y": 100},
        },
        "edges": [
            {"id": "e1", "source_node": "n2", "source_port": "out", "target_node": "n1", "target_port": "in", "condition": ""},
        ],
    }


def _make_flow_dict_with_end_as_source():
    """创建 END 节点作为连线来源的流程"""
    return {
        "id": "test_end_source",
        "name": "END作为来源",
        "nodes": {
            "n1": {"id": "n1", "node_type": "start", "label": "开始", "params": {}, "x": 100, "y": 100},
            "n2": {"id": "n2", "node_type": "end", "label": "结束", "params": {}, "x": 250, "y": 100},
            "n3": {"id": "n3", "node_type": "trigger", "label": "触发", "params": {"signal_id": "manual:trigger"}, "x": 400, "y": 100},
        },
        "edges": [
            {"id": "e1", "source_node": "n1", "source_port": "out", "target_node": "n2", "target_port": "in", "condition": ""},
            {"id": "e2", "source_node": "n2", "source_port": "out", "target_node": "n3", "target_port": "in", "condition": ""},
        ],
    }


def _make_flow_dict_with_condition_one_output():
    """创建 CONDITION 只有一个输出（缺少一个分支）的流程"""
    return {
        "id": "test_cond_one_output",
        "name": "CONDITION少一个输出",
        "nodes": {
            "n1": {"id": "n1", "node_type": "start", "label": "开始", "params": {}, "x": 100, "y": 100},
            "n2": {"id": "n2", "node_type": "trigger", "label": "触发", "params": {"signal_id": "manual:trigger"}, "x": 250, "y": 100},
            "n3": {"id": "n3", "node_type": "condition", "label": "条件", "params": {"operator": "gt", "value": 5}, "x": 400, "y": 100},
            "n4": {"id": "n4", "node_type": "execute", "label": "执行", "params": {"actuator_id": "led1", "action": "pulse", "duration_s": 1}, "x": 550, "y": 100},
        },
        "edges": [
            {"id": "e1", "source_node": "n1", "source_port": "out", "target_node": "n2", "target_port": "in", "condition": ""},
            {"id": "e2", "source_node": "n2", "source_port": "out", "target_node": "n3", "target_port": "in", "condition": ""},
            {"id": "e3", "source_node": "n3", "source_port": "true", "target_node": "n4", "target_port": "in", "condition": ""},
            # Missing "false" branch output
        ],
    }


# ============================================================================
# G3-FIX: NOT 节点校验
# ============================================================================

class TestNotValidation:
    """NOT 节点必须有 signal_id，timeout_s 范围 0.1~3600"""

    def test_not_missing_signal_id(self):
        from session.validator import validate_flow
        from session.flow_model import FlowGraph

        graph = FlowGraph.from_dict({
            "id": "test_not",
            "name": "NOT缺signal_id",
            "nodes": {
                "n1": {"id": "n1", "node_type": "start", "label": "S", "params": {}, "x": 100, "y": 100},
                "n2": {"id": "n2", "node_type": "trigger", "label": "T", "params": {"signal_id": "mock:trig"}, "x": 250, "y": 100},
                "n3": {"id": "n3", "node_type": "not", "label": "NOT", "params": {}, "x": 400, "y": 100},
            },
            "edges": [
                {"id": "e1", "source_node": "n1", "source_port": "out", "target_node": "n2", "target_port": "in", "condition": ""},
                {"id": "e2", "source_node": "n2", "source_port": "out", "target_node": "n3", "target_port": "in", "condition": ""},
            ],
        })
        result = validate_flow(graph)
        assert not result.valid
        assert any("signal_id" in e for e in result.errors)

    def test_not_timeout_range(self):
        from session.validator import validate_flow
        from session.flow_model import FlowGraph

        graph = FlowGraph.from_dict({
            "id": "test_not",
            "name": "NOT超时越界",
            "nodes": {
                "n1": {"id": "n1", "node_type": "start", "label": "S", "params": {}, "x": 100, "y": 100},
                "n2": {"id": "n2", "node_type": "trigger", "label": "T", "params": {"signal_id": "mock:trig"}, "x": 250, "y": 100},
                "n3": {"id": "n3", "node_type": "not", "label": "NOT", "params": {"signal_id": "mock:trig", "timeout_s": 9999}, "x": 400, "y": 100},
            },
            "edges": [
                {"id": "e1", "source_node": "n1", "source_port": "out", "target_node": "n2", "target_port": "in", "condition": ""},
                {"id": "e2", "source_node": "n2", "source_port": "out", "target_node": "n3", "target_port": "in", "condition": ""},
            ],
        })
        result = validate_flow(graph)
        assert not result.valid
        assert any("timeout_s" in e for e in result.errors)

    def test_not_valid(self):
        from session.validator import validate_flow
        from session.flow_model import FlowGraph

        graph = FlowGraph.from_dict({
            "id": "test_not_ok",
            "name": "NOT正常",
            "nodes": {
                "n1": {"id": "n1", "node_type": "start", "label": "S", "params": {}, "x": 100, "y": 100},
                "n2": {"id": "n2", "node_type": "trigger", "label": "T", "params": {"signal_id": "mock:trig"}, "x": 250, "y": 100},
                "n3": {"id": "n3", "node_type": "not", "label": "NOT", "params": {"signal_id": "mock:trig", "timeout_s": 5}, "x": 400, "y": 100},
                "n4": {"id": "n4", "node_type": "end", "label": "E", "params": {}, "x": 550, "y": 100},
            },
            "edges": [
                {"id": "e1", "source_node": "n1", "source_port": "out", "target_node": "n2", "target_port": "in", "condition": ""},
                {"id": "e2", "source_node": "n2", "source_port": "out", "target_node": "n3", "target_port": "in", "condition": ""},
                {"id": "e3", "source_node": "n3", "source_port": "out", "target_node": "n4", "target_port": "in", "condition": ""},
            ],
        })
        result = validate_flow(graph)
        # NOT has valid params → should pass (warnings about no END are OK)
        assert result.valid, f"Expected valid, got errors: {result.errors}"


# ============================================================================
# G3-FIX: LOOP 超时强制执行
# ============================================================================

class TestLoopTimeout:
    """LOOP timeout_s 在运行时应该被强制执行"""

    def test_loop_timeout_enforced(self):
        """LOOP 的 timeout_s 超时后应强制退出，不等 max_iterations"""
        import asyncio, time
        from session.engine import Engine
        from session.session import Session, ExperimentConfig
        from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection

        graph = FlowGraph(name="test_loop_timeout")
        n_start = graph.add_node(FlowNode(node_type=NodeType.START, label="S"))
        n_loop = graph.add_node(FlowNode(node_type=NodeType.LOOP, label="LOOP", params={
            "max_iterations": 100,
            "timeout_s": 0.3,  # 300ms timeout
        }))
        n_delay = graph.add_node(FlowNode(node_type=NodeType.DELAY, label="DELAY", params={"duration_s": 0.15}))
        n_rec = graph.add_node(FlowNode(node_type=NodeType.RECORD, label="REC", params={"event_name": "looped"}))

        graph.add_edge(Edge(source=NodePort(n_start.id, "out", PortDirection.OUT), target=NodePort(n_loop.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_loop.id, "body", PortDirection.OUT), target=NodePort(n_delay.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_delay.id, "out", PortDirection.OUT), target=NodePort(n_rec.id, "in", PortDirection.IN)))

        events = []
        def on_evt(kind, data):
            events.append((kind, data))

        async def run_test():
            engine = Engine()
            engine.set_on_engine_event(on_evt)
            session = Session()
            config = ExperimentConfig(name="test_loop_timeout", flow=graph)
            session.load(config)
            t0 = time.time()
            await engine.start(session)
            # Wait for timeout to trigger
            await asyncio.sleep(1.5)
            await engine.stop()
            elapsed = time.time() - t0

            # Should complete in under 1.5s (timeout 0.3s + some body iterations)
            # If only max_iterations was used, it would take 100 * 0.15 = 15 seconds
            assert elapsed < 3.0, f"超时应快速结束，实际耗时 {elapsed:.1f}s"
            # Less than ~3 iterations expected (300ms timeout / 150ms per iteration)
            iterations = [e for e in events if e[0] == "loop_iteration"]
            assert len(iterations) <= 3, f"应在超时前完成≤3次迭代，实际 {len(iterations)} 次"
            assert len(iterations) >= 1, "至少应有一次迭代"

        asyncio.run(run_test())


# ============================================================================
# G3-FIX: AND 节点状态重置
# ============================================================================

class TestAndReset:
    """AND 节点触发后应重置信号状态，确保循环中可重复使用"""

    def test_and_reset_after_fire(self):
        """AND 触发后 signal_key 被清理"""
        import asyncio, time
        from session.engine import Engine
        from session.session import Session, ExperimentConfig
        from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection
        from protocol.signal_source import SignalEvent, SourceType

        graph = FlowGraph(name="test_and_reset")
        n_start = graph.add_node(FlowNode(node_type=NodeType.START, label="S"))
        n_trig = graph.add_node(FlowNode(node_type=NodeType.TRIGGER, label="TRIG", params={"trigger": "rising", "signal_id": "mock:trig"}))
        n_and = graph.add_node(FlowNode(node_type=NodeType.AND, label="AND"))

        graph.add_edge(Edge(source=NodePort(n_start.id, "out", PortDirection.OUT), target=NodePort(n_trig.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_trig.id, "out", PortDirection.OUT), target=NodePort(n_and.id, "in", PortDirection.IN)))

        events = []
        def on_evt(kind, data):
            events.append((kind, data))

        async def run_test():
            engine = Engine()
            engine.set_on_engine_event(on_evt)
            session = Session()
            config = ExperimentConfig(name="test_and_reset", flow=graph)
            session.load(config)
            await engine.start(session)
            await asyncio.sleep(0.1)

            # Fire trigger → AND fires
            sig = SignalEvent(source_id="mock:0", signal_id="mock:trig", value=1, ts_ms=int(time.time()*1000), source_type=SourceType.MOCK)
            await engine.feed_signal(sig)
            await asyncio.sleep(0.3)

            # Verify AND fired and state was cleared
            and_fires = [e for e in events if e[0] == "node_executed" and e[1].get("type") == "and"]
            assert len(and_fires) == 1, f"AND 应触发，实际事件: {events}"

            # Verify signal_key was cleaned up (AND state reset)
            expected_key = f"and_{n_and.id}"
            assert expected_key not in engine._ctx.variables, f"AND state key '{expected_key}' 应在触发后被清理，但仍存在: {engine._ctx.variables}"

            await engine.stop()

        asyncio.run(run_test())


# ============================================================================
# G3-FIX: 嵌套循环
# ============================================================================

class TestNestedLoop:
    """嵌套 LOOP 应正确工作，不因全局标志位问题而提前终止"""

    def test_nested_loop_no_crash(self):
        """外循环包含 DELAY，内循环包含 RECORD，两层都正常运行"""
        import asyncio, time
        from session.engine import Engine
        from session.session import Session, ExperimentConfig
        from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection

        graph = FlowGraph(name="test_nested")
        n_start = graph.add_node(FlowNode(node_type=NodeType.START, label="S"))
        # 外循环
        n_outer = graph.add_node(FlowNode(node_type=NodeType.LOOP, label="OUTER", params={"max_iterations": 3, "timeout_s": 0}))
        # 外循环 body 内第一个节点
        n_delay = graph.add_node(FlowNode(node_type=NodeType.DELAY, label="D1", params={"duration_s": 0.05}))
        # 内循环
        n_inner = graph.add_node(FlowNode(node_type=NodeType.LOOP, label="INNER", params={"max_iterations": 2, "timeout_s": 0}))
        n_rec = graph.add_node(FlowNode(node_type=NodeType.RECORD, label="REC", params={"event_name": "inner_iter"}))

        graph.add_edge(Edge(source=NodePort(n_start.id, "out", PortDirection.OUT), target=NodePort(n_outer.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_outer.id, "body", PortDirection.OUT), target=NodePort(n_delay.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_delay.id, "out", PortDirection.OUT), target=NodePort(n_inner.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_inner.id, "body", PortDirection.OUT), target=NodePort(n_rec.id, "in", PortDirection.IN)))

        events = []
        def on_evt(kind, data):
            events.append((kind, data))

        async def run_test():
            engine = Engine()
            engine.set_on_engine_event(on_evt)
            session = Session()
            config = ExperimentConfig(name="test_nested", flow=graph)
            session.load(config)
            await engine.start(session)
            await asyncio.sleep(3.0)
            await engine.stop()

            # Inner REC should fire outer_iterations * inner_iterations = 3 * 2 = 6 times
            rec_events = [e for e in events if e[0] == "node_executed" and e[1].get("type") == "record"]
            assert len(rec_events) == 6, f"内循环 REC 应触发 6 次，实际 {len(rec_events)} 次。Events: {events}"

        asyncio.run(run_test())


# ============================================================================
# G3-FIX: NOT 节点引擎执行
# ============================================================================

class TestNotExecution:
    """NOT 节点：无信号时放行，有信号时重置等待"""

    def test_not_pass_without_signal(self):
        """NOT 节点在超时内无匹配信号时应放行"""
        import asyncio, time
        from session.engine import Engine
        from session.session import Session, ExperimentConfig
        from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection

        graph = FlowGraph(name="test_not_pass")
        n_start = graph.add_node(FlowNode(node_type=NodeType.START, label="S"))
        n_not = graph.add_node(FlowNode(node_type=NodeType.NOT, label="NOT", params={
            "signal_id": "mock:absent",
            "timeout_s": 0.2,
        }))
        n_rec = graph.add_node(FlowNode(node_type=NodeType.RECORD, label="REC", params={"event_name": "not_ok"}))

        graph.add_edge(Edge(source=NodePort(n_start.id, "out", PortDirection.OUT), target=NodePort(n_not.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_not.id, "out", PortDirection.OUT), target=NodePort(n_rec.id, "in", PortDirection.IN)))

        events = []
        def on_evt(kind, data):
            events.append((kind, data))

        async def run_test():
            engine = Engine()
            engine.set_on_engine_event(on_evt)
            session = Session()
            config = ExperimentConfig(name="test_not_pass", flow=graph)
            session.load(config)
            await engine.start(session)
            await asyncio.sleep(1.0)
            await engine.stop()

            not_events = [e for e in events if e[0] == "node_executed" and e[1].get("type") == "not"]
            assert len(not_events) >= 1, f"NOT 应放行（无信号），实际事件: {events}"

        asyncio.run(run_test())


# ============================================================================
# G3-FIX: SNIFFER 不影响主流程
# ============================================================================

class TestSnifferNonBlocking:
    """SNIFFER 观察者不应阻塞主流程的触发匹配"""

    def test_sniffer_does_not_block_trigger(self):
        """有 SNIFFER 监听同一 signal_id 时，TRIGGER 仍应正常触发"""
        import asyncio, time
        from session.engine import Engine
        from session.session import Session, ExperimentConfig
        from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection
        from protocol.signal_source import SignalEvent, SourceType

        graph = FlowGraph(name="test_sniffer_ok")
        n_start = graph.add_node(FlowNode(node_type=NodeType.START, label="S"))
        n_trig = graph.add_node(FlowNode(node_type=NodeType.TRIGGER, label="TRIG", params={"trigger": "rising", "signal_id": "mock:trig"}))
        n_sniff = graph.add_node(FlowNode(node_type=NodeType.SNIFFER, label="SNIFF", params={"signal_id": "mock:trig", "event_name": "旁路"}))
        n_rec = graph.add_node(FlowNode(node_type=NodeType.RECORD, label="REC", params={"event_name": "trig_ok"}))

        graph.add_edge(Edge(source=NodePort(n_start.id, "out", PortDirection.OUT), target=NodePort(n_trig.id, "in", PortDirection.IN)))
        graph.add_edge(Edge(source=NodePort(n_trig.id, "out", PortDirection.OUT), target=NodePort(n_rec.id, "in", PortDirection.IN)))

        events = []
        def on_evt(kind, data):
            events.append((kind, data))

        async def run_test():
            engine = Engine()
            engine.set_on_engine_event(on_evt)
            session = Session()
            config = ExperimentConfig(name="test_sniffer_ok", flow=graph)
            session.load(config)
            await engine.start(session)
            await asyncio.sleep(0.2)

            sig = SignalEvent(source_id="mock:0", signal_id="mock:trig", value=1, ts_ms=int(time.time()*1000), source_type=SourceType.MOCK)
            await engine.feed_signal(sig)
            await asyncio.sleep(0.5)

            await engine.stop()

            # TRIGGER must fire
            trig_events = [e for e in events if e[0] == "node_triggered"]
            assert len(trig_events) >= 1, f"TRIGGER 应触发，实际事件: {events}"
            # SNIFFER should capture too
            sniffer_events = [e for e in events if e[0] == "sniffer_captured"]
            assert len(sniffer_events) >= 1, f"SNIFFER 应捕获事件，实际事件: {events}"

        asyncio.run(run_test())
