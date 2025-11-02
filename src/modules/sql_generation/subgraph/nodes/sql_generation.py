"""SQL 生成节点 - 子图的第二个节点"""

from typing import Any, Dict, List, Optional

from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage

from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.services.db.pg_client import get_pg_client
from src.tools.schema_retrieval.join_planner import format_join_plan_for_prompt
from src.tools.schema_retrieval.value_matcher import (
    build_optimized_filters,
    format_dim_value_matches_for_prompt,
)
from src.utils.logger import get_module_logger

logger = get_module_logger("sql_generation")


class SQLGenerationAgent:
    """SQL 生成 Agent"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 Agent

        Args:
            config: SQL 生成配置
        """
        self.config = config

        # 初始化 LLM
        self.llm = ChatTongyi(
            model=config.get("llm_model", "qwen-plus"),
            dashscope_api_key=config.get("api_key"),
            temperature=config.get("temperature", 0),
            max_tokens=config.get("max_tokens", 2000),
        )

    def generate(
        self,
        query: str,
        schema_context: Dict[str, Any],
        similar_sqls: Optional[List[Dict[str, Any]]] = None,
        parse_result: Optional[Dict[str, Any]] = None,
        dependencies_results: Optional[Dict[str, Any]] = None,
        validation_errors: Optional[List[str]] = None,
    ) -> str:
        """
        生成 SQL

        Args:
            query: 子查询文本
            schema_context: Schema 上下文
            parse_hints: 解析提示
            dependencies_results: 依赖查询结果
            validation_errors: 上一次的验证错误（重试时使用）

        Returns:
            生成的 SQL 字符串
        """
        # 构建提示词
        prompt = self._build_prompt(
            query=query,
            schema_context=schema_context,
            similar_sqls=similar_sqls or [],
            parse_result=parse_result,
            dependencies_results=dependencies_results,
            validation_errors=validation_errors,
        )

        # 调用 LLM
        messages = [
            SystemMessage(content="You are an expert PostgreSQL SQL writer. Return valid SQL only."),
            HumanMessage(content=prompt),
        ]

        logger.debug("调用 LLM 生成 SQL...")
        response = self.llm.invoke(messages)
        
        # DEBUG: 打印 LLM 原始响应
        logger.debug("=" * 80)
        logger.debug("LLM 原始响应:")
        logger.debug("=" * 80)
        logger.debug(response.content)
        logger.debug("=" * 80)

        # 清理 SQL（去除 markdown 标记）
        sql = response.content.strip()
        sql = sql.replace("```sql", "").replace("```", "").strip()
        
        logger.debug(f"清理后的 SQL: {sql}")

        return sql

    def _build_prompt(
        self,
        query: str,
        schema_context: Dict[str, Any],
        similar_sqls: List[Dict[str, Any]],
        parse_result: Optional[Dict[str, Any]],
        dependencies_results: Optional[Dict[str, Any]],
        validation_errors: Optional[List[str]],
    ) -> str:
        """构建 SQL 生成提示词"""

        # 提取解析提示
        time_info = self._format_time_hints(parse_result)
        dimension_filters = self._format_dimension_filters(parse_result, schema_context)
        metric_info = self._format_metric_hints(parse_result)

        # 格式化 Schema 上下文
        table_cards_text = self._format_table_cards(schema_context.get("table_cards", {}))
        join_plans_text = format_join_plan_for_prompt(schema_context.get("join_plans", []))
        time_columns_text = self._format_time_columns(schema_context.get("table_cards", {}))
        dim_value_hits = schema_context.get("dim_value_hits", [])
        dim_values_text = format_dim_value_matches_for_prompt(dim_value_hits)

        # 格式化依赖结果
        dependencies_text = self._format_dependencies(dependencies_results)

        # 历史 SQL 上下文（来自独立参数）
        similar_sqls_text = self._format_similar_sqls(similar_sqls)

        # 格式化验证错误（重试时）
        errors_text = self._format_errors(validation_errors)

        # 组装完整提示词
        prompt = f"""
你是 PostgreSQL SQL 生成专家。根据以下上下文生成 SQL。

要求：
1. 仅输出 SQL，不附加说明。
2. 所有表必须包含 schema 前缀（例如 public.table）。
3. 时间过滤使用指定列，并遵循 >= start AND < end 的半开区间。
4. JOIN 条件必须严格按照 ON 模板，用实际别名替换 SRC/DST。
5. 以下提供的表结构、JOIN 计划和时间列为参考，你可以选择性使用它们，但不得使用未列出的字段。

---

方言：postgresql
问题：{query}
{time_info}
{dimension_filters}
{metric_info}{dependencies_text}{errors_text}

---

表结构：
{table_cards_text}

---

JOIN 计划：
{join_plans_text}

---

时间列：
{time_columns_text}

---
"""

        # 仅在有相似案例时添加历史 SQL 部分
        if similar_sqls:
            prompt += f"""
历史成功SQL案例（参考）：
{similar_sqls_text}

---
"""

        final_prompt = prompt.strip()
        
        # DEBUG: 打印完整提示词
        logger.debug("=" * 80)
        logger.debug("完整 LLM 提示词:")
        logger.debug("=" * 80)
        logger.debug(final_prompt)
        logger.debug("=" * 80)
        
        return final_prompt

    def _format_time_hints(self, parse_result: Optional[Dict[str, Any]]) -> str:
        """格式化时间提示"""
        if not parse_result or "time" not in parse_result:
            return ""

        time_window = parse_result["time"]
        start = time_window.get("start", "")
        end = time_window.get("end", "")

        if start and end:
            return f"时间窗口：{start} ~ {end}"
        return ""

    def _format_dimension_filters(
        self,
        parse_result: Optional[Dict[str, Any]],
        schema_context: Dict[str, Any],
    ) -> str:
        """格式化维度过滤条件"""
        if not parse_result or "dimensions" not in parse_result:
            return ""

        filters = build_optimized_filters(
            parse_hints=parse_result,
            dim_matches=schema_context.get("dim_value_hits", []),
            optimize_min_score=0.5,
        )

        if filters:
            return f"维度过滤：{', '.join(filters)}"
        return ""

    def _format_metric_hints(self, parse_result: Optional[Dict[str, Any]]) -> str:
        """格式化指标提示"""
        if not parse_result or "metric" not in parse_result:
            return ""

        metric = parse_result["metric"]
        return f"指标：{metric.get('text', '')}"

    def _format_table_cards(self, table_cards: Dict[str, Dict]) -> str:
        """格式化表卡片"""
        lines = []
        for table_id, card in table_cards.items():
            text_raw = card.get("text_raw", "").replace("\n", " ").strip()
            lines.append(f"- **{table_id}**  {text_raw}")
        return "\n".join(lines) if lines else "（无）"

    def _format_time_columns(self, table_cards: Dict[str, Dict]) -> str:
        """格式化时间列"""
        lines = []
        for table_id, card in table_cards.items():
            time_col = card.get("time_col_hint")
            if time_col:
                lines.append(f"- {table_id}.{time_col}")
        return "\n".join(lines) if lines else "（无明确时间列）"

    def _format_similar_sqls(self, similar_sqls: List[Dict]) -> str:
        """格式化历史 SQL 相似案例"""
        if not similar_sqls:
            return "（无相似案例）"

        lines = []
        for idx, hit in enumerate(similar_sqls[:2], 1):  # 最多显示 2 个
            sim = hit.get("similarity", 0.0)
            question = hit.get("question", "")
            sql_text = hit.get("sql", "")

            header = f"{idx}. 相似度：{sim:.2f}"
            lines.append(header)
            if question:
                lines.append(f"   查询：{question}")
            if sql_text:
                lines.append(f"   SQL：{sql_text}")

        return "\n".join(lines)

    def _format_dependencies(self, dependencies: Optional[Dict[str, Any]]) -> str:
        """格式化依赖结果"""
        if not dependencies:
            return ""

        deps = []
        for query_id, result in dependencies.items():
            deps.append(f"- {query_id}: {result}")

        return "\n\n依赖查询结果：\n" + "\n".join(deps)

    def _format_errors(self, errors: Optional[List[str]]) -> str:
        """格式化验证错误"""
        if not errors:
            return ""

        return (
            f"\n\n⚠️ 上一次生成的SQL验证失败，请修正以下错误：\n"
            + "\n".join(f"- {err}" for err in errors)
        )


