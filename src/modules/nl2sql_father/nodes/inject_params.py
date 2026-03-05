"""Inject Params 节点：依赖解析与参数注入（Phase 2）

Inject Params 是 Complex Path 循环的入口节点，负责：
1. 检查哪些子查询的依赖已经满足
2. 从已完成的子查询中提取执行结果
3. 将依赖结果注入到待执行子查询的 dependencies_results 字段
4. 更新子查询状态：pending → in_progress
5. 返回当前批次待执行的子查询ID列表
"""

from typing import Any, Dict

from src.modules.nl2sql_father.state import NL2SQLFatherState
from src.services.config_loader import load_config
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("inject_params")

# 配置缓存（模块级别加载一次）
_inject_params_config_cache = None


def _get_inject_params_config() -> Dict[str, Any]:
    """获取 Inject Params 配置（带缓存）

    Returns:
        Inject Params 配置字典
    """
    global _inject_params_config_cache
    if _inject_params_config_cache is None:
        # load_config 接收相对于项目根目录的路径
        config_path = "src/modules/nl2sql_father/config/nl2sql_father_graph.yaml"
        full_config = load_config(config_path)
        _inject_params_config_cache = full_config["inject_params"]
    return _inject_params_config_cache


def inject_params_node(state: NL2SQLFatherState) -> Dict[str, Any]:
    """Inject Params 节点：依赖解析与参数注入

    职责：
    1. **依赖检查**：找出所有依赖已满足的子查询（status=pending）
    2. **结果提取**：从已完成子查询的 execution_result 提取结果
    3. **参数注入**：填充待执行子查询的 dependencies_results 字典
    4. **状态更新**：将待执行子查询状态改为 in_progress
    5. **批量准备**：返回当前批次待执行的子查询ID列表

    注意事项：
    - 本节点不修改子查询的 query 字段（占位符 {{sq_id.result}} 保持不变）
    - Phase 2 采用"简单传递"策略，直接传递完整的 execution_result
    - current_round 由 Check Completion 节点统一管理和递增

    Args:
        state: 父图 State

    Returns:
        更新的 State 字段：
        - current_batch_ids: 当前轮次待执行的子查询ID列表

        失败时返回空列表（允许系统优雅退出）
    """
    sub_queries = state.get("sub_queries", [])
    current_round = state.get("current_round", 1)
    query_id = state.get("query_id", "unknown")

    # 日志
    query_logger = with_query_id(logger, query_id)
    query_logger.info(f"Inject Params 开始处理（轮次 {current_round}）")

    # 加载配置
    config = _get_inject_params_config()
    log_injection = config.get("log_injection", True)

    # 1. 找出所有已完成的子查询（用于依赖检查）
    completed_ids = set()
    for sq in sub_queries:
        if sq.get("status") == "completed":
            completed_ids.add(sq["sub_query_id"])

    if log_injection:
        query_logger.debug(f"已完成子查询: {completed_ids}")

    # 2. 找出依赖已满足的子查询（status=pending）
    ready_to_execute = []
    for sq in sub_queries:
        if sq.get("status") != "pending":
            continue  # 只处理 pending 状态的子查询

        dependencies = sq.get("dependencies", [])

        # 检查所有依赖是否都已完成
        if all(dep_id in completed_ids for dep_id in dependencies):
            ready_to_execute.append(sq)

    if log_injection:
        query_logger.info(f"找到 {len(ready_to_execute)} 个依赖已满足的子查询")

    # 3. 为每个待执行子查询注入依赖结果
    batch_ids = []
    for sq in ready_to_execute:
        sub_query_id = sq["sub_query_id"]
        dependencies = sq.get("dependencies", [])

        # 构建 dependencies_results 字典
        dependencies_results = {}
        for dep_id in dependencies:
            # 找到依赖的子查询
            dep_sq = next((s for s in sub_queries if s["sub_query_id"] == dep_id), None)
            if dep_sq and dep_sq.get("execution_result"):
                # Phase 2: 新格式 - 包含 question 和完整的 execution_result
                dependencies_results[dep_id] = {
                    "question": dep_sq["query"],
                    "execution_result": dep_sq["execution_result"]
                }

        # 更新子查询
        sq["dependencies_results"] = dependencies_results
        sq["status"] = "in_progress"
        batch_ids.append(sub_query_id)

        if log_injection:
            query_logger.debug(
                f"  - {sub_query_id}: 注入 {len(dependencies_results)} 个依赖结果"
            )

    # 日志总结
    if log_injection:
        query_logger.info(f"Inject Params 完成：准备执行 {len(batch_ids)} 个子查询")

    # 4. 返回当前批次ID列表（显式返回 sub_queries 以确保 in-place 修改被持久化）
    return {"current_batch_ids": batch_ids, "sub_queries": state.get("sub_queries", [])}
