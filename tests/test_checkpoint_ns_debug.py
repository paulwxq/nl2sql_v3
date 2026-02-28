"""调试 checkpoint_ns 为空的问题

此脚本用于验证：
1. 配置是否正确加载
2. checkpoint_ns 是否正确传递给 invoke
3. PostgresSaver 是否正确接收到 checkpoint_ns
"""

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv

# 加载 .env
load_dotenv()

from src.services.langgraph_persistence.postgres import (
    is_checkpoint_enabled,
    get_checkpoint_namespace,
    get_postgres_saver,
    build_db_uri_from_config,
    _get_persistence_config,
)
from src.services.config_loader import get_config


def test_config_loading():
    """测试配置加载"""
    print("=" * 80)
    print("1. 配置加载测试")
    print("=" * 80)
    
    # 获取完整配置
    config = get_config()
    persistence_config = config.get("langgraph_persistence", {})
    
    print(f"langgraph_persistence.enabled: {persistence_config.get('enabled')}")
    print(f"langgraph_persistence.checkpoint.father_enabled: {persistence_config.get('checkpoint', {}).get('father_enabled')}")
    print(f"langgraph_persistence.checkpoint.subgraph_enabled: {persistence_config.get('checkpoint', {}).get('subgraph_enabled')}")
    print(f"langgraph_persistence.checkpoint.father_namespace: {persistence_config.get('checkpoint', {}).get('father_namespace')}")
    print(f"langgraph_persistence.checkpoint.subgraph_namespace: {persistence_config.get('checkpoint', {}).get('subgraph_namespace')}")
    
    print(f"\nis_checkpoint_enabled('father'): {is_checkpoint_enabled('father')}")
    print(f"is_checkpoint_enabled('subgraph'): {is_checkpoint_enabled('subgraph')}")
    print(f"get_checkpoint_namespace('father'): {get_checkpoint_namespace('father')}")
    print(f"get_checkpoint_namespace('subgraph'): {get_checkpoint_namespace('subgraph')}")
    print()


def test_postgres_saver_creation():
    """测试 PostgresSaver 创建"""
    print("=" * 80)
    print("2. PostgresSaver 创建测试")
    print("=" * 80)
    
    try:
        db_uri = build_db_uri_from_config()
        # 隐藏密码部分
        safe_uri = db_uri.split('@')[0].split(':')[0] + ':***@' + db_uri.split('@')[1]
        print(f"DB URI: {safe_uri}")
        print()
    except Exception as e:
        print(f"构建 DB URI 失败: {e}")
        print()
        return
    
    # 测试创建 father saver
    print("创建 father PostgresSaver...")
    saver = get_postgres_saver("father")
    if saver:
        print("✓ PostgresSaver (father) 创建成功")
        print(f"  类型: {type(saver)}")
        print(f"  config_specs: {saver.config_specs if hasattr(saver, 'config_specs') else 'N/A'}")
    else:
        print("✗ PostgresSaver (father) 创建失败")
    print()


def test_invoke_config_construction():
    """测试 invoke config 构造"""
    print("=" * 80)
    print("3. Invoke Config 构造测试")
    print("=" * 80)
    
    # 模拟父图的 invoke_config 构造
    test_thread_id = "test-thread-123"
    test_query_id = "test-query-456"
    test_sub_query_id = "sub-query-789"
    
    # 父图 config
    if is_checkpoint_enabled("father"):
        father_namespace = get_checkpoint_namespace("father")
        father_config = {
            "configurable": {
                "thread_id": test_thread_id,
                "checkpoint_ns": father_namespace,
            }
        }
        print("父图 invoke_config:")
        print(f"  thread_id: {father_config['configurable']['thread_id']}")
        print(f"  checkpoint_ns: {father_config['configurable']['checkpoint_ns']}")
        print()
        
    # 子图 config
    if is_checkpoint_enabled("subgraph"):
        subgraph_namespace = get_checkpoint_namespace("subgraph")
        checkpoint_ns = f"{subgraph_namespace}:{test_sub_query_id}"
        subgraph_config = {
            "configurable": {
                "thread_id": test_thread_id,
                "checkpoint_ns": checkpoint_ns,
            }
        }
        print("子图 invoke_config:")
        print(f"  thread_id: {subgraph_config['configurable']['thread_id']}")
        print(f"  checkpoint_ns: {subgraph_config['configurable']['checkpoint_ns']}")
        print()
    else:
        print("子图 Checkpoint 未启用")
        print()


def test_direct_postgres_write():
    """直接测试 PostgresSaver 写入（验证 checkpoint_ns 是否写入数据库）"""
    print("=" * 80)
    print("4. PostgresSaver 直接写入测试")
    print("=" * 80)
    
    if not is_checkpoint_enabled("father"):
        print("Checkpoint (father) 未启用，跳过测试")
        return
    
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata
        import uuid
        
        db_uri = build_db_uri_from_config()
        
        # 创建 PostgresSaver 实例
        with PostgresSaver.from_conn_string(db_uri) as saver:
            print("✓ PostgresSaver 连接成功")
            
            # 构造测试配置
            test_thread_id = f"test-thread-{uuid.uuid4()}"
            test_checkpoint_ns = "test_namespace_debug"
            
            config = {
                "configurable": {
                    "thread_id": test_thread_id,
                    "checkpoint_ns": test_checkpoint_ns,
                }
            }
            
            print(f"\n测试配置:")
            print(f"  thread_id: {test_thread_id}")
            print(f"  checkpoint_ns: {test_checkpoint_ns}")
            
            # 创建一个简单的 checkpoint
            checkpoint = Checkpoint(
                v=1,
                id=str(uuid.uuid4()),
                ts=None,  # PostgresSaver 会自动填充时间戳
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
            
            # 写入 checkpoint
            print("\n尝试写入 checkpoint...")
            result = saver.put(config, checkpoint, metadata, {})
            print(f"✓ 写入成功")
            print(f"  返回 config: {result}")
            
            # 验证读取
            print("\n尝试读取 checkpoint...")
            retrieved = saver.get_tuple(config)
            if retrieved:
                print(f"✓ 读取成功")
                print(f"  checkpoint_id: {retrieved.checkpoint['id']}")
                print(f"  metadata: {retrieved.metadata}")
            else:
                print("✗ 读取失败（返回 None）")
            
            print(f"\n请检查数据库中的 checkpoints 表：")
            print(f"  SELECT thread_id, checkpoint_ns, checkpoint_id FROM langgraph.checkpoints")
            print(f"  WHERE thread_id = '{test_thread_id}';")
            
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    print()


def main():
    """主测试函数"""
    print("\n" + "=" * 80)
    print("checkpoint_ns 调试测试")
    print("=" * 80 + "\n")
    
    # 1. 配置测试
    test_config_loading()
    
    # 2. PostgresSaver 创建测试
    test_postgres_saver_creation()
    
    # 3. Invoke config 构造测试
    test_invoke_config_construction()
    
    # 4. 直接写入测试
    test_direct_postgres_write()
    
    print("=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == "__main__":
    main()

