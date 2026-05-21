"""
设备管理器 — 设备发现、连接生命周期、心跳监控、命令收发

基于 V1_设备协议规范 v0.3 的状态语义:
- online: 心跳正常
- suspect: 连续 >=2000ms 未收到心跳
- offline: 连续 >=3000ms 未收到心跳（断连安全态）
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List
from enum import Enum

from .transport import TransportBase, TransportState, TransportConfig
from .ws_transport import WsTransport
from .ble_transport import BleTransport, discover_devices as ble_discover, BleDiscoveryResult
from .messages import (
    Envelope, MsgType, CmdKind, EventKind, ErrorCode,
    SeqGenerator, BootId, host_ts_ms,
    build_cmd_envelope, build_heartbeat_envelope,
    EventMessage, ErrorMessage, RespMessage,
)

logger = logging.getLogger("BehaviorBox.DeviceManager")


class DeviceState(str, Enum):
    OFFLINE = "offline"
    SUSPECT = "suspect"
    ONLINE = "online"


@dataclass
class DeviceInfo:
    device_id: str
    name: str = ""
    transport_type: str = "ws"
    host: str = ""
    port: int = 0
    ble_address: str = ""


@dataclass
class DeviceStatus:
    device_id: str
    state: DeviceState
    boot_id: str = ""
    last_heartbeat_ms: int = 0
    connected_since_ms: int = 0
    session_active: bool = False
    session_id: str = ""


class DeviceManager:
    """
    设备管理器 — 管理单个设备的完整生命周期

    职责:
    1. 通过 Wi-Fi (WebSocket) 或 BLE 连接 ESP32 Hub
    2. 维持心跳: 1000ms 周期发送，监控接收，判定 online/suspect/offline
    3. 收发协议消息（命令/事件/响应/错误）
    4. 断连安全态: 检测到 offline 后，发送安全态通知
    """

    def __init__(self, config: Optional[TransportConfig] = None):
        self._config = config or TransportConfig()
        self._transport: Optional[TransportBase] = None
        self._state: DeviceState = DeviceState.OFFLINE
        self._device_id: str = ""
        self._boot_id: str = ""
        self._seq_gen = SeqGenerator()
        self._last_heartbeat_recv_ms: int = 0
        self._connected_at_ms: int = 0

        self._on_event: Optional[Callable[[EventMessage], None]] = None
        self._on_error: Optional[Callable[[ErrorMessage], None]] = None
        self._on_resp: Optional[Callable[[RespMessage], None]] = None
        self._on_state_change: Optional[Callable[[DeviceState, DeviceState], None]] = None
        self._on_safe_state: Optional[Callable[[], None]] = None

        self._heartbeat_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._pending_commands: Dict[int, asyncio.Future] = {}

    @property
    def state(self) -> DeviceState:
        return self._state

    @property
    def is_online(self) -> bool:
        return self._state == DeviceState.ONLINE

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def boot_id(self) -> str:
        return self._boot_id

    def set_callbacks(
        self,
        on_event: Optional[Callable[[EventMessage], None]] = None,
        on_error: Optional[Callable[[ErrorMessage], None]] = None,
        on_resp: Optional[Callable[[RespMessage], None]] = None,
        on_state_change: Optional[Callable[[DeviceState, DeviceState], None]] = None,
        on_safe_state: Optional[Callable[[], None]] = None,
    ):
        self._on_event = on_event
        self._on_error = on_error
        self._on_resp = on_resp
        self._on_state_change = on_state_change
        self._on_safe_state = on_safe_state

    def _set_state(self, new_state: DeviceState):
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        logger.info(f"设备状态变更: {old.value} -> {new_state.value}")
        if self._on_state_change:
            try:
                self._on_state_change(old, new_state)
            except Exception:
                logger.exception("on_state_change error")

        if new_state == DeviceState.OFFLINE:
            self._enter_safe_state()

    def _enter_safe_state(self):
        logger.warning("进入安全态：设备离线，释放所有待执行命令")
        for seq, future in list(self._pending_commands.items()):
            if not future.done():
                future.set_exception(RuntimeError("设备离线"))
            del self._pending_commands[seq]
        if self._on_safe_state:
            try:
                self._on_safe_state()
            except Exception:
                logger.exception("on_safe_state error")

    async def connect_ws(self, info: DeviceInfo) -> bool:
        self._device_id = info.device_id
        transport = WsTransport(
            TransportConfig(
                host=info.host or "192.168.4.1",
                port=info.port or 8080,
                timeout=self._config.timeout,
                heartbeat_interval_ms=self._config.heartbeat_interval_ms,
                offline_threshold_ms=self._config.offline_threshold_ms,
                suspect_threshold_ms=self._config.suspect_threshold_ms,
            )
        )
        return await self._connect(transport)

    async def connect_ble(self, info: DeviceInfo) -> bool:
        self._device_id = info.device_id
        transport = BleTransport(
            address=info.ble_address,
            config=self._config,
        )
        return await self._connect(transport)

    async def _connect(self, transport: TransportBase) -> bool:
        self._transport = transport
        transport.set_callbacks(
            on_message=self._on_raw_message,
            on_state_change=self._on_transport_state_change,
        )

        if not await transport.connect():
            return False

        self._connected_at_ms = host_ts_ms()
        self._seq_gen.reset(self._device_id)

        ping_seq = self._seq_gen.next(self._device_id)
        ping_env = build_cmd_envelope(
            self._device_id, self._boot_id, ping_seq, CmdKind.PING
        )
        await transport.send(ping_env.to_json())

        self._boot_id = BootId.generate()
        self._last_heartbeat_recv_ms = host_ts_ms()
        self._set_state(DeviceState.ONLINE)

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        return True

    async def disconnect(self):
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None
        if self._transport:
            await self._transport.stop()
            self._transport = None
        self._set_state(DeviceState.OFFLINE)

    async def send_cmd(
        self, cmd: CmdKind, payload: Optional[Dict[str, Any]] = None
    ) -> RespMessage:
        if not self._transport or not self._transport.is_connected:
            raise RuntimeError("设备未连接")

        seq = self._seq_gen.next(self._device_id)
        env = build_cmd_envelope(self._device_id, self._boot_id, seq, cmd, payload)
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_commands[seq] = future

        try:
            await self._transport.send(env.to_json())
            resp = await asyncio.wait_for(future, timeout=self._config.timeout)
            return resp
        except asyncio.TimeoutError:
            self._pending_commands.pop(seq, None)
            raise RuntimeError(f"命令 {cmd.value} 超时 (seq={seq})")
        except Exception:
            self._pending_commands.pop(seq, None)
            raise

    async def start_session(self, session_id: str, config: Dict[str, Any] = None) -> bool:
        resp = await self.send_cmd(
            CmdKind.START_SESSION,
            {"session_id": session_id, "config": config or {}},
        )
        return resp.ok

    async def stop_session(self, session_id: str) -> bool:
        resp = await self.send_cmd(
            CmdKind.STOP_SESSION,
            {"session_id": session_id},
        )
        return resp.ok

    async def set_rule(self, session_id: str, rule: Dict[str, Any]) -> bool:
        resp = await self.send_cmd(
            CmdKind.SET_RULE,
            {"session_id": session_id, "rule": rule},
        )
        return resp.ok

    async def query_status(self) -> Dict[str, Any]:
        resp = await self.send_cmd(CmdKind.QUERY_STATUS)
        return resp.envelope.payload

    async def ping(self) -> bool:
        resp = await self.send_cmd(CmdKind.PING)
        return resp.ok

    async def _heartbeat_loop(self):
        interval = self._config.heartbeat_interval_ms / 1000.0
        while self._transport and self._transport.is_connected:
            try:
                seq = self._seq_gen.next(self._device_id)
                env = build_heartbeat_envelope(self._device_id, self._boot_id, seq)
                await self._transport.send(env.to_json())
            except Exception:
                logger.exception("心跳发送失败")
            await asyncio.sleep(interval)

    async def _monitor_loop(self):
        suspect_ms = self._config.suspect_threshold_ms
        offline_ms = self._config.offline_threshold_ms

        while self._transport and self._state != DeviceState.OFFLINE:
            now = host_ts_ms()
            elapsed = now - self._last_heartbeat_recv_ms

            if elapsed >= offline_ms:
                logger.warning(f"心跳超时 {elapsed}ms，设备离线")
                self._set_state(DeviceState.OFFLINE)
                break
            elif elapsed >= suspect_ms and self._state == DeviceState.ONLINE:
                logger.warning(f"心跳延迟 {elapsed}ms，设备标记为 suspect")
                self._set_state(DeviceState.SUSPECT)
            elif elapsed < suspect_ms and self._state == DeviceState.SUSPECT:
                self._set_state(DeviceState.ONLINE)

            await asyncio.sleep(0.5)

    def _on_raw_message(self, raw: str):
        try:
            env = Envelope.from_json(raw)
        except Exception as e:
            logger.error(f"消息解析失败: {e}")
            return

        host_now = host_ts_ms()
        if env.host_rx_ts_ms is None:
            env.host_rx_ts_ms = host_now

        if env.msg_type == MsgType.HEARTBEAT:
            self._last_heartbeat_recv_ms = host_now
            if env.boot_id and env.boot_id != self._boot_id:
                self._boot_id = env.boot_id
                logger.info(f"设备重启，新 boot_id: {env.boot_id}")
            return

        if env.msg_type == MsgType.EVENT:
            event_msg = EventMessage(env)
            if self._on_event:
                try:
                    self._on_event(event_msg)
                except Exception:
                    logger.exception("on_event error")
            return

        if env.msg_type == MsgType.ERROR:
            error_msg = ErrorMessage(env)
            if self._on_error:
                try:
                    self._on_error(error_msg)
                except Exception:
                    logger.exception("on_error error")
            return

        if env.msg_type == MsgType.RESP:
            resp_msg = RespMessage(env)
            ack_seq = resp_msg.ack_seq
            if ack_seq is not None and ack_seq in self._pending_commands:
                future = self._pending_commands.pop(ack_seq)
                if not future.done():
                    future.set_result(resp_msg)
            if self._on_resp:
                try:
                    self._on_resp(resp_msg)
                except Exception:
                    logger.exception("on_resp error")

    def _on_transport_state_change(self, old: TransportState, new: TransportState):
        if new == TransportState.DISCONNECTED and self._state != DeviceState.OFFLINE:
            logger.warning("传输层断开，等待监控判定")
            self._last_heartbeat_recv_ms = 0

    def get_status(self) -> DeviceStatus:
        return DeviceStatus(
            device_id=self._device_id,
            state=self._state,
            boot_id=self._boot_id,
            last_heartbeat_ms=self._last_heartbeat_recv_ms,
            connected_since_ms=self._connected_at_ms,
        )

    @staticmethod
    async def discover() -> List[BleDiscoveryResult]:
        return await ble_discover()
