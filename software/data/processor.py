"""
数据处理器 — 事件清洗、去重、排序、插补/平滑

V1 必做:
- 事件清洗、去重、按时间排序
- 结构化输出：所有数据落入预定字段集合
- 丢帧/缺段处理：按配置规则插补或平滑，打「已平滑/已推断」标记
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable


@dataclass
class ProcessConfig:
    dedup_window_ms: int = 100
    max_gap_ms: int = 5000
    interpolation_strategy: str = "hold"
    sort_by: str = "ts_ms"


@dataclass
class EventRecord:
    session_id: str
    ts_ms: int
    device_ts_ms: int
    host_ts_ms: int
    event_type: str
    node_id: str = ""
    signal_id: str = ""
    actuator_id: str = ""
    trigger_type: str = ""
    action_type: str = ""
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    smoothing_flag: str = ""

    def is_smoothed(self) -> bool:
        return self.smoothing_flag in ("interpolated", "hold", "inferred")

    def to_row(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "ts_ms": self.ts_ms,
            "device_ts_ms": self.device_ts_ms,
            "host_ts_ms": self.host_ts_ms,
            "event_type": self.event_type,
            "node_id": self.node_id,
            "signal_id": self.signal_id,
            "actuator_id": self.actuator_id,
            "trigger_type": self.trigger_type,
            "action_type": self.action_type,
            "raw_payload": self.raw_payload,
            "smoothing_flag": self.smoothing_flag,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> EventRecord:
        return cls(
            session_id=row.get("session_id", ""),
            ts_ms=row.get("ts_ms", 0),
            device_ts_ms=row.get("device_ts_ms", 0),
            host_ts_ms=row.get("host_ts_ms", 0),
            event_type=row.get("event_type", ""),
            node_id=row.get("node_id", ""),
            signal_id=row.get("signal_id", ""),
            actuator_id=row.get("actuator_id", ""),
            trigger_type=row.get("trigger_type", ""),
            action_type=row.get("action_type", ""),
            raw_payload=row.get("raw_payload", {}) if isinstance(row.get("raw_payload"), dict) else {},
            smoothing_flag=row.get("smoothing_flag", ""),
        )


class DataProcessor:
    def __init__(self, config: Optional[ProcessConfig] = None):
        self._config = config or ProcessConfig()

    def process(self, events: List[Dict[str, Any]]) -> List[EventRecord]:
        records = [EventRecord.from_row(e) for e in events]
        records = self._deduplicate(records)
        records = self._sort(records)
        records = self._fill_gaps(records)
        return records

    def _deduplicate(self, records: List[EventRecord]) -> List[EventRecord]:
        window = self._config.dedup_window_ms
        if window <= 0:
            return records

        result: List[EventRecord] = []
        for r in records:
            is_dup = False
            for existing in result:
                if (
                    existing.event_type == r.event_type
                    and existing.node_id == r.node_id
                    and existing.signal_id == r.signal_id
                    and abs(existing.ts_ms - r.ts_ms) < window
                ):
                    is_dup = True
                    break
            if not is_dup:
                result.append(r)
        return result

    def _sort(self, records: List[EventRecord]) -> List[EventRecord]:
        return sorted(records, key=lambda r: r.ts_ms)

    def _fill_gaps(self, records: List[EventRecord]) -> List[EventRecord]:
        if not records or self._config.interpolation_strategy == "none":
            return records

        result: List[EventRecord] = [records[0]]
        for i in range(1, len(records)):
            gap = records[i].ts_ms - records[i - 1].ts_ms
            if gap > self._config.max_gap_ms:
                if self._config.interpolation_strategy == "hold":
                    hold = EventRecord(
                        session_id=records[i - 1].session_id,
                        ts_ms=records[i - 1].ts_ms + self._config.max_gap_ms // 2,
                        device_ts_ms=records[i - 1].device_ts_ms,
                        host_ts_ms=int(time.time() * 1000),
                        event_type="gap_hold",
                        node_id=records[i - 1].node_id,
                        signal_id=records[i - 1].signal_id,
                        smoothing_flag="hold",
                    )
                    result.append(hold)
            result.append(records[i])
        return result

    def to_structured(self, records: List[EventRecord],
                     session_id: str = "", subject_id: str = "",
                     session_name: str = "") -> List[Dict[str, Any]]:
        rows = [r.to_row() for r in records]
        # Inject session metadata and readable time
        for row in rows:
            row["session_name"] = session_name
            row["subject_id"] = subject_id
            ts = row.get("ts_ms", 0) / 1000.0
            row["time"] = time.strftime("%Y-%m-%d %H:%M:%S.", time.localtime(ts)) + f"{int((ts % 1) * 1000):03d}"
        return rows
