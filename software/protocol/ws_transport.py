"""
WebSocket 传输实现

基于 websockets 库实现与 ESP32 Hub 的 Wi-Fi 通信。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, WebSocketException
except ImportError:
    websockets = None

from .transport import TransportBase, TransportState, TransportConfig

logger = logging.getLogger("BehaviorBox.WsTransport")


class WsTransport(TransportBase):
    """WebSocket 传输层"""

    def __init__(self, config: Optional[TransportConfig] = None):
        super().__init__(config)
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    @property
    def uri(self) -> str:
        return f"ws://{self._config.host}:{self._config.port}"

    async def connect(self) -> bool:
        if websockets is None:
            logger.error("websockets 库未安装，请执行: pip install websockets")
            return False

        self._set_state(TransportState.CONNECTING)
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(
                    self.uri,
                    ping_interval=None,
                    close_timeout=3,
                    max_size=2 * 1024 * 1024,
                ),
                timeout=self._config.timeout,
            )
            self._set_state(TransportState.CONNECTED)
            logger.info(f"WebSocket 已连接: {self.uri}")
            self._stop_event.clear()
            self._receive_task = asyncio.create_task(self._receive_loop())
            return True
        except asyncio.TimeoutError:
            logger.error(f"WebSocket 连接超时: {self.uri}")
            self._set_state(TransportState.DISCONNECTED)
            return False
        except Exception as e:
            logger.error(f"WebSocket 连接失败: {e}")
            self._set_state(TransportState.DISCONNECTED)
            return False

    async def disconnect(self):
        self._set_state(TransportState.CLOSING)
        self._stop_event.set()

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            self._receive_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        self._set_state(TransportState.DISCONNECTED)
        logger.info("WebSocket 已断开")

    async def send(self, data: str):
        if not self._ws or self._state != TransportState.CONNECTED:
            raise RuntimeError("WebSocket 未连接")
        try:
            await self._ws.send(data)
        except ConnectionClosed as e:
            logger.warning(f"发送时连接关闭: {e}")
            self._set_state(TransportState.DISCONNECTED)
            raise

    async def _receive_loop(self):
        while not self._stop_event.is_set() and self._ws:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=0.5)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                self._on_receive(raw)
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed as e:
                logger.warning(f"WebSocket 连接关闭: {e}")
                self._set_state(TransportState.DISCONNECTED)
                break
            except Exception as e:
                logger.error(f"接收异常: {e}")
                break

        if self._state == TransportState.CONNECTED:
            self._set_state(TransportState.DISCONNECTED)
