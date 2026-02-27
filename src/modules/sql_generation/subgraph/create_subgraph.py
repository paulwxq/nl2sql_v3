"""SQL 生成子图编译 - 组装完整的子图"""

import time
import logging
from typing import Literal, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.modules.sql_generation.subgraph.nodes.question_parsing import (
    question_parsing_node,
)
from src.modules.sql_generation.subgraph.nodes.schema_retrieval import (
    schema_retrieval_node,
)
from src.modules.sql_generation.subgraph.nodes.sql_generation import sql_generation_node
from src.modules.sql_generation.subgraph.nodes.validation import validation_node
from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("sql_subgraph")

# ==============================================================================
# 编译图缓存（单例）
# ==============================================================================

_compiled_subgraph: Optional[CompiledStateGraph] = None
_compiled_subgraph_with_checkpoint: bool = False


def should_retry(state: SQLGenerationState) -> Literal["retry", "success", "fail"]:
    """
    判断是否应该重试

    根据验证结果和迭代次数决定流程走向

    Args:
        state: 当前 state

    Returns:
        - "success": 验证通过，成功结束
        - "retry": 验证失败且未超过最大迭代次数，重试
        - "fail": 验证失败且已超过最大迭代次数，失败结束
    """
    # 加载配置
    config = load_subgraph_config("sql_generation")
    max_iterations = config.get("retry", {}).get("max_iterations", 3)

    # 检查是否成功
    if state.get("validated_sql"):
        try:
            query_logger = with_query_id(logger, state.get("query_id", ""))
            query_logger.info("验证通过，流程成功结束")
        except Exception:
            pass
        return "success"

    # 检查是否有不可恢复的错误
    error_type = state.get("error_type")
    if error_type in ("schema_retrieval_failed", "generation_failed"):
        # 这些错误通常不通过重试解决
        try:
            query_logger = with_query_id(logger, state.get("query_id", ""))
            query_logger.error(f"出现不可恢复错误: {error_type}，流程失败结束")
        except Exception:
            pass
        return "fail"

    # 检查迭代次数
    iteration_count = state.get("iteration_count", 0)
    if iteration_count < max_iterations:
        try:
            query_logger = with_query_id(logger, state.get("query_id", ""))
            query_logger.warning(
                f"验证失败，准备重试（第 {iteration_count+1}/{max_iterations} 次）"
            )
        except Exception:
            pass
        return "retry"
    else:
        try:
            query_logger = with_query_id(logger, state.get("query_id", ""))
            query_logger.error("重试次数已达上限，流程失败结束")
        except Exception:
            pass
        return "fail"


def create_sql_generation_subgraph(checkpointer=None) -> CompiledStateGraph:
    """
    创建 SQL 生成子图

    流程：
    START -> schema_retrieval -> sql_generation -> validation
                                      ↑                 |
                                      └─────────────────┘
                                      (重试：validation失败且未超过3次)

    Args:
        checkpointer: 可选的 checkpointer（PostgresSaver 或 SafeCheckpointer）

    Returns:
        编译后的子图（可执行）
    """
    # 创建状态图
    subgraph = StateGraph(SQLGenerationState)

    # 添加节点
    subgraph.add_node("question_parsing", question_parsing_node)
    subgraph.add_node("schema_retrieval", schema_retrieval_node)
    subgraph.add_node("sql_generation", sql_generation_node)
    subgraph.add_node("validation", validation_node)

    # 入口：START -> question_parsing -> schema_retrieval
    subgraph.add_edge(START, "question_parsing")

    def _check_parsing(state: SQLGenerationState) -> str:
        if state.get("error_type") == "parsing_failed":
            return "fail"
        return "continue"

    subgraph.add_conditional_edges(
        "question_parsing",
        _check_parsing,
        {
            "continue": "schema_retrieval",
            "fail": END,
        },
    )

    # 固定边：schema_retrieval -> sql_generation
    subgraph.add_edge("schema_retrieval", "sql_generation")

    # 条件边：sql_generation -> (validation | fail)
    def _route_after_generation(state: SQLGenerationState) -> str:
        # 生成节点三次尝试仍失败会将 error_type 置为 generation_failed
        if state.get("error_type") == "generation_failed":
            return "fail"
        return "to_validation"

    subgraph.add_conditional_edges(
        "sql_generation",
        _route_after_generation,
        {
            "to_validation": "validation",
            "fail": END,
        },
    )

    # 条件边：validation -> (retry/success/fail)
    subgraph.add_conditional_edges(
        "validation",
        should_retry,
        {
            "retry": "sql_generation",  # 验证失败且未超过3次 -> 重试
            "success": END,             # 验证通过 -> 结束
            "fail": END,                # 验证失败且已重试3次 -> 结束
        },
    )

    # 编译子图
    if checkpointer is not None:
        compiled = subgraph.compile(checkpointer=checkpointer)
        logger.debug("SQL 生成子图已编译完成（已启用 Checkpoint）")
    else:
        compiled = subgraph.compile()
        logger.debug("SQL 生成子图已编译完成")

    return compiled


