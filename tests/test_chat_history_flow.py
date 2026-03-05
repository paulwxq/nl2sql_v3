"""对话历史记录流程验证脚本 (带 Schema 识别)

验证：
1. append_turn 写入
2. get_recent_turns 读取
3. 扫描数据库并自动识别存在的 schema
"""

import sys
import os
import uuid
import time
import psycopg

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from src.services.langgraph_persistence import (
    append_turn, 
    get_recent_turns, 
    setup_persistence, 
    close_persistence,
    build_db_uri_from_config
)

def verify_chat_history():
    print("=" * 80)
    print("对话历史记录流程验证")
    print("=" * 80)

    # 1. 初始化持久化层
    if not setup_persistence():
        print("✗ 持久化层初始化失败")
        return

    test_thread_id = f"test-hist-{uuid.uuid4().hex[:6]}"
    test_user_id = "test_user_001"
    db_uri = build_db_uri_from_config()
    
    print(f"\n[1] 写入模拟对话数据 (ThreadID: {test_thread_id})")
    append_turn(
        thread_id=test_thread_id,
        query_id="q-0",
        user_text="列出所有员工",
        assistant_text="SELECT * FROM employees;",
        user_id=test_user_id,
        success=True
    )
    
    # 等待异步写入完成
    time.sleep(2)

    # 2. 读取验证
    print("\n[2] 读取对话历史")
    history = get_recent_turns(
        thread_id=test_thread_id, 
        history_max_turns=5,
        max_history_content_length=500
    )
    
    if history:
        print(f"  ✓ 成功读取到 {len(history)} 轮记录")
        for turn in history:
            print(f"    - [Q] {turn['question']}")
            print(f"    - [A] {turn['answer']}")
    else:
        print("  ✗ 读取结果为空")

    # 3. 数据库表验证
    print("\n[3] 数据库表扫描")
    try:
        with psycopg.connect(db_uri) as conn:
            with conn.cursor() as cur:
                # 3.1 查找 store 表所在的 schema
                cur.execute("""
                    SELECT table_schema 
                    FROM information_schema.tables 
                    WHERE table_name = 'store'
                """)
                schemas = [row[0] for row in cur.fetchall()]
                print(f"  发现 store 表所在的 schema: {schemas}")
                
                for schema in schemas:
                    print(f"  正在检查 {schema}.store ...")
                    # 使用动态 SQL 时要注意安全，这里是测试脚本
                    query = f'SELECT COUNT(*) FROM "{schema}"."store" WHERE prefix = %s'
                    cur.execute(query, (['chat_history', test_thread_id],))
                    count = cur.fetchone()[0]
                    print(f"    - 记录数: {count}")
                    
                    if count > 0:
                        query_sample = f'SELECT key, value FROM "{schema}"."store" WHERE prefix = %s LIMIT 1'
                        cur.execute(query_sample, (['chat_history', test_thread_id],))
                        key, value = cur.fetchone()
                        print(f"    - 样本 Key: {key}")
                        print(f"    - 样本 Value[user]: {value['user']['content']}")

    except Exception as e:
        print(f"  ✗ 数据库查询失败: {e}")

    close_persistence()
    print("\n" + "=" * 80)

if __name__ == "__main__":
    verify_chat_history()
