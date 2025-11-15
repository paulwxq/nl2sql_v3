"""NL2SQL 父图编译与执行

此模块负责：
1. SQL生成子图 Wrapper（数据转换）
2. 条件边函数（路由逻辑）
3. 父图编译（组装所有节点）
4. 便捷函数（对外接口）
"""

import time
import uuid
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.modules.nl2sql_father.nodes.router import router_node
from src.modules.nl2sql_father.nodes.simple_planner import simple_planner_node
from src.modules.nl2sql_father.nodes.sql_execution import sql_execution_node
from src.modules.nl2sql_father.nodes.summarizer import summarizer_node
from src.modules.nl2sql_father.state import (
    NL2SQLFatherState,
    create_initial_state,
    extract_final_result,
)
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("nl2sql_father")


# ==================== SQL 生成子图 Wrapper ====================


def sql_gen_wrapper(state: NL2SQLFatherState) -> Dict[str, Any]:
    """SQL生成子图的 Wrapper（Fast Path）

    职责：
    1. 从 sub_queries 中获取当前子查询
    2. 调用 SQL 生成子图
    3. 将子图输出映射回父图State
    4. 更新 sub_queries 中对应子查询的状态

    为什么需要 Wrapper：
    - 父图使用 sub_queries 列表管理子查询（支持复杂路径的多子查询）
    - 子图需要单个 query 字符串作为输入
    - 避免在父图 State 中添加冗余字段（query, dependencies_results, parse_hints）

    Args:
        state: 父图 State

    Returns:
        更新的 State 字段：
        - validated_sql: 验证通过的 SQL
        - error: 错误信息
        - error_type: 错误类型
        - iteration_count: 迭代次数
    """
    from src.modules.sql_generation.subgraph.create_subgraph import (
        run_sql_generation_subgraph,
    )

    query_logger = with_query_id(logger, state.get("query_id", "unknown"))

    current_sub_query_id = state.get("current_sub_query_id")
    if not current_sub_query_id:
        query_logger.error("缺少 current_sub_query_id")
        return {"error": "No current sub_query_id", "error_type": "internal_error"}

    # 从 sub_queries 中找到当前子查询
    sub_queries = state.get("sub_queries", [])
    current_sub_query = None
    for sq in sub_queries:
        if sq["sub_query_id"] == current_sub_query_id:
            current_sub_query = sq
            break

    if not current_sub_query:
        query_logger.error(f"未找到子查询: {current_sub_query_id}")
        return {
            "error": f"Sub query {current_sub_query_id} not found",
            "error_type": "internal_error",
        }

    query_logger.info(f"开始调用 SQL 生成子图: {current_sub_query_id}")

    # 调用子图（使用便捷函数）+ 异常兜底
    try:
        subgraph_output = run_sql_generation_subgraph(
            query=current_sub_query["query"],  # 子查询文本
            query_id=state["query_id"],  # 会话级查询ID（用于日志关联与链路追踪）
            user_query=state["user_query"],  # 原始用户问题
            dependencies_results={},  # Fast Path 无依赖
            parse_hints=None,
        )

        # 更新当前子查询的状态
        if subgraph_output.get("validated_sql"):
            current_sub_query["status"] = "completed"
            current_sub_query["validated_sql"] = subgraph_output["validated_sql"]
            current_sub_query["iteration_count"] = subgraph_output.get("iteration_count", 0)
            query_logger.info(f"SQL 生成成功: {current_sub_query_id}")
        else:
            current_sub_query["status"] = "failed"
            current_sub_query["error"] = subgraph_output.get("error")
            query_logger.warning(f"SQL 生成失败: {current_sub_query_id}, error_type={subgraph_output.get('error_type')}")

        # 映射输出到父图State
        return {
            "validated_sql": subgraph_output.get("validated_sql"),
            "error": subgraph_output.get("error"),
            "error_type": subgraph_output.get("error_type"),
            "iteration_count": subgraph_output.get("iteration_count"),
        }

    except Exception as e:
        # 兜底：子图崩溃时记录错误，确保父图不会直接崩溃
        error_msg = f"SQL生成子图执行异常: {str(e)}"
        query_logger.error(error_msg, exc_info=True)

        # 更新子查询状态
        current_sub_query["status"] = "failed"
        current_sub_query["error"] = error_msg

        # 返回错误信息，流程将进入 Summarizer 输出友好提示
        return {
            "validated_sql": None,
            "error": error_msg,
            "error_type": "generation_failed",
            "iteration_count": 0,
        }


# ==================== 条件边函数 ====================


def route_by_complexity(state: NL2SQLFatherState) -> str:
    """条件边：根据 complexity 路由

    注意：complexity 是字符串 "simple" 或 "complex"，不是布尔值

    Returns:
        "simple_planner": 走 Fast Path，进入 Simple Planner 准备参数（当 complexity == "simple"）
        "summarizer": Phase 1 暂不支持复杂问题，直接进入 Summarizer（当 complexity == "complex"）
    """
    complexity = state.get("complexity")

    # 字符串比较（不是布尔判断）
    if complexity == "simple":  # ← 比较字符串 "simple"
        return "simple_planner"  # ← 进入 Simple Planner
    else:
        # Phase 1：复杂问题暂不支持，直接进入统一的 Summarizer 返回友好提示
        return "summarizer"


