"""
流程静态校验器

在发布实验配置前自动执行:
- 节点完整性检查（无孤立节点、无悬空分支）
- 执行节点必须绑定具体端口与外设实例
- 循环节点必须配置最大次数或超时终止
- 参数范围校验 + 端口映射校验 + 死循环风险检测
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple
from .flow_model import FlowGraph, NodeType, FlowNode


@dataclass
class ValidationResult:
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def merge(self, other: ValidationResult):
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if other.errors:
            self.valid = False

    def __str__(self) -> str:
        parts = []
        if self.valid:
            parts.append("✅ 流程校验通过")
        else:
            parts.append(f"❌ 流程校验失败 ({len(self.errors)} 个错误)")
        for e in self.errors:
            parts.append(f"  ❌ {e}")
        for w in self.warnings:
            parts.append(f"  ⚠️ {w}")
        return "\n".join(parts)


def validate_flow(graph: FlowGraph, available_signals: list[str] | None = None) -> ValidationResult:
    result = ValidationResult()

    if not graph.nodes:
        result.add_error("流程图为空，至少需要一个开始节点")
        return result

    result.merge(_check_start_end(graph))
    result.merge(_check_orphan_nodes(graph))
    result.merge(_check_dangling_branches(graph))
    result.merge(_check_node_params(graph))
    result.merge(_check_loop_guards(graph))
    result.merge(_check_execute_bindings(graph))
    result.merge(_check_infinite_loop_risk(graph))
    result.merge(_check_has_trigger(graph))
    result.merge(_check_port_validity(graph))
    if available_signals is not None:
        result.merge(_check_trigger_signal_ids(graph, available_signals))

    return result


def _check_start_end(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    starts = [n for n in graph.nodes.values() if n.node_type == NodeType.START]
    ends = [n for n in graph.nodes.values() if n.node_type == NodeType.END]

    if len(starts) == 0:
        result.add_error("缺少开始节点（必须且仅有一个）")
    elif len(starts) > 1:
        result.add_error(f"开始节点过多: {len(starts)} 个（必须仅一个）")

    if len(ends) == 0:
        result.add_warning("没有结束节点，流程可能无法正常终止")

    return result


def _check_orphan_nodes(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    for node in graph.nodes.values():
        if node.node_type in (NodeType.START, NodeType.SNIFFER, NodeType.RECORD_END):
            continue
        incoming = graph.get_incoming_edges(node.id)
        if not incoming:
            result.add_error(f"孤立节点 [{node.id}] {node.label}：没有入边连接")
    return result


def _nodes_inside_loop_body(graph: FlowGraph) -> set[str]:
    """返回所有 LOOP body 分支内的节点ID（递归，支持嵌套）。"""
    inside: set[str] = set()
    for node in graph.nodes.values():
        if node.node_type != NodeType.LOOP:
            continue
        for edge in graph.get_outgoing_edges(node.id):
            if edge.source.port_id != "body":
                continue
            # BFS from body target
            stack = [edge.target.node_id]
            while stack:
                nid = stack.pop()
                if nid in inside:
                    continue
                inside.add(nid)
                for e in graph.get_outgoing_edges(nid):
                    tgt = e.target.node_id
                    if tgt not in inside:
                        stack.append(tgt)
    return inside


def _check_dangling_branches(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    loop_body_nodes = _nodes_inside_loop_body(graph)
    for node in graph.nodes.values():
        if node.node_type in (NodeType.END, NodeType.SNIFFER, NodeType.RECORD_END):
            continue
        outgoing = graph.get_outgoing_edges(node.id)
        expected = len(node.output_ports)
        if len(outgoing) == 0:
            # LOOP body 内的末节点不需要出边，引擎自动回到 LOOP 做下一轮迭代判断
            if node.id in loop_body_nodes:
                continue
            result.add_error(f"悬空分支 [{node.id}] {node.label}：没有出边连接")
        elif node.node_type == NodeType.CONDITION and len(outgoing) < expected:
            result.add_error(
                f"条件分支不完整 [{node.id}] {node.label}："
                f"需要 True 和 False 两个出边（当前 {len(outgoing)}/{expected}）"
            )
        elif node.node_type == NodeType.FORK and len(outgoing) < expected:
            result.add_error(
                f"逻辑分叉不完整 [{node.id}] {node.label}："
                f"需要「继续」和「记录终止」两个出边（当前 {len(outgoing)}/{expected}）"
            )
    return result


def _check_node_params(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    for node in graph.nodes.values():
        if node.node_type == NodeType.DELAY:
            # Frontend Schema uses duration_s (seconds), range 0.1~3600
            duration_s = node.params.get("duration_s")
            if duration_s is None or duration_s == "":
                result.add_error(
                    f"延时节点 [{node.id}] {node.label}："
                    "duration_s 不能为空"
                )
            elif not isinstance(duration_s, (int, float)) or duration_s < 0.1 or duration_s > 3600:
                result.add_error(
                    f"延时节点 [{node.id}] {node.label}："
                    f"duration_s 需要 0.1~3600（秒）（当前 {duration_s}）"
                )
        elif node.node_type == NodeType.EXECUTE:
            actuator_id = node.params.get("actuator_id", "")
            if not actuator_id or actuator_id.strip() == "":
                result.add_error(
                    f"执行节点 [{node.id}] {node.label}："
                    "actuator_id 不能为空"
                )
            action = node.params.get("action", "")
            if action not in ("high", "low"):
                result.add_error(
                    f"执行节点 [{node.id}] {node.label}："
                    f"action 必须为 high 或 low（当前 {action}）"
                )
        elif node.node_type == NodeType.CONDITION:
            source = node.params.get("source", "")
            if not source or source == "":
                result.add_error(
                    f"条件判断节点 [{node.id}] {node.label}："
                    "source（数据来源）不能为空"
                )
            operator = node.params.get("operator", "")
            if operator not in ("eq", "neq", "gt", "lt", "gte", "lte"):
                result.add_error(
                    f"条件判断节点 [{node.id}] {node.label}："
                    f"无效的 operator '{operator}'"
                )
            value = node.params.get("value")
            if value is None or value == "":
                result.add_error(
                    f"条件判断节点 [{node.id}] {node.label}："
                    "value（判断值）不能为空"
                )
            elif not isinstance(value, (int, float)) or value < 0 or value > 999999:
                result.add_error(
                    f"条件判断节点 [{node.id}] {node.label}："
                    f"value 需要 0~999999（当前 {value}）"
                )
        elif node.node_type in (NodeType.RECORD, NodeType.RECORD_END):
            event_name = node.params.get("event_name")
            if not event_name or event_name.strip() == "":
                result.add_error(
                    f"记录节点 [{node.id}] {node.label}："
                    "event_name 不能为空"
                )
        elif node.node_type == NodeType.TRIGGER:
            # D-17: simplified to only signal_id (string, required, non-empty)
            signal_id = node.params.get("signal_id")
            if not signal_id or signal_id == "":
                result.add_error(
                    f"触发节点 [{node.id}] {node.label}："
                    "signal_id 不能为空"
                )
        elif node.node_type == NodeType.LOOP:
            # timeout_s=0 表示不启用超时（仅靠 max_iterations 控制），>=1 时为超时秒数
            timeout_s = node.params.get("timeout_s")
            if timeout_s is not None and timeout_s != "":
                if not isinstance(timeout_s, (int, float)) or timeout_s < 0 or timeout_s > 3600:
                    result.add_error(
                        f"循环节点 [{node.id}] {node.label}："
                        f"timeout_s 需要 1~3600（秒）（当前 {timeout_s}）"
                    )
        elif node.node_type == NodeType.NOT:
            signal_id = node.params.get("signal_id")
            if not signal_id or signal_id == "":
                result.add_error(
                    f"逻辑非节点 [{node.id}] {node.label}："
                    "signal_id 不能为空"
                )
            timeout_s = node.params.get("timeout_s")
            if timeout_s is not None and timeout_s != "":
                if not isinstance(timeout_s, (int, float)) or timeout_s < 0.1 or timeout_s > 3600:
                    result.add_error(
                        f"逻辑非节点 [{node.id}] {node.label}："
                        f"timeout_s 需要 0.1~3600（秒）（当前 {timeout_s}）"
                    )
    return result


def _check_loop_guards(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    for node in graph.nodes.values():
        if node.node_type == NodeType.LOOP:
            max_iter = node.params.get("max_iterations", 0)
            timeout = node.params.get("timeout_s", 0)
            if max_iter <= 0 and timeout <= 0:
                result.add_error(
                    f"循环节点 [{node.id}] {node.label}："
                    "必须配置 max_iterations > 0 或 timeout_s > 0 作为上限保护"
                )
    return result


def _check_execute_bindings(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    for node in graph.nodes.values():
        if node.node_type == NodeType.EXECUTE:
            actuator = node.params.get("actuator_id", "")
            if not actuator:
                result.add_error(
                    f"执行节点 [{node.id}] {node.label}："
                    "未绑定执行器（actuator_id 为空）"
                )
    return result


def _check_infinite_loop_risk(graph: FlowGraph) -> ValidationResult:
    """Detect all circular dependencies in the flow graph using DFS.

    D-22: "有 LOOP 的环放行（有终止条件），无 LOOP 的环拒绝"

    Covers:
    - Self-loops (A → A)
    - Mutual loops (A → B → A)
    - Multi-node loops (A → B → C → A)
    - All node types (CONDITION, DELAY, LOOP, AND, OR, NOT, etc.)
    """
    result = ValidationResult()

    # Build adjacency list from edges
    adjacency: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        adjacency[node.id] = []
    for edge in graph.edges:
        adjacency.setdefault(edge.source.node_id, []).append(edge.target.node_id)

    def _find_cycle_from(start_id: str) -> list[str] | None:
        """DFS from start_id, return cycle path if found, else None."""
        visited: set[str] = set()
        path: list[str] = []

        def dfs(nid: str) -> bool:
            if nid in visited:
                if nid == start_id and len(path) > 0:
                    return True
                return False
            visited.add(nid)
            path.append(nid)
            for next_id in adjacency.get(nid, []):
                if dfs(next_id):
                    return True
            path.pop()
            return False

        if dfs(start_id):
            cycle_start_idx = path.index(start_id)
            return path[cycle_start_idx:] + [start_id]
        return None

    def _cycle_contains_loop(cycle_path: list[str]) -> bool:
        """Check if any node in the cycle is a LOOP node."""
        for nid in cycle_path:
            node = graph.nodes.get(nid)
            if node and node.node_type == NodeType.LOOP:
                return True
        return False

    # Check all nodes for cycles
    checked_cycles: set[frozenset] = set()
    for node in graph.nodes.values():
        cycle_path = _find_cycle_from(node.id)
        if cycle_path:
            cycle_key = frozenset(cycle_path[:-1])
            if cycle_key not in checked_cycles:
                checked_cycles.add(cycle_key)
                cycle_str = " → ".join(cycle_path)
                if _cycle_contains_loop(cycle_path):
                    # D-22: 有 LOOP 的环放行（有终止条件）
                    result.add_warning(
                        f"检测到带循环的路径：{cycle_str} — "
                        "路径中包含 LOOP 节点，自动放行（有终止条件保护）"
                    )
                else:
                    result.add_error(
                        f"检测到循环依赖：{cycle_str} — "
                        "此连线会形成无终止条件的循环，流程无法运行。"
                        "如需循环请使用 LOOP 节点"
                    )
    return result


def _check_has_trigger(graph: FlowGraph) -> ValidationResult:
    """检查流程中是否包含至少一个 TRIGGER 节点（无 TRIGGER 为 warning，而非 error）"""
    result = ValidationResult()
    triggers = [n for n in graph.nodes.values() if n.node_type == NodeType.TRIGGER]
    if len(triggers) == 0:
        result.add_warning("流程中没有触发信号节点，可能无法响应外部信号")
    return result


def _check_port_validity(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()

    for node in graph.nodes.values():
        incoming = graph.get_incoming_edges(node.id)
        outgoing = graph.get_outgoing_edges(node.id)

        # SNIFFER 0入0出，跳过端口校验
        if node.node_type == NodeType.SNIFFER:
            continue

        # START 不能作为连线目标（没有输入端口）
        if node.node_type == NodeType.START and incoming:
            for edge in incoming:
                result.add_error(
                    f"开始节点 [{node.id}] {node.label}："
                    f"开始节点没有输入端口，不能作为连线目标"
                )

        # END 不能作为连线来源（没有输出端口）
        if node.node_type == NodeType.END and outgoing:
            for edge in outgoing:
                result.add_error(
                    f"结束节点 [{node.id}] {node.label}："
                    f"结束节点没有输出端口，不能作为连线来源"
                )

        # RECORD_END 不能作为连线来源（0个输出端口）
        if node.node_type == NodeType.RECORD_END and outgoing:
            for edge in outgoing:
                result.add_error(
                    f"记录终止节点 [{node.id}] {node.label}："
                    f"记录终止节点没有输出端口，不能作为连线来源"
                )

        # CONDITION 必须有 2 个输出（真/假）— 兼容中英文 port_id
        if node.node_type == NodeType.CONDITION:
            true_edges = [e for e in outgoing if e.source.port_id in ("true", "真")]
            false_edges = [e for e in outgoing if e.source.port_id in ("false", "假")]
            if len(true_edges) == 0:
                result.add_error(
                    f"条件分支不完整 [{node.id}] {node.label}："
                    f"缺少「真」分支输出连线"
                )
            if len(false_edges) == 0:
                result.add_error(
                    f"条件分支不完整 [{node.id}] {node.label}："
                    f"缺少「假」分支输出连线"
                )

        # LOOP 必须有 2 个输出（循环体/退出）
        if node.node_type == NodeType.LOOP:
            body_edges = [e for e in outgoing if e.source.port_id == "body"]
            exit_edges = [e for e in outgoing if e.source.port_id == "exit"]
            if len(body_edges) == 0:
                result.add_error(
                    f"循环节点 [{node.id}] {node.label}："
                    f"缺少「循环体」分支输出连线"
                )
            if len(exit_edges) == 0:
                result.add_error(
                    f"循环节点 [{node.id}] {node.label}："
                    f"缺少「退出」分支输出连线"
                )

        # AND 必须有 ≥1 个输入
        if node.node_type == NodeType.AND and len(incoming) == 0:
            result.add_error(
                f"逻辑节点 [{node.id}] {node.label}："
                f"需要至少一个输入连线"
            )

    # --- 每个输出端口 ≤1 出边 ---
    for node in graph.nodes.values():
        outgoing = graph.get_outgoing_edges(node.id)
        # Group by source port_id
        port_counts: dict[str, int] = {}
        for edge in outgoing:
            pid = edge.source.port_id
            port_counts[pid] = port_counts.get(pid, 0) + 1
        for pid, count in port_counts.items():
            if count >= 2:
                # Map port_id to human-readable label
                label_map = {
                    'body': '循环体', 'exit': '退出',
                    'true': '真', 'false': '假',
                    'continue': '继续', 'stop': '记录终止',
                }
                pname = label_map.get(pid, pid)
                result.add_error(
                    f"端口重复 [{node.id}] {node.label}："
                    f"「{pname}」端口有 {count} 条出边（每个端口最多 1 条）"
                )

    # --- 每个输入端口 ≤1 入边（多入边豁免节点除外）---
    for node in graph.nodes.values():
        if node.node_type in (NodeType.AND, NodeType.END, NodeType.TRIGGER,
                               NodeType.DELAY, NodeType.EXECUTE,
                               NodeType.RECORD, NodeType.RECORD_END):
            continue
        incoming = graph.get_incoming_edges(node.id)
        if len(incoming) >= 2:
            result.add_error(
                f"输入端口重复 [{node.id}] {node.label}："
                f"有 {len(incoming)} 条入边（最多 1 条）"
            )

    return result


def _check_trigger_signal_ids(graph: FlowGraph, available_signals: list[str]) -> ValidationResult:
    """Bug #7: 检查 TRIGGER 节点的 signal_id 是否在可用信号列表中"""
    result = ValidationResult()
    for node in graph.nodes.values():
        if node.node_type == NodeType.TRIGGER:
            signal_id = node.params.get("signal_id", "")
            if signal_id and signal_id not in available_signals:
                result.add_error(
                    f"触发节点 [{node.id}] {node.label}："
                    f"信号源 \"{signal_id}\" 不存在，请从可用信号源中选择"
                )
    return result
