"""
测试 flow-editor.js Schema 驱动架构。

覆盖：
1. 所有节点类型的 Schema 字段完整性
2. 参数校验逻辑（必填、数值范围、字符串长度）
3. 保存/加载一致性（JSON 序列化/反序列化）
4. 端口规范 v2 验证（CONDITION source/neq/variable, RECORD 通用变量写入, EXECUTE 简化）

注意：flow-editor.js 是前端 JS，无法直接用 pytest 测试。
本测试在 Python 端验证 Schema 定义与前端一致的 JSON 结构。
"""

import json
import pytest

from session.shared_schema import NODE_SCHEMA as SHARED_NODE_SCHEMA
from session.shared_schema import get_expanded_params, get_port_spec


# ============================================================================
# Schema 定义（与 shared_schema.py + flow-model.js NODE_SCHEMAS 保持一致）
# ============================================================================

NODE_SCHEMAS = {
    "start": {
        "label": "开始",
        "color": "#4C9B50",
        "icon": "\U0001F534",
        "fields": [],
        "help": "",
        "ports": {"inputs": 0, "outputs": 1},
    },
    "end": {
        "label": "结束",
        "color": "#D32F2F",
        "icon": "⏹",
        "fields": [],
        "help": "",
        "ports": {"inputs": -1, "outputs": 0},
    },
    "trigger": {
        "label": "触发信号",
        "color": "#FF9800",
        "icon": "⚡",
        "fields": [
            {
                "key": "signal_id",
                "label": "信号源",
                "type": "select",
                "options": "dynamic",
                "required": True,
            }
        ],
        "help": "当信号源检测到事件时触发流程执行。信号源从摄像头区域事件、模拟信号或硬件传感器中选择。",
        "ports": {"inputs": -1, "outputs": 1},
    },
    "delay": {
        "label": "延时等待",
        "color": "#9C27B0",
        "icon": "⏱",
        "fields": [
            {
                "key": "duration_value",
                "label": "等待数值",
                "type": "number",
                "min": 0,
                "max": 1000,
                "step": 1,
                "default": 1,
                "integer": True,
                "required": True,
            },
            {
                "key": "duration_unit",
                "label": "时间单位",
                "type": "select",
                "options": [
                    {"value": "seconds", "label": "秒"},
                    {"value": "minutes", "label": "分钟"},
                    {"value": "hours", "label": "小时"},
                ],
                "default": "seconds",
                "required": True,
            },
        ],
        "help": "流程执行到此节点时暂停指定时长。前端以整数数值 + 秒/分钟/小时配置。",
        "ports": {"inputs": -1, "outputs": 1},
    },
    "condition": {
        "label": "条件判断",
        "color": "#5C6BC0",
        "icon": "\U0001F500",
        "fields": [
            {
                "key": "source",
                "label": "数据来源",
                "type": "select",
                "options": [
                    {"value": "trigger_count", "label": "TRIGGER 累计计数"},
                    {"value": "variable", "label": "变量"},
                ],
                "default": "trigger_count",
                "required": True,
            },
            {
                "key": "variable_name",
                "label": "变量名称",
                "type": "text",
                "maxLength": 64,
                "required": False,
            },
            {
                "key": "operator",
                "label": "判断条件",
                "type": "select",
                "options": [
                    {"value": "eq", "label": "等于"},
                    {"value": "neq", "label": "不等于"},
                    {"value": "gt", "label": "大于"},
                    {"value": "lt", "label": "小于"},
                    {"value": "gte", "label": "大于等于"},
                    {"value": "lte", "label": "小于等于"},
                ],
                "default": "gt",
                "required": True,
            },
            {
                "key": "value",
                "label": "判断值",
                "type": "number",
                "min": -999999,
                "max": 999999,
                "default": 0,
                "integer": True,
                "required": True,
            },
            {
                "key": "compare_source",
                "label": "比较对象",
                "type": "select",
                "options": [
                    {"value": "value", "label": "固定数值"},
                    {"value": "variable", "label": "变量"},
                ],
                "default": "value",
                "required": False,
            },
            {
                "key": "compare_variable_name",
                "label": "比较变量名称",
                "type": "text",
                "maxLength": 64,
                "required": False,
            },
        ],
        "help": "根据上游数据做条件判断。可读取运行时变量和持久变量。",
        "ports": {"inputs": 1, "outputs": 2, "outputLabels": ["真", "假"], "outputPorts": ["true", "false"]},
    },
    "execute": {
        "label": "执行动作",
        "color": "#43A047",
        "icon": "\U0001F6E0",
        "fields": [
            {
                "key": "actuator_id",
                "label": "执行器名称",
                "type": "select",
                "options": "dynamic",
                "required": True,
            },
            {
                "key": "action",
                "label": "动作类型",
                "type": "select",
                "options": [
                    {"value": "high", "label": "开启"},
                    {"value": "low", "label": "关闭"},
                ],
                "default": "high",
                "required": True,
            },
        ],
        "help": "调用指定执行器执行动作。开启/关闭模式，具体参数由硬件模块自管。",
        "ports": {"inputs": -1, "outputs": 1},
    },
    "loop": {
        "label": "循环",
        "color": "#E91E63",
        "icon": "\U0001F504",
        "fields": [
            {
                "key": "max_iterations",
                "label": "最大循环次数",
                "type": "number",
                "min": 1,
                "max": 10000,
                "default": 10,
                "required": True,
            },
            {
                "key": "timeout_s",
                "label": "超时时间",
                "type": "number",
                "min": 1,
                "max": 3600,
                "default": 60,
                "required": True,
            },
        ],
        "help": "循环执行“循环体”分支，最多循环 max_iterations 次或超时 timeout_s 秒（哪个先到就退出）。循环结束后走“退出”分支。",
        "ports": {"inputs": 1, "outputs": 2, "outputLabels": ["循环体", "退出"]},
    },
    "and": {
        "label": "逻辑与",
        "color": "#607D8B",
        "icon": "\U0001F4E6",
        "fields": [],
        "help": "所有输入端口都收到信号后才触发输出。用于多路径汇聚。",
        "ports": {"inputs": -1, "outputs": 1},
    },
    "not": {
        "label": "逻辑非",
        "color": "#673AB7",
        "icon": "❑",
        "fields": [
            {
                "key": "signal_id",
                "label": "检测信号源",
                "type": "select",
                "options": "dynamic",
                "required": True,
            },
            {
                "key": "timeout_s",
                "label": "消失等待",
                "type": "number",
                "min": 0.1,
                "max": 3600,
                "step": 0.1,
                "default": 5,
                "unit": "秒",
                "required": True,
            },
        ],
        "help": "等待信号消失后放行：在超时上限内持续检测指定信号源，若无事件则放行。常用于检测动物离开区域等场景。",
        "ports": {"inputs": 1, "outputs": 1},
    },
    "record": {
        "label": "记录事件",
        "color": "#43A047",
        "icon": "\U0001F4DD",
        "fields": [
            {"key": "event_name", "label": "事件名称", "type": "text", "maxLength": 100, "required": True},
            {"key": "variable_name", "label": "变量名称", "type": "text", "maxLength": 64, "required": False},
            {
                "key": "variable_op",
                "label": "变量操作",
                "type": "select",
                "options": [
                    {"value": "add", "label": "加"},
                    {"value": "subtract", "label": "减"},
                    {"value": "set", "label": "设为"},
                ],
                "default": "add",
                "required": False,
            },
            {"key": "variable_value", "label": "变量数值", "type": "number", "min": -999999, "max": 999999, "step": 1, "default": 1, "integer": True, "required": False},
            {"key": "variable_persistent", "label": "是否持久状态", "type": "checkbox", "default": False, "required": False},
        ],
        "help": "记录实验事件。可选：写入运行时变量或持久变量。",
        "ports": {"inputs": -1, "outputs": 1},
    },
    "record_end": {
        "label": "记录终止",
        "color": "#E53935",
        "icon": "⏹",
        "fields": [
            {"key": "event_name", "label": "事件名称", "type": "text", "maxLength": 100, "required": True},
        ],
        "help": "记录后终止流程分支。",
        "ports": {"inputs": -1, "outputs": 0},
    },
}