def route_after_sql_gen(state: NL2SQLFatherState) -> str:
    """SQL生成后的路由：判断是否成功

    成功标志：validated_sql 非空

    Returns:
        "sql_exec": SQL生成成功，进入执行节点
        "summarizer": SQL生成失败，跳过执行，直接总结错误
    """
    if state.get("validated_sql"):
        return "sql_exec"  # 生成成功 → 执行SQL
    else:
        return "summarizer"  # 生成失败 → 直接总结错误


# ==================== 父图编译 ====================


def create_nl2sql_father_graph():
    """创建 NL2SQL 父图（Phase 1：Fast Path）

    拓扑：
    START → router → [simple_planner → sql_gen → [sql_exec → summarizer | summarizer] | summarizer] → END

    设计要点：
    1. Router 判定 simple → 进入 Simple Planner 准备参数
    2. Simple Planner → SQL生成子图（准备好参数后直接调用）
    3. Router 判定 complex → 直接进入 Summarizer（Phase 1 返回"暂不支持"提示）
    4. SQL生成失败 → 跳过SQL执行，直接进入Summarizer
    5. 所有路径统一经过 Summarizer 节点，确保返回格式一致

    Returns:
        编译后的父图（可执行）
    """
    # 创建状态图
    graph = StateGraph(NL2SQLFatherState)

    # ========== 添加节点 ==========
    graph.add_node("router", router_node)
    graph.add_node("simple_planner", simple_planner_node)  # 新增：Simple 问题参数准备
    graph.add_node("sql_gen", sql_gen_wrapper)
    graph.add_node("sql_exec", sql_execution_node)
    graph.add_node("summarizer", summarizer_node)  # 统一的响应构建器

    # ========== 添加边 ==========
    # 入口
    graph.add_edge(START, "router")

    # Router 条件边（共享 Summarizer 设计）
    graph.add_conditional_edges(
        "router",
        route_by_complexity,
        {
            "simple_planner": "simple_planner",  # simple → Simple Planner（参数准备）
            "summarizer": "summarizer",  # complex → 直接总结（暂不支持提示）
        },
    )

    # Simple Planner 固定边（参数准备完成后直接进入SQL生成）
    graph.add_edge("simple_planner", "sql_gen")

    # SQL生成后的条件边（优化：失败时跳过SQL执行）
    graph.add_conditional_edges(
        "sql_gen",
        route_after_sql_gen,
        {
            "sql_exec": "sql_exec",  # 生成成功 → 执行SQL
            "summarizer": "summarizer",  # 生成失败 → 直接总结错误
        },
    )

    # SQL执行后必定进入Summarizer
    graph.add_edge("sql_exec", "summarizer")
    graph.add_edge("summarizer", END)

    # ========== 编译 ==========
    app = graph.compile()

    logger.info("NL2SQL 父图编译完成")
    return app


# ==================== 便捷函数 ====================


def run_nl2sql_query(query: str, query_id: str = None) -> Dict[str, Any]:
    """执行 NL2SQL 查询（便捷函数）

    Args:
        query: 用户问题
        query_id: 查询ID（可选，不提供则自动生成）

    Returns:
        查询结果字典，包含：
        - user_query: 用户原始问题
        - query_id: 查询ID
        - complexity: "simple" | "complex" | None
        - path_taken: "fast" | "complex" | None
        - summary: 自然语言总结
        - error: 错误信息（若失败）
        - sql: 验证通过的 SQL（快捷访问）
        - sub_queries: 完整子查询列表
        - execution_results: 完整执行结果
        - metadata: 元数据（执行时间等）
    """
    # 创建父图
    start_time = time.time()
    app = create_nl2sql_father_graph()

    # 创建初始 State（query_id 由 create_initial_state 自动生成）
    initial_state = create_initial_state(user_query=query, query_id=query_id)

    # 获取实际的 query_id（可能是自动生成的）
    actual_query_id = initial_state["query_id"]

    # 日志
    query_logger = with_query_id(logger, actual_query_id)
    query_logger.info(f"开始执行 NL2SQL 查询: {query[:50]}...")

    # 执行父图
    final_state = app.invoke(initial_state)

    # 记录总耗时
    total_time_ms = (time.time() - start_time) * 1000
    final_state["total_execution_time_ms"] = total_time_ms

    # 提取结果
    result = extract_final_result(final_state)

    query_logger.info(
        f"NL2SQL 查询完成: complexity={result.get('complexity')}, "
        f"path={result.get('path_taken')}, "
        f"total_time={total_time_ms:.0f}ms"
    )

    return result
