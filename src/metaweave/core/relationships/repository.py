"""元数据仓库

负责加载Step 2的JSON元数据文件，并提取外键直通关系。
"""

import json
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any

from src.metaweave.core.relationships.models import Relation

logger = logging.getLogger("metaweave.relationships.repository")


class MetadataRepository:
    """元数据仓库

    负责：
    1. 加载所有JSON元数据文件
    2. 提取外键直通关系
    3. 生成确定性relationship_id
    """

    def __init__(self, json_dir: Path, rel_id_salt: str = ""):
        """初始化元数据仓库

        Args:
            json_dir: JSON文件目录（Step 2输出）
            rel_id_salt: relationship_id哈希盐（用于命名空间隔离）
        """
        self.json_dir = Path(json_dir)
        self.rel_id_salt = rel_id_salt

        if not self.json_dir.exists():
            raise FileNotFoundError(f"JSON目录不存在: {self.json_dir}")

        logger.info(f"元数据仓库已初始化: {self.json_dir}")

    def load_all_tables(self) -> Dict[str, dict]:
        """加载所有JSON元数据文件

        Returns:
            {full_name: json_data} 字典，其中full_name为"schema.table"
        """
        tables = {}
        json_files = list(self.json_dir.glob("*.json"))

        # 排除模板文件
        json_files = [f for f in json_files if not f.name.startswith("_template")]

        logger.info(f"发现 {len(json_files)} 个JSON文件")

        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                table_info = data.get("table_info", {})
                schema_name = table_info.get("schema_name")
                table_name = table_info.get("table_name")

                if not schema_name or not table_name:
                    logger.warning(f"JSON文件缺少schema_name或table_name: {json_file}")
                    continue

                full_name = f"{schema_name}.{table_name}"
                tables[full_name] = data

                logger.debug(f"加载表: {full_name}")

            except Exception as e:
                logger.error(f"加载JSON文件失败 ({json_file}): {e}")

        logger.info(f"成功加载 {len(tables)} 张表的元数据")
        return tables

    def collect_foreign_keys(self, tables: Dict[str, dict]) -> Tuple[List[Relation], Set[str]]:
        """从JSON元数据中提取外键直通关系

        Args:
            tables: 表元数据字典 {full_name: json_data}

        Returns:
            (pre_existing_relations, fk_signature_set)
            - pre_existing_relations: 外键直通关系列表
            - fk_signature_set: FK签名集合（用于后续候选去重）
        """
        pre_existing_relations: List[Relation] = []
        fk_signature_set: Set[str] = set()

        for full_name, table_data in tables.items():
            table_info = table_data.get("table_info", {})
            source_schema = table_info.get("schema_name")
            source_table = table_info.get("table_name")

            # 从table_profile.physical_constraints.foreign_keys提取
            table_profile = table_data.get("table_profile")
            if not table_profile:
                continue

            physical_constraints = table_profile.get("physical_constraints", {})
            foreign_keys = physical_constraints.get("foreign_keys", [])

            if not foreign_keys:
                continue

            for fk in foreign_keys:
                try:
                    source_columns = fk.get("source_columns", [])
                    target_schema = fk.get("target_schema")
                    target_table = fk.get("target_table")
                    target_columns = fk.get("target_columns", [])

                    if not all([source_columns, target_schema, target_table, target_columns]):
                        logger.warning(f"外键信息不完整: {fk}")
                        continue

                    # 生成relationship_id
                    rel_id = self._generate_relation_id(
                        source_schema, source_table, source_columns,
                        target_schema, target_table, target_columns
                    )

                    # 生成FK签名（用于去重）
                    fk_sig = self._generate_fk_signature(
                        source_schema, source_table, source_columns,
                        target_schema, target_table, target_columns
                    )

                    # 创建Relation对象
                    relation = Relation(
                        relationship_id=rel_id,
                        source_schema=source_schema,
                        source_table=source_table,
                        source_columns=source_columns,
                        target_schema=target_schema,
                        target_table=target_table,
                        target_columns=target_columns,
                        relationship_type="foreign_key",
                        cardinality=self._infer_cardinality(fk, tables, full_name, target_schema, target_table)
                    )

                    pre_existing_relations.append(relation)
                    fk_signature_set.add(fk_sig)

                    logger.debug(f"外键直通: {source_schema}.{source_table}.{source_columns} -> "
                                 f"{target_schema}.{target_table}.{target_columns}")

                except Exception as e:
                    logger.error(f"处理外键失败 ({full_name}): {e}")

        logger.info(f"提取到 {len(pre_existing_relations)} 个外键直通关系")
        return pre_existing_relations, fk_signature_set

    @staticmethod
    def compute_relationship_id(
            source_schema: str,
            source_table: str,
            source_columns: List[str],
            target_schema: str,
            target_table: str,
            target_columns: List[str],
            rel_id_salt: str = ""
    ) -> str:
        """生成确定性relationship_id（静态方法，可复用）

        格式: rel_ + MD5[:12]

        Args:
            source_schema: 源schema
            source_table: 源表
            source_columns: 源列列表
            target_schema: 目标schema
            target_table: 目标表
            target_columns: 目标列列表
            rel_id_salt: 哈希盐（用于命名空间隔离）

        Returns:
            relationship_id（格式: rel_abc123def456）
        """
        # 列名排序确保一致性（不同顺序应生成相同ID）
        src_cols = sorted(source_columns)
        tgt_cols = sorted(target_columns)

        # 构建签名字符串
        signature = (
            f"{source_schema}.{source_table}.[{','.join(src_cols)}]->"
            f"{target_schema}.{target_table}.[{','.join(tgt_cols)}]"
            f"{rel_id_salt}"
        )

        # MD5哈希
        hash_digest = hashlib.md5(signature.encode("utf-8")).hexdigest()
        return f"rel_{hash_digest[:12]}"

    def _generate_relation_id(
            self,
            source_schema: str,
            source_table: str,
            source_columns: List[str],
            target_schema: str,
            target_table: str,
            target_columns: List[str]
    ) -> str:
        """生成确定性relationship_id（实例方法，调用静态方法）

        Args:
            source_schema: 源schema
            source_table: 源表
            source_columns: 源列列表
            target_schema: 目标schema
            target_table: 目标表
            target_columns: 目标列列表

        Returns:
            relationship_id（格式: rel_abc123def456）
        """
        return self.compute_relationship_id(
            source_schema=source_schema,
            source_table=source_table,
            source_columns=source_columns,
            target_schema=target_schema,
            target_table=target_table,
            target_columns=target_columns,
            rel_id_salt=self.rel_id_salt
        )

    def _generate_fk_signature(
            self,
            source_schema: str,
            source_table: str,
            source_columns: List[str],
            target_schema: str,
            target_table: str,
            target_columns: List[str]
    ) -> str:
        """生成FK签名（用于候选去重）

        Args:
            source_schema: 源schema
            source_table: 源表
            source_columns: 源列列表
            target_schema: 目标schema
            target_table: 目标表
            target_columns: 目标列列表

        Returns:
            FK签名字符串
        """
        src_cols = sorted(source_columns)
        tgt_cols = sorted(target_columns)

        return (
            f"{source_schema}.{source_table}.[{','.join(src_cols)}]->"
            f"{target_schema}.{target_table}.[{','.join(tgt_cols)}]"
        )

    def _infer_cardinality(
            self,
            fk: Dict[str, Any],
            tables: Dict[str, dict],
            source_full_name: str,
            target_schema: str,
            target_table: str
    ) -> str:
        """推断关系基数

        规则：
        - 如果源列是唯一约束/主键 -> 1:1
        - 如果目标列是唯一约束/主键 -> N:1（默认）
        - 其他情况 -> M:N

        Args:
            fk: 外键信息
            tables: 所有表元数据
            source_full_name: 源表全名
            target_schema: 目标schema
            target_table: 目标表名

        Returns:
            基数（1:1 | 1:N | N:1 | M:N）
        """
        # 简化实现：默认N:1（大多数外键都是多对一）
        # Phase 2可以通过检查uniqueness完善
        return "N:1"
