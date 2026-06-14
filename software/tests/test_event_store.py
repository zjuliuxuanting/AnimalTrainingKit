"""
测试 event_store 事件读写。

所有测试使用 tmp_path fixture，不污染 data_store/。
"""

import pytest


@pytest.fixture
def store(tmp_path):
    """创建隔离的 Database + EventStore，跑完自动清理。"""
    from data.database import Database
    from data.event_store import EventStore
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.open()
    es = EventStore(db)
    yield es
    db.close()


class TestEventCRUD:
    def test_append_and_count(self, store):
        """追加事件 → count +1"""
        store.ensure_session("s1", name="测试会话")
        event_id = store.append_event(session_id="s1", event_type="manual", ts_ms=1000)
        events = store.get_events("s1")
        assert event_id == events[0]["id"]
        assert len(events) == 1
        assert events[0]["event_type"] == "manual"

    def test_query_by_session(self, store):
        """按 session_id 查询 → 返回该 session 的事件"""
        store.ensure_session("session-a")
        store.ensure_session("session-b")
        store.append_event(session_id="session-a", event_type="enter", ts_ms=100)
        store.append_event(session_id="session-b", event_type="leave", ts_ms=200)
        events_a = store.get_events("session-a")
        assert len(events_a) == 1
        assert events_a[0]["event_type"] == "enter"

    def test_append_multiple_events(self, store):
        """多次追加事件 → 事件数累计"""
        store.ensure_session("s-multi")
        for i in range(5):
            store.append_event(session_id="s-multi", event_type="click", ts_ms=i * 100)
        events = store.get_events("s-multi")
        assert len(events) == 5

    def test_query_by_type(self, store):
        """按事件类型筛选 → 只返回对应类型"""
        store.ensure_session("s-type")
        store.append_event(session_id="s-type", event_type="click", ts_ms=100)
        store.append_event(session_id="s-type", event_type="hold", ts_ms=200)
        store.append_event(session_id="s-type", event_type="click", ts_ms=300)
        clicks = store.get_events("s-type", event_type="click")
        assert len(clicks) == 2
        for evt in clicks:
            assert evt["event_type"] == "click"

    def test_event_fields(self, store):
        """事件字段完整性"""
        store.ensure_session("s-fields")
        store.append_event(
            session_id="s-fields",
            event_type="camera_enter",
            ts_ms=1000,
            node_id="node-1",
            signal_id="camera:zone1:enter",
            actuator_id="act-1",
            trigger_type="enter",
            action_type="feed",
            raw_payload={"zone": "zone1"},
            smoothing_flag="raw",
        )
        events = store.get_events("s-fields")
        assert len(events) == 1
        e = events[0]
        assert e["event_type"] == "camera_enter"
        assert e["node_id"] == "node-1"
        assert e["signal_id"] == "camera:zone1:enter"

    def test_delete_session(self, store):
        """清空 session 后 count = 0"""
        store.ensure_session("s-del")
        store.append_event(session_id="s-del", event_type="click", ts_ms=100)
        assert len(store.get_events("s-del")) == 1
        store.delete_session("s-del")
        # 删除后重新 ensure 得到空 session
        store.ensure_session("s-del")
        assert len(store.get_events("s-del")) == 0

    def test_get_sessions(self, store):
        """获取所有 session 列表"""
        store.ensure_session("session-1", name="会话1")
        store.ensure_session("session-2", name="会话2")
        sessions = store.get_sessions(limit=10)
        names = [s["name"] for s in sessions]
        assert "会话1" in names
        assert "会话2" in names

    def test_get_session_by_id(self, store):
        """按 ID 获取单个 session"""
        store.ensure_session("unique-session", name="唯一会话")
        sess = store.get_session("unique-session")
        assert sess is not None
        assert sess["name"] == "唯一会话"

    def test_append_batch(self, store):
        """批量追加事件"""
        store.ensure_session("s-batch")
        batch = [
            {"session_id": "s-batch", "event_type": "click", "ts_ms": i * 100}
            for i in range(3)
        ]
        store.append_batch(batch)
        assert len(store.get_events("s-batch")) == 3

    def test_session_state_update(self, store):
        """更新 session 状态"""
        store.ensure_session("s-state")
        store.update_session_state("s-state", "running")
        sess = store.get_session("s-state")
        assert sess["state"] == "running"
