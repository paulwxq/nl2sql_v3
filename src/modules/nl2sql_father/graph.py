"""NL2SQL 父图编译与执行

此模块负责：
1. SQL生成子图 Wrapper（数据转换）
2. 条件边函数（路由逻辑）
3. 父图编译（组装所有节点）
4. 便捷函数（对外接口）
5. LangGraph 持久化接入（Checkpoint + Store）
"""

import time
import uuid
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.modules.nl2sql_father.nodes.router import router_node
from src.modules.nl2sql_father.nodes.simple_planner import simple_planner_node
from src.modules.nl2sql_father.nodes.sql_execution import sql_execution_node
from src.modules.nl2sql_father.nodes.summarizer import summarizer_node
# Phase 2 新增节点
from src.modules.nl2sql_father.nodes.planner import planner_node
from src.modules.nl2sql_father.nodes.inject_params import inject_params_node
from src.modules.nl2sql_father.nodes.check_completion import check_completion_node
from src.modules.nl2sql_father.state import (
    NL2SQLFatherState,
    create_initial_state,
    extract_final_result,
)
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("father")

_father_graph_config_cache: dict | None = None


def _get_father_graph_config() -> dict:
    global _father_graph_config_cache
    if _father_graph_config_cache is None:
        from src.services.config_loader import load_config

        config_path = "src/modules/nl2sql_father/config/nl2sql_father_graph.yaml"
        _father_graph_config_cache = load_config(config_path)
    return _father_graph_config_cache

# ==============================================================================
# 编译图缓存（单例）
# ==============================================================================

_compiled_graph: Optional[CompiledStateGraph] = None
_compiled_graph_with_checkpoint: bool = False  # 记录当前缓存的图是否带 checkpointer


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
        return {"error": "No current sub_query_id", "error_type": "internal_error", "sub_queries": state.get("sub_queries", [])}

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
            "sub_queries": sub_queries,
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
            # 【新增】checkpoint 相关参数
            sub_query_id=current_sub_query_id,
            thread_id=state.get("thread_id"),
            conversation_history=state.get("conversation_history"),
        )

        # 更新当前子查询的状态
        if subgraph_output.get("validated_sql"):
            current_sub_query["status"] = "completed"
            current_sub_query["validated_sql"] = subgraph_output["validated_sql"]
            current_sub_query["iteration_count"] = subgraph_output.get("iteration_count", 0)
            current_sub_query["error"] = None
            current_sub_query["error_type"] = None
            current_sub_query["failed_step"] = None
            query_logger.info(f"SQL 生成成功: {current_sub_query_id}")
        else:
            current_sub_query["status"] = "failed"
            current_sub_query["error"] = subgraph_output.get("error")
            current_sub_query["error_type"] = subgraph_output.get("error_type")
            current_sub_query["failed_step"] = subgraph_output.get("failed_step")
            query_logger.warning(f"SQL 生成失败: {current_sub_query_id}, error_type={subgraph_output.get('error_type')}")

        # 映射输出到父图State（显式返回 sub_queries 以确保 in-place 修改被持久化）
        return {
            "validated_sql": subgraph_output.get("validated_sql"),
            "error": subgraph_output.get("error"),
            "error_type": subgraph_output.get("error_type"),
            "failed_step": subgraph_output.get("failed_step"),
            "iteration_count": subgraph_output.get("iteration_count"),
            "sub_queries": sub_queries,
        }

    except Exception as e:
        # 兜底：子图崩溃时记录错误，确保父图不会直接崩溃
        error_msg = f"SQL生成子图执行异常: {str(e)}"
        query_logger.error(error_msg, exc_info=True)

        # 更新子查询状态
        current_sub_query["status"] = "failed"
        current_sub_query["error"] = error_msg
        current_sub_query["error_type"] = "generation_failed"
        current_sub_query["failed_step"] = "sql_generation"

        # 返回错误信息，流程将进入 Summarizer 输出友好提示
        return {
            "validated_sql": None,
            "error": error_msg,
            "error_type": "generation_failed",
            "failed_step": "sql_generation",
            "iteration_count": 0,
            "sub_queries": sub_queries,
        }


