"""
调试 Milvus 相似度问题 - 分析为什么 maintenance_work_order 相似度最高

目标：
1. 查询 Milvus 中所有表的 object_desc（用于生成 embedding 的文本）
2. 对测试查询进行向量化
3. 手动计算相似度并排序
4. 分析为什么 maintenance_work_order 会排在前面
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv


def resolve_env_vars(config: Any) -> Any:
    """递归解析配置中的环境变量占位符。"""
    if isinstance(config, dict):
        return {k: resolve_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [resolve_env_vars(item) for item in config]
    elif isinstance(config, str):
        pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'
        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_value)
        return re.sub(pattern, replacer, config)
    else:
        return config


def load_config() -> Dict[str, Any]:
    """加载配置文件和环境变量。"""
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"

    if env_file.exists():
        load_dotenv(env_file)
        print(f"✅ 已加载环境变量: {env_file}")

    config_file = project_root / "src" / "configs" / "config.yaml"
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    config = resolve_env_vars(config)
    print(f"✅ 已加载配置文件: {config_file}\n")
    return config


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """计算余弦相似度。"""
    import math
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)


def main():
    """主函数。"""
    print("=" * 80)
    print("Milvus 相似度调试工具")
    print("=" * 80)

    # 1. 加载配置
    config = load_config()

    # 2. 连接 Milvus
    from pymilvus import Collection, connections, db

    milvus_config = config.get("vector_database", {}).get("providers", {}).get("milvus", {})
    host = milvus_config.get("host", "localhost")
    port = str(milvus_config.get("port", "19530"))
    database = milvus_config.get("database", "nl2sql")
    alias = milvus_config.get("alias", "default")

    print(f"📋 连接信息:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Database: {database}\n")

    try:
        print(f"🔗 连接 Milvus...")
        connections.connect(
            alias=alias,
            host=host,
            port=port,
            timeout=30,
        )

        # 切换 database
        db.using_database(database, using=alias)
        print(f"✅ 已连接并切换到 database: {database}\n")

        # 3. 获取 Collection
        collection = Collection("table_schema_embeddings", using=alias)
        print(f"📊 Collection 信息:")
        print(f"   记录数: {collection.num_entities:,}\n")

        # 4. 查询所有表级别的记录（object_type='table'）
        print(f"🔍 查询所有表的 object_desc...")
        results = collection.query(
            expr='object_type == "table"',
            output_fields=["object_id", "object_desc", "table_category", "embedding"],
            limit=100,
        )

        print(f"✅ 查询到 {len(results)} 个表\n")

        # 5. 对测试查询进行向量化
        test_query = "请问广州全家天河店的销售额是多少"
        print(f"📝 测试查询: {test_query}")

        # 使用项目的 embedding 客户端
        project_root = Path(__file__).parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from src.services.embedding.embedding_client import get_embedding_client

        embedding_client = get_embedding_client()
        query_embedding = embedding_client.embed_query(test_query)
        print(f"✅ 查询向量维度: {len(query_embedding)}\n")

        # 6. 计算每个表与查询的相似度
        print(f"🔢 计算相似度...")
        print("=" * 80)

        similarities = []
        for row in results:
            object_id = row.get("object_id")
            object_desc = row.get("object_desc", "")
            table_category = row.get("table_category", "")
            table_embedding = row.get("embedding", [])

            if not table_embedding:
                continue

            # 计算余弦相似度
            similarity = cosine_similarity(query_embedding, table_embedding)

            similarities.append({
                "object_id": object_id,
                "similarity": similarity,
                "table_category": table_category,
                "object_desc": object_desc,
            })

        # 7. 按相似度降序排序
        similarities.sort(key=lambda x: x["similarity"], reverse=True)

        # 8. 输出结果
        print(f"\n📊 相似度排序结果（Top 15）:\n")
        print(f"{'排名':<6} {'表名':<40} {'相似度':<10} {'类型':<10}")
        print("-" * 80)

        for idx, item in enumerate(similarities[:15], 1):
            table_id = item["object_id"]
            sim = item["similarity"]
            cat = item["table_category"]

            # 高亮显示关键表
            marker = ""
            if "maintenance_work_order" in table_id:
                marker = " ⚠️  [问题表]"
            elif "fact_store_sales" in table_id:
                marker = " ✅ [正确表]"

            print(f"{idx:<6} {table_id:<40} {sim:<10.4f} {cat:<10}{marker}")

        # 9. 详细分析 Top 5
        print(f"\n" + "=" * 80)
        print(f"📋 Top 5 表的 object_desc 详情:\n")

        for idx, item in enumerate(similarities[:5], 1):
            table_id = item["object_id"]
            sim = item["similarity"]
            desc = item["object_desc"]
            cat = item["table_category"]

            print(f"{idx}. {table_id} (相似度: {sim:.4f}, 类型: {cat})")
            print(f"   描述: {desc}")
            print()

        # 10. 对比分析：maintenance_work_order vs fact_store_sales_day
        print("=" * 80)
        print("🔬 对比分析:\n")

        maint_item = next((x for x in similarities if "maintenance_work_order" in x["object_id"]), None)
        sales_day_item = next((x for x in similarities if "fact_store_sales_day" in x["object_id"]), None)

        if maint_item and sales_day_item:
            print(f"maintenance_work_order:")
            print(f"  相似度: {maint_item['similarity']:.4f}")
            print(f"  描述: {maint_item['object_desc']}")
            print()
            print(f"fact_store_sales_day:")
            print(f"  相似度: {sales_day_item['similarity']:.4f}")
            print(f"  描述: {sales_day_item['object_desc']}")
            print()

            diff = maint_item['similarity'] - sales_day_item['similarity']
            print(f"📊 相似度差异: {diff:.4f}")

            if diff > 0:
                print(f"⚠️  maintenance_work_order 的相似度比 fact_store_sales_day 高 {diff:.4f}")
                print(f"\n💡 可能的原因:")
                print(f"   1. object_desc 的文本内容与查询更匹配")
                print(f"   2. Embedding 向量本身存在偏差")
                print(f"   3. 数据加载时使用了不同的描述文本")
            else:
                print(f"✅ fact_store_sales_day 的相似度更高")

        # 11. 保存结果到 JSON
        output_file = Path(__file__).parent / "milvus_similarity_debug_result.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                "query": test_query,
                "similarities": similarities[:15],
                "config": {
                    "host": host,
                    "port": port,
                    "database": database,
                }
            }, f, indent=2, ensure_ascii=False)

        print(f"\n💾 结果已保存到: {output_file}")

    except Exception as exc:
        print(f"\n❌ 错误: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            connections.disconnect(alias=alias)
            print(f"\n👋 已断开连接")
        except Exception:
            pass


if __name__ == "__main__":
    main()
