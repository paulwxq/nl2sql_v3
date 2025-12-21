"""
对比 Milvus 和 PgVector 中的 Embedding 数据

验证：
1. 同一个对象（表/列）在两个数据库中的 embedding 是否相同
2. 相似度计算是否一致
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.config_loader import get_config
from src.services.db.pg_client import PGClient
from src.services.embedding.embedding_client import get_embedding_client
from pymilvus import Collection, connections, db
import math


def cosine_similarity(vec1, vec2):
    """计算余弦相似度。"""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)


def main():
    """主函数。"""
    print("=" * 80)
    print("Milvus vs PgVector Embedding 对比")
    print("=" * 80 + "\n")

    config = get_config()

    # 测试查询
    test_query = "请问广州全家天河店的销售额是多少"
    print(f"📝 测试查询: {test_query}\n")

    # 生成查询向量
    embedding_client = get_embedding_client()
    query_embedding = embedding_client.embed_query(test_query)
    print(f"✅ 查询向量维度: {len(query_embedding)}\n")

    # 关注的对象
    test_objects = [
        "public.fact_store_sales_day.amount",
        "public.order_item.quantity",
        "public.employee.salary",
    ]

    print(f"🔍 检查以下对象的 embedding:\n")
    for obj in test_objects:
        print(f"  - {obj}")
    print()

    # 1. 从 Milvus 获取
    print("=" * 80)
    print("📊 从 Milvus 获取数据\n")

    milvus_config = config.get("vector_database", {}).get("providers", {}).get("milvus", {})
    host = milvus_config.get("host", "localhost")
    port = str(milvus_config.get("port", "19530"))
    database = milvus_config.get("database", "nl2sql")
    alias = milvus_config.get("alias", "default")

    connections.connect(alias=alias, host=host, port=port, timeout=30)
    db.using_database(database, using=alias)

    collection = Collection("table_schema_embeddings", using=alias)

    milvus_data = {}
    for obj_id in test_objects:
        results = collection.query(
            expr=f'object_id == "{obj_id}"',
            output_fields=["object_id", "object_desc", "embedding"],
            limit=1,
        )
        if results:
            milvus_data[obj_id] = {
                "desc": results[0].get("object_desc", ""),
                "embedding": results[0].get("embedding", []),
            }
            # 计算相似度
            similarity = cosine_similarity(query_embedding, milvus_data[obj_id]["embedding"])
            print(f"✅ {obj_id}")
            print(f"   相似度: {similarity:.4f}")
            print(f"   描述: {milvus_data[obj_id]['desc'][:100]}...")
            print()

    connections.disconnect(alias=alias)

    # 2. 从 PgVector 获取
    print("=" * 80)
    print("📊 从 PgVector 获取数据\n")

    pg_client = PGClient()

    for obj_id in test_objects:
        # 查询 PgVector
        query = """
        SELECT object_id, text_raw, embedding,
               1 - (embedding <=> %s::vector) AS similarity
        FROM system.sem_object_vec
        WHERE object_id = %s
        LIMIT 1
        """
        results = pg_client.execute_query(query, (query_embedding, obj_id))

        if results:
            row = results[0]
            print(f"✅ {obj_id}")
            print(f"   相似度: {row['similarity']:.4f}")
            print(f"   描述: {row['text_raw'][:100]}...")
            print()

            # 对比
            if obj_id in milvus_data:
                milvus_sim = cosine_similarity(query_embedding, milvus_data[obj_id]["embedding"])
                pg_sim = row['similarity']
                diff = abs(milvus_sim - pg_sim)

                print(f"   📊 对比:")
                print(f"      Milvus 相似度: {milvus_sim:.4f}")
                print(f"      PgVector 相似度: {pg_sim:.4f}")
                print(f"      差异: {diff:.4f}")

                if diff > 0.01:
                    print(f"      ⚠️  差异较大！可能是 embedding 数据不一致")
                else:
                    print(f"      ✅ 差异很小，数据一致")
                print()

    print("=" * 80)
    print("\n💡 结论:")
    print("   如果差异 > 0.01，说明 Milvus 和 PgVector 中的 embedding 数据不一致")
    print("   需要重新加载数据到 Milvus")


if __name__ == "__main__":
    main()
