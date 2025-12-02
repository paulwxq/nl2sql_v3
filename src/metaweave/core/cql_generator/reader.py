"""Step 4 JSON 读取器

读取 Step 2 的表/列画像 JSON 和 Step 3 的表间关系 JSON。
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple

from src.metaweave.core.cql_generator.models import (
    TableNode,
    ColumnNode,
    HASColumnRelation,
    JOINOnRelation
)

logger = logging.getLogger("metaweave.cql_generator.reader")


class JSONReader:
    """JSON 文件读取器

    负责读取 Step 2 和 Step 3 的 JSON 文件，并转换为内部数据模型。
    """

    def __init__(self, json_dir: Path, rel_dir: Path):
        """初始化读取器

        Args:
            json_dir: Step 2 JSON 目录（表/列画像）
            rel_dir: Step 3 JSON 目录（表间关系）
        """
        self.json_dir = Path(json_dir)
        self.rel_dir = Path(rel_dir)

        if not self.json_dir.exists():
            raise ValueError(f"JSON 目录不存在: {self.json_dir}")
        if not self.rel_dir.exists():
            raise ValueError(f"关系目录不存在: {self.rel_dir}")

    def read_all(self) -> Tuple[
        List[TableNode],
        List[ColumnNode],
        List[HASColumnRelation],
        List[JOINOnRelation]
    ]:
        """读取所有数据

        Returns:
            (tables, columns, has_column_rels, join_on_rels)
        """
        logger.info("开始读取 Step 2 和 Step 3 的 JSON 文件...")

        # 读取 Step 2 表/列画像
        tables, columns, has_column_rels = self._read_table_profiles()

        # 读取 Step 3 表间关系
        join_on_rels = self._read_relationships()

        # 注意：不再动态回填 logic_fk
        # logic_fk 保持 Step 2 画像中的初始值（通常为空列表）
        # 关系方向已在 Step 3 输出时翻转为标准 ER 语义

        logger.info(
            f"读取完成: "
            f"{len(tables)} 张表, "
            f"{len(columns)} 个列, "
            f"{len(join_on_rels)} 个关系"
        )

        return tables, columns, has_column_rels, join_on_rels

    def _read_table_profiles(self) -> Tuple[
        List[TableNode],
        List[ColumnNode],
        List[HASColumnRelation]
    ]:
        """读取 Step 2 表/列画像

        Returns:
            (tables, columns, has_column_rels)
        """
        tables = []
        columns = []
        has_column_rels = []

        # 获取所有 JSON 文件，但过滤掉模板文件
        all_json_files = list(self.json_dir.glob("*.json"))
        json_files = []

        for f in all_json_files:
            # 跳过以 _ 或 . 开头的文件（模板文件和隐藏文件）
            if f.name.startswith("_") or f.name.startswith("."):
                logger.debug(f"跳过模板文件: {f.name}")
                continue
            json_files.append(f)

        logger.info(
            f"找到 {len(json_files)} 个有效 JSON 文件"
            f"（已过滤 {len(all_json_files) - len(json_files)} 个模板文件）"
        )

        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 验证表名不是占位符
                table_info = data.get("table_info", {})
                table_name = table_info.get("table_name", "")

                if not table_name or table_name in ["table_name", "placeholder", "example"]:
                    logger.warning(
                        f"跳过占位符表: {json_file.name} (table_name={table_name})"
                    )
                    continue

                # 提取表信息
                table = self._extract_table(data)
                tables.append(table)

                # 提取列信息
                table_columns = self._extract_columns(data, table.full_name)
                columns.extend(table_columns)

                # 创建 HAS_COLUMN 关系
                for col in table_columns:
                    has_column_rels.append(
                        HASColumnRelation(
                            table_full_name=table.full_name,
                            column_full_name=col.full_name
                        )
                    )

            except Exception as e:
                logger.error(f"读取文件失败: {json_file}, 错误: {e}")
                raise

        return tables, columns, has_column_rels

    def _extract_table(self, data: Dict[str, Any]) -> TableNode:
        """从 JSON 中提取表信息"""
        table_info = data.get("table_info", {})
        table_profile = data.get("table_profile", {})
        physical_constraints = table_profile.get("physical_constraints", {})
        logical_keys = table_profile.get("logical_keys", {})

        schema = table_info.get("schema_name", "")
        name = table_info.get("table_name", "")
        full_name = f"{schema}.{name}"

        # 提取物理主键（符合 list<string> 规范）
        pk_data = physical_constraints.get("primary_key")
        if pk_data and isinstance(pk_data, dict):
            # Step 2 格式: {"constraint_name": "...", "columns": [...]}
            pk = pk_data.get("columns", [])
        elif pk_data and isinstance(pk_data, list):
            # 已经是列表格式
            pk = pk_data
        else:
            pk = []

        # 提取唯一约束（符合 list<list<string>> 规范）
        uk = []
        for uk_data in physical_constraints.get("unique_constraints", []):
            if isinstance(uk_data, dict):
                # Step 2 格式: {"constraint_name": "...", "columns": [...]}
                columns = uk_data.get("columns", [])
                if columns:
                    uk.append(columns)
            elif isinstance(uk_data, list):
                # 已经是列表格式
                if uk_data:
                    uk.append(uk_data)

        # 提取外键（转换为字典列表）
        fk = []
        for fk_data in physical_constraints.get("foreign_keys", []):
            fk.append({
                "constraint_name": fk_data.get("constraint_name", ""),
                "source_columns": fk_data.get("source_columns", []),
                "target_schema": fk_data.get("target_schema", ""),
                "target_table": fk_data.get("target_table", ""),
                "target_columns": fk_data.get("target_columns", [])
            })

        # 提取索引（只保留列名列表，符合 list<list<string>> 规范）
        indexes = []
        for idx_data in physical_constraints.get("indexes", []):
            columns = idx_data.get("columns", [])
            if columns:  # 只添加非空的列列表
                indexes.append(columns)

        # 提取候选逻辑主键（confidence >= 0.8）
        logic_pk = []
        for candidate in logical_keys.get("candidate_primary_keys", []):
            confidence = candidate.get("confidence_score", 0.0)
            if confidence >= 0.8:
                logic_pk.append(candidate.get("columns", []))

        return TableNode(
            full_name=full_name,
            schema=schema,
            name=name,
            comment=table_info.get("comment"),
            pk=pk,
            uk=uk,
            fk=fk,
            logic_pk=logic_pk,
            logic_fk=[],  # 稍后从关系中填充
            logic_uk=[],  # 预留
            indexes=indexes
        )

    def _extract_columns(
        self,
        data: Dict[str, Any],
        table_full_name: str
    ) -> List[ColumnNode]:
        """从 JSON 中提取列信息"""
        table_info = data.get("table_info", {})
        schema = table_info.get("schema_name", "")
        table_name = table_info.get("table_name", "")

        column_profiles = data.get("column_profiles", {})
        table_profile = data.get("table_profile", {})
        physical_constraints = table_profile.get("physical_constraints", {})

        # 获取物理主键列表（提取 columns 字段）
        pk_data = physical_constraints.get("primary_key")
        if pk_data and isinstance(pk_data, dict):
            # Step 2 格式: {"constraint_name": "...", "columns": [...]}
            pk_columns = pk_data.get("columns", [])
        elif pk_data and isinstance(pk_data, list):
            # 已经是列表格式
            pk_columns = pk_data
        else:
            pk_columns = []

        # 获取唯一约束列表（扁平化，提取 columns 字段）
        uk_columns = set()
        for uk_data in physical_constraints.get("unique_constraints", []):
            if isinstance(uk_data, dict):
                # Step 2 格式: {"constraint_name": "...", "columns": [...]}
                columns = uk_data.get("columns", [])
                uk_columns.update(columns)
            elif isinstance(uk_data, list):
                # 已经是列表格式
                uk_columns.update(uk_data)

        # 获取外键列表（扁平化）
        fk_columns = set()
        for fk_data in physical_constraints.get("foreign_keys", []):
            fk_columns.update(fk_data.get("source_columns", []))

        columns = []
        for col_name, col_data in column_profiles.items():
            # 基本信息
            full_name = f"{schema}.{table_name}.{col_name}"
            data_type = col_data.get("data_type", "")
            comment = col_data.get("comment")

            # 语义角色
            semantic_analysis = col_data.get("semantic_analysis", {})
            semantic_role = semantic_analysis.get("semantic_role")

            # 结构标志
            structure_flags = col_data.get("structure_flags", {})

            # 判断是否是主键/唯一键/外键
            is_pk = col_name in pk_columns
            is_uk = col_name in uk_columns
            is_fk = col_name in fk_columns

            # 判断是否是时间/度量字段
            is_time = semantic_role == "datetime"
            is_measure = semantic_role == "metric"

            # 主键位置
            pk_position = 0
            if is_pk and col_name in pk_columns:
                pk_position = pk_columns.index(col_name) + 1

            # 统计信息
            statistics = col_data.get("statistics", {})
            uniqueness = statistics.get("uniqueness", 0.0)
            null_rate = statistics.get("null_rate", 0.0)

            columns.append(
                ColumnNode(
                    full_name=full_name,
                    schema=schema,
                    table=table_name,
                    name=col_name,
                    data_type=data_type,
                    comment=comment,
                    semantic_role=semantic_role,
                    is_pk=is_pk,
                    is_uk=is_uk,
                    is_fk=is_fk,
                    is_time=is_time,
                    is_measure=is_measure,
                    pk_position=pk_position,
                    uniqueness=uniqueness,
                    null_rate=null_rate
                )
            )

        return columns

    def _read_relationships(self) -> List[JOINOnRelation]:
        """读取 Step 3 表间关系"""
        join_on_rels = []

        # 查找关系 JSON 文件（通常是 relationships_global.json）
        rel_files = list(self.rel_dir.glob("relationships_*.json"))
        if not rel_files:
            logger.warning(f"未找到关系文件: {self.rel_dir}/relationships_*.json")
            return []

        logger.info(f"找到 {len(rel_files)} 个关系文件")

        for rel_file in rel_files:
            try:
                with open(rel_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                relationships = data.get("relationships", [])
                logger.info(f"从 {rel_file.name} 读取 {len(relationships)} 个关系")

                for rel in relationships:
                    join_rel = self._extract_join_relation(rel)
                    if join_rel:
                        join_on_rels.append(join_rel)

            except Exception as e:
                logger.error(f"读取关系文件失败: {rel_file}, 错误: {e}")
                raise

        return join_on_rels

    def _extract_join_relation(self, rel: Dict[str, Any]) -> JOINOnRelation:
        """从关系 JSON 中提取 JOIN_ON 关系

        **重要说明**：
        - 输入语义（relationships_global.json）：from=主键表（发现驱动表），to=外键表（被查找的表）
        - 输出语义（CQL）：src=外键表（引用端），dst=主键表（被引用端）
        - 此方法在读取时翻转语义，确保 CQL 符合标准 ER 关系语义
        """
        # 读取原始的 from/to（发现语义）
        from_table = rel.get("from_table", {})  # 主键表（发现语义）
        to_table = rel.get("to_table", {})      # 外键表（发现语义）

        # 翻转为 ER 语义：src=外键表，dst=主键表
        src_schema = to_table.get("schema", "")   # 外键表（翻转）
        src_table = to_table.get("table", "")
        dst_schema = from_table.get("schema", "") # 主键表（翻转）
        dst_table = from_table.get("table", "")

        src_full_name = f"{src_schema}.{src_table}"  # 外键表
        dst_full_name = f"{dst_schema}.{dst_table}"  # 主键表

        # 列信息（同样翻转）
        rel_type = rel.get("type", "")
        if rel_type == "single_column":
            source_columns = [rel.get("to_column", "")]    # 外键列（翻转）
            target_columns = [rel.get("from_column", "")]  # 主键列（翻转）
        else:  # composite
            source_columns = rel.get("to_columns", [])     # 外键列（翻转）
            target_columns = rel.get("from_columns", [])   # 主键列（翻转）

        # 基数翻转（方向翻转时需同步翻转基数）
        raw_cardinality = rel.get("cardinality", "N:1")
        cardinality = self._flip_cardinality(raw_cardinality)
        logger.debug(f"基数翻转: {raw_cardinality} -> {cardinality} ({src_full_name} -> {dst_full_name})")

        # 约束名（仅外键直通才有）
        constraint_name = rel.get("constraint_name")

        # 构造 ON 表达式
        on_parts = []
        for src_col, tgt_col in zip(source_columns, target_columns):
            on_parts.append(f"SRC.{src_col} = DST.{tgt_col}")
        on_expr = " AND ".join(on_parts)

        return JOINOnRelation(
            src_full_name=src_full_name,    # 外键表（ER 语义）
            dst_full_name=dst_full_name,    # 主键表（ER 语义）
            cardinality=cardinality,
            join_type="INNER JOIN",
            on=on_expr,
            source_columns=source_columns,  # 外键列
            target_columns=target_columns,  # 主键列
            constraint_name=constraint_name
        )

    def _flip_cardinality(self, cardinality: str) -> str:
        """翻转基数方向

        当关系方向从 from→to 翻转为 to→from 时，
        基数也需要相应翻转。

        翻转规则：
        - "1:N" → "N:1"（1对多 → 多对1）
        - "N:1" → "1:N"（多对1 → 1对多）
        - "1:1" → "1:1"（对称，不变）
        - "M:N" → "M:N"（对称，不变）

        Args:
            cardinality: 原始基数字符串

        Returns:
            翻转后的基数字符串
        """
        flip_map = {
            "1:N": "N:1",
            "N:1": "1:N",
            "1:1": "1:1",  # 对称，不变
            "M:N": "M:N",  # 对称，不变
        }
        return flip_map.get(cardinality, cardinality)

