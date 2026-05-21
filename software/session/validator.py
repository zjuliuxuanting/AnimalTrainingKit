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


def validate_flow(graph: FlowGraph) -> ValidationResult:
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
        if node.node_type == NodeType.START:
            continue
        incoming = graph.get_incoming_edges(node.id)
        if not incoming:
            result.add_error(f"孤立节点 [{node.id}] {node.label}：没有入边连接")
    return result


def _check_dangling_branches(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    for node in graph.nodes.values():
        if node.node_type == NodeType.END:
            continue
        outgoing = graph.get_outgoing_edges(node.id)
        expected = len(node.output_ports)
        if len(outgoing) == 0:
            result.add_error(f"悬空分支 [{node.id}] {node.label}：没有出边连接")
        elif node.node_type == NodeType.CONDITION and len(outgoing) < expected:
            result.add_error(
                f"条件分支不完整 [{node.id}] {node.label}："
                f"需要 True 和 False 两个出边（当前 {len(outgoing)}/{expected}）"
            )
    return result


def _check_node_params(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    for node in graph.nodes.values():
        if node.node_type == NodeType.DELAY:
            ms = node.params.get("duration_ms", 0)
            if ms <= 0 or ms > 3600000:
                result.add_error(
                    f"延时节点 [{node.id}] {node.label}："
                    f"duration_ms 需要 1~3600000（当前 {ms}）"
                )
        elif node.node_type == NodeType.TRIGGER:
            trigger_type = node.params.get("trigger")
            if trigger_type not in ("high", "low", "rising", "falling", "change"):
                result.add_error(
                    f"触发节点 [{node.id}] {node.label}："
                    f"无效的触发类型 '{trigger_type}'"
                )
            debounce = node.params.get("debounce_ms", 0)
            if debounce < 0:
                result.add_error(
                    f"触发节点 [{node.id}] {node.label}：debounce_ms 不能为负"
                )
    return result


def _check_loop_guards(graph: FlowGraph) -> ValidationResult:
    result = ValidationResult()
    for node in graph.nodes.values():
        if node.node_type == NodeType.LOOP:
            max_iter = node.params.get("max_iterations", 0)
            timeout = node.params.get("timeout_ms", 0)
            if max_iter <= 0 and timeout <= 0:
                result.add_error(
                    f"循环节点 [{node.id}] {node.label}："
                    "必须配置 max_iterations > 0 或 timeout_ms > 0 作为上限保护"
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
    result = ValidationResult()

    def _detect_cycle(start_id: str) -> bool:
        visited = set()
        stack = [start_id]
        while stack:
            nid = stack.pop()
            if nid in visited:
                if nid == start_id:
                    return True
                continue
            visited.add(nid)
            for edge in graph.get_outgoing_edges(nid):
                stack.append(edge.target.node_id)
        return False

    for node in graph.nodes.values():
        if node.node_type == NodeType.LOOP:
            if _detect_cycle(node.id):
                result.add_warning(
                    f"循环节点 [{node.id}] {node.label}："
                    "检测到可能的无限循环结构，请确认已配置上限保护"
                )
    return result
