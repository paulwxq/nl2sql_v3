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
   - If the question does NOT explicitly mention any time constraint, the time field MUST be null.
   - Do NOT infer, guess, or create default time ranges when no time is mentioned.
2. Always emit valid JSON that matches the QueryParseResult schema.
3. Classify each dimension as either a column name candidate (column) or a literal value (value).
4. Supported intent.task values: plain_agg, topn, rank, compare_yoy, compare_mom.
"""

        user_prompt = (
            "今天的日期是: {current_date} (Asia/Shanghai 时区)\n\n"
            "请分析下述问题, 给出严格 JSON 输出。\n"
            "问题: {query}\n\n"
            "JSON schema:\n{{\n"
            "  \"keywords\": [str],\n"
            "  \"time\": {{\"start\": \"YYYY-MM-DD\", \"end\": \"YYYY-MM-DD\", \"grain_inferred\": str, \"is_full_period\": bool}} | null,\n"
            "  \"metric\": {{\"text\": str, \"is_aggregate_candidate\": bool}},\n"
            "  \"dimensions\": [{{\"text\": str, \"role\": \"column|value\", \"evidence\": str}}],\n"
            "  \"intent\": {{\"task\": \"plain_agg|topn|rank|compare_yoy|compare_mom\", \"topn\": int|null}},\n"
            "  \"signals\": [str]\n"
            "}}\n"
            "注意: time 字段仅在问题中明确提及时间约束时才填充, 否则必须为 null。\n"
            "输出要求: 仅输出 JSON, 不要额外说明。"
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
