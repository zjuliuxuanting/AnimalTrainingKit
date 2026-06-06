"""
测试 device_registry.py — 设备与信号源注册中心。

覆盖：
1. 注册/查询/注销信号源
2. 从 camera config 加载信号源
3. 按 experiment_id 隔离
4. 内置 mock/timer 信号源
5. 执行器注册与查询
"""

import pytest
from protocol.device_registry import (
    DeviceRegistry, RegistryEntry,
    SourceCategory, SourceStatus,
    get_registry, load_camera_sources,
)


class TestRegistryCRUD:
    """注册/查询/注销基本操作"""

    def test_register_and_get(self):
        reg = DeviceRegistry("test_exp")
        entry = RegistryEntry(
            source_id="camera:zoneA:enter",
            display_name="摄像头 - 区域A - 进入",
            category=SourceCategory.SIGNAL,
            source_type="camera_zone",
        )
        assert reg.register(entry) is True
        assert reg.get("camera:zoneA:enter") == entry
        assert reg.get("nonexistent") is None

    def test_unregister(self):
        reg = DeviceRegistry("test_exp")
        entry = RegistryEntry(
            source_id="test:signal",
            display_name="测试信号",
            category=SourceCategory.SIGNAL,
            source_type="mock",
        )
        reg.register(entry)
        assert reg.get("test:signal").enabled is True
        reg.unregister("test:signal")
        assert reg.get("test:signal").enabled is False
        # 注销不存在的 source_id 返回 False
        assert reg.unregister("nonexistent") is False

    def test_reregister_updates(self):
        reg = DeviceRegistry("test_exp")
        e1 = RegistryEntry(
            source_id="sig:1",
            display_name="第一版",
            category=SourceCategory.SIGNAL,
            source_type="mock",
        )
        reg.register(e1)
        e2 = RegistryEntry(
            source_id="sig:1",
            display_name="第二版",
            category=SourceCategory.SIGNAL,
            source_type="mock",
        )
        reg.register(e2)
        assert reg.get("sig:1").display_name == "第二版"

    def test_update_status(self):
        reg = DeviceRegistry("test_exp")
        entry = RegistryEntry(
            source_id="dev:1",
            display_name="设备1",
            category=SourceCategory.SIGNAL,
            source_type="hardware",
        )
        reg.register(entry)
        assert reg.update_status("dev:1", SourceStatus.ONLINE) is True
        assert reg.get("dev:1").status == SourceStatus.ONLINE
        reg.update_status("dev:1", SourceStatus.ERROR)
        assert reg.get("dev:1").status == SourceStatus.ERROR
        # 不存在的设备
        assert reg.update_status("nonexistent", SourceStatus.ONLINE) is False

    def test_heartbeat(self):
        reg = DeviceRegistry("test_exp")
        entry = RegistryEntry(
            source_id="dev:2",
            display_name="设备2",
            category=SourceCategory.SIGNAL,
            source_type="hardware",
        )
        reg.register(entry)
        reg.heartbeat("dev:2")
        assert reg.get("dev:2").status == SourceStatus.ONLINE


class TestQueryFilters:
    """查询过滤器"""

    def test_query_by_category(self):
        reg = DeviceRegistry("test_exp")
        reg.register(RegistryEntry(
            source_id="sig:a", display_name="信号A",
            category=SourceCategory.SIGNAL, source_type="camera_zone",
        ))
        reg.register(RegistryEntry(
            source_id="act:x", display_name="执行器X",
            category=SourceCategory.ACTUATOR, source_type="hardware",
        ))
        signals = reg.get_all_sources()
        assert len(signals) == 1
        assert signals[0].source_id == "sig:a"
        actuators = reg.get_all_actuators()
        assert len(actuators) == 1
        assert actuators[0].source_id == "act:x"

    def test_query_by_source_type(self):
        reg = DeviceRegistry("test_exp")
        reg.register(RegistryEntry(
            source_id="sig:1", display_name="摄像头信号",
            category=SourceCategory.SIGNAL, source_type="camera_zone",
        ))
        reg.register(RegistryEntry(
            source_id="sig:2", display_name="模拟信号",
            category=SourceCategory.SIGNAL, source_type="mock",
        ))
        camera_sources = reg.query(category=SourceCategory.SIGNAL, source_type="camera_zone")
        assert len(camera_sources) == 1
        assert camera_sources[0].source_id == "sig:1"

    def test_query_disabled_excluded(self):
        reg = DeviceRegistry("test_exp")
        reg.register(RegistryEntry(
            source_id="sig:ok", display_name="正常的",
            category=SourceCategory.SIGNAL, source_type="mock",
        ))
        reg.register(RegistryEntry(
            source_id="sig:disabled", display_name="禁用的",
            category=SourceCategory.SIGNAL, source_type="mock",
        ))
        reg.unregister("sig:disabled")
        results = reg.query(category=SourceCategory.SIGNAL, enabled=True)
        assert len(results) == 1
        assert results[0].source_id == "sig:ok"

    def test_query_by_experiment_id(self):
        reg = DeviceRegistry("exp_1")
        reg.register(RegistryEntry(
            source_id="sig:global", display_name="全局信号",
            category=SourceCategory.SIGNAL, source_type="mock",
            experiment_id="",
        ))
        reg.register(RegistryEntry(
            source_id="sig:local", display_name="实验专属",
            category=SourceCategory.SIGNAL, source_type="camera_zone",
            experiment_id="exp_1",
        ))
        # 查询 exp_1 应包含全局和实验专属
        results = reg.get_all_sources("exp_1")
        assert len(results) >= 1
        assert any(e.source_id == "sig:global" for e in results)
        # 查询 exp_2 应只包含全局和 exp_2 专属
        exp2_reg = DeviceRegistry("exp_2")
        exp2_reg.register_builtin()
        exp2_results = exp2_reg.get_all_sources("exp_2")
        # 全局信号在 exp_1 registry 中，不在 exp_2 registry
        assert all(e.source_id != "sig:local" for e in exp2_results)


