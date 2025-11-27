# 动态同名匹配实现修复（v3.2规范）

## 问题背景

在 Step 3 关系发现模块的实现中，**动态同名匹配** 功能与文档规范不一致：

### 原实现问题

在 `src/metaweave/core/relationships/candidate_generator.py:255-280`：

```python
def _find_dynamic_same_name(self, source_columns: List[str], target_table: dict) -> List[str]:
    target_profiles = target_table.get("column_profiles", {})
    matched = []

    for src_col in source_columns:
        # ❌ 问题1：大小写敏感
        if src_col not in target_profiles:
            return None

        # ❌ 问题2：无类型兼容性检查
        # TODO: 类型兼容性检查（Phase 1暂时只检查存在性）
        matched.append(src_col)

    return matched if len(matched) == len(source_columns) else None
```

### 文档要求（v3.2）

根据 `docs/gen_rag/step 3.关联字段查找算法详解_v3.2.md:620-679`：

#### 1. 大小写不敏感

**示例2**：字段名大小写不同，但匹配成功
```python
源表复合键: ['Store_ID', 'Date_Day']
目标表字段: {'store_id': {...}, 'date_day': {...}}

# 检查：
# - 字段名集合（忽略大小写）: {'store_id', 'date_day'} == {'store_id', 'date_day'} ✓
# - 类型兼容: Store_ID(INTEGER) ↔ store_id(INTEGER) ✓
#            Date_Day(DATE) ↔ date_day(DATE) ✓
# 结果: 匹配成功 ✅
```

#### 2. 类型兼容性检查

```python
# 3. 逐列类型兼容性检查
for i, src_col in enumerate(source_columns):
    tgt_col = target_columns[i]
    source_type = source_column_profiles[src_col]['data_type']
    target_type = target_column_profiles[tgt_col]['data_type']
    if not is_type_compatible(source_type, target_type):
        return None
```

#### 3. 返回顺序

返回的 `target_columns` 保持源列顺序（原实现已正确）

---

## 修复方案

### 核心变更

#### 1. 修改方法签名

添加 `source_table` 参数以获取源列类型信息：

```python
# 修改前
def _find_dynamic_same_name(
    self,
    source_columns: List[str],
    target_table: dict
) -> List[str]:

# 修改后
def _find_dynamic_same_name(
    self,
    source_columns: List[str],
    source_table: dict,  # ← 新增参数
    target_table: dict
) -> List[str]:
```

#### 2. 添加大小写不敏感映射

```python
# 构建大小写不敏感的映射（小写列名 -> 原始列名）
target_column_map = {col_name.lower(): col_name for col_name in target_profiles.keys()}

for src_col in source_columns:
    src_col_lower = src_col.lower()

    # 大小写不敏感的同名检查
    if src_col_lower not in target_column_map:
        return None

    # 获取目标列的原始名称
    tgt_col = target_column_map[src_col_lower]
```

#### 3. 添加类型兼容性检查

```python
# 类型兼容性检查
src_profile = source_profiles.get(src_col, {})
tgt_profile = target_profiles.get(tgt_col, {})

src_type = src_profile.get("data_type", "")
tgt_type = tgt_profile.get("data_type", "")

# 使用类型兼容性检查（复用 scorer 的逻辑）
if not self._is_type_compatible(src_type, tgt_type):
    return None
```

#### 4. 添加类型兼容性方法

复用 scorer 的类型兼容性逻辑：

```python
def _is_type_compatible(self, type1: str, type2: str) -> bool:
    """检查两个类型是否兼容

    复用 scorer 的类型兼容性逻辑，但返回布尔值（>= 0.5 视为兼容）
    """
    # 标准化类型
    t1 = self._normalize_type(type1)
    t2 = self._normalize_type(type2)

    # 完全相同
    if t1 == t2:
        return True

    # 整数类型族
    int_types = {"integer", "int", "int4", "bigint", "int8", "smallint", "int2", "serial", "bigserial"}
    if t1 in int_types and t2 in int_types:
        return True

    # 字符串类型族
    str_types = {"varchar", "character varying", "char", "character", "text", "bpchar"}
    if t1 in str_types and t2 in str_types:
        return True

    # 数值类型族
    num_types = {"numeric", "decimal", "real", "double precision", "float", "float4", "float8"}
    if t1 in num_types and t2 in num_types:
        return True

    # 整数与数值类型可以部分兼容
    if (t1 in int_types and t2 in num_types) or (t1 in num_types and t2 in int_types):
        return True

    # 日期/时间类型族
    date_types = {"date", "timestamp", "timestamp without time zone", "timestamp with time zone", "timestamptz"}
    if t1 in date_types and t2 in date_types:
        return True

    return False
```

### 相关调用更新

更新 `_find_target_columns` 方法的调用：

```python
# 修改前
target_columns = self._find_target_columns(
    source_columns, target_table, combo_type
)

# 修改后
target_columns = self._find_target_columns(
    source_columns, source_table, target_table, combo_type
)
```

---

## 修复效果

### ✅ 完全符合文档

#### 1. 大小写不敏感

```python
# 示例：大写 -> 小写
源表: ['Store_ID', 'Date_Day']
目标表: {'store_id': {...}, 'date_day': {...}}

matched = generator._find_dynamic_same_name(
    ['Store_ID', 'Date_Day'], source_table, target_table
)
# 结果: ['store_id', 'date_day'] ✅
```

#### 2. 类型兼容性检查

```python
# 示例：类型不兼容
源表: store_id(INTEGER), date_day(DATE)
目标表: store_id(INTEGER), date_day(TEXT)

matched = generator._find_dynamic_same_name(
    ['store_id', 'date_day'], source_table, target_table
)
# 结果: None ❌ (date 与 text 不兼容)
```

