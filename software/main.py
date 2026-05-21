"""
行为学训练盒 — 上位机主程序

架构：SignalBus(多信号源) → Engine(实验调度) → Session(数据记录)

信号源统一抽象：
- camera: USB 摄像头 + 运动检测 → signal events
- device: ESP32 Hub 传感器 → signal events
- timer: 周期定时器 → signal events
- mock: 模拟信号（无硬件测试用）

支持模式：
- 纯摄像头：插个摄像头就能跑全流程
- 纯设备：接 ESP32 Hub
- 混合：摄像头 + 设备传感器
- 纯 Mock：零硬件，演示/调试
"""

from __future__ import annotations

import sys
import os
import json
import asyncio
import logging
import platform
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QStatusBar, QToolBar,
    QMessageBox, QFileDialog, QSplitter, QComboBox, QGroupBox,
    QCheckBox, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QAction, QFont, QColor, QPalette

from protocol.signal_source import (
    SignalSource, SignalEvent, SourceType, SourceState,
    MockSignalSource, TimerSource,
)
from protocol.signal_bus import SignalBus
from protocol.device_manager import DeviceManager, DeviceState
from protocol.messages import CmdKind
from protocol.transport import TransportConfig

from session.session import Session, SessionState, ExperimentConfig
from session.flow_model import FlowGraph, FlowNode, NodeType
from session.engine import Engine, EngineState, EngineEvent
from session.validator import validate_flow

from data.database import Database
from data.event_store import EventStore
from data.processor import DataProcessor
from data.export import export_session_csv

from ui.flow_editor import FlowEditor
from ui.charts import DataVisualizationTab

try:
    from ui.camera import CameraSource, HAS_CV2 as HAS_CAMERA
except ImportError:
    HAS_CAMERA = False

APP_NAME = "行为学训练盒"
APP_VERSION = "1.0.0"

log_dir = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(log_dir, "behavior_box.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("BehaviorBox.App")


class AsyncLoopThread(QThread):
    started_loop = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.started_loop.emit()
        self.loop.run_forever()

    def stop(self):
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)


