"""
实验管理器 — 每个实验是一个自包含文件夹

data_store/experiments/{实验名称}/
├── experiment.json   ← 实验配置
├── flow.json         ← 关联流程
├── camera.json       ← 摄像头配置（可选）
├── events.db         ← SQLite 事件库
└── exports/          ← CSV 导出文件
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from typing import Optional, Dict, Any, List


EXPERIMENTS_ROOT = None


def set_experiments_root(path: str):
    global EXPERIMENTS_ROOT
    EXPERIMENTS_ROOT = path
    os.makedirs(path, exist_ok=True)


def _safe_folder_name(name: str) -> str:
    import re
    safe = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', name)
    return safe[:64] or "未命名"


def _experiment_path(name: str) -> str:
    return os.path.join(EXPERIMENTS_ROOT, _safe_folder_name(name))


def _index_path() -> str:
    return os.path.join(EXPERIMENTS_ROOT, ".index.json")


def _read_index() -> Dict[str, str]:
    try:
        with open(_index_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_index(idx: Dict[str, str]):
    with open(_index_path(), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def _load_experiment_from(folder: str) -> Optional[Dict[str, Any]]:
    cfg_path = os.path.join(folder, "experiment.json")
    if not os.path.exists(cfg_path):
        return None
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["_folder"] = folder
        return cfg
    except (json.JSONDecodeError, KeyError):
        return None


def create_experiment(
    name: str,
    subject_id: str = "",
    species: str = "",
    subject_notes: str = "",
    notes: str = "",
    max_duration_min: int = 30,
    max_trigger_count: int = 50,
    trigger_manual: bool = True,
    trigger_camera: bool = False,
    trigger_hardware: bool = False,
    hardware_count: int = 0,
    camera_zones: list = None,
    start_mode: str = "manual",
    timer_config: dict = None,
    save_path: str = "",
) -> str:
    for exp in list_experiments():
        if exp.get("name") == name:
            raise ValueError(f"同名实验「{name}」已存在，请使用不同的实验名称")

    exp_id = f"exp_{uuid.uuid4().hex[:12]}"
    safe = _safe_folder_name(name or exp_id)
    if save_path:
        folder = os.path.join(save_path, safe)
    else:
        folder = os.path.join(EXPERIMENTS_ROOT, safe)
    os.makedirs(folder, exist_ok=True)
    os.makedirs(os.path.join(folder, "exports"), exist_ok=True)

    config = {
        "id": exp_id,
        "name": name or "未命名实验",
        "subject_id": subject_id,
        "species": species,
        "subject_notes": subject_notes,
        "notes": notes,
        "max_duration_min": max_duration_min,
        "max_trigger_count": max_trigger_count,
        "trigger_manual": trigger_manual,
        "trigger_camera": trigger_camera,
        "trigger_hardware": trigger_hardware,
        "hardware_count": hardware_count,
        "camera_zones": camera_zones or [],
        "start_mode": start_mode,
        "timer_config": timer_config or {},
        "save_path": folder,
        "created_at": int(time.time() * 1000),
        "updated_at": int(time.time() * 1000),
    }

    with open(os.path.join(folder, "experiment.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    # G3-FIN-6: 创建默认 flow.json（含 START/END 节点），确保流程编辑器打开时不为空
    default_flow = {
        "id": f"flow_{exp_id}",
        "name": name or "未命名实验",
        "nodes": {
            "start_0": {
                "id": "start_0", "node_type": "start", "label": "开始",
                "params": {}, "x": 20, "y": 20,
            },
            "end_0": {
                "id": "end_0", "node_type": "end", "label": "结束",
                "params": {}, "x": 300, "y": 20,
            },
        },
        "edges": [],
    }
    with open(os.path.join(folder, "flow.json"), "w", encoding="utf-8") as f:
        json.dump(default_flow, f, ensure_ascii=False, indent=2)

    # Index custom paths so list/get can find them
    if save_path:
        idx = _read_index()
        idx[exp_id] = folder
        _write_index(idx)

    return exp_id


def get_experiment(exp_id: str) -> Optional[Dict[str, Any]]:
    # Check default root first
    for name in os.listdir(EXPERIMENTS_ROOT):
        folder = os.path.join(EXPERIMENTS_ROOT, name)
        if not os.path.isdir(folder):
            continue
        cfg = _load_experiment_from(folder)
        if cfg and cfg.get("id") == exp_id:
            return cfg

    # Check index for custom paths
    idx = _read_index()
    if exp_id in idx:
        cfg = _load_experiment_from(idx[exp_id])
        if cfg:
            return cfg
        # Stale index entry
        del idx[exp_id]
        _write_index(idx)

    return None


def list_experiments() -> List[Dict[str, Any]]:
    result = []
    if not os.path.isdir(EXPERIMENTS_ROOT):
        return result
    seen = set()

    # Scan default root
    for name in sorted(os.listdir(EXPERIMENTS_ROOT), reverse=True):
        folder = os.path.join(EXPERIMENTS_ROOT, name)
        if not os.path.isdir(folder):
            continue
        cfg = _load_experiment_from(folder)
        if cfg:
            seen.add(cfg["id"])
            result.append(cfg)

    # Add from index
    idx = _read_index()
    stale = []
    for exp_id, folder in idx.items():
        if exp_id not in seen:
            cfg = _load_experiment_from(folder)
            if cfg:
                result.append(cfg)
                seen.add(exp_id)
            else:
                stale.append(exp_id)
    if stale:
        for sid in stale:
            del idx[sid]
        _write_index(idx)

    return result


def update_experiment(exp_id: str, updates: Dict[str, Any]) -> bool:
    exp = get_experiment(exp_id)
    if not exp:
        return False
    folder = exp["_folder"]
    exp.update(updates)
    exp["updated_at"] = int(time.time() * 1000)
    with open(os.path.join(folder, "experiment.json"), "w", encoding="utf-8") as f:
        json.dump(exp, f, ensure_ascii=False, indent=2)
    return True


def delete_experiment(exp_id: str) -> bool:
    exp = get_experiment(exp_id)
    if not exp:
        return False
    folder = exp["_folder"]
    shutil.rmtree(folder, ignore_errors=True)
    # Clean up index
    idx = _read_index()
    if exp_id in idx:
        del idx[exp_id]
        _write_index(idx)
    return True


def batch_delete_experiments(exp_ids: List[str]) -> int:
    deleted = 0
    for exp_id in exp_ids:
        try:
            if delete_experiment(exp_id):
                deleted += 1
        except Exception:
            continue
    return deleted


def get_camera_config_status(exp_id: str) -> str:
    """return 'completed', 'pending', or 'disabled'"""
    exp = get_experiment(exp_id)
    if not exp:
        return 'disabled'
    if not exp.get("trigger_camera", False):
        return 'disabled'
    folder = exp.get("_folder", "")
    if not folder:
        return 'disabled'
    cam_path = os.path.join(folder, "camera.json")
    if not os.path.isfile(cam_path):
        return 'pending'
    try:
        with open(cam_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return 'pending'
    zones = cfg.get("zones", [])
    if len(zones) > 0:
        return 'completed'
    return 'pending'


def get_all_camera_statuses() -> dict:
    statuses = {}
    for exp in list_experiments():
        statuses[exp["id"]] = get_camera_config_status(exp["id"])
    return statuses


def clone_experiment(exp_id: str, new_name: str) -> Optional[str]:
    exp = get_experiment(exp_id)
    if not exp:
        return None
    name = new_name or (exp["name"] + "_副本")
    for e in list_experiments():
        if e.get("name") == name and e.get("id") != exp_id:
            raise ValueError(f"同名实验「{name}」已存在，请使用不同的实验名称")
    folder = exp["_folder"]
    new_id = f"exp_{uuid.uuid4().hex[:12]}"
    new_folder = _experiment_path(name)
    os.makedirs(new_folder, exist_ok=True)
    os.makedirs(os.path.join(new_folder, "exports"), exist_ok=True)

    for fname in os.listdir(folder):
        src = os.path.join(folder, fname)
        if os.path.isfile(src) and fname != "events.db":
            shutil.copy2(src, os.path.join(new_folder, fname))

    new_cfg = dict(exp)
    new_cfg["id"] = new_id
    new_cfg["name"] = name
    new_cfg["created_at"] = int(time.time() * 1000)
    new_cfg["updated_at"] = int(time.time() * 1000)
    del new_cfg["_folder"]

    with open(os.path.join(new_folder, "experiment.json"), "w", encoding="utf-8") as f:
        json.dump(new_cfg, f, ensure_ascii=False, indent=2)

    return new_id


def save_flow(exp_id: str, flow_data: dict):
    exp = get_experiment(exp_id)
    if not exp:
        return False
    folder = exp["_folder"]
    with open(os.path.join(folder, "flow.json"), "w", encoding="utf-8") as f:
        json.dump(flow_data, f, ensure_ascii=False, indent=2)
    return True


def load_flow(exp_id: str) -> Optional[dict]:
    exp = get_experiment(exp_id)
    if not exp:
        return None
    flow_path = os.path.join(exp["_folder"], "flow.json")
    if not os.path.exists(flow_path):
        return None
    with open(flow_path, encoding="utf-8") as f:
        return json.load(f)
