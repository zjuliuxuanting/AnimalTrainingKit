"""Frontend contract checks for generic variables and experiment context."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_web_js(name: str) -> str:
    return (ROOT / "web" / "js" / name).read_text(encoding="utf-8")


def test_frontend_flow_schema_uses_generic_record_and_delay_fields():
    source = _read_web_js("flow-model.js")
    schema_source = source.split("const NODE_SCHEMAS", 1)[1].split("// Palette display order", 1)[0]
    delay_schema = schema_source.split("delay:", 1)[1].split("condition:", 1)[0]
    record_schema = schema_source.split("record:", 1)[1].split("sniffer:", 1)[0]
    condition_schema = schema_source.split("condition:", 1)[1].split("// --- EXECUTE", 1)[0]

    assert "duration_value" in delay_schema
    assert "duration_unit" in delay_schema
    assert "duration_s" not in delay_schema

    assert "variable" in condition_schema
    assert "variable_name" in condition_schema
    assert "compare_variable_name" in condition_schema
    for legacy_key in ("quota_available", "quota_reached", "daily_quota_count", "cooldown_s"):
        assert legacy_key not in condition_schema

    assert "variable_name" in record_schema
    assert "variable_op" in record_schema
    assert "variable_value" in record_schema
    assert "variable_persistent" in record_schema
    for legacy_key in ("state_op", "daily_quota_count", "cooldown_s", "counter_op"):
        assert legacy_key not in record_schema


def test_stop_experiment_keeps_current_experiment_context():
    source = _read_web_js("app.js")
    stop_body = source.split("async function stopExperiment()", 1)[1].split("let monitorInterval", 1)[0]

    assert "clearExperimentContext" not in stop_body
    assert "currentExpBadge" not in stop_body


def test_default_realtime_log_does_not_render_raw_signal_messages():
    source = _read_web_js("app.js")
    ws_handler = source.split("ws.onmessage", 1)[1].split("ws.onclose", 1)[0]
    signal_branch = ws_handler.split("msg.type === 'signal'", 1)[1].split("msg.type === 'engine_event'", 1)[0]

    assert "log(" not in signal_branch
    assert "📡 信号" not in signal_branch


def test_monitor_exposes_manual_trigger_and_hides_mock_timer_user_path():
    index_source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app_source = _read_web_js("app.js")
    flow_editor_source = _read_web_js("flow-editor.js")

    assert 'id="btnManualTrigger"' in index_source
    assert "手动触发" in index_source
    assert "async function manualTrigger()" in app_source
    assert "/api/experiment/manual-trigger" in app_source

    assert "mock:trigger" not in flow_editor_source
    assert "模拟信号（测试用）" not in flow_editor_source
    assert "timer:" not in flow_editor_source


def test_realtime_log_deduplicates_websocket_and_poll_events():
    app_source = _read_web_js("app.js")
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")

    assert "function renderMonitorEventOnce" in app_source
    assert "monitorEventKey" in app_source
    assert "msg.event_id" in app_source
    assert "renderMonitorEventOnce(e2)" in app_source
    assert '"event_id": event_id' in server_source


def test_flow_config_uses_readonly_node_type_and_optional_display_name():
    index_source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    editor_source = _read_web_js("flow-editor.js")

    assert "节点名称" not in index_source
    assert "节点类型" in index_source
    assert "显示名称（可选）" in index_source
    assert 'id="cfgNodeType"' in index_source
    assert 'id="cfgDisplayName"' in index_source

    assert "cfgLabel" not in editor_source
    assert "cfgNodeType" in editor_source
    assert "cfgDisplayName" in editor_source
    assert "display_name" in editor_source


def test_dynamic_actuator_select_uses_registry_source_id_and_display_name():
    editor_source = _read_web_js("flow-editor.js")
    actuator_branch = editor_source.split("fieldKey === 'actuator_id'", 1)[1].split("if (_cachedSources", 1)[0]

    assert "s.source_id || s.id" in actuator_branch
    assert "s.display_name" in actuator_branch
    assert "<option value=\"${escapeHtml(String(sourceId))}\"" in actuator_branch


def test_realtime_log_shows_record_variable_change_and_user_friendly_action():
    app_source = _read_web_js("app.js")

    assert "function monitorRecordLabel" in app_source
    assert "function monitorActuatorLabel" in app_source
    assert "变量" in app_source
    assert "当前=" in app_source
    assert "执行动作: " in app_source
    assert "actuator_label" in app_source
