"""Sprint v1.1.5: generic flow variables, persistence, and delay units."""

import asyncio


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


def test_shared_schema_exposes_generic_variable_model_not_quota_fields():
    from session.shared_schema import get_expanded_params

    delay_keys = [field["key"] for field in get_expanded_params("delay")]
    assert delay_keys == ["duration_value", "duration_unit"]

    condition_fields = get_expanded_params("condition")
    condition_keys = [field["key"] for field in condition_fields]
    source_options = {
        option["value"]
        for field in condition_fields
        if field["key"] == "source"
        for option in field["options"]
    }
    assert "variable" in source_options
    assert "variable_name" in condition_keys
    assert "compare_variable_name" in condition_keys
    assert not {"feeds_today", "quota_available", "quota_reached", "cooldown_remaining_s"} & source_options
    assert "daily_quota_count" not in condition_keys

    record_keys = [field["key"] for field in get_expanded_params("record")]
    assert record_keys == [
        "event_name",
        "variable_name",
        "variable_op",
        "variable_value",
        "variable_persistent",
    ]
    assert not {"state_op", "daily_quota_count", "cooldown_s", "counter_op"} & set(record_keys)


def test_loaded_legacy_delay_and_counter_fields_are_normalized():
    from session.flow_model import FlowGraph

    graph = FlowGraph.from_dict({
        "id": "legacy-normalize",
        "name": "legacy-normalize",
        "nodes": {
            "start": {"id": "start", "node_type": "start", "label": "start", "params": {}, "x": 0, "y": 0},
            "delay": {
                "id": "delay",
                "node_type": "delay",
                "label": "旧延时",
                "params": {"duration_s": 0.1},
                "x": 100,
                "y": 0,
            },
            "record": {
                "id": "record",
                "node_type": "record",
                "label": "旧计数记录",
                "params": {"event_name": "记录", "counter_name": "press_count", "counter_op": "+1"},
                "x": 200,
                "y": 0,
            },
        },
        "edges": [],
    })

    assert graph.nodes["delay"].params == {"duration_value": 0, "duration_unit": "seconds"}
    assert graph.nodes["record"].params == {
        "event_name": "记录",
        "variable_name": "press_count",
        "variable_op": "add",
        "variable_value": 1,
        "variable_persistent": False,
    }


def test_variable_state_store_persists_zero_and_negative_values(tmp_path):
    from data.database import Database
    from data.variable_state import VariableStateStore

    db_path = str(tmp_path / "variables.db")
    db = Database(db_path)
    db.open()
    store = VariableStateStore(db)

    assert store.apply_op("exp-a", "feeds_today", "set", 0) == 0
    assert store.apply_op("exp-a", "feeds_today", "add", 3) == 3
    assert store.apply_op("exp-a", "feeds_today", "subtract", 5) == -2
    assert store.get_value("exp-a", "feeds_today") == -2
    db.close()

    reopened = Database(db_path)
    reopened.open()
    reopened_store = VariableStateStore(reopened)
    assert reopened_store.get_value("exp-a", "feeds_today") == -2
    reopened.close()