def _frontend_style_ports(node_type):
    ports = get_port_spec(node_type)
    if "output_labels" in ports:
        ports["outputLabels"] = ports.pop("output_labels")
    if "output_ports" in ports:
        ports["outputPorts"] = ports.pop("output_ports")
    return ports


def _build_schema_from_shared():
    result = {}
    for node_type, schema in SHARED_NODE_SCHEMA.items():
        fields = get_expanded_params(node_type)
        for field in fields:
            field.setdefault("label", field["key"])
        result[node_type] = {
            "label": schema["label"],
            "color": schema["color"],
            "icon": schema["icon"],
            "fields": fields,
            "help": schema.get("help", ""),
            "ports": _frontend_style_ports(node_type),
        }
    return result


# Use shared_schema.py as the test source of truth instead of maintaining a
# stale hand-copied mirror in this file.
NODE_SCHEMAS = _build_schema_from_shared()


# ============================================================================
# 测试 1: Schema 完整性
# ============================================================================

class TestSchemaCompleteness:
    """验证所有节点类型的 Schema 字段完整性。"""

    def test_all_node_types_exist(self):
        """所有节点类型都在 Schema 中定义。"""
        expected_types = {'start', 'end', 'trigger', 'delay', 'condition',
                          'execute', 'loop', 'and', 'not', 'fork',
                          'record', 'record_end', 'sniffer'}
        assert set(NODE_SCHEMAS.keys()) == expected_types

    def test_each_schema_has_required_keys(self):
        """每个 Schema 都有 label, color, icon, fields, help, ports。"""
        required_keys = {'label', 'color', 'icon', 'fields', 'help', 'ports'}
        for node_type, schema in NODE_SCHEMAS.items():
            assert required_keys.issubset(schema.keys()), \
                f"Schema '{node_type}' 缺少键: {required_keys - schema.keys()}"

    def test_ports_spec_valid(self):
        """每个 Schema 的 ports 规范有效。"""
        for node_type, schema in NODE_SCHEMAS.items():
            ports = schema['ports']
            assert 'inputs' in ports, f"'{node_type}' ports 缺少 inputs"
            assert 'outputs' in ports, f"'{node_type}' ports 缺少 outputs"
            assert isinstance(ports['inputs'], int), f"'{node_type}' inputs 必须是整数"
            assert isinstance(ports['outputs'], int), f"'{node_type}' outputs 必须是整数"

    def test_start_ports(self):
        """START: 0 输入, 1 输出。"""
        assert NODE_SCHEMAS['start']['ports'] == {'inputs': 0, 'outputs': 1}

    def test_end_ports(self):
        """END: >=1 输入, 0 输出。"""
        assert NODE_SCHEMAS['end']['ports'] == {'inputs': -1, 'outputs': 0}

    def test_condition_ports(self):
        """CONDITION: 1 输入, 2 输出（真/假）。"""
        assert NODE_SCHEMAS['condition']['ports'] == {
            'inputs': 1, 'outputs': 2,
            'outputLabels': ['真', '假'],
            'outputPorts': ['true', 'false'],
        }

    def test_loop_ports(self):
        """LOOP: 1 输入, 2 输出（循环体/退出）。"""
        assert NODE_SCHEMAS['loop']['ports'] == {
            'inputs': 1, 'outputs': 2,
            'outputLabels': ['循环体', '退出'],
            'outputPorts': ['body', 'exit'],
        }

    def test_trigger_ports(self):
        """TRIGGER: -1 输入 (>=1, 支持回路收敛), 1 输出。"""
        assert NODE_SCHEMAS['trigger']['ports'] == {'inputs': -1, 'outputs': 1}

    def test_and_ports(self):
        """AND: >=1 输入, 1 输出。"""
        assert NODE_SCHEMAS['and']['ports'] == {'inputs': -1, 'outputs': 1}

    def test_not_ports(self):
        """NOT: 1 输入, 1 输出。"""
        assert NODE_SCHEMAS['not']['ports'] == {'inputs': 1, 'outputs': 1}

    def test_no_config_fields_for_fixed_nodes(self):
        """START/END 无配置字段。"""
        assert NODE_SCHEMAS['start']['fields'] == []
        assert NODE_SCHEMAS['end']['fields'] == []

    def test_no_config_fields_for_logic_nodes(self):
        """AND 无配置字段。NOT 有 signal_id + timeout_s。"""
        assert NODE_SCHEMAS['and']['fields'] == []
        assert len(NODE_SCHEMAS['not']['fields']) == 2


