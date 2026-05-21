"""
消息模型 — 严格遵循 V1_设备协议规范 v0.3

协议规范文件: PM/V1_设备协议规范.md
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any, List


PROTOCOL_VERSION = "v0.3"


class MsgType(str, Enum):
    CMD = "cmd"
    EVENT = "event"
    RESP = "resp"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class CmdKind(str, Enum):
    START_SESSION = "start_session"
    STOP_SESSION = "stop_session"
    SET_RULE = "set_rule"
    QUERY_STATUS = "query_status"
    PING = "ping"


class EventKind(str, Enum):
    INPUT_TRIGGERED = "input_triggered"
    OUTPUT_EXECUTED = "output_executed"
    STATE_CHANGED = "state_changed"
    SESSION_STARTED = "session_started"
    SESSION_STOPPED = "session_stopped"


class ErrorCode(str, Enum):
    PROTO_BAD_PAYLOAD = "PROTO_BAD_PAYLOAD"
    PROTO_UNKNOWN_CMD = "PROTO_UNKNOWN_CMD"
    STATE_SESSION_NOT_RUNNING = "STATE_SESSION_NOT_RUNNING"
    STATE_DEVICE_BUSY = "STATE_DEVICE_BUSY"
    STATE_CONFLICT = "STATE_CONFLICT"
    IO_ACTUATOR_TIMEOUT = "IO_ACTUATOR_TIMEOUT"
    IO_SENSOR_FAULT = "IO_SENSOR_FAULT"


class ConnectionState(str, Enum):
    ONLINE = "online"
    SUSPECT = "suspect"
    OFFLINE = "offline"


@dataclass
class Envelope:
    """通用消息信封"""
    msg_type: MsgType
    device_id: str
    ts_ms: int
    seq: int
    boot_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    protocol_ver: str = PROTOCOL_VERSION
    device_ts_ms: Optional[int] = None
    host_rx_ts_ms: Optional[int] = None
    ack_seq: Optional[int] = None

    def to_json(self) -> str:
        d = {
            "msg_type": self.msg_type.value,
            "device_id": self.device_id,
            "ts_ms": self.ts_ms,
            "seq": self.seq,
            "boot_id": self.boot_id,
            "payload": self.payload,
            "protocol_ver": self.protocol_ver,
        }
        if self.device_ts_ms is not None:
            d["device_ts_ms"] = self.device_ts_ms
        if self.host_rx_ts_ms is not None:
            d["host_rx_ts_ms"] = self.host_rx_ts_ms
        if self.ack_seq is not None:
            d["ack_seq"] = self.ack_seq
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Envelope:
        data = json.loads(raw)
        return cls(
            msg_type=MsgType(data["msg_type"]),
            device_id=data["device_id"],
            ts_ms=data["ts_ms"],
            seq=data["seq"],
            boot_id=data["boot_id"],
            payload=data.get("payload", {}),
            protocol_ver=data.get("protocol_ver", PROTOCOL_VERSION),
            device_ts_ms=data.get("device_ts_ms"),
            host_rx_ts_ms=data.get("host_rx_ts_ms"),
            ack_seq=data.get("ack_seq"),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Envelope:
        return cls(
            msg_type=MsgType(data["msg_type"]),
            device_id=data["device_id"],
            ts_ms=data["ts_ms"],
            seq=data["seq"],
            boot_id=data["boot_id"],
            payload=data.get("payload", {}),
            protocol_ver=data.get("protocol_ver", PROTOCOL_VERSION),
            device_ts_ms=data.get("device_ts_ms"),
            host_rx_ts_ms=data.get("host_rx_ts_ms"),
            ack_seq=data.get("ack_seq"),
        )


@dataclass
class CmdMessage:
    """命令消息"""

    device_id: str
    boot_id: str
    seq: int
    cmd: CmdKind
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_envelope(self) -> Envelope:
        return Envelope(
            msg_type=MsgType.CMD,
            device_id=self.device_id,
            boot_id=self.boot_id,
            seq=self.seq,
            ts_ms=int(time.time() * 1000),
            payload={"cmd": self.cmd.value, **self.payload},
            host_rx_ts_ms=int(time.time() * 1000),
        )


@dataclass
class EventMessage:
    """从设备上报的事件消息"""

    envelope: Envelope

    @property
    def event_kind(self) -> EventKind:
        return EventKind(self.envelope.payload.get("event", ""))

    @property
    def session_id(self) -> Optional[str]:
        return self.envelope.payload.get("session_id")

    @property
    def event_data(self) -> Dict[str, Any]:
        return self.envelope.payload.get("data", {})


@dataclass
class ErrorMessage:
    """错误消息"""

    envelope: Envelope

    @property
    def code(self) -> str:
        return self.envelope.payload.get("code", "UNKNOWN")

    @property
    def message(self) -> str:
        return self.envelope.payload.get("message", "")

    @property
    def retryable(self) -> bool:
        return self.envelope.payload.get("retryable", False)


@dataclass
class RespMessage:
    """响应消息，必须包含 ack_seq 指向被响应命令的 seq"""

    envelope: Envelope

    @property
    def ack_seq(self) -> Optional[int]:
        return self.envelope.ack_seq

    @property
    def ok(self) -> bool:
        return self.envelope.payload.get("ok", False)


class SeqGenerator:
    """按 device_id 单调递增的序列号生成器（单设备单线程安全）"""

    def __init__(self):
        self._counters: Dict[str, int] = {}

    def next(self, device_id: str) -> int:
        current = self._counters.get(device_id, 0)
        current += 1
        self._counters[device_id] = current
        return current

    def reset(self, device_id: str):
        self._counters[device_id] = 0


class BootId:
    """设备启动实例标识"""

    @staticmethod
    def generate() -> str:
        return uuid.uuid4().hex[:16]


def host_ts_ms() -> int:
    return int(time.time() * 1000)


def build_cmd_envelope(
    device_id: str,
    boot_id: str,
    seq: int,
    cmd: CmdKind,
    payload: Optional[Dict[str, Any]] = None,
) -> Envelope:
    return Envelope(
        msg_type=MsgType.CMD,
        device_id=device_id,
        boot_id=boot_id,
        seq=seq,
        ts_ms=host_ts_ms(),
        payload={"cmd": cmd.value, **(payload or {})},
        host_rx_ts_ms=host_ts_ms(),
    )


def build_heartbeat_envelope(device_id: str, boot_id: str, seq: int) -> Envelope:
    return Envelope(
        msg_type=MsgType.HEARTBEAT,
        device_id=device_id,
        boot_id=boot_id,
        seq=seq,
        ts_ms=host_ts_ms(),
        host_rx_ts_ms=host_ts_ms(),
    )
