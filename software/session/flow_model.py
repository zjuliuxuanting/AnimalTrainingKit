"""
流程图数据模型 — 节点、边、流程图

定义 V1 支持的 8 种节点类型及其参数 schema。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
import uuid


class NodeType(str, Enum):
    START = "start"
    END = "end"
    TRIGGER = "trigger"
    DELAY = "delay"
    CONDITION = "condition"
    EXECUTE = "execute"
    LOOP = "loop"
    RECORD = "record"
    # RECORD_END 已于 Sprint v1.2.0 从新建面板下线，用 RECORD + END 组合替代。
    # 枚举值保留：旧流程加载时 _migrate_record_end 识别并迁移，
    # validator/engine 仍引用此枚举做防御性识别。新建流程不再产出 record_end。
    RECORD_END = "record_end"
    AND = "and"
    NOT = "not"
    FORK = "fork"
    SNIFFER = "sniffer"


class PortDirection(str, Enum):
    IN = "in"
    OUT = "out"


@dataclass
class NodePort:
    node_id: str
    port_id: str
    direction: PortDirection
    label: str = ""

    def __hash__(self):
        return hash((self.node_id, self.port_id))


@dataclass
class Edge:
    id: str = ""
    source: NodePort = field(default_factory=lambda: NodePort("", "", PortDirection.OUT))
    target: NodePort = field(default_factory=lambda: NodePort("", "", PortDirection.IN))
    condition: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]


@dataclass
class FlowNode:
    id: str = ""
    node_type: NodeType = NodeType.TRIGGER
    label: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.node_type.value}_{uuid.uuid4().hex[:6]}"
        if not self.label:
            self.label = self.id

    @property
    def output_ports(self) -> List[NodePort]:
        if self.node_type == NodeType.CONDITION:
            return [
                NodePort(node_id=self.id, port_id="true", direction=PortDirection.OUT, label="True"),
                NodePort(node_id=self.id, port_id="false", direction=PortDirection.OUT, label="False"),
            ]
        if self.node_type == NodeType.LOOP:
            return [
                NodePort(node_id=self.id, port_id="body", direction=PortDirection.OUT, label="循环体"),
                NodePort(node_id=self.id, port_id="exit", direction=PortDirection.OUT, label="退出"),
            ]
        if self.node_type == NodeType.FORK:
            return [
                NodePort(node_id=self.id, port_id="continue", direction=PortDirection.OUT, label="继续"),
                NodePort(node_id=self.id, port_id="stop", direction=PortDirection.OUT, label="记录终止"),
            ]
        if self.node_type in (NodeType.SNIFFER,):
            return []
        return [NodePort(node_id=self.id, port_id="out", direction=PortDirection.OUT, label="")]

    @property
    def input_ports(self) -> List[NodePort]:
        if self.node_type == NodeType.START:
            return []
        if self.node_type == NodeType.SNIFFER:
            return []
        return [NodePort(node_id=self.id, port_id="in", direction=PortDirection.IN, label="")]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "node_type": self.node_type.value,
            "label": self.label,
            "params": self.params,
            "x": self.x,
            "y": self.y,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FlowNode:
        node_type_str = data.get("node_type", "trigger")
        try:
            node_type = NodeType(node_type_str)
        except ValueError:
            # 容错：旧数据中可能存在已删除的节点类型（如 OR）
            # 降级为 RECORD 节点，保留原始 label 和 params
            node_type = NodeType.RECORD
        params = _normalize_legacy_params(node_type, data.get("params", {}))
        return cls(
            id=data.get("id", ""),
            node_type=node_type,
            label=data.get("label", ""),
            params=params,
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
        )


@dataclass
class FlowGraph:
    id: str = ""
    name: str = "新实验流程"
    nodes: Dict[str, FlowNode] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]

    def add_node(self, node: FlowNode) -> FlowNode:
        self.nodes[node.id] = node
        return node

    def remove_node(self, node_id: str):
        self.nodes.pop(node_id, None)
        self.edges = [
            e for e in self.edges
            if e.source.node_id != node_id and e.target.node_id != node_id
        ]

    def add_edge(self, edge: Edge):
        self.edges.append(edge)

    def remove_edge(self, edge_id: str):
        self.edges = [e for e in self.edges if e.id != edge_id]

    def get_start_node(self) -> Optional[FlowNode]:
        for node in self.nodes.values():
            if node.node_type == NodeType.START:
                return node
        return None

    def get_outgoing_edges(self, node_id: str) -> List[Edge]:
        return [e for e in self.edges if e.source.node_id == node_id]

    def get_incoming_edges(self, node_id: str) -> List[Edge]:
        return [e for e in self.edges if e.target.node_id == node_id]

    def validate_has_one_start(self) -> bool:
        starts = [n for n in self.nodes.values() if n.node_type == NodeType.START]
        return len(starts) == 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [
                {
                    "id": e.id,
                    "source_node": e.source.node_id,
                    "source_port": e.source.port_id,
                    "target_node": e.target.node_id,
                    "target_port": e.target.port_id,
                    "condition": e.condition,
                }
                for e in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FlowGraph:
        data = _migrate_record_end(data)
        graph = cls(
            id=data.get("id", ""),
            name=data.get("name", "新实验流程"),
        )
        for node_data in data.get("nodes", {}).values():
            graph.add_node(FlowNode.from_dict(node_data))
        for edge_data in data.get("edges", []):
            graph.add_edge(Edge(
                id=edge_data.get("id", ""),
                source=NodePort(
                    node_id=edge_data["source_node"],
                    port_id=edge_data["source_port"],
                    direction=PortDirection.OUT,
                ),
                target=NodePort(
                    node_id=edge_data["target_node"],
                    port_id=edge_data["target_port"],
                    direction=PortDirection.IN,
                ),
                condition=edge_data.get("condition", ""),
            ))
        return graph


def _migrate_record_end(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate legacy RECORD_END nodes to RECORD + END at the load boundary.

    A `record_end` node is split into:
      - a `record` node (keeps the original id, label, event_name and all
        incoming edges), and
      - a fresh `end` node connected from the record node's `out` port.

    This keeps old flows loadable and runnable after the RECORD_END node type
    was removed (Sprint v1.2.0). Records-then-terminates semantics are now
    expressed with the RECORD + END combination.
    """
    if not isinstance(data, dict):
        return data
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        return data

    has_record_end = any(
        isinstance(nd, dict) and nd.get("node_type") == "record_end"
        for nd in nodes.values()
    )
    if not has_record_end:
        return data

    migrated = dict(data)
    new_nodes: Dict[str, Any] = {}
    new_edges: List[Dict[str, Any]] = list(data.get("edges", []) or [])
    used_ids = set(nodes.keys())

    def _fresh_end_id(base: str) -> str:
        candidate = f"end_{base}"
        suffix = 0
        while candidate in used_ids:
            suffix += 1
            candidate = f"end_{base}_{suffix}"
        used_ids.add(candidate)
        return candidate

    for node_id, nd in nodes.items():
        if not isinstance(nd, dict) or nd.get("node_type") != "record_end":
            new_nodes[node_id] = nd
            continue

        params = dict(nd.get("params") or {})
        # RECORD_END only ever carried event_name; drop anything else stray.
        record_params: Dict[str, Any] = {}
        if params.get("event_name"):
            record_params["event_name"] = params["event_name"]
        if params.get("display_name"):
            record_params["display_name"] = params["display_name"]

        record_node = dict(nd)
        record_node["node_type"] = "record"
        record_node["params"] = record_params
        new_nodes[node_id] = record_node

        end_id = _fresh_end_id(node_id)
        new_nodes[end_id] = {
            "id": end_id,
            "node_type": "end",
            "label": "结束",
            "params": {},
            "x": float(nd.get("x", 0.0)) + 180,
            "y": float(nd.get("y", 0.0)),
        }
        new_edges.append({
            "id": f"edge_{node_id}_to_{end_id}",
            "source_node": node_id,
            "source_port": "out",
            "target_node": end_id,
            "target_port": "in",
            "condition": "",
        })

    migrated["nodes"] = new_nodes
    migrated["edges"] = new_edges
    return migrated


