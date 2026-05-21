"""
图形化流程编辑器

基于 PyQt6 QGraphicsView 的拖拽式节点编辑器。
支持 9 种 V1 节点类型，节点拖拽、连线、双击属性编辑。
"""

from __future__ import annotations

import sys
import os
from typing import Optional, Dict, List, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsObject, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsPathItem, QGraphicsTextItem,
    QPushButton, QLabel, QComboBox, QSpinBox, QLineEdit, QDialog,
    QFormLayout, QGroupBox, QSplitter, QMessageBox, QDialogButtonBox,
    QToolBar,
)
from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QLineF, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPainterPath,
    QAction, QActionGroup, QPolygonF, QLinearGradient, QTransform,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session.flow_model import (
    FlowGraph, FlowNode, Edge, NodePort,
    NodeType, PortDirection,
)
from session.validator import validate_flow, ValidationResult


NODE_COLORS: Dict[NodeType, str] = {
    NodeType.START: "#4CAF50",
    NodeType.END: "#F44336",
    NodeType.TRIGGER: "#2196F3",
    NodeType.DELAY: "#FF9800",
    NodeType.CONDITION: "#9C27B0",
    NodeType.EXECUTE: "#00BCD4",
    NodeType.LOOP: "#795548",
    NodeType.VARIABLE: "#607D8B",
    NodeType.RECORD: "#3F51B5",
    NodeType.EXCEPTION: "#E91E63",
}

NODE_LABELS: Dict[NodeType, str] = {
    NodeType.START: "开始",
    NodeType.END: "结束",
    NodeType.TRIGGER: "触发",
    NodeType.DELAY: "延时",
    NodeType.CONDITION: "条件",
    NodeType.EXECUTE: "执行",
    NodeType.LOOP: "循环",
    NodeType.VARIABLE: "变量",
    NodeType.RECORD: "记录",
    NodeType.EXCEPTION: "异常",
}

NODE_WIDTH = 140
NODE_HEIGHT = 50
PORT_RADIUS = 6
TEXT_COLOR = QColor("#222222")