# ============================================================================
# 测试 2: 功能节点 Schema 字段
# ============================================================================

class TestFunctionalNodeSchemas:
    """验证功能节点的 Schema 字段定义。"""

    def test_trigger_schema(self):
        """TRIGGER: 仅 signal_id 字段。"""
        schema = NODE_SCHEMAS['trigger']
        assert len(schema['fields']) == 1
        field = schema['fields'][0]
        assert field['key'] == 'signal_id'
        assert field['type'] == 'select'
        assert field['options'] == 'dynamic'
        assert field['required'] is True

    def test_delay_schema(self):
        """DELAY: 整数数值 + 秒/分钟/小时单位。"""
        schema = NODE_SCHEMAS['delay']
        assert len(schema['fields']) == 2
        value_field = schema['fields'][0]
        unit_field = schema['fields'][1]
        assert value_field['key'] == 'duration_value'
        assert value_field['type'] == 'number'
        assert value_field['min'] == 0
        assert value_field['max'] == 1000
        assert value_field['integer'] is True
        assert value_field['required'] is True
        assert unit_field['key'] == 'duration_unit'
        assert {opt['value'] for opt in unit_field['options']} == {'seconds', 'minutes', 'hours'}

    def test_condition_schema(self):
        """CONDITION: 可读 trigger_count/variable。"""
        schema = NODE_SCHEMAS['condition']
        keys = [field['key'] for field in schema['fields']]
        assert keys == ['source', 'variable_name', 'operator', 'value', 'compare_source', 'compare_variable_name']
        assert schema['fields'][0]['default'] == 'trigger_count'
        assert {opt['value'] for opt in schema['fields'][0]['options']} == {'trigger_count', 'variable'}
        assert schema['fields'][2]['key'] == 'operator'
        assert schema['fields'][2]['default'] == 'gt'
        assert schema['fields'][3]['key'] == 'value'
        assert schema['fields'][3]['type'] == 'number'
        assert schema['fields'][3]['min'] == -999999
        assert schema['fields'][3]['max'] == 999999

    def test_execute_schema(self):
        """EXECUTE: actuator_id + action（2 字段，actuator_id 为动态下拉）。"""
        schema = NODE_SCHEMAS['execute']
        assert len(schema['fields']) == 2
        assert schema['fields'][0]['key'] == 'actuator_id'
        assert schema['fields'][0]['type'] == 'select'
        assert schema['fields'][0]['options'] == 'dynamic'
        assert schema['fields'][1]['key'] == 'action'
        assert schema['fields'][1]['type'] == 'select'
        assert schema['fields'][1]['default'] == 'high'

    def test_loop_schema(self):
        """LOOP: max_iterations + timeout_s（秒）。"""
        schema = NODE_SCHEMAS['loop']
        assert len(schema['fields']) == 2
        assert schema['fields'][0]['key'] == 'max_iterations'
        assert schema['fields'][0]['min'] == 1
        assert schema['fields'][0]['max'] == 10000
        assert schema['fields'][1]['key'] == 'timeout_s'
        assert schema['fields'][1]['min'] == 1
        assert schema['fields'][1]['max'] == 3600

    def test_record_schema(self):
        """RECORD: event_name + 通用变量写入字段。"""
        schema = NODE_SCHEMAS['record']
        keys = [field['key'] for field in schema['fields']]
        assert keys == ['event_name', 'variable_name', 'variable_op', 'variable_value', 'variable_persistent']
        assert schema['fields'][1]['required'] is False
        assert schema['fields'][2]['default'] == 'add'
        assert {opt['value'] for opt in schema['fields'][2]['options']} == {'add', 'subtract', 'set'}
        assert schema['fields'][3]['integer'] is True
        assert schema['fields'][4]['type'] == 'checkbox'

    def test_record_end_schema(self):
        """RECORD_END: 仅 event_name（无 experiment_type）。"""
        schema = NODE_SCHEMAS['record_end']
        assert len(schema['fields']) == 1
        assert schema['fields'][0]['key'] == 'event_name'