def sql_gen_batch_wrapper(state: NL2SQLFatherState) -> Dict[str, Any]:
    """SQL生成子图批量 Wrapper（Complex Path）

    职责：
    1. 从 current_batch_ids 获取当前批次待处理的子查询ID列表
    2. 串行调用 SQL 生成子图（Phase 2 不并发调用子图，避免资源竞争）
    3. 更新每个子查询的 validated_sql 和 status

    Args:
        state: 父图 State

    Returns:
        空字典 {}（直接修改 sub_queries，无需返回）
    """
    from src.modules.sql_generation.subgraph.create_subgraph import (
        run_sql_generation_subgraph,
    )

    query_logger = with_query_id(logger, state.get("query_id", "unknown"))

    current_batch_ids = state.get("current_batch_ids", [])
    sub_queries = state.get("sub_queries", [])

    if not current_batch_ids:
        query_logger.warning("current_batch_ids 为空，跳过 SQL 生成")
        return {}

    query_logger.info(f"开始批量 SQL 生成：{len(current_batch_ids)} 个子查询")

    # 串行处理每个子查询
    for sub_query_id in current_batch_ids:
        # 找到对应的子查询
        sub_query = next((sq for sq in sub_queries if sq["sub_query_id"] == sub_query_id), None)
        if not sub_query:
            query_logger.warning(f"未找到子查询: {sub_query_id}")
            continue

        query_logger.info(f"生成 SQL: {sub_query_id}")

        try:
            # 调用 SQL 生成子图
            subgraph_output = run_sql_generation_subgraph(
                query=sub_query["query"],
                query_id=state["query_id"],
                user_query=state["user_query"],
                dependencies_results=sub_query.get("dependencies_results", {}),
                parse_hints=None,
                # 【新增】checkpoint 相关参数
                sub_query_id=sub_query_id,
                thread_id=state.get("thread_id"),
                conversation_history=state.get("conversation_history"),
            )

            # 更新子查询状态
            if subgraph_output.get("validated_sql"):
                sub_query["validated_sql"] = subgraph_output["validated_sql"]
                sub_query["iteration_count"] = subgraph_output.get("iteration_count", 0)
                sub_query["error"] = None
                sub_query["error_type"] = None
                sub_query["failed_step"] = None
                # 注意：不在此处更新 status，由 SQL 执行节点更新为 completed
                query_logger.info(f"SQL 生成成功: {sub_query_id}")
            else:
                sub_query["status"] = "failed"
                sub_query["error"] = subgraph_output.get("error", "SQL生成失败")
                sub_query["error_type"] = subgraph_output.get("error_type")
                sub_query["failed_step"] = subgraph_output.get("failed_step")
                query_logger.warning(
                    f"SQL 生成失败: {sub_query_id}, error_type={subgraph_output.get('error_type')}"
                )

        except Exception as e:
            # 异常兜底
            error_msg = f"SQL生成子图执行异常: {str(e)}"
            query_logger.error(error_msg, exc_info=True)
            sub_query["status"] = "failed"
            sub_query["error"] = error_msg
            sub_query["error_type"] = "generation_failed"
            sub_query["failed_step"] = "sql_generation"

    return {"sub_queries": state.get("sub_queries", [])}  # 显式返回 sub_queries 以确保 in-place 修改被持久化


# ==================== 条件边函数 ====================


def route_by_complexity(state: NL2SQLFatherState) -> str:
    """条件边：根据 complexity 路由

    注意：complexity 是字符串 "simple" 或 "complex"，不是布尔值

    Returns:
        "simple_planner": 走 Fast Path（当 complexity == "simple"）
        "planner": 走 Complex Path（当 complexity == "complex"）
    """
    complexity = state.get("complexity")

    # 字符串比较（不是布尔判断）
    if complexity == "simple":
        return "simple_planner"  # Fast Path
    else:
        return "planner"  # Complex Path (Phase 2)


def route_after_sql_gen(state: NL2SQLFatherState) -> str:
    """SQL生成后的路由：判断是否成功（Fast Path 专用）

    成功标志：validated_sql 非空

    Returns:
        "sql_exec": SQL生成成功，进入执行节点
        "summarizer": SQL生成失败，跳过执行，直接总结错误
    """
    if state.get("validated_sql"):
        return "sql_exec"  # 生成成功 → 执行SQL
    else:
        return "summarizer"  # 生成失败 → 直接总结错误


