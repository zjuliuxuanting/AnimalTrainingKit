"""
传输抽象层 — 定义上位机与设备通信的传输接口

支持 WebSocket 和 BLE GATT 两种传输方式，
上层 codec（消息编解码）与传输层解耦。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, Awaitable, List
import asyncio
import logging

logger = logging.getLogger("BehaviorBox.Transport")


class TransportState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"


@dataclass
class TransportConfig:
    host: str = "192.168.4.1"
    port: int = 8080
    timeout: float = 5.0
    reconnect_interval: float = 2.0
    max_reconnect_attempts: int = 5
    heartbeat_interval_ms: int = 1000
    offline_threshold_ms: int = 3000
    suspect_threshold_ms: int = 2000


class TransportBase(ABC):
    """
    传输层抽象基类

    子类需实现:
    - connect/disconnect: 连接生命周期
    - send: 发送原始字节/文本
    - _start_receive_loop: 启动接收循环（由子类决定实现方式）
    """

    def __init__(self, config: Optional[TransportConfig] = None):
        self._config = config or TransportConfig()
        self._state: TransportState = TransportState.DISCONNECTED
        self._on_message: Optional[Callable[[str], None]] = None
        self._on_state_change: Optional[Callable[[TransportState, TransportState], None]] = None
        self._reconnect_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> TransportState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == TransportState.CONNECTED

    def set_callbacks(
        self,
        on_message: Optional[Callable[[str], None]] = None,
        on_state_change: Optional[Callable[[TransportState, TransportState], None]] = None,
    ):
        self._on_message = on_message
        self._on_state_change = on_state_change

    def _set_state(self, new_state: TransportState):
        old = self._state
        self._state = new_state
        if old != new_state and self._on_state_change:
            try:
                self._on_state_change(old, new_state)
            except Exception:
                logger.exception("on_state_change callback error")

    def _on_receive(self, raw: str):
        if self._on_message:
            try:
                self._on_message(raw)
            except Exception:
                logger.exception("on_message callback error")

    @abstractmethod
    async def connect(self) -> bool:
        ...

    @abstractmethod
    async def disconnect(self):
        ...

    @abstractmethod
    async def send(self, data: str):
        ...

    async def start(self) -> bool:
        return await self.connect()

    async def stop(self):
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None
        await self.disconnect()

    async def _reconnect_loop(self):
        attempt = 0
        while (
            attempt < self._config.max_reconnect_attempts
            and self._state != TransportState.CONNECTED
        ):
            attempt += 1
            logger.info(f"重连尝试 {attempt}/{self._config.max_reconnect_attempts}")
            self._set_state(TransportState.CONNECTING)
            try:
                if await self.connect():
                    logger.info("重连成功")
                    return
            except Exception:
                logger.exception(f"重连尝试 {attempt} 失败")
            await asyncio.sleep(self._config.reconnect_interval)
        logger.warning("达到最大重连次数，放弃重连")
        self._set_state(TransportState.DISCONNECTED)
