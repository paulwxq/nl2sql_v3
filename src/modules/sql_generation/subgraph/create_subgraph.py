"""SQL 生成子图编译 - 组装完整的子图"""

import time
import logging
from typing import Literal

from langgraph.graph import END, START, StateGraph

from src.modules.sql_generation.subgraph.nodes.question_parsing import (
    question_parsing_node,
)
from src.modules.sql_generation.subgraph.nodes.schema_retrieval import (
    schema_retrieval_node,
)
from src.modules.sql_generation.subgraph.nodes.sql_generation import sql_generation_node
from src.modules.sql_generation.subgraph.nodes.validation import validation_node
from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("sql_subgraph")


def should_retry(state: SQLGenerationState) -> Literal["retry", "success", "fail"]:
    """
    判断是否应该重试

    根据验证结果和迭代次数决定流程走向

    Args:
        state: 当前 state

    Returns:
        - "success": 验证通过，成功结束
        - "retry": 验证失败且未超过最大迭代次数，重试
        - "fail": 验证失败且已超过最大迭代次数，失败结束
    """
    # 加载配置
    config = load_subgraph_config("sql_generation")
    max_iterations = config.get("retry", {}).get("max_iterations", 3)

    # 检查是否成功
    if state.get("validated_sql"):
        try:
            query_logger = with_query_id(logger, state.get("query_id", ""))
            query_logger.info("验证通过，流程成功结束")
        except Exception:
            pass
        return "success"

    # 检查是否有不可恢复的错误
    error_type = state.get("error_type")
    if error_type in ("schema_retrieval_failed", "generation_failed"):
        # 这些错误通常不通过重试解决
        try:
            query_logger = with_query_id(logger, state.get("query_id", ""))
            query_logger.error(f"出现不可恢复错误: {error_type}，流程失败结束")
        except Exception:
            pass
        return "fail"

    # 检查迭代次数
    iteration_count = state.get("iteration_count", 0)
    if iteration_count < max_iterations:
        try:
            query_logger = with_query_id(logger, state.get("query_id", ""))
            query_logger.warning(
                f"验证失败，准备重试（第 {iteration_count+1}/{max_iterations} 次）"
            )
        except Exception:
            pass
        return "retry"
    else:
        try:
            query_logger = with_query_id(logger, state.get("query_id", ""))
            query_logger.error("重试次数已达上限，流程失败结束")
        except Exception:
            pass
        return "fail"


def create_sql_generation_subgraph():
    """
    创建 SQL 生成子图

    流程：
    START -> schema_retrieval -> sql_generation -> validation
                                      ↑                 |
                                      └─────────────────┘
                                      (重试：validation失败且未超过3次)

    Returns:
        编译后的子图（可执行）
    """
    # 创建状态图
    subgraph = StateGraph(SQLGenerationState)

    # 添加节点
    subgraph.add_node("question_parsing", question_parsing_node)
    subgraph.add_node("schema_retrieval", schema_retrieval_node)
    subgraph.add_node("sql_generation", sql_generation_node)
    subgraph.add_node("validation", validation_node)

    # 入口：START -> question_parsing -> schema_retrieval
    subgraph.add_edge(START, "question_parsing")

    def _check_parsing(state: SQLGenerationState) -> str:
        if state.get("error_type") == "parsing_failed":
            return "fail"
        return "continue"

    subgraph.add_conditional_edges(
        "question_parsing",
        _check_parsing,
        {
            "continue": "schema_retrieval",
            "fail": END,
        },
    )

    # 固定边：schema_retrieval -> sql_generation
    subgraph.add_edge("schema_retrieval", "sql_generation")

    # 固定边：sql_generation -> validation
    subgraph.add_edge("sql_generation", "validation")

    # 条件边：validation -> (retry/success/fail)
    subgraph.add_conditional_edges(
        "validation",
        should_retry,
        {
            "retry": "sql_generation",  # 验证失败且未超过3次 -> 重试
            "success": END,             # 验证通过 -> 结束
            "fail": END,                # 验证失败且已重试3次 -> 结束
        },
    )

    # 编译子图
    compiled = subgraph.compile()
    logger.debug("SQL 生成子图已编译完成")
    return compiled


# 便捷函数：运行子图

def run_sql_generation_subgraph(
    query: str,
    query_id: str,
    user_query: str,
    dependencies_results: dict = None,
    parse_hints: dict = None,
) -> dict:
    """
    运行 SQL 生成子图（便捷函数）

    Args:
        query: 子查询文本
        query_id: 查询ID
        user_query: 用户原始查询
        dependencies_results: 依赖查询结果
        parse_hints: 解析提示

    Returns:
        子图输出字典
    """
    # 创建子图
    subgraph = create_sql_generation_subgraph()

    # 准备输入
    initial_state = {
        "messages": [],
        "query": query,
        "query_id": query_id,
        "user_query": user_query,
        "dependencies_results": dependencies_results or {},
        "parse_hints": parse_hints,
        "iteration_count": 0,
        "validation_history": [],
    }

    # 记录开始时间
    start_time = time.time()

    query_logger = with_query_id(logger, query_id)
    query_logger.info("开始执行 SQL 生成子图")
    logger.debug(f"初始状态准备完成: keys={list(initial_state.keys())}")

    # 运行子图
    final_state = subgraph.invoke(initial_state)

    # 打印最终 State 快照（不依赖 checkpoint，DEBUG 级别；始终可用，由日志级别控制是否可见）
    try:
        import json
        snapshot = {}
        for k, v in final_state.items():
            if k == "messages":
                snapshot["messages_count"] = len(v) if isinstance(v, list) else 0
                continue
            snapshot[k] = v
        query_logger.debug("========== 最终 State 快照 ==========")
        query_logger.debug(json.dumps(snapshot, ensure_ascii=False, indent=2))
        query_logger.debug("====================================")
    except Exception as exc:
        query_logger.warning(f"打印最终 State 快照失败: {exc}")

    # 记录结束时间
    execution_time = time.time() - start_time
    final_state["execution_time"] = execution_time

    # 提取输出
    from src.modules.sql_generation.subgraph.state import extract_output
    output = extract_output(final_state)

    query_logger.info(f"子图执行完成，耗时 {execution_time:.2f}秒")

    return output
