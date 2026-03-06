"""Simple Planner 节点：Fast Path 参数准备

Simple Planner 是一个纯函数（不调用 LLM），负责为 Fast Path 准备参数。
执行时间 < 1ms。
"""

from typing import Any, Dict

from src.modules.nl2sql_father.state import NL2SQLFatherState, SubQueryInfo
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("simple_planner")


def simple_planner_node(state: NL2SQLFatherState) -> Dict[str, Any]:
    """Simple Planner 节点：参数准备（纯函数）

    职责：
    1. 创建单个子查询（Fast Path 只有一个子查询）
    2. 设置 current_sub_query_id

    特点：
    - 纯函数，不调用 LLM
    - 执行时间 < 1ms
    - Phase 1: 直接复制 user_query 作为子查询
    - Phase 2 可扩展：对话裁剪、缓存检查等

    Args:
        state: 父图 State

    Returns:
        更新的 State 字段：
        - sub_queries: 包含单个子查询的列表
        - current_sub_query_id: 当前子查询ID
    """
    user_query = state["user_query"]
    query_id = state["query_id"]

    # 日志
    query_logger = with_query_id(logger, query_id)
    query_logger.info("Simple Planner 开始准备参数")

    # 创建子查询ID（格式：{query_id}_sq1）
    sub_query_id = f"{query_id}_sq1"

    # 创建子查询（Phase 1: 直接复制 user_query）
    sub_query: SubQueryInfo = {
        "sub_query_id": sub_query_id,
        "query": user_query,  # Phase 1: 直接使用用户原始问题
        "status": "pending",  # 状态：待处理
        "dependencies": [],  # Phase 1: 无依赖
        "validated_sql": None,
        "execution_result": None,
        "error": None,
        "error_type": None,
        "failed_step": None,
        "iteration_count": 0,
    }

    query_logger.info(f"Simple Planner 完成：创建子查询 {sub_query_id}")

    return {
        "sub_queries": [sub_query],  # 使用 reducer，会自动累加到列表
        "current_sub_query_id": sub_query_id,
    }
