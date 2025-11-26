# JSON 格式升级到 v2.0 - 修改摘要

## 修改日期
2025-11-22

## 修改概述

将元数据 JSON 格式从 v1.0 升级到 v2.0，主要改进包括：
1. 重组 JSON 结构，使其更加层次化和易于理解
2. 添加样例数据支持
3. 优化字段分组

## 修改的文件

### 1. 模板文件（手动修改）
- ✅ `_template.json` - 完整模板
- ✅ `_template_minimal.json` - 精简模板  
- ✅ `_template_with_comments.jsonc` - 带注释模板
- ✅ `README_TEMPLATE.md` - 说明文档

**主要修改**：
- 将 `statistics.count` 改为 `statistics.sample_count` 以匹配现有字段名

### 2. 代码文件（代码生成 JSON 格式）

#### `src/metaweave/core/metadata/models.py`

**修改 1: ColumnProfile.to_dict()**
```python
# 旧格式
{
  "column_name": "...",
  "semantic_role": "...",
  "semantic_confidence": 0.9,
  "structure_flags": {...},
  "identifier_info": {...},
  "inference_basis": [...]
}

# 新格式 v2.0
{
  "column_name": "...",
  "semantic_analysis": {
    "semantic_role": "...",
    "semantic_confidence": 0.9,
    "inference_basis": [...]
  },
  "structure_flags": {...},
  "role_specific_info": {
    "identifier_info": {...},
    "metric_info": {...},
    ...
  }
}
```

**修改 2: TableMetadata.to_dict()**
```python
# 旧格式
{
  "schema_name": "...",
  "table_name": "...",
  "primary_keys": [],
  "foreign_keys": [],
  "column_profiles": {...},
  "table_profile": {...},
  "candidate_logical_primary_keys": [...]
}

# 新格式 v2.0
{
  "metadata_version": "2.0",
  "generated_at": "2025-11-22T...",
  "table_info": {
    "schema_name": "...",
    "table_name": "...",
    "total_rows": 100,
    "total_columns": 10,
    "constraints": {
      "primary_keys": [],
      "foreign_keys": [],
      "unique_constraints": [],
      "indexes": []
    }
  },
  "column_profiles": {...},
  "table_profile": {
    ...
    "candidate_logical_primary_keys": [...]
  },
  "sample_records": {
    "sample_method": "random",
    "sample_size": 5,
    "total_rows": 100,
    "sampled_at": "...",
    "records": [...]
  }
}
```

**修改 3: TableProfile 数据类**
- 添加 `candidate_logical_primary_keys` 字段
- 调整 `to_dict()` 输出顺序和结构

#### `src/metaweave/core/metadata/profiler.py`

**修改**: `_profile_table()` 方法
- 在创建 `TableProfile` 时传递 `candidate_logical_primary_keys`

#### `src/metaweave/core/metadata/formatter.py`

**新增方法**: `_extract_sample_records_from_ddl()`
- 从 DDL 文件的 `SAMPLE_RECORDS` 注释块提取样例数据
- 自动转换数据类型（字符串数字 → 数字类型）
- 最多返回 5 条记录

**修改方法**: `_save_json()`
- 添加 `sample_data` 参数
- 优先从 DDL 提取样例数据
- 其次从 `sample_data` DataFrame 提取
- 将样例数据添加到 JSON 输出

**修改调用**: `format_and_save()`
- 调用 `_save_json()` 时传递 `sample_data` 参数

## v2.0 格式的主要特点

### 1. 顶层结构
```json
{
  "metadata_version": "2.0",
  "generated_at": "ISO 8601 时间戳",
  "table_info": {...},
  "column_profiles": {...},
  "table_profile": {...},
  "sample_records": {...}
}
```

### 2. table_info 分组
- 基本信息：schema、table、type、comment、total_rows、total_columns
- 约束信息：constraints (primary_keys, foreign_keys, unique_constraints, indexes)

### 3. column_profiles 优化
- `semantic_analysis`: 语义分析结果（role、confidence、inference_basis）
- `role_specific_info`: 角色特定信息（identifier_info、metric_info 等）

### 4. table_profile 增强
- 包含 `candidate_logical_primary_keys`
- 调整字段顺序，将 inference_basis 提前

### 5. sample_records 新增
- 元信息：sample_method、sample_size、total_rows、sampled_at
- 记录数组：保持原始数据类型

## 如何重新生成 JSON

```bash
# 方式 1: 使用 CLI
python -m src.metaweave.cli.metadata_cli generate \
  --config configs/metaweave/metadata_config.yaml \
  --step json

# 方式 2: 使用脚本
python scripts/metaweave/run_metadata_generation.py --step json
```

## 注意事项

1. **字段名变更**: 
   - `row_count` → `total_rows`
   - `column_count` → `total_columns`
   - `statistics.count` → `statistics.sample_count`
2. **样例数据来源**: 优先从 DDL 的 `SAMPLE_RECORDS` 提取，其次从数据库采样
3. **数据类型转换**: 样例数据中的数值会自动从字符串转换为数字类型
4. **条件字段**: `fact_table_info`, `dim_table_info`, `bridge_table_info` 只在非 null 时才出现
5. **向后兼容**: 旧代码可能无法读取 v2.0 格式，需要更新解析逻辑

## 测试建议

1. 运行重新生成命令，检查所有表的 JSON 文件
2. 验证 JSON 格式是否符合模板
3. 检查样例数据是否正确提取和转换
4. 确认数据类型（数字 vs 字符串）正确
5. 测试下游使用 JSON 的代码是否需要更新

## 相关文档

- `_template.json` - 完整格式参考
- `_template_with_comments.jsonc` - 字段说明
- `README_TEMPLATE.md` - 使用指南

