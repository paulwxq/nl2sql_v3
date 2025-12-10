"""简化版 JSON 数据画像生成器（供 LLM 使用）

新增：支持注释生成、Token 优化与自动分批。
"""

import asyncio
import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.core.metadata.extractor import MetadataExtractor
from src.metaweave.core.metadata.models import ColumnInfo, TableMetadata
from src.metaweave.services.llm_service import LLMService
from src.metaweave.utils.data_utils import dataframe_to_sample_dict, get_column_statistics
from src.metaweave.utils.file_utils import ensure_dir
from src.metaweave.utils.logger import get_metaweave_logger

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

        # 采样配置
        sampling_config = config.get("sampling", {})
        self.sample_size = sampling_config.get("sample_size", 1000)
        self.value_distribution_threshold = (
            sampling_config.get("column_statistics", {}).get("value_distribution_threshold", 10)
        )

        # LLM 异步配置
        langchain_config = config.get("llm", {}).get("langchain_config", {})
        self.use_async = langchain_config.get("use_async", False)
        self.batch_size = max(1, int(langchain_config.get("batch_size", 50) or 50))

        # 注释生成配置（兼容 comment_generation 顶层或 llm 内部）
        comment_config = config.get("llm", {}).get("comment_generation", {}) or config.get(
            "comment_generation", {}
        )
        self.comment_generation_enabled = comment_config.get("enabled", True)
        self.comment_language = comment_config.get("language", "zh")
        # 兼容 zh-CN 写法
        if self.comment_language.lower() in {"zh-cn", "zh_cn"}:
            self.comment_language = "zh"
        self.generate_table_comment = comment_config.get("generate_table_comment", True)
        self.generate_column_comment = comment_config.get("generate_column_comment", True)
        self.max_columns_per_call = comment_config.get("max_columns_per_call", 120)
        self.max_sample_rows = comment_config.get("max_sample_rows", 3)
        self.max_sample_cols = comment_config.get("max_sample_cols", 20)
        self.enable_batch_processing = comment_config.get("enable_batch_processing", True)
        self.overwrite_existing = comment_config.get("overwrite_existing", False)
        self.fallback_on_parse_error = comment_config.get("fallback_on_parse_error", True)
        self.log_failed_responses = comment_config.get("log_failed_responses", True)

        self._validate_config()

        logger.info(
            "注释生成配置: enabled=%s, language=%s, max_columns=%s, max_rows=%s, max_cols=%s, batch=%s",
            self.comment_generation_enabled,
            self.comment_language,
            self.max_columns_per_call,
            self.max_sample_rows,
            self.max_sample_cols,
            self.enable_batch_processing,
        )
        logger.info(
            "LLMJsonGenerator 已初始化: output_dir=%s, sample_size=%s, use_async=%s",
            self.output_dir,
            self.sample_size,
            self.use_async,
        )

    def _validate_config(self) -> None:
        """验证并矫正配置"""
        valid_languages = ["zh", "en", "bilingual"]
        if self.comment_language not in valid_languages:
            logger.warning(
                "⚠️ 无效的 comment_language: %s, 使用默认 'zh'。有效值: %s",
                self.comment_language,
                valid_languages,
            )
            self.comment_language = "zh"

        if self.max_columns_per_call < 10:
            logger.warning("⚠️ max_columns_per_call 过小(%s)，调整为 10", self.max_columns_per_call)
            self.max_columns_per_call = 10
        if self.max_sample_rows < 1:
            logger.warning("⚠️ max_sample_rows 至少为 1，调整为 3")
            self.max_sample_rows = 3
        if self.max_sample_cols < 5:
            logger.warning("⚠️ max_sample_cols 过小(%s)，调整为 10", self.max_sample_cols)
            self.max_sample_cols = 10

    def generate_all_from_ddl(self, ddl_dir: Path) -> int:
        """从 DDL 目录生成所有表的简化 JSON"""
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
        """异步生成（LLM 调用批量并发），确保所有路径先做 Token 优化。"""
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

        jobs = []
        for idx, table_json in enumerate(table_jsons):
            meta = table_json.get("_metadata", {})
            missing_cols = meta.get("missing_column_comments", [])
            need_table_comment = meta.get("need_table_comment", False) and self.generate_table_comment

            # 注释生成可配置禁用
            if not self.comment_generation_enabled:
                missing_cols = []
                need_table_comment = False

            if len(missing_cols) == 0 and not need_table_comment:
                optimized = self._build_simplified_json_for_llm(table_json, [])
                prompt = self._build_prompt(optimized)
                jobs.append({"table_idx": idx, "batch_idx": 0, "prompt": prompt})
            elif len(missing_cols) <= self.max_columns_per_call or not self.enable_batch_processing:
                cols = missing_cols[: self.max_columns_per_call]
                if len(missing_cols) > self.max_columns_per_call and not self.enable_batch_processing:
                    remaining = len(missing_cols) - self.max_columns_per_call
                    logger.warning(
                        "⚠️ 表 %s 缺失字段 %s 个，分批已禁用，仅处理前 %s 个，剩余 %s 个需人工/重跑",
                        table_json.get("table_info", {}).get("table_name"),
                        len(missing_cols),
                        self.max_columns_per_call,
                        remaining,
                    )
                optimized = self._build_simplified_json_for_llm(table_json, cols)
                optimized["_metadata"]["missing_column_comments"] = cols
                prompt = self._build_prompt(optimized)
                jobs.append({"table_idx": idx, "batch_idx": 0, "prompt": prompt})
            else:
                batch_size = self.max_columns_per_call
                total_batches = (len(missing_cols) + batch_size - 1) // batch_size
                table_name = table_json.get("table_info", {}).get("table_name")
                logger.info(
                    "📦 表 %s 有 %s 个缺失注释字段，分 %s 批处理（每批最多 %s 个）",
                    table_name,
                    len(missing_cols),
                    total_batches,
                    batch_size,
                )
                for b in range(total_batches):
                    start = b * batch_size
                    end = min(start + batch_size, len(missing_cols))
                    cols = missing_cols[start:end]
                    batch_json = self._build_simplified_json_for_llm(table_json, cols)
                    batch_json["_metadata"]["missing_column_comments"] = cols
                    prompt = self._build_prompt(batch_json)
                    jobs.append({"table_idx": idx, "batch_idx": b, "prompt": prompt})

        prompts = [j["prompt"] for j in jobs]

        def on_progress(done: int, total: int):
            if total:
                logger.info("LLM 异步进度: %s/%s", done, total)

        results = await self.llm_service.batch_call_llm_async(prompts, on_progress=on_progress)

        table_results: Dict[int, Dict] = {
            idx: {"column_comments": {}, "table_comment": None, "table_category": None, "table_domains": None}
            for idx in range(len(table_jsons))
        }

        for job, result in zip(jobs, results):
            response = result[1] if isinstance(result, (list, tuple)) and len(result) == 2 else result
            profile = {}
            table_name = table_jsons[job["table_idx"]].get("table_info", {}).get("table_name", "unknown")
            if response:
                profile = self._parse_llm_response(response, table_name)

            agg = table_results[job["table_idx"]]
            if "column_comments" in profile:
                agg["column_comments"].update(profile.get("column_comments") or {})
            if agg["table_comment"] is None and profile.get("table_comment"):
                agg["table_comment"] = profile.get("table_comment")
            if agg["table_category"] is None and profile.get("table_category"):
                agg["table_category"] = profile.get("table_category")
            if self.include_domains and agg["table_domains"] is None and profile.get("table_domains") is not None:
                agg["table_domains"] = profile.get("table_domains")

        generated_count = 0
        for idx, table_json in enumerate(table_jsons):
            profile = table_results[idx]
            self._merge_and_save(table_json, profile)
            generated_count += 1

        logger.info("简化版 JSON 异步生成完成，共 %s 个文件", generated_count)
        return generated_count

    def _run_async(self, coro):
        """在无事件循环场景运行协程，避免返回未执行的协程对象。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError("检测到已存在运行中的事件循环，请在外部 await 调用或自行管理事件循环。")

    def _parse_ddl_filename(self, filename_stem: str) -> Tuple[str, str]:
        """解析 DDL 文件名获取 schema 和 table"""
        if "." not in filename_stem:
            raise ValueError(
                f"DDL 文件名格式错误: '{filename_stem}.sql'，必须使用 '{{schema}}.{{table}}.sql' 格式"
            )
        schema, table = filename_stem.split(".", 1)
        return schema, table

    def _generate_single_table(self, schema: str, table: str) -> None:
        """生成单表的简化 JSON 并合并 LLM 结果"""
        logger.debug("处理表: %s.%s", schema, table)
        metadata: TableMetadata = self.extractor.extract_all(schema, table)
        if not metadata:
            raise ValueError(f"提取元数据失败: {schema}.{table}")

        sample_df: pd.DataFrame = self.connector.sample_data(schema, table, self.sample_size)
        json_data = self._build_simplified_json(metadata, sample_df)
        profile = self._generate_single_table_with_batching(json_data)
        self._merge_and_save(json_data, profile)

    def _generate_single_table_with_batching(self, table_json: Dict) -> Dict:
        """单表处理，包含 Token 优化与分批"""
        meta = table_json.get("_metadata", {})
        missing_cols = meta.get("missing_column_comments", [])
        need_table_comment = meta.get("need_table_comment", False) and self.generate_table_comment
        if not self.comment_generation_enabled:
            missing_cols = []
            need_table_comment = False

        # 无缺失，或只需分类
        if len(missing_cols) == 0 and not need_table_comment:
            optimized_json = self._build_simplified_json_for_llm(table_json, [])
            return self._infer_table_profile_sync(optimized_json)

        # 不分批或刚好一批
        if len(missing_cols) <= self.max_columns_per_call:
            optimized_json = self._build_simplified_json_for_llm(table_json, missing_cols)
            optimized_json["_metadata"]["missing_column_comments"] = missing_cols
            return self._infer_table_profile_sync(optimized_json)

        # 超出单批上限但禁用分批：截断
        if not self.enable_batch_processing:
            remaining = len(missing_cols) - self.max_columns_per_call
            logger.warning(
                "⚠️ 表 %s 缺失字段 %s 个，分批处理禁用，仅处理前 %s 个，剩余 %s 个需人工/重跑",
                table_json.get("table_info", {}).get("table_name"),
                len(missing_cols),
                self.max_columns_per_call,
                remaining,
            )
            truncated_cols = missing_cols[: self.max_columns_per_call]
            optimized_json = self._build_simplified_json_for_llm(table_json, truncated_cols)
            optimized_json["_metadata"]["missing_column_comments"] = truncated_cols
            return self._infer_table_profile_sync(optimized_json)

        # 自动分批
        batch_size = self.max_columns_per_call
        total_batches = (len(missing_cols) + batch_size - 1) // batch_size
        logger.info(
            "📦 表 %s 缺失字段 %s 个，分 %s 批处理（每批最多 %s 个）",
            table_json.get("table_info", {}).get("table_name"),
            len(missing_cols),
            total_batches,
            batch_size,
        )

        all_column_comments: Dict[str, str] = {}
        table_comment = None
        table_category = None
        table_domains = None

        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(missing_cols))
            batch_cols = missing_cols[start:end]
            logger.info("  批次 %s/%s: 字段 %s-%s", batch_idx + 1, total_batches, start + 1, end)
            batch_json = self._build_simplified_json_for_llm(table_json, batch_cols)
            batch_json["_metadata"]["missing_column_comments"] = batch_cols
            batch_result = self._infer_table_profile_sync(batch_json)

            if "column_comments" in batch_result:
                all_column_comments.update(batch_result.get("column_comments") or {})
                logger.info("  ✅ 批次 %s 完成，生成 %s 个注释", batch_idx + 1, len(batch_result["column_comments"]))

            if batch_idx == 0:
                table_comment = batch_result.get("table_comment")
                table_category = batch_result.get("table_category")
                table_domains = batch_result.get("table_domains")

        final_profile = {"column_comments": all_column_comments}
        if table_comment:
            final_profile["table_comment"] = table_comment
        if table_category:
            final_profile["table_category"] = table_category
        if table_domains:
            final_profile["table_domains"] = table_domains
        return final_profile

    def _build_simplified_json(self, metadata: TableMetadata, sample_df: Optional[pd.DataFrame]) -> Dict:
        """构建简化版 JSON（含 _metadata 状态）"""

        table_info = {
            "schema_name": metadata.schema_name,
            "table_name": metadata.table_name,
            "table_type": metadata.table_type,
            "comment": metadata.comment,
            "comment_source": metadata.comment_source,
            "total_rows": metadata.row_count,
            "total_columns": len(metadata.columns),
        }

        column_profiles = {}
        for col in metadata.columns:
            col_profile = self._build_column_profile(col, metadata, sample_df)
            column_profiles[col.column_name] = col_profile

        table_profile = {"physical_constraints": self._build_physical_constraints(metadata)}
        sample_records = self._build_sample_records(metadata, sample_df)

        json_data = {
            "metadata_version": "2.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "table_info": table_info,
            "column_profiles": column_profiles,
            "table_profile": table_profile,
            "sample_records": sample_records,
        }

        json_data["_metadata"] = {
            "need_table_comment": not (metadata.comment and str(metadata.comment).strip()),
            "missing_column_comments": [
                col.column_name for col in metadata.columns if not (col.comment and str(col.comment).strip())
            ],
            "existing_column_comments": {
                col.column_name: col.comment
                for col in metadata.columns
                if col.comment and str(col.comment).strip()
            },
        }
        return json_data

    def _build_column_profile(
        self, col: ColumnInfo, metadata: TableMetadata, sample_df: Optional[pd.DataFrame]
    ) -> Dict:
        """构建单列 profile（不含推断内容）"""
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

        if sample_df is not None and not sample_df.empty and col.column_name in sample_df.columns:
            stats = get_column_statistics(
                sample_df, col.column_name, value_distribution_threshold=self.value_distribution_threshold
            )
            profile["statistics"] = stats
        else:
            profile["statistics"] = None

        profile["structure_flags"] = self._build_structure_flags(col, metadata)
        return profile

    def _build_structure_flags(self, col: ColumnInfo, metadata: TableMetadata) -> Dict:
        """构建 structure_flags（复用 profiler 逻辑）"""
        col_lower = col.column_name.lower()

        pk_columns = set()
        is_pk_composite = False
        for pk in metadata.primary_keys:
            if len(pk.columns) > 1:
                is_pk_composite = True
            pk_columns.update(c.lower() for c in pk.columns)
        is_pk = col_lower in pk_columns

        fk_columns = set()
        is_fk_composite = False
        for fk in metadata.foreign_keys:
            if len(fk.source_columns) > 1:
                is_fk_composite = True
            fk_columns.update(c.lower() for c in fk.source_columns)
        is_fk = col_lower in fk_columns

        uc_columns = set()
        is_uc_composite = False
        for uc in metadata.unique_constraints:
            if len(uc.columns) > 1:
                is_uc_composite = True
            uc_columns.update(c.lower() for c in uc.columns)
        is_uc = col_lower in uc_columns

        idx_columns = set()
        is_idx_composite = False
        for idx in metadata.indexes:
            if len(idx.columns) > 1:
                is_idx_composite = True
            idx_columns.update(c.lower() for c in idx.columns)
        is_idx = col_lower in idx_columns

        return {
            "is_primary_key": is_pk and not is_pk_composite,
            "is_composite_primary_key_member": is_pk and is_pk_composite,
            "is_foreign_key": is_fk and not is_fk_composite,
            "is_composite_foreign_key_member": is_fk and is_fk_composite,
            "is_unique": False,
            "is_composite_unique_member": is_uc and is_uc_composite,
            "is_unique_constraint": is_uc and not is_uc_composite,
            "is_composite_unique_constraint_member": is_uc and is_uc_composite,
            "is_indexed": is_idx and not is_idx_composite,
            "is_composite_indexed_member": is_idx and is_idx_composite,
            "is_nullable": col.is_nullable,
        }

    def _build_physical_constraints(self, metadata: TableMetadata) -> Dict:
        """构建 physical_constraints"""
        primary_key = None
        if metadata.primary_keys:
            pk = metadata.primary_keys[0]
            primary_key = {"constraint_name": pk.constraint_name, "columns": pk.columns}

        foreign_keys = []
        for fk in metadata.foreign_keys:
            foreign_keys.append(
                {
                    "constraint_name": fk.constraint_name,
                    "source_columns": fk.source_columns,
                    "target_schema": fk.target_schema,
                    "target_table": fk.target_table,
                    "target_columns": fk.target_columns,
                    "on_delete": fk.on_delete,
                    "on_update": fk.on_update,
                }
            )

        unique_constraints = []
        for uc in metadata.unique_constraints:
            unique_constraints.append({"constraint_name": uc.constraint_name, "columns": uc.columns})

        indexes = []
        for idx in metadata.indexes:
            if not idx.is_primary:
                indexes.append(
                    {
                        "index_name": idx.index_name,
                        "columns": idx.columns,
                        "is_unique": idx.is_unique,
                        "index_type": idx.index_type,
                    }
                )

        return {
            "primary_key": primary_key,
            "foreign_keys": foreign_keys,
            "unique_constraints": unique_constraints,
            "indexes": indexes,
        }

    def _build_sample_records(self, metadata: TableMetadata, sample_df: Optional[pd.DataFrame]) -> Dict:
        """构建 sample_records（原始采样，后续再裁剪）"""
        records = []
        if sample_df is not None and not sample_df.empty:
            records = dataframe_to_sample_dict(sample_df, max_rows=min(5, len(sample_df)))
        return {
            "sample_method": "random",
            "sample_size": len(records),
            "total_rows": metadata.row_count,
            "sampled_at": datetime.utcnow().isoformat() + "Z",
            "records": records,
        }

    def _build_simplified_json_for_llm(self, json_data: Dict, missing_cols: List[str]) -> Dict:
        """为 LLM 调用裁剪 JSON，控制 Token 体积"""
        trimmed = copy.deepcopy(json_data)
        max_rows = self.max_sample_rows
        max_cols = self.max_sample_cols

        if "sample_records" in trimmed and "records" in trimmed["sample_records"]:
            records = trimmed["sample_records"]["records"]
            if len(records) > max_rows:
                trimmed["sample_records"]["records"] = records[:max_rows]
                trimmed["sample_records"]["_truncated_rows"] = True
                logger.debug("样例数据行数截断: %s -> %s", len(records), max_rows)

            column_profiles = trimmed.get("column_profiles", {})
            total_cols = len(column_profiles)
            if total_cols > max_cols:
                priority_cols = []
                for col_name, col_profile in column_profiles.items():
                    flags = col_profile.get("structure_flags", {})
                    if flags.get("is_primary_key"):
                        priority_cols.append((col_name, 0))
                    elif flags.get("is_foreign_key"):
                        priority_cols.append((col_name, 1))
                    elif col_name in missing_cols:
                        priority_cols.append((col_name, 2))
                    else:
                        priority_cols.append((col_name, 3))
                priority_cols.sort(key=lambda x: x[1])
                keep_cols = {col[0] for col in priority_cols[:max_cols]}

                for record in trimmed["sample_records"].get("records", []):
                    for key in list(record.keys()):
                        if key not in keep_cols:
                            del record[key]
                trimmed["sample_records"]["_truncated_cols"] = True
                logger.debug("样例数据列数截断: %s -> %s", total_cols, max_cols)

        for col_name, col_profile in trimmed.get("column_profiles", {}).items():
            if col_name not in missing_cols:
                original_stats = col_profile.get("statistics") or {}
                col_profile["statistics"] = {
                    "sample_count": original_stats.get("sample_count"),
                    "unique_count": original_stats.get("unique_count"),
                    "_simplified": True,
                }

        return trimmed

    def _infer_table_profile_sync(self, table_json: Dict) -> Dict:
        """同步推断表属性"""
        prompt = self._build_prompt(table_json)
        response = self.llm_service._call_llm(prompt)
        return self._parse_llm_response(response, table_json.get("table_info", {}).get("table_name", "unknown"))

    def _build_prompt(self, table_json: Dict) -> str:
        """构建 Prompt（支持注释生成、多语言）"""
        if not self.comment_generation_enabled:
            return self._build_prompt_without_comments(table_json)

        meta = table_json.get("_metadata", {}) or {}
        need_table_comment = meta.get("need_table_comment", False) and self.generate_table_comment
        missing_columns = meta.get("missing_column_comments", []) if self.generate_column_comment else []
        existing_comments = meta.get("existing_column_comments", {})

        sample_records = table_json.get("sample_records", {}).get("records", []) or []
        column_profiles = table_json.get("column_profiles", {}) or {}
        logger.info(
            "📊 Token 预算: 总字段=%s, 缺失注释=%s, 样例行数=%s (max=%s), 样例列数~%s (max=%s)",
            len(column_profiles),
            len(missing_columns),
            len(sample_records),
            self.max_sample_rows,
            len(sample_records[0]) if sample_records else 0,
            self.max_sample_cols,
        )

        base_prompt = f"""