class FlowEdgeItem(QGraphicsPathItem):
    """连线图元"""

    def __init__(self, edge: Edge, parent=None):
        super().__init__(parent)
        self._edge = edge
        self._source_pos = QPointF()
        self._target_pos = QPointF()
        color = QColor("#666666")
        pen = QPen(color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    @property
    def edge(self) -> Edge:
        return self._edge

    def set_positions(self, src: QPointF, tgt: QPointF):
        self._source_pos = src
        self._target_pos = tgt
        self._rebuild()

    def _rebuild(self):
        path = QPainterPath()
        path.moveTo(self._source_pos)
        dx = max(abs(self._target_pos.x() - self._source_pos.x()) * 0.5, 40)
        ctrl1 = QPointF(self._source_pos.x() + dx, self._source_pos.y())
        ctrl2 = QPointF(self._target_pos.x() - dx, self._target_pos.y())
        path.cubicTo(ctrl1, ctrl2, self._target_pos)
        self.setPath(path)

        last_pt = path.pointAtPercent(0.95)
        pre_pt = path.pointAtPercent(0.88)
        angle = -QLineF(pre_pt, last_pt).angle()
        sz = 8
        arrow = QPolygonF()
        arrow.append(QPointF(sz, 0))
        arrow.append(QPointF(-sz, sz * 0.5))
        arrow.append(QPointF(-sz, -sz * 0.5))
        t = QTransform()
        t.translate(last_pt.x(), last_pt.y())
        t.rotate(angle)
        self._arrow = t.map(arrow)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        super().paint(painter, option, widget)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.isSelected():
            painter.setBrush(QBrush(QColor("#FFEB3B")))
        else:
            painter.setBrush(QBrush(QColor("#666666")))
        painter.drawPolygon(self._arrow)


class FlowNodeItem(QGraphicsObject):
    """节点图元"""

    moved = pyqtSignal(str)
    double_clicked = pyqtSignal(str)

    def __init__(self, node: FlowNode, parent=None):
        super().__init__(parent)
        self._rect = QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)
        self._node = node
        self._color = QColor(NODE_COLORS.get(node.node_type, "#888888"))

        self.setPos(node.x, node.y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(10)

        self._title_text = QGraphicsTextItem(NODE_LABELS.get(node.node_type, node.node_type.value), self)
        self._title_text.setDefaultTextColor(self._color)
        f = self._title_text.font()
        f.setPointSize(11)
        f.setBold(True)
        self._title_text.setFont(f)
        self._title_text.setPos(8, 2)

        label = node.label if len(node.label) <= 14 else node.label[:13] + "…"
        self._label_text = QGraphicsTextItem(label, self)
        self._label_text.setDefaultTextColor(TEXT_COLOR)
        f2 = self._label_text.font()
        f2.setPointSize(9)
        self._label_text.setFont(f2)
        self._label_text.setPos(8, 18)

        self._input_ports: List[Tuple[NodePort, QGraphicsEllipseItem]] = []
        self._output_ports: List[Tuple[NodePort, QGraphicsEllipseItem]] = []
        self._build_ports()

    def boundingRect(self):
        return self._rect

    @property
    def node(self) -> FlowNode:
        return self._node

    def _build_ports(self):
        dark = QColor("#444444")
        for port in self._node.input_ports:
            dot = QGraphicsEllipseItem(-PORT_RADIUS, -PORT_RADIUS, PORT_RADIUS * 2, PORT_RADIUS * 2, self)
            dot.setBrush(QBrush(dark))
            dot.setPen(QPen(QColor("#222222"), 1))
            dot.setPos(0, NODE_HEIGHT / 2)
            dot.setZValue(20)
            dot.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._input_ports.append((port, dot))

        for i, port in enumerate(self._node.output_ports):
            dot = QGraphicsEllipseItem(-PORT_RADIUS, -PORT_RADIUS, PORT_RADIUS * 2, PORT_RADIUS * 2, self)
            dot.setBrush(QBrush(dark))
            dot.setPen(QPen(QColor("#222222"), 1))
            y_off = NODE_HEIGHT / 2
            if len(self._node.output_ports) > 1:
                spacing = NODE_HEIGHT / (len(self._node.output_ports) + 1)
                y_off = spacing * (i + 1)
            dot.setPos(NODE_WIDTH, y_off)
            dot.setZValue(20)
            dot.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._output_ports.append((port, dot))

    def get_port_scene_pos(self, port: NodePort) -> Optional[QPointF]:
        for p, dot in self._input_ports + self._output_ports:
            if p.port_id == port.port_id and p.direction == port.direction:
                return self.mapToScene(dot.pos())
        return None

    def _port_at_pos(self, local_pos: QPointF):
        for port, dot in self._input_ports:
            if dot.contains(dot.mapFromParent(local_pos)):
                return (port, dot, "input")
        for port, dot in self._output_ports:
            if dot.contains(dot.mapFromParent(local_pos)):
                return (port, dot, "output")
        return None

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._node.x = self.pos().x()
            self._node.y = self.pos().y()
            self.moved.emit(self._node.id)
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self._node.id)
        event.accept()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._rect

        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0, QColor("#FFFFFF"))
        grad.setColorAt(1, QColor("#F0F0F0"))
        painter.setBrush(QBrush(grad))

        if self.isSelected():
            painter.setPen(QPen(QColor("#FFA000"), 3))
        else:
            painter.setPen(QPen(self._color, 2.5))
        painter.drawRoundedRect(r, 8, 8)

        header = QRectF(1, 1, r.width() - 2, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color.darker(120)))
        hpath = QPainterPath()
        hpath.addRoundedRect(header.adjusted(0, 0, 0, 4), 8, 8)
        hpath.addRect(QRectF(1, 11, r.width() - 2, 10))
        painter.drawPath(hpath)

    def refresh_label(self):
        label = self._node.label
        self._label_text.setPlainText(label if len(label) <= 14 else label[:13] + "…")


