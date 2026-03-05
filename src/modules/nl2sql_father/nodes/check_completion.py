"""Check Completion 节点：完成度检查与循环控制（Phase 2）

Check Completion 是 Complex Path 循环的出口判定节点，负责：
1. 检查是否所有子查询都已完成（completed 或 failed）
2. 最大轮次保护（防止无限循环）
3. 依赖环检测（pending 但无法继续推进）
4. 轮次计数器管理（本节点是唯一递增 current_round 的节点）
5. 返回路由决策（继续循环 or 进入 Summarizer）
"""

from typing import Any, Dict

from src.modules.nl2sql_father.state import NL2SQLFatherState
from src.services.config_loader import load_config
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("check_completion")

# 配置缓存（模块级别加载一次）
_check_completion_config_cache = None


def _get_check_completion_config() -> Dict[str, Any]:
    """获取 Check Completion 配置（带缓存）

    Returns:
        Check Completion 配置字典
    """
    global _check_completion_config_cache
    if _check_completion_config_cache is None:
        # load_config 接收相对于项目根目录的路径
        config_path = "src/modules/nl2sql_father/config/nl2sql_father_graph.yaml"
        full_config = load_config(config_path)
        _check_completion_config_cache = full_config["check_completion"]
    return _check_completion_config_cache


def check_completion_node(state: NL2SQLFatherState) -> Dict[str, Any]:
    """Check Completion 节点：完成度检查与循环控制

    职责：
    1. **完成度检查**：判断是否所有子查询都已完成（completed 或 failed）
    2. **最大轮次保护**：防止无限循环（超过 max_rounds 强制终止）
    3. **依赖环检测**：检测是否有 pending 子查询无法继续推进（依赖环或孤立子查询）
    4. **轮次计数器管理**：本节点是唯一负责递增 current_round 的节点
    5. **路由决策**：返回路由信息（继续循环 or 进入 Summarizer）

    退出条件（3种）：
    - **正常完成**：所有子查询 completed 或 failed
    - **最大轮次**：current_round >= max_rounds（强制终止，标记未完成为 failed）
    - **依赖环**：pending 子查询无法继续推进（标记为 failed）

    Args:
        state: 父图 State

    Returns:
        继续循环时：
        - current_round: 轮次 +1

        结束循环时：
        - {} 空字典（条件边函数根据 all_done 判断路由）
    """
    sub_queries = state.get("sub_queries", [])
    current_round = state.get("current_round", 1)
    max_rounds = state.get("max_rounds", 5)
    query_id = state.get("query_id", "unknown")

    # 日志
    query_logger = with_query_id(logger, query_id)
    query_logger.info(f"Check Completion 开始检查（轮次 {current_round}）")

    # 加载配置
    config = _get_check_completion_config()
    enable_cycle_detection = config.get("enable_cycle_detection", True)
    log_status = config.get("log_status", True)

    # 统计子查询状态
    status_count = {
        "pending": 0,
        "in_progress": 0,
        "completed": 0,
        "failed": 0,
    }

    for sq in sub_queries:
        status = sq.get("status", "pending")
        status_count[status] = status_count.get(status, 0) + 1

    if log_status:
        query_logger.info(
            f"状态统计: pending={status_count['pending']}, "
            f"in_progress={status_count['in_progress']}, "
            f"completed={status_count['completed']}, "
            f"failed={status_count['failed']}"
        )

    # ========== 退出条件 1: 正常完成 ==========
    if status_count["pending"] == 0 and status_count["in_progress"] == 0:
        query_logger.info("所有子查询已完成（completed 或 failed），准备进入 Summarizer")
        return {}  # 返回空字典，路由到 Summarizer

    # ========== 退出条件 2: 最大轮次保护 ==========
    if current_round >= max_rounds:
        query_logger.warning(
            f"已达到最大轮次 {max_rounds}，强制终止，标记未完成子查询为 failed"
        )

        # 标记所有 pending 和 in_progress 为 failed
        for sq in sub_queries:
            if sq.get("status") in ["pending", "in_progress"]:
                sq["status"] = "failed"
                sq["error"] = f"超过最大轮次 {max_rounds}，强制终止"

        return {"sub_queries": sub_queries}  # 显式返回 in-place 修改后的 sub_queries

    # ========== 退出条件 3: 依赖环检测 ==========
    if enable_cycle_detection and status_count["pending"] > 0:
        # 检查是否有 pending 子查询可以继续推进
        completed_ids = {sq["sub_query_id"] for sq in sub_queries if sq.get("status") == "completed"}

        has_ready = False
        for sq in sub_queries:
            if sq.get("status") == "pending":
                dependencies = sq.get("dependencies", [])
                if all(dep_id in completed_ids for dep_id in dependencies):
                    has_ready = True
                    break

        if not has_ready:
            # 所有 pending 子查询都无法继续推进 → 依赖环或孤立子查询
            query_logger.warning("检测到依赖环或孤立子查询，标记为 failed")

            for sq in sub_queries:
                if sq.get("status") == "pending":
                    sq["status"] = "failed"
                    sq["error"] = "依赖环或孤立子查询，无法继续推进"

            return {"sub_queries": sub_queries}  # 显式返回 in-place 修改后的 sub_queries

    # ========== 继续循环：递增轮次 ==========
    next_round = current_round + 1
    query_logger.info(f"继续循环，进入轮次 {next_round}")

    return {"current_round": next_round}