你是一名数据仓库建模专家，请根据我提供的"表结构"和"样例数据"完成任务。

## 表结构与样例数据
{json.dumps(table_json, ensure_ascii=False, indent=2)}
# 注意：此 JSON 已经过 Token 优化（样例数据截断、统计信息简化）

## 任务一：判断表的类型（table_category）
1) fact：事实类表，特征：有度量值、随业务增长、含多维度外键
2) dim：维度类表，特征：描述性字段多、较稳定、以ID标识实体
3) bridge：桥接表，特征：用于多对多关系，通常只包含外键
4) unknown：无法判断时选择，不要强行猜测
"""

        if self.include_domains:
            base_prompt += self._build_domains_task()

        if need_table_comment or missing_columns:
            task_num = 2 if not self.include_domains else 3
            comment_section = f"\n## 任务{task_num}：生成缺失的注释\n"

            if missing_columns:
                comment_section += "\n### 字段注释生成\n"
                if existing_comments:
                    comment_section += "**已有注释的字段**（请在输出中保持原样）：\n"
                    for col_name, comment in existing_comments.items():
                        comment_section += f"- `{col_name}`: \"{comment}\"\n"
                    comment_section += "\n"

                comment_section += "**缺失注释的字段**（需要生成）：\n"
                for col_name in missing_columns:
                    comment_section += f"- `{col_name}`\n"
                comment_section += "\n"

                comment_section += self._get_comment_generation_instructions()

            if need_table_comment:
                comment_section += "\n### 表注释生成\n请为表生成一句话的业务含义说明\n"

            base_prompt += comment_section

        output_example: Dict = {"table_category": "<fact|dim|bridge|unknown>"}
        if self.include_domains:
            output_example["table_domains"] = ["主题1", "主题2"]
        if need_table_comment:
            output_example["table_comment"] = "表的业务含义"
        if missing_columns:
            output_example["column_comments"] = {}
            for col_name, comment in list(existing_comments.items())[:2]:
                output_example["column_comments"][col_name] = f"{comment} (保持原样)"
            for col_name in missing_columns[:2]:
                output_example["column_comments"][col_name] = "（请生成）"
        output_example["reason"] = "推断理由"

        base_prompt += f"""