class FlowView(QGraphicsView):
    """自定义 QGraphicsView —— 处理连线模式下的鼠标交互"""

    def __init__(self, scene: "FlowScene", parent=None):
        super().__init__(scene, parent)
        self._scene = scene
        self._connect_mode = False
        self._drawing_line = False
        self._drag_src_node_id = ""
        self._drag_src_port_id = ""
        self._drag_src_pos: QPointF = QPointF()
        self._temp_line: Optional[QGraphicsPathItem] = None

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor("#F5F5F5")))
        self.setMouseTracking(True)

    def set_connect_mode(self, enabled: bool):
        self._connect_mode = enabled
        if not enabled:
            self._cancel_line()
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag if enabled
            else QGraphicsView.DragMode.RubberBandDrag
        )

    def _cancel_line(self):
        if self._temp_line:
            self._scene.removeItem(self._temp_line)
            self._temp_line = None
        self._drawing_line = False
        self._drag_src_node_id = ""
        self._drag_src_port_id = ""

    def _find_node_at(self, view_pos: QPointF) -> Optional[FlowNodeItem]:
        scene_pos = self.mapToScene(view_pos.toPoint())
        for item in self._scene.items(scene_pos):
            if isinstance(item, FlowNodeItem):
                return item
        parent = self._scene.itemAt(scene_pos)
        while parent:
            if isinstance(parent, FlowNodeItem):
                return parent
            parent = parent.parentItem()
        return None

    def _find_port_at(self, node_item: FlowNodeItem, view_pos: QPointF) -> Optional[Tuple[NodePort, str]]:
        local = node_item.mapFromScene(self.mapToScene(view_pos.toPoint()))
        result = node_item._port_at_pos(local)
        if result:
            port, _, direction = result
            return (port, direction)
        return None

    def mousePressEvent(self, event):
        if self._connect_mode and event.button() == Qt.MouseButton.LeftButton:
            hit_node = self._find_node_at(event.pos())
            if hit_node:
                port_info = self._find_port_at(hit_node, event.pos())
                if port_info and port_info[1] == "output":
                    port, _ = port_info
                    self._drawing_line = True
                    self._drag_src_node_id = hit_node.node.id
                    self._drag_src_port_id = port.port_id
                    self._drag_src_pos = hit_node.mapToScene(
                        next(d.pos() for p, d in hit_node._output_ports if p.port_id == port.port_id)
                    )
                    path = QPainterPath()
                    path.moveTo(self._drag_src_pos)
                    self._temp_line = self._scene.addPath(
                        path, QPen(QColor("#FF9800"), 2, Qt.PenStyle.DashLine)
                    )
                    self._temp_line.setZValue(100)
                    event.accept()
                    return
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drawing_line and self._temp_line:
            scene_pos = self.mapToScene(event.pos().toPoint())
            path = QPainterPath()
            path.moveTo(self._drag_src_pos)
            ctrl_x = (self._drag_src_pos.x() + scene_pos.x()) / 2
            path.cubicTo(
                QPointF(ctrl_x, self._drag_src_pos.y()),
                QPointF(ctrl_x, scene_pos.y()),
                scene_pos,
            )
            self._temp_line.setPath(path)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drawing_line:
            src_node = self._drag_src_node_id
            src_port = self._drag_src_port_id
            self._cancel_line()

            hit_node = self._find_node_at(event.pos())
            port_info = self._find_port_at(hit_node, event.pos()) if hit_node else None

            if hit_node and hit_node.node.id != src_node:
                target_port_id = port_info[0].port_id if (port_info and port_info[1] == "input") else "in"

                source = NodePort(node_id=src_node, port_id=src_port, direction=PortDirection.OUT)
                target = NodePort(node_id=hit_node.node.id, port_id=target_port_id, direction=PortDirection.IN)
                edge = Edge(source=source, target=target)
                self._scene.edge_created.emit(edge)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class FlowScene(QGraphicsScene):
    """流程图场景"""

    edge_created = pyqtSignal(Edge)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-5000, -5000, 10000, 10000)

    def clear_flow(self):
        self.clear()


