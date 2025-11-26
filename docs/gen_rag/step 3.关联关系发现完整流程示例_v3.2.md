# 关联关系发现完整流程示例 v3.2

基于真实JSON文件：`fact_store_sales_day` → `dim_store`

---

## 阶段1：源表候选列选择（fact_store_sales_day）

### 1.1 提取物理约束

```
physical_constraints:
├─ primary_key: null
├─ foreign_keys: []
├─ unique_constraints: []
└─ indexes: []

结论：无物理约束
```

> 注：本示例无物理外键，因此不会生成 `type = "foreign_key"` 的直通关系；后续示例仅展示新发现的单字段/复合键关系。

### 1.2 提取逻辑主键

```
candidate_primary_keys:
└─ ["store_id", "date_day", "product_type_id"], confidence=0.8467

注意：源表单列候选不使用此信息（仅目标表使用）
```

### 1.3 主动搜索检查

检查每个字段是否有"重要约束"（单字段主键/唯一约束/索引）：

```
has_important_constraint():
├─ store_id: False（无单字段约束）
├─ date_day: False（无单字段约束）
├─ product_type_id: False（无单字段约束）
└─ amount: False（无单字段约束）

结论：所有字段不触发主动搜索
```

### 1.4 常规筛选

**排除规则**：
- semantic_role = 'audit'
- semantic_role = 'metric'
- data_type not in allowed_data_types（数据类型白名单）
- null_rate > 0.8

**允许的数据类型白名单**（来自配置：`sampling.identifier_detection.allowed_data_types`）：
```yaml
allowed_data_types:
  # 整数类型
  - integer, int, int4, bigint, int8, smallint, int2
  - serial, bigserial, smallserial
  
  # 字符串类型
  - varchar, character varying, char, character, bpchar
  
  # 日期时间类型
  - date, timestamp, timestamptz, time, timetz
  
  # UUID类型
  - uuid
  
  # 数值类型（scale=0，无小数位）
  - numeric, decimal
```

**说明**：
- 使用**白名单**而非黑名单，确保安全性和可预测性
- 排除复杂类型（JSON、ARRAY、BYTEA、GEOMETRY等）
- 排除大对象类型（TEXT、BLOB等）

**筛选结果**：

```
store_id:
├─ semantic_role: identifier ✅
├─ data_type: integer ✅（在白名单中）
├─ null_rate: 0.0 ✅
└─ 结果: ✅ 通过

date_day:
├─ semantic_role: datetime ✅
├─ data_type: date ✅（在白名单中）
├─ null_rate: 0.0 ✅
└─ 结果: ✅ 通过

product_type_id:
├─ semantic_role: identifier ✅
├─ data_type: integer ✅（在白名单中）
├─ null_rate: 0.0 ✅
└─ 结果: ✅ 通过

amount:
├─ semantic_role: metric ❌
└─ 结果: ❌ 被排除（度量值不做关联键）
```

### 1.5 源表候选列最终结果

```
源表候选列 = ["store_id", "date_day", "product_type_id"]
```

---

## 阶段2：目标表候选列选择（dim_store）

### 2.1 提取物理约束

```
physical_constraints:
├─ primary_key: null
├─ foreign_keys: []
├─ unique_constraints: []
└─ indexes: []

结论：无物理约束
```

### 2.2 提取逻辑主键

```
candidate_primary_keys:
├─ ["store_id"], confidence=1.0, uniqueness=1.0          ← 单字段
├─ ["store_id", "company_id"], confidence=0.88           ← 复合
├─ ["store_id", "region_id"], confidence=0.88            ← 复合
├─ ["company_id", "region_id"], confidence=0.88          ← 复合
└─ ["store_id", "company_id", "region_id"], confidence=0.88  ← 复合

关键：store_id 是单字段候选主键，confidence=1.0
```

### 2.3 目标列筛选规则

满足**任一条件**即可通过：
1. structure_flags.is_primary_key = true
2. structure_flags.is_unique = true
3. structure_flags.is_indexed = true
4. 在candidate_primary_keys中（单字段，confidence >= 0.8）

### 2.4 字段筛选结果