## 输出格式（JSON）
{json.dumps(output_example, ensure_ascii=False, indent=2)}

**重要提醒**：
- 请返回所有字段的注释（包括已有注释的字段）
- 已有注释的字段保持原样，缺失注释的字段进行生成
- 请只返回 JSON，不要包含其他内容
"""
        return base_prompt

    def _build_prompt_without_comments(self, table_json: Dict) -> str:
        """仅分类/主题的 Prompt"""
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
        if self.include_domains:
            base_prompt += self._build_domains_task()
            output_format = """
## 输出格式（JSON）
{"table_category": "<fact|dim|bridge|unknown>", "table_domains": ["主题1", "主题2"], "reason": "..."}
"""
        else:
            output_format = """
## 输出格式（JSON）
{"table_category": "<fact|dim|bridge|unknown>", "reason": "..."}
"""
        return base_prompt + output_format + "\n请只返回 JSON，不要包含其他内容。"

    def _build_domains_task(self) -> str:
        db_description = self.db_domains_config.get("database", {}).get("description", "")
        domains = self._get_domains_for_prompt()
        domain_list_text = "\n".join(
            f"{i}) {d['name']}：{d.get('description', '')}" for i, d in enumerate(domains, 1)
        )
        return f"""
## 数据库背景
{db_description}

