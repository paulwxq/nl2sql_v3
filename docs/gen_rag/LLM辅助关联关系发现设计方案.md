# LLM 辅助关联关系发现设计方案

## 1. 需求概述

### 1.1 背景

当前关联关系发现流程依赖复杂的启发式规则（语义分析、逻辑主键推断等），引入 LLM 可以简化流程并提高准确性。

### 1.2 目标

1. 新增 `json_llm` 步骤：生成简化版 JSON 数据画像（去除所有推断内容）
2. 新增 `rel_llm` 步骤：使用 LLM 发现候选关联关系，复用现有评分逻辑
3. 调整 CQL 生成：根据 cardinality 决定箭头方向

### 1.3 命令行接口

```bash
# LLM 辅助流程（推荐）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step ddl
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json_llm
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step cql_llm
python -m src.metaweave.cli.main load --type cql --clean

# 传统流程（命令行用法不变，CQL 方向逻辑已修复）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step ddl
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step cql
python -m src.metaweave.cli.main load --type cql --clean
```

### 1.4 路径说明

每个步骤都有**明确的读写路径**，不存在 fallback 逻辑。如果读取路径不存在，直接报错退出。

| 步骤 | 读取路径 | 写入路径 | 配置项 |
|------|----------|----------|--------|
| `ddl` | 数据库 | `ddl/` | `output.output_dir` |
| `json` | `ddl/` + 数据库 | `json/` | `output.json_directory` |
| `json_llm` | `ddl/` + 数据库 | `json_llm/` | `output.json_llm_directory` |
| `rel` | `json/` | `rel/` | `output.rel_directory` |
| `rel_llm` | `json_llm/` | `rel/` | `output.rel_directory` |
| `cql` | `json/` + `rel/` | `cql/` | `output.cql_directory` |
| `cql_llm` | `json_llm/` + `rel/` | `cql/` | `output.cql_directory` |

#### 1.4.1 两条流程对比

| 流程 | 步骤序列 | JSON 目录 |
|------|----------|-----------|
| **传统流程** | `ddl` → `json` → `rel` → `cql` | `json/` |
| **LLM 流程** | `ddl` → `json_llm` → `rel_llm` → `cql_llm` | `json_llm/` |

#### 1.4.2 错误处理

如果读取路径不存在或为空，直接报错退出：

```python
# 示例：rel_llm 步骤
if not json_llm_dir.exists() or not list(json_llm_dir.glob("*.json")):
    logger.error(f"json_llm 目录不存在或为空: {json_llm_dir}")
    raise FileNotFoundError(f"请先执行 --step json_llm 生成简化版 JSON")
```

### 1.5 rel 与 rel_llm 共存策略

`--step rel` 和 `--step rel_llm` **写入同一个 `rel/` 目录**，输出文件名相同（`relationships_global.json`）。

- **谁最后执行，谁的结果生效**
- `--step cql` 只读取 `rel/` 目录，不区分来源

---

