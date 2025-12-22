#!/usr/bin/env python3
"""
LangGraph 持久化功能测试脚本

测试 PostgresSaver (Checkpoint) 和 PostgresStore (历史对话) 的集成。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def create_schema():
    """创建 langgraph schema（如果不存在）"""
    import psycopg
    from src.services.config_loader import get_config
    
    config = get_config()
    db = config["database"]
    persistence = config.get("langgraph_persistence", {}).get("database", {})
    schema = persistence.get("schema", "langgraph")
    
    conn_str = f"host={db['host']} port={db['port']} dbname={db['database']} user={db['user']} password={db['password']}"
    
    print(f"📦 连接数据库: {db['host']}:{db['port']}/{db['database']}")
    
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.commit()
            print(f"✅ Schema '{schema}' 已创建或已存在")


def test_setup_persistence():
    """测试持久化初始化"""
    from src.services.langgraph_persistence import (
        setup_persistence,
        is_checkpoint_enabled,
        is_store_enabled,
    )
    
    print("\n" + "=" * 60)
    print("📋 测试 1: 持久化初始化")
    print("=" * 60)
    
    print(f"  Checkpoint enabled: {is_checkpoint_enabled()}")
    print(f"  Store enabled: {is_store_enabled()}")
    
    print("  正在初始化表结构...")
    result = setup_persistence()
    
    if result:
        print("  ✅ 持久化初始化成功！")
    else:
        print("  ❌ 持久化初始化失败")
    
    return result


def test_run_query():
    """测试执行查询（验证 checkpoint 和 store）"""
    from src.modules.nl2sql_father.graph import run_nl2sql_query
    
    print("\n" + "=" * 60)
    print("📋 测试 2: 执行 NL2SQL 查询")
    print("=" * 60)
    
    try:
        result = run_nl2sql_query(
            query="查询2024年的销售总额",
            user_id="test_user",
        )
        
        print(f"  ✅ 查询执行成功!")
        print(f"  Query ID: {result['query_id']}")
        print(f"  Thread ID: {result.get('thread_id')}")
        print(f"  User ID: {result.get('user_id')}")
        print(f"  Complexity: {result.get('complexity')}")
        print(f"  Path: {result.get('path_taken')}")
        
        if result.get('error'):
            print(f"  ⚠️ 业务错误: {result['error']}")
        
        return result
        
    except Exception as e:
        print(f"  ❌ 查询执行失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def verify_checkpoint_records():
    """验证 checkpoint 记录"""
    import psycopg
    from src.services.config_loader import get_config
    from src.services.langgraph_persistence.postgres import build_db_uri_from_config
    
    print("\n" + "=" * 60)
    print("📋 测试 3: 验证 Checkpoint 记录")
    print("=" * 60)
    
    config = get_config()
    db = config["database"]
    persistence = config.get("langgraph_persistence", {}).get("database", {})
    schema = persistence.get("schema", "langgraph")
    
    conn_str = f"host={db['host']} port={db['port']} dbname={db['database']} user={db['user']} password={db['password']}"
    
    try:
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                # 检查表是否存在
                cur.execute(f"""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = '{schema}'
                    ORDER BY table_name
                """)
                tables = cur.fetchall()
                
                if tables:
                    print(f"  ✅ Schema '{schema}' 中的表:")
                    for table in tables:
                        print(f"     - {table[0]}")
                else:
                    print(f"  ⚠️ Schema '{schema}' 中没有表")
                    return False
                
                # 检查 checkpoints 表（尝试不同的表名）
                for table_name in ["checkpoints", "checkpoint_blobs", "checkpoint_writes"]:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {schema}.{table_name}")
                        count = cur.fetchone()[0]
                        print(f"  ✅ {table_name}: {count} 条记录")
                    except Exception:
                        pass
                
                return True
                
    except Exception as e:
        print(f"  ❌ 验证失败: {e}")
        return False


def verify_store_records():
    """验证 store 记录"""
    import psycopg
    from src.services.config_loader import get_config
    
    print("\n" + "=" * 60)
    print("📋 测试 4: 验证 Store (历史对话) 记录")
    print("=" * 60)
    
    config = get_config()
    db = config["database"]
    persistence = config.get("langgraph_persistence", {})
    schema = persistence.get("database", {}).get("schema", "langgraph")
    namespace = persistence.get("store", {}).get("namespace", "chat_history")
    
    conn_str = f"host={db['host']} port={db['port']} dbname={db['database']} user={db['user']} password={db['password']}"
    
    try:
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                # 检查 store 表（使用 prefix 字段，实际 prefix 是 namespace 的元组形式）
                try:
                    # prefix 存储为元组的字符串形式，如 "('chat_history',)"
                    cur.execute(f"SELECT COUNT(*) FROM {schema}.store WHERE prefix = %s", (namespace,))
                    count = cur.fetchone()[0]
                    print(f"  ✅ Store 记录数 (prefix={namespace}): {count}")
                    
                    if count > 0:
                        cur.execute(f"""
                            SELECT key, created_at 
                            FROM {schema}.store 
                            WHERE prefix = %s
                            ORDER BY created_at DESC 
                            LIMIT 3
                        """, (namespace,))
                        rows = cur.fetchall()
                        print("  最近的记录:")
                        for key, created_at in rows:
                            print(f"     - {key} ({created_at})")
                    else:
                        # 尝试查看所有 prefix
                        cur.execute(f"SELECT DISTINCT prefix FROM {schema}.store LIMIT 5")
                        prefixes = cur.fetchall()
                        if prefixes:
                            print(f"  📋 Store 中存在的 prefix: {[p[0] for p in prefixes]}")
                    
                    return True
                    
                except Exception as e:
                    print(f"  ⚠️ Store 表查询失败: {e}")
                    return False
                
    except Exception as e:
        print(f"  ❌ 验证失败: {e}")
        return False


def main():
    """主测试流程"""
    print("=" * 60)
    print("🧪 LangGraph 持久化功能测试")
    print("=" * 60)
    
    # Step 0: 重置缓存（确保重新初始化）
    from src.services.langgraph_persistence.postgres import reset_persistence_cache
    reset_persistence_cache()
    
    # Step 1: 创建 schema
    try:
        create_schema()
    except Exception as e:
        print(f"❌ 创建 schema 失败: {e}")
        return
    
    # Step 2: 初始化持久化
    if not test_setup_persistence():
        print("\n⚠️ 持久化初始化失败，继续尝试...")
    
    # Step 3: 执行查询
    result = test_run_query()
    
    # Step 4: 验证 checkpoint
    verify_checkpoint_records()
    
    # Step 5: 验证 store
    verify_store_records()
    
    print("\n" + "=" * 60)
    print("🏁 测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()

