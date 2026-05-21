"""
运行期调度引擎

按流程图消费设备事件: 触发 → 条件/延时/循环 → 下发动作指令
会话级状态机，异常分流（断连/超时/冲突指令 → 按预设策略降级 + 记录决策轨迹）
"""

from __future__ import annotations

import asyncio
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, Callable, Awaitable, Set

from .session import Session, SessionState
from .flow_model import (
    FlowGraph, FlowNode, Edge, NodePort,
    NodeType, PortDirection,
)
from protocol.messages import EventKind

logger = logging.getLogger("BehaviorBox.Engine")


class EngineState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"


class ExceptionPolicy(str, Enum):
    RETRY = "retry"
    SKIP = "skip"
    TERMINATE = "terminate"


@dataclass
class EngineContext:
    """引擎运行时上下文"""
    session: Session
    flow: FlowGraph
    current_node_id: str = ""
    variables: Dict[str, Any] = field(default_factory=dict)
    counters: Dict[str, int] = field(default_factory=dict)
    loop_iterations: Dict[str, int] = field(default_factory=dict)
    trigger_history: Dict[str, float] = field(default_factory=dict)
    pending_actions: int = 0
    default_exception_policy: ExceptionPolicy = ExceptionPolicy.TERMINATE

    def set_variable(self, name: str, value: Any):
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)

    def inc_counter(self, name: str) -> int:
        current = self.counters.get(name, 0) + 1
        self.counters[name] = current
        return current


@dataclass
class EngineEvent:
    kind: str
    data: Dict[str, Any] = field(default_factory=dict)
    ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    @property
    def is_trigger(self) -> bool:
        return self.kind in ("input_triggered", "signal")

    @property
    def is_signal(self) -> bool:
        return self.kind == "signal"

    @property
    def is_output(self) -> bool:
        return self.kind == "output_executed"

    @property
    def is_error(self) -> bool:
        return self.kind.startswith("error_") or self.kind == "io_error"