# ============================================================================
# 测试 3: 参数校验逻辑
# ============================================================================

def validate_node_params(node_type, params):
    """
    Python 端参数校验（与前端 validateNodeParams 逻辑一致）。
    返回 (is_valid, errors) 元组。
    """
    schema = NODE_SCHEMAS.get(node_type)
    if not schema:
        return True, []

    errors = []
    for field in schema['fields']:
        # Required check
        if field.get('required'):
            if field['type'] == 'number':
                if params.get(field['key']) is None or params.get(field['key']) == '':
                    errors.append(f"{field['label']} 不能为空")
                    continue
            elif field['type'] in ('text', 'select'):
                if not params.get(field['key']) or params.get(field['key']) == '':
                    errors.append(f"{field['label']} 不能为空")
                    continue

        # Number range validation
        if field['type'] == 'number' and params.get(field['key']) is not None:
            val = params[field['key']]
            if 'min' in field and val < field['min']:
                errors.append(f"{field['label']} 不能小于 {field['min']}")
            if 'max' in field and val > field['max']:
                errors.append(f"{field['label']} 不能超过 {field['max']}")

        # String length validation
        if field['type'] == 'text' and 'maxLength' in field and params.get(field['key']):
            if len(params[field['key']]) > field['maxLength']:
                errors.append(f"{field['label']} 不能超过{field['maxLength']}个字符")

    return (len(errors) == 0, errors)


