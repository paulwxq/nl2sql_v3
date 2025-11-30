"""Step 4 Cypher 文件写入器

生成符合 v3.2 规范的 Neo4j Cypher 脚本文件。
"""

import json
import logging
from pathlib import Path
from typing import List
from datetime import datetime

from src.metaweave.core.cql_generator.models import (
    TableNode,
    ColumnNode,
    HASColumnRelation,
    JOINOnRelation
)

logger = logging.getLogger("metaweave.cql_generator.writer")


class CypherWriter:
    """Cypher 文件写入器

    负责生成 Neo4j Cypher 脚本文件（.cypher），确保幂等性。
    """

    def __init__(self, output_dir: Path):
        """初始化写入器

        Args:
            output_dir: 输出目录（./output/metaweave/metadata/cql/）
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"初始化 Cypher 写入器，输出目录: {self.output_dir}")

    def write_all(
        self,
        tables: List[TableNode],
        columns: List[ColumnNode],
        has_column_rels: List[HASColumnRelation],
        join_on_rels: List[JOINOnRelation]
    ) -> List[str]:
        """写入 Cypher 文件（默认 global 模式，生成单个完整文件）

        Args:
            tables: Table 节点列表
            columns: Column 节点列表
            has_column_rels: HAS_COLUMN 关系列表
            join_on_rels: JOIN_ON 关系列表

        Returns:
            生成的文件路径列表
        """
        output_files = []

        logger.info("开始生成 Cypher 文件 (global 模式)...")

        # 生成单个完整的 import_all.cypher 文件
        import_all_file = self._write_import_all(
            tables, columns, has_column_rels, join_on_rels
        )
        output_files.append(str(import_all_file))

        logger.info(f"Cypher 文件生成完成: {import_all_file.name}")
        return output_files

    def _write_constraints(self) -> Path:
        """生成 01_constraints.cypher"""
        output_file = self.output_dir / "01_constraints.cypher"

        content = """// 01_constraints.cypher
// 创建唯一约束（幂等）

CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT table_full_name IF NOT EXISTS FOR (t:Table) REQUIRE t.full_name IS UNIQUE;
CREATE CONSTRAINT column_full_name IF NOT EXISTS FOR (c:Column) REQUIRE c.full_name IS UNIQUE;
"""

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"生成约束文件: {output_file}")
        return output_file

    def _write_table_nodes(self, tables: List[TableNode]) -> Path:
        """生成 02_nodes_tables.cypher"""
        output_file = self.output_dir / "02_nodes_tables.cypher"

        # 转换为 Cypher 参数格式
        tables_data = [t.to_cypher_dict() for t in tables]
        tables_json = json.dumps(tables_data, ensure_ascii=False, indent=2)

        content = f"""// 02_nodes_tables.cypher
// 生成 Table 节点（MERGE + SET，确保幂等性）

UNWIND {tables_json} AS t
MERGE (n:Table {{full_name: t.full_name}})
SET n.id       = t.full_name,
    n.schema   = t.schema,
    n.name     = t.name,
    n.comment  = t.comment,
    n.pk       = t.pk,
    n.uk       = t.uk,
    n.fk       = t.fk,
    n.logic_pk = t.logic_pk,
    n.logic_fk = t.logic_fk,
    n.logic_uk = t.logic_uk,
    n.indexes  = t.indexes;
"""

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"生成 Table 节点文件: {output_file} ({len(tables)} 个节点)")
        return output_file

    def _write_column_nodes(self, columns: List[ColumnNode]) -> Path:
        """生成 03_nodes_columns.cypher"""
        output_file = self.output_dir / "03_nodes_columns.cypher"

        # 转换为 Cypher 参数格式
        columns_data = [c.to_cypher_dict() for c in columns]
        columns_json = json.dumps(columns_data, ensure_ascii=False, indent=2)

        content = f"""// 03_nodes_columns.cypher
// 生成 Column 节点（MERGE + SET，确保幂等性）

UNWIND {columns_json} AS c
MERGE (n:Column {{full_name: c.full_name}})
SET n.schema       = c.schema,
    n.table        = c.table,
    n.name         = c.name,
    n.comment      = c.comment,
    n.data_type    = c.data_type,
    n.semantic_role= c.semantic_role,
    n.is_pk        = c.is_pk,
    n.is_uk        = c.is_uk,
    n.is_fk        = c.is_fk,
    n.is_time      = c.is_time,
    n.is_measure   = c.is_measure,
    n.pk_position  = c.pk_position,
    n.uniqueness   = c.uniqueness,
    n.null_rate    = c.null_rate;
"""

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"生成 Column 节点文件: {output_file} ({len(columns)} 个节点)")
        return output_file

    def _write_has_column_rels(self, rels: List[HASColumnRelation]) -> Path:
        """生成 04_rels_has_column.cypher"""
        output_file = self.output_dir / "04_rels_has_column.cypher"

        # 转换为 Cypher 参数格式
        rels_data = [r.to_cypher_dict() for r in rels]
        rels_json = json.dumps(rels_data, ensure_ascii=False, indent=2)

        content = f"""// 04_rels_has_column.cypher
// 建立 HAS_COLUMN 关系（MERGE，确保幂等性）

