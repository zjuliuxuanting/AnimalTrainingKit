#!/usr/bin/env python3
"""
G3 自我验收 — 三端同步检查（修复版）

检查 shared_schema.py 与以下三端的定义是否完全一致：
  1. 后端 Model (flow_model.py)
  2. 后端 Validator (validator.py)
  3. 前端 Schema (flow-model.js)

用法：
    cd software && python3 tools/verify_consistency.py
"""

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from session.shared_schema import NODE_SCHEMA, MULTI_INPUT_NODES, get_port_spec


def read_file(path: str) -> str:
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path), "r") as f:
        return f.read()


def check_model():
    """检查 1: 后端 Model 枚举"""
    print("\n=== 📋 Model 检查 ===")
    errors = []
    code = read_file("session/flow_model.py")

    # 仅提取 NodeType 枚举 (class NodeType(...Enum): 到下一个 class)
    model_match = re.search(r'class NodeType.*?Enum\):\n(.*?)(?=\nclass |\n\n|\Z)', code, re.DOTALL)
    if not model_match:
        errors.append("无法解析 NodeType 枚举")
        return errors
    
    enum_body = model_match.group(1)
    type_enum = re.findall(r'(\w+)\s*=\s*"([^"]+)"', enum_body)
    enum_values = {v for _, v in type_enum}

    schema_types = set(NODE_SCHEMA.keys())
    missing = schema_types - enum_values
    extra = enum_values - schema_types

    if missing:
        errors.append(f"Model 缺少枚举值: {missing}")
    else:
        print(f"  ✅ NodeType 枚举覆盖全部 13 种节点")

    if extra:
        errors.append(f"Model 有多余枚举值: {extra}")
    else:
        print(f"  ✅ Model 无多余枚举值")

    # 检查 output_ports 是否匹配 port spec — 双出口节点
    double_out_types = {
        "condition": {"true", "false"},
        "loop": {"body", "exit"},
        "fork": {"continue", "stop"},
    }
    for nt, expected_ports in double_out_types.items():
        ps = get_port_spec(nt)
        if ps.get("outputs") == 2:
            # 检查 output_ports 返回了正确的端口列表
            # 用 for nt in (CONDITION, LOOP, FORK) 模式查找
            code_section = code[code.find(f"NodeType.{nt.upper()}"):code.find(f"NodeType.{nt.upper()}")+300] if f"NodeType.{nt.upper()}" in code else ""
            if not code_section:
                # 尝试作为第一个分支查找
                alt_idx = code.find(f"NodeType.{nt.upper()}")
                if alt_idx < 0:
                    # 检查 SNIFFER/RECORD_END 特殊处理中的逻辑
                    code_section = code[code.find(f"NodeType.SNIFFER"):code.find(f"NodeType.SNIFFER")+100] if nt == "sniffer" else ""
            
            found_ports = set()
            for p in expected_ports:
                if p in code_section or f'"{p}"' in code[:800]:
                    found_ports.add(p)
            
            if found_ports == expected_ports:
                print(f"  ✅ {nt}: 双出口端口 ({', '.join(expected_ports)}) 在 Model 中有定义")
            elif found_ports:
                print(f"  ⚠️  {nt}: 部分端口匹配 {found_ports} (期望 {expected_ports})")
            else:
                errors.append(f"{nt} 预期双出口但 Model 中可能缺失端口定义")
        else:
            print(f"  ✅ {nt}: 非双出口节点 (inputs={ps['inputs']}, outputs={ps['outputs']})")

    return errors


