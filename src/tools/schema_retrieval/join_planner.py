"""JOIN 路径规划算法 - 纯函数工具"""

from typing import Any, Dict, List, Optional


def build_join_plans(
    base_tables: List[str],
    all_tables: List[str],
    neo4j_client,
    max_hops: int = 5,
    strategy: str = "apoc_dijkstra",
) -> List[Dict[str, Any]]:
    """
    为多个 Base 表构建 JOIN 计划

    Args:
        base_tables: Base 表列表（事实表）
        all_tables: 所有候选表列表
        neo4j_client: Neo4j 客户端实例
        max_hops: 最大跳数
        strategy: 路径查找策略

    Returns:
        JOIN 计划列表，每个元素对应一个 Base 表
    """
    join_plans = []

    for base in base_tables:
        # 其他表作为 targets
        targets = [t for t in all_tables if t != base]

        if not targets:
            continue

        # 调用 Neo4j 客户端规划路径
        plans = neo4j_client.plan_join_paths(
            base_tables=[base],
            target_tables=targets,
            max_hops=max_hops,
            strategy=strategy,
        )

        # 添加到结果
        if plans and plans[0].get("edges"):
            join_plans.append(plans[0])

    return join_plans


def merge_join_edges(join_plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    合并多个 JOIN 计划的边（去重）

    Args:
        join_plans: JOIN 计划列表

    Returns:
        去重后的边列表
    """
    all_edges = []
    seen_edges = set()

    for plan in join_plans:
        for edge in plan.get("edges", []):
            # 使用 (src, dst, on) 作为唯一标识
            edge_key = (
                edge["src_table"],
                edge["dst_table"],
                edge.get("on"),
            )

            if edge_key not in seen_edges:
                all_edges.append(edge)
                seen_edges.add(edge_key)

    return all_edges


def format_join_plan_for_prompt(join_plans: List[Dict[str, Any]]) -> str:
    """
    格式化 JOIN 计划为提示词文本

    Args:
        join_plans: JOIN 计划列表

    Returns:
        格式化后的文本，用于插入到 LLM 提示词
    """
    if not join_plans:
        return "（无JOIN，单表查询）"

    segments = []

    for idx, plan in enumerate(join_plans[:3], 1):  # 最多显示3个计划
        base_table = plan.get("base", "")
        lines = [f"Base #{idx}：**{base_table}**"]

        for edge in plan.get("edges", []):
            on_clause = edge.get("on", "<missing on>")
            join_type = edge.get("join_type", "INNER JOIN")
            card = edge.get("cardinality", "")
            card_part = f" ({card})" if card else ""

            lines.append(
                f"- {edge['src_table']} --{join_type}{card_part}--> "
                f"{edge['dst_table']} ON {on_clause}"
            )

        segments.append("\n".join(lines))

    return "\n\n".join(segments)


def estimate_join_complexity(join_plans: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    估算 JOIN 复杂度

    Args:
        join_plans: JOIN 计划列表

    Returns:
        复杂度指标字典
    """
    if not join_plans:
        return {
            "total_edges": 0,
            "max_hops": 0,
            "total_cost": 0.0,
            "complexity": "simple",
        }

    total_edges = sum(len(plan.get("edges", [])) for plan in join_plans)
    max_hops = max(plan.get("hop_count", 0) for plan in join_plans)
    total_cost = sum(plan.get("total_cost", 0.0) for plan in join_plans)

    # 简单分类
    if total_edges <= 2:
        complexity = "simple"
    elif total_edges <= 5:
        complexity = "medium"
    else:
        complexity = "complex"

    return {
        "total_edges": total_edges,
        "max_hops": max_hops,
        "total_cost": total_cost,
        "complexity": complexity,
    }


def validate_join_plan(join_plan: Dict[str, Any]) -> List[str]:
    """
    验证 JOIN 计划的有效性

    Args:
        join_plan: JOIN 计划字典

    Returns:
        错误列表（空列表表示有效）
    """
    errors = []

    if not join_plan.get("base"):
        errors.append("JOIN 计划缺少 base 表")

    if not join_plan.get("edges"):
        errors.append("JOIN 计划缺少边信息")

    for edge in join_plan.get("edges", []):
        if not edge.get("src_table"):
            errors.append("边缺少 src_table")
        if not edge.get("dst_table"):
            errors.append("边缺少 dst_table")
        if not edge.get("on"):
            errors.append(f"边 {edge.get('src_table')} -> {edge.get('dst_table')} 缺少 ON 条件")

    return errors