def sql_generation_node(state: SQLGenerationState) -> Dict[str, Any]:
    """
    SQL 生成节点

    从 state 获取 Schema 上下文，调用 LLM 生成 SQL

    Args:
        state: 当前 state

    Returns:
        更新的 state 字典
    """
    # 加载配置
    config = load_subgraph_config("sql_generation")
    gen_config = config.get("sql_generation", {})

    # 初始化 Agent
    agent = SQLGenerationAgent(gen_config)

    # 获取上一次的验证错误（如果有）
    validation_errors = None
    if state.get("validation_result"):
        if not state["validation_result"].get("valid"):
            validation_errors = state["validation_result"].get("errors", [])

    schema_context = state.get("schema_context")
    if not schema_context:
        return {
            "generated_sql": None,
            "error": "Schema检索结果为空，无法生成SQL",
            "error_type": "generation_failed",
        }

    # 检索历史 SQL（复用查询向量）
    similar_sqls: List[Dict[str, Any]] = []
    query_embedding = state.get("query_embedding")
    if query_embedding:
        pg_client = get_pg_client()
        prompt_config = gen_config.get("prompt", {})
        top_k = prompt_config.get("max_similar_sqls", 2)
        similarity_threshold = gen_config.get("sql_similarity_threshold", 0.6)
        similar_sqls = pg_client.search_similar_sqls(
            embedding=query_embedding,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
        print(f"[{state['query_id']}] 检索到 {len(similar_sqls)} 个相似SQL案例")
    else:
        print(f"[{state['query_id']}] ⚠️ 缺少 query_embedding，跳过历史 SQL 检索")

    try:
        # 生成 SQL
        generated_sql = agent.generate(
            query=state["query"],
            schema_context=schema_context,
            similar_sqls=similar_sqls,
            parse_result=state.get("parse_result") or state.get("parse_hints"),
            dependencies_results=state.get("dependencies_results"),
            validation_errors=validation_errors,
        )

        print(f"[{state['query_id']}] SQL生成完成（第 {state.get('iteration_count', 0) + 1} 次）")

        return {
            "generated_sql": generated_sql,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    except Exception as e:
        print(f"[{state['query_id']}] ❌ SQL生成失败: {e}")

        return {
            "generated_sql": None,
            "error": f"SQL生成失败: {str(e)}",
            "error_type": "generation_failed",
        }
