"""NL2SQL 父图的 State 定义

定义父图的状态类型和辅助函数。
"""

import logging
import uuid
from typing import Any, Dict, List, Literal, Optional, TypedDict

logger = logging.getLogger(__name__)


class SubQueryInfo(TypedDict):
    """子查询信息

    用于管理拆分后的子查询（Phase 1 只有单个子查询，Phase 2 支持多个）
    """

    sub_query_id: str  # 子查询ID（格式：{query_id}_sq1）
    query: str  # 子查询文本
    status: str  # pending | in_progress | completed | failed
    dependencies: List[str]  # 依赖的其他子查询ID列表（Phase 2）
    validated_sql: Optional[str]  # 生成的SQL（验证通过）
    execution_result: Optional[Dict[str, Any]]  # 执行结果（双向绑定）
    error: Optional[str]  # 错误信息
    iteration_count: int  # SQL生成迭代次数
    dependencies_results: Optional[Dict[str, Any]]  # Phase 2: 依赖结果字典（由 Inject Params 注入）


class SQLExecutionResult(TypedDict):
    """SQL执行结果

    规范化的SQL执行结果类型
    """

    sub_query_id: str  # 所属子查询ID（用于精确定位）
    sql: str  # 执行的SQL语句
    success: bool  # 是否执行成功
    columns: Optional[List[str]]  # 列名列表
    rows: Optional[List[List[Any]]]  # 结果行（列表的列表）
    row_count: int  # 结果行数
    execution_time_ms: float  # 执行耗时（毫秒）
    error: Optional[str]  # 错误信息（若失败）


class NL2SQLFatherState(TypedDict):
    """NL2SQL 父图的 State 定义

    使用 TypedDict 定义，支持 LangGraph 的类型检查和序列化。
    所有字段使用覆盖模式（无 reducer），每次节点返回时覆盖旧值。
    """

    # ========== 输入与标识 ==========
    user_query: str  # 用户原始问题
    query_id: str  # 会话级查询ID
    thread_id: str  # 会话 ID（格式：{user_id}:{timestamp}）
    user_id: str  # 用户标识（未登录时为 "guest"）
    conversation_history: Optional[List[Dict[str, str]]]  # 对话历史（旧→新，仅 Q/A）

    # ========== 子查询管理（支持拆分） ==========
    sub_queries: List[SubQueryInfo]  # 子查询列表（覆盖模式）
    current_sub_query_id: Optional[str]  # 当前处理的子查询ID

    # ========== Router 输出 ==========
    complexity: Optional[Literal["simple", "complex"]]  # 问题复杂度（字符串枚举）
    router_reason: Optional[str]  # Router 判定理由
    router_latency_ms: Optional[float]  # Router 延迟（毫秒）

    # ========== SQL生成子图输出（当前子查询） ==========
    validated_sql: Optional[str]  # 验证通过的SQL
    error: Optional[str]  # 错误信息
    error_type: Optional[str]  # 错误类型
    iteration_count: Optional[int]  # SQL生成迭代次数

    # ========== SQL执行结果 ==========
    execution_results: List[SQLExecutionResult]  # 执行结果列表（覆盖模式）

    # ========== Phase 2 新增字段（Complex Path） ==========
    dependency_graph: Optional[Dict[str, Any]]  # 依赖图结构（Planner 输出，API 诊断）
    current_round: Optional[int]  # 当前轮次（从1开始，Check Completion 递增）
    max_rounds: Optional[int]  # 最大轮次（Planner 从配置读取并设置）
    current_batch_ids: Optional[List[str]]  # 当前轮次待执行的子查询ID列表（Inject Params 输出）
    planner_latency_ms: Optional[float]  # Planner 延迟（毫秒，Phase 2 监控指标）
    parallel_execution_count: Optional[int]  # 本轮并发执行的 SQL 数量（Phase 2 监控指标）

    # ========== 最终输出 ==========
    summary: Optional[str]  # 自然语言总结

    # ========== 元数据 ==========
    total_execution_time_ms: Optional[float]  # 总执行时间（毫秒）
    path_taken: Optional[Literal["fast", "complex"]]  # 执行路径（字符串枚举）
    metadata: Optional[Dict[str, Any]]  # 其他元数据


