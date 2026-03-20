"""Milvus 向量检索适配器。

基于 Milvus 向量数据库实现统一的检索接口。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from src.services.config_loader import get_config
from src.services.embedding.embedding_client import get_embedding_client
from src.services.vector_adapter.base import BaseVectorSearchAdapter
from src.services.vector_db.milvus_client import MilvusClient, _lazy_import_milvus
from src.utils.logger import get_module_logger

logger = get_module_logger("milvus_adapter")


class MilvusSearchAdapter(BaseVectorSearchAdapter):
    """Milvus 检索适配器。

    关键技术点：
    1. COSINE 度量：Milvus 的 hit.distance 返回的是相似度本身（不需要 1.0 - distance 转换）
    2. Collection 名称：table_schema_embeddings（表/列）、dim_value_embeddings（维度值）
    3. 字段映射：grain_hint=None, table_category 允许空，不返回 key_col/key_value
    4. 精确查询：使用 JSON 序列化避免单引号问题

    重要说明：
    - Milvus 2.x 的 COSINE 度量直接返回余弦相似度 [0, 1]，数值越大越相似
    - 这与 PgVector 的行为一致（1 - <=> 运算符）
    - 测试验证：hit.distance ≈ 手动计算的 cosine_similarity(query_vec, doc_vec)
    """

    def __init__(
        self,
        config: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None,
    ):
        """初始化 Milvus 适配器。

        Args:
            config: 向量数据库配置（来自 config.yaml 的 vector_database 段）
            search_params: Milvus 搜索参数（来自 subgraph config 的 milvus_search_params）

        Raises:
            ValueError: 当 Milvus 配置缺失或不完整时
        """
        super().__init__(config)
        self.config = config
        self.search_params = search_params or {
            "metric_type": "COSINE",
            "params": {"ef": 100},
        }

        # ⚠️ 验证 Milvus 配置完整性（防止悄悄连到 localhost）
        milvus_config = config.get("providers", {}).get("milvus")
        if not milvus_config:
            raise ValueError(
                "Milvus 配置缺失：vector_database.providers.milvus 未配置。"
                "请在 config.yaml 中添加 Milvus 连接配置（host, port, database 等）。"
            )

        # 验证必需字段
        required_fields = ["host", "database"]
        missing_fields = [f for f in required_fields if not milvus_config.get(f)]
        if missing_fields:
            raise ValueError(
                f"Milvus 配置不完整：缺少必需字段 {missing_fields}。"
                f"请在 config.yaml 的 vector_database.providers.milvus 中配置这些字段。"
            )

        # 初始化 Milvus 客户端
        self.milvus_client = MilvusClient(milvus_config)
        self.milvus_client.connect()

        # 获取 Collection 对象（延迟加载）
        _, _, _, _, Collection, _, _ = _lazy_import_milvus()
        self._Collection = Collection
        self._collection_table_schema: Optional[Any] = None
        self._collection_dim_value: Optional[Any] = None
        self._collection_sql_example: Optional[Any] = None

        # 获取 Embedding 客户端（用于 search_dim_values）
        self.embedding_client = get_embedding_client()

        logger.info("✅ Milvus 适配器初始化完成")

    def _get_table_schema_collection(self) -> Any:
        """获取 table_schema_embeddings Collection（懒加载）。"""
        if self._collection_table_schema is None:
            self._collection_table_schema = self._Collection(
                "table_schema_embeddings",
                using=self.milvus_client.alias,
            )
        return self._collection_table_schema

    def _get_dim_value_collection(self) -> Any:
        """获取 dim_value_embeddings Collection（懒加载）。"""
        if self._collection_dim_value is None:
            self._collection_dim_value = self._Collection(
                "dim_value_embeddings",
                using=self.milvus_client.alias,
            )
        return self._collection_dim_value

    def _get_sql_example_collection(self) -> Any:
        """获取 sql_example_embeddings Collection（懒加载）。"""
        if self._collection_sql_example is None:
            self._collection_sql_example = self._Collection(
                "sql_example_embeddings",
                using=self.milvus_client.alias,
            )
        return self._collection_sql_example

    def _get_search_params(self) -> Dict[str, Any]:
        """获取 Milvus 搜索参数。"""
        return self.search_params

    def _get_business_db_name(self) -> str:
        """获取业务数据库名，用于绑定 db_name 过滤条件。"""
        config = get_config()
        db_name = config.get("database.database", "")
        return str(db_name or "")

    def search_tables(
        self,
        embedding: List[float],
        top_k: int,
        similarity_threshold: float,
    ) -> List[Dict[str, Any]]:
        """检索语义相关的表。

        使用 table_schema_embeddings Collection，过滤 object_type='table'。

        Note:
            - time_col_hint 字段在 Milvus 中存在（仅 table 类型可能有值）
            - grain_hint 字段 Milvus 中不存在，返回 None
        """
        collection = self._get_table_schema_collection()

        # Milvus 搜索（不支持 expr 中过滤向量相似度，只能在结果中过滤）
        search_expr = 'object_type == "table"'
        search_limit = top_k * 2
        logger.debug(f"search_tables: collection={collection.name}, expr={search_expr!r}, limit={search_limit}, threshold={similarity_threshold}")
        results = collection.search(
            data=[embedding],
            anns_field="embedding",
            param=self._get_search_params(),
            limit=search_limit,
            expr=search_expr,
            output_fields=["object_id", "object_type", "table_name", "table_category", "time_col_hint"],
        )

        matches = []
        for hit in results[0]:
            # ⚠️ COSINE 度量说明：Milvus 的 COSINE 返回的是相似度本身（不是距离）
            # 测试验证：hit.distance ≈ 手动计算的 cosine_similarity，范围 [0, 1]
            similarity_raw = float(hit.distance)  # 直接使用，无需转换

            # 阈值过滤
            if similarity_raw < similarity_threshold:
                continue

            # clamp 用于返回值（数值规范化，虽然 Milvus 已经在 [0,1] 范围内）
            similarity = max(0.0, min(1.0, similarity_raw))

            matches.append({
                "object_id": hit.entity.get("object_id"),
                "table_name": hit.entity.get("table_name"),
                "object_type": "table",
                "similarity": similarity,
                "grain_hint": None,  # ⚠️ Milvus 无此字段
                "time_col_hint": hit.entity.get("time_col_hint"),  # Milvus 有此字段（仅 table 类型可能有值）
                "table_category": hit.entity.get("table_category", ""),
            })

            if len(matches) >= top_k:
                break

        return matches

    def search_columns(
        self,
        embedding: List[float],
        top_k: int,
        similarity_threshold: float,
    ) -> List[Dict[str, Any]]:
        """检索语义相关的列。

        使用 table_schema_embeddings Collection，过滤 object_type='column'。
        """
        collection = self._get_table_schema_collection()

        search_expr = 'object_type == "column"'
        search_limit = top_k * 2
        logger.debug(f"search_columns: collection={collection.name}, expr={search_expr!r}, limit={search_limit}, threshold={similarity_threshold}")
        results = collection.search(
            data=[embedding],
            anns_field="embedding",
            param=self._get_search_params(),
            limit=search_limit,
            expr=search_expr,
            output_fields=["object_id", "object_type", "table_name", "table_category"],
        )

        matches = []
        for hit in results[0]:
            # ⚠️ COSINE 度量说明：Milvus 的 COSINE 返回的是相似度本身（不是距离）
            similarity_raw = float(hit.distance)  # 直接使用，无需转换

            # 阈值过滤
            if similarity_raw < similarity_threshold:
                continue

            # clamp 用于返回值
            similarity = max(0.0, min(1.0, similarity_raw))

            matches.append({
                "object_id": hit.entity.get("object_id"),
                "table_name": hit.entity.get("table_name"),
                "object_type": "column",
                "similarity": similarity,
                "grain_hint": None,  # ⚠️ Milvus 无此字段
                "table_category": hit.entity.get("table_category", ""),  # 允许空
            })

            if len(matches) >= top_k:
                break

        return matches

    def search_dim_values(
        self,
        query_value: str,
        top_k: int,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索维度值匹配。

        使用 dim_value_embeddings Collection，需先对 query_value 进行向量化。

        Note:
            - 不返回 key_col/key_value（Milvus 数据中无此字段）
            - 下游需兼容处理（value_matcher 中降级展示）
        """
        collection = self._get_dim_value_collection()

        # 向量化 query_value
        query_embedding = self.embedding_client.embed_query(query_value)
        business_db_name = self._get_business_db_name()
        search_expr = f"db_name == {json.dumps(business_db_name)}" if business_db_name else None

        # Milvus 搜索
        # ⚠️ 多取一些数据，后续在内存中过滤阈值
        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=self._get_search_params(),
            limit=top_k * 2 if min_score > 0.0 else top_k,
            expr=search_expr,
            output_fields=["table_name", "col_name", "col_value"],
        )

        matches = []
        for hit in results[0]:
            # ⚠️ COSINE 度量说明：Milvus 的 COSINE 返回的是相似度本身（不是距离）
            score_raw = float(hit.distance)  # 直接使用，无需转换

            # ✅ 阈值过滤（使用 min_score 参数）
            if score_raw < min_score:
                continue  # 低分结果被正确排除

            # clamp 用于返回值（数值规范化）
            score = max(0.0, min(1.0, score_raw))

            matches.append({
                "dim_table": hit.entity.get("table_name"),
                "dim_col": hit.entity.get("col_name"),
                "matched_text": hit.entity.get("col_value"),
                "score": score,
                # ⚠️ 不返回 key_col/key_value（Milvus 数据中无此字段）
            })

            if len(matches) >= top_k:
                break

        return matches

    def search_similar_sqls(
        self,
        embedding: List[float],
        top_k: int,
        similarity_threshold: float,
    ) -> List[Dict[str, Any]]:
        """检索历史相似 SQL。

        使用 sql_example_embeddings Collection，通过 db_name 过滤当前业务库。
        """
        collection = self._get_sql_example_collection()
        business_db_name = self._get_business_db_name()
        search_expr = f"db_name == {json.dumps(business_db_name)}" if business_db_name else None

        results = collection.search(
            data=[embedding],
            anns_field="embedding",
            param=self._get_search_params(),
            limit=top_k * 2,
            expr=search_expr,
            output_fields=["example_id", "question_sql", "domain"],
        )

        matches = []
        for hit in results[0]:
            similarity_raw = float(hit.distance)
            if similarity_raw < similarity_threshold:
                continue

            similarity = max(0.0, min(1.0, similarity_raw))
            question = ""
            sql_text = ""
            payload = hit.entity.get("question_sql", "")
            if payload:
                try:
                    parsed = json.loads(payload)
                    question = parsed.get("question", "") or ""
                    sql_text = parsed.get("sql", "") or ""
                except (TypeError, ValueError):
                    sql_text = str(payload)

            matches.append({
                "question": question,
                "sql": sql_text,
                "similarity": similarity,
                "example_id": hit.entity.get("example_id", ""),
                "domain": hit.entity.get("domain", ""),
            })

            if len(matches) >= top_k:
                break

        return matches

    def fetch_table_cards(
        self,
        table_names: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """获取表卡片（批量精确查询）。

        使用 Milvus 的精确查询（expr + JSON 序列化）。

        Note:
            - Milvus 使用 object_desc（而非 text_raw），返回时映射为 text_raw 保持接口一致
            - time_col_hint 只在 object_type='table' 时可能有值
            - grain_hint 字段 Milvus 中不存在，返回 None
        """
        if not table_names:
            return {}

        collection = self._get_table_schema_collection()

        # ⚠️ 使用 JSON 序列化避免单引号问题
        expr = f'object_type == "table" and table_name in {json.dumps(table_names)}'
        logger.debug(f"fetch_table_cards: collection={collection.name}, expr={expr!r}, table_names={table_names}")

        # ⚠️ 查询正确的字段名：object_desc（而非 text_raw）、time_col_hint
        results = collection.query(
            expr=expr,
            output_fields=["object_id", "table_name", "object_desc", "time_col_hint", "table_category"],
        )
        logger.debug(f"fetch_table_cards: 返回 {len(results)} 条记录")

        cards = {}
        for row in results:
            table_name = row.get("table_name")
            if table_name:
                # ⚠️ 将 object_desc 映射为 text_raw（保持与 PgVector 接口一致）
                cards[table_name] = {
                    "object_id": row.get("object_id"),
                    "text_raw": row.get("object_desc", ""),  # Milvus 字段名是 object_desc
                    "grain_hint": None,  # Milvus 无此字段
                    "time_col_hint": row.get("time_col_hint"),  # Milvus 有此字段（仅 table 类型可能有值）
                    "table_category": row.get("table_category", ""),
                }

        return cards

    def fetch_table_categories(
        self,
        table_names: List[str],
    ) -> Dict[str, str]:
        """批量查询表的 table_category 字段。

        使用 Milvus 的精确查询。
        """
        if not table_names:
            return {}

        collection = self._get_table_schema_collection()

        # ⚠️ 使用 JSON 序列化避免单引号问题
        expr = f'table_name in {json.dumps(table_names)} and object_type == "table"'
        logger.debug(f"fetch_table_categories: collection={collection.name}, expr={expr!r}, table_names={table_names}")

        results = collection.query(
            expr=expr,
            output_fields=["table_name", "table_category"],
        )
        logger.debug(f"fetch_table_categories: 返回 {len(results)} 条记录")

        categories = {}
        for row in results:
            object_id = row.get("table_name")
            category = row.get("table_category", "")
            if object_id and category:  # 只记录非空的类型
                categories[object_id] = category

        return categories