class NodePalette(QWidget):
    """节点面板"""

    node_added = pyqtSignal(NodeType)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        title = QLabel("节点类型")
        title.setFont(QFont(title.font().family(), 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #333;")
        layout.addWidget(title)

        for nt in NodeType:
            btn = QPushButton(NODE_LABELS.get(nt, nt.value))
            color = NODE_COLORS.get(nt, "#888")
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color}; color: white; "
                f"border-radius: 4px; padding: 4px 8px; font-size: 11px; "
                f"font-weight: bold; border: none; }}"
                f"QPushButton:hover {{ background-color: {QColor(color).lighter(120).name()}; }}"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, t=nt: self.node_added.emit(t))
            layout.addWidget(btn)

        layout.addStretch()


class NodeEditDialog(QDialog):
    """节点属性编辑对话框"""

    def __init__(self, node: FlowNode, parent=None):
        super().__init__(parent)
        self._node = node
        self.setWindowTitle(f"编辑节点 - {NODE_LABELS.get(node.node_type, node.node_type.value)}")
        self.setMinimumWidth(350)
        self._build(node)

    def _build(self, node: FlowNode):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._label_edit = QLineEdit(node.label)
        form.addRow("标签:", self._label_edit)

        self._id_label = QLabel(node.id)
        self._id_label.setStyleSheet("color: #888;")
        form.addRow("ID:", self._id_label)

        layout.addLayout(form)

        params_group = QGroupBox("节点参数")
        params_layout = QFormLayout(params_group)

        nt = node.node_type
        self._param_widgets: Dict[str, QWidget] = {}

        if nt == NodeType.TRIGGER:
            trigger = QComboBox()
            trigger.addItems(["rising", "falling", "change", "high", "low"])
            trigger.setCurrentText(node.params.get("trigger", "rising"))
            params_layout.addRow("触发类型:", trigger)
            self._param_widgets["trigger"] = trigger

            signal = QLineEdit(node.params.get("signal_id", ""))
            signal.setPlaceholderText("如 mock:0:trigger")
            params_layout.addRow("信号ID:", signal)
            self._param_widgets["signal_id"] = signal

            debounce = QSpinBox()
            debounce.setRange(0, 10000)
            debounce.setValue(node.params.get("debounce_ms", 30))
            debounce.setSuffix(" ms")
            params_layout.addRow("去抖:", debounce)
            self._param_widgets["debounce_ms"] = debounce

        elif nt == NodeType.DELAY:
            dur = QSpinBox()
            dur.setRange(1, 3600000)
            dur.setValue(node.params.get("duration_ms", 1000))
            dur.setSuffix(" ms")
            params_layout.addRow("延时:", dur)
            self._param_widgets["duration_ms"] = dur

        elif nt == NodeType.CONDITION:
            var = QLineEdit(node.params.get("variable", ""))
            var.setPlaceholderText("变量名")
            params_layout.addRow("变量:", var)
            self._param_widgets["variable"] = var

            op = QComboBox()
            op.addItems(["eq", "gt", "lt", "gte", "lte"])
            op.setCurrentText(node.params.get("operator", "eq"))
            params_layout.addRow("运算符:", op)
            self._param_widgets["operator"] = op

            val = QSpinBox()
            val.setRange(-99999, 99999)
            val.setValue(node.params.get("value", 0))
            params_layout.addRow("比较值:", val)
            self._param_widgets["value"] = val

        elif nt == NodeType.EXECUTE:
            act_id = QLineEdit(node.params.get("actuator_id", ""))
            act_id.setPlaceholderText("执行器ID")
            params_layout.addRow("执行器ID:", act_id)
            self._param_widgets["actuator_id"] = act_id

            act_type = QComboBox()
            act_type.addItems(["high", "low", "toggle", "pulse"])
            act_type.setCurrentText(node.params.get("action", "high"))
            params_layout.addRow("动作:", act_type)
            self._param_widgets["action"] = act_type

            dur = QSpinBox()
            dur.setRange(0, 60000)
            dur.setValue(node.params.get("duration_ms", 0))
            dur.setSuffix(" ms")
            params_layout.addRow("持续时间:", dur)
            self._param_widgets["duration_ms"] = dur

        elif nt == NodeType.LOOP:
            max_iter = QSpinBox()
            max_iter.setRange(1, 10000)
            max_iter.setValue(node.params.get("max_iterations", 10))
            params_layout.addRow("最大次数:", max_iter)
            self._param_widgets["max_iterations"] = max_iter

            timeout = QSpinBox()
            timeout.setRange(0, 3600000)
            timeout.setValue(node.params.get("timeout_ms", 60000))
            timeout.setSuffix(" ms")
            params_layout.addRow("超时:", timeout)
            self._param_widgets["timeout_ms"] = timeout

        elif nt == NodeType.VARIABLE:
            var_name = QLineEdit(node.params.get("name", ""))
            var_name.setPlaceholderText("变量名")
            params_layout.addRow("变量名:", var_name)
            self._param_widgets["name"] = var_name

            op = QComboBox()
            op.addItems(["set", "inc", "dec"])
            op.setCurrentText(node.params.get("operation", "set"))
            params_layout.addRow("操作:", op)
            self._param_widgets["operation"] = op

            val = QSpinBox()
            val.setRange(-99999, 99999)
            val.setValue(node.params.get("value", 0))
            params_layout.addRow("值:", val)
            self._param_widgets["value"] = val

        elif nt == NodeType.RECORD:
            event_name = QLineEdit(node.params.get("event_name", node.label))
            event_name.setPlaceholderText("事件名")
            params_layout.addRow("事件名:", event_name)
            self._param_widgets["event_name"] = event_name

        elif nt == NodeType.EXCEPTION:
            policy = QComboBox()
            policy.addItems(["retry", "skip", "terminate"])
            policy.setCurrentText(node.params.get("on_failure", "terminate"))
            params_layout.addRow("失败策略:", policy)
            self._param_widgets["on_failure"] = policy

        if params_layout.rowCount() > 0:
            layout.addWidget(params_group)
        else:
            params_group.setTitle("节点参数（无）")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        self._node.label = self._label_edit.text()

        for key, w in self._param_widgets.items():
            if isinstance(w, QComboBox):
                self._node.params[key] = w.currentText()
            elif isinstance(w, QSpinBox):
                self._node.params[key] = w.value()
            elif isinstance(w, QLineEdit):
                self._node.params[key] = w.text()

        self.accept()