## 2. 整体流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LLM 辅助流程                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────┐       │
│  │ step    │     │ step        │     │ step        │     │ step    │       │
│  │ ddl     │────►│ json_llm    │────►│ rel_llm     │────►│ cql_llm │       │
│  └─────────┘     └─────────────┘     └─────────────┘     └─────────┘       │
│       │                │                    │                  │            │
│       ▼                ▼                    ▼                  ▼            │
│   ddl/*.sql      json_llm/*.json      rel/*.json         cql/*.cql        │
│   (物理DDL)       (简化画像)          (关联关系)          (图数据)          │
│                                            │                               │
│                                            │                               │
│                   ┌────────────────────────┴───────────────────┐           │
│                   │                                            │           │
│                   ▼                                            ▼           │
│            ┌─────────────┐                           ┌─────────────┐       │
│            │    LLM      │                           │  评分模块   │       │
│            │  两两组合    │ ─────────────────────────►│ (采样计算)  │       │
│            │  候选发现    │    返回候选字段对          │ 复用 Scorer │       │
│            └─────────────┘                           └─────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

传统流程对比：ddl → json → rel → cql（读取 json/ 目录）
LLM 流程：    ddl → json_llm → rel_llm → cql_llm（读取 json_llm/ 目录）
```

---

## 3. json_llm 步骤设计

### 3.1 设计原则

生成**简化版 JSON 数据画像**，只包含事实数据，**去除所有推断内容**，避免影响 LLM 判断。

### 3.2 输出内容

| 内容 | 保留 | 删除 | 说明 |
|------|------|------|------|
| `table_info` | ✅ | | 表基本信息 |
| `column_profiles.*.基本属性` | ✅ | | column_name, data_type, comment 等 |
| `column_profiles.*.statistics` | ✅ | | 采样统计（事实数据） |
| `column_profiles.*.structure_flags` | ✅ | | 物理约束标志（事实数据） |
| `column_profiles.*.semantic_analysis` | | ❌ | 推断内容 |
| `column_profiles.*.role_specific_info` | | ❌ | 推断内容 |
| `table_profile.physical_constraints` | ✅ | | 物理约束（事实数据） |
| `table_profile.table_category` | | ❌ | 推断内容 |
| `table_profile.confidence` | | ❌ | 推断内容 |
| `table_profile.inference_basis` | | ❌ | 推断内容 |
| `table_profile.logical_keys` | | ❌ | 推断内容 |
| `table_profile.fact_table_info` | | ❌ | 推断内容 |
| `table_profile.dim_table_info` | | ❌ | 推断内容 |
| `sample_records` | ✅ | | 样例数据 |

### 3.3 输出目录与文件命名

```
output/metaweave/metadata/
├── ddl/                    # DDL 文件（现有）
│   ├── public.dim_product.sql     # 文件名格式：{schema}.{table}.sql
│   └── ...
├── json/                   # 完整 JSON 画像（现有，传统流程使用）
├── json_llm/               # 简化 JSON 画像（新增，LLM 流程使用）
│   ├── public.dim_product.json    # 文件名格式：{schema}.{table}.json
│   ├── public.dim_store.json
│   └── ...
├── rel/                    # 关联关系（两条流程共用）
└── cql/                    # CQL 文件（现有）
```

#### 3.3.1 文件命名约定

DDL 文件**必须**使用标准格式：`{schema}.{table}.sql`

| DDL 文件名 | 解析结果 |
|------------|----------|
| `public.dim_store.sql` | schema=`public`, table=`dim_store` |
| `sales.dim_store.sql` | schema=`sales`, table=`dim_store` |

输出 JSON 文件名与 DDL 保持一致：`{schema}.{table}.json`

### 3.4 JSON Schema（简化版示例）

```json
{
  "metadata_version": "2.0",
  "generated_at": "2025-12-04T03:41:54.707645Z",
  "table_info": {
    "schema_name": "public",
    "table_name": "dim_store",
    "table_type": "table",
    "comment": "店铺维表",
    "comment_source": "ddl",
    "total_rows": 9,
    "total_columns": 4
  },
  "column_profiles": {
    "store_id": {
      "column_name": "store_id",
      "ordinal_position": 1,
      "data_type": "integer",
      "character_maximum_length": null,
      "numeric_precision": 32,
      "numeric_scale": null,
      "is_nullable": false,
      "column_default": null,
      "comment": "店铺ID（主键）",
      "comment_source": "ddl",
      "statistics": {
        "sample_count": 9,
        "unique_count": 9,
        "null_count": 0,
        "null_rate": 0.0,
        "uniqueness": 1.0,
        "min": "101",
        "max": "303",
        "mean": "202.0",
        "value_distribution": {
          "101": 1,
          "102": 1,
          "103": 1
        }
      },
      "structure_flags": {
        "is_primary_key": false,
        "is_composite_primary_key_member": false,
        "is_foreign_key": false,
        "is_composite_foreign_key_member": false,
        "is_unique": true,
        "is_composite_unique_member": false,
        "is_unique_constraint": false,
        "is_composite_unique_constraint_member": false,
        "is_indexed": false,
        "is_composite_indexed_member": false,
        "is_nullable": false
      }
    },
    "company_id": {
      "column_name": "company_id",
      "ordinal_position": 3,
      "data_type": "integer",
      "is_nullable": false,
      "comment": "所属公司ID（外键）",
      "statistics": {
        "sample_count": 9,
        "unique_count": 3,
        "uniqueness": 0.3333
      },
      "structure_flags": {
        "is_foreign_key": false
      }
    }
  },
  "table_profile": {
    "physical_constraints": {
      "primary_key": null,
      "foreign_keys": [],
      "unique_constraints": [],
      "indexes": []
    }
  },
  "sample_records": {
    "sample_method": "random",
    "sample_size": 5,
    "total_rows": 9,
    "sampled_at": "2025-12-04T03:20:26.832288Z",
    "records": [
      {
        "store_id": 101,
        "store_name": "京东便利天河岗顶店",
        "company_id": 1,
        "region_id": 440106
      }
    ]
  }
}
```

### 3.5 实现方案

#### 3.5.1 复用现有能力

`json_llm` 步骤**复用现有代码**，不重新实现：

| 复用能力 | 来源 | 说明 |
|----------|------|------|
| 表结构提取 | `MetadataExtractor.extract_all(schema, table)` | 提取列、主键、外键、索引 |
| 数据采样 | `DatabaseConnector.sample_data(schema, table, limit)` | 获取 DataFrame |
| 列统计计算 | `get_column_statistics(df, col_name, threshold)` | 计算 uniqueness, null_rate 等 |
| structure_flags | `MetadataProfiler._collect_pk_columns()` 等方法 | 收集物理约束标志 |

**不复用**（推断内容）：
- `MetadataProfiler._classify_semantics()` - 语义角色推断
- `MetadataProfiler._profile_table()` - 表类型推断
- `LogicalKeyDetector` - 逻辑主键推断

#### 3.5.2 实现代码

```python
# src/metaweave/core/metadata/llm_json_generator.py

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

logger = get_metaweave_logger("metadata.llm_json_generator")


class LLMJsonGenerator:
    """生成简化版 JSON 数据画像（供 LLM 使用）
    
    复用现有能力：
    - MetadataExtractor: 表结构提取
    - DatabaseConnector: 数据采样
    - get_column_statistics: 列统计计算
    
    不包含推断内容：
    - semantic_analysis（语义角色）
    - role_specific_info（角色特定信息）
    - table_profile 下的推断字段（table_category, confidence, logical_keys 等）
    """
    
    def __init__(self, config: Dict, connector: DatabaseConnector):
        self.config = config
        self.connector = connector
        self.extractor = MetadataExtractor(connector)
        
        # 输出目录
        output_config = config.get("output", {})
        self.output_dir = Path(output_config.get("json_llm_directory", "output/metaweave/metadata/json_llm"))
        ensure_dir(self.output_dir)
        
        # 采样配置（复用现有 sampling 配置）
        sampling_config = config.get("sampling", {})
        self.sample_size = sampling_config.get("sample_size", 1000)
        self.value_distribution_threshold = sampling_config.get("column_statistics", {}).get("value_distribution_threshold", 10)
        
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
        
        generated_count = 0
        
        for ddl_file in ddl_files:
            try:
                # 解析文件名获取 schema 和 table
                schema, table = self._parse_ddl_filename(ddl_file.stem)
                
                self._generate_single_table(schema, table)
                generated_count += 1
                logger.debug(f"已生成: {schema}.{table}")
            except Exception as e:
                logger.error(f"生成失败 {ddl_file.name}: {e}")
        
        logger.info(f"简化版 JSON 生成完成，共 {generated_count} 个文件")
        return generated_count
    
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
        5. 组装输出（不含推断内容）
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
        
        # 4. 保存文件
        output_path = self.output_dir / f"{schema}.{table}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
    
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
        if col.statistics:
            uniqueness = col.statistics.get("uniqueness")
            if uniqueness is not None:
                try:
                    is_data_unique = float(uniqueness) == 1.0
                except (TypeError, ValueError):
                    pass
        
        return {
            "is_primary_key": is_pk and not is_pk_composite,
            "is_composite_primary_key_member": is_pk and is_pk_composite,
            "is_foreign_key": is_fk and not is_fk_composite,
            "is_composite_foreign_key_member": is_fk and is_fk_composite,
            "is_unique": is_data_unique and not is_uc,
            "is_composite_unique_member": is_data_unique and is_uc and is_uc_composite,
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
```

#### 3.5.3 复用关系图

```
┌─────────────────────────────────────────────────────────────────────┐
│                      LLMJsonGenerator                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌───────────────────┐     ┌───────────────────┐                    │
│  │ MetadataExtractor │     │ DatabaseConnector │                    │
│  │   .extract_all()  │     │  .sample_data()   │                    │
│  └─────────┬─────────┘     └─────────┬─────────┘                    │
│            │                         │                               │
│            │     ┌───────────────────┘                               │
│            │     │                                                   │
│            ▼     ▼                                                   │
│     ┌─────────────────┐                                             │
│     │ TableMetadata   │                                             │
│     │ + DataFrame     │                                             │
│     └────────┬────────┘                                             │
│              │                                                       │
│              ▼                                                       │
│     ┌─────────────────────────────────────────────┐                 │
│     │  get_column_statistics()  ◄── 复用          │                 │
│     │  _build_structure_flags() ◄── 复用 profiler │                 │
│     │  dataframe_to_sample_dict() ◄── 复用        │                 │
│     └─────────────────────────────────────────────┘                 │
│              │                                                       │
│              ▼                                                       │
│     ┌─────────────────┐                                             │
│     │ 简化版 JSON      │  不含：semantic_analysis                   │
│     │ json_llm/*.json │       role_specific_info                    │
│     │                 │       table_category, logical_keys          │
│     └─────────────────┘                                             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. rel_llm 步骤设计

### 4.1 整体流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      rel_llm 步骤流程                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 加载所有 json_llm/*.json 文件                               │
│                    │                                            │
│                    ▼                                            │
│  2. 提取物理外键 ──────────────────────────► 直通结果           │
│                    │                              │             │
│                    ▼                              │             │
│  3. 生成表两两组合 (N 表 → C(N,2) 组合)                         │
│                    │                              │             │
│                    ▼                              │             │
│  4. 逐对调用 LLM，获取候选关联字段                              │
│                    │                              │             │
│                    ▼                              │             │
│  5. 解析 LLM 返回，过滤已有物理外键                             │
│                    │                              │             │
│                    ▼                              │             │
│  6. 调用 RelationshipScorer._calculate_scores 评分             │
│                    │                              │             │
│                    ▼                              │             │
│  7. 合并结果 ◄─────────────────────────────────────┘            │
│                    │                                            │
│                    ▼                                            │
│  8. 输出 rel/relationships_global.json（格式与现有一致）        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 LLM 调用策略

两两组合，全部调用 LLM：

```python
from itertools import combinations

tables = ["dim_product", "dim_region", "dim_store", "fact_sales", ...]
table_pairs = list(combinations(tables, 2))
# 10 个表 → 45 对
# 15 个表 → 105 对

logger.info(f"共 {len(tables)} 张表，生成 {len(table_pairs)} 个表对")
```

### 4.3 LLM 提示词设计

```python
RELATIONSHIP_DISCOVERY_PROMPT = """
你是一个数据库关系分析专家。请分析以下两个表，判断它们之间是否存在关联关系。

## 表 1: {table1_name}
```json
{table1_json}
```

## 表 2: {table2_name}
```json
{table2_json}
```

## 任务
分析这两个表之间可能的关联关系（外键关系）。考虑以下因素：
1. 字段名相同或相似
2. 数据类型兼容
3. 字段注释的语义关联
4. 样例数据的值域匹配
5. 复合键的可能性（多个字段组合）

## 输出格式
返回 JSON 格式。如果存在关联，返回关联信息；如果没有关联，返回空数组。

### 单列关联示例
```json
{
  "relationships": [
    {
      "type": "single_column",
      "from_table": {"schema": "public", "table": "dim_region"},
      "to_table": {"schema": "public", "table": "dim_store"},
      "from_column": "region_id",
      "to_column": "region_id"
    }
  ]
}
```

### 多列关联示例（type 为 composite，字段用数组）
```json
{
  "relationships": [
    {
      "type": "composite",
      "from_table": {"schema": "public", "table": "equipment_config"},
      "to_table": {"schema": "public", "table": "maintenance_work_order"},
      "from_columns": ["equipment_id", "config_version"],
      "to_columns": ["equipment_id", "config_version"]
    }
  ]
}
```

### 无关联
```json
{
  "relationships": []
}
```

请只返回 JSON，不要包含其他内容。
"""
```

### 4.4 LLM 返回格式

#### 4.4.1 单列关联

```json
{
  "relationships": [
    {
      "type": "single_column",
      "from_table": {"schema": "public", "table": "dim_region"},
      "to_table": {"schema": "public", "table": "dim_store"},
      "from_column": "region_id",
      "to_column": "region_id"
    }
  ]
}
```

#### 4.4.2 多列关联

```json
{
  "relationships": [
    {
      "type": "composite",
      "from_table": {"schema": "public", "table": "equipment_config"},
      "to_table": {"schema": "public", "table": "maintenance_work_order"},
      "from_columns": ["equipment_id", "config_version"],
      "to_columns": ["equipment_id", "config_version"]
    }
  ]
}
```

#### 4.4.3 无关联

```json
{
  "relationships": []
}
```

### 4.5 实现方案

> **数据来源说明**：
> - **LLM 调用阶段**：数据来自 `json_llm/*.json` 文件（包含 `sample_records`），**不查询数据库**
> - **评分阶段**：复用 `RelationshipScorer._calculate_scores`，**需要查询数据库**采样以计算 `inclusion_rate` 等指标

```python
# src/metaweave/core/relationships/llm_relationship_discovery.py

from itertools import combinations
from pathlib import Path
from typing import Dict, List, Set, Tuple
import json

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.core.relationships.models import Relation
from src.metaweave.core.relationships.repository import MetadataRepository
from src.metaweave.core.relationships.scorer import RelationshipScorer
from src.metaweave.services.llm_service import LLMService
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.llm_discovery")


class LLMRelationshipDiscovery:
    """LLM 辅助关联关系发现
    
    数据来源：
    - LLM 调用：从 json_llm 文件读取，不查询数据库
    - 评分阶段：复用 RelationshipScorer，需要数据库连接
    """
    
    def __init__(self, config: Dict, connector: DatabaseConnector):
        self.config = config
        self.connector = connector  # 仅用于评分阶段
        self.scorer = RelationshipScorer(config, connector)
        self.llm_service = LLMService(config.get("llm", {}))
        
        output_config = config.get("output", {})
        self.json_llm_dir = Path(output_config.get("json_llm_directory"))
        
        # 读取 rel_id_salt 配置（与现有管道保持一致）
        rel_id_salt = output_config.get("rel_id_salt", "")
        
        # 复用 MetadataRepository 提取物理外键（包含 cardinality、relationship_id）
        self.repo = MetadataRepository(self.json_llm_dir, rel_id_salt=rel_id_salt)
        
    def discover(self) -> Dict:
        """发现关联关系，返回 rel JSON 格式的结果"""
        logger.info("=" * 60)
        logger.info("开始 LLM 辅助关联关系发现")
        logger.info("=" * 60)
        
        # 1. 加载所有 json_llm 文件
        logger.info(f"阶段1: 加载 json_llm 文件，目录: {self.json_llm_dir}")
        tables = self._load_all_tables()
        logger.info(f"已加载 {len(tables)} 张表的元数据")
        
        # 2. 提取物理外键（复用 MetadataRepository，包含 cardinality、relationship_id）
        logger.info("阶段2: 提取物理外键")
        fk_relation_objects, fk_signatures = self.repo.collect_foreign_keys(tables)
        logger.info(f"物理外键直通: {len(fk_relation_objects)} 个")
        
        # 3. 两两组合调用 LLM
        logger.info("阶段3: 两两组合调用 LLM")
        table_pairs = list(combinations(tables.keys(), 2))
        logger.info(f"共 {len(table_pairs)} 个表对需要处理")
        
        llm_candidates = []
        for i, (table1_name, table2_name) in enumerate(table_pairs):
            logger.debug(f"处理表对 [{i+1}/{len(table_pairs)}]: {table1_name} <-> {table2_name}")
            
            candidates = self._call_llm(tables[table1_name], tables[table2_name])
            llm_candidates.extend(candidates)
            
            if (i + 1) % 10 == 0:
                logger.info(f"LLM 调用进度: {i+1}/{len(table_pairs)}")
        
        logger.info(f"LLM 返回候选: {len(llm_candidates)} 个")
        
        # 4. 过滤已有物理外键
        logger.info("阶段4: 过滤已有物理外键")
        filtered_candidates = self._filter_existing_fks(llm_candidates, fk_signatures)
        logger.info(f"过滤后候选: {len(filtered_candidates)} 个")
        
        # 5. 评分
        logger.info("阶段5: 对候选关联进行评分")
        scored_relations = self._score_candidates(filtered_candidates, tables)
        logger.info(f"评分后关系: {len(scored_relations)} 个")
        
        # 6. 合并结果（将 Relation 对象转换为字典）
        logger.info("阶段6: 合并物理外键和推断关系")
        fk_relations = [self._relation_to_dict(rel) for rel in fk_relation_objects]
        all_relations = fk_relations + scored_relations
        logger.info(f"最终关系总数: {len(all_relations)}")
        
        return self._build_output(all_relations)
    
    def _load_all_tables(self) -> Dict[str, Dict]:
        """加载所有 json_llm 文件"""
        tables = {}
        for json_file in self.json_llm_dir.glob("*.json"):
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            table_info = data.get("table_info", {})
            full_name = f"{table_info['schema_name']}.{table_info['table_name']}"
            tables[full_name] = data
            logger.debug(f"已加载: {full_name}")
        return tables
    
    def _relation_to_dict(self, rel: Relation) -> Dict:
        """将 Relation 对象转换为 rel JSON 格式的字典
        
        注意语义转换：
        - Relation 对象：source=外键表, target=主键表
        - rel JSON 约定：from=主键表, to=外键表
        - 因此需要交换 source/target
        """
        rel_type = "composite" if len(rel.source_columns) > 1 else "single_column"
        
        # 交换 source/target 以符合 rel JSON 约定（from=主键表, to=外键表）
        result = {
            "relationship_id": rel.relationship_id,
            "type": rel_type,
            "from_table": {"schema": rel.target_schema, "table": rel.target_table},  # 主键表
            "to_table": {"schema": rel.source_schema, "table": rel.source_table},    # 外键表
            "discovery_method": "foreign_key_constraint",
            "cardinality": self._flip_cardinality(rel.cardinality)  # 方向翻转，基数也要翻转
        }
        
        if rel_type == "single_column":
            result["from_column"] = rel.target_columns[0]   # 主键列
            result["to_column"] = rel.source_columns[0]     # 外键列
        else:
            result["from_columns"] = rel.target_columns     # 主键列
            result["to_columns"] = rel.source_columns       # 外键列
        
        return result
    
    def _flip_cardinality(self, cardinality: str) -> str:
        """翻转基数方向"""
        flip_map = {"1:N": "N:1", "N:1": "1:N", "1:1": "1:1", "M:N": "M:N"}
        return flip_map.get(cardinality, cardinality)
    
    def _call_llm(self, table1: Dict, table2: Dict) -> List[Dict]:
        """调用 LLM 获取候选关联
        
        注意：table1/table2 来自 json_llm 文件，不查询数据库
        """
        table1_info = table1.get("table_info", {})
        table2_info = table2.get("table_info", {})
        
        table1_name = f"{table1_info['schema_name']}.{table1_info['table_name']}"
        table2_name = f"{table2_info['schema_name']}.{table2_info['table_name']}"
        
        prompt = RELATIONSHIP_DISCOVERY_PROMPT.format(
            table1_name=table1_name,
            table1_json=json.dumps(table1, ensure_ascii=False, indent=2),
            table2_name=table2_name,
            table2_json=json.dumps(table2, ensure_ascii=False, indent=2),
        )
        
        try:
            response = self.llm_service.call(prompt)
            candidates = self._parse_llm_response(response)
            logger.debug(f"LLM 返回 {len(candidates)} 个候选: {table1_name} <-> {table2_name}")
            return candidates
        except Exception as e:
            logger.warning(f"LLM 调用失败: {table1_name} <-> {table2_name}, 错误: {e}")
            return []
    
    def _parse_llm_response(self, response: str) -> List[Dict]:
        """解析 LLM 返回"""
        try:
            data = json.loads(response)
            relationships = data.get("relationships", [])
            
            if not isinstance(relationships, list):
                logger.warning(f"LLM 返回格式错误: relationships 不是数组")
                return []
            
            return relationships
        except json.JSONDecodeError as e:
            logger.warning(f"LLM 返回 JSON 解析失败: {e}")
            return []
    
    def _score_candidates(self, candidates: List[Dict], tables: Dict[str, Dict]) -> List[Dict]:
        """对候选关联进行评分
        
        复用 RelationshipScorer._calculate_scores 方法
        """
        scored_relations = []
        rel_id_salt = self.config.get("output", {}).get("rel_id_salt", "")
        
        for candidate in candidates:
            from_table_info = candidate["from_table"]
            to_table_info = candidate["to_table"]
            
            from_full_name = f"{from_table_info['schema']}.{from_table_info['table']}"
            to_full_name = f"{to_table_info['schema']}.{to_table_info['table']}"
            
            # 获取表元数据
            from_table = tables.get(from_full_name)
            to_table = tables.get(to_full_name)
            
            if not from_table or not to_table:
                logger.warning(f"找不到表元数据: {from_full_name} 或 {to_full_name}")
                continue
            
            # 提取列名
            if candidate["type"] == "single_column":
                from_columns = [candidate["from_column"]]
                to_columns = [candidate["to_column"]]
            else:
                from_columns = candidate["from_columns"]
                to_columns = candidate["to_columns"]
            
            # 调用评分方法
            logger.debug(f"评分: {from_full_name}{from_columns} -> {to_full_name}{to_columns}")
            
            score_details, cardinality = self.scorer._calculate_scores(
                from_table, from_columns,
                to_table, to_columns
            )
            
            # 计算综合评分
            composite_score = sum(
                score_details[dim] * self.scorer.weights[dim]
                for dim in score_details
            )
            
            logger.debug(f"评分结果: composite={composite_score:.4f}, cardinality={cardinality}")
            
            # 生成 relationship_id（复用 MetadataRepository.compute_relationship_id）
            relationship_id = MetadataRepository.compute_relationship_id(
                source_schema=from_table_info["schema"],
                source_table=from_table_info["table"],
                source_columns=from_columns,
                target_schema=to_table_info["schema"],
                target_table=to_table_info["table"],
                target_columns=to_columns,
                rel_id_salt=rel_id_salt
            )
            
            # 构建关系对象（包含完整字段，与现有格式一致）
            # 注：target_source_type 语义与启发式流程不同：
            #   - 启发式流程：表示目标列的来源类型（candidate_logical_key、physical_constraints）
            #   - LLM 流程：表示关系的发现来源（llm_inferred）
            # LLM 不提供目标列类型信息，若需细粒度区分可后续扩展检查目标表元数据
            relation = {
                "relationship_id": relationship_id,
                **candidate,
                "discovery_method": "llm_assisted",
                "target_source_type": "llm_inferred",  # 关系发现来源标记（非目标列类型）
                "source_constraint": None,             # LLM 推断，无源约束
                "composite_score": round(composite_score, 4),
                "confidence_level": self._get_confidence_level(composite_score),
                "metrics": {k: round(v, 4) for k, v in score_details.items()},
                "cardinality": cardinality
            }
            
            scored_relations.append(relation)
        
        return scored_relations
    
    def _get_confidence_level(self, score: float) -> str:
        """根据评分确定置信度等级"""
        if score >= 0.8:
            return "high"
        elif score >= 0.6:
            return "medium"
        else:
            return "low"
    
    def _make_signature(self, src_schema, src_table, src_cols, tgt_schema, tgt_table, tgt_cols) -> str:
        """生成关系签名用于去重"""
        src_cols_str = ",".join(sorted(src_cols))
        tgt_cols_str = ",".join(sorted(tgt_cols))
        return f"{src_schema}.{src_table}[{src_cols_str}]->{tgt_schema}.{tgt_table}[{tgt_cols_str}]"
    
    def _filter_existing_fks(self, candidates: List[Dict], fk_signatures: Set[str]) -> List[Dict]:
        """过滤已有的物理外键
        
        注意签名方向：
        - fk_signatures 来自 MetadataRepository，方向是 外键表->主键表
        - LLM 候选的 from/to 方向是 主键表->外键表
        - 因此需要翻转 LLM 候选的方向再生成签名
        """
        filtered = []
        for candidate in candidates:
            from_info = candidate["from_table"]  # 主键表
            to_info = candidate["to_table"]      # 外键表
            
            if candidate["type"] == "single_column":
                from_cols = [candidate["from_column"]]  # 主键列
                to_cols = [candidate["to_column"]]      # 外键列
            else:
                from_cols = candidate["from_columns"]
                to_cols = candidate["to_columns"]
            
            # 翻转方向：外键表->主键表，与 fk_signatures 一致
            sig = self._make_signature(
                to_info["schema"], to_info["table"], to_cols,      # 外键表、外键列
                from_info["schema"], from_info["table"], from_cols  # 主键表、主键列
            )
            
            if sig not in fk_signatures:
                filtered.append(candidate)
            else:
                logger.debug(f"跳过已有物理外键: {sig}")
        
        return filtered
    
    def _build_output(self, relations: List[Dict]) -> Dict:
        """构建输出 JSON（与现有 rel JSON 格式一致）"""
        return {
            "metadata_source": "json_llm_files",
            "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
            "statistics": {
                "total_relationships_found": len(relations),
                "foreign_key_relationships": sum(1 for r in relations if r.get("discovery_method") == "physical_foreign_key"),
                "llm_assisted_relationships": sum(1 for r in relations if r.get("discovery_method") == "llm_assisted")
            },
            "relationships": relations
        }
```

### 4.6 LLM 调用失败处理

```
单个表对 LLM 调用流程：

  调用 LLM
     │
     ▼
  成功？ ──Yes──► 解析结果，继续评分
     │
    No
     │
     ▼
  重试次数 < retry_times？
     │
    Yes──► 等待后重试
     │
    No
     │
     ▼
  logger.warning("LLM 调用失败: {table1} <-> {table2}, 跳过")
     │
     ▼
  返回空列表，继续处理下一对
```

### 4.7 字段语义说明

`rel_llm` 输出的关系 JSON 中，部分字段与启发式流程语义不同：

| 字段 | 启发式流程语义 | LLM 流程语义 | 说明 |
|------|---------------|-------------|------|
| `target_source_type` | 目标列的来源类型 | 关系的发现来源 | LLM 不提供目标列类型信息 |
| `source_constraint` | 源列约束类型 | 固定为 `null` | LLM 不提供源列约束信息 |
| `discovery_method` | 发现方法（多种） | 固定为 `llm_assisted` | 统一标记 |

**启发式流程示例**（`target_source_type` 表示目标列类型）：
```json
{
  "discovery_method": "logical_key_matching",
  "target_source_type": "candidate_logical_key",
  "source_constraint": "unique_constraint"
}
```

**LLM 流程示例**（`target_source_type` 表示发现来源）：
```json
{
  "discovery_method": "llm_assisted",
  "target_source_type": "llm_inferred",
  "source_constraint": null
}
```

> **设计决策**：LLM 只返回表名和列名，不提供目标列是"逻辑主键"还是"物理约束"的信息。若需细粒度区分，可后续扩展检查目标表元数据，但会增加复杂度。当前采用简化设计，统一标记为 `llm_inferred`。

---

## 5. CQL 生成调整（通用修复）

> **说明**：此修改是对现有 bug 的修复，**同时影响 `cql` 和 `cql_llm` 两个步骤**，不是 LLM 特定修改。

### 5.1 问题描述

当前代码在 `_extract_join_relation` 方法中**无条件翻转**所有关系方向，这是错误的。

### 5.2 修改方案

根据 `cardinality` 决定是否翻转方向，确保 Neo4j 中**箭头指向 1 侧**：

| rel JSON 中的 cardinality | 含义 | CQL 方向处理 | 结果 |
|---------------------------|------|--------------|------|
| `1:N` | from=1, to=N | **翻转**：`to → from` | 箭头从 N 指向 1 |
| `N:1` | from=N, to=1 | **不翻转**：`from → to` | 箭头从 N 指向 1 |
| `1:1` | 对称 | **不翻转** | 保持原样 |
| `M:N` | 对称 | **不翻转** | 保持原样 |

### 5.3 代码修改

修改 `src/metaweave/core/cql_generator/reader.py`：

```python
def _extract_join_relation(self, rel: Dict[str, Any]) -> JOINOnRelation:
    """从关系 JSON 中提取 JOIN_ON 关系
    
    方向处理：根据 cardinality 决定是否翻转，确保箭头指向 1 侧
    - 1:N → 翻转（箭头从 N 指向 1）
    - N:1 → 不翻转（箭头已从 N 指向 1）
    - 1:1 / M:N → 不翻转（对称关系）
    """
    from_table = rel.get("from_table", {})
    to_table = rel.get("to_table", {})
    raw_cardinality = rel.get("cardinality", "N:1")
    
    logger.debug(f"处理关系: {from_table.get('table')} -> {to_table.get('table')}, cardinality={raw_cardinality}")
    
    # 根据 cardinality 决定是否翻转
    if raw_cardinality == "1:N":
        # 翻转方向：to → from，基数变为 N:1
        src_schema = to_table.get("schema", "")
        src_table = to_table.get("table", "")
        dst_schema = from_table.get("schema", "")
        dst_table = from_table.get("table", "")
        cardinality = "N:1"
        
        # 列也要翻转
        rel_type = rel.get("type", "")
        if rel_type == "single_column":
            source_columns = [rel.get("to_column", "")]
            target_columns = [rel.get("from_column", "")]
        else:
            source_columns = rel.get("to_columns", [])
            target_columns = rel.get("from_columns", [])
        
        logger.debug(f"1:N 关系翻转: {src_table} -> {dst_table}, cardinality={cardinality}")
    else:
        # N:1 / 1:1 / M:N 不翻转
        src_schema = from_table.get("schema", "")
        src_table = from_table.get("table", "")
        dst_schema = to_table.get("schema", "")
        dst_table = to_table.get("table", "")
        cardinality = raw_cardinality
        
        rel_type = rel.get("type", "")
        if rel_type == "single_column":
            source_columns = [rel.get("from_column", "")]
            target_columns = [rel.get("to_column", "")]
        else:
            source_columns = rel.get("from_columns", [])
            target_columns = rel.get("to_columns", [])
        
        logger.debug(f"{raw_cardinality} 关系保持原向: {src_table} -> {dst_table}")
    
    src_full_name = f"{src_schema}.{src_table}"
    dst_full_name = f"{dst_schema}.{dst_table}"
    
    # 构造 ON 表达式
    on_parts = []
    for src_col, tgt_col in zip(source_columns, target_columns):
        on_parts.append(f"SRC.{src_col} = DST.{tgt_col}")
    on_expr = " AND ".join(on_parts)
    
    logger.info(f"CQL 关系: ({src_full_name})-[:JOIN_ON]->({dst_full_name}), cardinality={cardinality}")
    
    return JOINOnRelation(
        src_full_name=src_full_name,
        dst_full_name=dst_full_name,
        cardinality=cardinality,
        join_type="INNER JOIN",
        on=on_expr,
        source_columns=source_columns,
        target_columns=target_columns,
        constraint_name=rel.get("constraint_name")
    )
```

### 5.4 rel JSON 格式（保持不变）

rel JSON 格式与现有代码保持一致，不做修改：

```json
{
  "relationships": [
    {
      "type": "single_column",
      "from_table": {"schema": "public", "table": "dim_company"},
      "to_table": {"schema": "public", "table": "dim_store"},
      "from_column": "company_id",
      "to_column": "company_id",
      "discovery_method": "llm_assisted",
      "composite_score": 1.0,
      "confidence_level": "high",
      "metrics": {
        "inclusion_rate": 1.0,
        "jaccard_index": 1.0,
        "name_similarity": 1.0,
        "type_compatibility": 1.0
      },
      "cardinality": "1:N"
    },
    {
      "type": "composite",
      "from_table": {"schema": "public", "table": "equipment_config"},
      "to_table": {"schema": "public", "table": "maintenance_work_order"},
      "from_columns": ["equipment_id", "config_version"],
      "to_columns": ["equipment_id", "config_version"],
      "discovery_method": "llm_assisted",
      "composite_score": 0.85,
      "confidence_level": "high",
      "metrics": {
        "inclusion_rate": 0.8,
        "jaccard_index": 0.7,
        "name_similarity": 1.0,
        "type_compatibility": 1.0
      },
      "cardinality": "N:1"
    }
  ]
}
```

---

## 6. 配置设计

### 6.1 metadata_config.yaml 新增/修改配置

#### 6.1.1 输出目录配置

```yaml
output:
  output_dir: output/metaweave/metadata
  
  # 表/列画像输出
  json_directory: output/metaweave/metadata/json          # --step json 输出 / --step rel & cql 输入
  json_llm_directory: output/metaweave/metadata/json_llm  # --step json_llm 输出 / --step rel_llm & cql_llm 输入
  
  # 关系发现输出
  rel_directory: output/metaweave/metadata/rel            # --step rel/rel_llm 输出 / --step cql/cql_llm 输入
  
  # CQL 生成输出
  cql_directory: output/metaweave/metadata/cql            # --step cql/cql_llm 输出 / load 输入
  # 注意：--step cql 读取 json_directory，--step cql_llm 读取 json_llm_directory
```

#### 6.1.2 LLM 配置

`rel_llm` 步骤复用现有 `LLMService`（`src/metaweave/services/llm_service.py`），支持 qwen-plus 和 deepseek。

**metadata_config.yaml 中的 LLM 配置**（已存在）：

```yaml
llm:
  # 提供商：qwen-plus | deepseek
  provider: qwen-plus
  
  # 模型名称
  # qwen 系列：qwen-turbo, qwen-plus, qwen-max, qwen-long
  # deepseek 系列：deepseek-chat
  model: ${DASHSCOPE_MODEL:qwen-plus}
  
  # API 密钥（从环境变量读取）
  api_key: ${DASHSCOPE_API_KEY}           # qwen-plus 使用
  # api_key: ${DEEPSEEK_API_KEY}          # deepseek 使用
  
  # API 基础 URL（deepseek 需要）
  api_base: ${DEEPSEEK_API_BASE:https://api.deepseek.com/v1}
  
  # 模型参数
  temperature: 0.1      # 低温度，保证输出稳定
  max_tokens: 500
  timeout: 60
  retry_times: 3
```

**环境变量配置**（.env 文件）：

```bash
# 通义千问（qwen-plus）
DASHSCOPE_API_KEY=sk-xxxx

# DeepSeek（可选）
# DEEPSEEK_API_KEY=sk-xxxx
# DEEPSEEK_API_BASE=https://api.deepseek.com/v1
```

> **说明**：`LLMService` 使用 LangChain 封装，qwen-plus 使用 `ChatTongyi`，deepseek 使用 `ChatOpenAI`（OpenAI 兼容 API）。

---

## 7. 代码修改清单

### 7.1 新增文件

| 文件 | 说明 |
|------|------|
| `src/metaweave/core/metadata/llm_json_generator.py` | 简化版 JSON 生成器 |
| `src/metaweave/core/relationships/llm_relationship_discovery.py` | LLM 关联发现 |

### 7.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `src/metaweave/cli/main.py` | 新增 `json_llm`, `rel_llm`, `cql_llm` 步骤 |
| `src/metaweave/core/cql_generator/reader.py` | 根据 cardinality 决定翻转（修复方向问题） |
| `configs/metaweave/metadata_config.yaml` | 新增 `json_llm_directory` 配置 |

### 7.3 步骤与读写路径映射

| 步骤 | 读取目录 | 写入目录 |
|------|----------|----------|
| `json` | `ddl/` | `json/` |
| `json_llm` | `ddl/` | `json_llm/` |
| `rel` | `json/` | `rel/` |
| `rel_llm` | `json_llm/` | `rel/` |
| `cql` | `json/` + `rel/` | `cql/` |
| `cql_llm` | `json_llm/` + `rel/` | `cql/` |

### 7.4 代码复用说明

| 步骤 | 复用率 | 说明 |
|------|--------|------|
| `cql_llm` | ~95% | 完全复用 `CQLGenerator`，仅在 CLI 层覆盖 `json_dir` 路径为 `json_llm/` |

`cql_llm` 实现只需在 CLI 添加分支，覆盖 `generator.json_dir` 即可：

```python
# src/metaweave/cli/metadata_cli.py

# 在现有 step == "cql" 分支前添加 cql_llm 分支
if step == "cql_llm":
    from src.metaweave.core.cql_generator.generator import CQLGenerator
    
    click.echo("🔧 开始生成 Neo4j CQL (LLM 流程)...")
    click.echo("")
    
    generator = CQLGenerator(config_path)
    
    # 覆盖 json_dir 为 json_llm 目录
    json_llm_dir = generator._resolve_path(
        generator.config.get("output", {}).get("json_llm_directory")
    )
    
    # 检查 json_llm 目录是否存在
    if not json_llm_dir.exists():
        raise FileNotFoundError(
            f"json_llm 目录不存在: {json_llm_dir}\n"
            f"请先执行 --step json_llm 生成简化版 JSON"
        )
    
    generator.json_dir = json_llm_dir
    logger.info(f"cql_llm: 使用 json_llm 目录: {json_llm_dir}")
    
    result = generator.generate()
    
    # 后续统计输出与 step == "cql" 完全相同，可复用
    # ... (省略，与 cql 分支一致)
    
    return

# 保持现有 cql 分支不变
if step == "cql":
    from src.metaweave.core.cql_generator.generator import CQLGenerator
    
    click.echo("🔧 开始生成 Neo4j CQL...")
    # ... 原有逻辑
```

**关键点**：
- `cql_llm` 与 `cql` 的唯一区别是 `json_dir` 路径
- `rel_directory` 保持不变（都读取 `rel/`）
- `cql_directory` 保持不变（都写入 `cql/`）
- 目录不存在时直接报错退出，不 fallback

---

## 8. 测试计划

### 8.1 集成测试

```bash
# LLM 辅助流程
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step ddl
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json_llm
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step cql_llm
python -m src.metaweave.cli.main load --type cql --clean

# 传统流程（对比测试）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step ddl
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step cql
python -m src.metaweave.cli.main load --type cql --clean
```

### 8.2 验证点

1. `json_llm/` 目录生成的 JSON 不包含推断内容
2. `rel/relationships_global.json` 格式正确
3. CQL 中箭头方向正确（指向 1 侧）
4. Neo4j 中关系的 cardinality 与箭头方向一致

### 8.3 错误场景测试

```bash
# 测试：未执行 json_llm 直接执行 rel_llm，应报错退出
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm
# 预期：FileNotFoundError: 请先执行 --step json_llm 生成简化版 JSON

# 测试：未执行 json_llm 直接执行 cql_llm，应报错退出
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step cql_llm
# 预期：FileNotFoundError: 请先执行 --step json_llm 生成简化版 JSON
```

---

## 9. 风险与应对

| 风险 | 应对措施 |
|------|----------|
| LLM 输出格式不稳定 | JSON Schema 校验 + 重试机制 |
| LLM 调用失败 | 跳过该表对，记录警告日志，继续处理 |
| LLM 响应慢 | 超时控制 |

---

## 附录 A：现有评分逻辑复用

`RelationshipScorer._calculate_scores` 方法签名：

```python
def _calculate_scores(
        self,
        source_table: dict,      # 完整的表元数据 JSON
        source_columns: List[str],
        target_table: dict,
        target_columns: List[str]
) -> Tuple[Dict[str, float], str]:
    """返回 (评分字典, 基数)"""
```

四个评分维度：
1. **inclusion_rate** (55%)：源表值在目标表中的包含率
2. **name_similarity** (20%)：列名相似度
3. **type_compatibility** (15%)：类型兼容性
4. **jaccard_index** (10%)：Jaccard 相似度

`rel_llm` 步骤直接调用此方法，只是候选来源从启发式规则变为 LLM 建议。
