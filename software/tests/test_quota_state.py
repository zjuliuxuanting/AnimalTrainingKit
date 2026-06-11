"""Generic variable model regression for the daily quota flow."""

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


def _daily_quota_graph(loop_iterations=12, cooldown_value=0):
    from session.flow_model import FlowGraph

    graph = FlowGraph(id="generic-daily-quota", name="daily-quota")
    for node in [
        _node("start", "start"),
        _node("set_quota", "record", {
            "event_name": "设置日定额",
            "variable_name": "daily_quota_count",
            "variable_op": "set",
            "variable_value": 3,
            "variable_persistent": True,
        }),
        _node("entry_merge", "record", {"event_name": "入口汇合"}),
        _node("locked", "condition", {
            "source": "variable",
            "variable_name": "quota_locked",
            "operator": "eq",
            "value": 1,
        }),
        _node("quota_left", "condition", {
            "source": "variable",
            "variable_name": "feeds_today",
            "operator": "lt",
            "compare_source": "variable",
            "compare_variable_name": "daily_quota_count",
        }),
        _node("lever", "trigger", {"signal_id": "mock:default"}),
        _node("feed", "execute", {"actuator_id": "actuator:feeder", "action": "high"}),
        _node("record_feed", "record", {
            "event_name": "投喂成功",
            "variable_name": "feeds_today",
            "variable_op": "add",
            "variable_value": 1,
            "variable_persistent": True,
        }),
        _node("quota_reached", "condition", {
            "source": "variable",
            "variable_name": "feeds_today",
            "operator": "gte",
            "compare_source": "variable",
            "compare_variable_name": "daily_quota_count",
        }),
        _node("record_continue", "record", {"event_name": "继续等待"}),
        _node("lock_quota", "record", {
            "event_name": "开始冷却",
            "variable_name": "quota_locked",
            "variable_op": "set",
            "variable_value": 1,
            "variable_persistent": True,
        }),
        _node("cooldown_delay", "delay", {
            "duration_value": cooldown_value,
            "duration_unit": "seconds",
        }),
        _node("reset_feeds", "record", {
            "event_name": "重置投喂数",
            "variable_name": "feeds_today",
            "variable_op": "set",
            "variable_value": 0,
            "variable_persistent": True,
        }),
        _node("unlock_quota", "record", {
            "event_name": "解除冷却",
            "variable_name": "quota_locked",
            "variable_op": "set",
            "variable_value": 0,
            "variable_persistent": True,
        }),
        _node("inc_day", "record", {
            "event_name": "新压缩日",
            "variable_name": "day_index",
            "variable_op": "add",
            "variable_value": 1,
            "variable_persistent": True,
        }),
        _node("merge", "record", {"event_name": "循环汇合"}),
        _node("loop", "loop", {"max_iterations": loop_iterations, "timeout_s": 60}),
        _node("end", "end"),
    ]:
        graph.add_node(node)

    for edge in [
        _edge("start", "out", "set_quota"),
        _edge("set_quota", "out", "entry_merge"),
        _edge("entry_merge", "out", "locked"),
        _edge("locked", "true", "cooldown_delay"),
        _edge("locked", "false", "quota_left"),
        _edge("quota_left", "true", "lever"),
        _edge("quota_left", "false", "lock_quota"),
        _edge("lever", "out", "feed"),
        _edge("feed", "out", "record_feed"),
        _edge("record_feed", "out", "quota_reached"),
        _edge("quota_reached", "true", "lock_quota"),
        _edge("quota_reached", "false", "record_continue"),
        _edge("record_continue", "out", "merge"),
        _edge("lock_quota", "out", "merge"),
        _edge("cooldown_delay", "out", "reset_feeds"),
        _edge("reset_feeds", "out", "unlock_quota"),
        _edge("unlock_quota", "out", "inc_day"),
        _edge("inc_day", "out", "merge"),
        _edge("merge", "out", "loop"),
        _edge("loop", "body", "entry_merge"),
        _edge("loop", "exit", "end"),
    ]:
        graph.add_edge(edge)
    return graph


