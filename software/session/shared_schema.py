"""
shared_schema.py — 流程节点定义的唯一真源

所有节点类型、端口、参数的范围和单位都在此定义。
后端 Model、Validator、测试全都从这份数据读取。
前端 NODE_SCHEMAS 通过 sync_schema.py 构建时自动生成。

使用方法:
    from session.shared_schema import get_node_schema, get_port_spec
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional


# ============================================================================
# 端口模式定义
# ============================================================================
PORT_SPEC: Dict[str, Dict[str, int]] = {
    "single": {"inputs": 1, "outputs": 1},     # 标准 1入1出
    "zero_in": {"inputs": 0, "outputs": 1},     # 无入边（START）
    "zero_out": {"inputs": -1, "outputs": 0},   # 无出边，多入（END）
    "multi_in": {"inputs": -1, "outputs": 1},   # 多入单出（TRIGGER, AND, DELAY, EXECUTE, RECORD）
    "bypass": {"inputs": 0, "outputs": 0},       # 旁路（SNIFFER）
}


# ============================================================================
# 参数模板 — 字段名只在此定义一次
# ============================================================================
PARAM_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "duration_value": {
        "label": "等待数值",
        "type": "number", "min": 0, "max": 1000, "step": 1,
        "default": 1, "unit": "", "required": True,
        "integer": True,
        "help": "延时数值，整数，允许 0~1000",
    },
    "duration_unit": {
        "label": "时间单位",
        "type": "select",
        "options": [
            {"value": "seconds", "label": "秒"},
            {"value": "minutes", "label": "分钟"},
            {"value": "hours", "label": "小时"},
        ],
        "default": "seconds", "required": True,
        "help": "延时时间单位",
    },
    "timeout_s": {
        "label": "超时时间",
        "type": "number", "min": 1, "max": 3600, "step": 1,
        "default": 60, "unit": "秒", "required": True,
        "help": "超时时间，单位秒；0 表示不启用超时",
    },
    "signal_id": {
        "label": "信号源",
        "type": "select", "options": "dynamic",
        "required": True,
        "help": "信号源 ID，从可用的摄像头区域/硬件传感器中选择",
    },
    "max_iterations": {
        "label": "最大循环次数",
        "type": "number", "min": 1, "max": 10000,
        "default": 10, "required": True,
        "help": "最大循环次数",
    },
    "event_name": {
        "label": "事件名称",
        "type": "text", "maxLength": 100,
        "required": True,
        "help": "事件名称",
    },
    "variable_name": {
        "label": "变量名称",
        "type": "text", "maxLength": 64,
        "required": False,
        "help": "变量名称，例如 feeds_today、daily_quota_count",
    },
    "variable_op": {
        "label": "变量操作",
        "type": "select",
        "options": [
            {"value": "add", "label": "加"},
            {"value": "subtract", "label": "减"},
            {"value": "set", "label": "设为"},
        ],
        "default": "add", "required": False,
        "help": "变量操作",
    },
    "variable_value": {
        "label": "变量数值",
        "type": "number", "min": -999999, "max": 999999, "step": 1,
        "default": 1, "required": False,
        "integer": True,
        "help": "变量操作数，整数，允许 0 和负数",
    },
    "variable_persistent": {
        "label": "是否持久状态",
        "type": "checkbox",
        "default": False, "required": False,
        "help": "勾选后变量写入持久状态，服务重启后仍可读取",
    },
    "compare_source": {
        "label": "比较对象",
        "type": "select",
        "options": [
            {"value": "value", "label": "固定数值"},
            {"value": "variable", "label": "变量"},
        ],
        "default": "value", "required": False,
        "help": "比较对象来源",
    },
    "compare_variable_name": {
        "label": "比较变量名称",
        "type": "text", "maxLength": 64,
        "required": False,
        "help": "当比较对象为变量时填写变量名称",
    },
    "actuator_id": {
        "label": "执行器名称",
        "type": "select", "options": "dynamic",
        "required": True,
        "help": "执行器 ID，从注册中心加载",
    },
    "action": {
        "label": "动作类型",
        "type": "select",
        "options": [
            {"value": "high", "label": "开启"},
            {"value": "low", "label": "关闭"},
        ],
        "default": "high", "required": True,
        "help": "动作类型",
    },
    "operator": {
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
        "default": "gt", "required": True,
        "help": "比较运算符",
    },
    "source": {
        "label": "数据来源",
        "type": "select",
        "options": [
            {"value": "trigger_count", "label": "TRIGGER 累计计数"},
            {"value": "variable", "label": "变量"},
        ],
        "default": "trigger_count", "required": True,
        "help": "条件判断数据来源：TRIGGER 上游累计数或变量",
    },
    "value": {
        "label": "判断值",
        "type": "number", "min": -999999, "max": 999999,
        "default": 0, "required": True, "integer": True,
        "help": "比较阈值",
    },
}


# ============================================================================
# 13 种节点的完整定义 — 这就是唯一真源
# ============================================================================
NODE_SCHEMA: Dict[str, Dict[str, Any]] = {
    "start": {
        "label": "开始", "label_en": "Start",
        "color": "#4C9B50", "icon": "🔴",
        "ports": "zero_in",  # 0入1出
        "params": [],
        "help": "流程入口。一个流程有且仅有一个开始节点。",
    },
    "end": {
        "label": "结束", "label_en": "End",
        "color": "#D32F2F", "icon": "⏹",
        "ports": "zero_out",  # 多入0出
        "params": [],
        "help": "流程出口。流程执行完毕或手动终止时到达此节点。",
    },
    "trigger": {
        "label": "触发信号", "label_en": "Trigger",
        "color": "#FF9800", "icon": "⚡",
        "ports": "multi_in",  # 多入1出
        "params": ["signal_id"],
        "help": "选择信号来源。当该信号源检测到事件时，流程从这里开始执行。",
    },
    "delay": {
        "label": "延时等待", "label_en": "Delay",
        "color": "#7C4DFF", "icon": "⏱",
        "ports": "multi_in",  # 多入1出（PORT-V2）
        "params": ["duration_value", "duration_unit"],
        "help": "流程执行到此节点时暂停指定时长。前端以整数数值 + 秒/分钟/小时配置。",
    },
    "condition": {
        "label": "条件判断", "label_en": "Condition",
        "color": "#5C6BC0", "icon": "🔀",
        "ports": {"inputs": 1, "outputs": 2,
                   "output_labels": ["真", "假"], "output_ports": ["true", "false"]},
        "params": ["source", "variable_name", "operator", "value", "compare_source", "compare_variable_name"],
        "help": "根据上游数据做条件判断。可读取运行时变量和持久变量。",
    },
    "execute": {
        "label": "执行动作", "label_en": "Execute",
        "color": "#43A047", "icon": "🛠",
        "ports": "multi_in",  # 多入1出（PORT-V2）
        "params": ["actuator_id", "action"],
        "help": "调用指定执行器执行动作。开启/关闭模式，具体参数由硬件模块自管。",
    },
    "loop": {
        "label": "循环", "label_en": "Loop",
        "color": "#7C4DFF", "icon": "🔄",
        "ports": {"inputs": 1, "outputs": 2,
                   "output_labels": ["循环体", "退出"], "output_ports": ["body", "exit"]},
        "params": ["max_iterations", "timeout_s"],
        "help": "循环执行，最多循环 max_iterations 次或超时 timeout_s 秒。",
    },
    "and": {
        "label": "逻辑与", "label_en": "AND",
        "color": "#78909C", "icon": "📦",
        "ports": "multi_in",  # 多入1出
        "params": [],
        "help": "所有输入端口都收到信号后才触发输出。用于多路径汇聚。",
    },
    "not": {
        "label": "逻辑非", "label_en": "NOT",
        "color": "#B0BEC5", "icon": "❑",
        "ports": {"inputs": 1, "outputs": 1},
        "params": ["signal_id", "timeout_s"],
        "help": "等待信号消失后放行：在超时上限内持续检测指定信号源。",
    },
    "fork": {
        "label": "逻辑分叉", "label_en": "Fork",
        "color": "#90A4AE", "icon": "🔁",
        "ports": {"inputs": 1, "outputs": 2,
                   "output_labels": ["继续", "记录终止"], "output_ports": ["continue", "stop"]},
        "params": [],
        "help": "同时触发下游两条路径。无配置参数。两路完全独立。",
    },
    "record": {
        "label": "记录事件", "label_en": "Record",
        "color": "#43A047", "icon": "📝",
        "ports": "multi_in",  # 多入1出（PORT-V2）
        "params": ["event_name", "variable_name", "variable_op", "variable_value", "variable_persistent"],
        "help": "记录实验事件，并可选执行变量写入。勾选持久状态后变量跨服务重启保留。",
    },
    "record_end": {
        "label": "记录终止", "label_en": "Record End",
        "color": "#E53935", "icon": "⏹",
        "ports": "zero_out",  # 多入0出（PORT-V2）
        "params": ["event_name"],
        "help": "记录后终止流程分支。用于分支路径的终点记录，记录完成即停止，不再往下执行。",
    },
    "sniffer": {
        "label": "旁路探针", "label_en": "Sniffer",
        "color": "#FFB74D", "icon": "👁",
        "ports": "bypass",  # 0入0出
        "params": ["signal_id", "event_name"],
        "help": "旁路观测节点。0入0出，不参与流程拓扑。运行时独立监听指定信号源。",
    },
}


# 调色板显示顺序
# 注：record_end 已于 Sprint v1.2.0 从新建面板下线（用 RECORD + END 组合替代）。
# NODE_SCHEMA 仍保留 record_end 定义，仅用于旧流程加载时的迁移识别，不进面板。
PALETTE_ORDER = [
    "trigger", "delay", "condition", "execute",
    "loop", "and", "not", "fork",
    "record", "sniffer",
]

# 多入边豁免节点列表（PORT-V2：inputs=-1 的节点）
MULTI_INPUT_NODES = [
    "and", "end", "trigger",
    "delay", "execute", "record", "record_end",
]


# ============================================================================
# 导出函数
# ============================================================================

def get_node_schema(node_type: str) -> Optional[Dict[str, Any]]:
    """获取指定节点类型的定义。如果节点类型不存在返回 None。"""
    return NODE_SCHEMA.get(node_type)


def get_port_spec(node_type: str) -> Dict[str, Any]:
    """获取指定节点类型的端口定义（展开 PORT_SPEC 引用的值）。"""
    schema = NODE_SCHEMA.get(node_type)
    if not schema:
        return {"inputs": 0, "outputs": 0}
    ports = schema["ports"]
    if isinstance(ports, str):
        return dict(PORT_SPEC[ports])
    if isinstance(ports, dict):
        return dict(ports)
    return {"inputs": 0, "outputs": 0}


def get_param_schema(param_key: str) -> Optional[Dict[str, Any]]:
    """获取参数模板定义。"""
    return PARAM_TEMPLATES.get(param_key)


def get_expanded_params(node_type: str) -> List[Dict[str, Any]]:
    """获取节点参数的完整展开定义（含所有字段的元信息）。"""
    schema = NODE_SCHEMA.get(node_type)
    if not schema:
        return []
    result: List[Dict[str, Any]] = []
    for key in schema.get("params", []):
        template = PARAM_TEMPLATES.get(key)
        if template:
            entry = dict(template)
            entry["key"] = key
            # 检查是否有条件显示
            conditions = schema.get("param_conditions", {})
            if key in conditions:
                entry["condition"] = conditions[key]
            result.append(entry)
    return result