```
store_id:
├─ is_primary_key: false
├─ is_unique: true ✅
├─ is_indexed: false
├─ 在candidate_primary_keys中: true ✅ (confidence=1.0)
└─ 结果: ✅ 通过（满足条件2和4）

store_name:
├─ is_primary_key: false
├─ is_unique: true ✅
├─ is_indexed: false
├─ 在candidate_primary_keys中: false
└─ 结果: ✅ 通过（满足条件2）

company_id:
├─ is_primary_key: false
├─ is_unique: false
├─ is_indexed: false
├─ 在candidate_primary_keys中: false（只在复合键中）
└─ 结果: ❌ 被排除

region_id:
├─ is_primary_key: false
├─ is_unique: false
├─ is_indexed: false
├─ 在candidate_primary_keys中: false（只在复合键中）
└─ 结果: ❌ 被排除
```

### 2.5 目标表候选列最终结果

```
目标表候选列 = ["store_id", "store_name"]
```

---

## 阶段3：列对组合生成

### 3.1 复合键候选（本例中为空）

```
源表复合键: []（无物理约束）
目标表复合键: [
    ['store_id', 'company_id'],
    ['store_id', 'region_id']
]

复合键笛卡尔积:
├─ 源表复合键为空
└─ 外层循环0次，无复合键候选生成

结果: 0个复合键候选
```

### 3.2 单字段候选（笛卡尔积）

```
源表候选列: ["store_id", "date_day", "product_type_id"]  (3个)
目标表候选列: ["store_id", "store_name"]  (2个)

单字段笛卡尔积: 3 × 2 = 6 个候选关系:
1. fact_store_sales_day.store_id → dim_store.store_id
2. fact_store_sales_day.store_id → dim_store.store_name
3. fact_store_sales_day.date_day → dim_store.store_id
4. fact_store_sales_day.date_day → dim_store.store_name
5. fact_store_sales_day.product_type_id → dim_store.store_id
6. fact_store_sales_day.product_type_id → dim_store.store_name

总候选关系: 0(复合键) + 6(单字段) = 6个
```

---

## 阶段4：评分计算

### 4.1 评分维度和权重

```yaml
weights:
  inclusion_rate: 0.30        # 包含率（源表值在目标表中的比例）
  jaccard_index: 0.15         # Jaccard系数（值集合重叠度）
  uniqueness: 0.10            # 唯一度（目标表字段的唯一性）
  name_similarity: 0.20       # 名称相似度
  type_compatibility: 0.20    # 类型兼容性
  semantic_role_bonus: 0.05   # 语义角色奖励
```

### 4.2 候选关系1：store_id → store_id（详细计算）

#### 步骤1：数据库采样

**源表采样（全量，144行）**：
```
store_id值: [101(16次), 102(16次), 103(16次), 
            201(16次), 202(16次), 203(16次),
            301(16次), 302(16次), 303(16次)]
唯一值集合: {101, 102, 103, 201, 202, 203, 301, 302, 303}
唯一值数量: 9
```

**目标表采样（全量，9行）**：
```
store_id值: [101, 102, 103, 201, 202, 203, 301, 302, 303]
唯一值集合: {101, 102, 103, 201, 202, 203, 301, 302, 303}
唯一值数量: 9
```

#### 步骤2：计算度量值

**包含率（Inclusion Rate）**：
```python
intersection = {101, 102, 103, 201, 202, 203, 301, 302, 303}  # 9个
from_unique = {101, 102, 103, 201, 202, 203, 301, 302, 303}   # 9个

inclusion_rate = len(intersection) / len(from_unique)
inclusion_rate = 9 / 9 = 1.0 ✅
```

**Jaccard系数（Jaccard Index）**：
```python
union = {101, 102, 103, 201, 202, 203, 301, 302, 303}  # 9个

jaccard_index = len(intersection) / len(union)
jaccard_index = 9 / 9 = 1.0 ✅
```

**唯一度（Uniqueness）**：
```python
# 从JSON直接获取目标字段的uniqueness
uniqueness = 1.0 ✅（目标字段完全唯一）
```

**名称相似度（Name Similarity）**：
```python
from_name = "store_id"
to_name = "store_id"

name_similarity = 1.0 ✅（完全相同）
```

