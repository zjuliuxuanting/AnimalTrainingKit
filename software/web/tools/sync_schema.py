#!/usr/bin/env python3
"""
构建工具：从 shared_schema.py 生成前端可读的 JSON 文件。

用法：
    python3 web/tools/sync_schema.py

输出到：web/json/node_schemas.json
"""

import json
import os
import sys
from datetime import datetime

# 添加 software/ 目录到路径（因为 session/ 在 software/ 下面）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from session.shared_schema import NODE_SCHEMA, PALETTE_ORDER, MULTI_INPUT_NODES, PARAM_TEMPLATES
from session.shared_schema import get_port_spec, get_expanded_params


def generate_frontend_schema() -> dict:
    """生成前端可用的 NODE_SCHEMAS 格式。"""
    result = {}
    for node_type, schema in NODE_SCHEMA.items():
        entry = {
            "label": schema["label"],
            "color": schema["color"],
            "icon": schema["icon"],
            "fields": get_expanded_params(node_type),
            "help": schema["help"],
            "ports": get_port_spec(node_type),
        }
        result[node_type] = entry

    output = {
        "NODE_SCHEMAS": result,
        "PALETTE_ORDER": PALETTE_ORDER,
        "MULTI_INPUT_NODES": MULTI_INPUT_NODES,
        "_meta": {
            "generated_from": "session/shared_schema.py",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
    return output


def main():
    output = generate_frontend_schema()

    # 确保输出目录存在
    # tools/ 在 software/web/ 下，所以 dirname(dirname) = software/
    # 我们要的是 software/web/json/
    SOFTWARE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    target_dir = os.path.join(SOFTWARE_DIR, "web", "json")
    os.makedirs(target_dir, exist_ok=True)

    json_path = os.path.join(target_dir, "node_schemas.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    count = len(output["NODE_SCHEMAS"])
    print(f"✅ 前端 Schema 已生成到 {json_path}")
    print(f"   包含 {count} 个节点定义")


if __name__ == "__main__":
    main()