class FlowEditor(QWidget):
    """图形化流程编辑器主组件"""

    flow_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flow = FlowGraph()
        self._edge_items: Dict[str, FlowEdgeItem] = {}

        self._init_ui()

    @property
    def flow(self) -> FlowGraph:
        return self._flow

    def set_flow(self, flow: FlowGraph):
        self._flow = flow
        self._rebuild_scene()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        palette = NodePalette()
        palette.node_added.connect(self._on_add_node)
        layout.addWidget(palette)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QToolBar()
        toolbar.setMovable(False)

        self._select_action = QAction("🖱 选择", self)
        self._select_action.setCheckable(True)
        self._select_action.setChecked(True)
        toolbar.addAction(self._select_action)

        self._connect_action = QAction("🔗 连线", self)
        self._connect_action.setCheckable(True)
        toolbar.addAction(self._connect_action)

        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        mode_group.addAction(self._select_action)
        mode_group.addAction(self._connect_action)

        mode_group.triggered.connect(self._on_mode_changed)

        toolbar.addSeparator()
        del_action = QAction("🗑 删除", self)
        del_action.triggered.connect(self._delete_selected)
        toolbar.addAction(del_action)

        toolbar.addSeparator()
        validate_action = QAction("✅ 校验", self)
        validate_action.triggered.connect(self._validate_flow)
        toolbar.addAction(validate_action)

        fit_action = QAction("🔍 适合窗口", self)
        fit_action.triggered.connect(self._fit_view)
        toolbar.addAction(fit_action)

        right_layout.addWidget(toolbar)

        self._scene = FlowScene()
        self._scene.edge_created.connect(self._on_edge_created)

        self._view = FlowView(self._scene)
        right_layout.addWidget(self._view)

        status = QLabel("点「连线」→ 从输出端口拖到目标节点 | 双击节点编辑属性")
        status.setStyleSheet("color: #888; padding: 3px; font-size: 10px;")
        right_layout.addWidget(status)

        layout.addWidget(right)

    def _on_mode_changed(self, action: QAction):
        is_connect = action == self._connect_action
        self._view.set_connect_mode(is_connect)

    def _rebuild_scene(self):
        self._scene.clear_flow()
        self._edge_items.clear()
        for node in self._flow.nodes.values():
            self._add_node_item(node)
        for edge in self._flow.edges:
            self._add_edge_item(edge)

    def _add_node_item(self, node: FlowNode):
        item = FlowNodeItem(node)
        item.moved.connect(lambda nid=node.id: self._on_node_moved(nid))
        item.double_clicked.connect(self._on_node_double_clicked)
        self._scene.addItem(item)
        return item

    def _add_edge_item(self, edge: Edge) -> Optional[FlowEdgeItem]:
        src = self._find_node_item(edge.source.node_id)
        tgt = self._find_node_item(edge.target.node_id)
        if not src or not tgt:
            return None
        src_pos = src.get_port_scene_pos(edge.source)
        tgt_pos = tgt.get_port_scene_pos(edge.target)
        if not src_pos or not tgt_pos:
            return None

        item = FlowEdgeItem(edge)
        item.set_positions(src_pos, tgt_pos)
        self._scene.addItem(item)
        self._edge_items[edge.id] = item
        return item

    def _find_node_item(self, node_id: str) -> Optional[FlowNodeItem]:
        for item in self._scene.items():
            if isinstance(item, FlowNodeItem) and item.node.id == node_id:
                return item
        return None

    def _refresh_edge_positions(self):
        for eitem in self._edge_items.values():
            e = eitem.edge
            src = self._find_node_item(e.source.node_id)
            tgt = self._find_node_item(e.target.node_id)
            if src and tgt:
                sp = src.get_port_scene_pos(e.source)
                tp = tgt.get_port_scene_pos(e.target)
                if sp and tp:
                    eitem.set_positions(sp, tp)

    def _on_add_node(self, node_type: NodeType):
        node = FlowNode(node_type=node_type)
        node.x = 200 + len(self._flow.nodes) * 40
        node.y = 120 + (len(self._flow.nodes) % 5) * 80
        self._flow.add_node(node)
        self._add_node_item(node)
        self.flow_changed.emit()

    def _on_node_moved(self, node_id: str):
        self._refresh_edge_positions()
        self.flow_changed.emit()

    def _on_node_double_clicked(self, node_id: str):
        node = self._flow.nodes.get(node_id)
        if not node:
            return
        dlg = NodeEditDialog(node, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            item = self._find_node_item(node_id)
            if item:
                item.refresh_label()
            self.flow_changed.emit()

    def _on_edge_created(self, edge: Edge):
        self._flow.add_edge(edge)
        self._add_edge_item(edge)
        self.flow_changed.emit()

    def _delete_selected(self):
        for item in self._scene.selectedItems():
            if isinstance(item, FlowNodeItem):
                nid = item.node.id
                self._flow.remove_node(nid)
                for eid in list(self._edge_items.keys()):
                    eitem = self._edge_items[eid]
                    if eitem.edge.source.node_id == nid or eitem.edge.target.node_id == nid:
                        self._scene.removeItem(eitem)
                        del self._edge_items[eid]
                self._scene.removeItem(item)
            elif isinstance(item, FlowEdgeItem):
                eid = item.edge.id
                self._flow.remove_edge(eid)
                self._edge_items.pop(eid, None)
                self._scene.removeItem(item)
        self.flow_changed.emit()

    def _validate_flow(self):
        result = validate_flow(self._flow)
        if result.valid:
            QMessageBox.information(self, "校验通过", str(result))
        else:
            QMessageBox.warning(self, "校验失败", str(result))

    def _fit_view(self):
        rect = self._scene.itemsBoundingRect()
        if rect.width() < 50:
            return
        self._view.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)

    def get_flow_data(self) -> Dict:
        return self._flow.to_dict()

    def load_flow_data(self, data: Dict):
        self._flow = FlowGraph.from_dict(data)
        self._rebuild_scene()
        self.flow_changed.emit()
