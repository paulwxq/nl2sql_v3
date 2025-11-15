"""SQL 执行节点：执行验证通过的 SQL

从 sub_queries 中收集待执行的 SQL，调用数据库执行，返回规范化结果。
"""

import os
import time
from typing import Any, Dict, List

from src.modules.nl2sql_father.state import NL2SQLFatherState, SQLExecutionResult
from src.services.config_loader import load_config
from src.services.db.pg_client import PGClient
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("sql_execution")

# 配置缓存（模块级别加载一次）
_sql_exec_config_cache = None


def _get_sql_execution_config() -> Dict[str, Any]:
    """获取 SQL 执行配置（带缓存）

    Returns:
        SQL 执行配置字典
    """
    global _sql_exec_config_cache
    if _sql_exec_config_cache is None:
        # load_config 接收相对于项目根目录的路径
        config_path = "src/modules/nl2sql_father/config/nl2sql_father_graph.yaml"
        full_config = load_config(config_path)
        _sql_exec_config_cache = full_config["sql_execution"]
    return _sql_exec_config_cache


def sql_execution_node(state: NL2SQLFatherState, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """SQL 执行节点（两路复用）

    职责：
    1. 从 sub_queries 中收集所有状态为 completed 且有 validated_sql 的子查询
    2. 串行/并行执行 SQL（Phase 1：串行）
    3. 规范化输出为 SQLExecutionResult 列表
    4. 更新 sub_queries 中的 execution_result（双向绑定）

    Args:
        state: 父图 State
        config: 运行时配置（可选，暂未使用）

    Returns:
        更新的 State 字段：
        - execution_results: SQL 执行结果列表
    """
    query_logger = with_query_id(logger, state.get("query_id", "unknown"))

    # 加载配置
    exec_config = _get_sql_execution_config()
    timeout_per_sql = exec_config["timeout_per_sql"]
    max_rows = exec_config["max_rows_per_query"]  # Phase 2 预留：当前版本暂未实现结果截断
    log_sql = exec_config["log_sql"]

    # 1. 从 sub_queries 中收集待执行 SQL
    sub_queries = state.get("sub_queries", [])
    sqls_to_execute = []
    sub_query_map = {}  # 用于映射：sub_query_id -> sub_query

    for sq in sub_queries:
        if sq.get("status") == "completed" and sq.get("validated_sql"):
            sql_item = {"sub_query_id": sq["sub_query_id"], "sql": sq["validated_sql"]}
            sqls_to_execute.append(sql_item)
            sub_query_map[sq["sub_query_id"]] = sq

    if not sqls_to_execute:
        query_logger.warning("没有待执行的SQL")
        return {"execution_results": []}

    if log_sql:
        query_logger.info(f"准备执行 {len(sqls_to_execute)} 条SQL")

    # 2. 执行 SQL（Phase 1：串行）
    results: List[SQLExecutionResult] = []
    pg_client = PGClient()

    for idx, sql_item in enumerate(sqls_to_execute, 1):
        sub_query_id = sql_item["sub_query_id"]
        sql = sql_item["sql"]

        if log_sql:
            query_logger.info(f"执行第 {idx}/{len(sqls_to_execute)} 条SQL (sub_query_id: {sub_query_id})")
        start_time = time.time()

        try:
            # 执行SQL
            result = pg_client.execute_query(sql, timeout=timeout_per_sql)
            execution_time_ms = (time.time() - start_time) * 1000

            exec_result: SQLExecutionResult = {
                "sub_query_id": sub_query_id,  # 携带 sub_query_id
                "sql": sql,
                "success": True,
                "columns": result.get("columns"),
                "rows": result.get("rows"),
                "row_count": len(result.get("rows", [])),
                "execution_time_ms": execution_time_ms,
                "error": None,
            }
            results.append(exec_result)

            # 更新 sub_query 的 execution_result（双向绑定）
            if sub_query_id in sub_query_map:
                sub_query_map[sub_query_id]["execution_result"] = exec_result

            if log_sql:
                query_logger.info(
                    f"SQL执行成功，返回 {len(result.get('rows', []))} 行，耗时 {execution_time_ms:.0f}ms"
                )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)

            exec_result: SQLExecutionResult = {
                "sub_query_id": sub_query_id,  # 携带 sub_query_id
                "sql": sql,
                "success": False,
                "columns": None,
                "rows": None,
                "row_count": 0,
                "execution_time_ms": execution_time_ms,
                "error": error_msg,
            }
            results.append(exec_result)

            # 更新 sub_query 的 execution_result（双向绑定）
            if sub_query_id in sub_query_map:
                sub_query_map[sub_query_id]["execution_result"] = exec_result

            query_logger.error(f"SQL执行失败: {error_msg}")

    return {"execution_results": results}