class TestParameterValidation:
    """验证参数校验逻辑。"""

    def test_trigger_missing_signal_id(self):
        """TRIGGER 缺少 signal_id -> 校验失败。"""
        valid, errors = validate_node_params('trigger', {})
        assert valid is False
        assert any('信号源' in e for e in errors)

    def test_trigger_valid_signal_id(self):
        """TRIGGER 有 signal_id -> 校验通过。"""
        valid, errors = validate_node_params('trigger', {'signal_id': 'camera:区域A:enter'})
        assert valid is True
        assert errors == []

    def test_delay_duration_too_low(self):
        """DELAY duration_value < 0 -> 校验失败。"""
        valid, errors = validate_node_params('delay', {'duration_value': -1, 'duration_unit': 'seconds'})
        assert valid is False
        assert any('不能小于 0' in e for e in errors)

    def test_delay_duration_too_high(self):
        """DELAY duration_value > 1000 -> 校验失败。"""
        valid, errors = validate_node_params('delay', {'duration_value': 1001, 'duration_unit': 'seconds'})
        assert valid is False
        assert any('不能超过 1000' in e for e in errors)

    def test_delay_duration_valid(self):
        """DELAY duration_value = 0 -> 校验通过。"""
        valid, errors = validate_node_params('delay', {'duration_value': 0, 'duration_unit': 'seconds'})
        assert valid is True

    def test_execute_missing_actuator_id(self):
        """EXECUTE 缺少 actuator_id -> 校验失败。"""
        valid, errors = validate_node_params('execute', {'action': 'high'})
        assert valid is False

    def test_execute_valid(self):
        """EXECUTE 有效参数 -> 校验通过。"""
        valid, errors = validate_node_params('execute', {
            'actuator_id': 'actuator:feeder',
            'action': 'high'
        })
        assert valid is True

    def test_condition_missing_source(self):
        """CONDITION 缺少 source -> 校验失败。"""
        valid, errors = validate_node_params('condition', {'operator': 'gt', 'value': 0})
        assert valid is False
        assert any('数据来源' in e for e in errors)

    def test_condition_value_range(self):
        """CONDITION value 支持负数但限制上界 -> 校验失败。"""
        valid, errors = validate_node_params('condition', {'source': 'trigger_count', 'operator': 'gt', 'value': -1})
        assert valid is True

        valid, errors = validate_node_params('condition', {'source': 'trigger_count', 'operator': 'gt', 'value': 1000000})
        assert valid is False

    def test_condition_valid(self):
        """CONDITION 有效参数（含 source + neq）-> 校验通过。"""
        valid, errors = validate_node_params('condition', {
            'source': 'trigger_count',
            'operator': 'neq',
            'value': 5
        })
        assert valid is True

    def test_loop_timeout_s_min(self):
        """LOOP timeout_s < 1 -> 校验失败。"""
        valid, errors = validate_node_params('loop', {
            'max_iterations': 10,
            'timeout_s': 0
        })
        assert valid is False
        assert any('不能小于 1' in e for e in errors)

    def test_record_event_name_empty(self):
        """RECORD event_name 为空 -> 校验失败。"""
        valid, errors = validate_node_params('record', {'event_name': ''})
        assert valid is False

    def test_record_event_name_too_long(self):
        """RECORD event_name > 100 字符 -> 校验失败。"""
        valid, errors = validate_node_params('record', {'event_name': 'a' * 101})
        assert valid is False

    def test_record_with_variable(self):
        """RECORD 含变量参数 -> 校验通过。"""
        valid, errors = validate_node_params('record', {
            'event_name': '测试事件',
            'variable_name': 'my_counter',
            'variable_op': 'subtract',
            'variable_value': 0,
            'variable_persistent': True,
        })
        assert valid is True