def route_after_check_completion(state: NL2SQLFatherState) -> str:
    """Check Completion 后的路由：判断是否继续循环（Complex Path 专用）

    判断标准：是否所有子查询都已完成

    Returns:
        "inject_params": 继续循环（还有未完成的子查询）
        "summarizer": 结束循环，进入总结
    """
    sub_queries = state.get("sub_queries", [])

    # 检查是否所有子查询都已完成或失败
    all_done = all(
        sq.get("status") in ["completed", "failed"]
        for sq in sub_queries
    )

    if all_done:
        return "summarizer"
    else:
        return "inject_params"


def route_after_sql_exec(state: NL2SQLFatherState) -> str:
    """SQL 执行后的路由：判断当前路径

    根据 path_taken 判断是 Fast Path 还是Complex Path

    Returns:
        "summarizer": Fast Path，直接进入总结
        "check_completion": Complex Path，进入完成度检查
    """
    path_taken = state.get("path_taken")

    if path_taken == "fast":
        return "summarizer"
    else:  # complex
        return "check_completion"


def route_after_planner(state: NL2SQLFatherState) -> str:
    """Planner 后的路由：判断是否成功

    成功标志：sub_queries 非空且无 error

    Returns:
        "inject_params": Planner 成功，进入参数注入
        "summarizer": Planner 失败，直接总结错误
    """
    sub_queries = state.get("sub_queries", [])
    error = state.get("error")

    if sub_queries and not error:
        return "inject_params"
    else:
        return "summarizer"


# ==================== 父图编译 ====================


def create_nl2sql_father_graph(checkpointer=None) -> CompiledStateGraph:
    """创建 NL2SQL 父图（Phase 1 + Phase 2）

    拓扑（统一图，包含 Fast Path 和 Complex Path）：

    START → router → {
        [Fast Path]  simple_planner → sql_gen → sql_exec → summarizer → END
        [Complex Path] planner → inject_params → sql_gen_batch → sql_exec →
                       check_completion → {inject_params (循环) | summarizer → END}
    }

    设计要点：
    1. Router 判定 simple → Fast Path（Simple Planner）
    2. Router 判定 complex → Complex Path（Planner）
    3. Complex Path 支持循环：inject_params → sql_gen_batch → sql_exec → check_completion
    4. Check Completion 判定未完成 → 循环回 inject_params
    5. Check Completion 判定完成 → 进入 Summarizer
    6. 所有路径统一经过 Summarizer 节点，确保返回格式一致

    Args:
        checkpointer: 可选的 checkpointer（PostgresSaver 或 SafeCheckpointer）

    Returns:
        编译后的父图（可执行）
    """
    # 创建状态图
    graph = StateGraph(NL2SQLFatherState)

    # ========== 添加节点 ==========
    # 共享节点
    graph.add_node("router", router_node)
    graph.add_node("sql_exec", sql_execution_node)  # 共享：Phase 1 + Phase 2
    graph.add_node("summarizer", summarizer_node)  # 共享：Phase 1 + Phase 2

    # Fast Path 节点
    graph.add_node("simple_planner", simple_planner_node)
    graph.add_node("sql_gen", sql_gen_wrapper)

    # Complex Path 节点（Phase 2）
    graph.add_node("planner", planner_node)
    graph.add_node("inject_params", inject_params_node)
    graph.add_node("sql_gen_batch", sql_gen_batch_wrapper)
    graph.add_node("check_completion", check_completion_node)

    # ========== 添加边 ==========
    # 入口
    graph.add_edge(START, "router")

    # Router 条件边（Fast Path vs Complex Path）
    graph.add_conditional_edges(
        "router",
        route_by_complexity,
        {
            "simple_planner": "simple_planner",  # Fast Path
            "planner": "planner",  # Complex Path (Phase 2)
        },
    )

    # ========== Fast Path 边 ==========
    graph.add_edge("simple_planner", "sql_gen")
    graph.add_conditional_edges(
        "sql_gen",
        route_after_sql_gen,
        {
            "sql_exec": "sql_exec",
            "summarizer": "summarizer",
        },
    )

    # ========== Complex Path 边（Phase 2）==========
    # Planner 条件边（失败时直接进入 Summarizer）
    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "inject_params": "inject_params",  # 成功 → 参数注入
            "summarizer": "summarizer",  # 失败 → 直接总结错误
        },
    )
    graph.add_edge("inject_params", "sql_gen_batch")
    graph.add_edge("sql_gen_batch", "sql_exec")  # 批量生成后执行SQL

    # ========== SQL 执行后的路由（共享节点，不同路径）==========
    graph.add_conditional_edges(
        "sql_exec",
        route_after_sql_exec,
        {
            "summarizer": "summarizer",  # Fast Path → 直接总结
            "check_completion": "check_completion",  # Complex Path → 检查完成度
        },
    )

    # Check Completion 条件边（循环控制）
    graph.add_conditional_edges(
        "check_completion",
        route_after_check_completion,
        {
            "inject_params": "inject_params",  # 循环边：继续下一轮
            "summarizer": "summarizer",  # 结束：进入总结
        },
    )

    # ========== 出口 ==========
    graph.add_edge("summarizer", END)

    # ========== 编译 ==========
    if checkpointer is not None:
        app = graph.compile(checkpointer=checkpointer)
        logger.info("NL2SQL 父图编译完成（Fast Path + Complex Path，已启用 Checkpoint）")
    else:
        app = graph.compile()
        logger.info("NL2SQL 父图编译完成（Fast Path + Complex Path）")

    return app