## 任务二：判断表的业务主题（table_domains）
从以下主题列表中选择（可单选或多选）：
{domain_list_text}

如果不属于任何主题，返回 ["{UNCLASSIFIED_DOMAIN}"]（必须是数组格式）。
"""

    def _get_comment_generation_instructions(self) -> str:
        instructions = {
            "zh": """**要求**：
1. 为缺失注释的字段生成简洁的中文说明
2. 基于表结构和样例数据推断业务含义
3. 参考已有注释的风格，保持一致性
4. 所有字段都需要在输出中返回
5. 已有注释的字段必须保持原样，不要修改

**注意**：
- 注释要简洁准确，避免重复字段名本身
- 不要修改已有注释的内容
""",
            "en": """**Requirements**:
1. Generate concise English descriptions for fields with missing comments
2. Infer business meaning based on table structure and sample data
3. Follow the style of existing comments for consistency
4. Return all fields in the output
5. Existing comments must remain unchanged

**Notes**:
- Comments should be concise and accurate, avoiding repetition of field names
- Do not modify existing comments
""",
            "bilingual": """**要求 / Requirements**：
1. 为缺失注释的字段生成中英双语说明 / Generate bilingual (Chinese & English) descriptions
2. 格式：`中文说明 / English Description`
3. 基于表结构和样例数据推断业务含义 / Infer business meaning from structure and samples
4. 参考已有注释的风格 / Follow existing comment style
5. 所有字段都需要在输出中返回 / Return all fields in output
6. 已有注释的字段必须保持原样 / Existing comments must remain unchanged
""",
        }
        return instructions.get(self.comment_language, instructions["zh"])

    def _get_domains_for_prompt(self) -> List[Dict]:
        domains = self.db_domains_config.get("domains", [])
        if not domains:
            return [{"name": UNCLASSIFIED_DOMAIN, "description": "无法归入其他业务主题的表"}]
        if not self.domain_filter or "all" in self.domain_filter:
            return domains
        return [d for d in domains if d.get("name") in self.domain_filter]

    def _parse_llm_response(self, response: str, table_name: str = "unknown") -> Dict:
        """稳健解析 LLM 响应，部分成功也返回"""
        try:
            result = json.loads(response.strip())
            if isinstance(result, list) and len(result) > 0:
                logger.warning("表 %s: LLM 返回列表，取第一个元素", table_name)
                result = result[0] if isinstance(result[0], dict) else {}
        except json.JSONDecodeError as e:
            logger.warning("表 %s: JSON 解析失败，尝试提取: %s", table_name, e)
            result = self._extract_json_from_markdown(response)

        if not result or not isinstance(result, dict):
            logger.error("表 %s: ❌ 解析失败，返回降级 profile", table_name)
            if self.log_failed_responses:
                logger.error("原始响应（前500字符）: %s", response[:500])
            return self._get_fallback_profile()

        profile: Dict = {}
        fields_found: List[str] = []
        fields_missing: List[str] = []

        if "table_category" in result:
            profile["table_category"] = result.get("table_category", "unknown")
            fields_found.append("table_category")
        else:
            profile["table_category"] = "unknown"
            fields_missing.append("table_category")

        if self.include_domains:
            if "table_domains" in result:
                domains = result.get("table_domains", [])
                profile["table_domains"] = domains if isinstance(domains, list) else []
                fields_found.append("table_domains")
            else:
                fields_missing.append("table_domains")

        if "table_comment" in result and isinstance(result.get("table_comment"), str):
            profile["table_comment"] = result.get("table_comment", "").strip()
            fields_found.append("table_comment")

        if "column_comments" in result:
            comments = result.get("column_comments")
            if isinstance(comments, dict):
                profile["column_comments"] = comments
                fields_found.append(f"column_comments({len(comments)}个)")
            else:
                fields_missing.append("column_comments")
        else:
            fields_missing.append("column_comments")

        if fields_found:
            logger.info("表 %s: ✅ 成功提取字段: %s", table_name, ", ".join(fields_found))
        if fields_missing:
            logger.warning("表 %s: ⚠️ 缺失字段: %s", table_name, ", ".join(fields_missing))

        return profile

    def _extract_json_from_markdown(self, response: str) -> Dict:
        """从复杂响应中稳健提取 JSON"""
        patterns_md = [
            r"```json\s*(\{.*?\})\s*```",
            r"```json\s*(\[.*?\])\s*```",
            r"```\s*(\{.*?\})\s*```",
            r"```\s*(\[.*?\])\s*```",
        ]
        for ptn in patterns_md:
            m = re.search(ptn, response, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(1))
                    if isinstance(parsed, list) and len(parsed) > 0:
                        logger.warning("⚠️ Markdown 代码块中为列表，取第一个元素")
                        return parsed[0] if isinstance(parsed[0], dict) else {}
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    continue

        json_patterns = [r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", r"\{.*?\}"]
        for ptn in json_patterns:
            matches = re.findall(ptn, response, re.DOTALL)
            for m in sorted(matches, key=len, reverse=True):
                try:
                    parsed = json.loads(m)
                    if isinstance(parsed, dict):
                        logger.warning("⚠️ 通过正则提取到 JSON 对象")
                        return parsed
                except json.JSONDecodeError:
                    continue

        list_pattern = r"\[.*?\]"
        m = re.search(list_pattern, response, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed, list) and len(parsed) > 0:
                    logger.warning("⚠️ 提取到列表，取第一个元素")
                    return parsed[0] if isinstance(parsed[0], dict) else {}
            except json.JSONDecodeError:
                pass

        logger.error("❌ 无法从响应中提取 JSON")
        if self.log_failed_responses:
            logger.error("原始响应（前500字符）: %s", response[:500])
        return {}

    def _get_fallback_profile(self) -> Dict:
        """降级策略：返回最小可用 profile"""
        logger.warning("⚠️ 使用降级 profile（category=unknown, 无注释）")
        profile = {"table_category": "unknown"}
        if self.include_domains:
            profile["table_domains"] = []
        return profile

    def _merge_and_save(self, table_json: Dict, profile: Dict) -> None:
        """合并 LLM 推断结果并保存文件"""
        table_profile = table_json.get("table_profile", {}) or {}
        if profile:
            table_profile["table_category"] = profile.get("table_category") or "unknown"
            if self.include_domains:
                domains = profile.get("table_domains", [])
                if not domains:
                    domains = [UNCLASSIFIED_DOMAIN]
                table_profile["table_domains"] = domains
        else:
            table_profile.setdefault("table_category", "unknown")
            if self.include_domains:
                table_profile.setdefault("table_domains", [UNCLASSIFIED_DOMAIN])

        # 表注释：只在缺失或允许覆盖时更新
        if "table_comment" in profile:
            existing_table_comment = table_json.get("table_info", {}).get("comment", "") or ""
            new_comment = profile.get("table_comment")
            if (new_comment and str(new_comment).strip()) and (
                self.overwrite_existing or not str(existing_table_comment).strip()
            ):
                table_json["table_info"]["comment"] = new_comment
                table_json["table_info"]["comment_source"] = "llm_generated"
                logger.info("✅ 生成表注释: %s", new_comment)
            else:
                logger.debug("⏭️  表注释已存在 (%s)，跳过更新", existing_table_comment)

        # 字段注释：只更新缺失或允许覆盖
        if "column_comments" in profile:
            column_profiles = table_json.get("column_profiles", {})
            updated_count = 0
            skipped_count = 0
            missing_count = 0

            for col_name, comment in profile.get("column_comments", {}).items():
                if col_name in column_profiles:
                    existing_comment = column_profiles[col_name].get("comment", "")
                    if self.overwrite_existing or not str(existing_comment).strip():
                        column_profiles[col_name]["comment"] = comment
                        column_profiles[col_name]["comment_source"] = "llm_generated"
                        updated_count += 1
                        logger.debug("✅ 生成字段注释: %s = '%s'", col_name, comment)
                    else:
                        skipped_count += 1
                        logger.debug("⏭️  字段 %s 已有注释 '%s'，跳过更新", col_name, existing_comment)
                else:
                    missing_count += 1
                    logger.warning("⚠️  LLM 返回了不存在的字段: %s", col_name)

            logger.info("📝 字段注释: %s 个生成, %s 个跳过, %s 个无效", updated_count, skipped_count, missing_count)

        table_json["table_profile"] = table_profile
        table_json.pop("_metadata", None)

        table_info = table_json.get("table_info", {})
        schema = table_info.get("schema_name")
        table = table_info.get("table_name")
        output_path = self.output_dir / f"{schema}.{table}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(table_json, f, ensure_ascii=False, indent=2)
        logger.info("💾 已保存: %s", output_path)