def test_daily_quota_flow_uses_generic_variables_and_blocks_fourth_feed(tmp_path):
    from data.database import Database
    from data.variable_state import VariableStateStore
    from protocol.signal_source import SignalEvent, SourceType
    from session.engine import Engine
    from session.session import ExperimentConfig, Session

    db = Database(str(tmp_path / "daily_quota_variables.db"))
    db.open()
    variable_store = VariableStateStore(db)

    actions = []
    engine_events = []

    async def _capture_action(cmd):
        actions.append(cmd)
        return True

    async def run_test():
        engine = Engine()
        engine.set_variable_state_store(variable_store, "exp-a")
        engine.set_send_action(_capture_action)
        engine.set_on_engine_event(lambda kind, data: engine_events.append((kind, data)))

        session = Session()
        session.load(ExperimentConfig(name="daily-quota-test", flow=_daily_quota_graph(loop_iterations=5, cooldown_value=20)))
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
            await asyncio.sleep(0.08)

        await engine.stop()

    asyncio.run(run_test())

    assert len(actions) == 3
    assert variable_store.get_value("exp-a", "daily_quota_count") == 3
    assert variable_store.get_value("exp-a", "feeds_today") == 3
    assert variable_store.get_value("exp-a", "quota_locked") == 1

    record_events = [
        data for kind, data in engine_events
        if kind == "node_executed" and data.get("type") == "record"
    ]
    condition_events = [
        data for kind, data in engine_events
        if kind == "node_executed" and data.get("type") == "condition"
    ]
    assert sum(1 for event in record_events if event.get("node_id") == "record_feed") == 3
    assert any(event.get("node_id") == "lock_quota" and event.get("variable_result") == 1 for event in record_events)
    assert any(event.get("node_id") == "quota_reached" and event.get("result") is True for event in condition_events)

    db.close()


def test_execute_event_includes_user_friendly_actuator_label():
    from session.engine import actuator_display_name

    assert actuator_display_name("actuator:light") == "灯光"
    assert actuator_display_name("actuator:feeder") == "给食器（出粮器）"
    assert actuator_display_name("custom:port1") == "custom:port1"


def test_daily_quota_cooldown_cycle_resets_with_delay_and_day_index(tmp_path):
    from data.database import Database
    from data.variable_state import VariableStateStore
    from protocol.signal_source import SignalEvent, SourceType
    from session.engine import Engine
    from session.session import ExperimentConfig, Session

    db = Database(str(tmp_path / "daily_quota_cooldown.db"))
    db.open()
    variable_store = VariableStateStore(db)

    actions = []

    async def _capture_action(cmd):
        actions.append(cmd)
        return True

    async def run_test():
        engine = Engine()
        engine.set_variable_state_store(variable_store, "exp-a")
        engine.set_send_action(_capture_action)

        session = Session()
        session.load(ExperimentConfig(name="daily-quota-reset", flow=_daily_quota_graph(loop_iterations=12, cooldown_value=0)))
        await engine.start(session)
        await asyncio.sleep(0.05)

        for _ in range(8):
            signal = SignalEvent(
                source_id="mock:0",
                source_type=SourceType.MOCK,
                signal_id="mock:default",
                ts_ms=int(time.time() * 1000),
                value=1,
                data={},
            )
            await engine.feed_signal(signal)
            await asyncio.sleep(0.08)

        await engine.stop()

    asyncio.run(run_test())

    assert len(actions) >= 6
    assert variable_store.get_value("exp-a", "daily_quota_count") == 3
    assert variable_store.get_value("exp-a", "feeds_today") <= 3
    assert variable_store.get_value("exp-a", "quota_locked") in (0, 1)
    assert variable_store.get_value("exp-a", "day_index") >= 1

    db.close()


def test_validator_rejects_quota_special_fields_and_accepts_generic_daily_quota():
    from session.validator import validate_flow

    ok = validate_flow(_daily_quota_graph(), available_signals=["mock:default"])
    assert ok.valid, ok.errors

    graph = _daily_quota_graph()
    graph.nodes["record_feed"].params = {
        "event_name": "旧投喂",
        "state_op": "feed_success",
        "daily_quota_count": 3,
        "cooldown_s": 20,
    }
    bad = validate_flow(graph, available_signals=["mock:default"])
    assert not bad.valid
    assert any("state_op" in err or "daily_quota_count" in err or "cooldown_s" in err for err in bad.errors)
