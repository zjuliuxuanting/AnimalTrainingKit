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
        if self.node_type in (NodeType.SNIFFER, NodeType.RECORD_END):
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
        return cls(
            id=data.get("id", ""),
            node_type=node_type,
            label=data.get("label", ""),
            params=data.get("params", {}),
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