**类型兼容性（Type Compatibility）**：
```python
from_type = "integer"
to_type = "integer"

type_compatibility = 1.0 ✅（完全相同）
```

**语义角色奖励（Semantic Role Bonus）**：
```python
from_role = "identifier", confidence = 0.85
to_role = "identifier", confidence = 0.95

# 两者都是identifier且置信度 >= 0.85
semantic_role_bonus = 1.0 ✅
```

#### 步骤3：加权计算

**基础评分**：
```python
base_score = (
    0.30 × 1.0 +  # inclusion_rate
    0.15 × 1.0 +  # jaccard_index
    0.10 × 1.0 +  # uniqueness
    0.20 × 1.0 +  # name_similarity
    0.20 × 1.0    # type_compatibility
)
base_score = 0.30 + 0.15 + 0.10 + 0.20 + 0.20 = 0.95
```

**综合评分**：
```python
composite_score = base_score + (0.05 × 1.0)
composite_score = 0.95 + 0.05 = 1.0
```

**置信度分级**：
```python
if composite_score >= 0.90:
    confidence_level = "high"

结果: "high" ⭐
```

#### 最终评分报告

```json
{
  "from_column": "store_id",
  "to_column": "store_id",
  "metrics": {
    "inclusion_rate": 1.0,
    "jaccard_index": 1.0,
    "uniqueness": 1.0,
    "name_similarity": 1.0,
    "type_compatibility": 1.0,
    "semantic_role_bonus": 1.0
  },
  "scoring": {
    "base_score": 0.95,
    "semantic_bonus": 0.05,
    "composite_score": 1.0,
    "confidence_level": "high"
  },
  "decision": "accept"
}
```

---

### 4.3 其他候选关系（快速评估）

**候选关系2：store_id → store_name**
```
name_similarity: ~0.3（store_id vs store_name）
type_compatibility: 0.0（integer vs varchar）❌
inclusion_rate: 0.0（整数值无法匹配字符串值）❌

预估评分: < 0.3
结果: 拒绝
```

**候选关系3：date_day → store_id**
```
name_similarity: 0.0（完全不同）
type_compatibility: 0.0（date vs integer）❌
inclusion_rate: 0.0（日期值无法匹配整数值）❌

预估评分: < 0.1
结果: 拒绝
```

**候选关系4：date_day → store_name**
```
name_similarity: 0.0
type_compatibility: 0.0（date vs varchar）❌
inclusion_rate: 0.0 ❌

预估评分: < 0.1
结果: 拒绝
```

**候选关系5：product_type_id → store_id**
```
name_similarity: ~0.2（product_type_id vs store_id）
type_compatibility: 1.0（integer vs integer）✅
inclusion_rate: 0.0（值不匹配：{1,2,3,4} vs {101,102,103...}）❌

预估评分: < 0.4
结果: 拒绝
```

**候选关系6：product_type_id → store_name**
```
name_similarity: 0.0
type_compatibility: 0.0（integer vs varchar）❌
inclusion_rate: 0.0 ❌

预估评分: < 0.1
结果: 拒绝
```

---

## 阶段5：决策和输出

### 5.1 评分排序

```
排序后的候选关系（按composite_score降序）:
1. store_id → store_id: 1.0 (high) ✅
2. product_type_id → store_id: ~0.35 (low) ❌
3. store_id → store_name: ~0.25 (low) ❌
4. date_day → store_id: ~0.05 (low) ❌
5. date_day → store_name: ~0.05 (low) ❌
6. product_type_id → store_name: ~0.05 (low) ❌
```

### 5.2 阈值过滤

**配置**：
```yaml
decision:
  accept_threshold: 0.80  # 接受/拒绝阈值（低于此值不写入结果JSON）
  high_confidence_threshold: 0.90     # 高置信度分级线（仅用于报告展示）
  medium_confidence_threshold: 0.80   # 中等置信度分级线（仅用于报告展示）
```

**过滤规则**：
```
composite_score >= accept_threshold: 接受 → 写入结果JSON
composite_score < accept_threshold:  拒绝 → 不写入结果
```

