"""测试 G3-FIN-4: 循环检测规则 — 有 LOOP 放行，无 LOOP 拒绝"""
import pytest
from session.flow_model import FlowGraph, FlowNode, Edge, NodePort, NodeType, PortDirection
from session.validator import validate_flow


def _make_node(nid: str, ntype: str, **params):
    return FlowNode(id=nid, node_type=NodeType(ntype), label=nid, params=params, x=0, y=0)


def _make_edge(sid: str, tid: str, sport: str = "out", tport: str = "in"):
    return Edge(
        id=f"e_{sid}_{tid}",
        source=NodePort(sid, sport, PortDirection.OUT),
        target=NodePort(tid, tport, PortDirection.IN),
    )


class TestLoopDetection:
    """G3-FIN-4: 循环检测规则"""

    def test_cycle_without_loop_rejected(self):
        """无 LOOP 节点的环 → 报 error"""
        flow = FlowGraph(
            id="test1", name="无LOOP循环",
            nodes={
                "a": _make_node("a", "trigger", signal_id="test"),
                "b": _make_node("b", "condition", operator="gt", value=5),
            },
            edges=[
                _make_edge("a", "b"),
                _make_edge("b", "a", sport="true"),
            ],
        )
        r = validate_flow(flow, available_signals=["test"])
        assert not r.valid, "无LOOP的循环应当被拒绝"
        has_cycle_error = any("循环依赖" in e for e in r.errors)
        assert has_cycle_error, f"应当检测到循环依赖错误, got errors={r.errors}"

    def test_cycle_with_loop_allowed(self):
        """有 LOOP 节点的环 → 放行（仅 warning）"""
        flow = FlowGraph(
            id="test2", name="有LOOP循环",
            nodes={
                "start": _make_node("start", "start"),
                "trigger": _make_node("trigger", "trigger", signal_id="test"),
                "loop": _make_node("loop", "loop", max_iterations=10, timeout_s=60),
                "delay": _make_node("delay", "delay", duration_s=1),
                "end": _make_node("end", "end"),
            },
            edges=[
                _make_edge("start", "trigger"),
                _make_edge("trigger", "loop"),
                _make_edge("loop", "delay", sport="body"),
                _make_edge("delay", "loop"),  # cycle back
                _make_edge("loop", "end", sport="exit"),
            ],
        )
        r = validate_flow(flow, available_signals=["test"])
        # 可能其他校验失败（如缺少出边等），但不应有"循环依赖"error
        has_cycle_error = any("循环依赖" in e for e in r.errors)
        assert not has_cycle_error, f"有LOOP的循环不应报循环依赖错误, got errors={r.errors}"
        # 应当有 warning
        has_cycle_warning = any("带循环的路径" in w for w in r.warnings)
        assert has_cycle_warning, f"应当有带循环的路径 warning, got warnings={r.warnings}"


class TestPortValidity:
    """端口规则：每个端口 ≤1 出边/入边"""

    def test_loop_dual_body_edges_rejected(self):
        """LOOP body 拉两根线 → 报 error"""
        flow = FlowGraph(
            id="test_loop_dual_body", name="LOOP双body线",
            nodes={
                "start": _make_node("start", "start"),
                "trigger": _make_node("trigger", "trigger", signal_id="test"),
                "loop": _make_node("loop", "loop", max_iterations=10, timeout_s=60),
                "delay_a": _make_node("delay_a", "delay", duration_s=1),
                "delay_b": _make_node("delay_b", "delay", duration_s=2),
                "end": _make_node("end", "end"),
            },
            edges=[
                _make_edge("start", "trigger"),
                _make_edge("trigger", "loop"),
                _make_edge("loop", "delay_a", sport="body"),
                _make_edge("loop", "delay_b", sport="body"),  # 第二条 body 线
                _make_edge("loop", "end", sport="exit"),
            ],
        )
        r = validate_flow(flow, available_signals=["test"])
        assert not r.valid, "LOOP body 端口有两条出边应当被拒绝"
        has_port_error = any("端口重复" in e or "端口" in e for e in r.errors)
        assert has_port_error, f"应当检测到端口重复错误, got errors={r.errors}"

    def test_normal_single_port_per_output_accepted(self):
        """正常每个输出端口仅一条出边 → 通过"""
        flow = FlowGraph(
            id="test_normal_ports", name="正常端口",
            nodes={
                "start": _make_node("start", "start"),
                "trigger": _make_node("trigger", "trigger", signal_id="test"),
                "condition": _make_node("condition", "condition", operator="gt", value=5),
                "delay": _make_node("delay", "delay", duration_s=1),
                "execute": _make_node("execute", "execute", actuator_id="pump", action="pulse", duration_s=1),
                "end": _make_node("end", "end"),
            },
            edges=[
                _make_edge("start", "trigger"),
                _make_edge("trigger", "condition"),
                _make_edge("condition", "delay", sport="true"),
                _make_edge("condition", "execute", sport="false"),
                _make_edge("delay", "end"),
                _make_edge("execute", "end"),
            ],
        )
        r = validate_flow(flow, available_signals=["test"])
        has_port_error = any("端口重复" in e or "输入端口重复" in e for e in r.errors)
        assert not has_port_error, f"正常端口不应报错, got errors={r.errors}"


