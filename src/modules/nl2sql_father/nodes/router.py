"""Router 节点：判定问题复杂度

Router 是父图的第一个节点，负责判断用户问题是 simple 还是 complex。
- simple: 可用一条SQL完成（进入 Fast Path）
- complex: 需要多条SQL或依赖查询（Phase 2 实现）
"""

import time
from typing import Any, Dict

from src.modules.nl2sql_father.state import NL2SQLFatherState
from src.services.config_loader import load_config
from src.services.llm_factory import extract_overrides, get_llm
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("router")

# 配置缓存（模块级别加载一次）
_router_config_cache = None


def _get_router_config() -> Dict[str, Any]:
    """获取 Router 配置（带缓存）

    Returns:
        Router 配置字典
    """
    global _router_config_cache
    if _router_config_cache is None:
        # load_config 接收相对于项目根目录的路径
        config_path = "src/modules/nl2sql_father/config/nl2sql_father_graph.yaml"
        full_config = load_config(config_path)
        _router_config_cache = full_config["router"]
    return _router_config_cache


def router_node(state: NL2SQLFatherState) -> Dict[str, Any]:
    """Router 节点：判定问题复杂度

    职责：
    - 唯一职责：调用 LLM 判定问题是 simple 还是 complex
    - 不做任何数据准备工作（交给对应的 Planner）

    Args:
        state: 父图 State

    Returns:
        更新的 State 字段：
        - complexity: "simple" | "complex"（字符串）
        - router_reason: 判定理由（调试用）
        - router_latency_ms: Router 延迟（毫秒）
        - path_taken: "fast" | "complex"（字符串）
    """
    user_query = state["user_query"]
    query_id = state.get("query_id", "unknown")

    # 日志
    query_logger = with_query_id(logger, query_id)
    query_logger.info("Router 开始判定问题复杂度")

    # 加载配置
    config = _get_router_config()
    default_on_error = config["default_on_error"]
    log_decision = config.get("log_decision", True)

    # 构造提示词
    prompt = f"""你是一个SQL查询复杂度分类器。判断用户问题需要执行几次SQL查询。

分类标准：
- simple: 问题可以通过**一条SQL查询**完成
  * 允许使用多表JOIN（如 INNER JOIN、LEFT JOIN等）
  * 允许使用WITH子查询（CTE，Common Table Expression）
  * 允许使用子查询、UNION、聚合函数等
  * 原则：能用一条SQL解决的，就不拆分成多条SQL

- complex: 问题必须拆分为多次SQL查询才能完成
  * 需要根据第一次查询结果决定后续查询内容
  * 包含多个独立的问题（如："A是多少？B是多少？"）
  * 需要使用临时表存储中间结果

用户问题：{user_query}

    请只输出一个词：simple 或 complex"""

    # 调用 LLM
    start_time = time.time()

    try:
        # DEBUG: 打印完整提示词（由日志级别控制是否可见）
        query_logger.debug("=" * 80)
        query_logger.debug("完整 LLM 提示词（router）:")
        query_logger.debug("=" * 80)
        query_logger.debug(prompt)
        query_logger.debug("=" * 80)

        llm_meta = get_llm(config["llm_profile"], **extract_overrides(config))
        llm = llm_meta.llm

        response = llm.invoke(prompt)
        content = response.content.strip().lower()

        # 归一化输出（注意：返回字符串 "simple" 或 "complex"，非布尔值）
        if "simple" in content:
            complexity = "simple"  # ← 字符串
        elif "complex" in content:
            complexity = "complex"  # ← 字符串
        else:
            # 异常情况：无法识别，使用配置的默认值
            query_logger.warning(f"Router 输出无法识别: {content}，使用默认值: {default_on_error}")
            complexity = default_on_error  # ← 从配置读取（默认 "complex"）

        latency_ms = (time.time() - start_time) * 1000

        # 日志
        if log_decision:
            query_logger.info(
                f"Router 判定完成: complexity={complexity}, latency={latency_ms:.2f}ms"
            )

        return {
            "complexity": complexity,  # "simple" | "complex"（字符串）
            "router_reason": content[:200],  # 保留前200字符（用于调试）
            "router_latency_ms": latency_ms,
            "path_taken": "fast" if complexity == "simple" else "complex",  # "fast" | "complex"（字符串）
        }

    except Exception as e:
        # 失败时使用配置的默认值
        latency_ms = (time.time() - start_time) * 1000
        query_logger.error(f"Router 失败: {str(e)}，使用默认值: {default_on_error}", exc_info=True)

        return {
            "complexity": default_on_error,  # 从配置读取（默认 "complex"）
            "router_reason": f"Router failed: {str(e)}",
            "router_latency_ms": latency_ms,
            "path_taken": "complex" if default_on_error == "complex" else "fast",
        }
