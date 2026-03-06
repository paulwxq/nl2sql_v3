"""Planner 节点：复杂问题拆分与依赖建立（Phase 2）

Planner 是 Complex Path 的第一个节点，负责：
1. 将复杂问题拆分为 2-5 个子查询
2. 建立子查询之间的依赖关系
3. 构建依赖图结构（用于环检测和API诊断）
4. 初始化循环控制变量（current_round=1, max_rounds）
"""

import json
import time
from collections import defaultdict
from typing import Any, Dict, List

from langchain_community.chat_models import ChatTongyi

from src.modules.nl2sql_father.state import NL2SQLFatherState, SubQueryInfo
from src.services.config_loader import load_config
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("planner")

# 配置缓存（模块级别加载一次）
_planner_config_cache = None


def _get_planner_config() -> Dict[str, Any]:
    """获取 Planner 配置（带缓存）

    Returns:
        Planner 配置字典
    """
    global _planner_config_cache
    if _planner_config_cache is None:
        # load_config 接收相对于项目根目录的路径
        config_path = "src/modules/nl2sql_father/config/nl2sql_father_graph.yaml"
        full_config = load_config(config_path)
        _planner_config_cache = full_config["planner"]
    return _planner_config_cache


# ==================== 提示词模板 ====================

PLANNER_PROMPT = """你是一个 SQL 查询规划专家。用户提出了一个复杂问题，需要拆分为多个步骤执行。

## 任务
将用户问题拆分为 2-5 个子查询，并建立依赖关系。

## 输出格式（严格 JSON）
{{
  "sub_queries": [
    {{
      "sub_query_id": "sq1",
      "query": "第一步要查询的问题",
      "dependencies": []
    }},
    {{
      "sub_query_id": "sq2",
      "query": "第二步要查询的问题（可以引用 {{{{sq1.result}}}}）",
      "dependencies": ["sq1"]
    }}
  ]
}}

## 规则
1. **子查询数量**：2-5 个（不能超过5个）
2. **依赖语法**：使用 `{{{{sq_id.result}}}}` 引用其他子查询结果（注意双层花括号）
3. **依赖关系**：dependencies 数组列出所有依赖的子查询ID
4. **查询独立性**：每个子查询应该是一个独立的问题，可以生成单独的 SQL
5. **ID规范**：sub_query_id 使用 sq1, sq2, sq3...（按顺序编号）
6. **无环约束**：不能有循环依赖（例如：sq1依赖sq2，sq2又依赖sq1）
7. **冲突处理**：当“对话历史”与“当前问题”矛盾时，以“当前问题”为准，不要被历史带偏。

## 示例

**用户问题**：哪个服务区销售额最高？它的地址和公司是什么？

**输出**：
{{
  "sub_queries": [
    {{
      "sub_query_id": "sq1",
      "query": "找出销售额最高的服务区ID",
      "dependencies": []
    }},
    {{
      "sub_query_id": "sq2",
      "query": "查询服务区 {{{{sq1.result}}}} 的地址和所属公司",
      "dependencies": ["sq1"]
    }}
  ]
}}

## 用户问题
{user_query}

请严格按照 JSON 格式输出，不要包含任何其他文字。"""


def _format_conversation_history(conversation_history: Any) -> str:
    if not conversation_history:
        return ""

    lines: List[str] = ["## 对话历史（旧→新，仅供指代消解）"]
    for i, turn in enumerate(conversation_history, start=1):
        if not isinstance(turn, dict):
            continue
        q = (turn.get("question") or "").strip()
        a = (turn.get("answer") or "").strip()
        if not q and not a:
            continue
        lines.append(f"{i}. Q: {q}")
        lines.append(f"   A: {a}")
    lines.append("")
    return "\n".join(lines)


# ==================== 依赖图构建与环检测 ====================


