"""端到端测试 LangGraph 图的 checkpoint_ns 传递

模拟实际的父图/子图场景，验证 checkpoint_ns 是否正确写入数据库
"""

import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from src.services.langgraph_persistence.postgres import build_db_uri_from_config
from src.services.langgraph_persistence.safe_checkpointer import SafeCheckpointer
import uuid


# 简单的测试 State
class TestState(TypedDict):
    message: str
    counter: int


def test_node(state: TestState) -> TestState:
    """测试节点"""
    return {"counter": state.get("counter", 0) + 1}


def test_graph_with_checkpoint_ns():
    """测试图编译和运行时 checkpoint_ns 的传递"""
    print("=" * 80)
    print("LangGraph 端到端 checkpoint_ns 测试")
    print("=" * 80)
    
    db_uri = build_db_uri_from_config()
    
    with PostgresSaver.from_conn_string(db_uri) as real_saver:
        # 包装为 SafeCheckpointer
        safe_saver = SafeCheckpointer(real_saver, enabled=True)
        
        # 创建图
        graph = StateGraph(TestState)
        graph.add_node("test_node", test_node)
        graph.add_edge(START, "test_node")
        graph.add_edge("test_node", END)
        
        # 编译图（传入 checkpointer）
        print("\n编译图（传入 SafeCheckpointer）...")
        app = graph.compile(checkpointer=safe_saver)
        print("✓ 图编译成功")
        
        # 测试配置
        test_thread_id = f"test-e2e-{uuid.uuid4()}"
        test_checkpoint_ns = "e2e_test_namespace"
        
        initial_state = {"message": "test", "counter": 0}
        
        config = {
            "configurable": {
                "thread_id": test_thread_id,
                "checkpoint_ns": test_checkpoint_ns,
            }
        }
        
        print(f"\n运行图...")
        print(f"  输入 state: {initial_state}")
        print(f"  config['configurable']['thread_id']: {test_thread_id}")
        print(f"  config['configurable']['checkpoint_ns']: {test_checkpoint_ns}")
        
        # 运行图
        final_state = app.invoke(initial_state, config=config)
        print(f"✓ 图运行完成")
        print(f"  输出 state: {final_state}")
        
        # 验证数据库中的 checkpoint_ns
        print(f"\n验证数据库中的记录...")
        
        import psycopg
        with psycopg.connect(db_uri) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT thread_id, checkpoint_ns, checkpoint_id
                    FROM langgraph.checkpoints
                    WHERE thread_id = %s
                    ORDER BY checkpoint_id
                """, (test_thread_id,))
                
                rows = cur.fetchall()
                if rows:
                    print(f"✓ 找到 {len(rows)} 条 checkpoint 记录:")
                    for i, row in enumerate(rows, 1):
                        actual_ns = row[1] if row[1] else '<空字符串>'
                        print(f"  记录 {i}:")
                        print(f"    thread_id: {row[0]}")
                        print(f"    checkpoint_ns: {actual_ns}")
                        print(f"    checkpoint_id: {row[2]}")
                        
                        # 判断是否匹配预期
                        if row[1] == test_checkpoint_ns:
                            print(f"    ✓ checkpoint_ns 正确")
                        else:
                            print(f"    ✗ checkpoint_ns 不匹配！预期: {test_checkpoint_ns}, 实际: {actual_ns}")
                else:
                    print("✗ 未找到任何 checkpoint 记录")
                
                # 检查 checkpoint_writes 表
                cur.execute("""
                    SELECT thread_id, checkpoint_ns, checkpoint_id, task_id
                    FROM langgraph.checkpoint_writes
                    WHERE thread_id = %s
                    LIMIT 5
                """, (test_thread_id,))
                
                rows = cur.fetchall()
                if rows:
                    print(f"\n✓ 找到 {len(rows)} 条 checkpoint_writes 记录（显示前5条）:")
                    for i, row in enumerate(rows, 1):
                        actual_ns = row[1] if row[1] else '<空字符串>'
                        print(f"  记录 {i}: checkpoint_ns = {actual_ns}")
                        
                        if row[1] == test_checkpoint_ns:
                            print(f"    ✓ checkpoint_ns 正确")
                        else:
                            print(f"    ✗ checkpoint_ns 不匹配！")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    test_graph_with_checkpoint_ns()

