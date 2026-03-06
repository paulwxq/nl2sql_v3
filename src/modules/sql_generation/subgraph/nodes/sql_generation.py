"""SQL 生成节点 - 子图的第二个节点"""

from typing import Any, Dict, List, Optional

from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage
import time

from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.tools.schema_retrieval.join_planner import format_join_plan_for_prompt
from src.tools.schema_retrieval.value_matcher import (
    build_optimized_filters,
    format_dim_value_matches_for_prompt,
)
from src.utils.logger import get_module_logger, with_query_id

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

        # 维度过滤配置
        dim_filter_cfg = (config or {}).get("dimension_filter", {})
        self.dimension_filter_min_score = float(dim_filter_cfg.get("optimize_min_score", 0.5))

    def generate(
        self,
        query: str,
        schema_context: Dict[str, Any],
        similar_sqls: Optional[List[Dict[str, Any]]] = None,
        parse_result: Optional[Dict[str, Any]] = None,
        dependencies_results: Optional[Dict[str, Any]] = None,
        validation_errors: Optional[List[str]] = None,
        query_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        生成 SQL

        Args:
            query: 子查询文本
            schema_context: Schema 上下文
            parse_hints: 解析提示
            dependencies_results: 依赖查询结果
            validation_errors: 上一次的验证错误（重试时使用）
            query_id: 查询ID（用于日志上下文）

        Returns:
            生成的 SQL 字符串
        """
        # 读取重试配置（固定间隔，避免过度设计）
        retry_conf = (self.config or {}).get("llm_retry", {})
        max_attempts = int(retry_conf.get("max_attempts", 3))
        initial_delay_ms = int(retry_conf.get("initial_delay_ms", 500))

        qlog = with_query_id(logger, query_id or "")
        provider = "DashScope"
        model_name = self.config.get("llm_model", "qwen-plus")

        # 构建提示词
        prompt = self._build_prompt(
            query=query,
            schema_context=schema_context,
            similar_sqls=similar_sqls or [],
            parse_result=parse_result,
            dependencies_results=dependencies_results,
            validation_errors=validation_errors,
            conversation_history=conversation_history,
        )

        # 调用 LLM（带固定次数重试与空结果自检）
        last_error_text: Optional[str] = None
        for attempt in range(1, max_attempts + 1):
            # 准备消息
            messages = [
                SystemMessage(content="You are an expert PostgreSQL SQL writer. Return valid SQL only."),
                HumanMessage(content=prompt),
            ]

            try:
                logger.debug("调用 LLM 生成 SQL...")
                response = self.llm.invoke(messages)

                # DEBUG: 打印 LLM 原始响应
                logger.debug("=" * 80)
                logger.debug("LLM 原始响应:")
                logger.debug("=" * 80)
                logger.debug(response.content)
                logger.debug("=" * 80)

                # 清理 SQL（去除 markdown 标记）
                sql = (response.content or "").strip()
                sql = sql.replace("```sql", "").replace("```", "").strip()

                logger.debug(f"清理后的 SQL: {sql}")

                # 自检：空结果视为失败
                if not sql:
                    qlog.warning(
                        "LLM 返回空结果（provider=%s, model=%s, attempt=%d/%d）",
                        provider,
                        model_name,
                        attempt,
                        max_attempts,
                    )
                    last_error_text = "empty_result"
                else:
                    return sql

            except Exception as e:
                # 最小实现：将常见连接/超时错误统一记录为 WARNING
                last_error_text = str(e)
                qlog.warning(
                    "LLM 服务连接失败（provider=%s, model=%s, attempt=%d/%d）：%s",
                    provider,
                    model_name,
                    attempt,
                    max_attempts,
                    last_error_text,
                )

            # 尝试间隔（固定间隔）
            if attempt < max_attempts:
                time.sleep(max(0, initial_delay_ms) / 1000.0)

        # 达到最大次数仍失败
        raise RuntimeError(
            f"LLM 服务不可用（provider={provider}, model={model_name}, attempts={max_attempts}, last_error={last_error_text}）"
        )

    def _build_prompt(
        self,
        query: str,
        schema_context: Dict[str, Any],
        similar_sqls: List[Dict[str, Any]],
        parse_result: Optional[Dict[str, Any]],
        dependencies_results: Optional[Dict[str, Any]],
        validation_errors: Optional[List[str]],
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> str:
        """构建 SQL 生成提示词"""

        # 提取解析提示
        time_info = self._format_time_hints(parse_result)
        dimension_filters = self._format_dimension_filters(parse_result, schema_context)
        metric_info = self._format_metric_hints(parse_result)

        # 格式化 Schema 上下文
        table_categories_text = self._format_table_categories(schema_context)  # 表类型分组
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

        history_text = self._format_conversation_history(conversation_history)
        history_block = ""
        if history_text:
            history_block = f"""

---

{history_text}

---
"""

        # 组装完整提示词
        prompt = f"""
你是 PostgreSQL SQL 生成专家。根据以下上下文生成 SQL。

要求：
1.仅输出 SQL，不附加说明；不要输出 markdown 代码块（```sql）；SQL 末尾不需要分号。
2.所有表必须包含 schema 前缀（例如 public.table）。
3.日期时间过滤使用指定列：同时具备 start 与 end 时使用 >= start AND < end；仅有 start 时使用 >= start；仅有 end 时使用 < end。
4.JOIN 条件必须严格按照 ON 模板，用实际别名替换 SRC/DST。
5.只允许使用“表结构”中列出的字段，禁止使用任何未列出的字段或推断字段。
6.下方列出的表仅为“可能参与查询”的候选集合：请根据问题与维度/指标需求，自主选择最合适的表与字段组合；若某表或字段不需要，可以忽略，不必强行引用。
7.当“对话历史”与“当前问题/依赖结果”矛盾时，以“当前问题/依赖结果”为准，不要被历史带偏。
8.如果下方“维度值匹配”给出了明确的主键等值条件（例如 dim_table.key_col='key_value'），优先使用它；不要凭空猜测主键列名或主键值。
9.性能建议：避免在 WHERE 中对列做函数运算（例如 DATE(time_col)），优先使用等值条件或可走索引的条件。

---

方言：postgresql
问题：{query}
{time_info}
{dimension_filters}
{metric_info}{dependencies_text}{errors_text}
{history_block}

---

表类型：
{table_categories_text}

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

维度值匹配（用于 WHERE 条件；仅在有匹配时使用）：
{dim_values_text}

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
        
        # DEBUG: 打印完整提示词（统一由日志级别控制是否可见）
        logger.debug("=" * 80)
        logger.debug("完整 LLM 提示词:")
        logger.debug("=" * 80)
        logger.debug(final_prompt)
        logger.debug("=" * 80)
        
        return final_prompt

    @staticmethod
    def _format_conversation_history(
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> str:
        if not conversation_history:
            return ""

        lines: List[str] = ["对话历史（旧→新，仅供指代消解，不可覆盖当前问题/依赖结果）："]
        for i, turn in enumerate(conversation_history, start=1):
            q = (turn.get("question") or "").strip()
            a = (turn.get("answer") or "").strip()
            if not q and not a:
                continue
            lines.append(f"{i}. Q: {q}")
            lines.append(f"   A: {a}")
        return "\n".join(lines)

    def _format_time_hints(self, parse_result: Optional[Dict[str, Any]]) -> str:
        """格式化时间提示"""
        if not parse_result or "time" not in parse_result:
            return ""

        time_window = parse_result["time"]
        # 如果 time 是 null，直接返回空
        if not time_window:
            return ""
            
        start = time_window.get("start", "")
        end = time_window.get("end", "")
        grain = time_window.get("grain_inferred", "")

        lines: List[str] = []

        # 统一输出“日期时间粒度”行（若可用）
        if grain:
            lines.append(f"日期时间粒度：{grain}")

        # 根据 start/end 的存在性拼接条件（仅输出“日期时间条件”，不再输出“日期时间窗口”）
        if start and end:
            # 区间：半开区间
            lines.append(f"日期时间条件：>= {start} AND < {end}")
        elif start:
            # 仅下界
            lines.append(f"日期时间条件：>= {start}")
        elif end:
            # 仅上界
            lines.append(f"日期时间条件：< {end}")

        return "\n".join(lines)

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
            optimize_min_score=self.dimension_filter_min_score,
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

    def _format_table_categories(self, schema_context: Dict[str, Any]) -> str:
        """
        格式化表类型分组

        根据 table_categories 按原始类型分组显示表

        Args:
            schema_context: Schema上下文，包含 table_categories 字典

        Returns:
            格式化后的表类型字符串，例如：
            - 交易表: table1, table2
            - 维度表: table3
            - 桥接表: table4
        """
        table_categories = schema_context.get("table_categories", {})
        if not table_categories:
            return "（无分类信息）"

        # 按类型分组
        category_groups: Dict[str, List[str]] = {}
        for table_id, category in table_categories.items():
            if category not in category_groups:
                category_groups[category] = []
            category_groups[category].append(table_id)

        # 格式化输出
        lines = []
        for category in sorted(category_groups.keys()):
            tables = category_groups[category]
            tables_str = ", ".join(sorted(tables))
            lines.append(f"  - {category}: {tables_str}")

        return "\n".join(lines) if lines else "（无分类信息）"

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

        # 从配置读取展示数量
        max_display = self.config.get("prompt", {}).get("max_similar_sqls", 2)
        
        lines = []
        for idx, hit in enumerate(similar_sqls[:max_display], 1):
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
        """格式化依赖结果
        
        Args:
            dependencies: 依赖结果字典，格式：
                {
                    "query_id": {
                        "question": "...",
                        "execution_result": {...}
                    }
                }
        
        Returns:
            格式化后的依赖信息字符串
        """
        if not dependencies:
            return ""
        
        max_rows = self.config.get("dependencies_formatting", {}).get("max_display_rows", 5)
        include_columns = self.config.get("dependencies_formatting", {}).get("include_columns", True)
        
        deps = []
        for query_id, dep_data in dependencies.items():
            # 处理旧格式或空数据
            if not dep_data or not isinstance(dep_data, dict):
                continue
                
            # 提取关键信息
            question = dep_data.get("question", f"子查询 {query_id}")
            exec_result = dep_data.get("execution_result")
            
            # 如果没有 execution_result，跳过
            if not exec_result or not isinstance(exec_result, dict):
                continue
            
            rows = exec_result.get("rows", [])
            columns = exec_result.get("columns", [])
            
            # 构建格式化输出
            deps.append(f"  - {query_id}:")
            deps.append(f"    question: {question}")
            
            if rows:
                deps.append(f"    result:")
                display_rows = rows[:max_rows]
                for row in display_rows:
                    deps.append(f"      - {row}")
                
                if len(rows) > max_rows:
                    deps.append(f"    ... 共 {len(rows)} 行，仅显示前 {max_rows} 行")
            
            if include_columns and columns:
                deps.append(f"    columns: {columns}")
        
        return "\n\n可能依赖的查询结果：\n" + "\n".join(deps)

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
            "failed_step": "sql_generation",
        }

    # 直接从 schema_context 读取历史 SQL（已在 schema_retrieval 阶段完成）
    similar_sqls = schema_context.get("similar_sqls", [])
    qlog = with_query_id(logger, state.get("query_id", ""))
    qlog.info(f"使用 {len(similar_sqls)} 个历史 SQL 案例")

    try:
        # 生成 SQL
        effective_query = state.get("rewritten_query") or state["query"]
        generated_sql = agent.generate(
            query=effective_query,
            schema_context=schema_context,
            similar_sqls=similar_sqls,
            parse_result=state.get("parse_result") or state.get("parse_hints"),
            dependencies_results=state.get("dependencies_results"),
            validation_errors=validation_errors,
            query_id=state.get("query_id"),
            conversation_history=state.get("conversation_history"),
        )

        qlog.info(f"SQL生成完成（第 {state.get('iteration_count', 0) + 1} 次）")

        return {
            "generated_sql": generated_sql,
            "iteration_count": state.get("iteration_count", 0) + 1,
            # 成功即清理上一轮的错误字段，保证状态一致
            "error": None,
            "error_type": None,
            "failed_step": None,
        }

    except Exception as e:
        qlog.error(f"SQL生成失败: {e}")

        return {
            "generated_sql": None,
            "error": f"SQL生成失败: {str(e)}",
            "error_type": "generation_failed",
            "failed_step": "sql_generation",
        }
