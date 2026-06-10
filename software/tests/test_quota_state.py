"""Sprint v1.1.3: daily quota persistent state tests."""

import asyncio
import time


def _node(nid, node_type, params=None):
    from session.flow_model import FlowNode, NodeType

    return FlowNode(id=nid, node_type=NodeType(node_type), label=nid, params=params or {})


def _edge(src, sport, dst):
    from session.flow_model import Edge, NodePort, PortDirection

    return Edge(
        id=f"e_{src}_{sport}_{dst}",
        source=NodePort(src, sport, PortDirection.OUT),
        target=NodePort(dst, "in", PortDirection.IN),
    )


def test_quota_state_persists_and_unlocks_after_cooldown(tmp_path):
    """Quota state survives db reopen and resets after cooldown expires."""
    from data.database import Database
    from data.quota_state import QuotaStateStore

    db_path = str(tmp_path / "quota.db")
    db = Database(db_path)
    db.open()
    store = QuotaStateStore(db)

    for _ in range(3):
        store.apply_record_op("exp-a", "feed_success", daily_quota_count=3)
    locked = store.apply_record_op(
        "exp-a",
        "start_cooldown",
        daily_quota_count=3,
        cooldown_s=0.2,
    )
    assert locked["feeds_today"] == 3
    assert locked["daily_quota_count"] == 3
    assert locked["quota_locked"] is True
    assert locked["cooldown_until"] > time.time()
    db.close()

    reopened = Database(db_path)
    reopened.open()
    reopened_store = QuotaStateStore(reopened)
    still_locked = reopened_store.get_state("exp-a")
    assert still_locked["feeds_today"] == 3
    assert still_locked["quota_locked"] is True

    time.sleep(0.25)
    unlocked = reopened_store.get_state("exp-a")
    assert unlocked["feeds_today"] == 0
    assert unlocked["quota_locked"] is False
    assert unlocked["cooldown_until"] == 0
    assert unlocked["day_index"] == 2
    reopened.close()


def test_engine_record_writes_quota_and_condition_blocks_fourth_feed(tmp_path):
    """RECORD writes quota state; CONDITION reads it and prevents extra food."""
    from data.database import Database
    from data.quota_state import QuotaStateStore
    from protocol.signal_source import SignalEvent, SourceType
    from session.engine import Engine
    from session.flow_model import FlowGraph
    from session.session import ExperimentConfig, Session

    db = Database(str(tmp_path / "quota_engine.db"))
    db.open()
    quota_store = QuotaStateStore(db)

    graph = FlowGraph(id="quota-flow", name="daily-quota")
    for node in [
        _node("start", "start"),
        _node("quota_available", "condition", {
            "source": "quota_available", "operator": "eq", "value": 1,
            "daily_quota_count": 3,
        }),
        _node("lever", "trigger", {"signal_id": "mock:default"}),
        _node("feed", "execute", {"actuator_id": "actuator:feeder", "action": "high"}),
        _node("record_feed", "record", {
            "event_name": "投喂成功",
            "state_op": "feed_success",
            "daily_quota_count": 3,
        }),
        _node("quota_reached", "condition", {
            "source": "quota_reached", "operator": "eq", "value": 1,
            "daily_quota_count": 3,
        }),
        _node("record_continue", "record", {"event_name": "继续等待"}),
        _node("record_cooldown", "record", {
            "event_name": "开始冷却",
            "state_op": "start_cooldown",
            "daily_quota_count": 3,
            "cooldown_s": 20,
        }),
        _node("merge", "record", {"event_name": "配额检查完成"}),
        _node("loop", "loop", {"max_iterations": 10, "timeout_s": 30}),
        _node("end", "end"),
    ]:
        graph.add_node(node)

    for edge in [
        _edge("start", "out", "quota_available"),
        _edge("quota_available", "true", "lever"),
        _edge("quota_available", "false", "end"),
        _edge("lever", "out", "feed"),
        _edge("feed", "out", "record_feed"),
        _edge("record_feed", "out", "quota_reached"),
        _edge("quota_reached", "false", "record_continue"),
        _edge("quota_reached", "true", "record_cooldown"),
        _edge("record_continue", "out", "merge"),
        _edge("record_cooldown", "out", "merge"),
        _edge("merge", "out", "loop"),
        _edge("loop", "body", "quota_available"),
        _edge("loop", "exit", "end"),
    ]:
        graph.add_edge(edge)

    actions = []
    engine_events = []

    async def run_test():
        engine = Engine()
        engine.set_quota_state_store(quota_store, "exp-a")
        engine.set_send_action(lambda cmd: _capture_action(cmd, actions))
        engine.set_on_engine_event(lambda kind, data: engine_events.append((kind, data)))

        session = Session()
        session.load(ExperimentConfig(name="quota-test", flow=graph))
        await engine.start(session)
        await asyncio.sleep(0.05)

        for _ in range(4):
            signal = SignalEvent(
                source_id="mock:0",
                source_type=SourceType.MOCK,
                signal_id="mock:default",
                ts_ms=int(time.time() * 1000),
                value=1,
                data={},
            )
            await engine.feed_signal(signal)
            await asyncio.sleep(0.1)

        await engine.stop()

    async def _capture_action(cmd, bucket):
        bucket.append(cmd)
        return True

    asyncio.run(run_test())

    state = quota_store.get_state("exp-a")
    assert len(actions) == 3
    assert state["feeds_today"] == 3
    assert state["daily_quota_count"] == 3
    assert state["quota_locked"] is True
    assert state["cooldown_until"] > time.time()

    record_events = [
        data for kind, data in engine_events
        if kind == "node_executed" and data.get("type") == "record"
    ]
    assert len(record_events) >= 3
    assert any(e.get("quota_state", {}).get("feeds_today") == 3 for e in record_events)
    assert any(data.get("node_id") == "quota_reached" for kind, data in engine_events)

    db.close()