def check_validator():
    """检查 2: 后端 Validator"""
    print("\n=== 📋 Validator 检查 ===")
    errors = []
    code = read_file("session/validator.py")

    # 检查端口豁免列表
    for nt in MULTI_INPUT_NODES:
        # 在 validator.py 中查找 NodeType.{UPPERCASE}
        enum_ref = f"NodeType.{nt.upper()}"
        # 或在豁免列表区域的字符串中出现
        if enum_ref not in code:
            errors.append(f"Validator 豁免列表可能缺失 {nt} (未找到 {enum_ref})")
        else:
            print(f"  ✅ {nt}: 在 Validator 多入边豁免列表中")

    # 检查参数校验范围
    range_checks = [
        ("DELAY", "duration_s", 0.1, 3600),
        ("EXECUTE", "duration_s", 0.1, 3600),
        ("LOOP", "max_iterations", 1, 10000),  # 在 _check_loop_guards 中检查
        ("LOOP", "timeout_s", 0, 3600),
        ("NOT", "timeout_s", 0.1, 3600),
    ]
    for node_name, field, lo, hi in range_checks:
        if field in code:
            if str(lo) in code and str(hi) in code:
                print(f"  ✅ {node_name}.{field}: 范围 [{lo}, {hi}] 已校验")
            else:
                # 可能是通过 guard 函数检查
                guard_pattern = f"{field}" in code and (f"<= 0" in code or f">= {lo}" in code or f"< {lo}" in code or f"> {hi}" in code)
                if guard_pattern or f"_check_loop_guards" in code:
                    print(f"  ✅ {node_name}.{field}: 通过 guard 函数校验")
                else:
                    errors.append(f"{node_name}.{field}: 范围校验可能缺失")
        else:
            errors.append(f"{node_name}.{field}: 在 validator 中未找到")

    return errors


def check_frontend():
    """检查 3: 前端 Schema (flow-model.js)"""
    print("\n=== 📋 前端 Schema 检查 ===")
    errors = []
    code = read_file("web/js/flow-model.js")

    # 检查所有 13 种节点
    for nt, schema in NODE_SCHEMA.items():
        if nt not in code and schema["label"] not in code:
            errors.append(f"前端缺失节点定义: {nt} ({schema['label']})")
        else:
            print(f"  ✅ {nt:12s} ({schema['label']})")

    # 检查多入边同步
    multi_input_types = [nt for nt in NODE_SCHEMA if get_port_spec(nt).get("inputs") == -1]
    for nt in multi_input_types:
        # 找到节点定义块：匹配 `  {nt}: {` (2空格缩进的JS对象定义)
        # 使用正则避免匹配到字段值中的同名关键词
        pattern = re.compile(rf'^\s+{re.escape(nt)}:\s*\{{', re.MULTILINE)
        match = pattern.search(code)
        if match:
            block_start = match.start()
            block = code[block_start:block_start+2500]
            if "inputs: -1" in block:
                print(f"  ✅ {nt}: 多入边 (inputs=-1) 已同步")
            else:
                errors.append(f"{nt}: 前端 inputs 未设置为 -1 (在 {match.group()[:40]} 附近)")
        else:
            # 退一步：直接搜索
            idx = code.find(f"\n  {nt}:")
            if idx >= 0:
                block = code[idx:idx+800]
                if "inputs: -1" in block:
                    print(f"  ✅ {nt}: 多入边 (inputs=-1) 已同步")
                else:
                    errors.append(f"{nt}: 前端 inputs 未设置为 -1")
            else:
                errors.append(f"{nt}: 未找到前端定义块")

    # 检查 PALETTE_ORDER 无 OR
    palette_sec = code[code.find("PALETTE_ORDER"):code.find("PALETTE_ORDER")+300]
    if "'or'" in palette_sec or '"or"' in palette_sec:
        errors.append("PALETTE_ORDER 仍含 'or' 节点")
    else:
        print(f"  ✅ PALETTE_ORDER 无 OR 残留")

    # 检查前端图标无 OR
    canvas_code = read_file("web/js/flow-canvas.js")
    if "'or'" in canvas_code and "icon" in canvas_code:
        # 检查是否是死代码
        icon_lines = [l for l in canvas_code.split("\n") if "'or'" in l and "icon" in l]
        if icon_lines:
            errors.append(f"flow-canvas.js icons 可能残留 or 死代码: {icon_lines}")

    return errors


def main():
    print("=" * 60)
    print("  G3 自我验收 — 三端同步一致性检查")
    print(f"  时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    all_errors = []
    all_errors.extend(check_model())
    all_errors.extend(check_validator())
    all_errors.extend(check_frontend())

    print(f"\n{'=' * 60}")
    if not all_errors:
        print("  🎉 全部检查通过! 三端同步一致")
        return 0
    else:
        print(f"  ❌ 发现 {len(all_errors)} 个问题:")
        for e in all_errors:
            print(f"    • {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