def get_compiled_subgraph() -> CompiledStateGraph:
    """获取编译后的子图（带缓存）

    根据 checkpoint 开关状态决定是否传入 checkpointer。
    使用模块级缓存避免每次请求都重新编译。

    缓存策略：
        - 按"配置意图"缓存，而非"实际是否有 checkpointer"
        - 如果 checkpoint 启用但 saver 创建失败，会缓存无 checkpointer 的图
        - DB 恢复后不会自动重试，需要调用 reset_subgraph_cache() 或重启应用

    Returns:
        编译后的子图
    """
    global _compiled_subgraph, _compiled_subgraph_with_checkpoint

    from src.services.langgraph_persistence.postgres import (
        get_postgres_saver,
        is_checkpoint_enabled,
    )
    from src.services.langgraph_persistence.safe_checkpointer import SafeCheckpointer

    # 检查当前 checkpoint 开关状态（配置意图）
    checkpoint_enabled = is_checkpoint_enabled()

    # 如果缓存存在且配置意图一致，直接返回（避免重复编译）
    # 注意：即使 saver 创建失败，只要配置意图不变就复用缓存
    if _compiled_subgraph is not None and _compiled_subgraph_with_checkpoint == checkpoint_enabled:
        return _compiled_subgraph

    # 需要重新编译
    checkpointer = None
    if checkpoint_enabled:
        real_checkpointer = get_postgres_saver("subgraph")
        if real_checkpointer is not None:
            # 使用 SafeCheckpointer 包装，实现 fail-open
            checkpointer = SafeCheckpointer(real_checkpointer, enabled=True)
            logger.info("子图使用 SafeCheckpointer（fail-open 模式）")
        else:
            logger.warning("Checkpoint 已启用但 PostgresSaver 创建失败，子图将不使用 checkpointer")

    _compiled_subgraph = create_sql_generation_subgraph(checkpointer=checkpointer)
    # 记录"配置意图"，用于缓存判断（避免 saver 创建失败时每次重新编译）
    _compiled_subgraph_with_checkpoint = checkpoint_enabled

    return _compiled_subgraph


def reset_subgraph_cache():
    """重置子图编译缓存

    使用场景：
        1. 单元测试：在 setup/teardown 中调用，确保测试隔离
        2. DB 恢复重试：如果 checkpoint 启用但 saver 创建失败，
           DB 恢复后调用此函数可触发重新编译挂载 checkpointer
    """
    global _compiled_subgraph, _compiled_subgraph_with_checkpoint
    _compiled_subgraph = None
    _compiled_subgraph_with_checkpoint = False


# 便捷函数：运行子图

def run_sql_generation_subgraph(
    query: str,
    query_id: str,
    user_query: str,
    dependencies_results: dict = None,
    parse_hints: dict = None,
    *,
    sub_query_id: str | None = None,
    thread_id: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> dict:
    """
    运行 SQL 生成子图（便捷函数）

    Args:
        query: 子查询文本
        query_id: 查询ID
        user_query: 用户原始查询
        dependencies_results: 依赖查询结果
        parse_hints: 解析提示
        sub_query_id: 子查询ID（用于 checkpoint_ns 隔离，新增）
        thread_id: 会话ID（从父图透传，新增）

    Returns:
        子图输出字典
    """
    from src.services.langgraph_persistence.postgres import (
        get_checkpoint_namespace,
        is_checkpoint_enabled,
    )

    # 获取编译后的子图（带缓存，自动处理 checkpoint）
    subgraph = get_compiled_subgraph()

    # 准备输入
    initial_state = {
        "messages": [],
        "query": query,
        "query_id": query_id,
        "thread_id": thread_id,
        "user_query": user_query,
        "dependencies_results": dependencies_results or {},
        "parse_hints": parse_hints,
        "conversation_history": conversation_history,
        "iteration_count": 0,
        "validation_history": [],
    }

    # 记录开始时间
    start_time = time.time()

    query_logger = with_query_id(logger, query_id)
    query_logger.info("开始执行 SQL 生成子图")
    logger.debug(f"初始状态准备完成: keys={list(initial_state.keys())}")

    # 构建 invoke 配置（checkpoint 需要 thread_id 和 checkpoint_ns）
    # 注意：这里按"配置意图"而非"实际挂载状态"判断
    # 如果 saver 创建失败导致图没有 checkpointer，传递这些参数是无害的，LangGraph 会忽略
    invoke_config = None
    if is_checkpoint_enabled() and thread_id:
        subgraph_namespace = get_checkpoint_namespace("subgraph")
        # checkpoint_ns 使用 {subgraph_namespace}:{sub_query_id} 隔离
        checkpoint_ns = f"{subgraph_namespace}:{sub_query_id or query_id}"
        invoke_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
            }
        }
        query_logger.debug(f"子图 Checkpoint 已启用: namespace={checkpoint_ns}")

    # 运行子图（invoke_config 为 None 时不传 config 参数，使用默认值）
    if invoke_config is not None:
        final_state = subgraph.invoke(initial_state, config=invoke_config)
    else:
        final_state = subgraph.invoke(initial_state)

    # 打印最终 State 快照（不依赖 checkpoint，DEBUG 级别；始终可用，由日志级别控制是否可见）
    try:
        import json
        snapshot = {}
        for k, v in final_state.items():
            if k == "messages":
                snapshot["messages_count"] = len(v) if isinstance(v, list) else 0
                continue
            snapshot[k] = v
        query_logger.debug("========== 最终 State 快照 ==========")
        query_logger.debug(json.dumps(snapshot, ensure_ascii=False, indent=2))
        query_logger.debug("====================================")
    except Exception as exc:
        query_logger.warning(f"打印最终 State 快照失败: {exc}")

    # 记录结束时间
    execution_time = time.time() - start_time
    final_state["execution_time"] = execution_time

    # 提取输出
    from src.modules.sql_generation.subgraph.state import extract_output
    output = extract_output(final_state)

    query_logger.info(f"子图执行完成，耗时 {execution_time:.2f}秒")

    return output