def test_new_day_reset_is_idempotent_after_auto_unlock(tmp_path):
    """Explicit reset after expired cooldown must not skip a day index."""
    from data.database import Database
    from data.quota_state import QuotaStateStore

    db = Database(str(tmp_path / "quota_reset.db"))
    db.open()
    store = QuotaStateStore(db)

    store.apply_record_op("exp-a", "feed_success", daily_quota_count=3, now=100.0)
    store.apply_record_op("exp-a", "start_cooldown", daily_quota_count=3, cooldown_s=10, now=101.0)
    auto_unlocked = store.get_state("exp-a", daily_quota_count=3, now=112.0)
    assert auto_unlocked["day_index"] == 2

    reset_again = store.apply_record_op("exp-a", "new_day_reset", daily_quota_count=3, now=113.0)
    assert reset_again["feeds_today"] == 0
    assert reset_again["quota_locked"] is False
    assert reset_again["day_index"] == 2

    db.close()


def test_validator_accepts_quota_sources_and_rejects_bad_state_op():
    from session.flow_model import FlowGraph
    from session.validator import validate_flow

    graph = FlowGraph(id="quota-validate", name="quota-validate")
    for node in [
        _node("start", "start"),
        _node("quota_available", "condition", {
            "source": "quota_available",
            "operator": "eq",
            "value": 1,
            "daily_quota_count": 3,
        }),
        _node("trigger", "trigger", {"signal_id": "mock:default"}),
        _node("record_feed", "record", {
            "event_name": "投喂成功",
            "state_op": "feed_success",
            "daily_quota_count": 3,
        }),
        _node("end", "end"),
    ]:
        graph.add_node(node)
    for edge in [
        _edge("start", "out", "quota_available"),
        _edge("quota_available", "true", "trigger"),
        _edge("quota_available", "false", "end"),
        _edge("trigger", "out", "record_feed"),
        _edge("record_feed", "out", "end"),
    ]:
        graph.add_edge(edge)

    ok = validate_flow(graph, available_signals=["mock:default"])
    assert ok.valid, ok.errors

    graph.nodes["record_feed"].params["state_op"] = "bad_op"
    bad = validate_flow(graph, available_signals=["mock:default"])
    assert not bad.valid
    assert any("state_op" in err for err in bad.errors)

    graph.nodes["record_feed"].params["state_op"] = "feed_success"
    graph.nodes["record_feed"].params["counter_op"] = "inc"
    bad_counter = validate_flow(graph, available_signals=["mock:default"])
    assert not bad_counter.valid
    assert any("counter_op" in err for err in bad_counter.errors)
