"""Summarizer 节点：响应构建器（自适应，两路共享）

Summarizer 负责将内部状态转换为用户友好的最终响应：
- 成功时：根据执行结果生成自然语言总结
- 失败时：将技术错误转换为用户可理解的提示
- 支持单/多SQL结果的总结（Phase 1: 单SQL，Phase 2: 多SQL）
"""

from typing import Any, Dict, List

from src.modules.nl2sql_father.state import NL2SQLFatherState
from src.services.config_loader import load_config
from src.services.llm_factory import extract_overrides, get_llm
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("summarizer")

# 配置缓存（模块级别加载一次）
_summarizer_config_cache = None


def _get_summarizer_config() -> Dict[str, Any]:
    """获取 Summarizer 配置（带缓存）

    Returns:
        Summarizer 配置字典
    """
    global _summarizer_config_cache
    if _summarizer_config_cache is None:
        # load_config 接收相对于项目根目录的路径
        config_path = "src/modules/nl2sql_father/config/nl2sql_father_graph.yaml"
        full_config = load_config(config_path)
        _summarizer_config_cache = full_config["summarizer"]
    return _summarizer_config_cache


def summarizer_node(state: NL2SQLFatherState) -> Dict[str, Any]:
    """Summarizer 节点（响应构建器，两路复用）

    职责：
    1. 将内部状态转换为用户友好的最终响应
    2. 成功时：根据执行结果生成自然语言总结
    3. 失败时：将技术错误转换为用户可理解的提示
    4. 支持单/多SQL结果的总结（自适应）
    5. 处理暂不支持的场景（如 Phase 1 的 complex 问题）

    处理4个场景：
    - 场景0：complex 问题暂不支持（Phase 1）
    - 场景1：SQL生成失败（技术错误转换）
    - 场景2：SQL执行失败
    - 场景3：SQL执行成功（生成自然语言总结）

    Args:
        state: 父图 State

    Returns:
        更新的 State 字段：
        - summary: 自然语言总结
    """
    user_query = state["user_query"]
    query_id = state.get("query_id", "unknown")
    complexity = state.get("complexity")
    execution_results = state.get("execution_results", [])
    error = state.get("error")
    error_type = state.get("error_type")

    # 日志
    query_logger = with_query_id(logger, query_id)
    query_logger.info("Summarizer 开始生成响应")

    # 加载配置
    config = _get_summarizer_config()
    max_rows_in_prompt = config["max_rows_in_prompt"]
    use_template = config["use_template"]
    history_block = _format_conversation_history(state.get("conversation_history"))

    # ========== 场景1：SQL生成失败（从子图直接跳转过来，跳过了SQL执行） ==========
    if not execution_results and error:
        query_logger.info(f"场景1：SQL生成失败，error_type={error_type}")
        summary = _build_error_summary(error, error_type, user_query)
        return {"summary": summary}

    # ========== 场景2：SQL执行失败或无结果 ==========
    if not execution_results:
        # 尝试从 sub_queries 提取失败信息（Complex Path 增强）
        failed_sqs = [sq for sq in state.get("sub_queries", []) if sq.get("status") == "failed"]
        if failed_sqs:
            lines = []
            for sq in failed_sqs:
                step = sq.get("failed_step", "未知阶段")
                err = sq.get("error", "未知错误")
                lines.append(f"子查询在{step}阶段失败：{err}")
            summary = "抱歉，查询未能完成。\n" + "\n".join(lines)
            query_logger.warning(f"场景2：子查询失败，失败数={len(failed_sqs)}")
        else:
            summary = "抱歉，系统未能生成有效的SQL查询。"
            query_logger.warning("场景2：无执行结果")
        return {"summary": summary}

    # 检查执行是否成功
    success_results = [r for r in execution_results if r.get("success")]
    failed_results = [r for r in execution_results if not r.get("success")]

    if not success_results:
        # 所有SQL都执行失败
        query_logger.error(f"场景2：所有SQL执行失败，失败数={len(failed_results)}")
        error_summary = "\n".join([r.get("error", "未知错误") for r in failed_results])
        return {
            "summary": f"抱歉，SQL执行失败。错误信息：\n{error_summary}",
        }

    # ========== 场景3：SQL执行成功，生成自然语言总结 ==========
    query_logger.info(f"场景3：SQL执行成功，成功数={len(success_results)}")

    # 自适应处理：根据结果数量自动选择处理方式
    # - Phase 1 (Fast Path): 只有1条SQL结果，直接总结
    # - Phase 2 (Complex Path): 可能有多条SQL结果，需要综合总结

    if len(success_results) == 1:
        # 单SQL结果处理（Phase 1）
        result = success_results[0]
        rows = result.get("rows", [])
        columns = result.get("columns", [])

        # 格式化结果为表格形式（使用配置的最大行数）
        result_table = _format_table(columns, rows[:max_rows_in_prompt])
        context_info = f"查询结果（共{len(rows)}行）：\n{result_table}"
    else:
        # ⚠️ 注意：这个分支在 Phase 1 不会被执行
        # 原因：Phase 1 只处理 Simple 问题，最多只有 1 条 SQL
        # Phase 2 扩展：Complex 问题可能有多条 SQL 结果
        query_logger.info(f"多SQL结果处理（Phase 2），结果数={len(success_results)}")
        context_info = _format_multi_results(success_results, state.get("sub_queries", []), max_rows_in_prompt)

    # 生成总结
    if use_template:
        # 使用模板（不调用LLM）
        result_count = sum(len(r.get("rows", [])) for r in success_results)
        if result_count == 0:
            summary = "查询成功，但未找到相关数据。"
        elif result_count == 1:
            summary = "查询成功，找到1条记录。"
        else:
            summary = f"查询成功，共找到{result_count}条记录。"
    else:
        # 调用LLM生成自然语言总结（自适应提示词）
        if len(success_results) == 1:
            # 单SQL结果提示词
            prompt = f"""你是一个数据分析助手。用户提出了一个问题，系统执行了SQL查询并获得了结果。请用自然语言总结结果。

{history_block}

规则：当“对话历史”与“当前问题/本次查询结果”矛盾时，以“当前问题/本次查询结果”为准，不要被历史带偏。

用户问题：{user_query}

{context_info}

请用1-2句话总结结果，直接回答用户的问题。如果结果为空，请说明"未找到相关数据"。"""
        else:
            # 多SQL结果提示词（Phase 2）
            prompt = f"""你是一个数据分析助手。用户提出了一个问题，系统分步执行了多个SQL查询并获得了结果。请综合所有结果，用自然语言回答用户的问题。

{history_block}

规则：当“对话历史”与“当前问题/本次查询结果”矛盾时，以“当前问题/本次查询结果”为准，不要被历史带偏。

用户问题：{user_query}

{context_info}

请综合以上所有查询结果，用2-3句话回答用户的问题。"""

        llm_meta = get_llm(config["llm_profile"], **extract_overrides(config))
        llm = llm_meta.llm

        try:
            # DEBUG: 打印完整提示词（由日志级别控制是否可见）
            query_logger.debug("=" * 80)
            query_logger.debug("完整 LLM 提示词（summarizer）:")
            query_logger.debug("=" * 80)
            query_logger.debug(prompt)
            query_logger.debug("=" * 80)

            response = llm.invoke(prompt)
            summary = response.content.strip()
            query_logger.info("LLM 生成总结成功")
        except Exception as e:
            # LLM失败时，使用简单模板
            query_logger.error(f"LLM 生成总结失败: {str(e)}，使用模板", exc_info=True)
            result_count = sum(len(r.get("rows", [])) for r in success_results)
            if result_count == 0:
                summary = "查询成功，但未找到相关数据。"
            elif result_count == 1:
                summary = "查询成功，找到1条记录。"
            else:
                summary = f"查询成功，共找到{result_count}条记录。"

    query_logger.info("Summarizer 完成响应生成")
    return {
        "summary": summary,
    }


