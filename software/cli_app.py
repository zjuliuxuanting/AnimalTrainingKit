"""
行为学训练盒 — 命令行版（用于验证 + 开发测试）

【实验管理】
  create                  创建实验
  experiments             列出所有实验（可 --detail 显示 session 统计）
  detail EXP_ID           查看实验详情 + 关联 session
  delete EXP_ID [...]     删除实验

【运行控制】
  start EXP_ID            启动实验（调 server API）
  stop                    停止实验
  status                  查看运行状态
  trigger                 手动触发信号

【数据】
  export --session SID    导出会话数据到 CSV
  list                    列出历史 session

【调试】
  mock --count N          Mock 模式跑完整链路（独立运行）
  run flow.json           加载流程图 JSON 并执行
  camera                  摄像头运动检测测试
  connect                 连接 ESP32 设备

【注意】
  CRUD 操作直连数据文件，无需服务运行。
  运行时操作（start/stop/status/trigger）需 server 在 8000 端口运行（G2 阶段收尾统一）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Optional, List

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from protocol.signal_source import (
    SignalSource, SignalEvent, SourceType, SourceState,
    MockSignalSource, TimerSource,
)
from protocol.signal_bus import SignalBus
from protocol.device_manager import DeviceManager, DeviceState
from protocol.messages import CmdKind
from session.session import Session, SessionState, ExperimentConfig
from session.flow_model import FlowGraph, FlowNode, NodeType
from session.engine import Engine, EngineState, EngineEvent
from session.validator import validate_flow

from data.database import Database
from data.event_store import EventStore
from data.processor import DataProcessor
from data.export import export_session_csv

# 运行时控制默认端口
DEFAULT_API_PORT = 8000


def _init_db() -> tuple[Database, EventStore]:
    db_dir = os.path.join(PROJECT_ROOT, "data_store")
    os.makedirs(db_dir, exist_ok=True)
    db = Database(os.path.join(db_dir, "behavior_box.db"))
    db.open()
    event_store = EventStore(db)
    return db, event_store


def _api_get(path: str, port: int = DEFAULT_API_PORT) -> Optional[dict]:
    """调 server GET API"""
    url = f"http://localhost:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        print(f"[错误] API 请求失败: {url}")
        print(f"   {e}")
        return None


def _api_post(path: str, data: dict = None, port: int = DEFAULT_API_PORT) -> Optional[dict]:
    """调 server POST API"""
    url = f"http://localhost:{port}{path}"
    body = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        try:
            detail = json.loads(err_body).get("detail", err_body)
        except json.JSONDecodeError:
            detail = err_body
        print(f"[错误] API {e.code}: {detail}")
        return None
    except (urllib.error.URLError, OSError) as e:
        print(f"[错误] API 请求失败: {url}")
        print(f"   请确认 server 已在端口 {port} 运行")
        print(f"   {e}")
        return None


def _init_exp_mgr():
    """初始化实验管理器，指向 data_store/experiments/"""
    from data import experiment_manager as em
    em.set_experiments_root(os.path.join(PROJECT_ROOT, "data_store", "experiments"))
    return em


def _format_exp(exp: dict) -> str:
    """格式化实验信息为可读字符串"""
    name = exp.get("name", "?")
    eid = exp.get("id", "?")[:16]
    subject = exp.get("subject_id", "") or "(未设置)"
    species = exp.get("species", "") or "(未设置)"
    created = time.strftime("%Y-%m-%d %H:%M", time.localtime(exp.get("created_at", 0) / 1000))
    triggers = []
    if exp.get("trigger_manual"): triggers.append("手动")
    if exp.get("trigger_camera"): triggers.append("摄像头")
    if exp.get("trigger_hardware"): triggers.append("硬件")
    trigger_str = "+".join(triggers) if triggers else "无"
    duration = exp.get("max_duration_min", 0)
    max_count = exp.get("max_trigger_count", 0)
    folder = exp.get("_folder", "") or exp.get("save_path", "")
    return (
        f"  ID:       {eid}\n"
        f"  名称:     {name}\n"
        f"  动物:     {subject} ({species})\n"
        f"  触发源:   {trigger_str}\n"
        f"  限制:     {duration}分 / {max_count}次\n"
        f"  创建:     {created}\n"
        f"  路径:     {folder}"
    )


def _make_mock_signal_bus() -> SignalBus:
    bus = SignalBus()
    mock = MockSignalSource("mock:0", event_interval_ms=1500)
    timer = TimerSource("timer:0", tick_interval_ms=1000)
    bus.register(mock)
    bus.register(timer)
    return bus


def _collect_signals(bus: SignalBus, duration_s: float) -> list[SignalEvent]:
    collected: list[SignalEvent] = []
    bus.set_on_signal(lambda e: collected.append(e))
    return collected


def _print_summary(title: str, session_id: str, events: list, elapsed_s: float, csv_path: str = ""):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")
    print(f"  Session:  {session_id[:16]}")
    print(f"  事件数:   {len(events)}")
    if events:
        types = {}
        for e in events:
            t = getattr(e, "event_type", None) or getattr(e, "kind", "unknown")
            types[t] = types.get(t, 0) + 1
        print(f"  类型分布: {types}")
    print(f"  耗时:     {elapsed_s:.1f}s")
    if csv_path:
        print(f"  CSV:      {csv_path}")
    print()


def cmd_mock(args: argparse.Namespace) -> int:
    """Mock 模式：验证从信号产生 → 存储 → CSV 导出的完整链路"""
    count = args.count
    duration_s = count * 1.8

    print(f"Mock 模式启动: 目标 {count} 个事件, 预计 {duration_s:.0f}s")
    print("  信号源: MockSignalSource(1.5s间隔) + TimerSource(1s间隔)")
    print()

    db, event_store = _init_db()

    session = Session()
    config = ExperimentConfig(
        name=f"CLI-Mock-{count}events",
        description=f"CLI mock test, target {count} events",
        session_timeout_ms=duration_s * 2000,
    )
    session.load(config)

    event_store.ensure_session(
        session.id,
        name=config.name,
        config_json=json.dumps(config.to_dict(), ensure_ascii=False),
    )

    bus = _make_mock_signal_bus()
    collected = _collect_signals(bus, duration_s)

    async def run():
        ok = await bus.start_all()
        if not ok:
            print("信号源启动失败")
            return

        session.start()
        deadline = time.time() + duration_s + 5
        while time.time() < deadline:
            if len(collected) >= count:
                break
            await asyncio.sleep(0.1)

        await bus.stop_all()
        session.stop()

    start_ts = time.time()
    asyncio.run(run())
    elapsed = time.time() - start_ts

    for sig in collected:
        event_store.append_event(
            session_id=session.id,
            event_type=f"{sig.source_type.value}_{sig.signal_id.split(':')[-1]}",
            ts_ms=sig.ts_ms,
            signal_id=f"{sig.source_id}:{sig.signal_id}",
            raw_payload={"value": sig.value, "data": sig.data},
        )
    event_store.update_session_state(
        session.id, session.state.value, elapsed_ms=int(elapsed * 1000),
    )

    raw_events = event_store.get_events(session.id)
    processor = DataProcessor()
    records = processor.process(raw_events)
    structured = processor.to_structured(records)

    csv_path = export_session_csv(structured, session.id,
                                   os.path.join(PROJECT_ROOT, "data_store"))

    _print_summary(f"Mock 模式完成: 收集 {len(collected)} 个信号, 入库 {len(raw_events)} 条",
                    session.id, raw_events, elapsed, csv_path)
    db.close()
    return 0 if len(collected) >= count else 1


def cmd_run(args: argparse.Namespace) -> int:
    """加载流程文件并驱动实验运行"""
    flow_path = args.flow
    if not os.path.exists(flow_path):
        print(f"流程文件不存在: {flow_path}")
        return 1

    with open(flow_path, "r", encoding="utf-8") as f:
        flow_data = json.load(f)
    flow = FlowGraph.from_dict(flow_data)
    result = validate_flow(flow)
    print(str(result))
    print()
    if not result.valid:
        return 1

    duration_s = args.duration or 30

    db, event_store = _init_db()

    session = Session()
    config = ExperimentConfig(
        name=flow.name,
        description="CLI run experiment",
        session_timeout_ms=duration_s * 2000,
        flow=flow,
    )
    session.load(config)

    event_store.ensure_session(
        session.id,
        name=config.name,
        flow_json=json.dumps(flow.to_dict(), ensure_ascii=False),
    )

    engine = Engine()
    engine.set_send_action(lambda cmd: _on_engine_action(cmd, session, event_store))
    engine.set_on_engine_event(lambda kind, data: _on_engine_event(kind, data, session, event_store))

    bus = _make_mock_signal_bus()

    engine_events: list = []

    def on_signal(event: SignalEvent):
        asyncio.run_coroutine_threadsafe(engine.feed_signal(event), loop)

    bus.set_on_signal(on_signal)

    loop = asyncio.new_event_loop()

    async def run():
        nonlocal loop
        await bus.start_all()
        await engine.start(session)
        start_ts = time.time()
        while time.time() - start_ts < duration_s:
            await asyncio.sleep(0.1)
        await engine.stop()
        await bus.stop_all()
        await asyncio.sleep(0.1)

    start_ts = time.time()
    loop.run_until_complete(run())
    loop.close()
    elapsed = time.time() - start_ts

    event_store.update_session_state(
        session.id, session.state.value, elapsed_ms=int(elapsed * 1000),
    )

    raw_events = event_store.get_events(session.id)
    processor = DataProcessor()
    records = processor.process(raw_events)
    structured = processor.to_structured(records)

    csv_path = export_session_csv(structured, session.id,
                                   os.path.join(PROJECT_ROOT, "data_store"))

    _print_summary(f"实验完成: {flow.name}",
                    session.id, raw_events, elapsed, csv_path)
    db.close()
    return 0


def _on_engine_action(cmd: dict, session: Session, event_store: EventStore) -> bool:
    actuator_id = cmd.get("actuator_id", "")
    action = cmd.get("action", "")
    duration_ms = cmd.get("duration_ms", 0)
    node_id = cmd.get("node_id", "")

    event_store.append_event(
        session_id=session.id,
        event_type="output_executed",
        ts_ms=int(time.time() * 1000),
        node_id=node_id,
        actuator_id=actuator_id,
        action_type=action,
        raw_payload={"duration_ms": duration_ms, "cmd": cmd},
    )
    print(f"  [执行] {actuator_id} -> {action} ({duration_ms}ms)")
    return True


def _on_engine_event(kind: str, data: dict, session: Session, event_store: EventStore):
    if kind == "node_triggered":
        event_store.append_event(
            session_id=session.id,
            event_type="node_triggered",
            ts_ms=int(time.time() * 1000),
            node_id=data.get("node_id", ""),
            signal_id=data.get("signal_id", ""),
        )
        print(f"  [触发] node={data.get('node_id')} signal={data.get('signal_id')}")
    elif kind == "node_executed":
        event_store.append_event(
            session_id=session.id,
            event_type="node_executed",
            ts_ms=int(time.time() * 1000),
            node_id=data.get("node_id", ""),
            raw_payload=data,
        )
        ntype = data.get("type", "")
        if ntype:
            print(f"  [执行] node={data.get('node_id')} type={ntype}")


def _point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """射线法判断点是否在多边形内"""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _load_camera_config(experiment_id: str) -> dict:
    """加载实验关联的摄像头配置"""
    _init_exp_mgr()
    from data import experiment_manager as em
    exp = em.get_experiment(experiment_id)
    if not exp:
        return {}
    folder = exp.get("_folder", "")
    if not folder:
        return {}
    cam_path = os.path.join(folder, "camera.json")
    try:
        with open(cam_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_camera_config(config: dict, experiment_id: str):
    """保存摄像头配置到实验文件夹"""
    _init_exp_mgr()
    from data import experiment_manager as em
    exp = em.get_experiment(experiment_id)
    if not exp:
        return
    folder = exp.get("_folder", "")
    if not folder:
        return
    cam_path = os.path.join(folder, "camera.json")
    os.makedirs(os.path.dirname(cam_path), exist_ok=True)
    with open(cam_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def cmd_camera_list(args: argparse.Namespace) -> int:
    """列出可用摄像头"""
    try:
        from ui.camera import CameraSource
    except ImportError:
        print("缺少 opencv-python，请安装: pip install opencv-python")
        return 2

    cameras = CameraSource.list_cameras()
    if not cameras:
        print("未检测到可用摄像头")
        return 0

    print(f"检测到 {len(cameras)} 个摄像头:")
    for idx, name in cameras:
        print(f"  [{idx}] {name}")
    return 0


def cmd_camera_test(args: argparse.Namespace) -> int:
    """摄像头运动检测测试（原 camera 行为）"""
    try:
        from ui.camera import CameraSource, HAS_CV2
    except ImportError:
        print("缺少 opencv-python，请安装: pip install opencv-python")
        return 2

    if not HAS_CV2:
        print("opencv-python 未安装")
        return 2

    duration_s = args.seconds or 10
    print(f"摄像头测试: camera_index={args.index}, {duration_s}s")
    print("  检测到运动时输出 [运动] 日志")
    print()

    db, event_store = _init_db()
    session = Session()
    config = ExperimentConfig(
        name=f"CLI-Camera-{args.index}",
        description="CLI camera test",
        session_timeout_ms=duration_s * 2000,
    )
    session.load(config)
    event_store.ensure_session(session.id, name=config.name)

    bus = SignalBus()
    cam = CameraSource(f"camera:{args.index}", camera_index=args.index, fps=15)
    bus.register(cam)
    collected = _collect_signals(bus, duration_s)

    async def run():
        ok = await bus.start_all()
        if not ok:
            print("摄像头启动失败")
            return
        session.start()

        deadline = time.time() + duration_s
        while time.time() < deadline:
            await asyncio.sleep(0.1)

        await bus.stop_all()
        session.stop()

        motion_events = [e for e in collected if "motion" in e.signal_id]
        print(f"\n  运动事件: {len(motion_events)}")

    asyncio.run(run())

    for sig in collected:
        event_store.append_event(
            session_id=session.id,
            event_type=f"camera_{sig.signal_id.split(':')[-1]}",
            ts_ms=sig.ts_ms,
            signal_id=f"{sig.source_id}:{sig.signal_id}",
            raw_payload={"value": sig.value, "data": sig.data},
        )
    event_store.update_session_state(session.id, session.state.value)

    raw_events = event_store.get_events(session.id)
    motion_events = [e for e in raw_events if "motion" in e.get("event_type", "")]
    print(f"  入库事件: {len(raw_events)}（其中运动 {len(motion_events)})")

    db.close()
    return 0


def cmd_camera_config(args: argparse.Namespace) -> int:
    """查看或配置摄像头区域"""
    exp_id = args.exp_id
    config = _load_camera_config(exp_id)

    if args.zone:
        # 添加区域: --zone NAME "x1,y1;x2,y2;..." EVENT
        name, coords_str, event = args.zone
        points = []
        for point_str in coords_str.split(";"):
            try:
                x_str, y_str = point_str.strip().split(",")
                points.append([int(x_str), int(y_str)])
            except (ValueError, TypeError):
                print(f"[错误] 坐标格式无效: {point_str}，应为 x,y")
                return 1
        if len(points) < 3:
            print("[错误] 区域至少需要 3 个顶点")
            return 1

        zones = config.get("zones", [])
        zone = {
            "name": name,
            "points": points,
            "color": config.get("next_color", "#ff0000"),
            "event": event,
        }
        zones.append(zone)
        config["zones"] = zones
        config["camera_index"] = args.camera_index
        config["fps"] = args.fps
        _save_camera_config(config, exp_id)
        print(f"区域已添加: {name} ({len(points)} 顶点, 事件={event})")
        print(f"  camera_index={args.camera_index}, fps={args.fps}")
        return 0

    # 查看当前配置
    if not config:
        print(f"实验 {exp_id} 无摄像头配置")
        return 0

    print(f"摄像头配置 ({exp_id}):")
    print(f"  camera_index: {config.get('camera_index', 0)}")
    print(f"  fps: {config.get('fps', 15)}")
    zones = config.get("zones", [])
    print(f"  区域 ({len(zones)} 个):")
    for z in zones:
        pts = z.get("points", [])
        print(f"    [{z.get('color','?')}] {z.get('name','?')}: {len(pts)} 顶点, 事件={z.get('event','?')}")
    return 0


def cmd_camera_detect(args: argparse.Namespace) -> int:
    """运行摄像头检测（无头模式），带区域交叉检测 + 引擎联动"""
    try:
        from ui.camera import CameraSource, HAS_CV2
    except ImportError:
        print("缺少 opencv-python，请安装: pip install opencv-python")
        return 2

    if not HAS_CV2:
        print("opencv-python 未安装")
        return 2

    exp_id = args.exp_id
    duration_s = args.seconds
    port = args.port

    # 1. 加载摄像头配置
    config = _load_camera_config(exp_id)
    zones = config.get("zones", [])
    camera_index = config.get("camera_index", args.index)
    fps = config.get("fps", 15)

    print(f"摄像头检测启动: camera_index={camera_index}, {duration_s}s")
    print(f"  fps={fps}, 区域数={len(zones)}")
    if zones:
        for z in zones:
            print(f"    区域: {z.get('name','?')} ({len(z.get('points',[]))} 顶点) → {z.get('event','?')}")
    print()

    db, event_store = _init_db()

    # 2. 创建 session
    session = Session()
    config_obj = ExperimentConfig(
        name=f"CLI-Camera-Detect-{exp_id[:8]}",
        description="CLI camera detection",
        session_timeout_ms=duration_s * 2000,
    )
    session.load(config_obj)
    event_store.ensure_session(session.id, name=config_obj.name, experiment_id=exp_id)

    # 3. 初始化摄像头
    bus = SignalBus()
    cam = CameraSource(f"camera:{exp_id}", camera_index=camera_index, fps=fps)
    bus.register(cam)

    motion_log: list = []
    zone_entry_log: dict = {}  # zone name → inside flag
    for z in zones:
        zone_entry_log[z.get("name", "?")] = False

    async def run():
        ok = await bus.start_all()
        if not ok:
            print("摄像头启动失败")
            return
        session.start()

        bus.set_on_signal(lambda e: motion_log.append(e))

        deadline = time.time() + duration_s
        check_interval = 0.5  # 每 500ms 检查一次

        while time.time() < deadline:
            await asyncio.sleep(check_interval)

            # 检查最近的运动事件
            recent = [e for e in motion_log if "motion_level" in e.signal_id][-5:]
            if not recent:
                continue

            max_level = max(e.value for e in recent)
            motion_active = max_level >= 500  # 运动阈值

            # 区域交叉检测（简化：有运动时触发区域事件）
            for z in zones:
                zname = z.get("name", "?")
                zevent = z.get("event", "enter")
                was_inside = zone_entry_log.get(zname, False)

                if motion_active and not was_inside:
                    zone_entry_log[zname] = True
                    # 发送区域进入事件到 server
                    if args.push:
                        payload = {
                            "zone": zname,
                            "event": "enter" if zevent == "enter" else "enter",
                            "experiment_id": exp_id,
                            "ts": int(time.time() * 1000),
                        }
                        _api_post("/api/experiment/camera-event", payload, port=port)

                    # 记录到本地 DB
                    event_store.append_event(
                        session_id=session.id,
                        event_type=f"zone_enter",
                        ts_ms=int(time.time() * 1000),
                        signal_id=f"camera:{zname}:enter",
                        raw_payload={"zone": zname, "event": "enter"},
                    )
                    print(f"  [进入] {zname}")
                elif not motion_active and was_inside:
                    zone_entry_log[zname] = False
                    event_store.append_event(
                        session_id=session.id,
                        event_type=f"zone_leave",
                        ts_ms=int(time.time() * 1000),
                        signal_id=f"camera:{zname}:leave",
                        raw_payload={"zone": zname, "event": "leave"},
                    )
                    print(f"  [离开] {zname}")

        await bus.stop_all()
        session.stop()

    asyncio.run(run())

    # 4. 入库所有运动事件
    for sig in motion_log:
        event_store.append_event(
            session_id=session.id,
            event_type=f"camera_{sig.signal_id.split(':')[-1]}",
            ts_ms=sig.ts_ms,
            signal_id=f"{sig.source_id}:{sig.signal_id}",
            raw_payload={"value": sig.value, "data": sig.data},
        )
    event_store.update_session_state(session.id, session.state.value)

    # 5. 汇总
    raw_events = event_store.get_events(session.id)
    zone_events = [e for e in raw_events if e.get("event_type", "").startswith("zone_")]
    motion_events = [e for e in raw_events if "motion" in e.get("event_type", "")]
    print(f"\n  入库事件: {len(raw_events)}")
    print(f"    运动: {len(motion_events)}")
    print(f"    区域: {len(zone_events)}")
    print(f"  Session: {session.id}")

    db.close()
    return 0


def cmd_camera_events(args: argparse.Namespace) -> int:
    """查询摄像头相关事件"""
    exp_id = args.exp_id
    limit = args.limit

    db, event_store = _init_db()

    # 查找该实验的所有 session
    sessions = event_store.get_sessions_by_experiment(exp_id)
    if not sessions:
        print(f"实验 {exp_id} 无关联 session")
        db.close()
        return 0

    all_events = []
    for s in sessions:
        events = event_store.get_events(s.get("id", ""))
        for e in events:
            if "camera" in e.get("event_type", "") or "zone" in e.get("event_type", ""):
                e["_session_id"] = s.get("id", "")[:16]
                all_events.append(e)

    # 去重后按时间排序
    seen = set()
    unique = []
    for e in sorted(all_events, key=lambda x: x.get("ts_ms", 0), reverse=True):
        eid = (e.get("_session_id", ""), e.get("ts_ms", 0), e.get("event_type", ""))
        if eid not in seen:
            seen.add(eid)
            unique.append(e)
    unique = unique[:limit]

    if not unique:
        print("无摄像头/区域事件")
        db.close()
        return 0

    print(f"最近 {len(unique)} 条摄像头/区域事件:")
    print(f"  {'时间':<22} {'类型':<18} {'信号源':<30} {'值':<6}")
    for e in unique:
        ts = e.get("ts_ms", 0)
        if ts > 1e12:  # 毫秒
            t_str = time.strftime("%m-%d %H:%M:%S", time.localtime(ts / 1000))
        else:
            t_str = str(ts)
        etype = e.get("event_type", "")[:18]
        sig = e.get("signal_id", "")[:30]
        val = e.get("raw_payload", {})
        val_str = val.get("value", "") if isinstance(val, dict) else ""
        print(f"  {t_str:<22} {etype:<18} {sig:<30} {str(val_str):<6}")

    db.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """导出指定会话的数据到 CSV"""
    session_id = args.session
    db, event_store = _init_db()

    session_info = event_store.get_session(session_id)
    if not session_info:
        print(f"会话不存在: {session_id}")
        print("可用会话列表: python cli_app.py list")
        db.close()
        return 1

    # 用数据库中的完整 ID（兼容前缀匹配）
    full_id = session_info["id"]
    raw_events = event_store.get_events(full_id)
    processor = DataProcessor()
    records = processor.process(raw_events)
    structured = processor.to_structured(records)

    csv_path = export_session_csv(structured, full_id,
                                   os.path.join(PROJECT_ROOT, "data_store"))
    print(f"已导出 {len(structured)} 条事件到:")
    print(f"  {csv_path}")
    db.close()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """列出所有历史会话"""
    db, event_store = _init_db()
    sessions = event_store.get_sessions(limit=50)
    if not sessions:
        print("暂无历史会话记录")
        db.close()
        return 0

    print(f"{'Session ID':<24} {'名称':<24} {'状态':<12} {'事件数':<8} {'时间'}")
    print("-" * 80)
    for s in sessions:
        sid = s.get("id", "")[:24]
        name = s.get("name", "")[:20]
        state = s.get("state", "")
        count = event_store.get_events(s.get("id", ""))
        created = time.strftime("%m-%d %H:%M",
                                 time.localtime(s.get("created_at", 0)))
        print(f"{sid:<24} {name:<24} {state:<12} {len(count):<8} {created}")
    db.close()
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    """连接设备（待硬件联调时使用）"""
    host = args.host
    port = args.port

    print(f"设备连接测试: {host}:{port}")
    print("  此功能需硬件交付后联调")
    print()

    from protocol.device_manager import DeviceInfo

    info = DeviceInfo(
        device_id="cli_test",
        name="CLI-Connect-Test",
        transport_type="ws",
        host=host,
        port=port,
    )

    mgr = DeviceManager()

    async def run():
        ok = await mgr.connect_ws(info)
        if ok:
            print(f"  设备已连接: {mgr.device_id}")
            status = mgr.get_status()
            print(f"  状态: {status.state.value}")
            await mgr.disconnect()
        else:
            print("  连接失败（预期行为：硬件未就绪）")

    asyncio.run(run())
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    """创建实验（全参数）"""
    em = _init_exp_mgr()
    try:
        exp_id = em.create_experiment(
            name=args.name,
            subject_id=args.subject or "",
            species=args.species or "",
            subject_notes=args.notes or "",
            notes=args.notes or "",
            max_duration_min=args.max_duration,
            max_trigger_count=args.max_triggers,
            trigger_manual=True,
            trigger_camera=args.camera,
            trigger_hardware=args.hardware,
            hardware_count=args.hardware_count,
            start_mode="manual",
            timer_config={"interval_ms": args.timer_interval} if args.timer else None,
            save_path=args.save_path or "",
        )
    except ValueError as e:
        print(f"[错误] {e}")
        return 1

    exp = em.get_experiment(exp_id)
    print("实验创建成功:")
    print(_format_exp(exp))
    print(f"  EXP ID:   {exp_id}")
    return 0


def cmd_experiments(args: argparse.Namespace) -> int:
    """列出所有实验"""
    em = _init_exp_mgr()
    db, event_store = _init_db()
    exps = em.list_experiments()
    if not exps:
        print("暂无实验记录")
        db.close()
        return 0

    show_detail = args.detail
    as_json = args.json

    results = []
    for exp in exps:
        eid = exp.get("id", "")
        sessions = event_store.get_sessions_by_experiment(eid)
        session_count = len(sessions)
        total_events = 0
        for s in sessions:
            total_events += len(event_store.get_events(s.get("id", "")))

        entry = {
            "id": eid,
            "name": exp.get("name", "?"),
            "subject": exp.get("subject_id", ""),
            "species": exp.get("species", ""),
            "session_count": session_count,
            "total_events": total_events,
            "created_at": exp.get("created_at", 0),
        }
        results.append(entry)

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        db.close()
        return 0

    if show_detail:
        for i, r in enumerate(results):
            created = time.strftime("%m-%d %H:%M",
                                     time.localtime(r["created_at"] / 1000))
            print(f"[{i+1}] {r['name']:<20} {r['subject']:<8} {r['species']:<8}"
                  f"  session: {r['session_count']:<3}  事件: {r['total_events']:<5}  {created}")
    else:
        print(f"{'#':<4} {'实验名称':<24} {'动物':<10} {'物种':<10} {'创建时间'}")
        print("-" * 70)
        for i, r in enumerate(results):
            created = time.strftime("%m-%d %H:%M",
                                     time.localtime(r["created_at"] / 1000))
            print(f"{i+1:<4} {r['name']:<24} {r['subject']:<10} {r['species']:<10} {created}")

    db.close()
    return 0


def cmd_detail(args: argparse.Namespace) -> int:
    """查看实验详情"""
    em = _init_exp_mgr()
    exp = em.get_experiment(args.exp_id)
    if not exp:
        print(f"[错误] 实验不存在: {args.exp_id}")
        return 1

    print(_format_exp(exp))
    notes = exp.get("notes", "") or exp.get("subject_notes", "")
    if notes:
        print(f"  备注:     {notes[:200]}")

    em_status = em.get_camera_config_status(args.exp_id)
    print(f"  摄像头配置: {em_status}")

    flow = em.load_flow(args.exp_id)
    if flow:
        print(f"  关联流程: {flow.get('name', '?')} ({len(flow.get('nodes', []))} 节点)")

    if args.sessions or args.json:
        db, event_store = _init_db()
        sessions = event_store.get_sessions_by_experiment(args.exp_id)
        if sessions:
            print(f"\n  --- 关联 Session ({len(sessions)} 个) ---")
            print(f"  {'Session ID':<24} {'事件数':<8} {'状态':<12} {'时间'}")
            for s in sessions:
                sid = s.get("id", "")[:20]
                count = len(event_store.get_events(s.get("id", "")))
                state = s.get("state", "")
                created = time.strftime("%m-%d %H:%M",
                                         time.localtime(s.get("created_at", 0)))
                print(f"  {sid:<24} {count:<8} {state:<12} {created}")
        else:
            print("\n  无关联 Session")
        db.close()

    if args.json:
        db, event_store = _init_db()
        info = dict(exp)
        info["sessions"] = [
            {**s, "event_count": len(event_store.get_events(s.get("id", "")))}
            for s in event_store.get_sessions_by_experiment(args.exp_id)
        ]
        print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
        db.close()

    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """删除实验"""
    em = _init_exp_mgr()
    exp_ids = args.exp_ids

    if args.all:
        exps = em.list_experiments()
        exp_ids = [e["id"] for e in exps]
        if not exp_ids:
            print("没有可删除的实验")
            return 0
        names = [e["name"] for e in exps]
        if not args.force:
            print(f"将删除 {len(exps)} 个实验:")
            for n in names:
                print(f"  - {n}")
            confirm = input("确认删除? (y/N): ")
            if confirm.lower() != "y":
                print("已取消")
                return 0

    if not exp_ids:
        print("[错误] 请指定要删除的实验 ID")
        return 1

    deleted = em.batch_delete_experiments(exp_ids)
    print(f"已删除 {deleted}/{len(exp_ids)} 个实验")
    return 0 if deleted == len(exp_ids) else 1


def cmd_clone(args: argparse.Namespace) -> int:
    """克隆实验"""
    em = _init_exp_mgr()
    try:
        new_id = em.clone_experiment(args.exp_id, args.name)
    except ValueError as e:
        print(f"[错误] {e}")
        return 1
    except Exception as e:
        print(f"[错误] 克隆失败: {e}")
        return 1

    if new_id:
        print(f"克隆成功: {new_id}")
        exp = em.get_experiment(new_id)
        if exp:
            print(_format_exp(exp))
        return 0
    print(f"[错误] 实验不存在: {args.exp_id}")
    return 1


def cmd_start(args: argparse.Namespace) -> int:
    """启动实验（调 server API）"""
    em = _init_exp_mgr()
    exp = em.get_experiment(args.exp_id)
    if not exp:
        print(f"[错误] 实验不存在: {args.exp_id}")
        return 1

    print(f"启动实验: {exp.get('name', '?')}")
    print(f"  事件数: {args.count}")
    print(f"  端口:   {args.port}")

    result = _api_post("/api/experiment/start-mock", {
        "count": args.count,
        "exp_name": exp.get("name", ""),
        "experiment_id": args.exp_id,
        "subject_id": exp.get("subject_id", ""),
        "notes": exp.get("notes", ""),
    }, port=args.port)

    if result is None:
        return 1
    print(f"  结果: {json.dumps(result, ensure_ascii=False)}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """停止实验（调 server API）"""
    result = _api_post("/api/experiment/stop", port=args.port)
    if result is None:
        return 1
    print(f"已停止: {json.dumps(result, ensure_ascii=False)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """查看实验状态"""
    watch = args.watch
    port = args.port
    interval = args.interval

    import itertools as _itertools
    for round_num in _itertools.count(1) if watch else [1]:
        if watch and round_num > 1:
            time.sleep(interval)
            # 清屏
            print("\033[2J\033[H", end="", flush=True)

        result = _api_get("/api/status", port=port)
        if result is None:
            if not watch:
                return 1
            continue

        print(f"{'='*50}")
        print(f"  行为学训练盒 — 状态 (端口 {port})")
        print(f"{'='*50}")
        print(f"  版本:   {result.get('version', '?')}")
        print(f"  引擎:   {result.get('engine', '?')}")
        print(f"  Session: {result.get('session', '?')}")
        print(f"  WS 客户端: {result.get('ws_clients', 0)}")
        print()
        print(f"  刷新: 第 {round_num} 次" if watch else "")

        if not watch:
            break

    return 0


def cmd_trigger(args: argparse.Namespace) -> int:
    """手动触发信号（调 server API）"""
    payload = {
        "zone": args.zone,
        "event": args.event_type,
        "experiment_id": args.exp_id or "",
        "ts": int(time.time() * 1000),
    }
    result = _api_post("/api/experiment/camera-event", payload, port=args.port)
    if result is None:
        print("[提示] 手动触发通过 WebSocket 在 web 端效果更好")
        print("   CLI 触发仅发送 HTTP 事件到 server，需实验运行中才生效")
        return 1
    print(f"触发结果: {json.dumps(result, ensure_ascii=False)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="behavior_box_cli",
        description="行为学训练盒 CLI 工具 — 用于验证和联调",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("mock", help="Mock 模式跑完整链路（无硬件验证）")
    sp.add_argument("--count", type=int, default=50,
                    help="目标事件数（默认 50）")
    sp.set_defaults(func=cmd_mock)

    sp = sub.add_parser("run", help="加载流程图 JSON 并驱动实验运行")
    sp.add_argument("flow", help="流程图 JSON 文件路径")
    sp.add_argument("--duration", type=int, default=30,
                    help="运行时长秒数（默认 30）")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("camera", help="摄像头操作（子命令: list/test/config/detect/events）")
    csub = sp.add_subparsers(dest="camera_cmd", required=True)

    cs = csub.add_parser("list", help="列出可用 USB 摄像头")
    cs.set_defaults(func=cmd_camera_list)

    cs = csub.add_parser("test", help="运动检测基础测试（原 camera 行为）")
    cs.add_argument("--index", type=int, default=0, help="摄像头索引（默认 0）")
    cs.add_argument("--seconds", type=int, default=10, help="测试时长（默认 10）")
    cs.set_defaults(func=cmd_camera_test)

    cs = csub.add_parser("config", help="查看/配置摄像头区域")
    cs.add_argument("exp_id", help="实验 ID")
    cs.add_argument("--zone", nargs=3,
                    metavar=("NAME", "COORDS", "EVENT"),
                    help="添加区域: name 'x1,y1;x2,y2;...' enter|leave")
    cs.add_argument("--camera-index", type=int, default=0, help="摄像头索引")
    cs.add_argument("--fps", type=int, default=15, help="帧率")
    cs.set_defaults(func=cmd_camera_config)

    cs = csub.add_parser("detect", help="运行检测（无头模式），区域交叉+引擎联动")
    cs.add_argument("exp_id", help="实验 ID")
    cs.add_argument("--seconds", type=int, default=30, help="检测时长（默认 30）")
    cs.add_argument("--index", type=int, default=0, help="摄像头索引覆盖")
    cs.add_argument("--push", action="store_true", help="将区域事件推送到 server API")
    cs.add_argument("--port", type=int, default=DEFAULT_API_PORT, help="server 端口")
    cs.set_defaults(func=cmd_camera_detect)

    cs = csub.add_parser("events", help="查询摄像头/区域事件")
    cs.add_argument("exp_id", help="实验 ID")
    cs.add_argument("--limit", type=int, default=20, help="显示条数")
    cs.set_defaults(func=cmd_camera_events)

    sp = sub.add_parser("export", help="导出指定会话数据到 CSV")
    sp.add_argument("--session", required=True, help="会话 ID")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("list", help="列出所有历史会话")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("connect", help="连接 ESP32 设备（待硬件联调）")
    sp.add_argument("--host", default="192.168.4.1", help="设备 IP")
    sp.add_argument("--port", type=int, default=8080, help="设备端口")
    sp.set_defaults(func=cmd_connect)

    # ==== 实验管理 ====
    sp = sub.add_parser("create", help="创建实验（全参数）")
    sp.add_argument("name", help="实验名称")
    sp.add_argument("--subject", help="动物编号，如 M01")
    sp.add_argument("--species", help="物种/品系，如 C57BL/6")
    sp.add_argument("--notes", help="备注")
    sp.add_argument("--max-duration", type=int, default=30, help="最长时长（分）")
    sp.add_argument("--max-triggers", type=int, default=50, help="最大触发次数")
    sp.add_argument("--hardware", action="store_true", help="启用硬件传感器")
    sp.add_argument("--hardware-count", type=int, default=1, help="硬件传感器数量")
    sp.add_argument("--camera", action="store_true", help="启用摄像头")
    sp.add_argument("--timer", action="store_true", help="启用定时器")
    sp.add_argument("--timer-interval", type=int, default=1000, help="定时器间隔（毫秒）")
    sp.add_argument("--save-path", help="保存路径（自定义）")
    sp.set_defaults(func=cmd_create)

    sp = sub.add_parser("experiments", help="列出所有实验")
    sp.add_argument("--detail", action="store_true", help="显示 session 统计")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.set_defaults(func=cmd_experiments)

    sp = sub.add_parser("detail", help="查看实验详情")
    sp.add_argument("exp_id", help="实验 ID")
    sp.add_argument("--sessions", action="store_true", help="同时列出关联 session")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.set_defaults(func=cmd_detail)

    sp = sub.add_parser("delete", help="删除实验")
    sp.add_argument("exp_ids", nargs="*", help="实验 ID（可多个）")
    sp.add_argument("--all", action="store_true", help="删除所有实验")
    sp.add_argument("--force", action="store_true", help="跳过确认")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("clone", help="克隆实验")
    sp.add_argument("exp_id", help="源实验 ID")
    sp.add_argument("--name", help="新实验名称（默认=原名_副本）")
    sp.set_defaults(func=cmd_clone)

    # ==== 运行控制 ====
    sp = sub.add_parser("start", help="启动实验（需 server 在运行）")
    sp.add_argument("exp_id", help="实验 ID")
    sp.add_argument("--count", type=int, default=10, help="Mock 事件数（默认 10）")
    sp.add_argument("--port", type=int, default=DEFAULT_API_PORT, help="server 端口")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", help="停止实验（需 server 在运行）")
    sp.add_argument("--port", type=int, default=DEFAULT_API_PORT, help="server 端口")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("status", help="查看运行状态（需 server 在运行）")
    sp.add_argument("--port", type=int, default=DEFAULT_API_PORT, help="server 端口")
    sp.add_argument("--watch", action="store_true", help="持续监听（每 2 秒刷新）")
    sp.add_argument("--interval", type=int, default=2, help="刷新间隔秒数")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("trigger", help="手动触发信号（需 server 在运行）")
    sp.add_argument("--exp-id", help="关联实验 ID（可选）")
    sp.add_argument("--zone", default="手动触发", help='区域名称（默认"手动触发"）')
    sp.add_argument("--event-type", default="enter", help="事件类型：enter/leave/manual（默认 enter）")
    sp.add_argument("--port", type=int, default=DEFAULT_API_PORT, help="server 端口")
    sp.set_defaults(func=cmd_trigger)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
