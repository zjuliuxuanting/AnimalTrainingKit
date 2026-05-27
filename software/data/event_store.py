"""
事件存储 — 会话事件的增删改查，与 SQLite 数据库交互
"""

from __future__ import annotations

import json
import time
from typing import Optional, Dict, Any, List
from .database import Database


class EventStore:
    def __init__(self, db: Database):
        self._db = db

    def ensure_session(self, session_id: str, name: str = "", description: str = "",
                       config_json: str = "", flow_json: str = "", experiment_id: str = ""):
        self._db.execute(
            """INSERT OR IGNORE INTO sessions (id, name, description, config_json, flow_json, created_at, experiment_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, name, description, config_json, flow_json, time.time(), experiment_id),
        )
        self._db.commit()

    def update_session_state(self, session_id: str, state: str, elapsed_ms: int = 0):
        self._db.execute(
            "UPDATE sessions SET state = ?, elapsed_ms = ?, ended_at = ? WHERE id = ?",
            (state, elapsed_ms, time.time() if state in ("completed", "error") else 0, session_id),
        )
        self._db.commit()

    def append_event(
        self,
        session_id: str,
        event_type: str,
        ts_ms: int = 0,
        device_ts_ms: int = 0,
        node_id: str = "",
        signal_id: str = "",
        actuator_id: str = "",
        trigger_type: str = "",
        action_type: str = "",
        raw_payload: Dict[str, Any] = None,
        smoothing_flag: str = "",
    ):
        self._db.execute(
            """INSERT INTO events
               (session_id, ts_ms, device_ts_ms, host_ts_ms,
                event_type, node_id, signal_id, actuator_id,
                trigger_type, action_type, raw_payload, smoothing_flag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                ts_ms or int(time.time() * 1000),
                device_ts_ms or 0,
                int(time.time() * 1000),
                event_type,
                node_id,
                signal_id,
                actuator_id,
                trigger_type,
                action_type,
                json.dumps(raw_payload or {}, ensure_ascii=False),
                smoothing_flag,
            ),
        )
        self._db.commit()

    def append_batch(self, events: List[Dict[str, Any]]):
        rows = [
            (
                e["session_id"],
                e.get("ts_ms", int(time.time() * 1000)),
                e.get("device_ts_ms", 0),
                int(time.time() * 1000),
                e["event_type"],
                e.get("node_id", ""),
                e.get("signal_id", ""),
                e.get("actuator_id", ""),
                e.get("trigger_type", ""),
                e.get("action_type", ""),
                json.dumps(e.get("raw_payload", {}), ensure_ascii=False),
                e.get("smoothing_flag", ""),
            )
            for e in events
        ]
        self._db.executemany(
            """INSERT INTO events
               (session_id, ts_ms, device_ts_ms, host_ts_ms,
                event_type, node_id, signal_id, actuator_id,
                trigger_type, action_type, raw_payload, smoothing_flag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._db.commit()

    def get_events(
        self, session_id: str, event_type: str = "", order: str = "ASC"
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM events WHERE session_id = ?"
        params: tuple = (session_id,)
        if event_type:
            sql += " AND event_type = ?"
            params = (session_id, event_type)
        sql += f" ORDER BY ts_ms {order}"

        cursor = self._db.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        cursor = self._db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_sessions(self, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = self._db.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_sessions_by_date(self, date_str: str) -> List[Dict[str, Any]]:
        """按日期获取会话列表（用于跨天对比）"""
        cursor = self._db.execute(
            """SELECT * FROM sessions
               WHERE date(created_at, 'unixepoch') = ?
               ORDER BY created_at""",
            (date_str,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_sessions_by_experiment(self, experiment_id: str) -> List[Dict[str, Any]]:
        cursor = self._db.execute(
            "SELECT * FROM sessions WHERE experiment_id = ? ORDER BY created_at DESC",
            (experiment_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_daily_aggregation(
        self, event_type: str, days: int = 7
    ) -> List[Dict[str, Any]]:
        """按天聚合事件统计（用于跨天对比图表）。event_type 为空时统计所有类型"""
        if event_type:
            cursor = self._db.execute(
                """SELECT
                     date(e.host_ts_ms / 1000, 'unixepoch') as day,
                     e.session_id,
                     COUNT(*) as event_count
                   FROM events e
                   WHERE e.event_type = ?
                     AND date(e.host_ts_ms / 1000, 'unixepoch') >= date('now', ?)
                   GROUP BY day, e.session_id
                   ORDER BY day""",
                (event_type, f"-{days} days"),
            )
        else:
            cursor = self._db.execute(
                """SELECT
                     date(e.host_ts_ms / 1000, 'unixepoch') as day,
                     e.session_id,
                     COUNT(*) as event_count
                   FROM events e
                   WHERE date(e.host_ts_ms / 1000, 'unixepoch') >= date('now', ?)
                   GROUP BY day, e.session_id
                   ORDER BY day""",
                (f"-{days} days",),
            )
        return [dict(row) for row in cursor.fetchall()]

    def log_device_state(self, session_id: str, device_state: str, details: str = ""):
        self._db.execute(
            "INSERT INTO device_status_log (session_id, ts_ms, device_state, details) VALUES (?, ?, ?, ?)",
            (session_id, int(time.time() * 1000), device_state, details),
        )
        self._db.commit()

    def get_device_state_log(
        self, session_id: str
    ) -> List[Dict[str, Any]]:
        cursor = self._db.execute(
            "SELECT * FROM device_status_log WHERE session_id = ? ORDER BY ts_ms",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_session(self, session_id: str):
        self._db.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
        self._db.execute("DELETE FROM device_status_log WHERE session_id = ?", (session_id,))
        self._db.execute("DELETE FROM video_frames WHERE session_id = ?", (session_id,))
        self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._db.commit()
