"""Schema 检索协调器 - 整合向量检索、图检索、维度值匹配"""

import time
from typing import Any, Dict, List, Optional, Tuple

from src.services.db.neo4j_client import get_neo4j_client
from src.services.db.pg_client import get_pg_client
from src.services.embedding.embedding_client import get_embedding_client
from src.services.vector_adapter import create_vector_search_adapter
from src.tools.schema_retrieval.join_planner import build_join_plans
from src.tools.schema_retrieval.value_matcher import add_source_index_to_matches
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("retrieval")


class SchemaRetriever:
    """Schema 检索协调器"""

    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化 Schema 检索器

        Args:
            config: 检索配置（来自子图配置）
        """
        self.config = config or {}

        # 初始化客户端
        self.pg_client = get_pg_client()  # 保留，用于执行生成的 SQL
        self.neo4j_client = get_neo4j_client()
        self.embedding_client = get_embedding_client()

        # ⭐ 新增：向量数据库客户端（通过工厂函数创建，支持 PgVector/Milvus 切换）
        self.vector_client = create_vector_search_adapter(self.config)

        # 提取配置参数
        retrieval_config = self.config.get("schema_retrieval", {})
        self.topk_tables = retrieval_config.get("topk_tables", 10)
        self.topk_columns = retrieval_config.get("topk_columns", 10)
        self.dim_index_topk = retrieval_config.get("dim_index_topk", 5)
        self.dim_value_min_score = retrieval_config.get("dim_value_min_score", 0.0)
        self.join_max_hops = retrieval_config.get("join_max_hops", 5)
        self.similarity_threshold = retrieval_config.get("similarity_threshold", 0.45)

        # 性能优化：预处理类型映射表（小写化）
        category_mapping = retrieval_config.get("table_category_mapping", {})
        if not category_mapping:
            raise ValueError(
                "配置错误：缺少 schema_retrieval.table_category_mapping 配置。"
                "请在 sql_generation_subgraph.yaml 中添加表分类映射规则。"
            )

        # 将所有类型值预先转为小写，避免运行时重复转换
        self._category_mapping_lower = {}
        for category_group in ["fact", "dimension", "bridge"]:
            type_list = category_mapping.get(category_group, [])
            self._category_mapping_lower[category_group] = {t.lower() for t in type_list}

        logger.info(
            f"表分类映射已加载: "
            f"fact包含 {len(self._category_mapping_lower['fact'])} 个子类型, "
            f"dimension包含 {len(self._category_mapping_lower['dimension'])} 个子类型, "
            f"bridge包含 {len(self._category_mapping_lower['bridge'])} 个子类型"
        )

    def retrieve(
        self,
        query: str,
        parse_result: Optional[Dict[str, Any]] = None,
        parse_hints: Optional[Dict[str, Any]] = None,
        *,
        query_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        检索 Schema 上下文

        Args:
            query: 子查询文本
            parse_hints: 解析提示（可选，包含时间、维度、指标等）

        Returns:
            Schema 上下文字典：
            {
                "join_plans": List[Dict],         # JOIN 计划列表（基于图检索生成）
                "table_cards": Dict[str, Dict],   # 表卡片字典（表的详细描述）
                "similar_sqls": List[Dict],       # 历史成功 SQL 案例
                "dim_value_hits": List[Dict],     # 维度值匹配结果（已去重）
                "table_categories": Dict[str, str],  # 表分类字典（table_id -> category）
                "metadata": Dict,                 # 元信息，包含：
                    # - retrieval_time: 检索耗时（秒）
                    # - table_count: 候选表数量
                    # - column_count: 候选列数量
                    # - join_plan_count: JOIN 计划数量
                    # - dim_match_count: 维度值匹配数量
                    # - candidate_fact_tables: 候选事实表列表（调试用）
                    # - candidate_dim_tables: 候选维度表列表（调试用）
            }

            注意：
            - tables/columns 字段已在"瘦身优化"中移除，信息整合到 join_plans 和 table_cards 中
            - dim_value_matches 已重命名为 dim_value_hits（与代码其他部分保持一致）
            - table_categories 用于补全候选表的原始类型信息（用于提示词展示）
        """
        start_time = time.time()

        # 统一解析结果（兼容 parse_hints 参数）
        if parse_result is None and parse_hints:
            parse_result = parse_hints

        # 1) 生成查询向量（局部变量）
        qlog = with_query_id(logger, query_id or "")
        qlog.info("步骤1: 生成查询向量")
        query_embedding = self.embedding_client.embed_query(query)
        qlog.debug(f"✓ 向量维度: {len(query_embedding)}")

        # 2) 向量检索：表和列
        # ⭐ 动态显示后端类型
        from src.services.config_loader import get_config
        active_type = get_config().get("vector_database", {}).get("active", "unknown")
        qlog.info(f"步骤2: 向量检索表和列（{active_type}）")
        logger.debug(
            f"参数: topk_tables={self.topk_tables}, topk_columns={self.topk_columns}, threshold={self.similarity_threshold}"
        )

        semantic_tables = self.vector_client.search_tables(
            embedding=query_embedding,
            top_k=self.topk_tables,
            similarity_threshold=self.similarity_threshold,
        )
        qlog.debug(f"✓ 检索到 {len(semantic_tables)} 个候选表")
        if semantic_tables:
            table_lines = []
            for t in semantic_tables:
                tid = t.get("table_name") or t.get("object_id")
                cat = (t.get("table_category") or t.get("category") or "").lower()
                sim = t.get("similarity")
                grain = t.get("grain_hint")
                time_col = t.get("time_col_hint")
                if sim is not None:
                    table_lines.append(
                        f"{tid} (sim={float(sim):.2f}, cat={cat}, grain={grain}, time_col={time_col})"
                    )
                else:
                    table_lines.append(
                        f"{tid} (cat={cat}, grain={grain}, time_col={time_col})"
                    )
            qlog.debug("候选表详情: [" + "; ".join(table_lines) + "]")

        semantic_columns = self.vector_client.search_columns(
            embedding=query_embedding,
            top_k=self.topk_columns,
            similarity_threshold=self.similarity_threshold,
        )
        qlog.debug(f"✓ 检索到 {len(semantic_columns)} 个候选列")
        if semantic_columns:
            col_lines = []
            for c in semantic_columns:
                cid = c.get("object_id")
                pid = c.get("table_name") or c.get("parent_id")
                sim = c.get("similarity")
                if sim is not None:
                    col_lines.append(f"{cid} (parent={pid}, sim={float(sim):.2f})")
                else:
                    col_lines.append(f"{cid} (parent={pid})")
            qlog.debug("候选列详情: [" + "; ".join(col_lines) + "]")

        # 3) 构建候选集合 & 维度值命中
        qlog.info("步骤3: 分类事实表和维度表")
        candidate_set = self._collect_and_classify_tables(
            semantic_tables=semantic_tables,
            semantic_columns=semantic_columns,
            parse_result=parse_result,
        )
        qlog.debug(
            f"✓ 事实表: {len(candidate_set['candidate_fact_tables'])} 个, "
            f"维度表: {len(candidate_set['candidate_dim_tables'])} 个, "
            f"桥接表: {len(candidate_set['candidate_bridge_tables'])} 个, "
            f"维度值命中: {len(candidate_set['dim_value_hits'])} 个"
        )
        # column dimension backfill 汇总日志
        column_dim_summary = candidate_set.get("column_dim_summary", {})
        if column_dim_summary:
            qlog.debug(
                f"column dimension backfill 补充 {len(column_dim_summary)} 个父表: "
                f"{list(column_dim_summary.keys())}"
            )
        # 列出详细名单
        if candidate_set.get("candidate_fact_tables"):
            qlog.debug(f"事实表列表: {candidate_set['candidate_fact_tables']}")
        if candidate_set.get("candidate_dim_tables"):
            qlog.debug(f"维度表列表: {candidate_set['candidate_dim_tables']}")
        if candidate_set.get("candidate_bridge_tables"):
            qlog.debug(f"桥接表列表: {candidate_set['candidate_bridge_tables']}")
        dim_hits = candidate_set.get("dim_value_hits") or []
        if dim_hits:
            # 输出命中名称清单（query_value -> matched_text [dim_table]）
            dim_hit_lines = []
            for hit in dim_hits:
                src = hit.get("query_value") or hit.get("source_text") or ""
                dst = hit.get("matched_text") or hit.get("text") or ""
                dim_table = hit.get("dim_table") or ""
                if dim_table and "." not in dim_table:
                    dim_table = f"public.{dim_table}"
                line = f"{src} -> {dst}" + (f" [{dim_table}]" if dim_table else "")
                dim_hit_lines.append(line)
            qlog.debug("维度值命中详情: [" + "; ".join(dim_hit_lines) + "]")

        # 4) 图检索：JOIN 计划（基于候选集合）
        qlog.info("步骤4: 查询 JOIN 路径（Neo4j）")
        join_plans = self._retrieve_join_plans(
            candidate_fact_tables=candidate_set["candidate_fact_tables"],
            candidate_dim_tables=candidate_set["candidate_dim_tables"],
            candidate_bridge_tables=candidate_set["candidate_bridge_tables"],  # 桥接表
            table_similarities=candidate_set["table_similarities"],
            parse_result=parse_result,
        )
        qlog.debug(f"✓ 生成 {len(join_plans)} 个 JOIN 计划")
        # 输出 JOIN 计划详情：基表、目标表、涉及表与边
        for idx, plan in enumerate(join_plans, 1):
            base = plan.get("base")
            targets = plan.get("targets") or []
            edges = plan.get("edges") or []
            qlog.debug(f"JOIN计划#{idx}: base={base}, targets={targets}")
            if edges:
                # 涉及的表集合
                tables_in_edges = []
                for e in edges:
                    s = e.get("src_table"); d = e.get("dst_table")
                    if s and s not in tables_in_edges:
                        tables_in_edges.append(s)
                    if d and d not in tables_in_edges:
                        tables_in_edges.append(d)
                qlog.debug(f"JOIN 关联涉及表: {tables_in_edges}")
                # 边详情
                edge_lines = []
                for e in edges:
                    s = e.get("src_table"); d = e.get("dst_table")
                    on = e.get("on") or e.get("on_clause")
                    edge_lines.append(f"{s} -> {d}" + (f" on {on}" if on else ""))
                qlog.debug("JOIN 边详情: [" + "; ".join(edge_lines) + "]")

        # 5) 获取表卡片
        all_table_ids = list(
            dict.fromkeys(
                candidate_set["candidate_fact_tables"] +
                candidate_set["candidate_dim_tables"]
            )
        )
        table_cards = self.vector_client.fetch_table_cards(all_table_ids)

        # 统计口径：总去重后的候选表数量（含所有来源）
        all_candidate_count = len(dict.fromkeys(
            candidate_set["candidate_fact_tables"] +
            candidate_set["candidate_dim_tables"] +
            candidate_set["candidate_bridge_tables"]
        ))

        # 6) 检索历史相似 SQL（带异常降级）
        qlog.info("步骤6: 检索历史相似 SQL")
        retrieval_config = self.config.get("schema_retrieval", {})
        sql_topk = retrieval_config.get("sql_embedding_top_k", 3)
        sql_threshold = retrieval_config.get("sql_similarity_threshold", 0.6)
        
        similar_sqls = []
        try:
            similar_sqls = self.vector_client.search_similar_sqls(
                embedding=query_embedding,
                top_k=sql_topk,
                similarity_threshold=sql_threshold,
            )
            qlog.debug(f"✓ 检索到 {len(similar_sqls)} 个相似 SQL 案例")
        except Exception as e:
            qlog.warning(f"历史 SQL 检索失败（已降级为空）: {e}")
            similar_sqls = []

        # 计算耗时
        retrieval_time = time.time() - start_time
        qlog.info(f"Schema 检索完成，耗时 {retrieval_time:.2f} 秒")

        # 维度匹配结果：去重并按分数降序排序
        try:
            from .value_matcher import deduplicate_dim_hits
            dedup_dim_hits = deduplicate_dim_hits(candidate_set["dim_value_hits"])
        except Exception:
            # 防御性回退：异常时保留原始结果
            dedup_dim_hits = candidate_set["dim_value_hits"]

        # 构建 schema_context
        schema_context = {
            # 保留：后续 SQL 生成实际使用的字段
            "join_plans": join_plans,
            "table_cards": table_cards,
            "similar_sqls": similar_sqls,  # 历史 SQL 案例
            "dim_value_hits": dedup_dim_hits,
            "table_categories": candidate_set["table_categories"],

            # 可选：元数据（调试/统计用，后续如需可在统一瘦身口移除）
            "metadata": {
                "retrieval_time": retrieval_time,
                "table_count": all_candidate_count,
                "column_count": len(semantic_columns) + candidate_set.get("column_dim_hit_count", 0),
                "join_plan_count": len(join_plans),
                "dim_match_count": len(candidate_set["dim_value_hits"]),
                # ✅ 候选表列表（调试用）
                "candidate_fact_tables": candidate_set["candidate_fact_tables"],
                "candidate_dim_tables": candidate_set["candidate_dim_tables"],
            },
        }

        return schema_context

    def _collect_table_names(
        self,
        semantic_tables: List[Dict[str, Any]],
        semantic_columns: List[Dict[str, Any]],
    ) -> List[str]:
        """
        汇总候选表名（表检索 + 列的父表）

        Args:
            semantic_tables: 表检索结果
            semantic_columns: 列检索结果

        Returns:
            去重排序后的表名列表
        """
        table_set = set()

        # 从表检索添加
        for t in semantic_tables:
            table_name = t.get("table_name") or t.get("object_id")
            if table_name:
                table_set.add(table_name)

        # 从列检索添加父表
        for c in semantic_columns:
            table_name = c.get("table_name") or c.get("parent_id")
            if table_name:
                table_set.add(table_name)

        return sorted(list(table_set))

    def _classify_table_category(self, category: str) -> str:
        """
        根据原始 table_category 值归类到 fact/dimension/bridge

        Args:
            category: 原始 table_category 值（如"事实表"、"交易表"等）

        Returns:
            归类结果: "fact" | "dimension" | "bridge"

        注意：
            - 完全依赖配置文件 sql_generation_subgraph.yaml 中的 table_category_mapping
            - 使用预处理的映射表（_category_mapping_lower），提升性能
        """
        if not category:
            return "dimension"  # 空值默认归为维度表

        # 使用预处理的小写映射表（O(1) 查找）
        category_lower = category.lower()

        # 检查是否属于事实表
        if category_lower in self._category_mapping_lower["fact"]:
            return "fact"

        # 检查是否属于桥接表
        if category_lower in self._category_mapping_lower["bridge"]:
            return "bridge"

        # 检查是否属于维度表
        if category_lower in self._category_mapping_lower["dimension"]:
            return "dimension"

        # 如果在配置中都找不到，默认归为维度表
        qlog = with_query_id(logger, "")
        qlog.warning(f"表类型 '{category}' 未在配置中定义，默认归为维度表")
        return "dimension"

    def _collect_and_classify_tables(
        self,
        semantic_tables: List[Dict[str, Any]],
        semantic_columns: List[Dict[str, Any]],
        parse_result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """构建 CandidateSet，区分事实表/维度表/桥接表并附加维度值命中"""
        qlog = with_query_id(logger, "")

        # 1) 维度值检索
        dim_value_hits = self._retrieve_dim_value_hits(parse_result)

        # 2) 通过维度值命中获取维度表
        dim_tables_from_values = []
        seen_dim_from_values = set()
        for hit in dim_value_hits:
            table_name = hit.get("dim_table")
            if not table_name:
                continue
            table_id = str(table_name)
            if "." not in table_id:
                table_id = f"public.{table_id}"
            if table_id not in seen_dim_from_values:
                dim_tables_from_values.append(table_id)
                seen_dim_from_values.add(table_id)

        # ── 提前初始化（原在步骤 4，前移以支持步骤 3 写入相似度） ──
        table_category_map = {
            (t.get("table_name") or t.get("object_id")): (t.get("table_category") or t.get("category") or "")
            for t in semantic_tables
            if (t.get("table_name") or t.get("object_id"))
        }
        table_similarities: Dict[str, float] = {}
        table_categories: Dict[str, str] = {}

        # 2.5) 【新增】通过 column 维度文本检索补充候选列命中
        column_dim_hits = self._retrieve_column_dimension_hits(parse_result)

        # 2.6) 【新增】补全 column_dim_hits 父表的 table_category
        #   Milvus 中 object_type="column" 的 table_category 为空，需通过父表 ID 查询
        if column_dim_hits:
            column_parent_ids = list({
                (col.get("table_name") or col.get("parent_id"))
                for col in column_dim_hits
                if (col.get("table_name") or col.get("parent_id"))
            })
            missing_parents = [pid for pid in column_parent_ids if pid not in table_category_map]
            if missing_parents:
                extra_categories = self.vector_client.fetch_table_categories(missing_parents)
                table_category_map.update(extra_categories)
                table_categories.update(extra_categories)

        # 3) 通过列命中收集父表（三分类）—— 合并 semantic_columns + column_dim_hits
        fact_from_columns: List[str] = []
        dim_from_columns: List[str] = []
        bridge_from_columns: List[str] = []

        all_column_hits = list(semantic_columns) + list(column_dim_hits)

        # column_dim_summary: 仅收集 column_dim_hits 来源的汇总信息（日志用，不进入 schema_context）
        column_dim_summary: Dict[str, Dict] = {}

        for col in all_column_hits:
            parent_id = col.get("table_name") or col.get("parent_id")
            if not parent_id:
                continue

            category = table_category_map.get(parent_id, "")
            category_group = self._classify_table_category(category)

            if category_group == "fact":
                if parent_id not in fact_from_columns:
                    fact_from_columns.append(parent_id)
            elif category_group == "bridge":
                if parent_id not in bridge_from_columns:
                    bridge_from_columns.append(parent_id)
            else:
                if parent_id not in dim_from_columns:
                    dim_from_columns.append(parent_id)

            # 写入相似度（取 max，修复既有问题：列命中父表此前从未写入 table_similarities）
            similarity = col.get("similarity")
            if similarity is not None:
                existing = table_similarities.get(parent_id, 0.0)
                table_similarities[parent_id] = max(existing, float(similarity))

            # 收集 column_dim_hits 来源的汇总（用于日志）
            if col.get("source_dimension_text") is not None:
                if parent_id not in column_dim_summary:
                    column_dim_summary[parent_id] = {
                        "best_similarity": 0.0,
                        "raw_category": category,
                        "category_group": category_group,
                        "source_texts": [],
                    }
                entry = column_dim_summary[parent_id]
                entry["best_similarity"] = max(entry["best_similarity"], float(similarity or 0))
                entry["category_group"] = category_group
                src = col.get("source_dimension_text", "")
                if src and src not in entry["source_texts"]:
                    entry["source_texts"].append(src)

        if column_dim_summary:
            qlog.debug(f"column dimension 补充候选表: {column_dim_summary}")

        # 4) 语义检索结果分类（三分类）—— 表级检索按信号优先级覆盖步骤 3 的列级分数
        semantic_fact_tables: List[str] = []
        semantic_dim_tables: List[str] = []
        semantic_bridge_tables: List[str] = []

        for table in semantic_tables:
            table_id = table.get("table_name") or table.get("object_id")
            if not table_id:
                continue
            similarity = table.get("similarity")
            if similarity is not None:
                # 表级直接检索，信号优先级高于列级间接推导，直接覆盖
                table_similarities[table_id] = float(similarity)

            category = table.get("table_category") or table.get("category") or ""
            if category:
                table_categories[table_id] = category

            category_group = self._classify_table_category(category)

            if category_group == "fact":
                if table_id not in semantic_fact_tables:
                    semantic_fact_tables.append(table_id)
            elif category_group == "bridge":
                if table_id not in semantic_bridge_tables:
                    semantic_bridge_tables.append(table_id)
            else:
                if table_id not in semantic_dim_tables:
                    semantic_dim_tables.append(table_id)

        # 5) 合并候选集合（保持顺序）
        candidate_fact_tables = list(dict.fromkeys(semantic_fact_tables + fact_from_columns))
        candidate_dim_tables = list(
            dict.fromkeys(dim_tables_from_values + dim_from_columns + semantic_dim_tables)
        )
        candidate_bridge_tables = list(dict.fromkeys(semantic_bridge_tables + bridge_from_columns))

        # 6) 补全缺失的表类型信息（用于提示词展示）
        all_candidate_tables = list(dict.fromkeys(
            candidate_fact_tables + candidate_dim_tables + candidate_bridge_tables
        ))
        missing_tables = [t for t in all_candidate_tables if t not in table_categories]

        if missing_tables:
            missing_categories = self.vector_client.fetch_table_categories(missing_tables)
            table_categories.update(missing_categories)

        return {
            "candidate_fact_tables": candidate_fact_tables,
            "candidate_dim_tables": candidate_dim_tables,
            "candidate_bridge_tables": candidate_bridge_tables,
            "table_similarities": table_similarities,
            "table_categories": table_categories,
            "dim_value_hits": dim_value_hits,
            "column_dim_summary": column_dim_summary,  # 仅日志用，不进入 schema_context
            "column_dim_hit_count": len(column_dim_hits),  # 统计用
        }

    def _retrieve_join_plans(
        self,
        candidate_fact_tables: List[str],
        candidate_dim_tables: List[str],
        candidate_bridge_tables: List[str],  # 桥接表
        table_similarities: Dict[str, float],
        parse_result: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        检索 JOIN 计划

        参考 docs/13 第718-900行的 Planner 阶段逻辑

        包含三个关键逻辑：
        1. 维度表优化判断（_should_use_dimension_only）
        2. Base表选择策略（事实表 > 维度表，桥接表不能作为base）
        3. 连通性分析（多维度表场景）

        注意：
            - 桥接表可以参与 JOIN（在 all_tables 中），但不能作为 base 表
            - 仅事实表和维度表可以作为 base 表
        """
        # 桥接表可以参与 JOIN，但不能作为 base 表
        all_tables = list(dict.fromkeys(candidate_fact_tables + candidate_dim_tables + candidate_bridge_tables))

        # 检查是否只有桥接表（无法生成 JOIN 计划）
        if not candidate_fact_tables and not candidate_dim_tables:
            qlog = with_query_id(logger, "")
            if candidate_bridge_tables:
                qlog.warning(
                    f"仅检测到桥接表 {candidate_bridge_tables}，无法生成JOIN计划。"
                    "桥接表不能作为 base 表，请检查查询意图或 Schema 设计。"
                )
            return []

        # 1) 维度表优化判断（参考 docs/13:727-784）
        should_use_dim_only, dim_only_table = self._should_use_dimension_only(
            parse_result,
            candidate_fact_tables,
            candidate_dim_tables,
            table_similarities
        )

        if should_use_dim_only and dim_only_table:
            # 单维度表查询，无需 JOIN
            print(f"[维度表优化] 跳过 Neo4j 查询，使用单表: {dim_only_table}")
            return [{
                "base": dim_only_table,
                "targets": [],
                "edges": []
            }]

        # 2) 选择 base 表
        if candidate_fact_tables:
            # 有事实表：选择第一个事实表作为 base（按相似度排序）
            base_tables = sorted(
                candidate_fact_tables,
                key=lambda t: table_similarities.get(t, 0.0),
                reverse=True,
            )
        elif candidate_dim_tables:
            # 只有维度表：通过连通性分析选择 base（参考 docs/13:798-829）
            base_tables = self._select_best_dim_base(
                candidate_dim_tables,
                table_similarities
            )
        else:
            # 无候选表
            return []

        # 3) 对每个 base 表查询 JOIN 路径
        join_plans = []
        for base in base_tables[:1]:  # 只使用最优的 base
            # 确定 targets
            targets = [t for t in all_tables if t != base]

            if not targets:
                # 只有一个表，无需 JOIN
                print(f"[JOIN规划] 只有一个表 {base}，无需JOIN")
                join_plans.append({
                    "base": base,
                    "targets": [],
                    "edges": []
                })
                continue

            # 查询 Neo4j 获取 JOIN 路径
            print(f"[JOIN规划] 准备查询: base={base}, targets={targets}")
            try:
                path_map = self._plan_join_paths_for_base(
                    base_table=base,
                    target_tables=targets,
                )

                # 构建 edges
                edges = []
                seen = set()
                for target in targets:
                    path = path_map.get(target) or []
                    for edge in path:
                        key = (edge["src_table"], edge["dst_table"])
                        if key not in seen:
                            edges.append(edge)
                            seen.add(key)

                join_plans.append({
                    "base": base,
                    "targets": targets,
                    "edges": edges
                })
            except Exception as e:
                print(f"[JOIN规划] base={base} 查询失败: {e}")
                continue

        # 如果未生成计划且只有一个表，提供兜底
        if not join_plans and len(all_tables) == 1:
            return [{"base": all_tables[0], "targets": [], "edges": []}]

        return join_plans

    def _should_use_dimension_only(
        self,
        parse_result: Optional[Dict[str, Any]],
        fact_tables: List[str],
        dim_tables: List[str],
        table_similarities: Dict[str, float],
    ) -> tuple[bool, Optional[str]]:
        """
        判断是否可以只用维度表
        
        参考 docs/13:727-784
        
        Returns:
            (should_use_dim_only, dim_table_to_use)
        """
        # 规则1: 有时间约束，通常需要事实表
        if parse_result and parse_result.get("time"):
            return False, None

        # 规则2: 没有维度表候选
        if not dim_tables:
            return False, None

        # 规则3: 纯维度表场景
        if not fact_tables:
            if len(dim_tables) == 1:
                return True, dim_tables[0]
            else:
                # 多个维度表，需要通过 Neo4j 判断关系
                return False, None

        # 规则4: 相似度差异判断
        if not table_similarities:
            return False, None

        best_dim_table, best_dim_sim = max(
            [(t, table_similarities.get(t, 0)) for t in dim_tables],
            key=lambda x: x[1]
        )
        best_fact_table, best_fact_sim = max(
            [(t, table_similarities.get(t, 0)) for t in fact_tables],
            key=lambda x: x[1]
        )

        # 相似度差距阈值（默认 0.05）
        similarity_gap_threshold = self.config.get("schema_retrieval", {}).get(
            "similarity_gap_threshold", 0.05
        )

        if best_dim_sim > best_fact_sim + similarity_gap_threshold:
            if len(dim_tables) == 1:
                return True, best_dim_table

        return False, None

    def _select_best_dim_base(
        self,
        dim_tables: List[str],
        table_similarities: Dict[str, float],
    ) -> List[str]:
        """
        多维度表场景下，通过连通性分析选择最优 base
        
        参考 docs/13:798-829
        
        Returns:
            [best_base_table]  # 只返回一个
        """
        if len(dim_tables) == 1:
            return dim_tables

        best_base = None
        max_connections = -1
        best_similarity = 0.0

        for candidate_base in dim_tables:
            candidate_targets = [t for t in dim_tables if t != candidate_base]

            try:
                path_map = self._plan_join_paths_for_base(
                    base_table=candidate_base,
                    target_tables=candidate_targets,
                )
                connections = sum(1 for t in candidate_targets if path_map.get(t))
                similarity = table_similarities.get(candidate_base, 0.0)

                # 选择连接数最多的；如果连接数相同，选择相似度最高的
                if connections > max_connections or \
                   (connections == max_connections and similarity > best_similarity):
                    best_base = candidate_base
                    max_connections = connections
                    best_similarity = similarity
            except Exception as e:
                print(f"[连通性分析] base={candidate_base} 查询失败: {e}")
                continue

        return [best_base] if best_base else dim_tables[:1]

    def _plan_join_paths_for_base(
        self,
        base_table: str,
        target_tables: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        包装现有 plan_join_paths 接口，提供 target→edges 映射
        
        参考文档第635-657行
        
        Args:
            base_table: Base 表
            target_tables: 目标表列表
            
        Returns:
            {target_table: [edge1, edge2, ...]}
        """
        if not target_tables:
            return {}

        plans = self.neo4j_client.plan_join_paths(
            base_tables=[base_table],
            target_tables=target_tables,
            max_hops=self.join_max_hops,
            strategy=self.config.get("schema_retrieval", {}).get("join_strategy", "apoc_dijkstra"),
        )

        # 现有实现返回 List[Dict]，需转换为 {target: edges}
        edges_map: Dict[str, List[Dict[str, Any]]] = {}
        
        if not plans:
            return edges_map
            
        for plan in plans:
            if plan.get("base") != base_table:
                continue
            
            # 提取所有边
            all_edges = plan.get("edges", [])
            
            # 为每个 target 构建到达它的路径
            for target in target_tables:
                # 简化实现：返回所有边（完整实现需要路径追踪）
                # 这里假设 Neo4j 返回的 edges 已经按路径组织
                edges_map[target] = all_edges
                
        return edges_map

    def _retrieve_column_dimension_hits(
        self,
        parse_result: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """根据 role='column' 维度文本检索匹配列，补充候选表。

        对 parse_result 中 role='column' 的维度（如"城市"），生成 embedding
        并在 table_schema_embeddings 中搜索 object_type='column'，返回命中列
        及其父表信息。

        Returns:
            命中列列表，每个元素包含 object_id, table_name, similarity,
            table_category（空，需后续补全）, source_dimension_text。
        """
        qlog = with_query_id(logger, "")

        if not parse_result:
            return []

        dimensions = parse_result.get("dimensions") or []
        if not dimensions:
            return []

        # 1) 筛选 role="column" 的条目，按 text 去重
        seen_texts = set()
        column_dimensions = []
        for dim in dimensions:
            if dim.get("role") != "column":
                continue
            text = (dim.get("text") or "").strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            column_dimensions.append(text)

        if not column_dimensions:
            return []

        qlog.debug(f"column dimension 检索: {column_dimensions}")

        # 2) 逐个检索
        all_hits: List[Dict[str, Any]] = []
        for text in column_dimensions:
            embedding = self.embedding_client.embed_query(text)
            matches = self.vector_client.search_columns(
                embedding=embedding,
                top_k=self.topk_columns,
                similarity_threshold=self.similarity_threshold,
            )
            qlog.debug(
                f"column dimension '{text}' 命中 {len(matches)} 列: "
                f"{[m['object_id'] for m in matches]}"
            )
            for m in matches:
                m["source_dimension_text"] = text
            all_hits.extend(matches)

        return all_hits

    def _retrieve_dim_value_hits(
        self,
        parse_result: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """根据解析结果检索维度值命中"""

        if not parse_result:
            return []

        dimensions = parse_result.get("dimensions") or []
        if not dimensions:
            return []

        # 构造与 value_matcher 兼容的结构
        parsed_dimensions = []
        for idx, dim in enumerate(dimensions):
            if dim.get("role") != "value":
                continue
            text = (dim.get("text") or "").strip()
            if not text:
                continue
            parsed_dimensions.append({
                "text": text,
                "role": "value",
                "source_index": idx,
            })

        if not parsed_dimensions:
            return []

        all_matches: List[Dict[str, Any]] = []
        for dv in parsed_dimensions:
            query_value = dv["text"]
            matches = self.vector_client.search_dim_values(
                query_value=query_value,
                top_k=self.dim_index_topk,
                min_score=self.dim_value_min_score,
            )
            enriched = add_source_index_to_matches(
                matches=matches,
                query_value=query_value,
                dimension_values=parsed_dimensions,
            )
            for hit in enriched:
                hit.setdefault("source_text", query_value)
            all_matches.extend(enriched)

        return all_matches

    def get_retrieval_stats(self, schema_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取检索统计信息

        Args:
            schema_context: Schema 上下文

        Returns:
            统计信息
        """
        metadata = schema_context.get("metadata", {})

        return {
            # ✅ 从 metadata 中读取预计算的统计值
            "table_count": metadata.get("table_count", 0),
            "column_count": metadata.get("column_count", 0),

            # ✅ 从实际列表计算长度（兼容性考虑）
            "join_plan_count": len(schema_context.get("join_plans", [])),
            "similar_sql_count": len(schema_context.get("similar_sqls", [])),
            "dim_match_count": len(schema_context.get("dim_value_hits", [])),

            # ✅ 从 metadata 读取
            "retrieval_time": metadata.get("retrieval_time", 0),
        }


# 便捷函数

def retrieve_schema(
    query: str,
    parse_result: Optional[Dict[str, Any]] = None,
    config: Dict[str, Any] = None,
    *,
    parse_hints: Optional[Dict[str, Any]] = None,
    query_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    检索 Schema 上下文（便捷函数）

    Args:
        query: 子查询文本
        parse_result: 解析结果
        config: 检索配置
        parse_hints: 解析提示
        query_id: 查询 ID（用于日志）

    Returns:
        Schema 上下文字典（包含 similar_sqls）
    """
    retriever = SchemaRetriever(config)
    return retriever.retrieve(
        query=query,
        parse_result=parse_result,
        parse_hints=parse_hints,
        query_id=query_id,
    )
