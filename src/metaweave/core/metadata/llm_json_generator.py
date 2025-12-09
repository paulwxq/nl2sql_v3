"""简化版 JSON 数据画像生成器（供 LLM 使用）

包含 LLM 推断内容：
- table_category（LLM 推断，默认启用）
- table_domains（LLM 推断，--domain 参数启用）

不包含规则推断内容：
- semantic_analysis（语义角色，由 --step json 的规则算法生成）
- role_specific_info（角色特定信息）
- logical_keys、confidence 等（由 --step json 的规则算法生成）

说明：
- 本模块通过 LLM 进行推断，与 --step json 的规则算法互为补充
- table_category 判断表的业务类型（dim/fact/bridge/unknown）
- table_domains 判断表所属的业务主题（需配合 --domain 参数和 db_domains.yaml）
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import pandas as pd

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.core.metadata.extractor import MetadataExtractor
from src.metaweave.core.metadata.models import TableMetadata, ColumnInfo
from src.metaweave.utils.data_utils import get_column_statistics, dataframe_to_sample_dict
from src.metaweave.utils.file_utils import ensure_dir
from src.metaweave.utils.logger import get_metaweave_logger
from src.metaweave.services.llm_service import LLMService

logger = get_metaweave_logger("metadata.llm_json_generator")


UNCLASSIFIED_DOMAIN = "_未分类_"


class LLMJsonGenerator:
    """生成简化版 JSON 数据画像（供 LLM 使用）"""
    
    def __init__(
        self,
        config: Dict,
        connector: DatabaseConnector,
        include_domains: bool = False,
        domain_filter: Optional[List[str]] = None,
        db_domains_config: Optional[Dict] = None,
    ):
        self.config = config
        self.connector = connector
        self.extractor = MetadataExtractor(connector)
        self.include_domains = include_domains
        self.domain_filter = domain_filter
        self.db_domains_config = db_domains_config or {}
        self.llm_service = LLMService(config.get("llm", {}))
        
        # 输出目录
        output_config = config.get("output", {})
        json_llm_dir = output_config.get("json_llm_directory", "output/metaweave/metadata/json_llm")
        self.output_dir = Path(json_llm_dir)
        ensure_dir(self.output_dir)
        
        # 采样配置（复用现有 sampling 配置）
        sampling_config = config.get("sampling", {})
        self.sample_size = sampling_config.get("sample_size", 1000)
        self.value_distribution_threshold = sampling_config.get("column_statistics", {}).get("value_distribution_threshold", 10)

        # LLM 异步配置
        langchain_config = config.get("llm", {}).get("langchain_config", {})
        self.use_async = langchain_config.get("use_async", False)
        self.batch_size = max(1, int(langchain_config.get("batch_size", 50) or 50))
        
        logger.info(f"LLMJsonGenerator 已初始化: output_dir={self.output_dir}, sample_size={self.sample_size}")
    
    def generate_all_from_ddl(self, ddl_dir: Path) -> int:
        """从 DDL 目录生成所有表的简化 JSON
        
        文件命名约定：DDL 文件必须使用 {schema}.{table}.sql 格式
        
        Args:
            ddl_dir: DDL 文件目录
            
        Returns:
            生成的文件数量
            
        Raises:
            ValueError: DDL 文件名格式不正确（缺少 schema）
        """
        logger.info("=" * 60)
        logger.info("开始生成简化版 JSON（json_llm）")
        logger.info(f"DDL 目录: {ddl_dir}")
        logger.info("=" * 60)

        ddl_files = list(ddl_dir.glob("*.sql"))
        logger.info(f"找到 {len(ddl_files)} 个 DDL 文件")

        if self.use_async:
            return self._run_async(self._generate_all_async(ddl_files))
        return self._generate_all_sync(ddl_files)

    def _generate_all_sync(self, ddl_files: List[Path]) -> int:
        generated_count = 0
        for ddl_file in ddl_files:
            try:
                schema, table = self._parse_ddl_filename(ddl_file.stem)
                self._generate_single_table(schema, table)
                generated_count += 1
                logger.debug("已生成: %s.%s", schema, table)
            except Exception as e:
                logger.error("生成失败 %s: %s", ddl_file.name, e)
        logger.info("简化版 JSON 生成完成，共 %s 个文件", generated_count)
        return generated_count

    async def _generate_all_async(self, ddl_files: List[Path]) -> int:
        """异步生成（LLM 调用批量并发）"""
        table_jsons: List[Dict] = []
        for ddl_file in ddl_files:
            try:
                schema, table = self._parse_ddl_filename(ddl_file.stem)
                metadata: TableMetadata = self.extractor.extract_all(schema, table)
                if not metadata:
                    raise ValueError(f"提取元数据失败: {schema}.{table}")
                sample_df: pd.DataFrame = self.connector.sample_data(schema, table, self.sample_size)
                json_data = self._build_simplified_json(metadata, sample_df)
                table_jsons.append(json_data)
            except Exception as e:
                logger.error("生成基础 JSON 失败 %s: %s", ddl_file.name, e)

        prompts = [self._build_prompt(tj) for tj in table_jsons]

        def on_progress(done: int, total: int):
            if total:
                logger.info("LLM 异步进度: %s/%s", done, total)

        results = await self.llm_service.batch_call_llm_async(
            prompts,
            on_progress=on_progress,
        )

        generated_count = 0
        for idx, result in enumerate(results):
            response = result[1] if isinstance(result, (list, tuple)) and len(result) == 2 else result
            profile = {}
            if response:
                profile = self._parse_llm_response(response)
            self._merge_and_save(table_jsons[idx], profile)
            generated_count += 1

        logger.info("简化版 JSON 异步生成完成，共 %s 个文件", generated_count)
        return generated_count
    
    def _run_async(self, coro):
        """在无事件循环场景运行协程，避免返回未执行的协程对象。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "检测到已存在运行中的事件循环，请在外部 await 调用或自行管理事件循环。"
        )
    
    def _parse_ddl_filename(self, filename_stem: str) -> Tuple[str, str]:
        """解析 DDL 文件名获取 schema 和 table
        
        命名约定：{schema}.{table}（如 public.dim_store）
        
        Args:
            filename_stem: 文件名（不含扩展名）
            
        Returns:
            (schema, table) 元组
            
        Raises:
            ValueError: 文件名格式不正确
        """
        if '.' not in filename_stem:
            raise ValueError(f"DDL 文件名格式错误: '{filename_stem}.sql'，必须使用 '{{schema}}.{{table}}.sql' 格式")
        
        parts = filename_stem.split('.', 1)
        schema = parts[0]
        table = parts[1]
        
        return schema, table
    
    def _generate_single_table(self, schema: str, table: str) -> None:
        """生成单表的简化 JSON
        
        步骤：
        1. 复用 MetadataExtractor 提取表结构
        2. 复用 DatabaseConnector 采样数据
        3. 复用 get_column_statistics 计算统计
        4. 构建 structure_flags（复用 profiler 逻辑）
        5. 组装输出并追加 LLM 推断的表属性
        """
        logger.debug(f"处理表: {schema}.{table}")
        
        # 1. 提取表结构（复用 MetadataExtractor）
        metadata: TableMetadata = self.extractor.extract_all(schema, table)
        if not metadata:
            raise ValueError(f"提取元数据失败: {schema}.{table}")
        
        # 2. 采样数据（复用 DatabaseConnector）
        sample_df: pd.DataFrame = self.connector.sample_data(schema, table, self.sample_size)
        
        # 3. 构建简化版 JSON
        json_data = self._build_simplified_json(metadata, sample_df)

        # 4. LLM 推断表属性
        profile = self._infer_table_profile_sync(json_data)
        self._merge_and_save(json_data, profile)
    
    def _build_simplified_json(self, metadata: TableMetadata, sample_df: Optional[pd.DataFrame]) -> Dict:
        """构建简化版 JSON（不含推断内容）"""
        
        # 1. table_info
        table_info = {
            "schema_name": metadata.schema_name,
            "table_name": metadata.table_name,
            "table_type": metadata.table_type,
            "comment": metadata.comment,
            "comment_source": metadata.comment_source,
            "total_rows": metadata.row_count,
            "total_columns": len(metadata.columns),
        }
        
        # 2. column_profiles（不含 semantic_analysis 和 role_specific_info）
        column_profiles = {}
        for col in metadata.columns:
            col_profile = self._build_column_profile(col, metadata, sample_df)
            column_profiles[col.column_name] = col_profile
        
        # 3. table_profile（只保留 physical_constraints）
        table_profile = {
            "physical_constraints": self._build_physical_constraints(metadata)
        }
        
        # 4. sample_records
        sample_records = self._build_sample_records(metadata, sample_df)
        
        return {
            "metadata_version": "2.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "table_info": table_info,
            "column_profiles": column_profiles,
            "table_profile": table_profile,
            "sample_records": sample_records,
        }
    
    def _build_column_profile(
        self, 
        col: ColumnInfo, 
        metadata: TableMetadata, 
        sample_df: Optional[pd.DataFrame]
    ) -> Dict:
        """构建单列的 profile（不含推断内容）"""
        
        # 基本信息
        profile = {
            "column_name": col.column_name,
            "ordinal_position": col.ordinal_position,
            "data_type": col.data_type,
            "character_maximum_length": col.character_maximum_length,
            "numeric_precision": col.numeric_precision,
            "numeric_scale": col.numeric_scale,
            "is_nullable": col.is_nullable,
            "column_default": col.column_default,
            "comment": col.comment,
            "comment_source": col.comment_source,
        }
        
        # statistics（复用 get_column_statistics）
        if sample_df is not None and not sample_df.empty and col.column_name in sample_df.columns:
            stats = get_column_statistics(
                sample_df, 
                col.column_name, 
                value_distribution_threshold=self.value_distribution_threshold
            )
            profile["statistics"] = stats
        else:
            profile["statistics"] = None
        
        # structure_flags（复用收集逻辑）
        profile["structure_flags"] = self._build_structure_flags(col, metadata)
        
        # 不包含：semantic_analysis, role_specific_info
        
        return profile
    
    def _build_structure_flags(self, col: ColumnInfo, metadata: TableMetadata) -> Dict:
        """构建 structure_flags（复用 profiler 逻辑）"""
        col_lower = col.column_name.lower()
        
        # 主键检查
        pk_columns = set()
        is_pk_composite = False
        for pk in metadata.primary_keys:
            if len(pk.columns) > 1:
                is_pk_composite = True
            pk_columns.update(c.lower() for c in pk.columns)
        is_pk = col_lower in pk_columns
        
        # 外键检查
        fk_columns = set()
        is_fk_composite = False
        for fk in metadata.foreign_keys:
            if len(fk.source_columns) > 1:
                is_fk_composite = True
            fk_columns.update(c.lower() for c in fk.source_columns)
        is_fk = col_lower in fk_columns
        
        # 唯一约束检查
        uc_columns = set()
        is_uc_composite = False
        for uc in metadata.unique_constraints:
            if len(uc.columns) > 1:
                is_uc_composite = True
            uc_columns.update(c.lower() for c in uc.columns)
        is_uc = col_lower in uc_columns
        
        # 索引检查
        idx_columns = set()
        is_idx_composite = False
        for idx in metadata.indexes:
            if len(idx.columns) > 1:
                is_idx_composite = True
            idx_columns.update(c.lower() for c in idx.columns)
        is_idx = col_lower in idx_columns
        
        # 数据唯一性检查（从 statistics）
        is_data_unique = False
        # 注意：此时 statistics 还未计算，需要从 sample_df 获取
        # 这里简化处理，不依赖 statistics
        
        return {
            "is_primary_key": is_pk and not is_pk_composite,
            "is_composite_primary_key_member": is_pk and is_pk_composite,
            "is_foreign_key": is_fk and not is_fk_composite,
            "is_composite_foreign_key_member": is_fk and is_fk_composite,
            "is_unique": False,  # 简化处理，不依赖 statistics
            "is_composite_unique_member": is_uc and is_uc_composite,
            "is_unique_constraint": is_uc and not is_uc_composite,
            "is_composite_unique_constraint_member": is_uc and is_uc_composite,
            "is_indexed": is_idx and not is_idx_composite,
            "is_composite_indexed_member": is_idx and is_idx_composite,
            "is_nullable": col.is_nullable,
        }
    
    def _build_physical_constraints(self, metadata: TableMetadata) -> Dict:
        """构建 physical_constraints"""
        # 主键
        primary_key = None
        if metadata.primary_keys:
            pk = metadata.primary_keys[0]
            primary_key = {
                "constraint_name": pk.constraint_name,
                "columns": pk.columns,
            }
        
        # 外键
        foreign_keys = []
        for fk in metadata.foreign_keys:
            foreign_keys.append({
                "constraint_name": fk.constraint_name,
                "source_columns": fk.source_columns,
                "target_schema": fk.target_schema,
                "target_table": fk.target_table,
                "target_columns": fk.target_columns,
                "on_delete": fk.on_delete,
                "on_update": fk.on_update,
            })
        
        # 唯一约束
        unique_constraints = []
        for uc in metadata.unique_constraints:
            unique_constraints.append({
                "constraint_name": uc.constraint_name,
                "columns": uc.columns,
            })
        
        # 索引
        indexes = []
        for idx in metadata.indexes:
            if not idx.is_primary:  # 排除主键索引
                indexes.append({
                    "index_name": idx.index_name,
                    "columns": idx.columns,
                    "is_unique": idx.is_unique,
                    "index_type": idx.index_type,
                })
        
        return {
            "primary_key": primary_key,
            "foreign_keys": foreign_keys,
            "unique_constraints": unique_constraints,
            "indexes": indexes,
        }
    
    def _build_sample_records(self, metadata: TableMetadata, sample_df: Optional[pd.DataFrame]) -> Dict:
        """构建 sample_records（与 json/ 步骤一致，固定 5 行）"""
        records = []
        if sample_df is not None and not sample_df.empty:
            records = dataframe_to_sample_dict(sample_df, max_rows=5)  # 与 json/ 步骤一致
        
        return {
            "sample_method": "random",
            "sample_size": len(records),
            "total_rows": metadata.row_count,
            "sampled_at": datetime.utcnow().isoformat() + "Z",
            "records": records,
        }

    def _infer_table_profile_sync(self, table_json: Dict) -> Dict:
        """同步推断表的 category 和 domains"""
        prompt = self._build_prompt(table_json)
        response = self.llm_service._call_llm(prompt)
        return self._parse_llm_response(response)

    def _merge_and_save(self, table_json: Dict, profile: Dict) -> None:
        """合并 LLM 推断结果并保存文件"""
        table_profile = table_json.get("table_profile", {}) or {}
        if profile:
            table_profile["table_category"] = profile.get("table_category")
            if self.include_domains:
                domains = profile.get("table_domains", [])
                if not domains:
                    domains = [UNCLASSIFIED_DOMAIN]
                table_profile["table_domains"] = domains
        else:
            # 无返回时兜底
            table_profile.setdefault("table_category", "unknown")
            if self.include_domains:
                table_profile.setdefault("table_domains", [UNCLASSIFIED_DOMAIN])

        table_json["table_profile"] = table_profile

        table_info = table_json.get("table_info", {})
        schema = table_info.get("schema_name")
        table = table_info.get("table_name")
        output_path = self.output_dir / f"{schema}.{table}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(table_json, f, ensure_ascii=False, indent=2)

    def _build_prompt(self, table_json: Dict) -> str:
        """构建 LLM 提示词（含可选 domain 部分）"""
        base_prompt = f"""
你是一名数据仓库建模专家，请根据我提供的"表结构"和"样例数据"完成任务。

## 表结构与样例数据
{json.dumps(table_json, ensure_ascii=False, indent=2)}

## 任务一：判断表的类型（table_category）
1) fact：事实类表，特征：有度量值、随业务增长、含多维度外键
2) dim：维度类表，特征：描述性字段多、较稳定、以ID标识实体
3) bridge：桥接表，特征：用于多对多关系，通常只包含外键
4) unknown：无法判断时选择，不要强行猜测
"""

        domains_text = ""
        if self.include_domains:
            db_description = self.db_domains_config.get("database", {}).get("description", "")
            domains = self._get_domains_for_prompt()
            domain_list_text = "\n".join(
                f"{i}) {d['name']}：{d.get('description', '')}"
                for i, d in enumerate(domains, 1)
            )
            domains_text = f"""
## 数据库背景
{db_description}

## 任务二：判断表的业务主题（table_domains）
从以下主题列表中选择（可单选或多选）：
{domain_list_text}

如果不属于任何主题，返回 [\"{UNCLASSIFIED_DOMAIN}\"]（注意：必须是数组格式）。
"""

        if self.include_domains:
            output_format = """
## 输出格式（JSON）
{"table_category": "<fact|dim|bridge|unknown>", "table_domains": ["主题1", "主题2"], "reason": "..."}
"""
        else:
            output_format = """
## 输出格式（JSON）
{"table_category": "<fact|dim|bridge|unknown>", "reason": "..."}
"""

        return base_prompt + domains_text + output_format + "\n请只返回 JSON，不要包含其他内容。"

    def _get_domains_for_prompt(self) -> List[Dict]:
        domains = self.db_domains_config.get("domains", [])
        if not domains:
            return [{"name": UNCLASSIFIED_DOMAIN, "description": "无法归入其他业务主题的表"}]
        if not self.domain_filter or "all" in self.domain_filter:
            return domains
        return [d for d in domains if d.get("name") in self.domain_filter]

    def _parse_llm_response(self, response: str) -> Dict:
        """解析 LLM 返回 JSON"""
        text = response.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

        data = json.loads(text)
        table_category = data.get("table_category")
        table_domains = data.get("table_domains", [])
        if self.include_domains and not table_domains:
            table_domains = [UNCLASSIFIED_DOMAIN]
        return {
            "table_category": table_category,
            "table_domains": table_domains,
            "reason": data.get("reason"),
        }

