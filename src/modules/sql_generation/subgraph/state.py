"""SQL 生成子图的 State 定义"""

from typing import Annotated, Any, Dict, List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph import MessagesState
from operator import add


class SQLGenerationState(MessagesState):
    """
    SQL 生成子图的状态

    继承自 MessagesState 以支持消息管理（用于 LLM 交互）
    """

    # ========== 输入字段 ==========
    query: str  # 子查询文本
    query_id: str  # 查询ID
    dependencies_results: Dict[str, Any]  # 依赖查询的结果（可能是列表、字典、数值等）
    user_query: str  # 用户原始查询
    parse_hints: Optional[Dict[str, Any]]  # 解析提示

    # ========== 解析阶段 ==========
    parse_result: Optional[Dict[str, Any]] = None  # 内部解析或外部传入的结构化结果
    parsing_source: Optional[str] = None  # "external" | "llm" | "disabled" | "fallback"
    query_embedding: Optional[List[float]] = None  # 查询向量（用于 schema 检索 / 历史 SQL）

    # ========== Schema检索阶段 ==========
    schema_context: Optional[Dict[str, Any]] = None
    # schema_context 结构：
    # {
    #   "tables": [...],           # 相关表列表（向量检索）
    #   "columns": [...],          # 相关列列表（向量检索）
    #   "join_plans": [...],       # JOIN计划（多 Base，图检索）
    #   "table_cards": {...},      # 表卡片字典
    #   "similar_sqls": [...],     # 历史成功SQL案例（兼容旧字段）
    #   "dim_value_matches": [...] # 维度值匹配结果（兼容旧字段）
    #   "candidate_fact_tables": [...],
    #   "candidate_dim_tables": [...],
    #   "table_similarities": {...},
    #   "dim_value_hits": [...],
    # }

    # ========== SQL生成阶段 ==========
    generated_sql: Optional[str] = None  # 当前生成的SQL
    iteration_count: int = 0  # 当前迭代次数

    # ========== 验证阶段 ==========
    validation_result: Optional[Dict[str, Any]] = None
    # validation_result 结构：
    # {
    #   "valid": bool,
    #   "errors": List[str],
    #   "warnings": List[str],  # 性能警告
    #   "layer": str,  # "syntax" / "security" / "semantic" / "all_passed"
    #   "explain_plan": Optional[str]  # EXPLAIN结果
    # }

    # 使用 reducer 避免共享可变默认值问题
    validation_history: Annotated[List[Dict], add] = []  # 所有验证历史

    # ========== 输出字段 ==========
    validated_sql: Optional[str] = None  # 最终验证通过的SQL
    error: Optional[str] = None  # 错误信息
    error_type: Optional[str] = None  # 错误类型
    execution_time: float = 0.0  # 执行耗时


# 为了方便，定义一些类型别名

SQLGenerationInput = Dict[str, Any]  # 输入字典类型
SQLGenerationOutput = Dict[str, Any]  # 输出字典类型


def create_initial_state(
    query: str,
    query_id: str,
    user_query: str,
    dependencies_results: Optional[Dict[str, Any]] = None,
    parse_hints: Optional[Dict[str, Any]] = None,
) -> SQLGenerationState:
    """
    创建初始 State

    Args:
        query: 子查询文本
        query_id: 查询ID
        user_query: 用户原始查询
        dependencies_results: 依赖查询结果
        parse_hints: 解析提示

    Returns:
        初始化的 State
    """
    return SQLGenerationState(
        messages=[],  # MessagesState 必需的字段
        query=query,
        query_id=query_id,
        user_query=user_query,
        dependencies_results=dependencies_results or {},
        parse_hints=parse_hints,
        iteration_count=0,
        validation_history=[],
        execution_time=0.0,
    )


def extract_output(state: SQLGenerationState) -> SQLGenerationOutput:
    """
    从 State 提取输出

    Args:
        state: 子图 State

    Returns:
        输出字典
    """
    return {
        "validated_sql": state.get("validated_sql"),
        "error": state.get("error"),
        "error_type": state.get("error_type"),
        "iteration_count": state.get("iteration_count", 0),
        "execution_time": state.get("execution_time", 0.0),
        "schema_context": state.get("schema_context"),
        "validation_history": state.get("validation_history", []),
    }


def is_successful(state: SQLGenerationState) -> bool:
    """
    判断子图是否成功生成了 SQL

    Args:
        state: 子图 State

    Returns:
        成功返回 True，否则返回 False
    """
    return state.get("validated_sql") is not None


def get_error_summary(state: SQLGenerationState) -> str:
    """
    获取错误摘要

    Args:
        state: 子图 State

    Returns:
        错误摘要文本
    """
    if is_successful(state):
        return "✅ 成功"

    error = state.get("error", "未知错误")
    error_type = state.get("error_type", "unknown")
    iteration_count = state.get("iteration_count", 0)

    return f"❌ 失败 (类型: {error_type}, 迭代: {iteration_count}次)\n{error}"