UNWIND {rels_json} AS hc
MATCH (t:Table {{full_name: hc.table_full_name}})
MATCH (c:Column {{full_name: hc.column_full_name}})
MERGE (t)-[:HAS_COLUMN]->(c);
"""

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"生成 HAS_COLUMN 关系文件: {output_file} ({len(rels)} 个关系)")
        return output_file

    def _write_join_on_rels(self, rels: List[JOINOnRelation]) -> Path:
        """生成 05_rels_join_on.cypher"""
        output_file = self.output_dir / "05_rels_join_on.cypher"

        # 转换为 Cypher 参数格式
        rels_data = [r.to_cypher_dict() for r in rels]
        rels_json = json.dumps(rels_data, ensure_ascii=False, indent=2)

        content = f"""// 05_rels_join_on.cypher
// 建立 JOIN_ON 关系（MERGE + SET，确保幂等性）

UNWIND {rels_json} AS j
MATCH (src:Table {{full_name: j.src_full_name}})
MATCH (dst:Table {{full_name: j.dst_full_name}})
MERGE (src)-[r:JOIN_ON]->(dst)
SET r.cardinality     = j.cardinality,
    r.constraint_name = j.constraint_name,
    r.join_type       = coalesce(j.join_type, 'INNER JOIN'),
    r.on              = j.on,
    r.source_columns  = j.source_columns,
    r.target_columns  = j.target_columns;
"""

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"生成 JOIN_ON 关系文件: {output_file} ({len(rels)} 个关系)")
        return output_file

    def _write_import_all(
        self,
        tables: List[TableNode],
        columns: List[ColumnNode],
        has_column_rels: List[HASColumnRelation],
        join_on_rels: List[JOINOnRelation]
    ) -> Path:
        """生成 import_all.cypher（完整的 global 模式 CQL 脚本）"""
        output_file = self.output_dir / "import_all.cypher"

        timestamp = datetime.now().isoformat()

        # 转换为 Cypher 参数格式
        tables_data = [t.to_cypher_dict() for t in tables]
        columns_data = [c.to_cypher_dict() for c in columns]
        has_column_data = [r.to_cypher_dict() for r in has_column_rels]
        join_on_data = [r.to_cypher_dict() for r in join_on_rels]

        tables_json = json.dumps(tables_data, ensure_ascii=False, indent=2)
        columns_json = json.dumps(columns_data, ensure_ascii=False, indent=2)
        has_column_json = json.dumps(has_column_data, ensure_ascii=False, indent=2)
        join_on_json = json.dumps(join_on_data, ensure_ascii=False, indent=2)

        content = f"""// import_all.cypher
// Neo4j 元数据导入脚本（global 模式，包含所有表和关系）
// 生成时间: {timestamp}
// 统计: {len(tables)} 张表, {len(columns)} 个列, {len(join_on_rels)} 个关系

// =====================================================================
// 1. 创建唯一约束
// =====================================================================

CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT table_full_name IF NOT EXISTS FOR (t:Table) REQUIRE t.full_name IS UNIQUE;
CREATE CONSTRAINT column_full_name IF NOT EXISTS FOR (c:Column) REQUIRE c.full_name IS UNIQUE;

// =====================================================================
// 2. 创建 Table 节点
// =====================================================================

UNWIND {tables_json} AS t
MERGE (n:Table {{full_name: t.full_name}})
SET n.id       = t.full_name,
    n.schema   = t.schema,
    n.name     = t.name,
    n.comment  = t.comment,
    n.pk       = t.pk,
    n.uk       = t.uk,
    n.fk       = t.fk,
    n.logic_pk = t.logic_pk,
    n.logic_fk = t.logic_fk,
    n.logic_uk = t.logic_uk,
    n.indexes  = t.indexes;

// =====================================================================
// 3. 创建 Column 节点
// =====================================================================

UNWIND {columns_json} AS c
MERGE (n:Column {{full_name: c.full_name}})
SET n.schema       = c.schema,
    n.table        = c.table,
    n.name         = c.name,
    n.comment      = c.comment,
    n.data_type    = c.data_type,
    n.semantic_role= c.semantic_role,
    n.is_pk        = c.is_pk,
    n.is_uk        = c.is_uk,
    n.is_fk        = c.is_fk,
    n.is_time      = c.is_time,
    n.is_measure   = c.is_measure,
    n.pk_position  = c.pk_position,
    n.uniqueness   = c.uniqueness,
    n.null_rate    = c.null_rate;

// =====================================================================
// 4. 建立 HAS_COLUMN 关系
// =====================================================================

UNWIND {has_column_json} AS hc
MATCH (t:Table {{full_name: hc.table_full_name}})
MATCH (c:Column {{full_name: hc.column_full_name}})
MERGE (t)-[:HAS_COLUMN]->(c);

// =====================================================================
// 5. 建立 JOIN_ON 关系
// =====================================================================

UNWIND {join_on_json} AS j
MATCH (src:Table {{full_name: j.src_full_name}})
MATCH (dst:Table {{full_name: j.dst_full_name}})
MERGE (src)-[r:JOIN_ON]->(dst)
SET r.cardinality     = j.cardinality,
    r.constraint_name = j.constraint_name,
    r.join_type       = coalesce(j.join_type, 'INNER JOIN'),
    r.on              = j.on,
    r.source_columns  = j.source_columns,
    r.target_columns  = j.target_columns;
"""

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"生成 global 模式 CQL 脚本: {output_file}")
        return output_file
