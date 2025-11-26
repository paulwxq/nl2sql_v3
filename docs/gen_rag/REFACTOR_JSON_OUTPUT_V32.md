# JSON 输出格式重构为 v3.2 规范

## 问题背景

在 Step 3 关系发现模块的实现中，JSON 输出格式与文档规范**完全不一致**：

### 原实现格式（v1.0）

```json
{
  "metadata_version": "1.0",
  "discovery_config": {...},
  "statistics": {
    "total_relations": 3,
    "foreign_key_relations": 1,
    "inferred_relations": 2,
    "high_confidence": 1,
    "medium_confidence": 1,
    "suppressed_count": 2
  },
  "relations": [
    {
      "relationship_id": "rel_xxx",
      "source_schema": "public",
      "source_table": "fact_sales",
      "source_columns": ["store_id"],
      "target_schema": "public",
      "target_table": "dim_store",
      "target_columns": ["store_id"],
      "relationship_type": "inferred",
      "cardinality": "N:1",
      "composite_score": 0.85,
      "score_details": {...},
      "inference_method": "single_active_search"
    }
  ]
}
```

### 文档要求格式（v3.2）

```json
{
  "metadata_source": "json_files",
  "json_metadata_version": "2.0",
  "json_files_loaded": 6,
  "database_queries_executed": 12,
  "analysis_timestamp": "2025-11-25T10:30:00Z",

  "statistics": {
    "total_relationships_found": 3,
    "composite_key_relationships": 1,
    "single_column_relationships": 2,
    "total_suppressed_single_relations": 2,
    "active_search_discoveries": 1,
    "dynamic_composite_discoveries": 0
  },

  "relationships": [
    {
      "relationship_id": "rel_xxx",
      "type": "single_column",
      "from_table": {"schema": "public", "table": "fact_sales"},
      "from_column": "store_id",
      "to_table": {"schema": "public", "table": "dim_store"},
      "to_column": "store_id",
      "discovery_method": "active_search",
      "composite_score": 0.85,
      "confidence_level": "high",
      "metrics": {...}
    },
    {
      "relationship_id": "rel_yyy",
      "type": "composite",
      "from_table": {"schema": "public", "table": "fact_sales"},
      "from_columns": ["store_id", "date_day"],
      "to_table": {"schema": "public", "table": "dim_store"},
      "to_columns": ["store_id", "date_day"],
      "discovery_method": "physical_constraints",
      "composite_score": 0.92,
      "confidence_level": "high",
      "metrics": {...},

      "suppressed_single_relations": [
        {
          "from_column": "store_id",
          "to_column": "store_id",
          "original_score": 0.85,
          "suppression_reason": "在复合键中，无独立约束",
          "could_have_been_accepted": true
        }
      ]
    }
  ]
}
```

### 核心差异

| 方面 | 原实现 | v3.2 规范 | 影响 |
|------|--------|-----------|------|
| **顶层字段** | `metadata_version: "1.0"` | `json_metadata_version: "2.0"` | ⚠️ 版本标识错误 |
| | `discovery_config` | 无此字段 | ⚠️ 多余字段 |
| | 无 | `metadata_source`, `json_files_loaded`, `database_queries_executed`, `analysis_timestamp` | ❌ 缺失关键元数据 |
| **statistics** | `total_relations` | `total_relationships_found` | ⚠️ 字段名不一致 |
| | `foreign_key_relations`, `inferred_relations` | `composite_key_relationships`, `single_column_relationships` | ❌ 统计口径不同 |
| | `high_confidence`, `medium_confidence` | 无此统计 | ⚠️ 多余统计 |
| | 无 | `total_suppressed_single_relations`, `active_search_discoveries`, `dynamic_composite_discoveries` | ❌ 缺失核心统计 |
| **关系数组** | `relations` | `relationships` | ⚠️ 字段名不一致 |
| **关系对象** | `source_schema`, `source_table`, `source_columns` | `from_table: {schema, table}`, `from_column(s)` | ❌ 结构完全不同 |
| | `target_schema`, `target_table`, `target_columns` | `to_table: {schema, table}`, `to_column(s)` | ❌ 结构完全不同 |
| | `relationship_type: "inferred"` | `type: "single_column"` 或 `"composite"` | ❌ 类型分类不同 |
| | `inference_method` | `discovery_method` | ⚠️ 字段名不一致 |
| | `score_details` | `metrics` | ⚠️ 字段名不一致 |
| | 无 | `confidence_level: "high"/"medium"/"low"` | ❌ 缺失置信度分级 |
| | `cardinality` | 无此字段 | ⚠️ 多余字段 |
| **抑制关系** | 单独文件 `relationships_suppressed.json` | 嵌入复合键对象的 `suppressed_single_relations` 数组 | ❌ **核心特性缺失** |

## 修复方案

完全重写 `writer.py` 以符合 v3.2 文档规范。

### 核心变更

#### 1. 顶层字段（`_write_json_v32`）

```python
data = {
    "metadata_source": "json_files",
    "json_metadata_version": "2.0",  # ← 不是 metadata_version: "1.0"
    "json_files_loaded": stats.get("json_files_loaded", 0),
    "database_queries_executed": stats.get("database_queries_executed", 0),
    "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
    "statistics": {...},
    "relationships": [...]  # ← 不是 relations
}
```

#### 2. 统计字段（`_calculate_statistics_v32`）