**过滤结果**：
```
├─ store_id → store_id (1.0 >= 0.80) ✅ 接受
└─ 其他5个关系 (< 0.80) ❌ 拒绝
```

**接受的关系**：
```
└─ store_id → store_id (1.0) ✅
```

**拒绝的关系**（不写入输出JSON）：
```
├─ product_type_id → store_id (0.35)
├─ store_id → store_name (0.25)
├─ date_day → store_id (0.05)
├─ date_day → store_name (0.05)
└─ product_type_id → store_name (0.05)
```

**注意**：
- `accept_threshold`：决定是否接受关系（影响JSON输出）
- `high_confidence_threshold`、`medium_confidence_threshold`：仅用于已接受关系的置信度分级（报告展示）
- 本例中所有被拒绝的关系都不会出现在输出JSON的 `relationships` 数组中

### 5.3 最终输出

**说明**：
本示例为了聚焦核心流程，展示的是**最简化的单字段关系场景**。实际输出会包含更多字段和节点。

**本示例省略的字段**：
- `suppressed_single_relations`：被抑制的单字段关系列表（仅当复合键成功时出现）
- `source_type`：关系来源类型（如 `candidate_logical_key`、`primary_key` 等）
- `source_constraint`：约束类型（如 `single_field_index`，主动搜索时）
- `metadata_source`：元数据来源标记
- `analysis_timestamp`：分析时间戳

**完整的输出格式请参考**：《关联字段查找算法详解 v3.2》第6.1节"JSON详细报告"。

**下面是本例的简化输出**：

> 注意：为便于阅读，示例中的 `relationship_id` 使用顺序编号（如 `rel_001`）。实际实现中，ID 按“确定性哈希规则”生成（如 `rel_7e3a9c12ab34`），同一关系在并发/增量运行下也保持稳定。

```json
{
  "relationships": [
    {
      "relationship_id": "rel_001",
      "type": "single_column",
      "from_table": "public.fact_store_sales_day",
      "from_column": "store_id",
      "to_table": "public.dim_store",
      "to_column": "store_id",
      "composite_score": 1.0,
      "confidence_level": "high",
      "discovery_method": "standard_matching",
      "metrics": {
        "inclusion_rate": 1.0,
        "jaccard_index": 1.0,
        "uniqueness": 1.0,
        "name_similarity": 1.0,
        "type_compatibility": 1.0,
        "semantic_role_bonus": 1.0
      },
      "semantic_context": {
        "from_role": "identifier",
        "from_confidence": 0.85,
        "to_role": "identifier",
        "to_confidence": 0.95
      }
    }
  ],
  
  "statistics": {
    "total_candidates_generated": 6,
    "candidates_evaluated": 6,
    "relationships_accepted": 1,
    "relationships_rejected": 5
  }
}
```

### 5.4 完整输出示例（包含v3.2核心特性）

**说明**：
以下展示包含所有v3.2核心字段的完整输出格式，即使本例中某些特性未被触发（如复合键抑制）。

```json
{
  "metadata_source": "json_files",
  "json_metadata_version": "2.0",
  "json_files_loaded": 2,
  "database_queries_executed": 6,
  "analysis_timestamp": "2025-11-25T10:30:00Z",
  
  "statistics": {
    "total_relationships_found": 1,
    "composite_key_relationships": 0,
    "single_column_relationships": 1,
    "total_suppressed_single_relations": 0,
    "active_search_discoveries": 0,
    "dynamic_composite_discoveries": 0
  },
  
  
  
  "relationships": [
    {
      "relationship_id": "rel_001",
      "type": "single_column",
      "from_table": {
        "schema": "public",
        "table": "fact_store_sales_day"
      },
      "from_column": "store_id",
      "to_table": {
        "schema": "public",
        "table": "dim_store"
      },
      "to_column": "store_id",
      "source_type": null,
      "discovery_method": "standard_matching",
      "source_constraint": null,
      "composite_score": 1.0,
      "confidence_level": "high",
      "metrics": {
        "inclusion_rate": 1.0,
        "jaccard_index": 1.0,
        "uniqueness": 1.0,
        "name_similarity": 1.0,
        "type_compatibility": 1.0,
        "semantic_role_bonus": 1.0
      },
      "semantic_roles": {
        "from_column": "identifier",
        "to_column": "identifier",
        "from_confidence": 0.85,
        "to_confidence": 0.95
      }
    }
  ]
}
```

