"""问题解析节点 - 负责生成结构化 parse_result"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.services.llm_factory import extract_llm_content, extract_overrides, get_llm
from src.utils.logger import get_module_logger, with_query_id


def _truncate_dependency_value(value: Any, max_len: int = 120) -> str:
    """截断依赖结果中的长文本，避免解析提示词膨胀。"""
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _format_conversation_history(
    conversation_history: Optional[list[dict[str, str]]],
) -> str:
    if not conversation_history:
        return ""

    lines = ["Conversation history (old -> new, for reference only):"]
    for i, turn in enumerate(conversation_history, start=1):
        q = (turn.get("question") or "").strip()
        a = (turn.get("answer") or "").strip()
        if not q and not a:
            continue
        lines.append(f"{i}. Q: {q}")
        lines.append(f"   A: {a}")
    lines.append("")
    return "\n".join(lines)


def _format_dependencies_for_parsing(
    dependencies_results: Optional[Dict[str, Any]],
    *,
    max_rows: int = 3,
    max_cell_len: int = 120,
) -> str:
    """将依赖查询结果压缩为适合 question_parsing 的短文本。"""
    if not dependencies_results:
        return ""

    lines = ["Dependency results (use them to resolve references/placeholders):"]
    for dep_id, dep_data in dependencies_results.items():
        if not isinstance(dep_data, dict):
            continue

        question = (dep_data.get("question") or f"子查询 {dep_id}").strip()
        exec_result = dep_data.get("execution_result")

        lines.append(f"- {dep_id}")
        lines.append(f"  question: {_truncate_dependency_value(question, max_cell_len)}")

        if not isinstance(exec_result, dict):
            lines.append("  result: unavailable")
            continue

        columns = exec_result.get("columns") or []
        rows = exec_result.get("rows") or []

        if columns:
            formatted_columns = ", ".join(
                _truncate_dependency_value(col, max_cell_len) for col in columns
            )
            lines.append(f"  columns: [{formatted_columns}]")

        if not rows:
            lines.append("  result: empty")
            continue

        lines.append("  rows:")
        for row in rows[:max_rows]:
            if isinstance(row, (list, tuple)):
                row_text = ", ".join(
                    _truncate_dependency_value(cell, max_cell_len) for cell in row
                )
            else:
                row_text = _truncate_dependency_value(row, max_cell_len)
            lines.append(f"    - [{row_text}]")

        if len(rows) > max_rows:
            lines.append(f"  ... total_rows={len(rows)}, showing_first={max_rows}")

    lines.append("")
    return "\n".join(lines)


class QuestionParsingAgent:
    """封装 LLM 调用以生成 QueryParseResult"""

    def __init__(self, config: Dict[str, Any]):
        self._config = config

        llm_meta = get_llm(config["llm_profile"], **extract_overrides(config))
        self._llm = llm_meta.llm

    def parse_with_rewrite(
        self,
        query: str,
        *,
        current_date: Optional[str] = None,
        conversation_history: Optional[list[dict[str, str]]] = None,
        dependencies_results: Optional[Dict[str, Any]] = None,
        query_id: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        if not query:
            raise ValueError("问题内容为空，无法解析")

        if current_date is None:
            current_date = datetime.now().strftime("%Y-%m-%d")

        system_prompt = """You are a Chinese business intelligence analyst.

You will be given (optional) conversation history and the current user question.
Your job is to:
1) Rewrite the current question into a fully self-contained question in Chinese by resolving pronouns/ellipsis using the conversation history.
   - If the current question is already self-contained, the rewritten question MUST be identical to the original question (do not add new constraints).
2) Extract a structured intent object (QueryParseResult) from the rewritten question.

Follow these rules strictly:
1. IMPORTANT: Time field handling:
   - If the question does NOT explicitly mention any date/time constraint, the "time" field MUST be null.
   - Do NOT infer, guess, or create default time ranges when no date/time constraint is mentioned.
   - When a date/time constraint is present, fill:
     * time.start and/or time.end as raw strings: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS" (do NOT add missing parts).
     * time.grain_inferred as one of: year|quarter|month|week|day|hour (choose the SMALLEST grain implied by the question):
       - If exact clock time appears (e.g., "12:00", "12点"), choose hour.
       - If a day-of-month appears and no clock time (e.g., "2025-11-08", "11月8日"), choose day.
       - If only month-level wording appears (e.g., "September", "9月/9月份", "this month/本月/上月"), choose month.
       - If quarter wording appears (e.g., "Q1", "第一季度"), choose quarter.
       - If only year-level wording appears (e.g., "2025年", "今年", "上一年"), choose year.
     * time.is_full_period:
       - true ONLY if the question explicitly implies a full natural period for the inferred grain (e.g., "this month", "September", "this week", "Q1", "this year", "today/whole day").
       - false otherwise (including single-sided constraints like "since X" or "until Y", or explicit start/end that are not stated as a full period).
   - Week semantics MUST follow ISO-8601 (week starts on Monday). Do NOT compute or align calendar boundaries in this step.
   - Timezone context: Asia/Shanghai. Do NOT convert or normalize; just reflect the user's wording.