class TestTriggerMultiInput:
    """TRIGGER 允许多入边（v2 端口规范）"""

    def test_trigger_two_inputs_loop_back_accepted(self):
        """操作性条件反射范式: START+LOOP回路 汇聚到 TRIGGER → 允许"""
        flow = FlowGraph(
            id="test_trigger_multi", name="操作性条件反射-回路",
            nodes={
                "start": _make_node("start", "start"),
                "trigger": _make_node("trigger", "trigger", signal_id="press"),
                "delay": _make_node("delay", "delay", duration_s=1),
                "execute": _make_node("execute", "execute", actuator_id="feeder", action="pulse", duration_s=1),
                "loop": _make_node("loop", "loop", max_iterations=100, timeout_s=3600),
                "end": _make_node("end", "end"),
            },
            edges=[
                _make_edge("start", "trigger"),
                _make_edge("trigger", "delay"),
                _make_edge("delay", "execute"),
                _make_edge("execute", "loop"),
                _make_edge("loop", "trigger", sport="body"),  # 回路：LOOP body → TRIGGER
                _make_edge("loop", "end", sport="exit"),
            ],
        )
        r = validate_flow(flow, available_signals=["press"])
        # 不应有"输入端口重复"错误
        has_multi_input_error = any("输入端口重复" in e for e in r.errors)
        assert not has_multi_input_error, f"TRIGGER应允许多入边, got errors={r.errors}"
        # 有 LOOP 的环 → warning 可接受
        has_cycle_warning = any("带循环的路径" in w for w in r.warnings)
        assert has_cycle_warning, f"应当有带循环的路径 warning, got warnings={r.warnings}"

    def test_trigger_single_input_still_works(self):
        """单入边 TRIGGER → 正常通过"""
        flow = FlowGraph(
            id="test_trigger_single", name="单入边触发",
            nodes={
                "start": _make_node("start", "start"),
                "trigger": _make_node("trigger", "trigger", signal_id="test"),
                "end": _make_node("end", "end"),
            },
            edges=[
                _make_edge("start", "trigger"),
                _make_edge("trigger", "end"),
            ],
        )
        r = validate_flow(flow, available_signals=["test"])
        assert r.valid, f"单入边TRIGGER应通过, got errors={r.errors}"

    def test_other_nodes_still_reject_multi_input(self):
        """CONDITION/NOT/FORK/LOOP 等严格单入边节点仍然拒绝多入边"""
        flow = FlowGraph(
            id="test_not_multi", name="NOT多入边",
            nodes={
                "start": _make_node("start", "start"),
                "trigger_a": _make_node("trigger_a", "trigger", signal_id="a"),
                "trigger_b": _make_node("trigger_b", "trigger", signal_id="b"),
                "not_node": _make_node("not_node", "not", signal_id="x", timeout_s=5),
                "end": _make_node("end", "end"),
            },
            edges=[
                _make_edge("start", "trigger_a"),
                _make_edge("trigger_a", "not_node"),
                _make_edge("trigger_b", "not_node"),  # 第二条入边到 NOT
                _make_edge("not_node", "end"),
            ],
        )
        r = validate_flow(flow, available_signals=["a", "b", "x"])
        assert not r.valid, "NOT多入边应当被拒绝（NOT inputs=1）"
        has_multi_error = any("输入端口重复" in e for e in r.errors)
        assert has_multi_error, f"NOT多入边应当报错, got errors={r.errors}"
