"""维度值匹配工具 - 纯函数逻辑"""

from typing import Any, Dict, List, Optional


def extract_dimension_values(parse_hints: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    从 parse_hints 中提取维度值

    Args:
        parse_hints: 诊断 Agent 提取的解析提示

    Returns:
        维度值列表，每个元素包含：
        - text: 原始文本
        - role: 角色（"value" 或 "column"）
        - source_index: 在原始列表中的索引
    """
    if not parse_hints or "dimensions" not in parse_hints:
        return []

    dimensions = parse_hints["dimensions"]
    values = []

    for idx, dim in enumerate(dimensions):
        if dim.get("role") == "value":
            values.append({
                "text": dim["text"],
                "role": dim["role"],
                "source_index": idx,
            })

    return values


def filter_matches_by_score(
    matches: List[Dict[str, Any]],
    min_score: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    根据分数过滤匹配结果

    Args:
        matches: 匹配结果列表
        min_score: 最小分数阈值

    Returns:
        过滤后的匹配列表
    """
    return [m for m in matches if m.get("score", 0.0) >= min_score]


def group_matches_by_source(matches: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """
    按 source_index 分组匹配结果

    Args:
        matches: 匹配结果列表（带 source_index 字段）

    Returns:
        分组字典 {source_index: [matches]}
    """
    grouped = {}

    for match in matches:
        source_idx = match.get("source_index")
        if source_idx is not None:
            if source_idx not in grouped:
                grouped[source_idx] = []
            grouped[source_idx].append(match)

    return grouped


def select_best_match(matches: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    从多个匹配中选择最佳匹配

    Args:
        matches: 同一个源的匹配列表

    Returns:
        最佳匹配，如果列表为空返回 None
    """
    if not matches:
        return None

    # 按分数排序，返回最高分
    return max(matches, key=lambda m: m.get("score", 0.0))


def format_dim_value_matches_for_prompt(
    matches: List[Dict[str, Any]],
    min_display_score: float = 0.5,
) -> str:
    """
    格式化维度值匹配结果为提示词文本

    Args:
        matches: 匹配结果列表
        min_display_score: 最小显示分数（低于此分数的不显示）

    Returns:
        格式化后的文本
    """
    # 过滤低分匹配
    filtered_matches = filter_matches_by_score(matches, min_display_score)

    if not filtered_matches:
        return "（无）"

    lines = []
    for m in filtered_matches:
        # 构建建议的 WHERE 条件
        suggested_condition = f"{m['dim_table']}.{m['key_col']}='{m['key_value']}'"

        # 格式化输出
        lines.append(
            f"- '{m['query_value']}' → {suggested_condition} "
            f"(匹配: {m['matched_text']}, 相似度: {m['score']:.2f})"
        )

    lines.append("")
    lines.append("**使用建议**：")
    lines.append("- 优先使用主键过滤（如 store_id = '12345'）而非文本匹配")
    lines.append("- 如果相似度 >= 0.8，直接使用主键条件")
    lines.append("- 如果相似度 < 0.8，可考虑使用 LIKE 模糊匹配或让用户确认")

    return "\n".join(lines)


def build_optimized_filters(
    parse_hints: Optional[Dict[str, Any]],
    dim_matches: List[Dict[str, Any]],
    optimize_min_score: float = 0.5,
) -> List[str]:
    """
    构建优化后的维度过滤条件

    根据维度值匹配结果，优化替换原始维度值

    Args:
        parse_hints: 解析提示
        dim_matches: 维度值匹配结果
        optimize_min_score: 优化最小分数（低于此分数不优化）

    Returns:
        过滤条件列表（用于展示在提示词中）
    """
    if not parse_hints or "dimensions" not in parse_hints:
        return []

    dimensions = parse_hints["dimensions"]
    filters = []

    # 按 source_index 分组匹配
    grouped_matches = group_matches_by_source(dim_matches)

    for idx, dim in enumerate(dimensions):
        if dim.get("role") == "value":
            # 查找最佳匹配
            if idx in grouped_matches:
                best_match = select_best_match(grouped_matches[idx])
                if best_match and best_match.get("score", 0) >= optimize_min_score:
                    # 使用匹配到的值
                    filters.append(f"value={best_match.get('matched_text')}")
                else:
                    # 使用原始值
                    filters.append(f"value={dim.get('text')}")
            else:
                # 没有匹配，使用原始值
                filters.append(f"value={dim.get('text')}")

        elif dim.get("role") == "column":
            filters.append(f"column={dim.get('text')}")

    return filters


def add_source_index_to_matches(
    matches: List[Dict[str, Any]],
    query_value: str,
    dimension_values: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    为匹配结果添加 source_index 字段

    将 query_value 与 dimension_values 中的值匹配，找到对应的 source_index

    Args:
        matches: 原始匹配结果（来自数据库）
        query_value: 查询的维度值
        dimension_values: 从 parse_hints 提取的维度值列表（带 source_index）

    Returns:
        添加了 source_index 的匹配结果
    """
    enriched_matches = []

    # 找到对应的 source_index
    source_index = None
    for dv in dimension_values:
        if dv["text"] == query_value:
            source_index = dv["source_index"]
            break

    # 为每个匹配添加 source_index
    for match in matches:
        enriched_match = match.copy()
        enriched_match["query_value"] = query_value
        enriched_match["source_index"] = source_index
        enriched_matches.append(enriched_match)

    return enriched_matches


def validate_dim_value_match(match: Dict[str, Any]) -> List[str]:
    """
    验证维度值匹配结果的完整性

    Args:
        match: 匹配结果字典

    Returns:
        错误列表（空列表表示有效）
    """
    errors = []

    required_fields = ["dim_table", "dim_col", "key_col", "key_value", "matched_text", "score"]

    for field in required_fields:
        if field not in match or match[field] is None:
            errors.append(f"缺少必需字段：{field}")

    # 验证分数范围
    if "score" in match:
        score = match["score"]
        if not (0.0 <= score <= 1.0):
            errors.append(f"分数超出范围 [0.0, 1.0]: {score}")

    return errors
