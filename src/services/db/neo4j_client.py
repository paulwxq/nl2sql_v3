"""Neo4j 业务客户端 - JOIN 路径检索"""

from typing import Any, Dict, List, Optional

from neo4j.exceptions import Neo4jError

from src.services.db.neo4j_connection import get_neo4j_manager
from src.utils.logger import get_module_logger

logger = get_module_logger("neo4j")


class Neo4jClient:
    """Neo4j 业务客户端"""

    def __init__(self):
        """初始化 Neo4j 客户端"""
        self.neo4j_manager = get_neo4j_manager()

    # ==================== JOIN 路径检索 ====================

    def find_join_path(
        self,
        base_table: str,
        target_table: str,
        max_hops: int = 5,
        strategy: str = "apoc_dijkstra",
    ) -> Optional[Dict[str, Any]]:
        """
        查找两个表之间的 JOIN 路径

        Args:
            base_table: 起始表（如 "public.fact_sales"）
            target_table: 目标表（如 "public.dim_store"）
            max_hops: 最大跳数
            strategy: 策略（"apoc_dijkstra" 或 "shortest_path"）

        Returns:
            路径信息字典，包含：
            - base: 起始表
            - target: 目标表
            - edges: 边列表（JOIN关系）
            - total_cost: 总成本
            如果未找到路径返回 None
        """
        if strategy == "apoc_dijkstra":
            path = self._find_path_apoc_dijkstra(base_table, target_table, max_hops)
            if path is not None:
                return path

            # APOC 失败，回退到最短路径
            logger.warning("APOC Dijkstra 未找到路径，回退到 shortestPath")
            return self._find_path_shortest(base_table, target_table, max_hops)

        else:
            return self._find_path_shortest(base_table, target_table, max_hops)

    def _find_path_apoc_dijkstra(
        self,
        base_table: str,
        target_table: str,
        max_hops: int,
    ) -> Optional[Dict[str, Any]]:
        """
        使用 APOC Dijkstra 算法查找最优路径（基于 cost 权重）

        Args:
            base_table: 起始表
            target_table: 目标表
            max_hops: 最大跳数（未在 APOC 中使用，仅用于兼容）

        Returns:
            路径信息字典或 None
        """
        query = """
            MATCH (src:Table {id: $base}), (dst:Table {id: $target})
            CALL apoc.algo.dijkstra(src, dst, 'JOIN_ON', 'cost', 1.0)
            YIELD path, weight
            RETURN path, weight
            ORDER BY weight ASC
            LIMIT 1
        """

        try:
            with self.neo4j_manager.get_session() as session:
                logger.debug(f"APOC Dijkstra CQL: {query.strip()}  参数: base={base_table!r}, target={target_table!r}")
                result = session.run(query, base=base_table, target=target_table)
                record = result.single()

                if record and record.get("path"):
                    path = record["path"]
                    weight = record["weight"]
                    logger.debug(f"✓ APOC Dijkstra 找到路径: {base_table} → {target_table}，权重: {weight:.2f}")
                    return self._extract_path_info(base_table, target_table, path, weight)

                logger.debug(f"✗ APOC Dijkstra 未找到路径: {base_table} → {target_table}")
                return None

        except Neo4jError as e:
            # APOC 可能不可用
            logger.warning(f"APOC Dijkstra 执行失败: {e}")
            return None

    def _find_path_shortest(
        self,
        base_table: str,
        target_table: str,
        max_hops: int,
    ) -> Optional[Dict[str, Any]]:
        """
        使用内置 shortestPath 查找最短路径

        Args:
            base_table: 起始表
            target_table: 目标表
            max_hops: 最大跳数

        Returns:
            路径信息字典或 None
        """
        query = f"""
            MATCH path = shortestPath(
                (src:Table {{id: $base}})-[:JOIN_ON*..{max_hops}]-(dst:Table {{id: $target}})
            )
            RETURN path
            LIMIT 1
        """

        try:
            with self.neo4j_manager.get_session() as session:
                logger.debug(f"shortestPath CQL: {query.strip()}  参数: base={base_table!r}, target={target_table!r}")
                result = session.run(query, base=base_table, target=target_table)
                record = result.single()

                if record and record.get("path"):
                    path = record["path"]
                    hop_count = len(path.relationships)
                    logger.debug(f"✓ shortestPath 找到路径: {base_table} → {target_table}，跳数: {hop_count}")
                    return self._extract_path_info(base_table, target_table, path)

                logger.warning(f"✗ shortestPath 未找到路径: {base_table} → {target_table}")
                return None

        except Neo4jError as e:
            logger.error(f"shortestPath 执行失败: {e}")
            return None

    def _extract_path_info(
        self,
        base_table: str,
        target_table: str,
        path,
        total_cost: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        从 Neo4j Path 对象提取路径信息

        Args:
            base_table: 起始表
            target_table: 目标表
            path: Neo4j Path 对象
            total_cost: 总成本（可选）

        Returns:
            路径信息字典
        """
        edges = []

        for relationship in path.relationships:
            # 获取节点 ID
            src_node = relationship.start_node
            dst_node = relationship.end_node

            src_table = src_node.get("id") or src_node.get("name")
            dst_table = dst_node.get("id") or dst_node.get("name")

            # 获取关系属性
            edge_info = {
                "src_table": src_table,
                "dst_table": dst_table,
                "constraint_name": relationship.get("constraint_name"),
                "join_type": relationship.get("join_type", "INNER JOIN"),
                "cardinality": relationship.get("cardinality"),
                "on": relationship.get("on_clause") or relationship.get("on"),
                "cost": relationship.get("cost", 1.0),
            }

            edges.append(edge_info)

        # 计算总成本（如果未提供）
        if total_cost is None:
            total_cost = sum(edge.get("cost", 1.0) for edge in edges)

        return {
            "base": base_table,
            "target": target_table,
            "edges": edges,
            "total_cost": total_cost,
            "hop_count": len(edges),
        }

    # ==================== 批量路径规划 ====================

    def plan_join_paths(
        self,
        base_tables: List[str],
        target_tables: List[str],
        max_hops: int = 5,
        strategy: str = "apoc_dijkstra",
    ) -> List[Dict[str, Any]]:
        """
        为多个 base 表规划 JOIN 计划

        为每个 base 表找到所有 target 表的路径，合并为单个 JOIN 计划

        Args:
            base_tables: 起始表列表（通常是事实表）
            target_tables: 目标表列表（通常是维表）
            max_hops: 最大跳数
            strategy: 路径查找策略

        Returns:
            JOIN 计划列表，每个元素对应一个 base 表
        """
        logger.info("plan_join_paths 调用参数")
        logger.debug(f"  base_tables = {base_tables}")
        logger.debug(f"  target_tables = {target_tables}")
        logger.debug(f"  max_hops = {max_hops}, strategy = {strategy}")
        
        join_plans = []

        for base in base_tables:
            # 找到当前 base 到所有 targets 的路径
            all_edges = []
            reachable_targets = []

            for target in target_tables:
                if target == base:
                    continue

                logger.debug(f"查询路径: {base} → {target}")
                path = self.find_join_path(base, target, max_hops, strategy)

                if path and path.get("edges"):
                    # 合并边（去重）
                    for edge in path["edges"]:
                        # 简单去重：检查是否已存在相同的边
                        edge_key = (edge["src_table"], edge["dst_table"], edge.get("on"))
                        if not any(
                            (e["src_table"], e["dst_table"], e.get("on")) == edge_key
                            for e in all_edges
                        ):
                            all_edges.append(edge)

                    reachable_targets.append(target)

            # 如果找到了至少一条路径，添加到计划
            if all_edges:
                join_plans.append({
                    "base": base,
                    "targets": reachable_targets,
                    "edges": all_edges,
                    "total_cost": sum(e.get("cost", 1.0) for e in all_edges),
                })

        return join_plans

    # ==================== 工具方法 ====================

    def check_table_exists(self, table_id: str) -> bool:
        """
        检查表节点是否存在

        Args:
            table_id: 表ID（如 "public.fact_sales"）

        Returns:
            存在返回 True，否则返回 False
        """
        query = """
            MATCH (t:Table {id: $table_id})
            RETURN count(t) > 0 AS exists
        """

        with self.neo4j_manager.get_session() as session:
            result = session.run(query, table_id=table_id)
            record = result.single()
            return record["exists"] if record else False

    def get_table_neighbors(
        self,
        table_id: str,
        direction: str = "both",
    ) -> List[Dict[str, Any]]:
        """
        获取表的直接邻居（1跳）

        Args:
            table_id: 表ID
            direction: 方向（"outgoing"/"incoming"/"both"）

        Returns:
            邻居表列表
        """
        if direction == "outgoing":
            query = """
                MATCH (src:Table {id: $table_id})-[r:JOIN_ON]->(dst:Table)
                RETURN dst.id AS neighbor_id, dst.name AS neighbor_name,
                       type(r) AS relationship_type, properties(r) AS relationship_props
            """
        elif direction == "incoming":
            query = """
                MATCH (src:Table {id: $table_id})<-[r:JOIN_ON]-(dst:Table)
                RETURN dst.id AS neighbor_id, dst.name AS neighbor_name,
                       type(r) AS relationship_type, properties(r) AS relationship_props
            """
        else:  # both
            query = """
                MATCH (src:Table {id: $table_id})-[r:JOIN_ON]-(dst:Table)
                RETURN dst.id AS neighbor_id, dst.name AS neighbor_name,
                       type(r) AS relationship_type, properties(r) AS relationship_props
            """

        with self.neo4j_manager.get_session() as session:
            result = session.run(query, table_id=table_id)
            return [dict(record) for record in result]

    def get_join_statistics(self) -> Dict[str, Any]:
        """
        获取 JOIN 关系统计信息

        Returns:
            统计信息字典
        """
        query = """
            MATCH (t:Table)
            OPTIONAL MATCH (t)-[r:JOIN_ON]-()
            RETURN
                count(DISTINCT t) AS table_count,
                count(r) AS join_relationship_count
        """

        with self.neo4j_manager.get_session() as session:
            result = session.run(query)
            record = result.single()

            if record:
                return {
                    "table_count": record["table_count"],
                    "join_relationship_count": record["join_relationship_count"],
                }
            else:
                return {"table_count": 0, "join_relationship_count": 0}


# 全局 Neo4j 客户端实例（单例）
_global_neo4j_client: Optional[Neo4jClient] = None


def get_neo4j_client() -> Neo4jClient:
    """
    获取全局 Neo4j 客户端（单例）

    Returns:
        Neo4jClient 实例
    """
    global _global_neo4j_client

    if _global_neo4j_client is None:
        _global_neo4j_client = Neo4jClient()

    return _global_neo4j_client
