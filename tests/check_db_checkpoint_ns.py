"""检查数据库中的 checkpoint_ns 字段

直接查询数据库，查看实际存储的 checkpoint_ns 值
"""

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

import psycopg
from src.services.langgraph_persistence.postgres import build_db_uri_from_config


def check_checkpoint_ns():
    """检查数据库中的 checkpoint_ns 字段"""
    print("=" * 80)
    print("数据库 checkpoint_ns 检查")
    print("=" * 80)
    
    db_uri = build_db_uri_from_config()
    
    try:
        with psycopg.connect(db_uri) as conn:
            with conn.cursor() as cur:
                # 1. 检查 checkpoints 表
                print("\n1. checkpoints 表:")
                print("-" * 80)
                cur.execute("""
                    SELECT 
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        parent_checkpoint_id,
                        type
                    FROM langgraph.checkpoints
                    LIMIT 10
                """)
                
                rows = cur.fetchall()
                if rows:
                    print(f"前 10 条记录:")
                    print(f"{'Thread ID':<40} {'Checkpoint NS':<30} {'Checkpoint ID':<40}")
                    print("-" * 110)
                    for row in rows:
                        thread_id = row[0] or ''
                        checkpoint_ns = row[1] if row[1] else '<空字符串>'
                        checkpoint_id = row[2] or ''
                        print(f"{thread_id:<40} {checkpoint_ns:<30} {checkpoint_id[:36]:<40}")
                else:
                    print("表为空，没有数据")
                
                # 统计 checkpoint_ns 为空的记录数
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(checkpoint_ns) as has_ns,
                        COUNT(*) - COUNT(checkpoint_ns) as empty_ns,
                        COUNT(CASE WHEN checkpoint_ns = '' THEN 1 END) as blank_ns
                    FROM langgraph.checkpoints
                """)
                stats = cur.fetchone()
                print(f"\n统计信息:")
                print(f"  总记录数: {stats[0]}")
                print(f"  有 checkpoint_ns 值: {stats[1]}")
                print(f"  checkpoint_ns 为 NULL: {stats[2]}")
                print(f"  checkpoint_ns 为空字符串: {stats[3]}")
                
                # 2. 检查 checkpoint_writes 表
                print("\n" + "=" * 80)
                print("2. checkpoint_writes 表:")
                print("-" * 80)
                cur.execute("""
                    SELECT 
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        task_id
                    FROM langgraph.checkpoint_writes
                    LIMIT 10
                """)
                
                rows = cur.fetchall()
                if rows:
                    print(f"前 10 条记录:")
                    print(f"{'Thread ID':<40} {'Checkpoint NS':<30} {'Task ID':<20}")
                    print("-" * 90)
                    for row in rows:
                        thread_id = row[0] or ''
                        checkpoint_ns = row[1] if row[1] else '<空字符串>'
                        task_id = row[3] or ''
                        print(f"{thread_id:<40} {checkpoint_ns:<30} {task_id:<20}")
                else:
                    print("表为空，没有数据")
                
                # 统计 checkpoint_ns 为空的记录数
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(checkpoint_ns) as has_ns,
                        COUNT(*) - COUNT(checkpoint_ns) as empty_ns,
                        COUNT(CASE WHEN checkpoint_ns = '' THEN 1 END) as blank_ns
                    FROM langgraph.checkpoint_writes
                """)
                stats = cur.fetchone()
                print(f"\n统计信息:")
                print(f"  总记录数: {stats[0]}")
                print(f"  有 checkpoint_ns 值: {stats[1]}")
                print(f"  checkpoint_ns 为 NULL: {stats[2]}")
                print(f"  checkpoint_ns 为空字符串: {stats[3]}")
                
                # 3. 检查 checkpoint_blobs 表
                print("\n" + "=" * 80)
                print("3. checkpoint_blobs 表:")
                print("-" * 80)
                cur.execute("""
                    SELECT 
                        thread_id,
                        checkpoint_ns,
                        channel,
                        type
                    FROM langgraph.checkpoint_blobs
                    LIMIT 10
                """)
                
                rows = cur.fetchall()
                if rows:
                    print(f"前 10 条记录:")
                    print(f"{'Thread ID':<40} {'Checkpoint NS':<30} {'Channel':<20}")
                    print("-" * 90)
                    for row in rows:
                        thread_id = row[0] or ''
                        checkpoint_ns = row[1] if row[1] else '<空字符串>'
                        channel = row[2] or ''
                        print(f"{thread_id:<40} {checkpoint_ns:<30} {channel:<20}")
                else:
                    print("表为空，没有数据")
                
                # 统计 checkpoint_ns 为空的记录数
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(checkpoint_ns) as has_ns,
                        COUNT(*) - COUNT(checkpoint_ns) as empty_ns,
                        COUNT(CASE WHEN checkpoint_ns = '' THEN 1 END) as blank_ns
                    FROM langgraph.checkpoint_blobs
                """)
                stats = cur.fetchone()
                print(f"\n统计信息:")
                print(f"  总记录数: {stats[0]}")
                print(f"  有 checkpoint_ns 值: {stats[1]}")
                print(f"  checkpoint_ns 为 NULL: {stats[2]}")
                print(f"  checkpoint_ns 为空字符串: {stats[3]}")
                
                # 4. 查找刚才测试写入的记录
                print("\n" + "=" * 80)
                print("4. 测试记录验证（test_namespace_debug）:")
                print("-" * 80)
                cur.execute("""
                    SELECT 
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id
                    FROM langgraph.checkpoints
                    WHERE checkpoint_ns = 'test_namespace_debug'
                    LIMIT 5
                """)
                
                rows = cur.fetchall()
                if rows:
                    print(f"找到 {len(rows)} 条测试记录:")
                    for row in rows:
                        print(f"  Thread ID: {row[0]}")
                        print(f"  Checkpoint NS: {row[1]}")
                        print(f"  Checkpoint ID: {row[2]}")
                        print()
                else:
                    print("未找到测试记录（可能已被清理）")
                
    except Exception as e:
        print(f"数据库查询失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("=" * 80)


if __name__ == "__main__":
    check_checkpoint_ns()

