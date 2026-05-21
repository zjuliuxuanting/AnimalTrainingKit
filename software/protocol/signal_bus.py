"""
信号总线 — 统一多源事件收集与分发

职责:
1. 管理多个 SignalSource 的注册/启停
2. 归一化各源事件时间戳到统一时间线
3. 将 SignalEvent 投喂给实验引擎
4. 记录所有事件到 EventStore
5. 支持多种运行模式：纯摄像头、纯设备、混合、纯 Mock
"""

from __future__ import annotations

import asyncio
import time
import logging
from typing import Optional, Dict, List, Callable, Any

from .signal_source import (
    SignalSource, SignalEvent, SourceType, SourceState,
    MockSignalSource, TimerSource,
)

logger = logging.getLogger("BehaviorBox.SignalBus")


class SignalBus:
    """信号总线 — 上层只跟 SignalBus 交互，不直接接触各个信号源"""

    def __init__(self):
        self._sources: Dict[str, SignalSource] = {}
        self._on_signal: Optional[Callable[[SignalEvent], None]] = None
        self._on_source_state: Optional[Callable[[str, SourceState, SourceState], None]] = None
        self._event_log: List[SignalEvent] = []
        self._running = False
        self._started_at_ms: int = 0
        self._event_count: int = 0

    @property
    def sources(self) -> Dict[str, SignalSource]:
        return dict(self._sources)

    @property
    def signal_list(self) -> Dict[str, List[str]]:
        """返回全部可用信号: {source_id: [signal_id, ...]}"""
        return {sid: src.list_signals() for sid, src in self._sources.items()}

    @property
    def has_camera(self) -> bool:
        return any(s.source_type == SourceType.CAMERA for s in self._sources.values())

    @property
    def has_device(self) -> bool:
        return any(s.source_type == SourceType.DEVICE for s in self._sources.values())

    @property
    def event_count(self) -> int:
        return self._event_count

    def set_on_signal(self, cb: Optional[Callable[[SignalEvent], None]]):
        self._on_signal = cb

    def set_on_source_state(self, cb: Optional[Callable[[str, SourceState, SourceState], None]]):
        self._on_source_state = cb

    def register(self, source: SignalSource):
        if source.source_id in self._sources:
            logger.warning(f"信号源已注册，覆盖: {source.source_id}")
        self._sources[source.source_id] = source
        source.set_callbacks(
            on_event=self._on_source_event,
            on_state_change=lambda old, new, sid=source.source_id: self._on_source_state_change(sid, old, new),
        )
        logger.info(f"信号源已注册: {source.source_id} ({source.source_type.value})")

    def unregister(self, source_id: str):
        src = self._sources.pop(source_id, None)
        if src:
            asyncio.create_task(src.stop())

    async def start_all(self) -> bool:
        self._running = True
        self._started_at_ms = int(time.time() * 1000)
        self._event_count = 0
        self._event_log.clear()

        for source_id, source in self._sources.items():
            try:
                ok = await source.start()
                if not ok:
                    logger.error(f"信号源启动失败: {source_id}")
                else:
                    logger.info(f"信号源已启动: {source_id}")
            except Exception as e:
                logger.exception(f"信号源启动异常: {source_id}: {e}")

        running = any(s.is_running for s in self._sources.values())
        if running:
            logger.info(f"SignalBus 已启动: {len(self._sources)} 个信号源")
        else:
            logger.warning("SignalBus 启动：无可用信号源")
        return running

    async def stop_all(self):
        self._running = False
        for source_id, source in list(self._sources.items()):
            try:
                await source.stop()
            except Exception:
                logger.exception(f"信号源停止异常: {source_id}")
        logger.info(f"SignalBus 已停止: 共收集 {self._event_count} 个事件")

    def _on_source_event(self, event: SignalEvent):
        self._event_count += 1
        self._event_log.append(event)
        if len(self._event_log) > 10000:
            self._event_log = self._event_log[-5000:]

        if self._on_signal:
            try:
                self._on_signal(event)
            except Exception:
                logger.exception("on_signal error")

    def _on_source_state_change(self, source_id: str, old: SourceState, new: SourceState):
        logger.info(f"信号源状态: {source_id} {old.value} -> {new.value}")
        if self._on_source_state:
            try:
                self._on_source_state(source_id, old, new)
            except Exception:
                logger.exception("on_source_state error")

    def get_events_since(self, since_ms: int = 0) -> List[SignalEvent]:
        if since_ms <= 0:
            return list(self._event_log)
        return [e for e in self._event_log if e.ts_ms >= since_ms]

    async def create_default_setup(self) -> Dict[str, SignalSource]:
        """
        默认设置：Mock 信号源 + 定时器
        用于无任何硬件时的最小可运行模式
        """
        mock = MockSignalSource("mock:0", event_interval_ms=2000)
        timer = TimerSource("timer:0", tick_interval_ms=1000)
        self.register(mock)
        self.register(timer)
        return {"mock:0": mock, "timer:0": timer}
