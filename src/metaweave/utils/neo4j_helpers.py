"""Neo4j 辅助工具函数

提供便捷的工具函数，用于处理 Neo4j 查询结果中的特殊格式字段。
"""

import json
import logging
from typing import List, Optional, Any, Dict

logger = logging.getLogger(__name__)


def parse_nested_array_field(field_value: Optional[str]) -> List[List[str]]:
    """解析 Neo4j 中的嵌套数组字段（JSON 字符串格式）

    由于 Neo4j 不支持嵌套集合属性，CQLLoader 将嵌套数组（如 pk/uk/fk/logic_pk 等）
    转换为 JSON 字符串存储。此函数用于将 JSON 字符串解析回嵌套列表。

    **使用场景：**
    - 查询表的主键/外键/唯一键信息
    - 查询逻辑键信息（logic_pk/logic_fk/logic_uk）
    - 查询索引信息（indexes）

    **示例：**
    ```python
    # 查询表节点
    query = "MATCH (t:Table {full_name: 'public.dim_company'}) RETURN t.logic_pk AS logic_pk"
    result = neo4j_manager.execute_query(query)

    # 解析 JSON 字符串
    logic_pk = parse_nested_array_field(result[0]["logic_pk"])
    # 结果: [["company_id"]]

    # 使用数据
    for key_columns in logic_pk:
        print(f"复合键包含列: {', '.join(key_columns)}")
    ```

    Args:
        field_value: JSON 字符串，如 '[["col1"], ["col2", "col3"]]'
                     如果为 None 或空字符串，返回空列表

    Returns:
        解析后的嵌套列表，如 [["col1"], ["col2", "col3"]]
        如果为空或解析失败，返回空列表 []

    Examples:
        >>> parse_nested_array_field('[["company_id"]]')
        [['company_id']]

        >>> parse_nested_array_field('[["code", "type"], ["id"]]')
        [['code', 'type'], ['id']]

        >>> parse_nested_array_field('[]')
        []

        >>> parse_nested_array_field(None)
        []

        >>> parse_nested_array_field('')
        []
    """
    if not field_value:
        return []

    try:
        parsed = json.loads(field_value)
        # 验证格式是否正确（应该是 list of list of str）
        if not isinstance(parsed, list):
            logger.warning(f"嵌套数组字段格式错误（应为列表）: {field_value[:50]}...")
            return []
        return parsed
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"无法解析嵌套数组字段: {field_value[:50]}... 错误: {e}")
        return []


def get_primary_keys(table_node: Dict[str, Any]) -> List[List[str]]:
    """获取表的主键信息（物理主键 + 逻辑主键）

    Args:
        table_node: 表节点数据（Neo4j 查询结果）

    Returns:
        主键列表（嵌套列表）

    Example:
        >>> table_node = {
        ...     "pk": '[["id"]]',
        ...     "logic_pk": '[["company_id"]]'
        ... }
        >>> get_primary_keys(table_node)
        [['id'], ['company_id']]
    """
    pk = parse_nested_array_field(table_node.get("pk"))
    logic_pk = parse_nested_array_field(table_node.get("logic_pk"))

    # 合并并去重
    all_keys = []
    seen = set()

    for key_columns in pk + logic_pk:
        key_tuple = tuple(sorted(key_columns))
        if key_tuple not in seen:
            seen.add(key_tuple)
            all_keys.append(key_columns)

    return all_keys


def get_foreign_keys(table_node: Dict[str, Any]) -> List[List[str]]:
    """获取表的外键信息（物理外键 + 逻辑外键）

    Args:
        table_node: 表节点数据（Neo4j 查询结果）

    Returns:
        外键列表（嵌套列表）

    Example:
        >>> table_node = {
        ...     "fk": '[["parent_id"]]',
        ...     "logic_fk": '[["company_id"]]'
        ... }
        >>> get_foreign_keys(table_node)
        [['parent_id'], ['company_id']]
    """
    fk = parse_nested_array_field(table_node.get("fk"))
    logic_fk = parse_nested_array_field(table_node.get("logic_fk"))

    # 合并并去重
    all_keys = []
    seen = set()

    for key_columns in fk + logic_fk:
        key_tuple = tuple(sorted(key_columns))
        if key_tuple not in seen:
            seen.add(key_tuple)
            all_keys.append(key_columns)

    return all_keys


def get_unique_keys(table_node: Dict[str, Any]) -> List[List[str]]:
    """获取表的唯一键信息（物理唯一键 + 逻辑唯一键）

    Args:
        table_node: 表节点数据（Neo4j 查询结果）

    Returns:
        唯一键列表（嵌套列表）

    Example:
        >>> table_node = {
        ...     "uk": '[["code"]]',
        ...     "logic_uk": '[["name"]]'
        ... }
        >>> get_unique_keys(table_node)
        [['code'], ['name']]
    """
    uk = parse_nested_array_field(table_node.get("uk"))
    logic_uk = parse_nested_array_field(table_node.get("logic_uk"))

    # 合并并去重
    all_keys = []
    seen = set()

    for key_columns in uk + logic_uk:
        key_tuple = tuple(sorted(key_columns))
        if key_tuple not in seen:
            seen.add(key_tuple)
            all_keys.append(key_columns)

    return all_keys


def is_composite_key(key_columns: List[str]) -> bool:
    """判断是否为复合键（多列组成的键）

    Args:
        key_columns: 键的列名列表，如 ["col1", "col2"]

    Returns:
        bool: 是否为复合键

    Example:
        >>> is_composite_key(["id"])
        False

        >>> is_composite_key(["code", "type"])
        True
    """
    return len(key_columns) > 1
