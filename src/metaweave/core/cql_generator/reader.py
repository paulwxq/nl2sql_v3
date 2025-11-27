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

        # 更新 Table.logic_fk（从关系中提取）
        self._update_logic_fk(tables, join_on_rels)

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

        json_files = list(self.json_dir.glob("*.json"))
        logger.info(f"找到 {len(json_files)} 个 JSON 文件")

        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

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

        # 提取物理主键
        pk = physical_constraints.get("primary_key") or []
        if not isinstance(pk, list):
            pk = [pk] if pk else []

        # 提取唯一约束
        uk = physical_constraints.get("unique_constraints", [])

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

        # 提取索引
        indexes = physical_constraints.get("indexes", [])

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

        # 获取物理主键列表
        pk_columns = physical_constraints.get("primary_key") or []
        if not isinstance(pk_columns, list):
            pk_columns = [pk_columns] if pk_columns else []

        # 获取唯一约束列表（扁平化）
        uk_columns = set()
        for uk_list in physical_constraints.get("unique_constraints", []):
            uk_columns.update(uk_list)

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
        """从关系 JSON 中提取 JOIN_ON 关系"""
        # 源表和目标表
        from_table = rel.get("from_table", {})
        to_table = rel.get("to_table", {})

        src_schema = from_table.get("schema", "")
        src_table = from_table.get("table", "")
        dst_schema = to_table.get("schema", "")
        dst_table = to_table.get("table", "")

        src_full_name = f"{src_schema}.{src_table}"
        dst_full_name = f"{dst_schema}.{dst_table}"

        # 列信息
        rel_type = rel.get("type", "")
        if rel_type == "single_column":
            source_columns = [rel.get("from_column", "")]
            target_columns = [rel.get("to_column", "")]
        else:  # composite
            source_columns = rel.get("from_columns", [])
            target_columns = rel.get("to_columns", [])

        # 基数（默认 N:1）
        cardinality = rel.get("cardinality", "N:1")

        # 约束名（仅外键直通才有）
        constraint_name = rel.get("constraint_name")

        # 构造 ON 表达式
        on_parts = []
        for src_col, tgt_col in zip(source_columns, target_columns):
            on_parts.append(f"SRC.{src_col} = DST.{tgt_col}")
        on_expr = " AND ".join(on_parts)

        return JOINOnRelation(
            src_full_name=src_full_name,
            dst_full_name=dst_full_name,
            cardinality=cardinality,
            join_type="INNER JOIN",
            on=on_expr,
            source_columns=source_columns,
            target_columns=target_columns,
            constraint_name=constraint_name
        )

    def _update_logic_fk(
        self,
        tables: List[TableNode],
        join_rels: List[JOINOnRelation]
    ):
        """更新 Table.logic_fk（从关系中提取源端列集合）"""
        # 构建表索引
        table_dict = {t.full_name: t for t in tables}

        # 遍历关系，更新源表的 logic_fk
        for rel in join_rels:
            src_table = table_dict.get(rel.src_full_name)
            if src_table:
                # 将源端列集合添加到 logic_fk
                if rel.source_columns and rel.source_columns not in src_table.logic_fk:
                    src_table.logic_fk.append(rel.source_columns)