def _normalize_legacy_params(node_type: NodeType, params: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize older saved flow fields at the file/API boundary.

    Legacy quota-specific state fields are intentionally not migrated here
    because they require structural flow changes. Those flows should fail
    validation with an explicit message and be migrated to variables.
    """
    normalized = dict(params or {})
    if node_type == NodeType.DELAY:
        if "duration_value" not in normalized and "duration_s" in normalized:
            try:
                seconds = float(normalized.get("duration_s") or 0)
            except (TypeError, ValueError):
                seconds = 1
            normalized["duration_value"] = max(0, min(1000, round(seconds)))
            normalized["duration_unit"] = "seconds"
        normalized.pop("duration_s", None)

    if node_type == NodeType.RECORD:
        counter_name = normalized.get("counter_name")
        counter_op = normalized.get("counter_op")
        if counter_name and counter_op and "variable_name" not in normalized:
            op_map = {
                "+1": ("add", 1),
                "-1": ("subtract", 1),
                "=0": ("set", 0),
                "=1": ("set", 1),
            }
            if counter_op in op_map:
                variable_op, variable_value = op_map[counter_op]
                normalized["variable_name"] = counter_name
                normalized["variable_op"] = variable_op
                normalized["variable_value"] = variable_value
                normalized.setdefault("variable_persistent", False)
                normalized.pop("counter_name", None)
                normalized.pop("counter_op", None)

    if node_type == NodeType.CONDITION:
        if normalized.get("source") == "counter" and normalized.get("counter_name") and "variable_name" not in normalized:
            normalized["source"] = "variable"
            normalized["variable_name"] = normalized.get("counter_name")
            normalized.pop("counter_name", None)

    return normalized