**字段说明**：

**顶层元数据**：
- `metadata_source`: "json_files" - 优先使用JSON元数据
- `json_metadata_version`: "2.0" - JSON格式版本
- `json_files_loaded`: 2 - 加载的JSON文件数
- `database_queries_executed`: 6 - 执行的数据库查询数（仅用于采样）
- `analysis_timestamp`: 分析时间戳

**statistics节点**：
- `total_relationships_found`: 最终输出的关系总数
- `composite_key_relationships`: 复合键关系数量
- `single_column_relationships`: 单字段关系数量
- `total_suppressed_single_relations`: 被复合键抑制的单字段关系数（本例为0）
- `active_search_discoveries`: 主动搜索发现的关系数（本例为0）
- `dynamic_composite_discoveries`: 动态同名复合键发现数（本例为0）

（已删除）

**relationships中的关键字段**：
- `source_type`: 关系来源（`candidate_logical_key`、`primary_key`等，本例为null）
- `discovery_method`: 发现方法（`standard_matching`、`active_search`、`dynamic_same_name`等）
- `source_constraint`: 源字段约束类型（`single_field_index`等，本例为null）
- `semantic_roles`: 详细的语义角色信息

**注意**：
- 本例是最简单的场景（无复合键、无抑制），所以 `suppressed_single_relations` 不出现
- 更复杂的场景（含复合键抑制）请参考下一节

---

### 5.5 复合键抑制示例（v3.2核心特性）

**场景说明**：
假设 fact_store_sales_day 有物理复合主键 `(store_id, date_day, product_type_id)`，并且发现了与 fact_store_sales_month 的复合键关系。

**关键点**：
- 复合键关系成功后，检查其包含的字段是否有独立约束
- 有独立约束的字段（如单字段索引）：单字段关系保留
- 无独立约束的字段：单字段关系被抑制

```json
{
  "metadata_source": "json_files",
  "json_metadata_version": "2.0",
  "json_files_loaded": 3,
  "database_queries_executed": 15,
  "analysis_timestamp": "2025-11-25T10:35:00Z",
  
  "statistics": {
    "total_relationships_found": 2,
    "composite_key_relationships": 1,
    "single_column_relationships": 1,
    "total_suppressed_single_relations": 2,
    "active_search_discoveries": 1,
    "dynamic_composite_discoveries": 0
  },
  
  
  
  "relationships": [
    {
      "relationship_id": "rel_001",
      "type": "composite_key",
      "from_table": {
        "schema": "public",
        "table": "fact_store_sales_day"
      },
      "source_columns": ["store_id", "date_day", "product_type_id"],
      "to_table": {
        "schema": "public",
        "table": "fact_store_sales_month"
      },
      "target_columns": ["store_id", "date_month", "product_type_id"],
      "source_type": "primary_key",
      "discovery_method": "physical_constraint_matching",
      "composite_score": 0.87,
      "confidence_level": "high",
      "metrics": {
        "inclusion_rate": 0.95,
        "jaccard_index": 0.88,
        "name_similarity": 0.90,
        "type_compatibility": 0.95,
        "uniqueness": 1.0,
        "semantic_role_bonus": 0.80
      },
      "suppressed_single_relations": [
        {
          "from_column": "date_day",
          "to_column": "date_month",
          "original_score": 0.76,
          "suppression_reason": "在复合键中，无独立约束",
          "could_have_been_accepted": false
        },
        {
          "from_column": "product_type_id",
          "to_column": "product_type_id",
          "original_score": 0.82,
          "suppression_reason": "在复合键中，无独立约束",
          "could_have_been_accepted": true
        }
      ],
      "note": "store_id有独立索引，其单字段关系不被抑制"
    },
    {
      "relationship_id": "rel_002",
      "type": "single_column",
      "from_table": {
        "schema": "public",
        "table": "fact_store_sales_day"
      },
      "from_column": "store_id",
      "to_table": {
        "schema": "public",
        "table": "dim_store"
      },
      "to_column": "store_id",
      "source_type": null,
      "discovery_method": "active_search",
      "source_constraint": "single_field_index",
      "composite_score": 0.95,
      "confidence_level": "high",
      "metrics": {
        "inclusion_rate": 1.0,
        "jaccard_index": 1.0,
        "uniqueness": 1.0,
        "name_similarity": 1.0,
        "type_compatibility": 1.0,
        "semantic_role_bonus": 1.0
      },
      "semantic_roles": {
        "from_column": "identifier",
        "to_column": "identifier",
        "from_confidence": 0.85,
        "to_confidence": 0.95
      },
      "note": "源字段有独立索引，主动搜索发现，不被复合键抑制"
    }
  ]
}
```

