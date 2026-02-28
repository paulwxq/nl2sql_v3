"""验证脚本：Checkpoint 分离效果验证 (数据库级别)

验证：
1. 父图 Checkpoint 是否能够正常写入数据库
2. 子图 Saver 是否为 None（即被正确禁用）
3. 检查数据库中当前的命名空间分布
"""

import sys
import os
import uuid
import psycopg
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from src.services.langgraph_persistence.postgres import (
    get_postgres_saver,
    is_father_checkpoint_enabled,
    is_subgraph_checkpoint_enabled,
    build_db_uri_from_config
)

def verify_db():
    print("=" * 80)
    print("Checkpoint 分离效果验证 (数据库级别)")
    print("=" * 80)
    
    try:
        db_uri = build_db_uri_from_config()
        # 隐藏密码部分
        safe_uri = db_uri.split('@')[0].split(':')[0] + ':***@' + db_uri.split('@')[1]
        print(f"目标数据库: {safe_uri}")
    except Exception as e:
        print(f"✗ 无法构建数据库连接串: {e}")
        return
    
    # 1. 验证配置状态
    print("\n[1] 配置状态检查")
    f_enabled = is_father_checkpoint_enabled()
    s_enabled = is_subgraph_checkpoint_enabled()
    print(f"  父图 Checkpoint 开启状态: {'ON' if f_enabled else 'OFF'}")
    print(f"  子图 Checkpoint 开启状态: {'ON' if s_enabled else 'OFF'}")
    
    # 2. 验证父图写入能力
    print("\n[2] 父图持久化能力测试")
    if f_enabled:
        saver = get_postgres_saver("father")
        if saver:
            test_thread_id = f"verify-f-{uuid.uuid4().hex[:6]}"
            # 模拟写入一个极简 checkpoint
            config = {"configurable": {"thread_id": test_thread_id, "checkpoint_ns": "nl2sql_father"}}
            checkpoint = Checkpoint(
                v=1, 
                id=str(uuid.uuid4()), 
                ts="2026-02-28T12:00:00Z", 
                channel_values={"test": "persistence_ok"}, 
                channel_versions={}, 
                versions_seen={}
            )
            metadata = CheckpointMetadata(source="verify_script", step=0, writes={}, parents={})
            
            try:
                saver.put(config, checkpoint, metadata, {})
                print(f"  ✓ 成功向 'nl2sql_father' 命名空间写入测试记录")
                print(f"    thread_id: {test_thread_id}")
                
                # 从数据库查询确认
                # 注意：build_db_uri_from_config 已经设置了 search_path，所以直接用表名
                with psycopg.connect(db_uri) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id = %s", (test_thread_id,))
                        count = cur.fetchone()[0]
                        if count > 0:
                            print(f"  ✓ 数据库校验成功: 在 checkpoints 中找到 {count} 条记录")
                        else:
                            print("  ✗ 数据库校验失败: 未找到刚写入的记录")
            except Exception as e:
                print(f"  ✗ 写入测试失败: {e}")
        else:
            print("  ✗ 无法获取父图 Saver 实例")
    else:
        print("  - 父图 Checkpoint 已关闭，跳过测试")

    # 3. 验证子图禁用状态
    print("\n[3] 子图禁用状态检查")
    if not s_enabled:
        saver = get_postgres_saver("subgraph")
        if saver is None:
            print("  ✓ 确认: get_postgres_saver('subgraph') 返回 None (符合预期)")
        else:
            print("  ✗ 警告: 子图配置已关闭，但 get_postgres_saver 仍返回了实例")
    else:
        print("  - 子图 Checkpoint 当前为开启状态 (不符合本次优化的默认预期)")

    # 4. 检查命名空间
    print("\n[4] 数据库命名空间扫描")
    try:
        with psycopg.connect(db_uri) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT checkpoint_ns FROM checkpoints")
                rows = cur.fetchall()
                namespaces = [row[0] for row in rows if row[0] is not None]
                print(f"  当前数据库中存在的命名空间: {namespaces}")
                
                # 检查是否有 'sql_generation' 开头的 ns
                sub_ns = [ns for ns in namespaces if ns and ns.startswith("sql_generation")]
                if sub_ns:
                    print(f"  ! 注意: 发现子图命名空间记录: {sub_ns}")
                    print(f"    (若这是最近产生的，说明子图 Checkpoint 可能未被完全隔离)")
                else:
                    print("  ✓ 数据库中目前没有子图命名空间记录")
    except Exception as e:
        print(f"  ✗ 扫描失败: {e}")

    print("\n" + "=" * 80)
    print("验证完成")
    print("=" * 80)

if __name__ == "__main__":
    verify_db()