class Engine:
    """
    运行期调度引擎

    职责:
    1. 按流程图拓扑消费设备事件
    2. 维护运行时上下文（变量、计数器、循环状态）
    3. 驱动节点执行（触发→条件→延时→循环→执行→记录→异常处理）
    4. 将执行指令下发到通信层
    """

    def __init__(self):
        self._state: EngineState = EngineState.IDLE
        self._ctx: Optional[EngineContext] = None
        self._event_queue: Optional[asyncio.Queue] = None
        self._run_task: Optional[asyncio.Task] = None

        self._send_action: Optional[Callable[[Dict[str, Any]], Awaitable[bool]]] = None
        self._on_engine_event: Optional[Callable[[str, Dict[str, Any]], None]] = None
        self._on_state_change: Optional[Callable[[EngineState, EngineState], None]] = None

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == EngineState.RUNNING

    def set_send_action(self, cb: Callable[[Dict[str, Any]], Awaitable[bool]]):
        self._send_action = cb

    def set_on_engine_event(self, cb: Callable[[str, Dict[str, Any]], None]):
        self._on_engine_event = cb

    def set_on_state_change(self, cb: Callable[[EngineState, EngineState], None]):
        self._on_state_change = cb

    def _set_state(self, new_state: EngineState):
        old = self._state
        self._state = new_state
        if self._on_state_change:
            try:
                self._on_state_change(old, new_state)
            except Exception:
                logger.exception("on_state_change error")

    async def start(self, session: Session):
        if not session.config or not session.config.flow:
            raise RuntimeError("会话未加载实验配置或流程图")

        self._event_queue = asyncio.Queue()

        self._ctx = EngineContext(
            session=session,
            flow=session.config.flow,
        )
        session.start()
        self._set_state(EngineState.RUNNING)
        self._run_task = asyncio.create_task(self._run_loop())
        logger.info(f"引擎启动: session={session.id}")

    async def stop(self):
        if self._state in (EngineState.IDLE, EngineState.STOPPED):
            return
        self._set_state(EngineState.STOPPING)
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            self._run_task = None
        if self._ctx:
            self._ctx.session.stop()
        self._set_state(EngineState.STOPPED)
        logger.info("引擎已停止")

    async def pause(self):
        if self._state != EngineState.RUNNING:
            return
        self._ctx.session.pause()
        self._set_state(EngineState.PAUSED)

    async def resume(self):
        if self._state != EngineState.PAUSED:
            return
        self._ctx.session.resume()
        self._set_state(EngineState.RUNNING)

    async def feed_event(self, event: EngineEvent):
        if self._state not in (EngineState.RUNNING, EngineState.PAUSED):
            return
        if self._event_queue is None:
            return
        await self._event_queue.put(event)

    async def feed_signal(self, signal):
        """接收来自 SignalBus 的统一信号事件"""
        from protocol.signal_source import SignalEvent
        if isinstance(signal, SignalEvent):
            event = EngineEvent(
                kind="signal",
                data=signal.to_engine_event(),
                ts_ms=signal.ts_ms,
            )
            await self.feed_event(event)
        else:
            await self.feed_event(EngineEvent(
                kind="signal",
                data=signal if isinstance(signal, dict) else {"raw": str(signal)},
            ))

    async def _run_loop(self):
        """主调度循环"""
        start_node = self._ctx.flow.get_start_node()
        if not start_node:
            logger.error("流程图缺少开始节点")
            await self.stop()
            return

        self._ctx.current_node_id = start_node.id
        await self._step_to_next(start_node)

        while self._state == EngineState.RUNNING:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                await self._handle_event(event)
            except asyncio.TimeoutError:
                if self._ctx.session.check_timeout():
                    logger.warning("会话超时，自动停止")
                    await self.stop()
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("调度循环异常")

    async def _handle_event(self, event: EngineEvent):
        current_node = self._ctx.flow.nodes.get(self._ctx.current_node_id)
        if not current_node:
            return

        if event.is_trigger:
            await self._process_trigger(current_node, event)
        elif event.is_error:
            await self._handle_error(current_node, event)

    async def _process_trigger(self, node: FlowNode, event: EngineEvent):
        if node.node_type != NodeType.TRIGGER:
            return

        trigger_type = node.params.get("trigger", "rising")
        node_signal_id = node.params.get("signal_id", "")

        if event.is_signal:
            event_signal_id = event.data.get("signal_id", "")
            event_value = event.data.get("value")
            event_source_type = event.data.get("source_type", "")

            full_match = (
                event_signal_id == node_signal_id
                or f"{event.data.get('source_id','')}:{event_signal_id}" == node_signal_id
            )
            if not full_match:
                return

            if event_signal_id.endswith(":motion_start"):
                matched = trigger_type in ("rising", "change", "high")
            elif event_signal_id.endswith(":motion_stop"):
                matched = trigger_type in ("falling", "change", "low")
            elif event_signal_id.endswith(":motion_active"):
                matched = trigger_type in ("high", "change")
            elif event_value is not None:
                if trigger_type == "high":
                    matched = bool(event_value)
                elif trigger_type == "low":
                    matched = not bool(event_value)
                elif trigger_type == "rising":
                    matched = bool(event_value)
                elif trigger_type == "falling":
                    matched = not bool(event_value)
                else:
                    matched = True
            else:
                matched = True

            if not matched:
                return
        else:
            event_signal = event.data.get("signal_id", "")
            event_trigger = event.data.get("trigger", "")
            if event_signal != node_signal_id:
                return
            if trigger_type != "change" and event_trigger != trigger_type:
                return

        debounce_ms = node.params.get("debounce_ms", 0)
        if debounce_ms > 0:
            last = self._ctx.trigger_history.get(node.id, 0)
            now = time.time() * 1000
            if now - last < debounce_ms:
                return
            self._ctx.trigger_history[node.id] = now

        logger.info(f"触发节点 [{node.id}] 匹配: signal={node_signal_id}, trigger={trigger_type}")
        self._emit_engine_event("node_triggered", {"node_id": node.id, "signal_id": node_signal_id})

        await self._step_to_next(node)

    async def _step_to_next(self, node: FlowNode):
        outgoing = self._ctx.flow.get_outgoing_edges(node.id)
        if not outgoing:
            if node.node_type != NodeType.END:
                logger.warning(f"节点 [{node.id}] 没有出边，流程终止")
            await self.stop()
            return

        edge = outgoing[0]
        next_node = self._ctx.flow.nodes.get(edge.target.node_id)
        if next_node:
            await self._execute_node(next_node, edge)

    async def _execute_node(self, node: FlowNode, incoming_edge: Edge):
        logger.debug(f"执行节点: [{node.id}] {node.node_type.value}")

        if node.node_type == NodeType.END:
            self._emit_engine_event("node_executed", {"node_id": node.id, "type": "end"})
            await self.stop()
            return

        if node.node_type == NodeType.DELAY:
            await self._execute_delay(node)

        elif node.node_type == NodeType.CONDITION:
            await self._execute_condition(node)

        elif node.node_type == NodeType.EXECUTE:
            await self._execute_action(node)

        elif node.node_type == NodeType.LOOP:
            await self._execute_loop(node)

        elif node.node_type == NodeType.VARIABLE:
            await self._execute_variable(node)

        elif node.node_type == NodeType.RECORD:
            await self._execute_record(node)

        elif node.node_type == NodeType.EXCEPTION:
            await self._execute_exception_handler(node)

        elif node.node_type == NodeType.START:
            await self._step_to_next(node)

        elif node.node_type == NodeType.TRIGGER:
            self._ctx.current_node_id = node.id

    async def _execute_delay(self, node: FlowNode):
        ms = node.params.get("duration_ms", 1000)
        logger.info(f"延时 {ms}ms: [{node.id}]")
        await asyncio.sleep(ms / 1000.0)
        self._emit_engine_event("node_executed", {"node_id": node.id, "type": "delay", "duration_ms": ms})
        await self._step_to_next(node)

    async def _execute_condition(self, node: FlowNode):
        var_name = node.params.get("variable", "")
        operator = node.params.get("operator", "eq")
        value = node.params.get("value", 0)

        current = self._ctx.get_variable(var_name, 0)

        result = False
        if operator == "eq":
            result = current == value
        elif operator == "gt":
            result = current > value
        elif operator == "lt":
            result = current < value
        elif operator == "gte":
            result = current >= value
        elif operator == "lte":
            result = current <= value

        port_id = "true" if result else "false"
        logger.info(f"条件判断 [{node.id}]: {var_name}({current}) {operator} {value} -> {port_id}")

        self._emit_engine_event("node_executed", {
            "node_id": node.id,
            "type": "condition",
            "variable": var_name,
            "result": result,
        })

        for edge in self._ctx.flow.get_outgoing_edges(node.id):
            if edge.source.port_id == port_id:
                next_node = self._ctx.flow.nodes.get(edge.target.node_id)
                if next_node:
                    await self._execute_node(next_node, edge)

    async def _execute_action(self, node: FlowNode):
        actuator_id = node.params.get("actuator_id", "")
        action = node.params.get("action", "high")
        duration_ms = node.params.get("duration_ms", 0)

        cmd = {
            "actuator_id": actuator_id,
            "action": action,
            "duration_ms": duration_ms,
            "node_id": node.id,
        }

        success = True
        if self._send_action:
            try:
                success = await self._send_action(cmd)
            except Exception as e:
                logger.error(f"下发动作失败: {e}")
                success = False
                self._handle_action_failure(node, cmd, str(e))
        else:
            logger.info(f"执行动作 (dry): {actuator_id} -> {action} ({duration_ms}ms)")

        self._emit_engine_event("node_executed", {
            "node_id": node.id,
            "type": "execute",
            "actuator_id": actuator_id,
            "action": action,
            "success": success,
        })

        if duration_ms > 0:
            await asyncio.sleep(duration_ms / 1000.0)

        await self._step_to_next(node)

    async def _execute_loop(self, node: FlowNode):
        max_iter = node.params.get("max_iterations", 10)
        timeout_ms = node.params.get("timeout_ms", 60000)
        counter_key = f"loop_{node.id}"

        current = self._ctx.loop_iterations.get(counter_key, 0)
        if current >= max_iter:
            logger.info(f"循环 [{node.id}] 达到最大次数 {max_iter}，退出")
            self._emit_engine_event("loop_exit", {"node_id": node.id, "iterations": current})
            for edge in self._ctx.flow.get_outgoing_edges(node.id):
                if edge.source.port_id == "exit":
                    next_node = self._ctx.flow.nodes.get(edge.target.node_id)
                    if next_node:
                        await self._execute_node(next_node, edge)
            return

        self._ctx.loop_iterations[counter_key] = current + 1
        logger.info(f"循环 [{node.id}]: 第 {current + 1}/{max_iter} 次迭代")
        self._emit_engine_event("loop_iteration", {"node_id": node.id, "iteration": current + 1})

        for edge in self._ctx.flow.get_outgoing_edges(node.id):
            if edge.source.port_id == "body":
                next_node = self._ctx.flow.nodes.get(edge.target.node_id)
                if next_node:
                    await self._execute_node(next_node, edge)

    async def _execute_variable(self, node: FlowNode):
        var_name = node.params.get("name", "")
        op = node.params.get("operation", "set")
        value = node.params.get("value", 0)

        if op == "set":
            self._ctx.set_variable(var_name, value)
        elif op == "inc":
            current = self._ctx.get_variable(var_name, 0)
            self._ctx.set_variable(var_name, current + 1)
        elif op == "dec":
            current = self._ctx.get_variable(var_name, 0)
            self._ctx.set_variable(var_name, current - 1)

        self._emit_engine_event("node_executed", {
            "node_id": node.id,
            "type": "variable",
            "name": var_name,
            "operation": op,
            "value": self._ctx.get_variable(var_name),
        })
        await self._step_to_next(node)

    async def _execute_record(self, node: FlowNode):
        event_name = node.params.get("event_name", node.label)
        data = {
            "node_id": node.id,
            "ts_ms": int(time.time() * 1000),
            **{k: self._ctx.get_variable(k) for k in node.params.get("variables", [])},
        }
        self._ctx.session._record_event(event_name, data)
        self._emit_engine_event("node_executed", {"node_id": node.id, "type": "record", "event_name": event_name})
        await self._step_to_next(node)

    async def _execute_exception_handler(self, node: FlowNode):
        self._emit_engine_event("node_executed", {"node_id": node.id, "type": "exception_handler"})
        await self._step_to_next(node)

    def _handle_action_failure(self, node: FlowNode, cmd: Dict[str, Any], error: str):
        policy_str = node.params.get("on_failure", self._ctx.default_exception_policy.value)
        try:
            policy = ExceptionPolicy(policy_str)
        except ValueError:
            policy = ExceptionPolicy.TERMINATE

        logger.warning(f"动作失败 [{node.id}]: {error}, 处理策略={policy.value}")

        if policy == ExceptionPolicy.TERMINATE:
            self._ctx.session.error(f"动作执行失败: {error}")
            asyncio.create_task(self.stop())
        elif policy == ExceptionPolicy.SKIP:
            asyncio.create_task(self._step_to_next(node))
        elif policy == ExceptionPolicy.RETRY:
            if self._send_action:
                asyncio.create_task(self._retry_action(node, cmd))

    async def _retry_action(self, node: FlowNode, cmd: Dict[str, Any], max_retries: int = 3):
        for attempt in range(1, max_retries + 1):
            logger.info(f"重试动作 [{node.id}] 第 {attempt}/{max_retries} 次")
            await asyncio.sleep(1.0)
            try:
                if self._send_action:
                    success = await self._send_action(cmd)
                    if success:
                        await self._step_to_next(node)
                        return
            except Exception as e:
                logger.error(f"重试失败: {e}")
        self._ctx.session.error(f"动作重试失败（{max_retries}次）")
        await self.stop()

    async def _handle_error(self, node: FlowNode, event: EngineEvent):
        exception_handlers = [
            n for n in self._ctx.flow.nodes.values()
            if n.node_type == NodeType.EXCEPTION
        ]
        if exception_handlers:
            await self._step_to_next(exception_handlers[0])
        else:
            self._ctx.session.error(event.data.get("message", "未知错误"))
            await self.stop()

    def _emit_engine_event(self, kind: str, data: Dict[str, Any]):
        if self._on_engine_event:
            try:
                self._on_engine_event(kind, data)
            except Exception:
                logger.exception("on_engine_event error")
