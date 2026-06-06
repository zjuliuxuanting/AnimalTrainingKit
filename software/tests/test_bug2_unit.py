#!/usr/bin/env python3
"""Bug #2: AND 节点 _execute_and 单元测试 - 直接测试方法签名和逻辑"""
import sys
sys.path.insert(0, "/Applications/test/创业/行为学盒项目/behavior_box/software")

from session.engine import Engine
from session.flow_model import FlowGraph, FlowNode, Edge, NodeType, NodePort, PortDirection
from session.session import Session, ExperimentConfig
import asyncio

def test_and_node_signature():
    """Test that _execute_and has correct signature (no NameError)"""
    print("=" * 60)
    print("BUG #2: AND 节点签名测试")
    print("=" * 60)

    engine = Engine()

    # Create a flow with AND node
    graph = FlowGraph(name="bug2_and_test")

    start_node = FlowNode(
        id="start_1",
        node_type=NodeType.START,
        label="开始",
        params={},
        x=0, y=0
    )
    graph.add_node(start_node)

    trigger_a = FlowNode(
        id="trigger_a",
        node_type=NodeType.TRIGGER,
        label="触发A",
        params={"signal_id": "mock:timer"},
        x=0, y=100
    )
    graph.add_node(trigger_a)

    trigger_b = FlowNode(
        id="trigger_b",
        node_type=NodeType.TRIGGER,
        label="触发B",
        params={"signal_id": "mock:random"},
        x=0, y=200
    )
    graph.add_node(trigger_b)

    and_node = FlowNode(
        id="and_1",
        node_type=NodeType.AND,
        label="AND门",
        params={},
        x=300, y=150
    )
    graph.add_node(and_node)

    exec_node = FlowNode(
        id="exec_1",
        node_type=NodeType.EXECUTE,
        label="执行",
        params={"actuator_id": "servo_1", "action": "high"},
        x=600, y=150
    )
    graph.add_node(exec_node)

    end_node = FlowNode(
        id="end_1",
        node_type=NodeType.END,
        label="结束",
        params={},
        x=900, y=150
    )
    graph.add_node(end_node)

    # Add edges: trigger_a -> and_1, trigger_b -> and_1, and_1 -> exec_1, exec_1 -> end_1
    edge1 = Edge(
        source=NodePort(node_id="trigger_a", port_id="out", direction=PortDirection.OUT),
        target=NodePort(node_id="and_1", port_id="in", direction=PortDirection.IN)
    )
    graph.add_edge(edge1)

    edge2 = Edge(
        source=NodePort(node_id="trigger_b", port_id="out", direction=PortDirection.OUT),
        target=NodePort(node_id="and_1", port_id="in", direction=PortDirection.IN)
    )
    graph.add_edge(edge2)

    edge3 = Edge(
        source=NodePort(node_id="and_1", port_id="out", direction=PortDirection.OUT),
        target=NodePort(node_id="exec_1", port_id="in", direction=PortDirection.IN)
    )
    graph.add_edge(edge3)

    edge4 = Edge(
        source=NodePort(node_id="exec_1", port_id="out", direction=PortDirection.OUT),
        target=NodePort(node_id="end_1", port_id="in", direction=PortDirection.IN)
    )
    graph.add_edge(edge4)

    # Create a session and start the engine
    session = Session()
    config = ExperimentConfig(name="bug2_test", flow=graph)
    session.load(config)

    async def run_test():
        try:
            await engine.start(session)

            # Manually set current node to trigger_a (simulating START -> TRIGGER path)
            engine._ctx.current_node_id = "trigger_a"

            # Feed a signal that matches trigger_a's signal_id
            from protocol.signal_source import SignalEvent, SourceType
            sig = SignalEvent(
                source_id="mock:0",
                source_type=SourceType.MOCK,
                signal_id="mock:timer",
                ts_ms=int(asyncio.get_event_loop().time() * 1000),
                value=1,
                data={}
            )

            # Feed the first trigger signal
            await engine.feed_signal(sig)
            print(f"  Fed first signal to trigger_a")

            # Wait a bit for processing
            await asyncio.sleep(0.5)

            # Now feed second signal matching trigger_b
            sig2 = SignalEvent(
                source_id="mock:0",
                source_type=SourceType.MOCK,
                signal_id="mock:random",
                ts_ms=int(asyncio.get_event_loop().time() * 1000),
                value=42,
                data={}
            )

            await engine.feed_signal(sig2)
            print(f"  Fed second signal to trigger_b")

            # Wait for AND node to process both signals
            await asyncio.sleep(1.0)

            # Check if engine is still running (no crash)
            if engine.state.value == "running":
                print("  ✅ Engine still running after AND processing - no NameError!")
            elif engine.state.value == "stopped":
                print("  ⚠️ Engine stopped (may be expected if flow completed)")

            await engine.stop()

        except NameError as e:
            print(f"  ❌ FAIL: NameError in _execute_and: {e}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            print(f"  ⚠️ Other error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    asyncio.run(run_test())

if __name__ == "__main__":
    test_and_node_signature()
