"""输出格式化器

将元数据格式化为 DDL、Markdown、JSON 等格式并保存。
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import pandas as pd

from src.metaweave.core.metadata.models import TableMetadata
from src.metaweave.utils.file_utils import save_text, save_json, ensure_dir
from src.metaweave.utils.data_utils import dataframe_to_sample_dict

logger = logging.getLogger("metaweave.formatter")


class OutputFormatter:
    """输出格式化器
    
    将表元数据格式化为不同格式并保存到文件。
    """
    
    def __init__(self, config: dict):
        """初始化输出格式化器
        
        Args:
            config: 配置字典
                - output_dir: 输出目录
                - formats: 输出格式列表 ['ddl', 'markdown', 'json']
                - ddl_options: DDL 选项
                - markdown_options: Markdown 选项
        """
        self.config = config
        self.output_dir = Path(config.get("output_dir", "output/metaweave/metadata"))
        self.formats = config.get("formats", ["ddl", "markdown", "json"])
        self.ddl_options = config.get("ddl_options", {})
        sample_records_config = self.ddl_options.get("sample_records", {})
        self.sample_record_options = {
            "enabled": sample_records_config.get("enabled", True),
            "count": sample_records_config.get("count", 3),
            "label_prefix": sample_records_config.get("label_prefix", "Record"),
            "include_placeholders": sample_records_config.get("include_placeholders", True),
        }
        self.markdown_options = config.get("markdown_options", {})
        self.markdown_sample_value_count = max(
            1,
            int(self.markdown_options.get("sample_value_count", 2))
        )

        # 确保输出目录存在
        ensure_dir(self.output_dir / "ddl")
        self.markdown_dir = self.output_dir / "md"
        ensure_dir(self.markdown_dir)
        ensure_dir(self.output_dir / "json")
        
        logger.info(f"输出格式化器已初始化: {self.output_dir}")
    
    def format_and_save(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame] = None,
        formats_override: Optional[List[str]] = None
    ) -> dict:
        """格式化并保存元数据
        
        Args:
            metadata: 表元数据
            sample_data: 样本数据（可选，用于 Markdown）
            
        Returns:
            保存的文件路径字典 {'ddl': path, 'markdown': path, 'json': path}
        """
        output_files = {}
        active_formats = self.formats if formats_override is None else formats_override
        
        if not active_formats:
            logger.info("未指定输出格式，跳过文件保存")
            return output_files
        
        # 生成 DDL
        if "ddl" in active_formats:
            ddl_path = self._save_ddl(metadata, sample_data)
            if ddl_path:
                output_files["ddl"] = str(ddl_path)
        
        # 生成 Markdown
        if "markdown" in active_formats:
            md_path = self._save_markdown(metadata, sample_data)
            if md_path:
                output_files["markdown"] = str(md_path)
        
        # 生成 JSON
        if "json" in active_formats:
            json_path = self._save_json(metadata, sample_data)
            if json_path:
                output_files["json"] = str(json_path)
        
        return output_files
    
    def generate_ddl(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame] = None
    ) -> str:
        """生成 DDL 脚本
        
        Args:
            metadata: 表元数据
            
        Returns:
            DDL 脚本内容
        """
        ddl_lines = []
        
        # 文件头注释
        ddl_lines.append(f"-- ====================================")
        ddl_lines.append(f"-- Table: {metadata.full_name}")
        if metadata.comment:
            ddl_lines.append(f"-- Comment: {metadata.comment}")
        ddl_lines.append(f"-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        ddl_lines.append(f"-- ====================================")
        ddl_lines.append("")
        
        # CREATE TABLE 语句
        ddl_lines.append(f"CREATE TABLE IF NOT EXISTS {metadata.full_name} (")
        
        # 字段定义
        column_defs = []
        for col in metadata.columns:
            col_def = f"    {col.column_name} {col.data_type.upper()}"
            
            # 添加长度/精度
            if col.character_maximum_length:
                col_def += f"({col.character_maximum_length})"
            elif col.numeric_precision:
                if col.numeric_scale:
                    col_def += f"({col.numeric_precision},{col.numeric_scale})"
                else:
                    col_def += f"({col.numeric_precision})"
            
            # 添加 NOT NULL
            if not col.is_nullable:
                col_def += " NOT NULL"
            
            # 添加默认值
            if col.column_default:
                col_def += f" DEFAULT {col.column_default}"
            
            column_defs.append(col_def)
        
        # 添加主键约束
        for pk in metadata.primary_keys:
            pk_def = f"    CONSTRAINT {pk.constraint_name} PRIMARY KEY ({', '.join(pk.columns)})"
            column_defs.append(pk_def)
        
        # 添加唯一约束
        for uc in metadata.unique_constraints:
            uc_def = f"    CONSTRAINT {uc.constraint_name} UNIQUE ({', '.join(uc.columns)})"
            column_defs.append(uc_def)
        
        # 添加外键约束
        for fk in metadata.foreign_keys:
            fk_def = (
                f"    CONSTRAINT {fk.constraint_name} FOREIGN KEY ({', '.join(fk.source_columns)}) "
                f"REFERENCES {fk.target_schema}.{fk.target_table} ({', '.join(fk.target_columns)})"
            )
            if fk.on_delete != "NO ACTION":
                fk_def += f" ON DELETE {fk.on_delete}"
            if fk.on_update != "NO ACTION":
                fk_def += f" ON UPDATE {fk.on_update}"
            column_defs.append(fk_def)
        
        ddl_lines.append(",\n".join(column_defs))
        ddl_lines.append(");")
        ddl_lines.append("")
        
        # 字段注释
        if self.ddl_options.get("include_comments", True):
            ddl_lines.append("-- Column Comments")
            for col in metadata.columns:
                if col.comment:
                    ddl_lines.append(
                        f"COMMENT ON COLUMN {metadata.full_name}.{col.column_name} IS '{col.comment}';"
                    )
            ddl_lines.append("")
        
        # 索引（排除主键和唯一约束索引）
        if self.ddl_options.get("include_indexes", True):
            non_pk_indexes = [
                idx for idx in metadata.indexes
                if not idx.is_primary and not idx.is_unique
            ]
            
            if non_pk_indexes:
                ddl_lines.append("-- Indexes")
                for idx in non_pk_indexes:
                    ddl_lines.append(
                        f"CREATE INDEX {idx.index_name} ON {metadata.full_name}"
                        f"({', '.join(idx.columns)});"
                    )
                ddl_lines.append("")
        
        # 表注释
        if metadata.comment:
            ddl_lines.append("-- Table Comment")
            ddl_lines.append(f"COMMENT ON TABLE {metadata.full_name} IS '{metadata.comment}';")
        
        sample_block = self._build_sample_records_block(metadata, sample_data)
        if sample_block:
            ddl_lines.append("")
            ddl_lines.append(sample_block)
        
        return "\n".join(ddl_lines)
    
    def _get_sample_value(
        self,
        column_name: str,
        sample_data: Optional[pd.DataFrame]
    ) -> str:
        """从样本数据中获取字段的第一个非空值
        
        Args:
            column_name: 字段名
            sample_data: 样本数据
            
        Returns:
            字段的示例值，如果为空或不存在则返回 "null"
        """
        if sample_data is None or sample_data.empty:
            return "null"

        if column_name not in sample_data.columns:
            return "null"

        non_null_values = sample_data[column_name].dropna()
        if non_null_values.empty:
            return "null"

        sample_values = (
            non_null_values.iloc[: self.markdown_sample_value_count]
            .astype(str)
            .tolist()
        )

        if not sample_values:
            return "null"

        return ", ".join(sample_values)
    
    def generate_markdown(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame] = None
    ) -> str:
        """生成 Markdown 文档
        
        Args:
            metadata: 表元数据
            sample_data: 样本数据（可选）
            
        Returns:
            Markdown 文档内容
        """
        md_lines = []
        
        # 1. 标题：schema.table_name（表注释）
        comment_part = f"（{metadata.comment}）" if metadata.comment else ""
        md_lines.append(f"# {metadata.full_name}{comment_part}")
        
        # 2. 字段列表
        md_lines.append("## 字段列表：")
        
        for col in metadata.columns:
            # 构建类型字符串（含长度/精度）
            data_type = col.data_type.lower()
            if col.character_maximum_length:
                data_type += f"({col.character_maximum_length})"
            elif col.numeric_precision:
                if col.numeric_scale:
                    data_type += f"({col.numeric_precision},{col.numeric_scale})"
                else:
                    data_type += f"({col.numeric_precision})"
            
            # 获取示例值
            sample_value = self._get_sample_value(col.column_name, sample_data)
            
            # 字段注释
            comment = col.comment if col.comment else "无注释"
            
            # 生成字段行
            md_lines.append(f"- {col.column_name} ({data_type}) - {comment} [示例: {sample_value}]")
        
        # 3. 字段补充说明
        supplementary_items = []
        
        # 3.1 主键约束
        if metadata.primary_keys:
            for pk in metadata.primary_keys:
                cols = ', '.join(pk.columns)
                supplementary_items.append(f"- 主键约束 {pk.constraint_name}: {cols}")
        
        # 3.2 外键关系
        if metadata.foreign_keys:
            for fk in metadata.foreign_keys:
                source_cols = ', '.join(fk.source_columns)
                target_cols = ', '.join(fk.target_columns)
                supplementary_items.append(
                    f"- {source_cols} 关联 {fk.target_schema}.{fk.target_table}.{target_cols}"
                )
        
        # 3.3 逻辑主键 - 已禁用，不在 Markdown 中显示
        # if metadata.logical_keys:
        #     for lk in metadata.logical_keys:
        #         cols = ', '.join(lk.columns)
        #         supplementary_items.append(
        #             f"- 逻辑主键候选：{cols} (置信度: {lk.confidence_score:.2f})"
        #         )
        
        # 3.4 唯一约束
        if metadata.unique_constraints:
            for uc in metadata.unique_constraints:
                cols = ', '.join(uc.columns)
                supplementary_items.append(f"- 唯一约束 {uc.constraint_name}: {cols}")
        
        # 3.5 索引（排除主键和唯一索引）
        regular_indexes = [
            idx for idx in metadata.indexes 
            if not idx.is_primary and not idx.is_unique
        ]
        if regular_indexes:
            for idx in regular_indexes:
                cols = ', '.join(idx.columns)
                supplementary_items.append(
                    f"- 索引 {idx.index_name} ({idx.index_type}): {cols}"
                )
        
        # 3.6 数据类型精度说明（针对 numeric/decimal 类型）
        numeric_cols = [
            col for col in metadata.columns 
            if 'numeric' in col.data_type.lower() or 'decimal' in col.data_type.lower()
        ]
        if numeric_cols:
            for col in numeric_cols:
                if col.numeric_precision and col.numeric_scale:
                    supplementary_items.append(
                        f"- {col.column_name} 使用{col.data_type}({col.numeric_precision},{col.numeric_scale})"
                        f"存储，精确到小数点后{col.numeric_scale}位"
                    )
        
        # 只有当有补充说明内容时才显示这一节
        if supplementary_items:
            md_lines.append("## 字段补充说明：")
            md_lines.extend(supplementary_items)
        
        return "\n".join(md_lines)
    
    def _save_ddl(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame] = None
    ) -> Optional[Path]:
        """保存 DDL 脚本"""
        try:
            ddl_content = self.generate_ddl(metadata, sample_data)
            file_path = self.output_dir / "ddl" / f"{metadata.schema_name}.{metadata.table_name}.sql"
            save_text(ddl_content, file_path)
            logger.info(f"保存 DDL: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"保存 DDL 失败 ({metadata.full_name}): {e}")
            return None
    
    def _save_markdown(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame] = None
    ) -> Optional[Path]:
        """保存 Markdown 文档"""
        try:
            md_content = self.generate_markdown(metadata, sample_data)
            file_path = self.markdown_dir / f"{metadata.schema_name}.{metadata.table_name}.md"
            save_text(md_content, file_path)
            logger.info(f"保存 Markdown: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"保存 Markdown 失败 ({metadata.full_name}): {e}")
            return None
    
    def _extract_sample_records_from_ddl(self, metadata: TableMetadata) -> Optional[Dict[str, Any]]:
        """从 DDL 文件中提取样例记录
        
        Args:
            metadata: 表元数据
            
        Returns:
            样例记录字典，如果没有找到则返回 None
        """
        try:
            ddl_file = self.output_dir / "ddl" / f"{metadata.schema_name}.{metadata.table_name}.sql"
            if not ddl_file.exists():
                return None
            
            content = ddl_file.read_text(encoding="utf-8")
            
            # 查找 SAMPLE_RECORDS 注释块
            pattern = r'/\*\s*SAMPLE_RECORDS\s*(.*?)\s*\*/'
            match = re.search(pattern, content, re.DOTALL)
            
            if not match:
                return None
            
            json_str = match.group(1)
            sample_data = json.loads(json_str)
            
            # 提取有效的记录（排除 placeholder）
            records = []
            for record in sample_data.get("records", []):
                if record.get("data") is not None:
                    # 转换数据类型（将字符串数字转换为数字）
                    converted_data = {}
                    for key, value in record["data"].items():
                        if isinstance(value, str):
                            # 尝试转换为数字
                            try:
                                # 尝试整数
                                if '.' not in value:
                                    converted_data[key] = int(value)
                                else:
                                    converted_data[key] = float(value)
                            except (ValueError, TypeError):
                                # 保持字符串
                                converted_data[key] = value
                        else:
                            converted_data[key] = value
                    records.append(converted_data)
            
            if not records:
                return None
            
            return {
                "sample_method": "random",
                "sample_size": len(records),
                "total_rows": metadata.row_count,
                "sampled_at": sample_data.get("generated_at"),
                "records": records[:5]  # 最多取5条
            }
            
        except Exception as e:
            logger.warning(f"从 DDL 提取样例数据失败 ({metadata.full_name}): {e}")
            return None
    
    def _save_json(self, metadata: TableMetadata, sample_data: Optional[pd.DataFrame] = None) -> Optional[Path]:
        """保存 JSON 文件
        
        Args:
            metadata: 表元数据
            sample_data: 可选的样本数据 DataFrame
        """
        try:
            json_data = metadata.to_dict()
            
            # 尝试从 DDL 提取样例数据
            sample_records = self._extract_sample_records_from_ddl(metadata)
            
            # 如果 DDL 中没有，尝试从 sample_data 提取
            if not sample_records and sample_data is not None and not sample_data.empty:
                samples = dataframe_to_sample_dict(sample_data, max_rows=5)
                if samples:
                    sample_records = {
                        "sample_method": "random",
                        "sample_size": len(samples),
                        "total_rows": metadata.row_count,
                        "sampled_at": datetime.utcnow().isoformat() + "Z",
                        "records": samples
                    }
            
            # 如果还是没有样例数据，创建空结构
            if not sample_records:
                sample_records = {
                    "sample_method": "random",
                    "sample_size": 0,
                    "total_rows": metadata.row_count,
                    "sampled_at": None,
                    "records": []
                }
            
            # 添加样例数据到 JSON
            json_data["sample_records"] = sample_records
            
            file_path = self.output_dir / "json" / f"{metadata.schema_name}.{metadata.table_name}.json"
            save_json(json_data, file_path)
            logger.info(f"保存 JSON: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"保存 JSON 失败 ({metadata.full_name}): {e}")
            return None

    def _build_sample_records_block(
        self,
        metadata: TableMetadata,
        sample_data: Optional[pd.DataFrame]
    ) -> str:
        """构建样例记录注释块"""
        if not self.sample_record_options.get("enabled", True):
            return ""
        
        max_records = max(0, int(self.sample_record_options.get("count", 3)))
        if max_records == 0:
            return ""
        
        label_prefix = self.sample_record_options.get("label_prefix", "Record")
        include_placeholders = self.sample_record_options.get("include_placeholders", True)
        samples = []
        if sample_data is not None and not sample_data.empty:
            samples = dataframe_to_sample_dict(sample_data, max_rows=max_records)
        
        records = []
        for idx in range(max_records):
            if idx < len(samples):
                record = {
                    "label": f"{label_prefix} {idx + 1}",
                    "data": samples[idx]
                }
            elif include_placeholders:
                record = {
                    "label": f"{label_prefix} {idx + 1}",
                    "data": None,
                    "note": "placeholder"
                }
            else:
                break
            records.append(record)
        
        if not records:
            return ""
        
        payload = {
            "version": 1,
            "table": metadata.full_name,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "records": records
        }
        json_block = json.dumps(payload, ensure_ascii=False, indent=2)
        return "\n".join(["/* SAMPLE_RECORDS", json_block, "*/"])

