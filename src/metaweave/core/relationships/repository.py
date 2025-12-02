"""元数据仓库

负责加载Step 2的JSON元数据文件，并提取外键直通关系。
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any

from src.metaweave.core.relationships.models import Relation
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.repository")


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
        """推断外键关系的基数

        优先级：物理约束 > 统计值

        判断逻辑：
        - 源列唯一 + 目标列唯一 → 1:1
        - 源列唯一 + 目标列不唯一 → 1:N
        - 源列不唯一 + 目标列唯一 → N:1
        - 双方都不唯一 → M:N

        Args:
            fk: 外键信息
            tables: 所有表元数据
            source_full_name: 源表全名
            target_schema: 目标schema
            target_table: 目标表名

        Returns:
            基数（1:1 | 1:N | N:1 | M:N）
        """
        source_columns = fk["source_columns"]
        target_columns = fk.get("target_columns", fk.get("referenced_columns", []))
        target_full_name = f"{target_schema}.{target_table}"

        # 判断源列和目标列的唯一性
        source_is_unique = self._is_columns_unique(tables, source_full_name, source_columns)
        target_is_unique = self._is_columns_unique(tables, target_full_name, target_columns)

        # 判断基数
        if source_is_unique and target_is_unique:
            cardinality = "1:1"
        elif source_is_unique and not target_is_unique:
            cardinality = "1:N"
        elif not source_is_unique and target_is_unique:
            cardinality = "N:1"
        else:
            cardinality = "M:N"

        logger.debug(
            f"外键基数推断: {source_full_name}{source_columns} -> {target_full_name}{target_columns}, "
            f"source_unique={source_is_unique}, target_unique={target_is_unique}, cardinality={cardinality}"
        )

        return cardinality

    def _is_columns_unique(
            self,
            tables: Dict[str, dict],
            full_name: str,
            columns: List[str]
    ) -> bool:
        """判断列（单列或复合列）是否唯一

        优先级：物理约束 > 统计值

        Args:
            tables: 所有表元数据
            full_name: 表全名（schema.table）
            columns: 列名列表

        Returns:
            True: 列是唯一的
            False: 列不唯一或无法判断
        """
        table = tables.get(full_name)
        if not table:
            logger.warning(f"表元数据不存在: {full_name}")
            return False

        profiles = table.get("column_profiles", {})
        table_profile = table.get("table_profile", {})

        # === 1. 检查物理约束（优先） ===

        # 单列情况
        if len(columns) == 1:
            col_name = columns[0]
            col_profile = profiles.get(col_name, {})
            flags = col_profile.get("structure_flags", {})

            # 主键或唯一约束 → 唯一
            if flags.get("is_primary_key") or flags.get("is_unique_constraint"):
                logger.debug(f"{full_name}.{col_name}: 物理约束判定为唯一")
                return True

        # 复合列情况：检查复合主键/唯一约束
        else:
            physical = table_profile.get("physical_constraints", {})

            # 检查复合主键
            pk = physical.get("primary_key")
            if pk and set(pk.get("columns", [])) == set(columns):
                logger.debug(f"{full_name}.{columns}: 复合主键，判定为唯一")
                return True

            # 检查复合唯一约束
            for uk in physical.get("unique_constraints", []):
                if set(uk.get("columns", [])) == set(columns):
                    logger.debug(f"{full_name}.{columns}: 复合唯一约束，判定为唯一")
                    return True

        # === 2. Fallback 到统计值 ===

        HIGH_UNIQUENESS = 0.95  # 与 scorer 使用相同阈值

        if len(columns) == 1:
            col_name = columns[0]
            col_profile = profiles.get(col_name, {})
            stats = col_profile.get("statistics", {})
            uniqueness = stats.get("uniqueness", 0.0)

            if uniqueness >= HIGH_UNIQUENESS:
                logger.debug(f"{full_name}.{col_name}: 统计值 uniqueness={uniqueness:.3f} >= {HIGH_UNIQUENESS}，判定为唯一")
                return True
        else:
            # 复合列：取最小唯一性（保守估计）
            min_uniqueness = 1.0
            for col_name in columns:
                col_profile = profiles.get(col_name, {})
                stats = col_profile.get("statistics", {})
                uniqueness = stats.get("uniqueness", 0.0)
                min_uniqueness = min(min_uniqueness, uniqueness)

            if min_uniqueness >= HIGH_UNIQUENESS:
                logger.debug(f"{full_name}.{columns}: 组合统计值 min_uniqueness={min_uniqueness:.3f} >= {HIGH_UNIQUENESS}，判定为唯一")
                return True

        logger.debug(f"{full_name}.{columns}: 未满足唯一条件")
        return False
