"""SQL 执行节点：执行验证通过的 SQL

从 sub_queries 中收集待执行的 SQL，调用数据库执行，返回规范化结果。

兼容设计：
- Phase 1 (Fast Path): 串行执行 1 条 SQL（status=completed）
- Phase 2 (Complex Path): 并发执行多条 SQL（status=in_progress）
- 自动检测模式，避免重复执行
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _execute_single_sql(
    sql_item: Dict[str, str],
    pg_client,
    timeout: int,
    idx: int,
    total: int,
    query_logger,
    log_results: bool = False,
    max_log_rows: int = 3,
) -> SQLExecutionResult:
    """执行单条 SQL（串行和并发模式复用）

    Args:
        sql_item: 包含 sub_query_id 和 sql 的字典
        pg_client: 共享的 PGClient 实例（连接复用）
        timeout: 超时时间（秒）
        idx: 当前 SQL 索引（从 1 开始）
        total: SQL 总数
        query_logger: 日志记录器

    Returns:
        SQLExecutionResult: 规范化的执行结果
    """
    sub_query_id = sql_item["sub_query_id"]
    sql = sql_item["sql"]

    # 记录执行进度
    query_logger.info(f"执行第 {idx}/{total} 条SQL (sub_query_id: {sub_query_id})")
    start_time = time.time()

    try:
        # 执行SQL（使用共享的 pg_client 实例）
        result = pg_client.execute_query(sql, timeout=timeout)
        execution_time_ms = (time.time() - start_time) * 1000

        exec_result: SQLExecutionResult = {
            "sub_query_id": sub_query_id,
            "sql": sql,
            "success": True,
            "columns": result.get("columns"),
            "rows": result.get("rows"),
            "row_count": len(result.get("rows", [])),
            "execution_time_ms": execution_time_ms,
            "error": None,
        }
        query_logger.info(
            f"SQL执行成功，返回 {len(result.get('rows', []))} 行，耗时 {execution_time_ms:.0f}ms"
        )
        
        # 记录执行结果详情
        if log_results and result.get('rows'):
            display_rows = result.get('rows')[:max_log_rows]
            query_logger.debug(f"执行结果（前{max_log_rows}行）: {display_rows}")
        
        return exec_result

    except Exception as e:
        execution_time_ms = (time.time() - start_time) * 1000
        error_msg = str(e)

        exec_result: SQLExecutionResult = {
            "sub_query_id": sub_query_id,
            "sql": sql,
            "success": False,
            "columns": None,
            "rows": None,
            "row_count": 0,
            "execution_time_ms": execution_time_ms,
            "error": error_msg,
        }
        query_logger.error(f"SQL执行失败 ({sub_query_id}): {error_msg}")
        return exec_result


def sql_execution_node(state: NL2SQLFatherState, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """SQL 执行节点（Phase 1 + Phase 2 共享，增强版）

    职责：
    1. 从 sub_queries 中收集待执行 SQL（支持 Phase 1 和 Phase 2）
    2. 串行/并发执行 SQL（自动检测模式）
    3. 规范化输出为 SQLExecutionResult 列表
    4. 更新 sub_queries 中的 execution_result 和 status

    兼容设计：
    - Phase 1: 收集 status=completed（SQL生成成功后），串行执行 1 条
    - Phase 2: 收集 status=in_progress（依赖注入后），并发执行多条
    - 避免重复执行：跳过已有 execution_result 的子查询
    - 自动检测：len(sqls) > 1 and enable_parallel → 并发，否则串行

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
    max_concurrency = exec_config.get("max_concurrency", 1)
    enable_parallel = exec_config.get("enable_parallel", False)
    log_sql = exec_config.get("log_sql", True)
    log_results = exec_config.get("log_results", False)
    max_log_rows = exec_config.get("max_log_rows", 3)

    # 1. 从 sub_queries 中收集待执行 SQL
    sub_queries = state.get("sub_queries", [])
    sqls_to_execute = []
    sub_query_map = {}  # 用于映射：sub_query_id -> sub_query

    for sq in sub_queries:
        # 跳过已执行的子查询（避免 Phase 2 循环中重复执行）
        if sq.get("execution_result") is not None:
            continue

        # 收集待执行的 SQL：
        # - Phase 1 (Fast Path): status=completed（SQL 生成成功后的状态）
        # - Phase 2 (Complex Path): status=in_progress（Inject Params 注入依赖后的状态）
        if sq.get("status") in ["completed", "in_progress"] and sq.get("validated_sql"):
            sql_item = {"sub_query_id": sq["sub_query_id"], "sql": sq["validated_sql"]}
            sqls_to_execute.append(sql_item)
            sub_query_map[sq["sub_query_id"]] = sq

    if not sqls_to_execute:
        query_logger.warning("没有待执行的SQL")
        # 直接返回非空必须字段，省略 execution_results 和 sub_queries 
        # 会被 LangGraph 自动保留原有值，且不触发 blob 写入
        return {
            "parallel_execution_count": state.get("parallel_execution_count") or 0,
        }

    if log_sql:
        query_logger.info(f"准备执行 {len(sqls_to_execute)} 条SQL")

    # 保留已有的执行结果（覆盖模式下需要手动拼接，替代原 add reducer）
    existing_results = state.get("execution_results", [])

    # 2. 执行 SQL（自动检测：串行 or 并发）
    results: List[SQLExecutionResult] = []
    pg_client = PGClient()  # 创建共享的 PGClient 实例（连接池是线程安全的）

    # 判断执行模式
    use_parallel = len(sqls_to_execute) > 1 and enable_parallel

    if use_parallel:
        # ========== 并发执行模式（Phase 2） ==========
        query_logger.info(f"使用并发执行模式（max_concurrency={max_concurrency}）")

        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            # 提交所有任务
            future_to_sql = {
                executor.submit(
                    _execute_single_sql,
                    sql_item,
                    pg_client,
                    timeout_per_sql,
                    idx,
                    len(sqls_to_execute),
                    query_logger,
                    log_results,
                    max_log_rows,
                ): sql_item
                for idx, sql_item in enumerate(sqls_to_execute, 1)
            }

            # 收集结果（按完成顺序）
            for future in as_completed(future_to_sql):
                sql_item = future_to_sql[future]
                try:
                    exec_result = future.result()
                    results.append(exec_result)

                    # 更新 sub_query
                    sub_query_id = exec_result["sub_query_id"]
                    if sub_query_id in sub_query_map:
                        sq = sub_query_map[sub_query_id]
                        sq["execution_result"] = exec_result
                        # Phase 2: 根据执行结果设置状态（成功 → completed，失败 → failed）
                        sq["status"] = "completed" if exec_result["success"] else "failed"

                    if log_sql:
                        query_logger.info(
                            f"SQL执行完成 ({sub_query_id}): "
                            f"success={exec_result['success']}, "
                            f"rows={exec_result['row_count']}, "
                            f"time={exec_result['execution_time_ms']:.0f}ms"
                        )

                except Exception as e:
                    query_logger.error(f"并发执行任务失败: {str(e)}", exc_info=True)

    else:
        # ========== 串行执行模式（Phase 1 or Phase 2 单条） ==========
        for idx, sql_item in enumerate(sqls_to_execute, 1):
            exec_result = _execute_single_sql(
                sql_item, pg_client, timeout_per_sql, idx, len(sqls_to_execute), query_logger,
                log_results, max_log_rows
            )
            results.append(exec_result)

            # 更新 sub_query
            sub_query_id = exec_result["sub_query_id"]
            if sub_query_id in sub_query_map:
                sq = sub_query_map[sub_query_id]
                sq["execution_result"] = exec_result
                # Phase 2: 根据执行结果设置状态（成功 → completed，失败 → failed）
                sq["status"] = "completed" if exec_result["success"] else "failed"

    # 记录全局最大并发数（Phase 2 监控指标）
    # 取本轮并发数与历史最大值的较大者，避免被后续串行轮次覆盖
    current_parallel_count = len(sqls_to_execute) if use_parallel else 0
    previous_count = state.get("parallel_execution_count") or 0  # None 转为 0
    max_parallel_count = max(previous_count, current_parallel_count)

    return {
        "execution_results": existing_results + results,
        "sub_queries": state.get("sub_queries", []),
        "parallel_execution_count": max_parallel_count,
    }
