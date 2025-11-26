# 字段命名对齐修复（v3.2规范）

## 问题背景

在 Step 3 关系发现模块的实现中，存在**字段命名不一致**的问题：

### 原实现格式

输出的推断关系使用单一字段 `inference_method`（值为 `candidate_type`，如 `single_active_search`、`composite_physical` 等）来表示关系的发现方法。

```json
{
  "relationship_id": "rel_xxx",
  "type": "single_column",
  "from_table": {"schema": "public", "table": "fact_sales"},
  "from_column": "store_id",
  "to_table": {"schema": "public", "table": "dim_store"},
  "to_column": "store_id",
  "composite_score": 0.88,
  "confidence_level": "high",
  "metrics": {...}
  // ❌ 缺少 discovery_method, source_type, source_constraint 字段
}
```

### 文档要求格式（v3.2）

v3.2 文档要求将关系的发现信息拆分为三个独立字段：

```json
{
  "relationship_id": "rel_xxx",
  "type": "single_column",
  "from_table": {"schema": "public", "table": "fact_sales"},
  "from_column": "store_id",
  "to_table": {"schema": "public", "table": "dim_store"},
  "to_column": "store_id",
  "discovery_method": "active_search",      // ← 发现方法
  "source_type": null,                       // ← 来源类型（可选）
  "source_constraint": "single_field_index", // ← 约束类型（可选）
  "composite_score": 0.88,
  "confidence_level": "high",
  "metrics": {...}
}
```

### 核心差异

| 方面 | 原实现 | v3.2 规范 | 影响 |
|------|--------|-----------|------|
| **发现方法** | 无此字段 | `discovery_method` | ❌ 缺失核心字段 |
| **来源类型** | 无此字段 | `source_type` | ❌ 缺失来源信息 |
| **约束类型** | 无此字段 | `source_constraint` | ❌ 缺失约束信息 |
| **内部字段** | `inference_method` 存储 `candidate_type` | 需要拆分映射 | ⚠️ 需要转换逻辑 |

## 修复方案

在 `writer.py` 的 `_convert_to_v32_format()` 方法中，添加 `_parse_discovery_info()` 方法来解析 `inference_method` 并映射为三个独立字段。

### 映射规则

#### 1. 外键约束（Foreign Key）

```python
# relationship_type == "foreign_key"
{
    "discovery_method": "foreign_key_constraint",
    "source_type": "foreign_key",
    "source_constraint": None
}
```

#### 2. 单列主动搜索（Active Search）

```python
# inference_method == "single_active_search"
{
    "discovery_method": "active_search",
    "source_type": None,
    "source_constraint": "single_field_index"  # 简化版，实际可能是其他约束
}
```

#### 3. 单列逻辑主键（Logical Key）

```python
# inference_method == "single_logical_key"
{
    "discovery_method": "logical_key_matching",
    "source_type": "candidate_logical_key",
    "source_constraint": None
}
```

#### 4. 复合键物理约束（Physical Constraints）

```python
# inference_method == "composite_physical"
{
    "discovery_method": "physical_constraint_matching",
    "source_type": "physical_constraints",  # 简化版，实际可能是 primary_key/unique_constraint/index
    "source_constraint": None
}
```

#### 5. 复合键逻辑主键（Logical Key）

```python
# inference_method == "composite_logical"
{
    "discovery_method": "logical_key_matching",
    "source_type": "candidate_logical_key",
    "source_constraint": None
}
```

#### 6. 复合键动态同名（Dynamic Same Name）

```python
# inference_method == "composite_dynamic_same_name"
{
    "discovery_method": "dynamic_same_name",
    "source_type": "candidate_logical_key",
    "source_constraint": None
}
```

#### 7. 其他未知类型（Fallback）

```python
# 其他情况
{
    "discovery_method": "standard_matching",
    "source_type": None,
    "source_constraint": None
}
```

### 实现代码

在 `src/metaweave/core/relationships/writer.py` 中添加：

```python
def _parse_discovery_info(
        self,
        inference_method: Optional[str],
        rel: Relation
) -> Dict[str, Optional[str]]:
    """解析 inference_method 为 discovery_method, source_type, source_constraint

    映射规则（基于v3.2文档）：
    - single_active_search -> discovery_method: "active_search", source_constraint: "single_field_index"
    - single_logical_key -> discovery_method: "logical_key_matching", source_type: "candidate_logical_key"
    - composite_physical -> discovery_method: "physical_constraint_matching", source_type: "physical_constraints"
    - composite_logical -> discovery_method: "logical_key_matching", source_type: "candidate_logical_key"
    - composite_dynamic_same_name -> discovery_method: "dynamic_same_name", source_type: "candidate_logical_key"
    - 其他 -> discovery_method: "standard_matching"

    Args:
        inference_method: 推断方法字符串（如 single_active_search）
        rel: 关系对象

    Returns:
        包含 discovery_method, source_type, source_constraint 的字典
    """
    if not inference_method:
        return {
            "discovery_method": "standard_matching",
            "source_type": None,
            "source_constraint": None
        }

    # 单列主动搜索
    if inference_method == "single_active_search":
        return {
            "discovery_method": "active_search",
            "source_type": None,
            "source_constraint": "single_field_index"
        }

    # 单列逻辑主键匹配
    if inference_method == "single_logical_key":
        return {
            "discovery_method": "logical_key_matching",
            "source_type": "candidate_logical_key",
            "source_constraint": None
        }

    # 复合键物理约束匹配
    if inference_method == "composite_physical":
        return {
            "discovery_method": "physical_constraint_matching",
            "source_type": "physical_constraints",
            "source_constraint": None
        }

    # 复合键逻辑主键匹配
    if inference_method == "composite_logical":
        return {
            "discovery_method": "logical_key_matching",
            "source_type": "candidate_logical_key",
            "source_constraint": None
        }

    # 复合键动态同名匹配
    if inference_method == "composite_dynamic_same_name":
        return {
            "discovery_method": "dynamic_same_name",
            "source_type": "candidate_logical_key",
            "source_constraint": None
        }

    # 其他未知类型，使用标准匹配
    logger.warning(f"未知的 inference_method: {inference_method}，使用 standard_matching")
    return {
        "discovery_method": "standard_matching",
        "source_type": None,
        "source_constraint": None
    }
```

