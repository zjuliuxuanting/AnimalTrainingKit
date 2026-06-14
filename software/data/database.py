"""
SQLite 数据库管理

提供数据库初始化、连接管理和 schema 迁移。
所有会话数据、事件日志、配置信息均落盘到 SQLite。
"""

from __future__ import annotations

import os
import sqlite3
import logging
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("BehaviorBox.Database")

SCHEMA_VERSION = 3

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    state TEXT DEFAULT 'idle',
    config_json TEXT DEFAULT '{}',
    flow_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    started_at REAL DEFAULT 0,
    ended_at REAL DEFAULT 0,
    elapsed_ms INTEGER DEFAULT 0,
    event_count INTEGER DEFAULT 0,
    experiment_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    device_ts_ms INTEGER,
    host_ts_ms INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    node_id TEXT DEFAULT '',
    signal_id TEXT DEFAULT '',
    actuator_id TEXT DEFAULT '',
    trigger_type TEXT DEFAULT '',
    action_type TEXT DEFAULT '',
    raw_payload TEXT DEFAULT '{}',
    smoothing_flag TEXT DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(session_id, ts_ms);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(session_id, event_type);

CREATE TABLE IF NOT EXISTS device_status_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    device_state TEXT NOT NULL,
    details TEXT DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS video_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    frame_index INTEGER NOT NULL,
    ts_ms INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_video_frames_session ON video_frames(session_id, ts_ms);

CREATE TABLE IF NOT EXISTS trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    experiment_id TEXT DEFAULT '',
    ts_ms INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    zone_name TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_trajectories_session ON trajectories(session_id, ts_ms);
"""


class Database:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def path(self) -> str:
        return self._db_path

    def open(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._migrate()
        logger.info(f"数据库已打开: {self._db_path}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("数据库已关闭")

    def _migrate(self):
        current = self._get_schema_version()
        if current < SCHEMA_VERSION:
            logger.info(f"数据库迁移: v{current} -> v{SCHEMA_VERSION}")
            self._conn.executescript(SCHEMA_DDL)
            # Migration v1→v2: add experiment_id column
            if current < 2:
                try:
                    self._conn.execute("ALTER TABLE sessions ADD COLUMN experiment_id TEXT DEFAULT ''")
                except sqlite3.OperationalError:
                    pass  # column already exists
            if current < 3:
                try:
                    self._conn.executescript("""
CREATE TABLE IF NOT EXISTS trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    experiment_id TEXT DEFAULT '',
    ts_ms INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    zone_name TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trajectories_session ON trajectories(session_id, ts_ms);
""")
                except sqlite3.OperationalError:
                    pass
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_version VALUES (?)",
                (SCHEMA_VERSION,),
            )
            self._conn.commit()
            logger.info("数据库迁移完成")

    def _get_schema_version(self) -> int:
        try:
            cursor = self._conn.execute("SELECT MAX(version) FROM schema_version")
            row = cursor.fetchone()
            return row[0] if row and row[0] else 0
        except sqlite3.OperationalError:
            return 0

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def executemany(self, sql: str, params_list: List[tuple]):
        self._conn.executemany(sql, params_list)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
