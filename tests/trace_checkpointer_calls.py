"""追踪 LangGraph 调用 checkpointer 时传递的参数"""

import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from typing import TypedDict, Any
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from src.services.langgraph_persistence.postgres import build_db_uri_from_config
import uuid


# 简单的测试 State
class TestState(TypedDict):
    message: str


def test_node(state: TestState) -> TestState:
    return {"message": f"{state['message']} processed"}


# 创建一个追踪版本的 Checkpointer
class TracingCheckpointer:
    """包装 checkpointer，打印所有调用的参数"""
    
    def __init__(self, real_checkpointer):
        self._real = real_checkpointer
        self._call_count = 0
    
    def put(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        """追踪 put 调用"""
        self._call_count += 1
        print(f"\n{'='*80}")
        print(f"TracingCheckpointer.put() 调用 #{self._call_count}")
        print(f"{'='*80}")
        print(f"config 类型: {type(config)}")
        print(f"config 内容: {config}")
        
        if isinstance(config, dict):
            configurable = config.get('configurable', {})
            print(f"\nconfig['configurable']:")
            for key, value in configurable.items():
                print(f"  {key}: {value}")
            
            # 检查 checkpoint_ns
            if 'checkpoint_ns' in configurable:
                print(f"\n✓ checkpoint_ns 存在: '{configurable['checkpoint_ns']}'")
            else:
                print(f"\n✗ checkpoint_ns 不存在！")
        
        return self._real.put(config, checkpoint, metadata, new_versions)
    
    def put_writes(self, config: Any, writes: Any, task_id: str, task_path: str = "") -> None:
        """追踪 put_writes 调用"""
        print(f"\nTracingCheckpointer.put_writes() 调用")
        print(f"  task_id: {task_id}")
        print(f"  config: {config}")
        
        if isinstance(config, dict):
            configurable = config.get('configurable', {})
            checkpoint_ns = configurable.get('checkpoint_ns', '<不存在>')
            print(f"  checkpoint_ns: {checkpoint_ns}")
        
        return self._real.put_writes(config, writes, task_id, task_path)
    
    def get(self, config: dict) -> Any:
        return self._real.get(config)
    
    def get_tuple(self, config: dict) -> Any:
        return self._real.get_tuple(config)
    
    def list(self, config: Any = None, *, filter: Any = None, before: Any = None, limit: Any = None) -> Any:
        return self._real.list(config, filter=filter, before=before, limit=limit)
    
    def get_next_version(self, current: Any, channel: Any) -> str:
        return self._real.get_next_version(current, channel)
    
    @property
    def config_specs(self):
        print(f"\nTracingCheckpointer.config_specs 被访问")
        specs = self._real.config_specs
        print(f"  返回值: {specs}")
        return specs
    
    @property
    def serde(self):
        return self._real.serde


def test_tracing():
    """测试追踪"""
    print("=" * 80)
    print("追踪 LangGraph 调用 checkpointer 的参数")
    print("=" * 80)
    
    db_uri = build_db_uri_from_config()
    
    with PostgresSaver.from_conn_string(db_uri) as real_saver:
        # 使用追踪包装器
        tracing_saver = TracingCheckpointer(real_saver)
        
        # 创建图
        graph = StateGraph(TestState)
        graph.add_node("test_node", test_node)
        graph.add_edge(START, "test_node")
        graph.add_edge("test_node", END)
        
        # 编译图
        print("\n编译图...")
        app = graph.compile(checkpointer=tracing_saver)
        print("✓ 图编译完成\n")
        
        # 准备配置
        test_thread_id = f"trace-test-{uuid.uuid4()}"
        test_checkpoint_ns = "trace_test_namespace"
        
        config = {
            "configurable": {
                "thread_id": test_thread_id,
                "checkpoint_ns": test_checkpoint_ns,
            }
        }
        
        print("="  * 80)
        print("准备运行图")
        print("=" * 80)
        print(f"输入 config:")
        print(f"  thread_id: {test_thread_id}")
        print(f"  checkpoint_ns: {test_checkpoint_ns}")
        print()
        
        # 运行图
        initial_state = {"message": "test"}
        final_state = app.invoke(initial_state, config=config)
        
        print("\n" + "=" * 80)
        print("图运行完成")
        print("=" * 80)
        print(f"最终状态: {final_state}")
        print(f"\n总共调用 put() 次数: {tracing_saver._call_count}")


if __name__ == "__main__":
    test_tracing()

