# 关联关系发现完整流程示例

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

```
假设 medium_confidence_threshold = 0.80

过滤结果:
├─ composite_score >= 0.80: 接受
└─ composite_score < 0.80: 拒绝

接受的关系:
└─ store_id → store_id (1.0) ✅

拒绝的关系:
├─ product_type_id → store_id (0.35)
├─ store_id → store_name (0.25)
├─ date_day → store_id (0.05)
├─ date_day → store_name (0.05)
└─ product_type_id → store_name (0.05)
```

### 5.3 最终输出

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
