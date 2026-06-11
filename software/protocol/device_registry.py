"""
device_registry.py — 设备与信号源注册中心

三类注册表统一管理：
- 信号源（SignalSource）：TRIGGER 节点选信号时用
- 执行器（Actuator）：EXECUTE 节点选设备时用
- 记录事件（EventType）：RECORD 节点选事件类型时用

注册时机：配置保存时自动注册（摄像头 zone→信号源，硬件连接→执行器）
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import time


class SourceCategory(str, Enum):
    SIGNAL = "signal"
    ACTUATOR = "actuator"
    EVENT = "event"


class SourceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class RegistryEntry:
    """注册条目"""
    source_id: str              # 全局唯一ID
    display_name: str           # 用户可读名称
    category: SourceCategory    # 所属类别
    source_type: str            # camera_zone / hardware / mock / timer / virtual
    device_id: str = ""         # 所属物理设备ID（可选）
    status: SourceStatus = SourceStatus.UNKNOWN
    enabled: bool = True
    produced_signals: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    experiment_id: str = ""


class DeviceRegistry:
    """设备注册中心 — 每个实验一个实例"""

    def __init__(self, experiment_id: str = ""):
        self._experiment_id = experiment_id
        self._entries: Dict[str, RegistryEntry] = {}
        self._subscribers: List = []

    # --- 注册/注销 ---

    def register(self, entry: RegistryEntry) -> bool:
        entry.updated_at = time.time()
        if not entry.experiment_id:
            entry.experiment_id = self._experiment_id
        self._entries[entry.source_id] = entry
        self._notify("register", entry.source_id)
        return True

    def unregister(self, source_id: str) -> bool:
        if source_id in self._entries:
            self._entries[source_id].enabled = False
            self._notify("unregister", source_id)
            return True
        return False

    def update_status(self, source_id: str, status: SourceStatus) -> bool:
        entry = self._entries.get(source_id)
        if not entry:
            return False
        entry.status = status
        entry.updated_at = time.time()
        self._notify("status_change", source_id)
        return True

    def heartbeat(self, source_id: str):
        entry = self._entries.get(source_id)
        if entry:
            entry.status = SourceStatus.ONLINE
            entry.updated_at = time.time()

    # --- 查询 ---

    def query(self,
              category: Optional[SourceCategory] = None,
              source_type: Optional[str] = None,
              enabled: Optional[bool] = True,
              experiment_id: Optional[str] = None
              ) -> List[RegistryEntry]:
        results = []
        for entry in self._entries.values():
            if enabled is not None and entry.enabled != enabled:
                continue
            if category is not None and entry.category != category:
                continue
            if source_type is not None and entry.source_type != source_type:
                continue
            if experiment_id is not None and entry.experiment_id != experiment_id and entry.experiment_id != "":
                continue
            results.append(entry)
        return sorted(results, key=lambda e: e.display_name)

    def get(self, source_id: str) -> Optional[RegistryEntry]:
        return self._entries.get(source_id)

    def get_all_sources(self, experiment_id: str = "") -> List[RegistryEntry]:
        return self.query(category=SourceCategory.SIGNAL, experiment_id=experiment_id or self._experiment_id)

    def get_all_actuators(self, experiment_id: str = "") -> List[RegistryEntry]:
        return self.query(category=SourceCategory.ACTUATOR, experiment_id=experiment_id or self._experiment_id)

    def get_all_event_types(self, experiment_id: str = "") -> List[RegistryEntry]:
        return self.query(category=SourceCategory.EVENT, experiment_id=experiment_id or self._experiment_id)

    # --- 订阅/通知 ---

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def _notify(self, action: str, source_id: str):
        for cb in self._subscribers:
            try:
                cb({"action": action, "source_id": source_id})
            except Exception:
                pass

    # --- 持久化（从配置加载）---

    def load_from_camera_config(self, config: dict, experiment_id: str = ""):
        """从 camera.json 配置加载信号源"""
        eid = experiment_id or self._experiment_id
        zones = config.get("zones", [])
        event_rules = config.get("event_rules", [])

        for rule in event_rules:
            if rule.get("role", "trigger") != "trigger":
                continue  # role=record 等不注册为信号源
            zone = rule.get("zone", "未知区域")
            event = rule.get("event", "enter")
            name = rule.get("name", f"{zone}-{event}")
            source_id = f"camera:{zone}:{event}"
            self.register(RegistryEntry(
                source_id=source_id,
                display_name=f"摄像头 - {name}",
                category=SourceCategory.SIGNAL,
                source_type="camera_zone",
                produced_signals=[source_id],
                experiment_id=eid,
                metadata={"zone": zone, "event": event, "role": "trigger"},
            ))

        for z in zones:
            name = z.get("name", "区域")
            zone_events = z.get("events", {})
            if zone_events and isinstance(zone_events, dict):
                for event_type, event_config in zone_events.items():
                    if isinstance(event_config, dict):
                        enabled = event_config.get("enabled", True)
                        role = event_config.get("role", "trigger")
                        if enabled and role == "trigger":
                            source_id = f"camera:{name}:{event_type}"
                            if source_id not in self._entries:
                                self.register(RegistryEntry(
                                    source_id=source_id,
                                    display_name=f"摄像头 - {name} - {event_type}",
                                    category=SourceCategory.SIGNAL,
                                    source_type="camera_zone",
                                    produced_signals=[source_id],
                                    experiment_id=eid,
                                    metadata={"zone": name, "event": event_type, "role": role},
                                ))
            elif not event_rules:
                for event_type in ["enter", "leave"]:
                    source_id = f"camera:{name}:{event_type}"
                    if source_id not in self._entries:
                        self.register(RegistryEntry(
                            source_id=source_id,
                            display_name=f"摄像头 - {name} - {event_type}",
                            category=SourceCategory.SIGNAL,
                            source_type="camera_zone",
                            produced_signals=[source_id],
                            experiment_id=eid,
                        ))

    def register_builtin(self):
        """注册实验人员主路径可用的内置能力。"""
        self.register(RegistryEntry(
            source_id="manual:trigger",
            display_name="手动触发",
            category=SourceCategory.SIGNAL,
            source_type="manual",
            produced_signals=["manual:trigger"],
        ))
        # 注册内置执行器
        self.register(RegistryEntry(
            source_id="actuator:feeder",
            display_name="给食器（出粮器）",
            category=SourceCategory.ACTUATOR,
            source_type="hardware",
        ))
        self.register(RegistryEntry(
            source_id="actuator:shock",
            display_name="电击器",
            category=SourceCategory.ACTUATOR,
            source_type="hardware",
        ))
        self.register(RegistryEntry(
            source_id="actuator:light",
            display_name="灯光",
            category=SourceCategory.ACTUATOR,
            source_type="hardware",
        ))
        self.register(RegistryEntry(
            source_id="actuator:buzzer",
            display_name="蜂鸣器",
            category=SourceCategory.ACTUATOR,
            source_type="hardware",
        ))


# 全局注册中心管理器
_registry_cache: Dict[str, DeviceRegistry] = {}

def get_registry(experiment_id: str = "") -> DeviceRegistry:
    """获取指定实验的注册中心实例（缓存复用）"""
    key = experiment_id or "__global__"
    if key not in _registry_cache:
        reg = DeviceRegistry(experiment_id)
        reg.register_builtin()
        _registry_cache[key] = reg
    return _registry_cache[key]


def load_camera_sources(experiment_id: str, config: dict):
    """从摄像头配置加载信号源"""
    reg = get_registry(experiment_id)
    reg.load_from_camera_config(config, experiment_id)


def invalidate_registry(experiment_id: str = ""):
    """清除指定实验的注册中心缓存（实验删除/配置更新时用）"""
    key = experiment_id or "__global__"
    _registry_cache.pop(key, None)