def get_compiled_father_graph() -> CompiledStateGraph:
    """获取编译后的父图（带缓存）

    根据 checkpoint 开关状态决定是否传入 checkpointer。
    使用模块级缓存避免每次请求都重新编译。

    缓存策略：
        - 按"配置意图"缓存，而非"实际是否有 checkpointer"
        - 如果 checkpoint 启用但 saver 创建失败，会缓存无 checkpointer 的图
        - DB 恢复后不会自动重试，需要调用 reset_father_graph_cache() 或重启应用

    Returns:
        编译后的父图
    """
    global _compiled_graph, _compiled_graph_with_checkpoint

    from src.services.langgraph_persistence.postgres import (
        get_postgres_saver,
        is_father_checkpoint_enabled,
    )
    from src.services.langgraph_persistence.safe_checkpointer import SafeCheckpointer

    # 检查当前 checkpoint 开关状态（配置意图）
    checkpoint_enabled = is_father_checkpoint_enabled()

    # 如果缓存存在且配置意图一致，直接返回（避免重复编译）
    # 注意：即使 saver 创建失败，只要配置意图不变就复用缓存
    if _compiled_graph is not None and _compiled_graph_with_checkpoint == checkpoint_enabled:
        return _compiled_graph

    # 需要重新编译
    checkpointer = None
    if checkpoint_enabled:
        real_checkpointer = get_postgres_saver("father")
        if real_checkpointer is not None:
            # 使用 SafeCheckpointer 包装，实现 fail-open
            checkpointer = SafeCheckpointer(real_checkpointer, enabled=True)
            logger.info("父图使用 SafeCheckpointer（fail-open 模式）")
        else:
            logger.warning("Checkpoint 已启用但 PostgresSaver 创建失败，父图将不使用 checkpointer")

    _compiled_graph = create_nl2sql_father_graph(checkpointer=checkpointer)
    # 记录"配置意图"，用于缓存判断（避免 saver 创建失败时每次重新编译）
    _compiled_graph_with_checkpoint = checkpoint_enabled

    return _compiled_graph


def reset_father_graph_cache():
    """重置父图编译缓存

    使用场景：
        1. 单元测试：在 setup/teardown 中调用，确保测试隔离
        2. DB 恢复重试：如果 checkpoint 启用但 saver 创建失败，
           DB 恢复后调用此函数可触发重新编译挂载 checkpointer
    """
    global _compiled_graph, _compiled_graph_with_checkpoint
    _compiled_graph = None
    _compiled_graph_with_checkpoint = False


# ==================== 便捷函数 ====================


