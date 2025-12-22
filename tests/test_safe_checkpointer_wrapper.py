"""测试 SafeCheckpointer 是否正确传递 checkpoint_ns"""

import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from langgraph.checkpoint.postgres import PostgresSaver
from src.services.langgraph_persistence.postgres import build_db_uri_from_config
from src.services.langgraph_persistence.safe_checkpointer import SafeCheckpointer
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata
import uuid


def test_safe_checkpointer_passthrough():
    """测试 SafeCheckpointer 是否正确传递 checkpoint_ns"""
    print("=" * 80)
    print("SafeCheckpointer checkpoint_ns 传递测试")
    print("=" * 80)
    
    db_uri = build_db_uri_from_config()
    
    with PostgresSaver.from_conn_string(db_uri) as real_saver:
        # 包装为 SafeCheckpointer
        safe_saver = SafeCheckpointer(real_saver, enabled=True)
        
        # 测试配置
        test_thread_id = f"test-safe-wrapper-{uuid.uuid4()}"
        test_checkpoint_ns = "safe_wrapper_test_ns"
        
        config = {
            "configurable": {
                "thread_id": test_thread_id,
                "checkpoint_ns": test_checkpoint_ns,
            }
        }
        
        print(f"\n输入 config:")
        print(f"  thread_id: {test_thread_id}")
        print(f"  checkpoint_ns: {test_checkpoint_ns}")
        
        # 创建 checkpoint
        checkpoint = Checkpoint(
            v=1,
            id=str(uuid.uuid4()),
            ts=None,
            channel_values={},
            channel_versions={},
            versions_seen={},
        )
        
        metadata = CheckpointMetadata(
            source="test",
            step=1,
            writes={},
            parents={},
        )
        
        # 通过 SafeCheckpointer 写入
        print("\n通过 SafeCheckpointer 写入...")
        result = safe_saver.put(config, checkpoint, metadata, {})
        print(f"✓ 写入成功")
        print(f"  返回 config: {result}")
        
        # 验证读取
        print("\n通过 SafeCheckpointer 读取...")
        retrieved = safe_saver.get_tuple(config)
        if retrieved:
            print(f"✓ 读取成功")
            print(f"  checkpoint_id: {retrieved.checkpoint['id']}")
        else:
            print("✗ 读取失败")
        
        # 直接通过 real_saver 读取，验证数据库中的实际值
        print("\n直接通过 PostgresSaver 读取（验证数据库）...")
        retrieved_direct = real_saver.get_tuple(config)
        if retrieved_direct:
            print(f"✓ 读取成功")
            print(f"  checkpoint_id: {retrieved_direct.checkpoint['id']}")
            print(f"  config: {retrieved_direct.config}")
        else:
            print("✗ 读取失败")
        
        print(f"\n请检查数据库：")
        print(f"  SELECT thread_id, checkpoint_ns, checkpoint_id FROM langgraph.checkpoints")
        print(f"  WHERE thread_id = '{test_thread_id}';")


if __name__ == "__main__":
    test_safe_checkpointer_passthrough()