class SignalSourcePanel(QGroupBox):
    """信号源配置面板"""
    source_toggled = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__("信号源配置", parent)
        self._checkboxes: dict = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        tip = QLabel("选择实验要使用的信号源（可多选）")
        tip.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(tip)

        self._mock_cb = QCheckBox("Mock 模拟信号（无需硬件）")
        self._mock_cb.setChecked(True)
        self._mock_cb.setToolTip("产生模拟触发信号，用于功能测试")
        layout.addWidget(self._mock_cb)
        self._checkboxes["mock"] = self._mock_cb

        self._timer_cb = QCheckBox("定时器信号（周期性tick）")
        self._timer_cb.setChecked(True)
        self._timer_cb.setToolTip("产生定时触发信号")
        layout.addWidget(self._timer_cb)
        self._checkboxes["timer"] = self._timer_cb

        self._camera_cb = QCheckBox("摄像头信号（运动检测）")
        self._camera_cb.setChecked(HAS_CAMERA)
        self._camera_cb.setEnabled(HAS_CAMERA)
        self._camera_cb.setToolTip("USB 摄像头 + 运动检测作为触发源" if HAS_CAMERA else "需要 opencv-python")
        layout.addWidget(self._camera_cb)
        self._checkboxes["camera"] = self._camera_cb

        self._device_cb = QCheckBox("ESP32 设备信号（Wi-Fi）")
        self._device_cb.setToolTip("连接 ESP32 Hub 获取传感器信号")
        layout.addWidget(self._device_cb)
        self._checkboxes["device"] = self._device_cb

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet("color: #888;")
        layout.addWidget(self._status_label)

        for cb in self._checkboxes.values():
            cb.stateChanged.connect(self._on_changed)

    def _on_changed(self):
        for key, cb in self._checkboxes.items():
            self.source_toggled.emit(key, cb.isChecked())

    def get_enabled_sources(self) -> list:
        return [k for k, cb in self._checkboxes.items() if cb.isChecked()]

    def set_status(self, text: str, color: str = "#888"):
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color};")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1100, 750)
        self.resize(1280, 850)

        self._async_thread = AsyncLoopThread()
        self._signal_bus = SignalBus()
        self._device_mgr: Optional[DeviceManager] = None
        self._session: Optional[Session] = None
        self._engine: Optional[Engine] = None
        self._camera_source: Optional[CameraSource] = None

        db_path = os.path.join(PROJECT_ROOT, "data", "behavior_box.db")
        self._db = Database(db_path)
        self._db.open()
        self._event_store = EventStore(self._db)
        self._data_processor = DataProcessor()

        self._init_ui()
        self._init_engine()
        self._start_async_loop()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._setup_action = QAction("⚙ 配置信号源", self)
        self._setup_action.triggered.connect(self._setup_sources)
        toolbar.addAction(self._setup_action)

        toolbar.addSeparator()

        self._start_action = QAction("▶ 启动实验", self)
        self._start_action.triggered.connect(self._start_experiment)
        toolbar.addAction(self._start_action)

        self._pause_action = QAction("⏸ 暂停", self)
        self._pause_action.setEnabled(False)
        self._pause_action.triggered.connect(self._pause_experiment)
        toolbar.addAction(self._pause_action)

        self._stop_action = QAction("⏹ 停止", self)
        self._stop_action.setEnabled(False)
        self._stop_action.triggered.connect(self._stop_experiment)
        toolbar.addAction(self._stop_action)

        toolbar.addSeparator()

        export_action = QAction("📥 导出CSV", self)
        export_action.triggered.connect(self._export_csv)
        toolbar.addAction(export_action)

        self._tabs = QTabWidget()

        left_splitter = QSplitter(Qt.Orientation.Vertical)

        self._source_panel = SignalSourcePanel()
        left_splitter.addWidget(self._source_panel)

        self._flow_editor = FlowEditor()
        self._flow_editor.flow_changed.connect(self._on_flow_changed)
        left_splitter.addWidget(self._flow_editor)

        left_splitter.setSizes([100, 500])
        self._tabs.addTab(left_splitter, "流程编辑器")

        self._chart_tab = DataVisualizationTab()
        self._tabs.addTab(self._chart_tab, "数据可视化")

        self._log_widget = QWidget()
        log_layout = QVBoxLayout(self._log_widget)
        from PyQt6.QtWidgets import QTextEdit
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Menlo" if platform.system() == "Darwin" else "Consolas", 10))
        log_layout.addWidget(self._log_text)
        self._tabs.addTab(self._log_widget, "运行日志")

        layout.addWidget(self._tabs)

        self._status_bar = QStatusBar()
        self._status_bar.showMessage("就绪 | 点击「配置信号源」开始")
        self.setStatusBar(self._status_bar)

    def _init_engine(self):
        self._engine = Engine()
        self._engine.set_send_action(self._send_action_to_device)
        self._engine.set_on_engine_event(self._on_engine_event)
        self._engine.set_on_state_change(self._on_engine_state_change)

    def _start_async_loop(self):
        self._async_thread.started_loop.connect(self._on_async_ready)
        self._async_thread.start()

    def _on_async_ready(self):
        loop = self._async_thread.loop
        self._device_mgr = DeviceManager(TransportConfig())
        self._device_mgr.set_callbacks(
            on_event=self._on_device_event,
            on_error=self._on_device_error,
            on_state_change=self._on_device_state_change,
            on_safe_state=self._on_safe_state,
        )
        self._log("异步引擎就绪")

    def _setup_sources(self):
        enabled = self._source_panel.get_enabled_sources()
        self._source_panel.set_status("正在启动信号源...", "#2196F3")

        async def _do():
            for sid in enabled:
                if sid == "mock":
                    mock = MockSignalSource("mock:0", event_interval_ms=2000)
                    self._signal_bus.register(mock)
                elif sid == "timer":
                    timer = TimerSource("timer:0", tick_interval_ms=1000)
                    self._signal_bus.register(timer)
                elif sid == "camera" and HAS_CAMERA:
                    cam = CameraSource("camera:0", camera_index=0, fps=15)
                    self._signal_bus.register(cam)
                    self._camera_source = cam
                elif sid == "device":
                    pass

            ok = await self._signal_bus.start_all()
            if ok:
                self._log("✅ 信号源启动成功", "#4CAF50")
                sig_count = sum(len(v) for v in self._signal_bus.signal_list.values())
                self._source_panel.set_status(f"运行中 | {len(self._signal_bus.sources)}个信号源, {sig_count}个信号", "#4CAF50")
                self._start_action.setEnabled(True)
            else:
                self._log("⚠️ 无信号源启动，但可继续操作", "#FF9800")
                self._source_panel.set_status("无信号源（可手动启动实验）", "#FF9800")

        asyncio.run_coroutine_threadsafe(_do(), self._async_thread.loop)

    def _start_experiment(self):
        flow = self._flow_editor.flow
        result = validate_flow(flow)
        if not result.valid:
            QMessageBox.warning(self, "流程校验失败", str(result))
            return

        config = ExperimentConfig(
            name="实验 - " + flow.name,
            description="",
            session_timeout_ms=3600000,
            flow=flow,
        )

        self._session = Session()
        self._session.load(config)
        self._session.set_on_state_change(self._on_session_state_change)

        self._event_store.ensure_session(
            self._session.id,
            name=config.name,
            flow_json=json.dumps(flow.to_dict(), ensure_ascii=False),
        )

        self._signal_bus.set_on_signal(self._on_bus_signal)

        async def _do():
            await self._engine.start(self._session)

        asyncio.run_coroutine_threadsafe(_do(), self._async_thread.loop)

        self._start_action.setEnabled(False)
        self._pause_action.setEnabled(True)
        self._stop_action.setEnabled(True)
        self._log(f"🚀 实验已启动: session={self._session.id[:12]}")

    def _pause_experiment(self):
        async def _do():
            await self._engine.pause()
        asyncio.run_coroutine_threadsafe(_do(), self._async_thread.loop)
        self._pause_action.setText("▶ 恢复")
        self._pause_action.triggered.disconnect()
        self._pause_action.triggered.connect(self._resume_experiment)

    def _resume_experiment(self):
        async def _do():
            await self._engine.resume()
        asyncio.run_coroutine_threadsafe(_do(), self._async_thread.loop)
        self._pause_action.setText("⏸ 暂停")
        self._pause_action.triggered.disconnect()
        self._pause_action.triggered.connect(self._pause_experiment)

    def _stop_experiment(self):
        async def _do():
            await self._engine.stop()
        asyncio.run_coroutine_threadsafe(_do(), self._async_thread.loop)
        self._start_action.setEnabled(True)
        self._pause_action.setEnabled(False)
        self._stop_action.setEnabled(False)

    def _export_csv(self):
        if not self._session:
            QMessageBox.warning(self, "提示", "没有可导出的会话数据")
            return
        events = self._event_store.get_events(self._session.id)
        if not events:
            QMessageBox.warning(self, "提示", "该会话没有事件数据")
            return
        records = self._data_processor.process(events)
        structured = self._data_processor.to_structured(records)
        path, _ = QFileDialog.getSaveFileName(self, "导出CSV", "", "CSV Files (*.csv)")
        if path:
            export_session_csv(structured, self._session.id, os.path.dirname(path))
            QMessageBox.information(self, "导出成功", f"数据已导出到: {path}")

    async def _send_action_to_device(self, cmd: dict) -> bool:
        if not self._device_mgr or not self._device_mgr.is_online:
            self._log(f"📋 动作记录: {cmd.get('actuator_id')} -> {cmd.get('action')}", "#888")
            return True
        try:
            await self._device_mgr.send_cmd(CmdKind.SET_RULE, {"action": cmd})
            return True
        except Exception as e:
            self._log(f"动作下发失败: {e}", "#F44336")
            return False

    def _on_bus_signal(self, event: SignalEvent):
        qualified = f"{event.source_id}:{event.signal_id}"
        self._log(f"📡 {qualified} = {event.value}", "#2196F3")
        if self._session:
            self._event_store.append_event(
                session_id=self._session.id,
                event_type=f"{event.source_type.value}_{event.signal_id.split(':')[-1]}",
                ts_ms=event.ts_ms,
                signal_id=qualified,
                node_id=event.data.get("node_id", ""),
                actuator_id=event.data.get("actuator_id", ""),
                raw_payload={"value": event.value, "data": event.data},
            )
        if self._engine and self._engine.is_running:
            asyncio.run_coroutine_threadsafe(
                self._engine.feed_signal(event), self._async_thread.loop
            )

    def _on_device_event(self, event_msg):
        qualified = f"device:{event_msg.envelope.device_id}:{event_msg.event_kind.value}"
        self._log(f"📩 {qualified}", "#2196F3")
        if self._session:
            self._event_store.append_event(
                session_id=self._session.id,
                event_type=event_msg.event_kind.value,
                ts_ms=event_msg.envelope.ts_ms,
                device_ts_ms=event_msg.envelope.device_ts_ms,
                raw_payload=event_msg.event_data,
            )

    def _on_device_error(self, error_msg):
        self._log(f"❌ 设备错误: [{error_msg.code}] {error_msg.message}", "#F44336")

    def _on_device_state_change(self, old: DeviceState, new: DeviceState):
        self._status_bar.showMessage(f"设备: {new.value}")

    def _on_safe_state(self):
        self._log("⚠️ 设备进入安全态（离线保护）", "#FF9800")

    def _on_engine_event(self, kind: str, data: dict):
        if kind == "node_triggered":
            self._log(f"⚡ 节点触发: {data.get('node_id')} signal={data.get('signal_id')}", "#FF9800")
        elif kind == "node_executed":
            self._log(f"✅ 节点执行: {data.get('node_id')} type={data.get('type')}", "#4CAF50")
        else:
            self._log(f"🔧 {kind}: {data}")

    def _on_engine_state_change(self, old: EngineState, new: EngineState):
        self._log(f"引擎: {old.value} → {new.value}")
        self._status_bar.showMessage(f"引擎: {new.value} | 信号源: {len(self._signal_bus.sources)}个")

    def _on_session_state_change(self, old: SessionState, new: SessionState):
        self._event_store.update_session_state(
            self._session.id,
            new.value,
            elapsed_ms=self._session.elapsed_ms,
        )

    def _on_flow_changed(self):
        pass

    def _log(self, message: str, color: str = "#333"):
        from PyQt6.QtGui import QTextCursor
        cursor = self._log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log_text.setTextCursor(cursor)
        self._log_text.insertHtml(f'<span style="color:{color};">{message}</span><br>')
        bar = self._log_text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def closeEvent(self, event):
        async def _shutdown():
            if self._engine and self._engine.is_running:
                await self._engine.stop()
            await self._signal_bus.stop_all()
            if self._device_mgr:
                await self._device_mgr.disconnect()

        asyncio.run_coroutine_threadsafe(_shutdown(), self._async_thread.loop)
        self._async_thread.stop()
        self._db.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    if platform.system() == "Windows":
        app.setStyle("Fusion")
        font = QFont("Microsoft YaHei", 9)
    else:
        font = QFont("PingFang SC", 12)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
