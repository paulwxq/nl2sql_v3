# Bug 修复：source_constraint 硬编码问题

## 🐛 问题描述

在 `relationships_global.json` 中，发现 `source_constraint` 字段被硬编码为 `"single_field_index"`，即使源列实际上并没有索引。

### 问题案例

```json
{
  "from_table": {"schema": "public", "table": "dim_product_type"},
  "to_table": {"schema": "public", "table": "fact_store_sales_month"},
  "from_column": "product_type_id",
  "to_column": "product_type_id",
  "discovery_method": "active_search",
  "source_type": null,
  "source_constraint": "single_field_index",  // ❌ 错误！
  ...
}
```

### 实际情况

查看 `dim_product_type.json` 的 `product_type_id` 列：

```json
"structure_flags": {
  "is_primary_key": false,      // 不是物理主键
  "is_foreign_key": false,
  "is_unique": true,             // 只是数据唯一（不是约束）
  "is_unique_constraint": false, // ❌ 没有唯一约束
  "is_indexed": false,           // ❌ 没有索引
  "is_nullable": false
}
```

**结论**：`dim_product_type.product_type_id` 只是**数据碰巧唯一**，没有任何物理约束，`source_constraint` 应该是 `null`，而不是 `"single_field_index"`。

---

## 🔍 根本原因

### 问题代码位置

**`src/metaweave/core/relationships/writer.py:300-305`**（修复前）

```python
# 单列主动搜索
if inference_method == "single_active_search":
    return {
        "discovery_method": "active_search",
        "source_type": None,
        "source_constraint": "single_field_index"  # ❌ 硬编码，没有检查实际约束
    }
```

### 为什么会触发 active_search？

在 `candidate_generator.py` 中：

```python
def _has_important_constraint(self, col_profile: dict) -> bool:
    structure_flags = col_profile.get("structure_flags", {})
    
    # 检查单列唯一约束
    if structure_flags.get("is_unique") or structure_flags.get("is_unique_constraint"):
        if "single_field_unique_constraint" in self.important_constraints:
            return True  # ✅ is_unique=True 满足条件，触发 active_search
```

**问题**：`is_unique=True` 触发了 active_search，但 writer 硬编码返回 `"single_field_index"`，没有区分实际的约束类型。

---

## ✅ 修复方案

### 修改的文件

1. **`src/metaweave/core/relationships/writer.py`**
   - 修改 `write_results()` 方法：添加 `tables` 参数
   - 修改 `_parse_discovery_info()` 方法：调用新的 `_get_source_constraint()`
   - 新增 `_get_source_constraint()` 方法：检查源列的实际约束类型

2. **`src/metaweave/core/relationships/pipeline.py`**
   - 调用 `writer.write_results()` 时传入 `self.tables`

### 修复后的逻辑

```python
def _parse_discovery_info(self, inference_method, rel):
    if inference_method == "single_active_search":
        # ✅ 正确：检查实际约束
        constraint = self._get_source_constraint(rel)
        return {
            "discovery_method": "active_search",
            "source_type": None,
            "source_constraint": constraint  # 根据实际情况返回
        }

def _get_source_constraint(self, rel):
    """获取源列的实际约束类型"""
    # 获取源列的 structure_flags
    structure_flags = ...
    
    # 按优先级检查
    if structure_flags.get("is_primary_key"):
        return "single_field_primary_key"
    elif structure_flags.get("is_unique_constraint"):
        return "single_field_unique_constraint"
    elif structure_flags.get("is_indexed"):
        return "single_field_index"
    else:
        return None  # 没有物理约束
```

---

## 🧪 测试验证

运行 `tests/test_source_constraint_fix.py`：

```bash
python tests/test_source_constraint_fix.py
```

### 测试结果

```
✅ 主键           -> single_field_primary_key
✅ 唯一约束       -> single_field_unique_constraint
✅ 索引           -> single_field_index
✅ 只有数据唯一   -> None（正确！）
✅ 无任何约束     -> None
```

### 实际案例测试

```
dim_product_type.product_type_id:
  is_unique: True（数据唯一）
  is_indexed: False（没有索引）
  
✅ 检测结果: None（正确！）
```

---

## 📊 修复前后对比

| 场景 | 修复前 | 修复后 | 说明 |
|------|--------|--------|------|
| 主键列 | `"single_field_index"` ❌ | `"single_field_primary_key"` ✅ | 正确识别主键 |
| 唯一约束列 | `"single_field_index"` ❌ | `"single_field_unique_constraint"` ✅ | 正确识别唯一约束 |
| 索引列 | `"single_field_index"` ✅ | `"single_field_index"` ✅ | 保持正确 |
| 只有数据唯一的列 | `"single_field_index"` ❌ | `null` ✅ | 正确识别无物理约束 |

---

## 🎯 影响范围

### 不受影响的代码

- ✅ **关系发现逻辑**：`candidate_generator.py`、`scorer.py`、`decision_engine.py` 都不受影响
- ✅ **其他 discovery_method**：只修改了 `single_active_search` 的处理，其他方法不变
- ✅ **向后兼容**：`tables` 参数是可选的，如果不传则返回 `None`

### 需要重新运行

修复后，需要重新运行关系发现流程以生成正确的 JSON：

```bash
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel
```

---

## 📝 验证修复

修复后，`relationships_global.json` 中的 `dim_product_type.product_type_id` 关系应该显示：

```json
{
  "from_table": {"schema": "public", "table": "dim_product_type"},
  "to_table": {"schema": "public", "table": "fact_store_sales_month"},
  "from_column": "product_type_id",
  "to_column": "product_type_id",
  "discovery_method": "active_search",
  "source_type": null,
  "source_constraint": null,  // ✅ 正确！没有物理约束
  ...
}
```

---

## 🔗 相关文件

- **修改的代码**：
  - `src/metaweave/core/relationships/writer.py`
  - `src/metaweave/core/relationships/pipeline.py`

- **测试文件**：
  - `tests/test_source_constraint_fix.py`

- **相关数据**：
  - `output/metaweave/metadata/json/public.dim_product_type.json`
  - `output/metaweave/metadata/json/public.fact_store_sales_month.json`
  - `output/metaweave/metadata/rel/relationships_global.json`

---

## ✨ 总结

这个修复确保了 `source_constraint` 字段准确反映源列的**实际物理约束类型**，而不是硬编码的错误值。这对于：

1. **数据库优化建议**：正确识别哪些列需要添加索引
2. **关系可靠性判断**：区分物理约束和逻辑关系
3. **文档准确性**：为用户提供准确的元数据信息

修复后的代码更加健壮和准确！🎉

