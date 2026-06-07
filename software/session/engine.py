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
    signal_history: Dict[str, float] = field(default_factory=dict)
    pending_actions: int = 0
    default_exception_policy: ExceptionPolicy = ExceptionPolicy.TERMINATE
    # F2: FORK 分支中等待信号的 TRIGGER 节点 ID 集合（并行追踪）
    fork_waiting_triggers: set = field(default_factory=set)
    # F6: FORK 非 TRIGGER 分支的 asyncio Task 列表（避免同步阻塞主循环）
    fork_branch_tasks: list = field(default_factory=list)

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

        # LOOP body 深度计数器（支持嵌套循环）
        self._loop_body_depth: int = 0
        # B1 fix: pending LOOP reentry id (body completed, need to re-enter LOOP)
        self._pending_loop_continue: Optional[str] = None

        # SNIFFER 后台监听任务列表（G3-FIN-3）
        self._sniffer_configs: list[dict] = []
        self._signal_callback: Optional[Callable] = None

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

        # G3-FIN-3: 扫描 SNIFFER 节点并启动后台监听协程
        await self._start_sniffers()

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
            # F2: 清理 FORK 并行等待集合
            self._ctx.fork_waiting_triggers.clear()
            # F6: 取消并清理 FORK 分支任务
            for t in self._ctx.fork_branch_tasks:
                if not t.done():
                    t.cancel()
            self._ctx.fork_branch_tasks.clear()
        # G3-FIN-3: 清理 SNIFFER 后台监听任务
        await self._cleanup_sniffers()
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
            # F7: 立即派发到 SNIFFER（绕过 _run_loop 初始链阻塞）
            # _run_loop 在 await _step_to_next(start_node) 时阻塞，
            # 期间从未进入 while 循环，_handle_event 不会被调用。
            # 在 feed_signal 直接派发确保 SNIFFER 捕获不被初始链阻塞。
            self._dispatch_to_sniffers(event)
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
        # 记录信号历史 + 派发 SNIFFER（需在流程处理前，防止 stop() 提前清理配置）
        if event.is_signal:
            signal_id = event.data.get("signal_id", "")
            if signal_id:
                self._ctx.signal_history[signal_id] = time.time()
            self._dispatch_to_sniffers(event)

        current_node = self._ctx.flow.nodes.get(self._ctx.current_node_id)

        if current_node and event.is_trigger:
            await self._process_trigger(current_node, event)
            # F6: 主 TRIGGER 匹配后，取消 FORK 其他分支任务（动物已做选择）
            self._cancel_fork_branches()

        # F2 fix: 处理 FORK 并行等待中的 TRIGGER
        if event.is_signal and self._ctx.fork_waiting_triggers:
            event_signal_id = event.data.get("signal_id", "")
            for waiting_id in list(self._ctx.fork_waiting_triggers):
                waiting_node = self._ctx.flow.nodes.get(waiting_id)
                if waiting_node and waiting_node.node_type == NodeType.TRIGGER:
                    node_signal_id = waiting_node.params.get("signal_id", "")
                    full_match = (
                        event_signal_id == node_signal_id
                        or f"{event.data.get('source_id','')}:{event_signal_id}" == node_signal_id
                    )
                    # F4: registry-based matching for fork waiting triggers too
                    if not full_match:
                        full_match = self._match_signal_via_registry(node_signal_id, event_signal_id)
                    if full_match:
                        self._ctx.fork_waiting_triggers.discard(waiting_id)
                        logger.info(f"FORK 分支 TRIGGER [{waiting_node.id}] 匹配: signal={node_signal_id}")
                        self._emit_engine_event("node_triggered", {
                            "node_id": waiting_node.id,
                            "signal_id": node_signal_id,
                        })
                        await self._step_to_next(waiting_node)
                        # F6: FORK 分支 TRIGGER 匹配后，取消其他分支任务
                        self._cancel_fork_branches()
                        # 一个信号只匹配第一个等待中的 TRIGGER（选择模型：动物做一次选择）
                        break

        elif event.is_error and current_node:
            await self._handle_error(current_node, event)

    def _cancel_fork_branches(self):
        """F6: 取消所有 FORK 非 TRIGGER 分支任务（一个分支做出选择后，其他分支放弃）"""
        if self._ctx and self._ctx.fork_branch_tasks:
            for t in self._ctx.fork_branch_tasks:
                if not t.done():
                    t.cancel()
            self._ctx.fork_branch_tasks.clear()

    def _match_signal_via_registry(self, node_signal_id: str, event_signal_id: str) -> bool:
        """F4 fix: 通过注册中心匹配信号。当 node_signal_id 是注册中心 source_id 时，
        检查 event_signal_id 是否在其 produced_signals 中。"""
        try:
            from protocol.device_registry import get_registry
            reg = get_registry()
            reg_entry = reg.get(node_signal_id)
            if reg_entry and reg_entry.produced_signals:
                matched = event_signal_id in reg_entry.produced_signals
                if matched:
                    logger.info(f"注册中心匹配: {node_signal_id} → {event_signal_id} (produced={reg_entry.produced_signals})")
                return matched
            else:
                logger.info(f"注册中心未找到源 {node_signal_id} 或其 produced_signals 为空")
        except Exception:
            pass
        return False

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
            # F4 fix: 注册中心匹配 — node_signal_id 可能是注册中心 source_id
            if not full_match:
                full_match = self._match_signal_via_registry(node_signal_id, event_signal_id)
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

        # 递增全局触发计数器，供下游 CONDITION(source=trigger_count) 读取
        self._ctx.counters["trigger_count"] = self._ctx.counters.get("trigger_count", 0) + 1

        await self._step_to_next(node)

    async def _step_to_next(self, node: FlowNode):
        outgoing = self._ctx.flow.get_outgoing_edges(node.id)
        if not outgoing:
            if node.node_type == NodeType.END:
                await self.stop()
            elif self._loop_body_depth > 0 or self._pending_loop_continue is not None:
                # B1 fix: body 节点无出边但有待重入的 LOOP,先重入 LOOP
                if self._pending_loop_continue:
                    loop_id = self._pending_loop_continue
                    self._pending_loop_continue = None
                    loop_node = self._ctx.flow.nodes.get(loop_id)
                    if loop_node:
                        logger.debug(f"LOOP body 完成,重入 LOOP [{loop_id}]")
                        await self._execute_loop(loop_node)
                    return
                # 循环体内节点无出边，静默返回（由 LOOP 控制流程）
                logger.debug(f"LOOP body 内节点 [{node.id}] 无出边，返回")
            else:
                logger.warning(f"节点 [{node.id}] 没有出边，流程终止")
                await self.stop()
            return

        # 支持多输出节点：遍历所有出边并执行
        for edge in outgoing:
            next_node = self._ctx.flow.nodes.get(edge.target.node_id)
            if next_node:
                await self._execute_node(next_node, edge)

    async def _execute_node(self, node: FlowNode, incoming_edge: Edge):
        logger.debug(f"执行节点: [{node.id}] {node.node_type.value}")

        if node.node_type == NodeType.END:
            # LOOP body 内不允许走到 END，防止流程终止
            if self._loop_body_depth > 0:
                logger.debug(f"LOOP body mode (depth={self._loop_body_depth}): 跳过 END 节点 [{node.id}]")
                return
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

        elif node.node_type == NodeType.RECORD:
            await self._execute_record(node)

        elif node.node_type == NodeType.RECORD_END:
            await self._execute_record_end(node)

        elif node.node_type == NodeType.START:
            await self._step_to_next(node)

        elif node.node_type == NodeType.TRIGGER:
            self._ctx.current_node_id = node.id

        elif node.node_type == NodeType.AND:
            await self._execute_and(node, incoming_edge)

        elif node.node_type == NodeType.NOT:
            await self._execute_not(node)

        elif node.node_type == NodeType.FORK:
            await self._execute_fork(node)

        elif node.node_type == NodeType.SNIFFER:
            # SNIFFER 0入0出，不参与主流程，无事可做
            pass

    async def _execute_delay(self, node: FlowNode):
        duration_s = node.params.get("duration_s", 1.0)
        ms = duration_s * 1000.0
        logger.info(f"延时 {duration_s}秒 ({ms}ms): [{node.id}]")
        await asyncio.sleep(duration_s)
        self._emit_engine_event("node_executed", {"node_id": node.id, "type": "delay", "duration_s": duration_s})
        await self._step_to_next(node)

    async def _execute_condition(self, node: FlowNode):
        source = node.params.get("source", "trigger_count")
        operator = node.params.get("operator", "eq")
        expected_value = node.params.get("value", 0)

        # Resolve actual value from the chosen data source
        if source == "counter":
            counter_name = node.params.get("counter_name", "default")
            actual_value = self._ctx.counters.get(counter_name, 0)
        else:
            # trigger_count: 全局触发计数器（所有 TRIGGER 节点匹配时递增）
            actual_value = self._ctx.counters.get("trigger_count", 0)

        result = False
        if operator == "eq":
            result = actual_value == expected_value
        elif operator == "neq":
            result = actual_value != expected_value
        elif operator == "gt":
            result = actual_value > expected_value
        elif operator == "lt":
            result = actual_value < expected_value
        elif operator == "gte":
            result = actual_value >= expected_value
        elif operator == "lte":
            result = actual_value <= expected_value

        # Write back to context for downstream nodes or logging
        self._ctx.set_variable("condition_result", result)
        self._ctx.set_variable("actual_value", actual_value)
        self._ctx.set_variable("expected_value", expected_value)

        port_id = "true" if result else "false"
        logger.info(f"条件判断 [{node.id}]: source={source}, actual={actual_value} {operator} {expected_value} -> {port_id}")

        self._emit_engine_event("node_executed", {
            "node_id": node.id,
            "type": "condition",
            "source": source,
            "actual_value": actual_value,
            "expected_value": expected_value,
            "operator": operator,
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

        cmd = {
            "actuator_id": actuator_id,
            "action": action,
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
            logger.info(f"执行动作 (dry): {actuator_id} -> {action}")

        self._emit_engine_event("node_executed", {
            "node_id": node.id,
            "type": "execute",
            "actuator_id": actuator_id,
            "action": action,
            "success": success,
        })

        await self._step_to_next(node)

    async def _execute_loop(self, node: FlowNode):
        max_iter = node.params.get("max_iterations", 10)
        timeout_s = node.params.get("timeout_s", 0)
        counter_key = f"loop_{node.id}"
        deadline_key = f"loop_deadline_{node.id}"

        # 首次迭代时记录超时 deadline
        if timeout_s > 0 and deadline_key not in self._ctx.variables:
            self._ctx.variables[deadline_key] = time.time() + timeout_s

        # 检查超时
        if timeout_s > 0:
            deadline = self._ctx.variables.get(deadline_key, 0)
            if time.time() >= deadline:
                logger.info(f"循环 [{node.id}] 超时 {timeout_s}秒，强制退出")
                self._emit_engine_event("loop_timeout", {"node_id": node.id, "timeout_s": timeout_s})
                # F8: 超时退出也 emit loop_exit，标记循环已退出（含原因）
                current_iter = self._ctx.loop_iterations.get(counter_key, 0)
                self._emit_engine_event("loop_exit", {"node_id": node.id, "iterations": current_iter, "reason": "timeout"})
                await self._exit_loop_path(node, counter_key)
                return

        # 检查最大次数（max_iter <= 0 表示不限制次数，仅靠 timeout 控制）
        current = self._ctx.loop_iterations.get(counter_key, 0)
        if max_iter > 0 and current >= max_iter:
            logger.info(f"循环 [{node.id}] 达到最大次数 {max_iter}，退出")
            self._emit_engine_event("loop_exit", {"node_id": node.id, "iterations": current})
            await self._exit_loop_path(node, counter_key)
            return

        self._ctx.loop_iterations[counter_key] = current + 1
        max_label = str(max_iter) if max_iter > 0 else "∞"
        logger.info(f"循环 [{node.id}]: 第 {current + 1}/{max_label} 次迭代（超时 {timeout_s}秒）")
        self._emit_engine_event("loop_iteration", {"node_id": node.id, "iteration": current + 1})

        # 执行 body 路径：增加深度计数，防止 body 内走到 END
        self._loop_body_depth += 1
        try:
            body_edge = None
            for edge in self._ctx.flow.get_outgoing_edges(node.id):
                if edge.source.port_id == "body":
                    body_edge = edge
                    break

            if body_edge:
                next_node = self._ctx.flow.nodes.get(body_edge.target.node_id)
                if next_node:
                    # F1 fix: 执行 body 前先重置 current_node_id 为哨兵值 None
                    # TRIGGER 是唯一设置 current_node_id 后暂停的节点类型
                    # 重置为 None 确保无论第几次迭代都能可靠检测到 TRIGGER 暂停
                    # (原方案: 保存 saved_node_id → 第1次迭代后 TRIGGER 设置了它,
                    #  第2次迭代 saved_node_id = TRIGGER.id, TRIGGER 再次设置后不变, != 失效)
                    self._ctx.current_node_id = None
                    await self._execute_node(next_node, body_edge)

                    # F1 fix: 用 is not None 替代 != saved_node_id
                    # 只要任何节点设置了 current_node_id 就说明 body 链在某处暂停
                    if self._ctx.current_node_id is not None:
                        waiting_node = self._ctx.flow.nodes.get(self._ctx.current_node_id)
                        if waiting_node and waiting_node.node_type == NodeType.TRIGGER:
                            self._pending_loop_continue = node.id
                            logger.debug(f"LOOP [{node.id}] body 中 TRIGGER [{waiting_node.id}] 等待信号,暂不递归")
                            return  # 不检查 should_continue,不递归,等信号触发后由 _step_to_next 重入

            # body 路径执行完成后，检查是否继续循环
            should_continue = True
            if timeout_s > 0 and time.time() >= self._ctx.variables.get(deadline_key, 0):
                should_continue = False
            if self._ctx.loop_iterations.get(counter_key, 0) >= max_iter and max_iter > 0:
                should_continue = False

            if should_continue:
                await self._execute_loop(node)
            else:
                # B1 cleanup: 清除待重入标记,防止 _step_to_next 误重入已退出的 LOOP
                if self._pending_loop_continue == node.id:
                    self._pending_loop_continue = None
                reason = "达到最大次数" if self._ctx.loop_iterations.get(counter_key, 0) >= max_iter else "超时"
                logger.info(f"循环 [{node.id}] {reason}，退出")
                self._emit_engine_event("loop_exit", {"node_id": node.id, "reason": reason})
                await self._exit_loop_path(node, counter_key)
        finally:
            self._loop_body_depth -= 1

    async def _exit_loop_path(self, node: FlowNode, counter_key: str):
        """执行 LOOP 的退出分支并清理循环状态"""
        deadline_key = f"loop_deadline_{node.id}"
        self._ctx.variables.pop(deadline_key, None)
        self._ctx.loop_iterations.pop(counter_key, None)
        # B2 fix: 退出路径不应算作循环体内,临时清零 _loop_body_depth
        # 防止 exit→END 时被 END 节点的 loop_body_depth 卫语句拦截 stop()
        saved_depth = self._loop_body_depth
        self._loop_body_depth = 0
        try:
            for edge in self._ctx.flow.get_outgoing_edges(node.id):
                if edge.source.port_id == "exit":
                    next_node = self._ctx.flow.nodes.get(edge.target.node_id)
                    if next_node:
                        await self._execute_node(next_node, edge)
        finally:
            self._loop_body_depth = saved_depth

    async def _execute_record(self, node: FlowNode):
        event_name = node.params.get("event_name", node.label)
        data = {
            "node_id": node.id,
            "ts_ms": int(time.time() * 1000),
            **{k: self._ctx.get_variable(k) for k in node.params.get("variables", [])},
        }

        # 计数器操作（如果配置了 counter_name 和 counter_op）
        counter_name = node.params.get("counter_name", "")
        counter_op = node.params.get("counter_op", "")
        if counter_name and counter_op:
            if counter_op == "+1":
                self._ctx.counters[counter_name] = self._ctx.counters.get(counter_name, 0) + 1
            elif counter_op == "=0":
                self._ctx.counters[counter_name] = 0
            elif counter_op == "=1":
                self._ctx.counters[counter_name] = 1
            elif counter_op == "-1":
                self._ctx.counters[counter_name] = self._ctx.counters.get(counter_name, 0) - 1
            data["counter_name"] = counter_name
            data["counter_op"] = counter_op
            data["counter_value"] = self._ctx.counters[counter_name]

        self._ctx.session._record_event(event_name, data)
        self._emit_engine_event("node_executed", {"node_id": node.id, "type": "record", "event_name": event_name})
        await self._step_to_next(node)

    async def _execute_and(self, node: FlowNode, incoming_edge: Edge):
        """AND 节点：所有输入端口都收到信号后才触发输出。
        
        通过追踪入边信号状态实现。当所有入边都收到信号时，从输出端口继续执行。
        """
        incoming_edges = self._ctx.flow.get_incoming_edges(node.id)
        if not incoming_edges:
            logger.warning(f"AND 节点 [{node.id}] 没有入边，直接输出")
            await self._step_to_next(node)
            return

        # 追踪每个入边的信号状态
        signal_key = f"and_{node.id}"
        if signal_key not in self._ctx.variables:
            # 初始化：所有入边都未收到信号
            self._ctx.variables[signal_key] = {
                "received": set(),  # 已收到信号的入边索引
                "total": len(incoming_edges),
            }

        # 标记当前入边已收到信号
        incoming_idx = self._ctx.variables[signal_key]["received"]
        # 找到当前入边在 incoming_edges 中的索引
        for i, edge in enumerate(incoming_edges):
            if edge.source.node_id == incoming_edge.source.node_id and edge.source.port_id == incoming_edge.source.port_id:
                incoming_idx.add(i)
                break

        total = self._ctx.variables[signal_key]["total"]
        received_count = len(incoming_idx)
        logger.info(f"AND 节点 [{node.id}]: 收到 {received_count}/{total} 个输入信号")

        if received_count >= total:
            logger.info(f"AND 节点 [{node.id}]: 所有输入已收到，触发输出")
            self._emit_engine_event("node_executed", {
                "node_id": node.id,
                "type": "and",
                "signals_received": received_count,
            })
            # 重置状态，确保后续使用（如循环中再次经过 AND）时重新收集信号
            self._ctx.variables.pop(signal_key, None)
            await self._step_to_next(node)
        else:
            logger.info(f"AND 节点 [{node.id}]: 等待 {total - received_count} 个更多输入信号")

    async def _execute_not(self, node: FlowNode):
        """NOT 节点：等待信号消失后放行。

        在 timeout_s 上限内持续检测 signal_id：
        - 若检测到信号出现 → 重置等待计时
        - 若 timeout_s 内无信号 → 条件满足，放行
        """
        signal_id = node.params.get("signal_id", "")
        timeout_s = node.params.get("timeout_s", 5.0)
        poll_interval = 0.1

        logger.info(f"NOT 节点 [{node.id}]: 等待信号 {signal_id} 消失（超时 {timeout_s}秒）")

        wait_start = time.time()
        while time.time() - wait_start < timeout_s:
            last_seen = self._ctx.signal_history.get(signal_id, 0)
            if last_seen > wait_start:
                logger.debug(f"NOT 节点 [{node.id}]: 检测到信号 {signal_id}，重置等待")
                wait_start = time.time()
            await asyncio.sleep(poll_interval)

        logger.info(f"NOT 节点 [{node.id}]: 信号 {signal_id} 已消失 {timeout_s}秒，放行")
        self._emit_engine_event("node_executed", {
            "node_id": node.id,
            "type": "not",
            "signal_id": signal_id,
        })
        await self._step_to_next(node)

    async def _execute_record_end(self, node: FlowNode):
        """RECORD_END 节点：记录事件后流程在此终止（1进0出）"""
        event_name = node.params.get("event_name", node.label)
        data = {
            "node_id": node.id,
            "ts_ms": int(time.time() * 1000),
            **{k: self._ctx.get_variable(k) for k in node.params.get("variables", [])},
        }

        # 计数器操作（如果配置了 counter_name 和 counter_op）
        counter_name = node.params.get("counter_name", "")
        counter_op = node.params.get("counter_op", "")
        if counter_name and counter_op:
            if counter_op == "+1":
                self._ctx.counters[counter_name] = self._ctx.counters.get(counter_name, 0) + 1
            elif counter_op == "=0":
                self._ctx.counters[counter_name] = 0
            elif counter_op == "=1":
                self._ctx.counters[counter_name] = 1
            elif counter_op == "-1":
                self._ctx.counters[counter_name] = self._ctx.counters.get(counter_name, 0) - 1
            data["counter_name"] = counter_name
            data["counter_op"] = counter_op
            data["counter_value"] = self._ctx.counters[counter_name]

        self._ctx.session._record_event(event_name, data)
        self._emit_engine_event("node_executed", {
            "node_id": node.id, "type": "record_end", "event_name": event_name,
        })
        # 0 outputs — flow stops on this branch, no _step_to_next

    async def _execute_fork(self, node: FlowNode):
        """FORK 节点：1入2出，无条件分叉。TRIGGER 子节点加入并行等待队列。

        F2 fix: 原实现通过 _step_to_next 遍历所有出边，两个分支的 TRIGGER
        会互相覆盖 current_node_id（引擎只有单线程 current_node_id）。
        修复：TRIGGER 子节点不立即执行，而是加入并行等待集合，
        第一个 TRIGGER 设为主追踪节点，其余加入 fork_waiting_triggers。

        F6 fix: 非 TRIGGER 子节点（DELAY/EXECUTE/RECORD等）原先用 await
        同步执行，阻塞主循环事件处理，导致 TRIGGER 分支永远匹配不到信号。
        修复：非 TRIGGER 分支启动为 asyncio Task，让主循环继续处理事件。
        """
        logger.info(f"FORK [{node.id}]: 分叉")
        self._emit_engine_event("node_executed", {"node_id": node.id, "type": "fork"})

        outgoing = self._ctx.flow.get_outgoing_edges(node.id)
        triggers = []
        for edge in outgoing:
            target = self._ctx.flow.nodes.get(edge.target.node_id)
            if target is None:
                continue
            if target.node_type == NodeType.TRIGGER:
                triggers.append(target)
            else:
                # F6 fix: 非 TRIGGER 分支启动为并发 task，不阻塞主循环
                task = asyncio.create_task(self._execute_fork_branch(target, edge, node.id))
                self._ctx.fork_branch_tasks.append(task)
                logger.debug(f"FORK [{node.id}]: 后台分支 {target.node_type.value} [{target.id}] 启动")

        if triggers:
            # 第一个 TRIGGER 设为主追踪节点，其余加入并行等待集合
            self._ctx.current_node_id = triggers[0].id
            for t in triggers[1:]:
                self._ctx.fork_waiting_triggers.add(t.id)
                logger.debug(f"FORK [{node.id}]: TRIGGER [{t.id}] 加入并行等待集合")

    async def _execute_fork_branch(self, node: FlowNode, incoming_edge: Edge, fork_node_id: str):
        """F6: 以 asyncio task 方式执行 FORK 的非 TRIGGER 分支。

        分支执行链持续直到遇到 TRIGGER（交还主循环）或到达终端节点。
        DELAY 节点在 task 内 await asyncio.sleep，不阻塞主循环事件处理。

        竞态保护：当主循环中另一分支的 TRIGGER 先匹配时，
        _cancel_fork_branches 会取消本 task，防止并行执行同一后续节点。
        """
        try:
            current = node
            edge = incoming_edge
            while current is not None and self._state == EngineState.RUNNING:
                if current.node_type == NodeType.TRIGGER:
                    # 分支遇到 TRIGGER，加入并行等待（与主循环协作）
                    if not self._ctx.current_node_id:
                        self._ctx.current_node_id = current.id
                    else:
                        self._ctx.fork_waiting_triggers.add(current.id)
                    logger.debug(f"FORK branch [{fork_node_id}]: TRIGGER [{current.id}] 加入等待")
                    break

                # 执行当前节点（DELAY 会 asyncio.sleep，不阻塞主循环）
                await self._execute_node(current, edge)

                # 检查是否已经到达终止状态
                if self._state != EngineState.RUNNING:
                    break

                # 获取下一步
                outgoing = self._ctx.flow.get_outgoing_edges(current.id)
                if not outgoing:
                    # 遇到无出边的节点（如 RECORD_END/END），停止分支
                    break
                # 取第一条出边（FORK 分支内通常单线）
                next_edge = outgoing[0]
                current = self._ctx.flow.nodes.get(next_edge.target.node_id)
                edge = next_edge

        except asyncio.CancelledError:
            logger.debug(f"FORK branch (from [{fork_node_id}]) cancelled - another branch won")
        except Exception:
            logger.exception(f"FORK branch (from [{fork_node_id}]) error")

    async def _start_sniffers(self):
        """G3-FIN-3: 扫描流程图中所有 SNIFFER 节点，存储配置供主循环派发"""
        if not self._ctx:
            return
        flow = self._ctx.flow
        for node in flow.nodes.values():
            if node.node_type == NodeType.SNIFFER:
                signal_id = node.params.get("signal_id", "")
                event_name = node.params.get("event_name", "旁路记录")
                if signal_id:
                    self._sniffer_configs.append({
                        "node_id": node.id,
                        "signal_id": signal_id,
                        "event_name": event_name,
                    })
                    logger.info(f"SNIFFER [{node.id}]: 注册监听 signal_id={signal_id}")
        if not self._sniffer_configs:
            logger.debug("流程中无 SNIFFER 节点，跳过注册")

    async def _cleanup_sniffers(self):
        """G3-FIN-3: 清理所有 SNIFFER 配置"""
        self._sniffer_configs.clear()
        logger.info("SNIFFER 配置已清理")

    def _dispatch_to_sniffers(self, event: EngineEvent):
        """主循环派发事件给所有 SNIFFER 观察者（被动观察，不消费队列）"""
        if not event.is_signal or not self._sniffer_configs:
            return
        event_signal_id = event.data.get("signal_id", "")
        event_source_id = event.data.get("source_id", "")
        logger.info(f"SNIFFER dispatch: event signal={event_signal_id} source={event_source_id} configs={len(self._sniffer_configs)}")
        for cfg in self._sniffer_configs:
            full_match = (
                event_signal_id == cfg["signal_id"]
                or f"{event_source_id}:{event_signal_id}" == cfg["signal_id"]
            )
            # F4: registry-based matching for SNIFFER too
            if not full_match:
                full_match = self._match_signal_via_registry(cfg["signal_id"], event_signal_id)
            if full_match:
                logger.info(f"SNIFFER [{cfg['node_id']}]: 捕获信号 {cfg['signal_id']} → {cfg['event_name']}")
                self._emit_engine_event("sniffer_captured", {
                    "node_id": cfg["node_id"],
                    "signal_id": cfg["signal_id"],
                    "event_name": cfg["event_name"],
                    "ts_ms": event.ts_ms,
                })
                if self._ctx:
                    self._ctx.session._record_event(
                        event_type=f"sniffer:{cfg['event_name']}",
                        data={
                            "signal_id": cfg["signal_id"],
                            "event_name": cfg["event_name"],
                            "raw": event.data,
                        }
                    )

    def set_signal_callback(self, cb: Callable):
        """设置外部信号回调，供 SNIFFER 等组件使用"""
        self._signal_callback = cb

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
        self._ctx.session.error(event.data.get("message", "未知错误"))
        await self.stop()

    def _emit_engine_event(self, kind: str, data: Dict[str, Any]):
        if self._on_engine_event:
            try:
                self._on_engine_event(kind, data)
            except Exception:
                logger.exception("on_engine_event error")
