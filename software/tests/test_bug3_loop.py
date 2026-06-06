#!/usr/bin/env python3
"""Bug #3: LOOP 节点多次迭代验证 - START -> LOOP(max_iterations=3) -> DELAY(0.5s) -> END"""

import sys
sys.path.insert(0, "/Applications/test/创业/行为学盒项目/behavior_box/software")

from session.engine import Engine
from session.flow_model import FlowGraph, FlowNode, Edge, NodeType, NodePort, PortDirection
from session.session import Session, ExperimentConfig
import asyncio

def test_loop_iterations():
    print("=" * 60)
    print("BUG #3: LOOP 节点迭代次数测试")
    print("=" * 60)

    engine = Engine()

    graph = FlowGraph(name="bug3_loop_test")

    start_node = FlowNode(
        id="start_1", node_type=NodeType.START, label="开始", params={}, x=0, y=0
    )
    graph.add_node(start_node)

    # LOOP with max_iterations=3
    loop_node = FlowNode(
        id="loop_1", node_type=NodeType.LOOP, label="循环3次",
        params={"max_iterations": 3}, x=200, y=0
    )
    graph.add_node(loop_node)

    # DELAY inside loop body (short delay for testing)
    delay_node = FlowNode(
        id="delay_1", node_type=NodeType.DELAY, label="延时0.3秒",
        params={"duration_s": 0.3}, x=400, y=0
    )
    graph.add_node(delay_node)

    # END (exit path from loop)
    end_node = FlowNode(
        id="end_1", node_type=NodeType.END, label="结束", params={}, x=600, y=0
    )
    graph.add_node(end_node)

    # Edges: START -> LOOP, LOOP(body) -> DELAY, LOOP(exit) -> END
    edge_start_loop = Edge(
        source=NodePort(node_id="start_1", port_id="out", direction=PortDirection.OUT),
        target=NodePort(node_id="loop_1", port_id="in", direction=PortDirection.IN)
    )
    graph.add_edge(edge_start_loop)

    edge_loop_delay = Edge(
        source=NodePort(node_id="loop_1", port_id="body", direction=PortDirection.OUT),
        target=NodePort(node_id="delay_1", port_id="in", direction=PortDirection.IN)
    )
    graph.add_edge(edge_loop_delay)

    edge_loop_end = Edge(
        source=NodePort(node_id="loop_1", port_id="exit", direction=PortDirection.OUT),
        target=NodePort(node_id="end_1", port_id="in", direction=PortDirection.IN)
    )
    graph.add_edge(edge_loop_end)

    session = Session()
    config = ExperimentConfig(name="bug3_test", flow=graph)
    session.load(config)

    iteration_count = 0
    loop_exit_count = 0

    def on_engine_event(kind, data):
        nonlocal iteration_count, loop_exit_count
        if kind == "loop_iteration":
            iteration_count += 1
            print(f"  Loop iteration #{data.get('iteration')}: node={data.get('node_id')}")
        elif kind == "loop_exit":
            loop_exit_count += 1
            print(f"  Loop exit: iterations={data.get('iterations')}")

    engine.set_on_engine_event(on_engine_event)

    async def run_test():
        try:
            await engine.start(session)

            # Wait for the loop to complete (3 iterations * 0.3s = ~1s + overhead)
            await asyncio.sleep(5)

            print(f"\n[Result] Total loop iterations recorded: {iteration_count}")
            print(f"[Result] Loop exits recorded: {loop_exit_count}")

            if iteration_count == 3:
                print("  ✅ PASS: LOOP executed exactly 3 times as expected!")
            elif iteration_count == 1:
                print("  ❌ FAIL: LOOP only executed once (Bug #3 still exists)")
            else:
                print(f"  ⚠️ Unexpected: {iteration_count} iterations")

            await engine.stop()

        except Exception as e:
            print(f"  Error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    asyncio.run(run_test())

if __name__ == "__main__":
    test_loop_iterations()
