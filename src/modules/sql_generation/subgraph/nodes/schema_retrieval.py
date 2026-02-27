"""Schema 检索节点 - 子图的第一个节点"""

from typing import Dict, Any

from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.tools.schema_retrieval.retriever import SchemaRetriever
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("schema_retrieval")


def schema_retrieval_node(state: SQLGenerationState) -> Dict[str, Any]:
    """
    Schema 检索节点

    从 state 获取查询信息，调用 SchemaRetriever 检索相关的 Schema 上下文，
    并将结果写回 state

    Args:
        state: 当前 state

    Returns:
        更新的 state 字典（只包含更新的字段）
    """
    # 加载子图配置
    config = load_subgraph_config("sql_generation")

    # 初始化 Schema 检索器
    retriever = SchemaRetriever(config)

    # 执行检索
    try:
        effective_query = state.get("rewritten_query") or state["query"]
        schema_context = retriever.retrieve(
            query=effective_query,
            parse_result=state.get("parse_result"),
            parse_hints=state.get("parse_hints"),
            query_id=state.get("query_id"),
        )

        # 记录检索统计
        stats = retriever.get_retrieval_stats(schema_context)
        qlog = with_query_id(logger, state.get("query_id", ""))
        qlog.info(
            f"Schema检索完成: {stats['table_count']}表, {stats['column_count']}列, {stats['join_plan_count']}个JOIN计划, 耗时{stats['retrieval_time']:.2f}秒"
        )
        
        # 详细记录检索结果
        query_id = state['query_id']
        metadata = schema_context.get("metadata", {})
        logger.debug("========== Schema检索详情 ==========")
        logger.debug(f"候选事实表: {metadata.get('candidate_fact_tables', [])}")
        logger.debug(f"候选维度表: {metadata.get('candidate_dim_tables', [])}")
        logger.debug(f"维度值匹配: {len(schema_context.get('dim_value_hits', []))} 个")
        if schema_context.get('dim_value_hits'):
            for hit in schema_context['dim_value_hits'][:3]:  # 只显示前3个
                logger.debug(f"  - {hit.get('query_value')} → {hit.get('matched_text')} (score: {hit.get('score', 0):.2f})")
        logger.debug("========================================")

        return {
            "schema_context": schema_context,
        }

    except Exception as e:
        qlog = with_query_id(logger, state.get("query_id", ""))
        qlog.error(f"Schema检索失败: {e}", exc_info=True)

        # 返回错误状态
        return {
            "schema_context": None,
            "error": f"Schema检索失败: {str(e)}",
            "error_type": "schema_retrieval_failed",
        }
