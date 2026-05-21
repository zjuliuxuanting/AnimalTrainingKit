"""
统一信号源抽象 — 将摄像头、设备传感器、定时器等全部视为信号输入源

设计理念：
- 所有输入源统一抽象为 SignalSource，产生统一格式的 SignalEvent
- SignalBus 汇集多源事件，归一化时间戳，投喂给实验引擎
- 支持任意组合：纯摄像头、纯设备传感器、混合模式
- 类似 EthoVision XT 的理念：视频也是信号输入，可以触发实验事件
"""

from __future__ import annotations

import asyncio
import time
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Dict, Any, List, Set

logger = logging.getLogger("BehaviorBox.SignalSource")


class SourceType(str, Enum):
    CAMERA = "camera"
    DEVICE = "device"
    TIMER = "timer"
    MOCK = "mock"


class SourceState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class SignalEvent:
    """统一信号事件 — 所有信号源输出此格式"""
    source_id: str
    source_type: SourceType
    signal_id: str
    ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    value: Any = None
    data: Dict[str, Any] = field(default_factory=dict)

    def to_engine_event(self) -> Dict[str, Any]:
        """转为引擎可消费的事件格式"""
        return {
            "kind": "signal",
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "signal_id": self.signal_id,
            "ts_ms": self.ts_ms,
            "value": self.value,
            "data": self.data,
        }

    def __repr__(self):
        return (f"SignalEvent({self.source_type.value}:{self.source_id}"
                f" -> {self.signal_id}, ts={self.ts_ms})")


class SignalSource(ABC):
    """信号源抽象基类"""

    def __init__(self, source_id: str, source_type: SourceType):
        self._source_id = source_id
        self._source_type = source_type
        self._state: SourceState = SourceState.STOPPED
        self._on_event: Optional[Callable[[SignalEvent], None]] = None
        self._on_state_change: Optional[Callable[[SourceState, SourceState], None]] = None

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def source_type(self) -> SourceType:
        return self._source_type

    @property
    def state(self) -> SourceState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == SourceState.RUNNING

    def set_callbacks(
        self,
        on_event: Optional[Callable[[SignalEvent], None]] = None,
        on_state_change: Optional[Callable[[SourceState, SourceState], None]] = None,
    ):
        self._on_event = on_event
        self._on_state_change = on_state_change

    def _set_state(self, new_state: SourceState):
        old = self._state
        self._state = new_state
        if old != new_state and self._on_state_change:
            try:
                self._on_state_change(old, new_state)
            except Exception:
                logger.exception("on_state_change error")

    def _emit(self, signal_id: str, value: Any = None, data: Dict[str, Any] = None):
        if self._on_event:
            event = SignalEvent(
                source_id=self._source_id,
                source_type=self._source_type,
                signal_id=signal_id,
                ts_ms=int(time.time() * 1000),
                value=value,
                data=data or {},
            )
            try:
                self._on_event(event)
            except Exception:
                logger.exception("on_event error")

    def list_signals(self) -> List[str]:
        """返回此信号源可产生的信号 ID 列表"""
        return []

    @abstractmethod
    async def start(self) -> bool:
        ...

    @abstractmethod
    async def stop(self):
        ...


class MockSignalSource(SignalSource):
    """模拟信号源 — 用于无硬件时的测试和演示"""

    def __init__(self, source_id: str = "mock:0", event_interval_ms: int = 2000):
        super().__init__(source_id, SourceType.MOCK)
        self._interval = event_interval_ms / 1000.0
        self._task: Optional[asyncio.Task] = None
        self._counter = 0
        self._signals = ["mock:trigger", "mock:timer", "mock:random"]

    def list_signals(self) -> List[str]:
        return self._signals

    async def start(self) -> bool:
        self._set_state(SourceState.STARTING)
        self._counter = 0
        self._set_state(SourceState.RUNNING)
        self._task = asyncio.create_task(self._loop())
        logger.info(f"MockSignalSource 启动: {self._source_id}")
        return True

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        self._set_state(SourceState.STOPPED)

    async def _loop(self):
        while self._state == SourceState.RUNNING:
            await asyncio.sleep(self._interval)
            self._counter += 1

            self._emit("mock:timer", self._counter)
            self._emit("mock:trigger", int(self._counter % 3 == 0))
            self._emit("mock:random", self._counter * 7 % 100)


class TimerSource(SignalSource):
    """定时器信号源 — 产生周期性的时间事件，用于定时触发实验流程"""

    def __init__(self, source_id: str = "timer:0", tick_interval_ms: int = 1000):
        super().__init__(source_id, SourceType.TIMER)
        self._interval = tick_interval_ms / 1000.0
        self._task: Optional[asyncio.Task] = None
        self._tick = 0

    def list_signals(self) -> List[str]:
        return ["timer:tick", "timer:elapsed_1s", "timer:elapsed_5s", "timer:elapsed_10s"]

    async def start(self) -> bool:
        self._set_state(SourceState.STARTING)
        self._tick = 0
        self._set_state(SourceState.RUNNING)
        self._task = asyncio.create_task(self._loop())
        return True

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        self._set_state(SourceState.STOPPED)

    async def _loop(self):
        while self._state == SourceState.RUNNING:
            await asyncio.sleep(self._interval)
            self._tick += 1
            self._emit("timer:tick", self._tick, {"elapsed_ms": self._tick * 1000})
            if self._tick % 5 == 0:
                self._emit("timer:elapsed_5s", self._tick)
            if self._tick % 10 == 0:
                self._emit("timer:elapsed_10s", self._tick)
