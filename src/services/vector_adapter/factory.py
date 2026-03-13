"""向量检索适配器工厂函数。

根据配置动态创建 PgVector 或 Milvus 适配器。
"""

from typing import Any, Dict, Optional

from src.services.config_loader import get_config
from src.services.vector_adapter.base import BaseVectorSearchAdapter
from src.services.vector_adapter.milvus_adapter import MilvusSearchAdapter
from src.services.vector_adapter.pgvector_adapter import PgVectorSearchAdapter
from src.utils.logger import get_module_logger

logger = get_module_logger("vector_factory")


def create_vector_search_adapter(
    subgraph_config: Optional[Dict[str, Any]] = None,
) -> BaseVectorSearchAdapter:
    """创建向量检索适配器（工厂函数）。

    根据全局配置（config.yaml）中的 vector_database.active 字段，
    动态创建 PgVector 或 Milvus 适配器。

    Args:
        subgraph_config: 子图配置（可选），用于传递 Milvus 搜索参数

    Returns:
        向量检索适配器实例

    Raises:
        ValueError: 配置缺失或 active 值非法

    Examples:
        >>> # 在 SchemaRetriever 中使用
        >>> adapter = create_vector_search_adapter(self.config)
        >>> tables = adapter.search_tables(embedding, top_k=10, similarity_threshold=0.5)
    """
    # 从全局配置读取向量数据库连接配置
    vector_db_config = get_config().get("vector_database")
    if not vector_db_config:
        raise ValueError(
            "缺少 vector_database 配置，请检查 config.yaml 中的 vector_database 段"
        )

    active_type = vector_db_config.get("active")
    if not active_type:
        raise ValueError(
            "缺少 vector_database.active 配置，请在 config.yaml 中设置 active: pgvector 或 active: milvus"
        )

    # 从子图配置读取 Milvus 搜索参数（仅 Milvus 使用）
    subgraph_config = subgraph_config or {}
    retrieval_config = subgraph_config.get("schema_retrieval", {})
    milvus_search_params = retrieval_config.get("milvus_search_params")

    # 根据类型创建适配器
    if active_type == "milvus":
        logger.info("✅ 使用 Milvus 向量数据库")
        return MilvusSearchAdapter(
            config=vector_db_config,
            search_params=milvus_search_params,
        )
    elif active_type == "pgvector":
        logger.info("✅ 使用 PgVector 向量数据库")
        return PgVectorSearchAdapter(vector_db_config)
    else:
        raise ValueError(
            f"不支持的向量数据库类型: {active_type}，仅支持 'pgvector' 或 'milvus'"
        )
