"""
测试 Milvus 相似度修复

验证修复后：
1. fact_store_sales_day 相似度最高
2. maintenance_work_order 相似度较低
3. 表排序正确
"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.config_loader import get_config
from src.services.embedding.embedding_client import get_embedding_client
from src.services.vector_adapter import create_vector_search_adapter


def main():
    """主函数。"""
    print("=" * 80)
    print("Milvus 修复验证测试")
    print("=" * 80 + "\n")

    # 1. 加载配置
    config = get_config()

    # 确认使用 Milvus
    active_db = config.get("vector_database", {}).get("active")
    print(f"📋 当前向量数据库: {active_db}")

    if active_db != "milvus":
        print(f"⚠️  警告：当前不是 Milvus，而是 {active_db}")
        print(f"请在 config.yaml 中设置 vector_database.active: milvus")
        return

    # 2. 初始化客户端
    print(f"\n🔗 初始化向量搜索适配器...\n")
    vector_adapter = create_vector_search_adapter(config.get("sql_generation", {}))
    embedding_client = get_embedding_client()

    # 3. 测试查询
    test_query = "请问广州全家天河店的销售额是多少"
    print(f"📝 测试查询: {test_query}\n")

    # 4. 生成查询向量
    print(f"🔍 向量化查询...")
    query_embedding = embedding_client.embed_query(test_query)
    print(f"✅ 查询向量维度: {len(query_embedding)}\n")

    # 5. 使用适配器搜索（修复后）
    print(f"🔍 搜索相关表（Top 10）...\n")
    results = vector_adapter.search_tables(
        embedding=query_embedding,
        top_k=10,
        similarity_threshold=0.0,  # 不过滤，查看所有结果
    )

    # 6. 输出结果
    print(f"{'排名':<6} {'表名':<40} {'相似度':<10} {'类型':<10}")
    print("-" * 80)

    for idx, result in enumerate(results, 1):
        table_id = result.get("object_id")
        similarity = result.get("similarity")
        category = result.get("table_category", "")

        # 标记关键表
        marker = ""
        if "maintenance_work_order" in table_id:
            marker = " ⚠️  [问题表]"
        elif "fact_store_sales" in table_id:
            marker = " ✅ [正确表]"

        print(f"{idx:<6} {table_id:<40} {similarity:<10.4f} {category:<10}{marker}")

    # 7. 验证结果
    print("\n" + "=" * 80)
    print("📊 验证结果:\n")

    fact_sales_day = next((r for r in results if "fact_store_sales_day" in r["object_id"]), None)
    maintenance = next((r for r in results if "maintenance_work_order" in r["object_id"]), None)

    if fact_sales_day and maintenance:
        fact_sim = fact_sales_day["similarity"]
        maint_sim = maintenance["similarity"]

        print(f"✅ fact_store_sales_day 相似度: {fact_sim:.4f}")
        print(f"⚠️  maintenance_work_order 相似度: {maint_sim:.4f}")
        print()

        if fact_sim > maint_sim:
            print(f"✅ 修复成功！fact_store_sales_day 的相似度更高（{fact_sim:.4f} > {maint_sim:.4f}）")
            print(f"   正确的表被选为 Base 表")
        else:
            print(f"❌ 修复失败！maintenance_work_order 的相似度仍然更高")
            print(f"   这不应该发生，请检查代码")

        # 检查排名
        fact_rank = next((i for i, r in enumerate(results, 1) if "fact_store_sales_day" in r["object_id"]), None)
        maint_rank = next((i for i, r in enumerate(results, 1) if "maintenance_work_order" in r["object_id"]), None)

        print(f"\n📊 排名对比:")
        print(f"   fact_store_sales_day: 第 {fact_rank} 名")
        print(f"   maintenance_work_order: 第 {maint_rank} 名")

        if fact_rank and maint_rank and fact_rank < maint_rank:
            print(f"   ✅ 排序正确")
        else:
            print(f"   ❌ 排序错误")

    print("\n" + "=" * 80)
    print("\n💡 预期结果:")
    print("   1. fact_store_sales_day 应该排在前面（相似度 ~0.50）")
    print("   2. maintenance_work_order 应该排在后面（相似度 ~0.33）")
    print("   3. 修复前的错误值（0.67 和 0.50）应该消失")


if __name__ == "__main__":
    main()
