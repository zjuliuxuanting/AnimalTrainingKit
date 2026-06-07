"""
行为学训练盒 — Web 服务器

启动方式：
  pip install fastapi uvicorn websockets
  python server.py
  浏览器打开 http://localhost:8000

版本号：v1.1.0（2026-05-19 UX 修复后）
端口：默认 8000（G2 阶段收尾统一）
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import signal
import logging
import subprocess
import time
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from contextlib import asynccontextmanager

from protocol.signal_source import MockSignalSource, TimerSource, SignalEvent
from protocol.signal_bus import SignalBus
from session.session import Session, ExperimentConfig
from session.flow_model import FlowGraph
from session.engine import Engine
from session.validator import validate_flow
from data.database import Database
from data.event_store import EventStore
from data.processor import DataProcessor
from data.export import export_session_csv
from data.experiment_manager import set_experiments_root, create_experiment, list_experiments, get_experiment, update_experiment, delete_experiment, batch_delete_experiments, get_all_camera_statuses, clone_experiment, save_flow, load_flow

APP_VERSION = "v1.1.0"
DEFAULT_PORT = 8000

db: Optional[Database] = None
event_store: Optional[EventStore] = None
bus: Optional[SignalBus] = None
engine: Optional[Engine] = None
session: Optional[Session] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
ws_clients: set = set()
_mutex = asyncio.Lock()
_experiment_active = False
_mock_device_mgr = None
_camera_config_path = os.path.join(PROJECT_ROOT, "data_store", "camera_config.json")


@asynccontextmanager
async def lifespan(app_instance):
    global db, event_store, _loop
    _loop = asyncio.get_event_loop()
    db_dir = os.path.join(PROJECT_ROOT, "data_store")
    old_db_dir = os.path.join(PROJECT_ROOT, "data")
    os.makedirs(db_dir, exist_ok=True)
    # 启动兼容迁移：如果 data_store/ 为空但旧 data/ 有数据，自动复制
    _auto_migrate_if_needed(old_db_dir, db_dir)
    db = Database(os.path.join(db_dir, "behavior_box.db"))
    db.open()
    event_store = EventStore(db)
    set_experiments_root(os.path.join(PROJECT_ROOT, "data_store", "experiments"))
    yield
    if engine:
        await engine.stop()
    if bus:
        await bus.stop_all()
    if db:
        db.close()


def _auto_migrate_if_needed(old_dir: str, new_dir: str):
    """启动时自动迁移：如果新目录为空但旧目录有运行时数据，自动复制到新目录"""
    import shutil
    new_items = os.listdir(new_dir)
    if new_items:
        return  # data_store/ 已有数据，不需迁移
    if not os.path.isdir(old_dir):
        return  # 旧目录不存在
    old_items = [f for f in os.listdir(old_dir)
                 if os.path.isfile(os.path.join(old_dir, f)) and not f.endswith(".py")]
    if not old_items and not os.path.isdir(os.path.join(old_dir, "experiments")):
        return  # 旧目录无可迁移数据
    logger.info("检测到 data_store/ 为空，从 data/ 自动迁移运行时数据...")
    # 复制根目录的非 .py 文件
    for f in old_items:
        src = os.path.join(old_dir, f)
        dst = os.path.join(new_dir, f)
        shutil.copy2(src, dst)
    # 复制 experiments/ 目录
    old_exp = os.path.join(old_dir, "experiments")
    new_exp = os.path.join(new_dir, "experiments")
    if os.path.isdir(old_exp):
        os.makedirs(new_exp, exist_ok=True)
        for item in os.listdir(old_exp):
            src = os.path.join(old_exp, item)
            dst = os.path.join(new_exp, item)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    logger.info("自动迁移完成，旧 data/ 目录保留不变")


app = FastAPI(title="行为学训练盒", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("action") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


async def broadcast(msg: dict):
    dead = set()
    for ws in list(ws_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


app.mount("/static", StaticFiles(directory=os.path.join(PROJECT_ROOT, "web")), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(PROJECT_ROOT, "web", "index.html"))


@app.get("/dashboard")
async def dashboard():
    return FileResponse(os.path.join(PROJECT_ROOT, "web", "project-dashboard.html"))


@app.get("/api/status")
async def api_status():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "engine": engine.state.value if engine else "idle",
        "session": session.state.value if session else "none",
        "ws_clients": len(ws_clients),
    }


@app.post("/api/experiment/start-mock")
async def api_start_mock(data: dict = None, count: int = 10, subject_id: str = "", exp_name: str = "", notes: str = "", max_duration_min: int = 0, experiment_id: str = ""):
    global bus, engine, session, _experiment_active
    if data:
        count = data.get("count", count)
        subject_id = data.get("subject_id", subject_id)
        exp_name = data.get("exp_name", exp_name)
        notes = data.get("notes", notes)
        max_duration_min = data.get("max_duration_min", max_duration_min)
        experiment_id = data.get("experiment_id", experiment_id)
    use_camera_source = data.get("use_camera_source", False) if data else False
    camera_index = data.get("camera_index", 0) if data else 0
    if count < 1 and max_duration_min < 1:
        raise HTTPException(400, "触发次数和运行时间至少有一个必须大于 0")
    async with _mutex:
        if _experiment_active:
            raise HTTPException(400, "实验正在运行中，请先停止")

        # 主问题修复: 有关联流程的实验不能用 start-mock,引导用户去流程编辑器
        if experiment_id:
            existing_flow = load_flow(experiment_id)
            if existing_flow and existing_flow.get("nodes") and len(existing_flow.get("nodes", {})) > 0:
                raise HTTPException(400, "该实验已关联流程设计,请切换到「流程编辑器」标签页,点击「▶ 运行流程」按钮启动")

        # Bug #6: Stop any existing engine/bus/session before overwriting
        if engine:
            await engine.stop()
        if bus:
            try:
                await bus.stop_all()
            except Exception:
                pass
        if session:
            session.stop()

        duration_s = max_duration_min * 60 if max_duration_min > 0 else (count * 1.8 if count > 0 else 30) + 5
        s = Session()
        safe_name = exp_name or f"手动触发-{count}次"
        config = ExperimentConfig(
            name=safe_name,
            description=notes or "手动信号测试",
            session_timeout_ms=int(max(duration_s, 30) * 2000),
        )
        s.load(config)
        event_store.ensure_session(s.id, name=config.name, experiment_id=experiment_id, config_json=json.dumps({
            "name": safe_name, "subject_id": subject_id, "notes": notes, "count": count,
        }, ensure_ascii=False))

        b = SignalBus()
        if use_camera_source:
            from ui.camera import CameraSource, MotionConfig
            cam = CameraSource(
                source_id="camera:0",
                camera_index=camera_index,
                fps=15,
                motion=MotionConfig(enabled=True, threshold=25, min_area=500),
            )
            b.register(cam)
        else:
            b.register(MockSignalSource("mock:0", event_interval_ms=1500))
        b.register(TimerSource("timer:0", tick_interval_ms=1000))

        e = Engine()

        def _on_signal(sig):
            event_store.append_event(
                session_id=s.id,
                event_type=f"{sig.source_type.value}_{sig.signal_id.split(':')[-1]}" if sig.source_type.value != "mock" else "manual_trigger",
                ts_ms=sig.ts_ms,
                signal_id=f"{sig.source_id}:{sig.signal_id}",
                raw_payload={"value": sig.value, "data": sig.data},
            )
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "signal", "session_id": s.id, "signal_id": f"{sig.source_id}:{sig.signal_id}", "ts": sig.ts_ms, "value": str(sig.value)}),
                _loop,
            )

        b.set_on_signal(_on_signal)

        async def run():
            global _experiment_active
            try:
                await b.start_all()
                s.start()
                start_ts = time.time()
                deadline = start_ts + duration_s
                max_events = count if count > 0 else float('inf')
                while time.time() < deadline:
                    await asyncio.sleep(0.1)
                    event_count = len(event_store.get_events(s.id))
                    if event_count >= max_events:
                        logger.info(f"达到最大触发次数 {int(max_events)}，停止")
                        break
                    if time.time() >= deadline:
                        break
                await b.stop_all()
                s.stop()
                event_store.update_session_state(s.id, s.state.value)
                raw_events = event_store.get_events(s.id)
                processor = DataProcessor()
                structured = processor.to_structured(processor.process(raw_events), session_id=s.id, subject_id=subject_id, session_name=safe_name)
                csv_path = export_session_csv(structured, s.id, os.path.join(PROJECT_ROOT, "data_store"), subject_id=subject_id, session_name=safe_name)
                await broadcast({"type": "mock_complete", "session_id": s.id, "event_count": len(raw_events), "csv_path": csv_path})
            except Exception as exc:
                logger.exception(f"实验运行异常: {exc}")
            finally:
                _experiment_active = False

        _experiment_active = True
        asyncio.create_task(run())
        session = s
        engine = e
        bus = b
    return {"status": "started", "session_id": s.id, "target": count}


@app.post("/api/experiment/stop")
async def api_stop():
    global engine, bus, session, _experiment_active
    _experiment_active = False
    if engine:
        await engine.stop()
    if session:
        session.stop()
    if bus:
        try:
            await bus.stop_all()
        except Exception:
            pass
    return {"status": "stopped", "session_state": session.state.value if session else "none"}


@app.get("/api/experiment/state")
async def api_experiment_state():
    return {
        "engine": "running" if _experiment_active else "idle",
        "session": session.state.value if session else "none",
        "session_id": session.id if session else "",
    }


@app.get("/api/sessions")
async def api_sessions():
    return {"sessions": event_store.get_sessions(limit=50)}


@app.get("/api/sessions/{session_id}/events")
async def api_session_events(session_id: str):
    return {"events": event_store.get_events(session_id)}


@app.get("/api/sessions/{session_id}/export")
async def api_session_export(session_id: str):
    sess = event_store.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    raw = event_store.get_events(session_id)
    processor = DataProcessor()
    subject_id = ""
    session_name = ""
    if sess.get("config_json"):
        try:
            cfg = json.loads(sess["config_json"])
            subject_id = cfg.get("subject_id", "")
            session_name = cfg.get("name", sess.get("name", ""))
        except Exception:
            pass
    structured = processor.to_structured(processor.process(raw), session_id=session_id, subject_id=subject_id, session_name=session_name)
    csv_path = export_session_csv(structured, session_id, os.path.join(PROJECT_ROOT, "data_store"), subject_id=subject_id, session_name=session_name)
    return {"csv_path": csv_path, "count": len(structured)}


@app.get("/api/flows")
async def api_flows():
    flows_dir = os.path.join(PROJECT_ROOT, "data_store")
    flows = []
    for f in os.listdir(flows_dir):
        if f.endswith(".json") and f.startswith("flow_"):
            with open(os.path.join(flows_dir, f), "r") as fh:
                data = json.load(fh)
                flows.append({"id": f, "name": data.get("name", f)})
    return {"flows": flows}


def _safe_filename(name: str) -> str:
    import re
    safe = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', name)
    return safe[:64]


@app.post("/api/flows/save")
async def api_save_flow(data: dict):
    name = data.get("name", "unnamed")
    # Bug #9: Reject whitespace-only names
    if not name or not name.strip():
        raise HTTPException(400, "请输入流程名称")
    name = name.strip()
    flow_data = data.get("flow", {})
    safe_name = _safe_filename(name)
    filename = f"flow_{safe_name}_{int(time.time())}.json"
    path = os.path.join(PROJECT_ROOT, "data_store", filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flow_data, f, ensure_ascii=False, indent=2)
    return {"filename": filename}


def _safe_load_filename(filename: str) -> str:
    """Validate filename for loading — prevent path traversal attacks.

    CR-7: Reject filenames containing '../' or other path traversal patterns.
    Only allow filenames matching the expected pattern: flow_*.json
    """
    import re
    # Must match expected flow filename pattern
    if not re.match(r'^flow_[\w\u4e00-\u9fff\-]+_\d+\.json$', filename):
        raise HTTPException(400, "无效的文件名")
    # Additional safety: resolve to absolute path and verify it's under data_store
    safe = os.path.normpath(filename)
    if '..' in safe or safe.startswith('/'):
        raise HTTPException(400, "无效的文件名")
    return safe


@app.get("/api/flows/{filename}")
async def api_load_flow(filename: str):
    safe_filename = _safe_load_filename(filename)
    path = os.path.join(PROJECT_ROOT, "data_store", safe_filename)
    if not os.path.exists(path):
        raise HTTPException(404, "流程文件不存在")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/flows/validate")
async def api_validate_flow(data: dict):
    try:
        flow = FlowGraph.from_dict(data)
        # Gather available signal IDs for semantic validation (Bug #7)
        available_signals = [s["id"] for s in _get_available_sources()]
        result = validate_flow(flow, available_signals=available_signals)
        return {"valid": result.valid, "errors": result.errors, "warnings": result.warnings}
    except Exception as e:
        return {"valid": False, "errors": [str(e)], "warnings": []}


@app.post("/api/experiment/run-flow")
async def api_run_flow(data: dict):
    global bus, engine, session, _experiment_active
    flow_data = data.get("flow", {})
    experiment_id = data.get("experiment_id", "")

    # G3-FIN-1: 如果提供了 experiment_id 且 flow 为空，从实验文件夹加载流程
    if experiment_id and not flow_data:
        loaded = load_flow(experiment_id)
        if loaded:
            flow_data = loaded
        else:
            raise HTTPException(400, "实验没有关联的流程，请先保存流程")

    duration_s = data.get("duration", 30)
    subject_id = data.get("subject_id", "")
    exp_name = data.get("exp_name", "")
    use_camera_source = data.get("use_camera_source", False)
    camera_index = data.get("camera_index", 0)
    safe_name = exp_name or flow_data.get("name", "流程实验")
    if duration_s < 1 or duration_s > 86400:
        raise HTTPException(400, "运行时长需在 1~86400 秒之间")
    try:
        flow = FlowGraph.from_dict(flow_data)
    except Exception as e:
        raise HTTPException(400, f"流程解析失败: {e}")

    available_signals = [s["id"] for s in _get_available_sources()]
    result = validate_flow(flow, available_signals=available_signals)
    if not result.valid:
        raise HTTPException(400, f"流程校验失败: {result.errors}")

    # Bug #6: Check before entering mutex (fast path)
    if _experiment_active:
        raise HTTPException(400, "实验正在运行中，请先停止")

    async with _mutex:
        if _experiment_active:
            raise HTTPException(400, "实验正在运行中，请先停止")

        # Bug #6: Stop any existing engine/bus/session before overwriting
        if engine:
            await engine.stop()
        if bus:
            try:
                await bus.stop_all()
            except Exception:
                pass
        if session:
            session.stop()

        s = Session()
        config = ExperimentConfig(name=safe_name, description="流程实验", session_timeout_ms=duration_s * 2000, flow=flow)
        s.load(config)
        event_store.ensure_session(s.id, name=config.name, config_json=json.dumps({
            "name": safe_name, "subject_id": subject_id, "flow_name": flow.name,
        }, ensure_ascii=False))

        e = Engine()
        e.set_send_action(lambda cmd: _on_action(cmd, s))
        e.set_on_engine_event(lambda kind, data: _on_engine_evt(kind, data, s))

        b = SignalBus()
        if use_camera_source:
            from ui.camera import CameraSource, MotionConfig
            cam = CameraSource(
                source_id="camera:0",
                camera_index=camera_index,
                fps=15,
                motion=MotionConfig(enabled=True, threshold=25, min_area=500),
            )
            b.register(cam)
        else:
            b.register(MockSignalSource("mock:0", event_interval_ms=1500))
        b.register(TimerSource("timer:0", tick_interval_ms=1000))

        collected_signals = []

        def _on_signal(event: SignalEvent):
            collected_signals.append(event)
            event_store.append_event(
                session_id=s.id,
                event_type=f"{event.source_type.value}_{event.signal_id.split(':')[-1]}",
                ts_ms=event.ts_ms,
                signal_id=f"{event.source_id}:{event.signal_id}",
                raw_payload={"value": event.value, "data": event.data},
            )
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "signal", "session_id": s.id, "signal_id": f"{event.source_id}:{event.signal_id}", "ts": event.ts_ms, "value": str(event.value)}),
                _loop,
            )
            asyncio.run_coroutine_threadsafe(e.feed_signal(event), _loop)

        b.set_on_signal(_on_signal)

        async def run():
            global _experiment_active
            try:
                await b.start_all()
                await e.start(s)
                start_ts = time.time()
                while time.time() - start_ts < duration_s:
                    await asyncio.sleep(0.1)
                await e.stop()
                await b.stop_all()
                await asyncio.sleep(0.1)
                event_store.update_session_state(s.id, s.state.value)
                raw = event_store.get_events(s.id)
                # 统计 RECORD 事件数（node_executed 中 type=record/record_end）
                record_count = 0
                for ev in raw:
                    if ev.get("event_type") == "node_executed":
                        try:
                            rp = json.loads(ev.get("raw_payload", "{}")) if isinstance(ev.get("raw_payload"), str) else (ev.get("raw_payload") or {})
                            if rp.get("type") in ("record", "record_end"):
                                record_count += 1
                        except (json.JSONDecodeError, TypeError):
                            pass
                processor = DataProcessor()
                structured = processor.to_structured(processor.process(raw), session_id=s.id, subject_id=subject_id, session_name=safe_name)
                csv_path = export_session_csv(structured, s.id, os.path.join(PROJECT_ROOT, "data_store"), subject_id=subject_id, session_name=safe_name)
                await broadcast({"type": "flow_complete", "session_id": s.id, "event_count": len(raw), "record_count": record_count, "csv_path": csv_path})
            except Exception as exc:
                logger.exception(f"流程实验异常: {exc}")
            finally:
                _experiment_active = False

        _experiment_active = True
        asyncio.create_task(run())
        session = s
        engine = e
        bus = b
    return {"status": "started", "session_id": s.id, "flow_name": flow.name}


async def _on_action(cmd: dict, s: Session) -> bool:
    event_store.append_event(
        session_id=s.id, event_type="output_executed",
        ts_ms=int(time.time() * 1000), node_id=cmd.get("node_id", ""),
        actuator_id=cmd.get("actuator_id", ""), action_type=cmd.get("action", ""),
        raw_payload={"duration_ms": cmd.get("duration_ms", 0)},
    )
    return True


def _on_engine_evt(kind: str, data: dict, s: Session):
    event_store.append_event(
        session_id=s.id, event_type=kind, ts_ms=int(time.time() * 1000),
        node_id=data.get("node_id", ""), signal_id=data.get("signal_id", ""),
        raw_payload=data,
    )
    # 实时推送引擎事件到前端 WebSocket（监控面板用）
    # 加 try/except 防止 event loop 未就绪时崩溃
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast({
            "type": "engine_event",
            "kind": kind,
            "data": data,
            "session_id": s.id,
        }))
    except RuntimeError:
        # 没有运行中的 event loop（理论上不会发生，但防御性处理）
        pass


@app.post("/api/device/connect")
async def api_device_connect(data: dict):
    global _mock_device_mgr
    host = data.get("host", "192.168.4.1")
    port = data.get("port", 8080)
    try:
        from protocol.device_manager import DeviceManager, DeviceInfo
        mgr = DeviceManager()
        info = DeviceInfo(device_id="web_connect", name="Web GUI", transport_type="ws", host=host, port=port)
        import asyncio
        ok = await asyncio.wait_for(mgr.connect_ws(info), timeout=5)
        if ok:
            _mock_device_mgr = mgr
            return {"ok": True, "device_id": mgr.device_id}
        return {"ok": False, "error": "连接超时或拒绝"}
    except ImportError:
        return {"ok": False, "error": "device_manager 模块未就绪"}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "连接超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/device/disconnect")
async def api_device_disconnect():
    global _mock_device_mgr
    if _mock_device_mgr:
        await _mock_device_mgr.disconnect()
        _mock_device_mgr = None
    return {"ok": True}


@app.post("/api/experiment/camera-event")
async def api_camera_event(data: dict):
    zone = data.get("zone", "未知区域")
    event = data.get("event", "unknown")
    ts = data.get("ts", int(time.time() * 1000))
    experiment_id = data.get("experiment_id", "")
    signal_id = f"camera:{zone}:{event}"
    session_key = f"camera_{experiment_id}" if experiment_id else "camera_detection"
    if event_store:
        event_store.ensure_session(session_key, name="摄像头检测", experiment_id=experiment_id)
        event_store.append_event(
            session_id=session_key,
            event_type=f"camera_{event}",
            ts_ms=ts,
            signal_id=signal_id,
            raw_payload={"zone": zone, "event": event, "experiment_id": experiment_id},
        )
    if engine and engine.is_running and _loop:
        from protocol.signal_source import SignalEvent, SourceType
        sig = SignalEvent(
            source_id="camera:0",
            source_type=SourceType.CAMERA,
            signal_id=signal_id,
            ts_ms=ts,
            value=1 if event == "enter" else 0,
            data={"zone": zone, "event": event, "experiment_id": experiment_id},
        )
        asyncio.run_coroutine_threadsafe(engine.feed_signal(sig), _loop)
    return {"ok": True}


# === 实验管理 API ===

@app.post("/api/experiments")
async def api_create_experiment(data: dict):
    hardware_count = data.get("hardware_count", 0)
    if hardware_count < 0 or hardware_count > 8:
        raise HTTPException(400, "设备数量必须在 0~8 之间")
    try:
        exp_id = create_experiment(
            name=data.get("name", ""),
            subject_id=data.get("subject_id", ""),
            species=data.get("species", ""),
            subject_notes=data.get("subject_notes", ""),
            notes=data.get("notes", ""),
            max_duration_min=data.get("max_duration_min", 30),
            max_trigger_count=data.get("max_trigger_count", 50),
            trigger_manual=data.get("trigger_manual", True),
            trigger_camera=data.get("trigger_camera", False),
            trigger_hardware=data.get("trigger_hardware", False),
            hardware_count=hardware_count,
            camera_zones=data.get("camera_zones", []),
            start_mode=data.get("start_mode", "manual"),
            timer_config=data.get("timer_config", {}),
            save_path=data.get("save_path", ""),
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"id": exp_id}


@app.get("/api/experiments")
async def api_list_experiments():
    return {"experiments": list_experiments()}


@app.get("/api/experiments/camera-statuses")
async def api_camera_statuses():
    return {"statuses": get_all_camera_statuses()}


@app.get("/api/experiments/{exp_id}")
async def api_get_experiment(exp_id: str):
    exp = get_experiment(exp_id)
    if not exp:
        raise HTTPException(404, "实验不存在")
    # Attach folder path
    folder = exp.get("_folder", "")
    if folder:
        exp["folder_path"] = folder
    # D-30: 预加载摄像头信号源到注册中心
    from protocol.device_registry import load_camera_sources
    camera_config = _load_camera_config(exp_id)
    if camera_config:
        load_camera_sources(exp_id, camera_config)
    return exp


@app.get("/api/experiments/{exp_id}/sessions")
async def api_experiment_sessions(exp_id: str):
    sessions = event_store.get_sessions_by_experiment(exp_id)
    return {"sessions": sessions}


@app.post("/api/experiments/batch-delete")
async def api_batch_delete_experiments(data: dict):
    exp_ids = data.get("experiment_ids", [])
    if not exp_ids or not isinstance(exp_ids, list):
        raise HTTPException(400, "请提供要删除的实验 ID 列表")
    deleted = batch_delete_experiments(exp_ids)
    return {"deleted": deleted}


@app.post("/api/experiments/{exp_id}")
async def api_update_experiment(exp_id: str, data: dict):
    ok = update_experiment(exp_id, data)
    if not ok:
        raise HTTPException(404, "实验不存在")
    return {"ok": True}


@app.delete("/api/experiments/{exp_id}")
async def api_delete_experiment(exp_id: str):
    ok = delete_experiment(exp_id)
    if not ok:
        raise HTTPException(404, "实验不存在")
    return {"ok": True}


@app.post("/api/experiments/{exp_id}/clone")
async def api_clone_experiment(exp_id: str, data: dict):
    try:
        new_id = clone_experiment(exp_id, data.get("new_name", ""))
    except ValueError as e:
        raise HTTPException(409, str(e))
    if not new_id:
        raise HTTPException(404, "源实验不存在")
    return {"id": new_id}


@app.post("/api/experiments/{exp_id}/open-folder")
async def api_open_experiment_folder(exp_id: str):
    exp = get_experiment(exp_id)
    if not exp:
        raise HTTPException(404, "实验不存在")
    folder = exp.get("_folder", "")
    if folder and os.path.isdir(folder):
        subprocess.Popen(["open", folder])
    return {"ok": True}


@app.post("/api/experiments/{exp_id}/flow/save")
async def api_save_experiment_flow(exp_id: str, data: dict):
    """保存流程到实验文件夹 (flow.json)，模仿 camera.json 设计模式（D-21）"""
    flow_data = data.get("flow", {})
    if not flow_data:
        raise HTTPException(400, "流程数据不能为空")
    ok = save_flow(exp_id, flow_data)
    if not ok:
        raise HTTPException(404, "实验不存在")
    return {"ok": True}


@app.get("/api/experiments/{exp_id}/flow/load")
async def api_load_experiment_flow(exp_id: str):
    """从实验文件夹加载流程 (flow.json)"""
    flow = load_flow(exp_id)
    if flow is None:
        # 返回空流程（含默认 START/END），不报错
        return {"nodes": {}, "edges": []}
    return flow


# === 目录选择器 ===


@app.post("/api/browse-folder")
async def api_browse_folder():
    """打开原生目录选择器，返回用户选择的路径。"""
    import platform

    if platform.system() == "Darwin":
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e",
                'set folderPath to choose folder with prompt "选择实验保存位置:"\n'
                "return POSIX path of folderPath",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
                if proc.returncode == 0:
                    return {"path": stdout.decode().strip()}
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except (FileNotFoundError, Exception):
            pass

    # 非 macOS 或 osascript 失败：尝试 tkinter
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="选择实验保存位置")
        root.destroy()
        if path:
            return {"path": path}
    except Exception:
        pass

    return {"path": ""}


# === 摄像头配置持久化 ===


def _get_camera_config_path(experiment_id: str = None) -> str:
    if experiment_id:
        exp = get_experiment(experiment_id)
        if exp and exp.get("_folder"):
            return os.path.join(exp["_folder"], "camera.json")
    return _camera_config_path


def _load_camera_config(experiment_id: str = None) -> dict:
    path = _get_camera_config_path(experiment_id)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_camera_config(config: dict, experiment_id: str = None):
    path = _get_camera_config_path(experiment_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


@app.post("/api/camera/config")
async def api_camera_save_config(data: dict):
    config = data.get("config", {})
    experiment_id = data.get("experiment_id", None)
    _save_camera_config(config, experiment_id)
    # D-30: 配置保存后清除注册中心缓存，下次 _get_available_sources 会重新加载
    from protocol.device_registry import invalidate_registry
    invalidate_registry(experiment_id or "")
    invalidate_registry("")  # 同时清除全局缓存（防止前端不带 experiment_id 时拿到旧数据）
    return {"ok": True}


@app.get("/api/camera/config")
async def api_camera_load_config(experiment_id: str = None):
    return {"config": _load_camera_config(experiment_id)}


@app.get("/api/camera/config/exists")
async def api_camera_config_exists(experiment_id: str = None):
    path = _get_camera_config_path(experiment_id)
    return {"exists": os.path.isfile(path), "path": path}


@app.get("/api/camera/config/view")
async def api_camera_config_view(experiment_id: str = None):
    path = _get_camera_config_path(experiment_id)
    if not os.path.isfile(path):
        raise HTTPException(404, "配置文件不存在，请先保存配置")
    return FileResponse(path, media_type="application/json", content_disposition_type="inline")


def _get_background_path(experiment_id: str = None) -> str:
    config_path = _get_camera_config_path(experiment_id)
    return os.path.join(os.path.dirname(config_path), "background.png")


@app.post("/api/camera/background")
async def api_camera_save_background(data: dict):
    experiment_id = data.get("experiment_id", None)
    image_b64 = data.get("image", "")
    if not image_b64:
        raise HTTPException(400, "缺少图片数据")
    import base64
    path = _get_background_path(experiment_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(base64.b64decode(image_b64.split(",")[-1] if "," in image_b64 else image_b64))
    return {"ok": True, "path": path}


@app.get("/api/camera/background")
async def api_camera_load_background(experiment_id: str = None):
    path = _get_background_path(experiment_id)
    if not os.path.isfile(path):
        raise HTTPException(404, "暂无保存的背景图片")
    return FileResponse(path, media_type="image/png")


def _get_available_sources(experiment_id: str | None = None) -> list[dict]:
    """获取可用信号源列表（从注册中心读取，供校验器和 API 共用）

    D-30: 统一从注册中心读取，不再硬编码。支持：
    - 内置 mock/timer 信号源
    - 摄像头 zone 自动注册的信号源
    - 硬件设备注册的信号源
    """
    from protocol.device_registry import get_registry, load_camera_sources
    eid = experiment_id or ""
    reg = get_registry(eid)

    # 自动加载该实验的摄像头配置信号源
    if eid:
        camera_config = _load_camera_config(eid)
        if camera_config:
            load_camera_sources(eid, camera_config)

    entries = reg.get_all_sources(eid)
    result = []
    for e in entries:
        result.append({"id": e.source_id, "label": e.display_name, "type": e.source_type})
        for sig in e.produced_signals:
            result.append({"id": sig, "label": f"{e.display_name}:{sig}", "type": e.source_type})
    return result


@app.get("/api/sources")
async def api_list_sources(experiment_id: str = None):
    """返回所有可用信号源列表（从注册中心读取）"""
    return {"sources": _get_available_sources(experiment_id)}


# === D-30 注册中心 API ===


@app.get("/api/registry/sources")
async def api_registry_sources(experiment_id: str = None):
    """获取所有信号源（含详细信息）"""
    from protocol.device_registry import get_registry
    reg = get_registry(experiment_id or "")
    return {"entries": [{
        "source_id": e.source_id,
        "display_name": e.display_name,
        "source_type": e.source_type,
        "status": e.status.value,
        "produced_signals": e.produced_signals,
    } for e in reg.get_all_sources(experiment_id or "")]}


@app.get("/api/registry/actuators")
async def api_registry_actuators(experiment_id: str = None):
    """获取所有执行器（供 EXECUTE 节点下拉）"""
    from protocol.device_registry import get_registry
    reg = get_registry(experiment_id or "")
    return {"entries": [{
        "source_id": e.source_id,
        "display_name": e.display_name,
        "source_type": e.source_type,
    } for e in reg.get_all_actuators(experiment_id or "")]}


@app.get("/api/registry/events")
async def api_registry_events(experiment_id: str = None):
    """获取所有记录事件类型（供 RECORD 节点下拉）"""
    from protocol.device_registry import get_registry
    reg = get_registry(experiment_id or "")
    return {"entries": [{
        "source_id": e.source_id,
        "display_name": e.display_name,
    } for e in reg.get_all_event_types(experiment_id or "")]}


@app.get("/api/stats/daily")
async def api_daily_stats(days: int = 7):
    return {"stats": event_store.get_daily_aggregation("", days=days)}


@app.get("/api/dashboard/data")
async def api_dashboard_data():
    """返回项目仪表盘的实时数据"""
    import subprocess
    try:
        script_path = os.path.join(PROJECT_ROOT, "scripts", "dashboard_data.py")
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {
            "error": f"Dashboard script error (exit {result.returncode})",
            "stderr": result.stderr[:500],
        }
    except subprocess.TimeoutExpired:
        return {"error": "Dashboard script timed out"}
    except Exception as e:
        return {"error": str(e)}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="行为学训练盒上位机")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"监听端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    args = parser.parse_args()

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)

    def _shutdown(signum, frame):
        """优雅关闭：通知 uvicorn 停止，触发 lifespan 的 yield 后清理"""
        if server:
            server.should_exit = True

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        # lifespan yield 已执行 engine.stop() + bus.stop_all() + db.close()
        logger = logging.getLogger("BehaviorBox")
        logger.info("服务器已优雅关闭")


if __name__ == "__main__":
    main()
