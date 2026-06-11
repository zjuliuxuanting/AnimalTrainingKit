"""Generic persistent integer variables for flow runtime state."""

from __future__ import annotations

import time
from typing import Dict, Optional

from .database import Database


class VariableStateStore:
    """Stores persistent integer variables by experiment/subject scope."""

    VALID_OPS = {"add", "subtract", "set"}

    def __init__(self, db: Database):
        self._db = db
        self._ensure_schema()

    def _ensure_schema(self):
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS variable_state (
                scope_id TEXT NOT NULL,
                variable_name TEXT NOT NULL,
                value INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (scope_id, variable_name)
            )"""
        )
        self._db.commit()

    def get_value(self, scope_id: str, variable_name: str, default: Optional[int] = 0) -> Optional[int]:
        scope = scope_id or "global"
        name = (variable_name or "").strip()
        if not name:
            return None if default is None else int(default)
        cursor = self._db.execute(
            "SELECT value FROM variable_state WHERE scope_id = ? AND variable_name = ?",
            (scope, name),
        )
        row = cursor.fetchone()
        if row is None:
            return None if default is None else int(default)
        return int(row["value"])

    def set_value(self, scope_id: str, variable_name: str, value: int) -> int:
        scope = scope_id or "global"
        name = (variable_name or "").strip()
        if not name:
            raise ValueError("variable_name is required")
        int_value = int(value)
        self._db.execute(
            """INSERT INTO variable_state (scope_id, variable_name, value, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(scope_id, variable_name)
               DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (scope, name, int_value, time.time()),
        )
        self._db.commit()
        return int_value

    def apply_op(self, scope_id: str, variable_name: str, op: str, value: int) -> int:
        if op not in self.VALID_OPS:
            raise ValueError(f"unknown variable op: {op}")
        current = self.get_value(scope_id, variable_name, 0)
        operand = int(value)
        if op == "add":
            next_value = current + operand
        elif op == "subtract":
            next_value = current - operand
        else:
            next_value = operand
        return self.set_value(scope_id, variable_name, next_value)

    def list_values(self, scope_id: str) -> Dict[str, int]:
        scope = scope_id or "global"
        cursor = self._db.execute(
            "SELECT variable_name, value FROM variable_state WHERE scope_id = ? ORDER BY variable_name",
            (scope,),
        )
        return {str(row["variable_name"]): int(row["value"]) for row in cursor.fetchall()}