# ============================================================================
# 测试 4: 保存/加载一致性
# ============================================================================

class TestSaveLoadConsistency:
    """验证保存/加载的 JSON 序列化/反序列化一致性。"""

    def _build_flow_node(self, node_type, params=None):
        """构建一个流程节点数据。"""
        schema = NODE_SCHEMAS[node_type]
        defaults = {}
        for field in schema['fields']:
            if 'default' in field:
                defaults[field['key']] = field['default']
        return {
            'id': f'{node_type}_1',
            'node_type': node_type,
            'label': schema['label'],
            'params': params or defaults,
            'x': 100,
            'y': 100,
        }

    def test_trigger_roundtrip(self):
        """TRIGGER 节点保存->加载参数一致。"""
        node = self._build_flow_node('trigger', {'signal_id': 'camera:区域A:enter'})
        json_str = json.dumps(node)
        restored = json.loads(json_str)
        assert restored['node_type'] == 'trigger'
        assert restored['params']['signal_id'] == 'camera:区域A:enter'

    def test_execute_roundtrip(self):
        """EXECUTE 节点保存->加载参数一致。"""
        node = self._build_flow_node('execute', {
            'actuator_id': '出粮器',
            'action': 'high',
        })
        json_str = json.dumps(node)
        restored = json.loads(json_str)
        assert restored['params']['actuator_id'] == '出粮器'
        assert restored['params']['action'] == 'high'

    def test_condition_roundtrip(self):
        """CONDITION 节点保存->加载参数一致（含 source + neq）。"""
        node = self._build_flow_node('condition', {
            'source': 'trigger_count',
            'operator': 'neq',
            'value': 10,
        })
        json_str = json.dumps(node)
        restored = json.loads(json_str)
        assert restored['params']['source'] == 'trigger_count'
        assert restored['params']['operator'] == 'neq'
        assert restored['params']['value'] == 10

    def test_complex_flow_roundtrip(self):
        """复杂流程（5+ 节点混合类型）保存->加载一致。"""
        flow = {
            'id': 'flow_web',
            'name': '测试流程',
            'nodes': {
                'start_0': {
                    'id': 'start_0',
                    'node_type': 'start',
                    'label': '开始',
                    'params': {},
                    'x': 16, 'y': 16,
                },
                'trigger_1': self._build_flow_node('trigger', {
                    'signal_id': 'camera:区域A:enter'
                }),
                'condition_2': self._build_flow_node('condition', {
                    'source': 'trigger_count',
                    'operator': 'gt',
                    'value': 5,
                }),
                'execute_3': self._build_flow_node('execute', {
                    'actuator_id': '喂食器',
                    'action': 'high',
                }),
                'record_4': self._build_flow_node('record', {
                    'event_name': '喂食记录',
                    'variable_name': 'feed_count',
                    'variable_op': 'add',
                    'variable_value': 1,
                    'variable_persistent': False,
                }),
                'end_5': {
                    'id': 'end_5',
                    'node_type': 'end',
                    'label': '结束',
                    'params': {},
                    'x': 500, 'y': 400,
                },
            },
            'edges': [
                {'id': 'e1', 'source_node': 'start_0', 'source_port': 'out',
                 'target_node': 'trigger_1', 'target_port': 'in'},
                {'id': 'e2', 'source_node': 'trigger_1', 'source_port': 'out',
                 'target_node': 'condition_2', 'target_port': 'in'},
                {'id': 'e3', 'source_node': 'condition_2', 'source_port': 'true',
                 'target_node': 'execute_3', 'target_port': 'in'},
                {'id': 'e4', 'source_node': 'execute_3', 'source_port': 'out',
                 'target_node': 'record_4', 'target_port': 'in'},
                {'id': 'e5', 'source_node': 'record_4', 'source_port': 'out',
                 'target_node': 'end_5', 'target_port': 'in'},
            ],
        }
        json_str = json.dumps(flow)
        restored = json.loads(json_str)

        assert len(restored['nodes']) == 6
        assert restored['nodes']['trigger_1']['params']['signal_id'] == 'camera:区域A:enter'
        assert restored['nodes']['condition_2']['params']['operator'] == 'gt'
        assert restored['nodes']['condition_2']['params']['source'] == 'trigger_count'
        assert restored['nodes']['execute_3']['params']['actuator_id'] == '喂食器'

        assert len(restored['edges']) == 5
        assert restored['edges'][0]['source_node'] == 'start_0'
        assert restored['edges'][4]['target_node'] == 'end_5'

    def test_and_node_no_params(self):
        """AND 节点无 params -> 保存/加载不丢失。"""
        node = self._build_flow_node('and', {})
        json_str = json.dumps(node)
        restored = json.loads(json_str)
        assert restored['node_type'] == 'and'
        assert restored['params'] == {}

    def test_loop_timeout_s_preserved(self):
        """LOOP timeout_s 大数值保存/加载不丢失精度。"""
        node = self._build_flow_node('loop', {
            'max_iterations': 100,
            'timeout_s': 3600,
        })
        json_str = json.dumps(node)
        restored = json.loads(json_str)
        assert restored['params']['timeout_s'] == 3600
        assert restored['params']['max_iterations'] == 100

    def test_record_variable_roundtrip(self):
        """RECORD 变量参数保存/加载一致。"""
        node = self._build_flow_node('record', {
            'event_name': '压杆记录',
            'variable_name': 'press_count',
            'variable_op': 'add',
            'variable_value': 1,
            'variable_persistent': True,
        })
        json_str = json.dumps(node)
        restored = json.loads(json_str)
        assert restored['params']['variable_name'] == 'press_count'
        assert restored['params']['variable_op'] == 'add'
        assert restored['params']['variable_value'] == 1
        assert restored['params']['variable_persistent'] is True