def test_engine_record_writes_runtime_and_persistent_variables_and_condition_reads_them(tmp_path):
    from data.database import Database
    from data.variable_state import VariableStateStore
    from session.engine import Engine
    from session.flow_model import FlowGraph
    from session.session import ExperimentConfig, Session

    db = Database(str(tmp_path / "engine_variables.db"))
    db.open()
    variable_store = VariableStateStore(db)

    graph = FlowGraph(id="variable-flow", name="variable-flow")
    for node in [
        _node("start", "start"),
        _node("set_quota", "record", {
            "event_name": "设置定额",
            "variable_name": "daily_quota_count",
            "variable_op": "set",
            "variable_value": 3,
            "variable_persistent": True,
        }),
        _node("runtime_negative", "record", {
            "event_name": "运行时负数",
            "variable_name": "runtime_score",
            "variable_op": "subtract",
            "variable_value": 1,
            "variable_persistent": False,
        }),
        _node("negative_ok", "condition", {
            "source": "variable",
            "variable_name": "runtime_score",
            "operator": "lt",
            "value": 0,
        }),
        _node("feed_once", "record", {
            "event_name": "投喂一次",
            "variable_name": "feeds_today",
            "variable_op": "add",
            "variable_value": 1,
            "variable_persistent": True,
        }),
        _node("quota_left", "condition", {
            "source": "variable",
            "variable_name": "feeds_today",
            "operator": "lt",
            "compare_source": "variable",
            "compare_variable_name": "daily_quota_count",
        }),
        _node("ok", "record", {"event_name": "仍有额度"}),
        _node("fail", "record", {"event_name": "异常分支"}),
        _node("end", "end"),
    ]:
        graph.add_node(node)

    for edge in [
        _edge("start", "out", "set_quota"),
        _edge("set_quota", "out", "runtime_negative"),
        _edge("runtime_negative", "out", "negative_ok"),
        _edge("negative_ok", "true", "feed_once"),
        _edge("negative_ok", "false", "fail"),
        _edge("feed_once", "out", "quota_left"),
        _edge("quota_left", "true", "ok"),
        _edge("quota_left", "false", "fail"),
        _edge("ok", "out", "end"),
        _edge("fail", "out", "end"),
    ]:
        graph.add_edge(edge)

    engine_events = []

    async def run_test():
        engine = Engine()
        engine.set_variable_state_store(variable_store, "exp-a")
        engine.set_on_engine_event(lambda kind, data: engine_events.append((kind, data)))
        session = Session()
        session.load(ExperimentConfig(name="variable-test", flow=graph))
        await engine.start(session)
        await asyncio.sleep(0.05)
        await engine.stop()

    asyncio.run(run_test())

    assert variable_store.get_value("exp-a", "daily_quota_count") == 3
    assert variable_store.get_value("exp-a", "feeds_today") == 1
    assert variable_store.get_value("exp-a", "runtime_score", default=None) is None

    condition_events = [
        data for kind, data in engine_events
        if kind == "node_executed" and data.get("type") == "condition"
    ]
    assert any(event["node_id"] == "negative_ok" and event["actual_value"] == -1 and event["result"] is True for event in condition_events)
    assert any(event["node_id"] == "quota_left" and event["actual_value"] == 1 and event["expected_value"] == 3 and event["result"] is True for event in condition_events)

    db.close()


def test_validator_accepts_delay_units_and_rejects_legacy_quota_record_params():
    from session.flow_model import FlowGraph
    from session.validator import validate_flow

    graph = FlowGraph(id="validate-variable-flow", name="validate-variable-flow")
    for node in [
        _node("start", "start"),
        _node("delay", "delay", {"duration_value": 0, "duration_unit": "seconds"}),
        _node("trigger", "trigger", {"signal_id": "mock:default"}),
        _node("record", "record", {
            "event_name": "记录变量",
            "variable_name": "score",
            "variable_op": "subtract",
            "variable_value": 0,
            "variable_persistent": False,
        }),
        _node("end", "end"),
    ]:
        graph.add_node(node)
    for edge in [
        _edge("start", "out", "delay"),
        _edge("delay", "out", "trigger"),
        _edge("trigger", "out", "record"),
        _edge("record", "out", "end"),
    ]:
        graph.add_edge(edge)

    ok = validate_flow(graph, available_signals=["mock:default"])
    assert ok.valid, ok.errors

    graph.nodes["record"].params = {
        "event_name": "旧特化",
        "state_op": "feed_success",
        "daily_quota_count": 3,
        "cooldown_s": 20,
    }
    bad = validate_flow(graph, available_signals=["mock:default"])
    assert not bad.valid
    assert any("state_op" in error or "daily_quota_count" in error or "cooldown_s" in error for error in bad.errors)
