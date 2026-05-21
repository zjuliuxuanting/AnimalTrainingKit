"""
实验会话生命周期管理

负责会话的创建、启动、暂停、恢复、停止，
以及实验配置的加载与会话状态追踪。
"""

from __future__ import annotations

import uuid
import time
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List, Callable

from .flow_model import FlowGraph

logger = logging.getLogger("BehaviorBox.Session")


class SessionState(str, Enum):
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    ERROR = "error"


class SessionEvent(str, Enum):
    CREATED = "created"
    LOADED = "loaded"
    STARTED = "started"
    PAUSED = "paused"
    RESUMED = "resumed"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ExperimentConfig:
    name: str = "新实验"
    description: str = ""
    session_timeout_ms: int = 3600000
    device_port_mapping: Dict[str, Any] = field(default_factory=dict)
    flow: Optional[FlowGraph] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "name": self.name,
            "description": self.description,
            "session_timeout_ms": self.session_timeout_ms,
            "device_port_mapping": self.device_port_mapping,
        }
        if self.flow:
            d["flow"] = self.flow.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExperimentConfig:
        flow = None
        if "flow" in data and data["flow"]:
            flow = FlowGraph.from_dict(data["flow"])
        return cls(
            name=data.get("name", "新实验"),
            description=data.get("description", ""),
            session_timeout_ms=data.get("session_timeout_ms", 3600000),
            device_port_mapping=data.get("device_port_mapping", {}),
            flow=flow,
        )


class Session:
    """实验会话"""

    def __init__(self):
        self._id: str = f"session_{uuid.uuid4().hex[:12]}"
        self._state: SessionState = SessionState.IDLE
        self._config: Optional[ExperimentConfig] = None
        self._created_at: float = time.time()
        self._started_at: float = 0.0
        self._paused_at: float = 0.0
        self._total_paused_ms: int = 0
        self._event_log: List[Dict[str, Any]] = []

        self._on_state_change: Optional[Callable[[SessionState, SessionState], None]] = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def config(self) -> Optional[ExperimentConfig]:
        return self._config

    @property
    def elapsed_ms(self) -> int:
        if self._started_at == 0:
            return 0
        elapsed = (time.time() - self._started_at) * 1000 - self._total_paused_ms
        return max(0, int(elapsed))

    def set_on_state_change(self, cb: Optional[Callable[[SessionState, SessionState], None]]):
        self._on_state_change = cb

    def _set_state(self, new_state: SessionState, event: Optional[SessionEvent] = None):
        old = self._state
        self._state = new_state
        self._record_event(event or SessionEvent.CREATED, {"old_state": old.value, "new_state": new_state.value})
        if self._on_state_change:
            try:
                self._on_state_change(old, new_state)
            except Exception:
                logger.exception("on_state_change error")

    def load(self, config: ExperimentConfig):
        self._set_state(SessionState.LOADING)
        self._config = config
        self._set_state(SessionState.READY, SessionEvent.LOADED)
        logger.info(f"会话 {self._id} 已加载: {config.name}")

    def start(self):
        if self._state not in (SessionState.READY, SessionState.PAUSED):
            raise RuntimeError(f"无法启动: 当前状态 {self._state.value}")
        self._started_at = time.time()
        self._set_state(SessionState.RUNNING, SessionEvent.STARTED)
        logger.info(f"会话 {self._id} 已启动")

    def pause(self):
        if self._state != SessionState.RUNNING:
            raise RuntimeError(f"无法暂停: 当前状态 {self._state.value}")
        self._paused_at = time.time()
        self._set_state(SessionState.PAUSED, SessionEvent.PAUSED)
        logger.info(f"会话 {self._id} 已暂停")

    def resume(self):
        if self._state != SessionState.PAUSED:
            raise RuntimeError(f"无法恢复: 当前状态 {self._state.value}")
        self._total_paused_ms += int((time.time() - self._paused_at) * 1000)
        self._paused_at = 0.0
        self._set_state(SessionState.RUNNING, SessionEvent.RESUMED)
        logger.info(f"会话 {self._id} 已恢复")

    def stop(self):
        if self._state not in (SessionState.RUNNING, SessionState.PAUSED):
            return
        self._set_state(SessionState.STOPPING)
        self._set_state(SessionState.COMPLETED, SessionEvent.STOPPED)
        logger.info(f"会话 {self._id} 已停止")

    def error(self, message: str):
        self._set_state(SessionState.ERROR, SessionEvent.ERROR)
        self._record_event("error", {"message": message})
        logger.error(f"会话 {self._id} 错误: {message}")

    def _record_event(self, event_type, data: Dict[str, Any] = None):
        self._event_log.append({
            "ts_ms": int(time.time() * 1000),
            "session_id": self._id,
            "event": str(event_type),
            "data": data or {},
        })

    def check_timeout(self) -> bool:
        if self._config and self._config.session_timeout_ms > 0:
            return self.elapsed_ms > self._config.session_timeout_ms
        return False

    def to_summary(self) -> Dict[str, Any]:
        return {
            "session_id": self._id,
            "state": self._state.value,
            "config_name": self._config.name if self._config else "",
            "created_at": self._created_at,
            "elapsed_ms": self.elapsed_ms,
            "event_count": len(self._event_log),
        }