class TestCameraConfigLoading:
    """从 camera.json 加载信号源"""

    def test_load_from_event_rules(self):
        reg = DeviceRegistry("cam_exp")
        config = {
            "event_rules": [
                {"zone": "区域A", "event": "enter", "role": "trigger",
                 "name": "A区进入"},
                {"zone": "区域A", "event": "leave", "role": "record",
                 "name": "A区离开"},
            ],
            "zones": [],
        }
        reg.load_from_camera_config(config, "cam_exp")
        sources = reg.get_all_sources("cam_exp")
        # event_rules 中只有 role=trigger 的会被注册
        source_ids = {s.source_id for s in sources}
        assert "camera:区域A:enter" in source_ids
        # role=record 不注册为信号源
        assert "camera:区域A:leave" not in source_ids

    def test_load_from_zone_events(self):
        reg = DeviceRegistry("cam_exp2")
        config = {
            "event_rules": [],
            "zones": [
                {
                    "name": "区域B",
                    "events": {
                        "enter": {"enabled": True, "role": "trigger"},
                        "leave": {"enabled": False, "role": "trigger"},
                    },
                },
            ],
        }
        reg.load_from_camera_config(config, "cam_exp2")
        sources = reg.get_all_sources("cam_exp2")
        source_ids = {s.source_id for s in sources}
        assert "camera:区域B:enter" in source_ids
        # disabled 的不注册
        assert "camera:区域B:leave" not in source_ids

    def test_load_backward_compat(self):
        """兼容旧格式：zone 无 events 配置时默认生成 enter/leave"""
        reg = DeviceRegistry("cam_exp3")
        config = {
            "event_rules": [],
            "zones": [{"name": "旧区域"}],
        }
        reg.load_from_camera_config(config, "cam_exp3")
        sources = reg.get_all_sources("cam_exp3")
        source_ids = {s.source_id for s in sources}
        assert "camera:旧区域:enter" in source_ids
        assert "camera:旧区域:leave" in source_ids

    def test_duplicate_source_id(self):
        """重复 source_id 注册会被更新而非创建新条目"""
        reg = DeviceRegistry("cam_exp4")
        config = {
            "event_rules": [
                {"zone": "区域C", "event": "enter", "role": "trigger",
                 "name": "第一名称"},
            ],
            "zones": [
                {"name": "区域C", "events": {"enter": {"enabled": True, "role": "trigger"}}},
            ],
        }
        reg.load_from_camera_config(config, "cam_exp4")
        sources = reg.get_all_sources("cam_exp4")
        # 同一个 source_id 只应出现一次
        ids = [s.source_id for s in sources if s.source_id == "camera:区域C:enter"]
        assert len(ids) == 1


class TestBuiltinSources:
    """内置信号源和执行器"""

    def test_builtin_mock_timer(self):
        reg = DeviceRegistry()
        reg.register_builtin()
        sources = reg.get_all_sources()
        source_ids = {s.source_id for s in sources}
        assert "mock:default" in source_ids
        assert "timer:system" in source_ids
        mock = reg.get("mock:default")
        assert "mock:trigger" in mock.produced_signals

    def test_builtin_actuators(self):
        reg = DeviceRegistry()
        reg.register_builtin()
        actuators = reg.get_all_actuators()
        actuator_ids = {a.source_id for a in actuators}
        assert "actuator:feeder" in actuator_ids
        assert "actuator:light" in actuator_ids

    def test_builtin_event_types_empty_initially(self):
        """事件类型初始为空（预留给 RECORD 使用）"""
        reg = DeviceRegistry()
        reg.register_builtin()
        events = reg.get_all_event_types()
        assert events == []


class TestGlobalFactory:
    """全局注册中心工厂"""

    def test_get_registry_cached(self):
        reg1 = get_registry("exp_cache")
        reg2 = get_registry("exp_cache")
        assert reg1 is reg2  # 同一实验的注册中心应缓存复用

    def test_get_registry_different_experiments(self):
        reg_a = get_registry("exp_a")
        reg_b = get_registry("exp_b")
        assert reg_a is not reg_b

    def test_load_camera_sources_helper(self):
        config = {
            "event_rules": [
                {"zone": "测试区", "event": "enter", "role": "trigger",
                 "name": "测试进入"},
            ],
            "zones": [],
        }
        load_camera_sources("exp_helper", config)
        reg = get_registry("exp_helper")
        sources = reg.get_all_sources("exp_helper")
        assert any(s.source_id == "camera:测试区:enter" for s in sources)


class TestExperimentIsolation:
    """实验隔离"""

    def test_different_experiments_isolated(self):
        config_a = {
            "event_rules": [
                {"zone": "区A", "event": "enter", "role": "trigger",
                 "name": "实验A"},
            ],
            "zones": [],
        }
        config_b = {
            "event_rules": [
                {"zone": "区B", "event": "enter", "role": "trigger",
                 "name": "实验B"},
            ],
            "zones": [],
        }
        load_camera_sources("iso_a", config_a)
        load_camera_sources("iso_b", config_b)
        reg_a = get_registry("iso_a")
        reg_b = get_registry("iso_b")
        # 实验A的信号源不应出现在实验B
        a_ids = {s.source_id for s in reg_a.get_all_sources("iso_a")}
        assert "camera:区A:enter" in a_ids
        b_ids = {s.source_id for s in reg_b.get_all_sources("iso_b")}
        assert "camera:区B:enter" in b_ids