**抑制逻辑详解**：

1. **复合键关系成功**：
   ```
   (store_id, date_day, product_type_id) → (store_id, date_month, product_type_id)
   ```

2. **检查每个字段的独立约束**：
   ```
   store_id:
   ├─ has_important_constraint() = True
   ├─ 原因: 有单字段索引 INDEX idx_store (store_id)
   └─ 决策: 单字段关系 store_id → dim_store.store_id 保留 ✅
   
   date_day:
   ├─ has_important_constraint() = False
   ├─ 原因: 只在复合主键中，无单字段约束
   └─ 决策: 单字段关系被抑制 ❌
   
   product_type_id:
   ├─ has_important_constraint() = False
   ├─ 原因: 只在复合主键中，无单字段约束
   └─ 决策: 单字段关系被抑制 ❌
   ```

3. **抑制信息记录**：
   - `date_day` 和 `product_type_id` 的单字段关系被记录在复合键的 `suppressed_single_relations` 中
   - `could_have_been_accepted` 字段说明：如果不被抑制，该关系是否会被接受
     - `date_day`: false - 评分0.76 < 0.80，即使不抑制也会被拒绝
     - `product_type_id`: true - 评分0.82 >= 0.80，本可以被接受

4. **最终输出**：
   - ✅ 复合键关系：1个
   - ✅ 单字段关系：1个（store_id → dim_store.store_id，有独立索引）
   - ❌ 被抑制关系：2个（记录在 suppressed_single_relations 中）

**为什么要抑制？**

避免语义错误：
- 复合键 `(store_id, date_day, product_type_id)` 表示"某店铺在某天销售某商品类型"
- 如果单独输出 `date_day → date_month`，语义变成"某天对应某月"，丢失了店铺和商品信息
- 这是**语义不完整**的关系，应该被抑制

**何时不抑制？**

字段有独立约束时：
- `store_id` 有单字段索引，说明它独立具有重要性
- 它既可以作为复合键的一部分，也可以独立建立关系（如 → dim_store）
- 因此 `store_id → dim_store.store_id` **不被抑制**

---

### 5.6 动态复合键匹配示例（v3.2核心特性）

**场景说明**：
假设有两个事实表需要进行关联分析：
- 源表：`fact_sales_detail`（销售明细，有候选逻辑主键）
- 目标表：`fact_sales_summary`（销售汇总，无物理约束但有同名字段）

**关键点**：
- 源表有候选逻辑主键：`(order_id, product_id)`
- 目标表**没有任何物理约束**（无主键、无唯一约束、无索引）
- 目标表有同名字段：`order_id` 和 `product_id`
- 通过**动态同名匹配**发现复合键关系

