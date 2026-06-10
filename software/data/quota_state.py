"""Minimal persistent quota state for daily feeding flows."""

from __future__ import annotations

import time
from typing import Any, Dict

from .database import Database


class QuotaStateStore:
    """Stores one small quota record per experiment/subject scope."""

    def __init__(self, db: Database):
        self._db = db
        self._ensure_schema()

    def _ensure_schema(self):
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS quota_state (
                scope_id TEXT PRIMARY KEY,
                feeds_today INTEGER NOT NULL DEFAULT 0,
                daily_quota_count INTEGER NOT NULL DEFAULT 0,
                quota_locked INTEGER NOT NULL DEFAULT 0,
                cooldown_until REAL NOT NULL DEFAULT 0,
                day_index INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            )"""
        )
        self._db.commit()

    def get_state(
        self,
        scope_id: str,
        daily_quota_count: int | None = None,
        now: float | None = None,
    ) -> Dict[str, Any]:
        scope = scope_id or "global"
        now_ts = time.time() if now is None else now
        self._ensure_row(scope, daily_quota_count=daily_quota_count, now=now_ts)

        row = self._fetch(scope)
        if row is None:
            raise RuntimeError(f"quota state missing for {scope}")

        state = self._row_to_state(row)
        quota = self._coerce_quota(daily_quota_count, state["daily_quota_count"])
        if quota != state["daily_quota_count"]:
            state["daily_quota_count"] = quota
            self._save(scope, state, now_ts)

        if self._cooldown_expired(state, now_ts):
            state["feeds_today"] = 0
            state["quota_locked"] = False
            state["cooldown_until"] = 0
            state["day_index"] += 1
            self._save(scope, state, now_ts)

        return dict(state)

    def get_value(
        self,
        scope_id: str,
        source: str,
        daily_quota_count: int | None = None,
        now: float | None = None,
    ) -> int:
        now_ts = time.time() if now is None else now
        state = self.get_state(scope_id, daily_quota_count=daily_quota_count, now=now_ts)
        quota = self._coerce_quota(daily_quota_count, state["daily_quota_count"])
        if source == "feeds_today":
            return state["feeds_today"]
        if source == "daily_quota_count":
            return quota
        if source == "quota_locked":
            return 1 if self._is_locked(state, now_ts) else 0
        if source == "quota_available":
            return 1 if (not self._is_locked(state, now_ts) and state["feeds_today"] < quota) else 0
        if source == "quota_reached":
            return 1 if state["feeds_today"] >= quota else 0
        if source == "cooldown_remaining_s":
            return max(0, int(round(state["cooldown_until"] - now_ts)))
        if source == "day_index":
            return state["day_index"]
        return 0

    def apply_record_op(
        self,
        scope_id: str,
        state_op: str,
        daily_quota_count: int | None = None,
        cooldown_s: float | None = None,
        now: float | None = None,
    ) -> Dict[str, Any]:
        now_ts = time.time() if now is None else now
        state = self.get_state(scope_id, daily_quota_count=daily_quota_count, now=now_ts)
        quota = self._coerce_quota(daily_quota_count, state["daily_quota_count"])
        state["daily_quota_count"] = quota

        if state_op == "feed_success":
            if not self._is_locked(state, now_ts) and state["feeds_today"] < quota:
                state["feeds_today"] += 1
        elif state_op == "start_cooldown":
            state["quota_locked"] = True
            cooldown = float(cooldown_s or 0)
            if cooldown <= 0:
                cooldown = 20 * 60 * 60
            state["cooldown_until"] = now_ts + cooldown
        elif state_op == "new_day_reset":
            already_reset = (
                state["feeds_today"] == 0
                and not state["quota_locked"]
                and state["cooldown_until"] == 0
            )
            state["feeds_today"] = 0
            state["quota_locked"] = False
            state["cooldown_until"] = 0
            if not already_reset:
                state["day_index"] += 1
        elif not state_op:
            return dict(state)
        else:
            raise ValueError(f"unknown quota state op: {state_op}")

        self._save(scope_id or "global", state, now_ts)
        return dict(state)

    def _ensure_row(self, scope_id: str, daily_quota_count: int | None, now: float):
        quota = self._coerce_quota(daily_quota_count, 0)
        self._db.execute(
            """INSERT OR IGNORE INTO quota_state
               (scope_id, feeds_today, daily_quota_count, quota_locked,
                cooldown_until, day_index, updated_at)
               VALUES (?, 0, ?, 0, 0, 1, ?)""",
            (scope_id, quota, now),
        )
        self._db.commit()

    def _fetch(self, scope_id: str):
        cursor = self._db.execute("SELECT * FROM quota_state WHERE scope_id = ?", (scope_id,))
        return cursor.fetchone()

    def _save(self, scope_id: str, state: Dict[str, Any], now: float):
        self._db.execute(
            """UPDATE quota_state
               SET feeds_today = ?, daily_quota_count = ?, quota_locked = ?,
                   cooldown_until = ?, day_index = ?, updated_at = ?
               WHERE scope_id = ?""",
            (
                int(state["feeds_today"]),
                int(state["daily_quota_count"]),
                1 if state["quota_locked"] else 0,
                float(state["cooldown_until"]),
                int(state["day_index"]),
                now,
                scope_id,
            ),
        )
        self._db.commit()

    @staticmethod
    def _coerce_quota(value: int | None, fallback: int) -> int:
        try:
            quota = int(value) if value is not None and value != "" else int(fallback)
        except (TypeError, ValueError):
            quota = int(fallback or 0)
        return max(1, quota)

    @staticmethod
    def _row_to_state(row) -> Dict[str, Any]:
        return {
            "feeds_today": int(row["feeds_today"]),
            "daily_quota_count": int(row["daily_quota_count"]),
            "quota_locked": bool(row["quota_locked"]),
            "cooldown_until": float(row["cooldown_until"] or 0),
            "day_index": int(row["day_index"]),
        }

    @staticmethod
    def _is_locked(state: Dict[str, Any], now: float) -> bool:
        return bool(state["quota_locked"]) and state["cooldown_until"] > now

    @classmethod
    def _cooldown_expired(cls, state: Dict[str, Any], now: float) -> bool:
        return bool(state["quota_locked"]) and state["cooldown_until"] > 0 and state["cooldown_until"] <= now