2. Always emit valid JSON that matches the QueryParseResult schema.
3. Classify each dimension as either a column name candidate (column) or a literal value (value).
4. Supported intent.task values: plain_agg, topn, rank, compare_yoy, compare_mom.
5. If the current question contains references such as “它/这个/这些/上述” or placeholders like {{sq1.result}}, use dependency results first to rewrite it into a self-contained question.
6. If dependency results include stronger identifiers such as ID/code together with names, prefer keeping ID/code in rewritten_query because they are more precise for downstream retrieval and SQL generation.
7. If a dependency result is empty, do not invent a fake entity. Preserve uncertainty in the rewritten question instead of hallucinating.
"""

        history_text = _format_conversation_history(conversation_history)
        dependencies_text = _format_dependencies_for_parsing(dependencies_results)
        user_prompt = (
            "Today's date is: {current_date} (Asia/Shanghai timezone)\n\n"
            "{history_text}\n"
            "{dependencies_text}"
            "Current question: {query}\n\n"
            "Output JSON schema (strict):\n{{\n"
            "  \"rewritten_query\": str,\n"
            "  \"parse_result\": {{\n"
            "    \"keywords\": [str],\n"
            "    \"time\": {{\n"
            "      \"start\": \"YYYY-MM-DD\" or \"YYYY-MM-DD HH:MM:SS\",\n"
            "      \"end\":   \"YYYY-MM-DD\" or \"YYYY-MM-DD HH:MM:SS\",\n"
            "      \"grain_inferred\": \"year|quarter|month|week|day|hour\",\n"
            "      \"is_full_period\": bool\n"
            "    }} | null,\n"
            "    \"metric\": {{\"text\": str, \"is_aggregate_candidate\": bool}},\n"
            "    \"dimensions\": [{{\"text\": str, \"role\": \"column|value\", \"evidence\": str}}],\n"
            "    \"intent\": {{\"task\": \"plain_agg|topn|rank|compare_yoy|compare_mom\", \"topn\": int|null}},\n"
            "    \"signals\": [str]\n"
            "  }}\n"
            "}}\n"
            "Notes:\n"
            "- rewritten_query MUST be a self-contained question in Chinese; if already self-contained, keep it identical.\n"
            "- If dependency results contain ID/code/name together, prefer ID/code in rewritten_query because they are stronger constraints.\n"
            "- If dependency results are empty, do not fabricate a concrete entity.\n"
            "- Populate time ONLY when explicitly mentioned; otherwise time MUST be null.\n"
            "- Return JSON only, without any extra explanations."
        ).format(
            current_date=current_date,
            query=query,
            history_text=history_text,
            dependencies_text=dependencies_text,
        )

        if query_id:
            qlog = with_query_id(get_module_logger("sql_subgraph"), query_id)
            qlog.debug("=" * 80)
            qlog.debug("完整 LLM 提示词（question_parsing）: [System]")
            qlog.debug("=" * 80)
            qlog.debug(system_prompt)
            qlog.debug("=" * 80)
            qlog.debug("完整 LLM 提示词（question_parsing）: [User]")
            qlog.debug("=" * 80)
            qlog.debug(user_prompt)
            qlog.debug("=" * 80)

        response = self._llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )

        raw_content = extract_llm_content(response)
        if not raw_content:
            raise ValueError("LLM 返回空响应")

        try:
            payload = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            snippet = raw_content[:200]
            raise ValueError(f"解析 LLM 响应失败: {exc}; snippet={snippet}") from exc

        rewritten_query = (payload.get("rewritten_query") or "").strip()
        parse_result = payload.get("parse_result")
        if not rewritten_query:
            rewritten_query = query
        if not isinstance(parse_result, dict):
            raise ValueError("LLM 输出不符合 schema：parse_result 不是对象")

        return rewritten_query, parse_result

    def parse(self, query: str, current_date: Optional[str] = None) -> Dict[str, Any]:
        _, parse_result = self.parse_with_rewrite(query, current_date=current_date)
        return parse_result

def question_parsing_node(state: SQLGenerationState) -> Dict[str, Any]:
    """子图中的问题解析节点"""

    query_id = state.get("query_id", "unknown")
    query = state.get("query")
    qlog = with_query_id(get_module_logger("sql_subgraph"), query_id)
    dependencies_results = state.get("dependencies_results") or {}

    # 1. 向后兼容：外部传入 parse_hints 时直接复用
    if state.get("parse_hints"):
        qlog.info("使用外部传入的 parse_hints")
        return {
            "parse_result": state["parse_hints"],
            "parsing_source": "external",
            "rewritten_query": query,
        }

    # 2. 加载配置，判断是否启用内部解析
    config = load_subgraph_config("sql_generation")
    parsing_config = (config.get("question_parsing") or {})

    if not parsing_config.get("enable_internal_parser", True):
        qlog.info("内部解析已禁用，返回空解析结果")
        return {
            "parse_result": {},
            "parsing_source": "disabled",
            "rewritten_query": query,
        }

    agent = QuestionParsingAgent(parsing_config)

    try:
        qlog.debug(f"question_parsing 收到 dependencies_results={len(dependencies_results)}")
        qlog.info("开始执行问题解析")
        rewritten_query, parse_result = agent.parse_with_rewrite(
            query=query,
            conversation_history=state.get("conversation_history"),
            dependencies_results=dependencies_results,
            query_id=query_id,
        )
        qlog.info("问题解析完成")
        qlog.debug(f"rewritten_query={rewritten_query}")
        
        # 详细记录解析结果
        qlog.debug("========== 问题解析结果 ==========")
        qlog.debug(json.dumps(parse_result, ensure_ascii=False, indent=2))
        qlog.debug("====================================")
        
        return {
            "parse_result": parse_result,
            "parsing_source": "llm",
            "rewritten_query": rewritten_query,
        }
    except Exception as exc:
        qlog.error(f"问题解析失败: {exc}", exc_info=True)
        if parsing_config.get("fallback_to_empty", True):
            qlog.warning("使用空解析结果作为回退")
            return {
                "parse_result": {},
                "parsing_source": "fallback",
                "parsing_error": str(exc),
                "rewritten_query": query,
            }
        return {
            "parse_result": None,
            "parsing_source": "llm",
            "error": f"问题解析失败: {exc}",
            "error_type": "parsing_failed",
            "failed_step": "question_parsing",
            "rewritten_query": query,
        }
