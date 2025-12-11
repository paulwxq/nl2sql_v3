"""测试维度值向量搜索功能

使用场景：
    给定一个查询字符串，从 Milvus dim_value_embeddings Collection 中
    查找语义最相似的维度值，用于 NL2SQL 中的值匹配。

运行方式：
    python tests/test_dim_value_search.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from typing import List, Dict, Any

from src.metaweave.services.embedding_service import EmbeddingService
from src.metaweave.services.vector_db.milvus_client import MilvusClient
from src.services.config_loader import ConfigLoader
# 导入 env 模块会自动加载 .env 文件（见 env.py 第 102 行）
import src.utils.env  # noqa: F401


def load_config(config_path: str = "configs/metaweave/metadata_config.yaml") -> Dict[str, Any]:
    """加载配置文件（支持环境变量替换）"""
    config_file = project_root / config_path
    loader = ConfigLoader(str(config_file))
    return loader.load()


def search_dim_values(
    query_text: str,
    top_k: int = 5,
    filter_table: str | None = None
) -> List[Dict[str, Any]]:
    """搜索语义相似的维度值

    Args:
        query_text: 查询字符串（如 "上海"、"华东地区"）
        top_k: 返回前 k 个最相似的结果
        filter_table: 可选，只在指定表中搜索（如 "public.dim_region"）

    Returns:
        List[Dict]: 相似度最高的维度值列表，每个字典包含：
            - table_name: 表名
            - col_name: 列名
            - col_value: 列值
            - cosine_similarity: 余弦相似度（-1~1，越大越相似）
            - similarity_score: 相似度分数（-1~1，越大越相似）
    """
    # 1. 加载配置（环境变量已在模块导入时自动加载）
    config = load_config()

    # 2. 初始化 Embedding 服务
    embedding_config = config.get("embedding", {})
    embedding_service = EmbeddingService(embedding_config)

    # 3. 初始化 Milvus 客户端
    vector_db_config = config["vector_database"]["providers"]["milvus"]
    milvus_client = MilvusClient(vector_db_config)
    milvus_client.connect()

    # 4. 生成查询向量
    print(f"🔍 查询文本: {query_text}")
    # get_embedding() 返回单个向量（而不是字典）
    query_embedding = embedding_service.get_embedding(query_text)
    print(f"✅ 生成查询向量: {len(query_embedding)} 维")

    # 5. 构建搜索参数
    collection_name = "dim_value_embeddings"
    search_params = {
        "metric_type": "COSINE",  # 使用余弦相似度
        "params": {"ef": 64}       # HNSW 搜索参数
    }

    # 6. 构建过滤表达式（可选）
    filter_expr = None
    if filter_table:
        filter_expr = f'table_name == "{filter_table}"'
        print(f"🔎 过滤条件: {filter_expr}")

    # 7. 执行向量搜索
    print(f"🚀 搜索 Milvus Collection: {collection_name}")

    try:
        # 获取 Collection 对象
        from pymilvus import Collection
        collection = Collection(collection_name)
        collection.load()

        # 执行搜索
        results = collection.search(
            data=[query_embedding],           # 查询向量
            anns_field="embedding",           # 向量字段名
            param=search_params,              # 搜索参数
            limit=top_k,                      # 返回前 k 个结果
            expr=filter_expr,                 # 过滤表达式
            output_fields=["table_name", "col_name", "col_value"]  # 返回字段
        )

        # 8. 解析结果
        search_results = []
        if results and len(results) > 0:
            for hit in results[0]:
                # 注意：Milvus 对 COSINE metric 返回的 distance 实际上是余弦相似度
                # 范围 [-1, 1]，值越大越相似
                search_results.append({
                    "table_name": hit.entity.get("table_name"),
                    "col_name": hit.entity.get("col_name"),
                    "col_value": hit.entity.get("col_value"),
                    "cosine_similarity": hit.distance,  # 这就是余弦相似度（越大越相似）
                    "similarity_score": hit.distance    # 相似度分数（0-1，越大越相似）
                })

        return search_results

    except Exception as e:
        print(f"❌ 搜索失败: {e}")
        raise
    finally:
        milvus_client.close()


def print_results(results: List[Dict[str, Any]]):
    """打印搜索结果"""
    print("\n" + "=" * 80)
    print("📊 搜索结果")
    print("=" * 80)

    if not results:
        print("⚠️  未找到匹配结果")
        return

    for idx, result in enumerate(results, 1):
        similarity = result['similarity_score']
        print(f"\n[{idx}] 余弦相似度: {similarity:.4f} (范围 -1~1，越大越相似)")
        print(f"    表名: {result['table_name']}")
        print(f"    列名: {result['col_name']}")
        print(f"    值  : {result['col_value']}")

    print("\n" + "=" * 80)


def main():
    """主函数：测试不同的查询场景"""

    # ========== 测试场景 1: 无过滤条件的全局搜索 ==========
    print("\n" + "=" * 80)
    print("测试场景 1: 全局搜索")
    print("=" * 80)

    query_text = "全家姑苏店"
    results = search_dim_values(query_text, top_k=5)
    print_results(results)

    # ========== 测试场景 2: 指定表范围搜索 ==========
    print("\n\n" + "=" * 80)
    print("测试场景 2: 指定表搜索")
    print("=" * 80)

    query_text = "华东"
    filter_table = "public.dim_region"
    results = search_dim_values(query_text, top_k=5, filter_table=filter_table)
    print_results(results)

    # ========== 测试场景 3: 公司名称搜索 ==========
    print("\n\n" + "=" * 80)
    print("测试场景 3: 公司名称搜索")
    print("=" * 80)

    query_text = "京东便利店"
    results = search_dim_values(query_text, top_k=5)
    print_results(results)

    # ========== 测试场景 4: 模糊语义搜索 ==========
    print("\n\n" + "=" * 80)
    print("测试场景 4: 模糊语义搜索")
    print("=" * 80)

    query_text = "信息部"
    results = search_dim_values(query_text, top_k=5)
    print_results(results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