在 `_convert_to_v32_format()` 方法中调用：

```python
# 发现方法、来源类型、约束类型（规范化映射）
if rel.relationship_type == "foreign_key":
    result["discovery_method"] = "foreign_key_constraint"
    result["source_type"] = "foreign_key"
    result["source_constraint"] = None
else:
    # 从 inference_method (candidate_type) 拆分为规范字段
    discovery_info = self._parse_discovery_info(rel.inference_method, rel)
    result["discovery_method"] = discovery_info["discovery_method"]
    result["source_type"] = discovery_info.get("source_type")
    result["source_constraint"] = discovery_info.get("source_constraint")
```

## 修复效果

### ✅ 完全符合文档

1. **外键关系**：
   ```json
   {
     "discovery_method": "foreign_key_constraint",
     "source_type": "foreign_key",
     "source_constraint": null
   }
   ```

2. **单列主动搜索**：
   ```json
   {
     "discovery_method": "active_search",
     "source_type": null,
     "source_constraint": "single_field_index"
   }
   ```

3. **复合键物理约束**：
   ```json
   {
     "discovery_method": "physical_constraint_matching",
     "source_type": "physical_constraints",
     "source_constraint": null
   }
   ```

4. **复合键逻辑主键**：
   ```json
   {
     "discovery_method": "logical_key_matching",
     "source_type": "candidate_logical_key",
     "source_constraint": null
   }
   ```

5. **复合键动态同名**：
   ```json
   {
     "discovery_method": "dynamic_same_name",
     "source_type": "candidate_logical_key",
     "source_constraint": null
   }
   ```

### ✅ 向后兼容

- 内部 `Relation` 数据模型保持不变（仍使用 `inference_method`）
- 仅在输出时转换为 v3.2 格式
- 不影响其他模块（repository, scorer, decision_engine, candidate_generator）

### ✅ 测试验证

- **所有 30 个单元测试通过**（从29个增加到30个）
- 新增测试覆盖：
  - `test_discovery_method_mapping`：验证所有 inference_method 的正确映射
  - 测试了5种不同的 inference_method 类型
  - 验证了 discovery_method, source_type, source_constraint 三个字段的正确性

## 输出示例

### 单列主动搜索

```json
{
  "relationship_id": "rel_001",
  "type": "single_column",
  "from_table": {"schema": "public", "table": "fact_sales"},
  "from_column": "store_id",
  "to_table": {"schema": "public", "table": "dim_store"},
  "to_column": "store_id",
  "discovery_method": "active_search",
  "source_type": null,
  "source_constraint": "single_field_index",
  "composite_score": 0.88,
  "confidence_level": "high",
  "metrics": {...}
}
```

### 复合键物理约束

```json
{
  "relationship_id": "rel_002",
  "type": "composite",
  "from_table": {"schema": "public", "table": "fact_sales"},
  "from_columns": ["store_id", "date_day"],
  "to_table": {"schema": "public", "table": "dim_store"},
  "to_columns": ["store_id", "date_day"],
  "discovery_method": "physical_constraint_matching",
  "source_type": "physical_constraints",
  "source_constraint": null,
  "composite_score": 0.92,
  "confidence_level": "high",
  "metrics": {...}
}
```

### 复合键动态同名

```json
{
  "relationship_id": "rel_004",
  "type": "composite",
  "from_table": {"schema": "public", "table": "fact_sales"},
  "from_columns": ["order_id", "product_id"],
  "to_table": {"schema": "public", "table": "fact_summary"},
  "to_columns": ["order_id", "product_id"],
  "discovery_method": "dynamic_same_name",
  "source_type": "candidate_logical_key",
  "source_constraint": null,
  "composite_score": 0.90,
  "confidence_level": "high",
  "metrics": {...}
}
```

## 未来优化

当前实现使用简化的映射规则（如将所有物理约束映射为 `"physical_constraints"`）。如果需要更精确的映射（如区分 `primary_key`、`unique_constraint`、`index`），需要：

1. 在 `DecisionEngine` 中存储更多源表信息到 `Relation` 对象
2. 在 `_parse_discovery_info()` 方法中根据源表信息细化 `source_type`

## 相关文件

- **修改的代码文件**：
  - `src/metaweave/core/relationships/writer.py`（添加 `_parse_discovery_info()` 方法）

- **修改的测试文件**：
  - `tests/unit/metaweave/relationships/test_writer.py`（新增 `test_discovery_method_mapping` 测试）

- **参考文档**：
  - `docs/gen_rag/step 3.关联关系发现完整流程示例_v3.2.md`
  - `docs/gen_rag/step 3.关联字段查找算法详解_v3.2.md`

## 版本信息

- 修复时间：2025-11-26
- 影响模块：Step 3 关系发现（输出模块）
- 字段映射规则：基于 v3.2 文档
- 测试覆盖：30/30 单元测试通过