```json
{
  "metadata_source": "json_files",
  "json_metadata_version": "2.0",
  "json_files_loaded": 2,
  "database_queries_executed": 8,
  "analysis_timestamp": "2025-11-25T11:00:00Z",
  
  "statistics": {
    "total_relationships_found": 1,
    "composite_key_relationships": 1,
    "single_column_relationships": 0,
    "total_suppressed_single_relations": 2,
    "active_search_discoveries": 0,
    "dynamic_composite_discoveries": 1
  },
  
  
  
  "relationships": [
    {
      "relationship_id": "rel_001",
      "type": "composite_key",
      "from_table": {
        "schema": "public",
        "table": "fact_sales_detail"
      },
      "source_columns": ["order_id", "product_id"],
      "to_table": {
        "schema": "public",
        "table": "fact_sales_summary"
      },
      "target_columns": ["order_id", "product_id"],
      "source_type": "candidate_logical_key",
      "discovery_method": "dynamic_same_name",
      "composite_score": 0.88,
      "confidence_level": "high",
      "metrics": {
        "inclusion_rate": 0.92,
        "jaccard_index": 0.85,
        "name_similarity": 1.0,
        "type_compatibility": 1.0,
        "uniqueness": 1.0,
        "semantic_role_bonus": 0.85
      },
      "suppressed_single_relations": [
        {
          "from_column": "order_id",
          "to_column": "order_id",
          "original_score": 0.79,
          "suppression_reason": "在复合键中，无独立约束",
          "could_have_been_accepted": false
        },
        {
          "from_column": "product_id",
          "to_column": "product_id",
          "original_score": 0.81,
          "suppression_reason": "在复合键中，无独立约束",
          "could_have_been_accepted": true
        }
      ],
      "note": "目标表无物理约束，通过动态同名匹配发现"
    }
  ]
}
```

**动态匹配逻辑详解**：

1. **源表复合键来源**：
   ```
   fact_sales_detail.candidate_primary_keys:
   └─ ["order_id", "product_id"], confidence=0.92, uniqueness=1.0
   
   来源类型: candidate_logical_key（候选逻辑主键）
   ```

2. **目标表情况**：
   ```
   fact_sales_summary:
   ├─ physical_constraints: 全空（无任何物理约束）
   ├─ candidate_primary_keys: []（无候选逻辑主键）
   └─ column_profiles: 包含 order_id, product_id 等字段
   
   问题: 按常规逻辑，目标表没有复合键候选！
   ```

3. **动态同名匹配触发**：
   ```
   算法检查:
   ├─ 源表复合键字段: ["order_id", "product_id"]
   ├─ 目标表是否有同名字段?
   │  ├─ order_id: ✅ 存在
   │  └─ product_id: ✅ 存在
   ├─ 字段名是否完全相同?
   │  └─ ✅ 忽略大小写后完全匹配
   └─ 类型是否兼容?
      ├─ order_id: integer ↔ integer ✅
      └─ product_id: integer ↔ integer ✅
   
   结果: 触发动态同名匹配 🎯
   ```

4. **关系发现和评分**：
   ```
   复合键关系:
   ├─ (order_id, product_id) → (order_id, product_id)
   ├─ composite_score: 0.88
   ├─ discovery_method: "dynamic_same_name"
   └─ 决策: 接受 ✅
   ```

5. **单字段关系抑制**：
   ```
   order_id和product_id都无独立约束
   └─ 单字段关系被抑制 ❌
      └─ 记录在 suppressed_single_relations 中
   ```

**为什么需要动态同名匹配？**

**场景1：无主键的事实表**
```
许多事实表没有定义物理主键（性能考虑）
但逻辑上存在复合主键关系
→ 动态同名匹配可以发现这些隐式关系
```

**场景2：ETL临时表**
```
ETL过程中的临时表
├─ 没有物理约束
├─ 但字段名和含义保持一致
└─ 通过同名匹配可以追踪数据血缘
```

**场景3：跨系统数据集成**
```
不同系统的表
├─ 可能没有正式的外键约束
├─ 但遵循相同的命名规范
└─ 同名字段组合暗示关联关系
```

**与物理约束匹配的区别**：

| 特性 | 物理约束匹配 | 动态同名匹配 |
|------|------------|------------|
| **目标表要求** | 必须有物理复合约束 | 只需有同名字段 |
| **匹配条件** | 名称相似度 >= 0.7 | 名称完全相同 |
| **类型要求** | 兼容度 >= 0.8 | 兼容度 >= 0.8 |
| **discovery_method** | physical_constraint_matching | dynamic_same_name |
| **适用场景** | 有完整DDL的生产表 | 无约束的事实表/临时表 |

**动态匹配的优势**：