def _format_conversation_history(conversation_history: Any) -> str:
    if not conversation_history:
        return ""

    lines: List[str] = ["对话历史（旧→新，仅供指代消解）："]
    for i, turn in enumerate(conversation_history, start=1):
        if not isinstance(turn, dict):
            continue
        q = (turn.get("question") or "").strip()
        a = (turn.get("answer") or "").strip()
        if not q and not a:
            continue
        lines.append(f"{i}. Q: {q}")
        lines.append(f"   A: {a}")
    return "\n".join(lines)


def _build_error_summary(error: str, error_type: str, user_query: str) -> str:
    """将技术错误转换为用户友好的提示

    Args:
        error: 错误信息
        error_type: 错误类型
        user_query: 用户问题

    Returns:
        用户友好的错误提示
    """
    # 错误类型到友好提示的映射
    error_templates = {
        "parsing_failed": "抱歉，系统无法理解您的问题。建议您换一种方式描述，或提供更多上下文信息。",
        "schema_retrieval_failed": "抱歉，系统暂时无法找到相关的数据表。请确认您的问题是否涉及系统已有的数据。",
        "generation_failed": "抱歉，系统在生成查询时遇到了问题。可能是问题过于复杂，建议您简化问题后重试。",
        "validation_failed": "抱歉，系统生成的查询存在问题，无法执行。建议您换一种方式提问。",
        "validation_syntax_failed": "抱歉，系统生成的SQL存在语法问题，建议您换一种方式描述。",
        "validation_security_failed": "抱歉，系统检测到不安全的查询操作，已拒绝执行。",
        "validation_semantic_failed": "抱歉，系统生成的查询引用了不存在的表或列，建议您确认问题描述。",
    }

    # 获取模板（如果error_type未知，使用通用模板）
    template = error_templates.get(error_type, "抱歉，系统遇到了问题，暂时无法处理您的请求。")

    # Phase 1: 直接返回模板
    # Phase 2 可扩展：使用轻量LLM生成更个性化的错误提示
    # if config.get("enable_llm_error_message"):
    #     return _generate_friendly_error_with_llm(error, error_type, user_query)

    return template


