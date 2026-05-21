"""
行为学训练盒 — 命令行版（用于验证 + 联调）

用法:
  python cli_app.py mock --count 50              # Mock 模式跑完整链路
  python cli_app.py run flow.json --duration 30   # 加载流程文件并执行
  python cli_app.py camera --seconds 10           # 摄像头运动检测测试
  python cli_app.py export --session SESSION_ID   # 导出会话数据到 CSV
  python cli_app.py connect --host 192.168.4.1    # 连接设备（待硬件联调）
  python cli_app.py list                          # 列出所有历史会话
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
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


def _init_db() -> tuple[Database, EventStore]:
    db_dir = os.path.join(PROJECT_ROOT, "data")
    os.makedirs(db_dir, exist_ok=True)
    db = Database(os.path.join(db_dir, "behavior_box.db"))
    db.open()
    event_store = EventStore(db)
    return db, event_store


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
                                   os.path.join(PROJECT_ROOT, "data"))

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
                                   os.path.join(PROJECT_ROOT, "data"))

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


def cmd_camera(args: argparse.Namespace) -> int:
    """摄像头运动检测测试"""
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

        motion_count = 0
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

    raw_events = event_store.get_events(session_id)
    processor = DataProcessor()
    records = processor.process(raw_events)
    structured = processor.to_structured(records)

    csv_path = export_session_csv(structured, session_id,
                                   os.path.join(PROJECT_ROOT, "data"))
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
        sid = s.get("id", "")[:16]
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

    sp = sub.add_parser("camera", help="摄像头运动检测测试")
    sp.add_argument("--index", type=int, default=0,
                    help="摄像头索引（默认 0）")
    sp.add_argument("--seconds", type=int, default=10,
                    help="测试时长（默认 10）")
    sp.set_defaults(func=cmd_camera)

    sp = sub.add_parser("export", help="导出指定会话数据到 CSV")
    sp.add_argument("--session", required=True, help="会话 ID")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("list", help="列出所有历史会话")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("connect", help="连接 ESP32 设备（待硬件联调）")
    sp.add_argument("--host", default="192.168.4.1", help="设备 IP")
    sp.add_argument("--port", type=int, default=8080, help="设备端口")
    sp.set_defaults(func=cmd_connect)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
