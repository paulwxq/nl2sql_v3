#!/usr/bin/env python3
"""多轮对话测试：验证同一 thread_id 下的多次查询"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.modules.nl2sql_father.graph import run_nl2sql_query
from src.services.langgraph_persistence.identifiers import get_or_generate_thread_id
from src.services.langgraph_persistence.postgres import reset_persistence_cache
import psycopg
from src.services.config_loader import get_config


def main():
    print("=" * 60)
    print("🧪 多轮对话测试")
    print("=" * 60)
    
    # 使用同一个 thread_id 进行多次查询
    user_id = "multi_turn_test"
    thread_id = get_or_generate_thread_id(None, user_id)
    print(f"\n📍 Thread ID: {thread_id}")
    print(f"📍 User ID: {user_id}")
    
    queries = [
        "查询2024年的销售总额",
        "按月份统计销售额",
        "哪个门店销售最好",
    ]
    
    for i, query in enumerate(queries, 1):
        print(f"\n--- 第 {i} 轮查询 ---")
        print(f"📝 问题: {query}")
        
        result = run_nl2sql_query(
            query=query,
            thread_id=thread_id,
            user_id=user_id,
        )
        
        print(f"✅ Query ID: {result['query_id']}")
        print(f"   Complexity: {result.get('complexity')}")
        print(f"   Path: {result.get('path_taken')}")
    
    # 验证 Store 记录
    print("\n" + "=" * 60)
    print("📋 验证 Store 记录")
    print("=" * 60)
    
    config = get_config()
    db = config["database"]
    conn_str = f"host={db['host']} port={db['port']} dbname={db['database']} user={db['user']} password={db['password']}"
    
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            # 查询该 thread_id 的所有记录
            cur.execute("""
                SELECT key, created_at, value->>'query_id' as query_id
                FROM langgraph.store 
                WHERE key LIKE %s
                ORDER BY created_at
            """, (f"{thread_id}%",))
            
            rows = cur.fetchall()
            print(f"\n该 Thread 下共 {len(rows)} 条对话记录:")
            for key, created_at, query_id in rows:
                print(f"  - {query_id} ({created_at})")
    
    print("\n" + "=" * 60)
    print("🏁 多轮对话测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()

