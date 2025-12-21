"""
验证 Milvus 返回的 distance 值

目标：
1. 直接使用 Milvus API 进行搜索
2. 查看 hit.distance 的原始值
3. 对比手动计算的余弦相似度
4. 验证转换公式是否正确
"""

import json
import math
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

    config_file = project_root / "src" / "configs" / "config.yaml"
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    config = resolve_env_vars(config)
    return config


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
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
    print("Milvus Distance 验证工具")
    print("=" * 80 + "\n")

    # 1. 加载配置
    config = load_config()
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # 2. 连接 Milvus
    from pymilvus import Collection, connections, db
    from src.services.embedding.embedding_client import get_embedding_client

    milvus_config = config.get("vector_database", {}).get("providers", {}).get("milvus", {})
    host = milvus_config.get("host", "localhost")
    port = str(milvus_config.get("port", "19530"))
    database = milvus_config.get("database", "nl2sql")
    alias = milvus_config.get("alias", "default")

    print(f"📋 连接到 Milvus: {host}:{port}/{database}\n")

    try:
        connections.connect(alias=alias, host=host, port=port, timeout=30)
        db.using_database(database, using=alias)

        # 3. 获取 Collection
        collection = Collection("table_schema_embeddings", using=alias)

        # 4. 准备测试查询
        test_query = "请问广州全家天河店的销售额是多少"
        print(f"📝 测试查询: {test_query}\n")

        # 5. 向量化查询
        embedding_client = get_embedding_client()
        query_embedding = embedding_client.embed_query(test_query)
        print(f"✅ 查询向量维度: {len(query_embedding)}\n")

        # 6. 使用 Milvus 搜索
        print(f"🔍 使用 Milvus 搜索（Top 10）...\n")
        search_params = {"metric_type": "COSINE", "params": {"ef": 100}}

        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=10,
            expr='object_type == "table"',
            output_fields=["object_id", "object_desc", "embedding"],
        )

        # 7. 分析结果
        print(f"{'排名':<6} {'表名':<40} {'Milvus Distance':<18} {'转换后相似度':<18} {'手动计算':<18} {'差异':<10}")
        print("-" * 120)

        for idx, hit in enumerate(results[0], 1):
            object_id = hit.entity.get("object_id")
            table_embedding = hit.entity.get("embedding")

            # Milvus 返回的原始距离
            milvus_distance = float(hit.distance)

            # 代码中的转换
            converted_similarity = 1.0 - milvus_distance
            clamped_similarity = max(0.0, min(1.0, converted_similarity))

            # 手动计算的余弦相似度
            manual_similarity = cosine_similarity(query_embedding, table_embedding)

            # 计算差异
            diff = abs(clamped_similarity - manual_similarity)

            # 标记关键表
            marker = ""
            if "maintenance_work_order" in object_id:
                marker = " ⚠️"
            elif "fact_store_sales_day" in object_id or "fact_store_sales_month" in object_id:
                marker = " ✅"

            print(f"{idx:<6} {object_id:<40} {milvus_distance:<18.6f} {clamped_similarity:<18.6f} {manual_similarity:<18.6f} {diff:<10.6f}{marker}")

        # 8. 重点分析
        print("\n" + "=" * 120)
        print("🔬 详细分析:\n")

        # 找到关键表
        fact_sales_day = None
        maintenance = None

        for hit in results[0]:
            object_id = hit.entity.get("object_id")
            if "fact_store_sales_day" in object_id:
                fact_sales_day = hit
            elif "maintenance_work_order" in object_id:
                maintenance = hit

        if fact_sales_day:
            print("✅ fact_store_sales_day:")
            print(f"   Milvus Distance: {float(fact_sales_day.distance):.6f}")
            print(f"   转换后相似度: {1.0 - float(fact_sales_day.distance):.6f}")
            print(f"   手动计算: {cosine_similarity(query_embedding, fact_sales_day.entity.get('embedding')):.6f}")
            print()

        if maintenance:
            print("⚠️  maintenance_work_order:")
            print(f"   Milvus Distance: {float(maintenance.distance):.6f}")
            print(f"   转换后相似度: {1.0 - float(maintenance.distance):.6f}")
            print(f"   手动计算: {cosine_similarity(query_embedding, maintenance.entity.get('embedding')):.6f}")
            print()

        # 9. 结论
        print("=" * 120)
        print("\n📊 结论:")
        print("-" * 80)
        print("\n如果 '转换后相似度' 与 '手动计算' 差异很小（< 0.001）：")
        print("   ✅ 说明转换公式正确，问题在于日志中记录的值不对")
        print("\n如果差异很大（> 0.01）：")
        print("   ❌ 说明 Milvus 的 COSINE distance 语义与预期不符")
        print()

    except Exception as exc:
        print(f"\n❌ 错误: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            connections.disconnect(alias=alias)
        except Exception:
            pass


if __name__ == "__main__":
    main()