# ============================================================================
# 测试 5: Schema 与端口规范 v2 一致性
# ============================================================================

class TestSchemaVsSpec:
    """验证 Schema 与端口规范 v2 参数取值规范一致。"""

    def _field(self, node_type, key):
        return next(f for f in NODE_SCHEMAS[node_type]["fields"] if f["key"] == key)

    def test_trigger_signal_id_dynamic(self):
        """TRIGGER signal_id 为动态加载。"""
        field = NODE_SCHEMAS['trigger']['fields'][0]
        assert field['options'] == 'dynamic'

    def test_delay_duration_range(self):
        """DELAY duration_value: 0 ~ 1000 integer."""
        field = self._field('delay', 'duration_value')
        assert field['min'] == 0 and field['max'] == 1000
        assert field['integer'] is True
        unit_field = self._field('delay', 'duration_unit')
        assert {opt['value'] for opt in unit_field['options']} == {'seconds', 'minutes', 'hours'}

    def test_condition_has_source(self):
        """CONDITION 有 source 字段，默认 trigger_count。"""
        field = NODE_SCHEMAS['condition']['fields'][0]
        assert field['key'] == 'source'
        assert field['default'] == 'trigger_count'

    def test_condition_operator_has_neq(self):
        """CONDITION operator 选项包含 neq（6 选项）。"""
        options = [opt['value'] for opt in self._field('condition', 'operator')['options']]
        assert set(options) == {'eq', 'neq', 'gt', 'lt', 'gte', 'lte'}

    def test_condition_operator_default(self):
        """CONDITION operator 默认值 gt。"""
        field = self._field('condition', 'operator')
        assert field['default'] == 'gt'

    def test_condition_value_range(self):
        """CONDITION value: -999,999 ~ 999,999。"""
        field = self._field('condition', 'value')
        assert field['min'] == -999999 and field['max'] == 999999

    def test_execute_action_options(self):
        """EXECUTE action 选项仅 high/low。"""
        options = [opt['value'] for opt in NODE_SCHEMAS['execute']['fields'][1]['options']]
        assert set(options) == {'high', 'low'}

    def test_execute_no_duration_s(self):
        """EXECUTE 无 duration_s 字段。"""
        keys = [f['key'] for f in NODE_SCHEMAS['execute']['fields']]
        assert 'duration_s' not in keys

    def test_record_no_experiment_type(self):
        """RECORD 无 experiment_type 字段。"""
        keys = [f['key'] for f in NODE_SCHEMAS['record']['fields']]
        assert 'experiment_type' not in keys

    def test_record_has_variable_fields(self):
        """RECORD 有通用变量写入字段。"""
        keys = [f['key'] for f in NODE_SCHEMAS['record']['fields']]
        assert 'variable_name' in keys
        assert 'variable_op' in keys
        assert 'variable_value' in keys
        assert 'variable_persistent' in keys
        assert 'counter_name' not in keys
        assert 'counter_op' not in keys

    def test_record_end_no_experiment_type(self):
        """RECORD_END 无 experiment_type 字段。"""
        keys = [f['key'] for f in NODE_SCHEMAS['record_end']['fields']]
        assert 'experiment_type' not in keys


class TestGenericVariableSchema:
    """Sprint v1.1.5: 第5链路改由通用变量体系表达。"""

    def test_condition_reads_generic_variable_sources_not_quota_sources(self):
        from session.shared_schema import get_expanded_params

        fields = get_expanded_params("condition")
        source_field = next(f for f in fields if f["key"] == "source")
        options = {opt["value"] for opt in source_field["options"]}
        keys = {f["key"] for f in fields}

        assert "variable" in options
        assert "variable_name" in keys
        assert "compare_variable_name" in keys
        assert not {"feeds_today", "quota_available", "quota_reached", "cooldown_remaining_s"} & options
        assert "daily_quota_count" not in keys

    def test_record_writes_generic_variable_ops_not_quota_ops(self):
        from session.shared_schema import get_expanded_params

        fields = get_expanded_params("record")
        keys = [f["key"] for f in fields]
        op_field = next(f for f in fields if f["key"] == "variable_op")
        ops = {opt["value"] for opt in op_field["options"]}

        assert keys == ["event_name", "variable_name", "variable_op", "variable_value", "variable_persistent"]
        assert {"add", "subtract", "set"} <= ops
        assert not {"state_op", "daily_quota_count", "cooldown_s", "counter_op"} & set(keys)