def _format_table(columns: List[str], rows: List[List[Any]]) -> str:
    """格式化结果为表格字符串

    Args:
        columns: 列名列表
        rows: 数据行列表

    Returns:
        格式化后的表格字符串
    """
    if not rows:
        return "（无数据）"

    # 简单的表格格式
    lines = []
    lines.append(" | ".join(columns))
    lines.append("-" * 50)

    for row in rows:
        lines.append(" | ".join(str(v) for v in row))

    if len(rows) >= 10:
        lines.append("...")

    return "\n".join(lines)


def _format_multi_results(results: List[Dict], sub_queries: List[Dict], max_rows: int) -> str:
    """格式化多SQL结果为字符串

    ⚠️ 重要提示：本函数仅用于 Phase 2（Complex Path）

    Phase 1 说明：
    - Phase 1 只处理 Simple 问题，最多只有 1 条 SQL
    - 本函数在 Phase 1 不会被调用（代码永远走单SQL分支）
    - 开发者在 Phase 1 阶段可以跳过详细实现

    Phase 2 说明：
    - Complex 问题会被拆分为多个子查询，生成多条 SQL
    - 本函数负责将多个查询结果格式化为易读的字符串
    - 每个结果会显示对应的子查询问题文本

    Args:
        results: SQL执行结果列表（Phase 2 可能有多个）
        sub_queries: 子查询列表
        max_rows: 每个结果最多显示的行数

    Returns:
        格式化后的多结果字符串
    """
    # Phase 2 完整实现：为每个结果显示对应的子查询问题文本
    # 1. 构建 sub_query_id 到 sub_query 对象的映射
    sub_query_map = {sq["sub_query_id"]: sq for sq in sub_queries}

    # 2. 格式化每个结果
    lines = []
    for idx, result in enumerate(results, 1):
        sub_query_id = result.get("sub_query_id")

        # 3. 获取子查询文本（用于标题）
        if sub_query_id and sub_query_id in sub_query_map:
            query_text = sub_query_map[sub_query_id].get("query", "")
            if query_text:
                title = f"【{query_text}】"
            else:
                # 子查询存在但 query 字段为空（异常情况）
                title = f"查询 {idx}"
        else:
            # 回退：找不到对应子查询时使用通用标题（异常情况）
            title = f"查询 {idx}"

        # 4. 格式化表格
        rows = result.get("rows", [])
        columns = result.get("columns", [])

        lines.append(f"\n{title}")
        lines.append(_format_table(columns, rows[:max_rows]))

        # 5. 可选：显示行数统计（如果结果被截断）
        if len(rows) > max_rows:
            lines.append(f"（仅显示前{max_rows}行，实际共{len(rows)}行）")

    return "\n".join(lines)