#### 3. 列缺失检测

```python
# 示例：目标表缺少列
源表: ['store_id', 'date_day', 'product_id']
目标表: {'store_id': {...}, 'date_day': {...}}

matched = generator._find_dynamic_same_name(
    ['store_id', 'date_day', 'product_id'], source_table, target_table
)
# 结果: None ❌ (缺少 product_id)
```

### ✅ 向后兼容

- 内部数据流保持不变
- 仅改进候选生成的精确性
- 不影响其他模块

### ✅ 测试验证

- **所有 33 个单元测试通过**（从 30 个增加到 33 个）
- 新增测试覆盖：
  - `test_dynamic_same_name_case_insensitive`：验证大小写不敏感
  - `test_dynamic_same_name_type_incompatible`：验证类型兼容性检查
  - `test_dynamic_same_name_missing_column`：验证列缺失检测

---

## 使用场景

### 场景1：无主键的事实表

```
许多事实表没有定义物理主键（性能考虑）
但逻辑上存在复合主键关系
→ 动态同名匹配可以发现这些隐式关系
```

### 场景2：ETL临时表

```
ETL过程中的临时表
├─ 没有物理约束
├─ 但字段名和含义保持一致
└─ 通过同名匹配可以追踪数据血缘
```

### 场景3：跨系统数据集成

```
不同系统的表可能使用不同的命名规范
├─ 系统A: Store_ID, Product_ID
├─ 系统B: store_id, product_id
└─ 大小写不敏感匹配可以发现这些关系
```

---

## 类型兼容性规则

### 完全兼容（1.0）

- 相同类型：`integer` ↔ `integer`
- 整数类型族：`int`, `int4`, `bigint`, `int8`, `smallint`, `int2`, `serial`, `bigserial`
- 数值类型族：`numeric`, `decimal`, `real`, `double precision`, `float`, `float4`, `float8`
- 日期/时间族：`date`, `timestamp`, `timestamptz`

### 部分兼容（0.5-0.8）

- 字符串类型族：`varchar`, `char`, `text`, `bpchar`
- 整数与数值：`integer` ↔ `numeric`（0.6）

### 不兼容（0.0）

- 跨类型族：`integer` ↔ `text`, `date` ↔ `text`, `date` ↔ `integer`

---

## 相关文件

### 修改的代码文件

- `src/metaweave/core/relationships/candidate_generator.py`
  - 修改 `_find_target_columns()` 方法签名
  - 修改 `_find_dynamic_same_name()` 方法实现
  - 添加 `_is_type_compatible()` 方法
  - 添加 `_normalize_type()` 方法

### 修改的测试文件

- `tests/unit/metaweave/relationships/test_candidate_generator.py`
  - 新增 `test_dynamic_same_name_case_insensitive`
  - 新增 `test_dynamic_same_name_type_incompatible`
  - 新增 `test_dynamic_same_name_missing_column`

### 参考文档

- `docs/gen_rag/step 3.关联字段查找算法详解_v3.2.md` (line 620-679)
- `docs/gen_rag/step 3.关联关系发现完整流程示例_v3.2.md` (line 885-934)

---

## 完整示例

### 代码示例

```python
# 源表：使用大写命名
source_table = {
    "table_info": {"schema_name": "public", "table_name": "FACT_SALES"},
    "column_profiles": {
        "Store_ID": {"data_type": "integer"},
        "Date_Day": {"data_type": "date"},
        "Product_ID": {"data_type": "integer"}
    },
    "table_profile": {
        "logical_keys": {
            "candidate_primary_keys": [{
                "columns": ["Store_ID", "Date_Day", "Product_ID"],
                "confidence_score": 0.95
            }]
        }
    }
}

# 目标表：使用小写命名
target_table = {
    "table_info": {"schema_name": "public", "table_name": "fact_sales_summary"},
    "column_profiles": {
        "store_id": {"data_type": "integer"},
        "date_day": {"data_type": "date"},
        "product_id": {"data_type": "integer"}
    },
    "table_profile": {}  # 无物理约束
}

# 动态同名匹配
matched = generator._find_dynamic_same_name(
    ["Store_ID", "Date_Day", "Product_ID"],
    source_table,
    target_table
)

# 结果
matched == ["store_id", "date_day", "product_id"]  # ✅ 匹配成功
```

### 输出结果

```json
{
  "relationship_id": "rel_xxx",
  "type": "composite",
  "from_table": {"schema": "public", "table": "FACT_SALES"},
  "from_columns": ["Store_ID", "Date_Day", "Product_ID"],
  "to_table": {"schema": "public", "table": "fact_sales_summary"},
  "to_columns": ["store_id", "date_day", "product_id"],
  "discovery_method": "dynamic_same_name",
  "source_type": "candidate_logical_key",
  "composite_score": 0.88,
  "confidence_level": "high",
  "metrics": {...}
}
```

---

## 版本信息

- 修复时间：2025-11-26
- 影响模块：Step 3 关系发现（候选生成模块）
- 修复优先级：中等
- 测试覆盖：33/33 单元测试通过

---

## 后续优化

1. **性能优化**：
   - 考虑缓存类型兼容性检查结果
   - 对于大量列的表，优化映射构建

2. **扩展兼容性规则**：
   - 添加更多数据库特定类型（如 PostgreSQL 的 UUID, JSON 等）
   - 支持自定义类型兼容性规则

3. **错误诊断**：
   - 记录匹配失败的原因（列缺失 vs 类型不兼容）
   - 在日志中输出详细的匹配过程