def _build_dependency_graph(sub_queries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构建依赖图结构

    Args:
        sub_queries: 子查询列表

    Returns:
        依赖图字典：
        {
            "nodes": ["sq1", "sq2", "sq3"],
            "edges": [
                {"from": "sq1", "to": "sq2"},
                {"from": "sq1", "to": "sq3"}
            ]
        }
    """
    nodes = [sq["sub_query_id"] for sq in sub_queries]
    edges = []

    for sq in sub_queries:
        sub_query_id = sq["sub_query_id"]
        dependencies = sq.get("dependencies", [])

        for dep_id in dependencies:
            # 边的方向：from=依赖的子查询，to=当前子查询
            edges.append({"from": dep_id, "to": sub_query_id})

    return {"nodes": nodes, "edges": edges}


def _has_cycle(dependency_graph: Dict[str, Any]) -> bool:
    """检测依赖图中是否存在环（使用 DFS）

    Args:
        dependency_graph: 依赖图结构

    Returns:
        True 表示有环，False 表示无环
    """
    nodes = dependency_graph["nodes"]
    edges = dependency_graph["edges"]

    # 构建邻接表
    adj = defaultdict(list)
    for edge in edges:
        adj[edge["from"]].append(edge["to"])

    # DFS 检测环
    visited = set()
    rec_stack = set()  # 递归栈，用于检测环

    def dfs(node):
        visited.add(node)
        rec_stack.add(node)

        for neighbor in adj[node]:
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # 发现环
                return True

        rec_stack.remove(node)
        return False

    # 对所有节点执行 DFS
    for node in nodes:
        if node not in visited:
            if dfs(node):
                return True

    return False


# ==================== Planner 节点 ====================


def planner_node(state: NL2SQLFatherState) -> Dict[str, Any]:
    """Planner 节点：复杂问题拆分与依赖建立

    职责：
    1. 调用 LLM 将复杂问题拆分为 2-5 个子查询
    2. 解析 LLM 输出，提取子查询和依赖关系
    3. 构建依赖图并检测环
    4. 初始化子查询列表（status=pending）
    5. 初始化循环控制变量（current_round=1, max_rounds）

    Args:
        state: 父图 State

    Returns:
        更新的 State 字段：
        - sub_queries: 子查询列表（SubQueryInfo）
        - dependency_graph: 依赖图结构
        - current_round: 1（初始轮次）
        - max_rounds: 从配置读取（默认5）
        - path_taken: "complex"

        失败时返回：
        - error: 错误信息
        - error_type: "planning_failed"
    """
    user_query = state["user_query"]
    query_id = state.get("query_id", "unknown")

    # 日志
    query_logger = with_query_id(logger, query_id)
    query_logger.info("Planner 开始拆分复杂问题")

    # 加载配置
    config = _get_planner_config()
    model_name = config["model"]
    temperature = config["temperature"]
    timeout = config["timeout"]
    max_sub_queries = config["max_sub_queries"]
    min_sub_queries = config["min_sub_queries"]
    max_rounds = config["max_rounds"]
    log_plan = config.get("log_plan", True)

    # 构造提示词
    history_block = _format_conversation_history(state.get("conversation_history"))
    prompt = (
        history_block
        + PLANNER_PROMPT.format(user_query=user_query)
    )

    # 调用 LLM
    start_time = time.time()

    try:
        # DEBUG: 打印完整提示词（由日志级别控制是否可见）
        query_logger.debug("=" * 80)
        query_logger.debug("完整 LLM 提示词（planner）:")
        query_logger.debug("=" * 80)
        query_logger.debug(prompt)
        query_logger.debug("=" * 80)

        llm = ChatTongyi(
            model=model_name,
            temperature=temperature,
            timeout=timeout,
        )

        response = llm.invoke(prompt)
        content = response.content.strip()

        # 解析 JSON
        try:
            # 提取 JSON（移除可能的 markdown 代码块标记）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            plan_data = json.loads(content)
            sub_queries_raw = plan_data.get("sub_queries", [])

        except json.JSONDecodeError as e:
            latency_ms = (time.time() - start_time) * 1000
            query_logger.error(f"Planner JSON 解析失败: {str(e)}\n原始输出: {content[:500]}")
            return {
                "error": "Planner 输出格式错误，无法解析 JSON",
                "error_type": "planning_failed",
                "path_taken": "complex",
                "planner_latency_ms": latency_ms,
            }

        # 验证子查询数量
        if len(sub_queries_raw) < min_sub_queries:
            latency_ms = (time.time() - start_time) * 1000
            query_logger.error(f"子查询数量不足: {len(sub_queries_raw)} < {min_sub_queries}")
            return {
                "error": f"复杂问题至少需要 {min_sub_queries} 个子查询",
                "error_type": "planning_failed",
                "path_taken": "complex",
                "planner_latency_ms": latency_ms,
            }

        if len(sub_queries_raw) > max_sub_queries:
            query_logger.warning(f"子查询数量超过限制: {len(sub_queries_raw)} > {max_sub_queries}，截断到 {max_sub_queries} 个")
            sub_queries_raw = sub_queries_raw[:max_sub_queries]

        # 构建 SubQueryInfo 列表
        sub_queries: List[SubQueryInfo] = []
        for idx, sq_raw in enumerate(sub_queries_raw, 1):
            sub_query_id = sq_raw.get("sub_query_id", f"sq{idx}")
            # 规范化 sub_query_id（添加 query_id 前缀，确保全局唯一）
            full_sub_query_id = f"{query_id}_{sub_query_id}"

            sub_query_info: SubQueryInfo = {
                "sub_query_id": full_sub_query_id,
                "query": sq_raw.get("query", ""),
                "status": "pending",
                "dependencies": [
                    f"{query_id}_{dep_id}" for dep_id in sq_raw.get("dependencies", [])
                ],  # 依赖也要加前缀
                "validated_sql": None,
                "execution_result": None,
                "error": None,
                "error_type": None,
                "failed_step": None,
                "iteration_count": 0,
                "dependencies_results": None,  # Phase 2: 初始化为 None
            }
            sub_queries.append(sub_query_info)

        # 构建依赖图
        dependency_graph = _build_dependency_graph(sub_queries)

        # 环检测
        if _has_cycle(dependency_graph):
            latency_ms = (time.time() - start_time) * 1000
            query_logger.error("检测到依赖环，无法执行")
            return {
                "error": "子查询之间存在循环依赖，无法执行",
                "error_type": "planning_failed",
                "path_taken": "complex",
                "planner_latency_ms": latency_ms,
            }

        # 日志
        latency_ms = (time.time() - start_time) * 1000
        if log_plan:
            query_logger.info(
                f"Planner 完成: 拆分为 {len(sub_queries)} 个子查询，"
                f"依赖边数={len(dependency_graph['edges'])}，耗时={latency_ms:.0f}ms"
            )
            for sq in sub_queries:
                query_logger.debug(f"  - {sq['sub_query_id']}: {sq['query'][:50]}... (deps={sq['dependencies']})")

        # 返回结果
        return {
            "sub_queries": sub_queries,
            "dependency_graph": dependency_graph,
            "current_round": 1,  # 初始化轮次
            "max_rounds": max_rounds,  # 从配置读取
            "path_taken": "complex",
            "planner_latency_ms": latency_ms,  # Phase 2 监控指标
        }

    except Exception as e:
        # 兜底：LLM 调用失败
        latency_ms = (time.time() - start_time) * 1000
        query_logger.error(f"Planner 异常: {str(e)}，耗时={latency_ms:.0f}ms", exc_info=True)

        return {
            "error": f"Planner 执行失败: {str(e)}",
            "error_type": "planning_failed",
            "path_taken": "complex",
            "planner_latency_ms": latency_ms,  # Phase 2 监控指标（失败时也记录）
        }
