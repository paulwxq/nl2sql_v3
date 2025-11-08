"""问题解析节点 - 负责生成结构化 parse_result"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage

from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.utils.logger import get_module_logger, with_query_id


class QuestionParsingAgent:
    """封装 LLM 调用以生成 QueryParseResult"""

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._llm = ChatTongyi(
            model=config.get("parser_model", "qwen-plus"),
            dashscope_api_key=config.get("api_key"),
            temperature=config.get("temperature", 0),
            max_tokens=config.get("max_tokens", 1500),
            timeout=config.get("timeout", 20),
        )

    def parse(self, query: str, current_date: Optional[str] = None) -> Dict[str, Any]:
        if not query:
            raise ValueError("问题内容为空，无法解析")

        if current_date is None:
            current_date = datetime.now().strftime("%Y-%m-%d")

        system_prompt = """You are a Chinese business intelligence analyst who extracts structured intents from natural language questions.
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
"""

        user_prompt = (
            "Today's date is: {current_date} (Asia/Shanghai timezone)\n\n"
            "Please analyze the question below and return a strict JSON output.\n"
            "Question: {query}\n\n"
            "JSON schema:\n{{\n"
            "  \"keywords\": [str],\n"
            "  \"time\": {{\n"
            "    \"start\": \"YYYY-MM-DD\" or \"YYYY-MM-DD HH:MM:SS\",\n"
            "    \"end\":   \"YYYY-MM-DD\" or \"YYYY-MM-DD HH:MM:SS\",\n"
            "    \"grain_inferred\": \"year|quarter|month|week|day|hour\",\n"
            "    \"is_full_period\": bool\n"
            "  }} | null,\n"
            "  \"metric\": {{\"text\": str, \"is_aggregate_candidate\": bool}},\n"
            "  \"dimensions\": [{{\"text\": str, \"role\": \"column|value\", \"evidence\": str}}],\n"
            "  \"intent\": {{\"task\": \"plain_agg|topn|rank|compare_yoy|compare_mom\", \"topn\": int|null}},\n"
            "  \"signals\": [str]\n"
            "}}\n"
            "Notes:\n"
            "- Populate \"time\" ONLY when the question explicitly mentions a date/time constraint; otherwise \"time\" MUST be null.\n"
            "- Choose grain_inferred as the SMALLEST grain implied by the wording (e.g., time-of-day → hour; date with no time → day; month wording → month; quarter wording → quarter; year wording → year).\n"
            "- Set is_full_period=true ONLY for explicit full-period phrases (e.g., \"this month\", \"September\", \"this week\", \"Q1\", \"this year\", \"today/whole day\"); otherwise false.\n"
            "- Single-sided constraints: \"since X\" → only time.start (is_full_period=false); \"until Y\" → only time.end (is_full_period=false).\n"
            "- Week semantics follow ISO-8601 (week starts on Monday). Do NOT compute calendar boundaries here.\n"
            "- Timezone context: Asia/Shanghai. Do NOT convert or normalize; do NOT add missing parts.\n"
            "Output requirement: Return JSON only, without any extra explanations."
        ).format(current_date=current_date, query=query)

        response = self._llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )

        raw_content = (response.content or "").strip()
        if not raw_content:
            raise ValueError("LLM 返回空响应")

        try:
            return json.loads(raw_content)
        except json.JSONDecodeError as exc:
            snippet = raw_content[:200]
            raise ValueError(f"解析 LLM 响应失败: {exc}; snippet={snippet}") from exc


def question_parsing_node(state: SQLGenerationState) -> Dict[str, Any]:
    """子图中的问题解析节点"""

    query_id = state.get("query_id", "unknown")
    query = state.get("query")
    qlog = with_query_id(get_module_logger("sql_subgraph"), query_id)

    # 1. 向后兼容：外部传入 parse_hints 时直接复用
    if state.get("parse_hints"):
        qlog.info("使用外部传入的 parse_hints")
        return {
            "parse_result": state["parse_hints"],
            "parsing_source": "external",
        }

    # 2. 加载配置，判断是否启用内部解析
    config = load_subgraph_config("sql_generation")
    parsing_config = (config.get("question_parsing") or {})

    if not parsing_config.get("enable_internal_parser", True):
        qlog.info("内部解析已禁用，返回空解析结果")
        return {
            "parse_result": {},
            "parsing_source": "disabled",
        }

    agent = QuestionParsingAgent(parsing_config)

    try:
        qlog.info("开始执行问题解析")
        parse_result = agent.parse(query=query)
        qlog.info("问题解析完成")
        
        # 详细记录解析结果
        import json
        qlog.debug("========== 问题解析结果 ==========")
        qlog.debug(json.dumps(parse_result, ensure_ascii=False, indent=2))
        qlog.debug("====================================")
        
        return {
            "parse_result": parse_result,
            "parsing_source": "llm",
        }
    except Exception as exc:
        qlog.error(f"问题解析失败: {exc}", exc_info=True)
        if parsing_config.get("fallback_to_empty", True):
            qlog.warning("使用空解析结果作为回退")
            return {
                "parse_result": {},
                "parsing_source": "fallback",
                "parsing_error": str(exc),
            }
        return {
            "parse_result": None,
            "parsing_source": "llm",
            "error": f"问题解析失败: {exc}",
            "error_type": "parsing_failed",
        }
