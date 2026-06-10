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
    "zero_out": {"inputs": -1, "outputs": 0},   # 无出边，多入（END, RECORD_END）
    "multi_in": {"inputs": -1, "outputs": 1},   # 多入单出（TRIGGER, AND, DELAY, EXECUTE, RECORD）
    "bypass": {"inputs": 0, "outputs": 0},       # 旁路（SNIFFER）
}


# ============================================================================
# 参数模板 — 字段名只在此定义一次
# ============================================================================
PARAM_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "duration_s": {
        "type": "number", "min": 0.1, "max": 3600, "step": 0.1,
        "default": 1.0, "unit": "秒", "required": True,
        "help": "持续时间，单位秒",
    },
    "timeout_s": {
        "type": "number", "min": 1, "max": 3600, "step": 1,
        "default": 60, "unit": "秒", "required": True,
        "help": "超时时间，单位秒；0 表示不启用超时",
    },
    "signal_id": {
        "type": "select", "options": "dynamic",
        "required": True,
        "help": "信号源 ID，从可用的摄像头区域/硬件传感器中选择",
    },
    "max_iterations": {
        "type": "number", "min": 1, "max": 10000,
        "default": 10, "required": True,
        "help": "最大循环次数",
    },
    "event_name": {
        "type": "text", "maxLength": 100,
        "required": True,
        "help": "事件名称",
    },
    "counter_name": {
        "type": "text", "maxLength": 64,
        "required": False,
        "help": "计数器名称，用于累积计数操作",
    },
    "counter_op": {
        "type": "select",
        "options": [
            {"value": "+1", "label": "+1（递增）"},
            {"value": "=0", "label": "=0（重置为零）"},
            {"value": "=1", "label": "=1（重置为一）"},
            {"value": "-1", "label": "-1（递减）"},
        ],
        "default": "+1", "required": False,
        "help": "计数器操作",
    },
    "daily_quota_count": {
        "type": "number", "min": 1, "max": 10000, "step": 1,
        "default": 3, "unit": "次/颗", "required": False,
        "help": "每日投喂上限，软件只按投喂次数/颗数计量",
    },
    "cooldown_s": {
        "type": "number", "min": 0.1, "max": 86400, "step": 0.1,
        "default": 72000, "unit": "秒", "required": False,
        "help": "达到日额度后的冷却时长；验收可压缩为 20 秒",
    },
    "state_op": {
        "type": "select",
        "options": [
            {"value": "", "label": "不写持久状态"},
            {"value": "feed_success", "label": "投喂成功：feeds_today +1"},
            {"value": "start_cooldown", "label": "开始冷却：锁定额度"},
            {"value": "new_day_reset", "label": "新日重置：清零并解锁"},
        ],
        "default": "", "required": False,
        "help": "第5链路专用：RECORD 写入最小持久额度状态",
    },
    "actuator_id": {
        "type": "select", "options": "dynamic",
        "required": True,
        "help": "执行器 ID，从注册中心加载",
    },
    "action": {
        "type": "select",
        "options": [
            {"value": "high", "label": "开启"},
            {"value": "low", "label": "关闭"},
        ],
        "default": "high", "required": True,
        "help": "动作类型",
    },
    "operator": {
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
        "type": "select",
        "options": [
            {"value": "trigger_count", "label": "TRIGGER 累计计数"},
            {"value": "counter", "label": "指定计数器"},
            {"value": "feeds_today", "label": "今日已投喂次数"},
            {"value": "daily_quota_count", "label": "每日投喂上限"},
            {"value": "quota_locked", "label": "额度冷却锁定中"},
            {"value": "quota_available", "label": "今日额度仍可用"},
            {"value": "quota_reached", "label": "今日额度已达上限"},
            {"value": "cooldown_remaining_s", "label": "剩余冷却秒数"},
            {"value": "day_index", "label": "压缩日序号"},
        ],
        "default": "trigger_count", "required": True,
        "help": "条件判断数据来源：TRIGGER 上游累计数、指定计数器或第5链路持久额度状态",
    },
    "value": {
        "type": "number", "min": 0, "max": 999999,
        "default": 0, "required": True,
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
        "params": ["duration_s"],
        "help": "流程执行到此节点时暂停指定时长。默认 1 秒，范围 0.1 秒 ~ 1 小时。",
    },
    "condition": {
        "label": "条件判断", "label_en": "Condition",
        "color": "#5C6BC0", "icon": "🔀",
        "ports": {"inputs": 1, "outputs": 2,
                   "output_labels": ["真", "假"], "output_ports": ["true", "false"]},
        "params": ["source", "operator", "value", "daily_quota_count"],
        "help": "根据上游数据做条件判断。source 可读取 TRIGGER 累计数、计数器或第5链路持久额度状态。",
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
        "params": ["event_name", "counter_name", "counter_op", "state_op", "daily_quota_count", "cooldown_s"],
        "help": "记录实验事件。可选做运行时计数器操作；第5链路可写入最小持久额度状态。",
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
PALETTE_ORDER = [
    "trigger", "delay", "condition", "execute",
    "loop", "and", "not", "fork",
    "record", "record_end", "sniffer",
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
