"""
CSV 导出

将结构化事件数据导出为 CSV 文件，供外部复核。
"""

from __future__ import annotations

import csv
import os
import time
from typing import List, Dict, Any, Optional


CSV_FIELDS = [
    "session_id",
    "session_name",
    "subject_id",
    "time",
    "ts_ms",
    "event_type",
    "node_id",
    "signal_id",
    "actuator_id",
    "trigger_mode",
    "action_type",
    "smoothing_flag",
    "raw_payload",
]

CSV_HEADERS = {
    "session_id": "实验编号",
    "session_name": "实验名称",
    "subject_id": "动物编号",
    "time": "时间",
    "ts_ms": "时间戳(毫秒)",
    "event_type": "事件类型",
    "node_id": "节点编号",
    "signal_id": "信号源",
    "actuator_id": "执行器",
    "trigger_mode": "触发方式",
    "action_type": "动作类型",
    "smoothing_flag": "数据标记",
    "raw_payload": "原始数据",
}


def export_csv(
    records: List[Dict[str, Any]],
    output_path: str,
    include_raw: bool = False,
) -> bool:
    """
    导出事件数据为 CSV。

    Args:
        records: 结构化事件记录列表
        output_path: 输出文件路径
        include_raw: 是否包含 raw_payload 列

    Returns:
        是否成功
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fields = list(CSV_FIELDS)
    if not include_raw:
        fields = [f for f in fields if f != "raw_payload"]

    try:
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            header_row = {k: CSV_HEADERS.get(k, k) for k in fields}
            writer.writerow(header_row)
            for record in records:
                row = {k: record.get(k, "") for k in fields}
                if "raw_payload" in row and isinstance(row["raw_payload"], dict):
                    import json
                    row["raw_payload"] = json.dumps(row["raw_payload"], ensure_ascii=False)
                writer.writerow(row)
        return True
    except Exception as e:
        raise RuntimeError(f"CSV 导出失败: {e}")


def export_session_csv(
    records: List[Dict[str, Any]],
    session_id: str,
    output_dir: str,
    include_raw: bool = False,
    subject_id: str = "",
    session_name: str = "",
) -> str:
    """
    按会话导出 CSV，文件名 {动物编号}_{实验名称}_{日期}_{时间}.csv
    """
    safe_subject = subject_id.replace(" ", "_").replace("/", "_").replace(":", "_")[:32] if subject_id else "未命名动物"
    safe_name = session_name.replace(" ", "_").replace("/", "_").replace(":", "_")[:32] if session_name else "未命名"
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_subject}_{safe_name}_{ts}.csv"
    path = os.path.join(output_dir, filename)
    export_csv(records, path, include_raw=include_raw)
    return path