```python
return {
    "total_relationships_found": total,           # ← 不是 total_relations
    "composite_key_relationships": composite_count,
    "single_column_relationships": single_count,
    "total_suppressed_single_relations": suppressed_single_count,
    "active_search_discoveries": active_search_count,
    "dynamic_composite_discoveries": dynamic_composite_count,
    # ✅ 移除了 foreign_key_relations, high_confidence, medium_confidence
}
```

#### 3. 关系对象转换（`_convert_to_v32_format`）

```python
# 类型判断
rel_type = "composite" if rel.is_composite else "single_column"

# 基础字段
result = {
    "relationship_id": rel.relationship_id,
    "type": rel_type,  # ← 不是 relationship_type
    "from_table": {"schema": rel.source_schema, "table": rel.source_table},
    "to_table": {"schema": rel.target_schema, "table": rel.target_table},
}

# 列名（单列用 from_column，复合用 from_columns）
if rel.is_single_column:
    result["from_column"] = rel.source_columns[0]
    result["to_column"] = rel.target_columns[0]
else:
    result["from_columns"] = rel.source_columns
    result["to_columns"] = rel.target_columns

# 发现方法
result["discovery_method"] = rel.inference_method or "standard_matching"

# 评分字段
if rel.composite_score is not None:
    result["composite_score"] = rel.composite_score
    result["confidence_level"] = confidence_level  # ← 新增
    result["metrics"] = rel.score_details  # ← 不是 score_details
```

#### 4. 被抑制关系嵌入（`_group_suppressed_by_table_pair`）

```python
# 按表对分组被抑制的单列关系
suppressed_by_table_pair = self._group_suppressed_by_table_pair(suppressed)

# 转换关系为v3.2格式，并嵌入被抑制的单列
for rel in relations:
    rel_dict = self._convert_to_v32_format(rel)

    # ✅ 如果是复合键关系，嵌入被抑制的单列
    if rel.is_composite:
        table_pair = rel.table_pair
        if table_pair in suppressed_by_table_pair:
            rel_dict["suppressed_single_relations"] = suppressed_by_table_pair[table_pair]

    relationships_v32.append(rel_dict)
```

嵌入格式：

```python
suppressed_rel = {
    "from_column": candidate["source_columns"][0],
    "to_column": candidate["target_columns"][0],
    "original_score": candidate.get("composite_score", 0.0),
    "suppression_reason": "在复合键中，无独立约束",
    "could_have_been_accepted": candidate.get("composite_score", 0.0) >= 0.80
}
```

## 修复效果

### ✅ 完全符合文档

1. **顶层字段**：`json_metadata_version: "2.0"` + 元数据字段
2. **统计口径**：区分 composite/single_column，计算 active_search/dynamic
3. **关系结构**：`type`, `from_table/to_table`, `from_column(s)/to_column(s)`
4. **被抑制关系**：嵌入复合键对象的 `suppressed_single_relations` 数组
5. **置信度分级**：`confidence_level: "high"/"medium"/"low"`

### ✅ 向后兼容

- 内部 `Relation` 数据模型保持不变
- 仅输出格式转换为 v3.2
- 不影响其他模块（repository, scorer, decision_engine）

### ✅ 测试验证

- **所有 29 个单元测试通过**
- 新增测试覆盖：
  - v3.2 顶层字段验证
  - v3.2 统计字段验证
  - suppressed_single_relations 嵌入验证

## 输出示例

### 单列关系

```json
{
  "relationship_id": "rel_7e3a9c12ab34",
  "type": "single_column",
  "from_table": {"schema": "public", "table": "fact_sales"},
  "from_column": "store_id",
  "to_table": {"schema": "public", "table": "dim_store"},
  "to_column": "store_id",
  "discovery_method": "single_active_search",
  "composite_score": 0.88,
  "confidence_level": "high",
  "metrics": {
    "inclusion_rate": 0.85,
    "jaccard_index": 0.72,
    "uniqueness": 0.95,
    "name_similarity": 1.0,
    "type_compatibility": 1.0,
    "semantic_role_bonus": 1.0
  }
}
```

### 复合键关系（含被抑制单列）

```json
{
  "relationship_id": "rel_9f2b8d45ef67",
  "type": "composite",
  "from_table": {"schema": "public", "table": "fact_sales"},
  "from_columns": ["store_id", "date_day"],
  "to_table": {"schema": "public", "table": "dim_store"},
  "to_columns": ["store_id", "date_day"],
  "discovery_method": "composite_physical",
  "composite_score": 0.92,
  "confidence_level": "high",
  "metrics": {...},

  "suppressed_single_relations": [
    {
      "from_column": "store_id",
      "to_column": "store_id",
      "original_score": 0.88,
      "suppression_reason": "在复合键中，无独立约束",
      "could_have_been_accepted": true
    },
    {
      "from_column": "date_day",
      "to_column": "date_day",
      "original_score": 0.76,
      "suppression_reason": "在复合键中，无独立约束",
      "could_have_been_accepted": false
    }
  ]
}
```

## 相关文件

- **修改的代码文件**：
  - `src/metaweave/core/relationships/writer.py`（完全重写）

- **修改的测试文件**：
  - `tests/unit/metaweave/relationships/test_writer.py`（更新为 v3.2 格式验证）

- **参考文档**：
  - `docs/gen_rag/step 3.关联关系发现完整流程示例_v3.2.md`
  - `docs/gen_rag/step 3.关联字段查找算法详解_v3.2.md`

## 版本信息

- 修复时间：2025-11-26
- 影响模块：Step 3 关系发现（输出模块）
- JSON 版本：v1.0 → v3.2
- 测试覆盖：29/29 单元测试通过