def run_nl2sql_query(
    query: str,
    query_id: str = None,
    thread_id: str = None,
    user_id: str = None,
) -> Dict[str, Any]:
    """执行 NL2SQL 查询（便捷函数）

    Args:
        query: 用户问题
        query_id: 查询ID（可选，不提供则自动生成）
        thread_id: 会话ID（可选，多轮对话时复用）
        user_id: 用户标识（可选，未登录时为 "guest"）

    Returns:
        查询结果字典，包含：
        - user_query: 用户原始问题
        - query_id: 查询ID
        - thread_id: 会话ID
        - user_id: 用户标识
        - complexity: "simple" | "complex" | None
        - path_taken: "fast" | "complex" | None
        - summary: 自然语言总结
        - error: 错误信息（若失败）
        - sql: 验证通过的 SQL（快捷访问）
        - sub_queries: 完整子查询列表
        - execution_results: 完整执行结果
        - metadata: 元数据（执行时间等）
    """
    from src.services.langgraph_persistence.postgres import (
        get_checkpoint_namespace,
        is_father_checkpoint_enabled,
        is_store_enabled,
    )
    from src.services.langgraph_persistence.chat_history_writer import append_turn
    from src.services.langgraph_persistence.chat_history_reader import get_recent_turns

    start_time = time.time()

    # 获取编译后的图（带缓存，自动处理 checkpoint）
    app = get_compiled_father_graph()

    # 创建初始 State（thread_id/user_id 由 create_initial_state 自动处理）
    initial_state = create_initial_state(
        user_query=query,
        query_id=query_id,
        thread_id=thread_id,
        user_id=user_id,
    )

    # 获取实际的标识（可能是自动生成的）
    actual_query_id = initial_state["query_id"]
    actual_thread_id = initial_state["thread_id"]
    actual_user_id = initial_state["user_id"]

    # 日志
    query_logger = with_query_id(logger, actual_query_id)
    query_logger.info(f"开始执行 NL2SQL 查询: {query[:50]}...")
    query_logger.debug(f"thread_id={actual_thread_id}, user_id={actual_user_id}")

    # 读取对话历史（fail-open；仅一次读取并透传到子图/父图节点）
    conversation_history = []
    try:
        cfg = _get_father_graph_config().get("conversation_history", {}) or {}
        if cfg.get("enabled", False) and is_store_enabled():
            conversation_history = get_recent_turns(
                thread_id=actual_thread_id,
                history_max_turns=int(cfg.get("history_max_turns", 3)),
                max_history_content_length=int(cfg.get("max_history_content_length", 200)),
                exclude_query_id=actual_query_id,
                timeout_seconds=float(cfg.get("read_timeout_seconds", 10)),
            )
            query_logger.debug(f"读取到对话历史 {len(conversation_history)} 轮")
    except Exception as e:
        query_logger.warning(f"读取对话历史失败（已忽略，继续执行）: {e}")

    initial_state["conversation_history"] = conversation_history

    # 构建 invoke 配置（checkpoint 需要 thread_id 和 checkpoint_ns）
    # 注意：这里按"配置意图"而非"实际挂载状态"判断
    # 如果 saver 创建失败导致图没有 checkpointer，传递这些参数是无害的，LangGraph 会忽略
    invoke_config = None
    if is_father_checkpoint_enabled():
        father_namespace = get_checkpoint_namespace("father")
        invoke_config = {
            "configurable": {
                "thread_id": actual_thread_id,
                "checkpoint_ns": father_namespace,
            }
        }
        query_logger.debug(f"Checkpoint 已启用: namespace={father_namespace}")

    # 执行父图（invoke_config 为 None 时不传 config 参数，使用默认值）
    if invoke_config is not None:
        final_state = app.invoke(initial_state, config=invoke_config)
    else:
        final_state = app.invoke(initial_state)

    # 记录总耗时
    total_time_ms = (time.time() - start_time) * 1000
    final_state["total_execution_time_ms"] = total_time_ms

    # 提取结果
    result = extract_final_result(final_state)

    # 写入历史对话（仅写入，失败不影响主流程）
    if is_store_enabled():
        try:
            success = any(
                isinstance(r, dict) and r.get("success") for r in result.get("execution_results", [])
            )
            append_turn(
                thread_id=actual_thread_id,
                query_id=actual_query_id,
                user_text=query,
                assistant_text=result.get("summary") or "",
                user_id=actual_user_id,
                metadata={
                    "complexity": result.get("complexity"),
                    "path_taken": result.get("path_taken"),
                    "total_execution_time_ms": total_time_ms,
                    "sub_query_count": len(result.get("sub_queries", [])),
                },
                success=success,
            )
            query_logger.debug("历史对话写入成功")
        except Exception as e:
            query_logger.warning(f"历史对话写入失败（已跳过）: {e}")

    query_logger.info(
        f"NL2SQL 查询完成: complexity={result.get('complexity')}, "
        f"path={result.get('path_taken')}, "
        f"total_time={total_time_ms:.0f}ms"
    )

    return result