def create_initial_state(
    user_query: str,
    query_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> NL2SQLFatherState:
    """创建初始 State

    Args:
        user_query: 用户原始问题
        query_id: 查询ID（可选，不提供则自动生成）
        thread_id: 会话ID（可选，格式：{user_id}:{timestamp}）
        user_id: 用户标识（可选，未登录时为 "guest"）

    Returns:
        初始化的父图 State

    thread_id 与 user_id 一致性规则：
        - 只传 thread_id → 从 thread_id 反推 user_id
        - 只传 user_id → 自动生成 thread_id
        - 都传入且一致 → 直接使用
        - 都传入但不一致 → 以 thread_id 为准，记录 warning
        - 都不传 → user_id=guest，自动生成 thread_id
    """
    from src.services.langgraph_persistence.identifiers import (
        get_or_generate_thread_id,
        get_user_id_from_thread_id,
        sanitize_user_id,
        validate_thread_id,
    )

    # 自动生成 query_id（如果未提供）
    if query_id is None:
        query_id = f"q_{uuid.uuid4().hex[:8]}"

    # thread_id 和 user_id 一致性处理
    if thread_id and validate_thread_id(thread_id):
        # 传入了合法 thread_id → 从中反推 user_id
        actual_thread_id = thread_id
        thread_user_id = get_user_id_from_thread_id(thread_id)

        if user_id and user_id != thread_user_id:
            # 两者都传入但不一致 → 以 thread_id 为准，记录 warning
            logger.warning(
                f"user_id '{user_id}' != thread_id prefix '{thread_user_id}', "
                f"using '{thread_user_id}' from thread_id"
            )
        actual_user_id = thread_user_id
    else:
        # 未传入 thread_id 或格式非法 → 自动生成
        # 传入原始 thread_id，让 get_or_generate_thread_id 内部记录 warning（如果非法）
        actual_user_id = sanitize_user_id(user_id)  # 校验 user_id，不合法则回退为 guest
        actual_thread_id = get_or_generate_thread_id(thread_id, actual_user_id)

    return NL2SQLFatherState(
        # 输入
        user_query=user_query,
        query_id=query_id,
        thread_id=actual_thread_id,
        user_id=actual_user_id,
        conversation_history=None,
        # 子查询管理
        sub_queries=[],
        current_sub_query_id=None,
        # Router 输出
        complexity=None,
        router_reason=None,
        router_latency_ms=None,
        # SQL生成输出
        validated_sql=None,
        error=None,
        error_type=None,
        iteration_count=None,
        # 执行结果
        execution_results=[],
        # Phase 2 字段
        dependency_graph=None,
        current_round=None,
        max_rounds=None,
        current_batch_ids=None,
        planner_latency_ms=None,
        parallel_execution_count=None,
        # 最终输出
        summary=None,
        # 元数据
        total_execution_time_ms=None,
        path_taken=None,
        metadata=None,
    )


def extract_final_result(state: NL2SQLFatherState) -> Dict[str, Any]:
    """提取最终返回结果

    从父图 State 中提取用户关心的字段，用于 API 响应。

    Returns:
        返回结果字典，包含：
        - Phase 1 + Phase 2 通用字段（complexity, path_taken, summary, etc.）
        - Phase 2 诊断字段（dependency_graph, current_round, max_rounds）
        - Phase 1 运行时，Phase 2 字段为 None
    """
    # 提取 SQL（快捷访问：仅在单子查询时填充，多子查询时为 None）
    sql = None
    sub_queries = state.get("sub_queries", [])
    if len(sub_queries) == 1:
        sql = sub_queries[0].get("validated_sql")

    return {
        # ========== Phase 1 + Phase 2 通用字段 ==========
        "user_query": state["user_query"],
        "query_id": state["query_id"],
        "thread_id": state.get("thread_id"),  # 会话 ID
        "user_id": state.get("user_id"),  # 用户标识
        "complexity": state.get("complexity"),  # "simple" | "complex" | None
        "path_taken": state.get("path_taken"),  # "fast" | "complex" | None
        "summary": state.get("summary"),
        "error": state.get("error"),
        "sql": sql,  # 快捷访问：单子查询时为 SQL，多子查询时为 None
        "sub_queries": sub_queries,  # 完整子查询列表
        "execution_results": state.get("execution_results", []),  # 完整执行结果

        # ========== Phase 2 诊断字段（Phase 1 为 None）==========
        "dependency_graph": state.get("dependency_graph"),  # Phase 2: 依赖图结构
        "current_round": state.get("current_round"),        # Phase 2: 当前轮次
        "max_rounds": state.get("max_rounds"),              # Phase 2: 最大轮次

        # ========== 元数据 ==========
        "metadata": {
            "total_execution_time_ms": state.get("total_execution_time_ms"),
            "router_latency_ms": state.get("router_latency_ms"),
            "planner_latency_ms": state.get("planner_latency_ms"),  # Phase 2
            "parallel_execution_count": state.get("parallel_execution_count"),  # Phase 2
            "sub_query_count": len(sub_queries),  # Phase 2: 子查询数量
        },
    }