✅ **发现隐式关系**：
- 许多表逻辑上有复合主键，但未定义物理约束
- 动态匹配可以发现这些隐式关系

✅ **字段名一致性强**：
- 要求字段名完全相同（比物理约束匹配更严格）
- 减少误匹配的可能性

✅ **扩展覆盖范围**：
- 不依赖物理约束
- 可以分析更多类型的表

**注意事项**：

⚠️ **字段顺序无关**：
```
源表: ["order_id", "product_id"]
目标表: ["product_id", "order_id"]  ← 顺序不同
结果: 仍然可以匹配 ✅
```

⚠️ **字段名必须完全相同**：
```
源表: ["order_id", "product_id"]
目标表: ["order_no", "product_id"]  ← order_id vs order_no
结果: 不匹配 ❌（字段名不同）
```

⚠️ **不检查名称相似度**：
- 物理约束匹配：允许名称相似（>= 0.7）
- 动态同名匹配：必须完全相同
- 原因：避免误匹配无约束的字段

---

## 完整流程总结

```
fact_store_sales_day (源表)          dim_store (目标表)
4个字段                              4个字段
│                                    │
阶段1: 源表候选列选择                  阶段2: 目标表候选列选择
├─ 提取约束                           ├─ 提取约束
├─ 主动搜索检查                       ├─ 提取逻辑主键
├─ 常规筛选                           ├─ 复合键筛选
└─ 结果:                              └─ 单字段筛选
   ├─ 复合键: []（0个）                  └─ 结果:
   └─ 单字段: [store_id,                    ├─ 复合键: 2个
       date_day, product_type_id]            └─ 单字段: [store_id, store_name]
        │                                    │
        └────────────────┬───────────────────┘
                         │
                  阶段3: 列对组合生成
                  │
                  ├─ 复合键笛卡尔积
                  │  └─ 0(源) × 2(目标) = 0个
                  │     └─ 外层循环0次，跳过
                  │
                  └─ 单字段笛卡尔积
                     └─ 3(源) × 2(目标) = 6个
                  │
                  └─ 总候选: 0 + 6 = 6个
                         │
                  阶段4: 评分计算
                  ├─ 数据库采样
                  ├─ 计算6个维度
                  └─ 加权求和
                         │
                  阶段5: 决策输出
                  ├─ 评分排序
                  ├─ 阈值过滤
                  └─ 输出JSON
                         │
                  最终结果: 1个关系
                  store_id → store_id (1.0)
```

---

## 关键洞察

### 为什么只有 store_id → store_id 得分高？

| 因素 | store_id → store_id | 其他关系 |
|------|-------------------|----------|
| **名称匹配** | 完全相同 | 不同 |
| **类型匹配** | integer ↔ integer | 不匹配或不相关 |
| **值匹配** | 完全相同的9个值 | 值集合不相交 |
| **语义角色** | identifier ↔ identifier | 角色不匹配 |
| **唯一性** | 目标字段完全唯一 | store_name唯一但其他不匹配 |

### 典型的外键关系特征

```
事实表 → 维度表
├─ 多对一关系（144行 → 9行）
├─ 完美的引用完整性（inclusion_rate = 1.0）
├─ 值集合完全相同（jaccard_index = 1.0）
├─ 字段名和类型完全匹配
└─ 语义角色都是高置信度的identifier

这是一个教科书级别的完美外键关系！
```

---

## 附录：数据概览

### fact_store_sales_day

```
总行数: 144
粒度: (store_id, date_day, product_type_id)

字段分布:
├─ store_id: 9个唯一值（101-303）
├─ date_day: 4个唯一值（4天）
├─ product_type_id: 4个唯一值（4种商品类型）
└─ amount: 90个唯一值（度量字段）

逻辑: 9店铺 × 4天 × 4商品类型 = 144行
```

### dim_store

```
总行数: 9
主键: store_id（候选逻辑主键，uniqueness=1.0）

字段分布:
├─ store_id: 9个唯一值（101-303）
├─ store_name: 9个唯一值（店铺名称）
├─ company_id: 3个唯一值（3家公司）
└─ region_id: 8个唯一值（8个地区）

逻辑: 3家公司，每家3个店铺
```
