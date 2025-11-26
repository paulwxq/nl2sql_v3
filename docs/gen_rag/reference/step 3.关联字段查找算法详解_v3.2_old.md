# 关联字段查找算法详解 v3.2

## 概述

DB2Graph项目中的关联字段查找算法是一个多阶段、多维度的智能关系发现系统。算法**优先从JSON元数据文件中获取表和字段的统计信息**，大幅减少数据库访问，提升分析效率。算法结合了JSON元数据分析、确定性规则匹配以及可选的嵌入/LLM语义增强，能够从预先生成的表画像和实际数据库中自动发现表之间的潜在关联关系。

### 核心特性

1. **JSON元数据优先**: 从JSON文件读取表结构、字段画像、统计信息、样例数据
2. **主动发现机制**: 源字段有重要约束时，主动在目标表中查找同名字段
3. **动态复合键匹配**: 支持逻辑主键和同名字段组合的动态发现
4. **智能抑制规则**: 复合键关系成功后，默认抑制包含在其中的单字段关系（仅限同一对表）
5. **按需数据库访问**: 只在评估阶段访问数据库，获取样本进行精确计算

## 1. JSON元数据格式说明

### 1.1 整体结构

```json
{
  "metadata_version": "2.0",
  "generated_at": "2025-11-23T15:42:26.967418Z",
  
  "table_info": {
    "schema_name": "public",
    "table_name": "dim_company",
    "table_type": "table",
    "comment": "公司维表",
    "total_rows": 3,
    "total_columns": 2
  },
  
  "column_profiles": {
    "company_id": {
      "column_name": "company_id",
      "data_type": "integer",
      "statistics": {...},
      "semantic_analysis": {...},
      "structure_flags": {...}
    }
  },
  
  "table_profile": {
    "table_category": "dim",
    "physical_constraints": {...},
    "logical_keys": {...},
    "column_statistics": {...}
  },
  
  "sample_records": {...}
}
```

### 1.2 物理约束 (physical_constraints)

**位置**: `table_profile.physical_constraints`

**结构**:
```json
{
  "physical_constraints": {
    "primary_key": {
      "constraint_name": "pk_company",
      "columns": ["company_id"]
    },
    "foreign_keys": [
      {
        "constraint_name": "fk_region",
        "source_columns": ["region_id"],
        "target_schema": "public",
        "target_table": "dim_region",
        "target_columns": ["region_id"]
      }
    ],
    "unique_constraints": [
      {
        "constraint_name": "uk_name",
        "columns": ["company_name"]
      }
    ],
    "indexes": [
      {
        "index_name": "idx_region",
        "columns": ["region_id"],
        "is_unique": false,
        "index_type": "btree"
      },
      {
        "index_name": "idx_composite",
        "columns": ["store_id", "date_day"],
        "is_unique": true,
        "index_type": "btree"
      }
    ]
  }
}
```

**说明**:
- `primary_key`: 物理主键约束，可能为null（表示没有物理主键）
- `foreign_keys`: 物理外键列表，注意使用`source_columns`和`target_columns`
- `unique_constraints`: 唯一约束列表
- `indexes`: 索引列表，包括单列和复合索引

### 1.3 逻辑主键 (logical_keys)

**位置**: `table_profile.logical_keys`

**结构**:
```json
{
  "logical_keys": {
    "candidate_primary_keys": [
      {
        "columns": ["company_id"],
        "confidence_score": 1.0,
        "uniqueness": 1.0,
        "null_rate": 0.0
      },
      {
        "columns": ["store_id", "date_day", "product_id"],
        "confidence_score": 0.85,
        "uniqueness": 1.0,
        "null_rate": 0.0
      }
    ]
  }
}
```

**说明**:
- `candidate_primary_keys`: 推断的候选主键列表
- 可以是单列或多列
- `confidence_score`: 置信度（0-1），算法使用>=0.8的候选

### 1.4 字段画像 (column_profiles)

**关键字段**:
- `structure_flags`: 物理标记
  - `is_primary_key`: 是否是物理主键的一部分
  - `is_unique`: 是否有唯一性（主键或唯一约束）
  - `is_indexed`: 是否有索引
- `semantic_analysis`: 语义角色
  - `semantic_role`: 角色类型（identifier/datetime/enum/metric/audit/attribute）
  - `semantic_confidence`: 置信度（0-1）
- `statistics`: 统计信息
  - `uniqueness`: 唯一度（0-1）
  - `null_rate`: 空值率（0-1）
  - `value_distribution`: 值分布

## 2. 主键、外键和索引的处理

### 2.1 现有外键的处理

**JSON来源**: `table_profile.physical_constraints.foreign_keys`

**处理策略**:
- **直通转换**: 已存在的外键约束被直接转换为高置信度关系（confidence=1.0）
- **排除机制**: 在候选生成阶段，已存在的外键关系会被排除，避免重复分析
- **关系类型**: 外键关系被标记为`foreign_key`类型，具有最高优先级

**示例**:
```json
{
  "foreign_keys": [
    {
      "constraint_name": "fk_store_region",
      "source_columns": ["region_id"],
      "target_schema": "public",
      "target_table": "dim_region",
      "target_columns": ["region_id"]
    }
  ]
}
```

### 2.2 主键和唯一键的处理

**物理约束来源**:
- `table_profile.physical_constraints.primary_key`
- `table_profile.physical_constraints.unique_constraints`

**逻辑主键来源**:
- `table_profile.logical_keys.candidate_primary_keys`

**目标列筛选逻辑**: 在单列关系候选生成中，目标列（to_column）必须满足以下条件之一:
- `structure_flags.is_primary_key = true` （物理主键）
- `structure_flags.is_unique = true` （唯一约束）
- `structure_flags.is_indexed = true` （有索引）
- 在`candidate_primary_keys`的任一候选组合中（confidence_score >= 0.8）

### 2.3 索引的处理

**索引来源**: `table_profile.physical_constraints.indexes`

**复合索引识别**:
```python
# 从JSON中提取复合索引(列数>=2)
composite_indexes = [
    idx for idx in physical_constraints['indexes']
    if len(idx['columns']) >= 2
]
```

**索引应用**:
- **单列索引**: 标记在`column_profiles[col].structure_flags.is_indexed`
- **复合索引**: 作为复合键候选来源之一
- **目标列优先级**: 拥有索引的列在候选筛选时自动合格
- **查询优化**: 评估阶段的数据库查询可利用索引提升性能

### 2.4 语义角色的使用

**来源**: `column_profiles[col].semantic_analysis.semantic_role`

**角色类型及处理策略**:

**在候选筛选阶段**:
- `audit`: 审计字段，**排除**，不参与关联分析
- `metric`: 度量值，**排除**，不参与关联分析
- `identifier`: 标识符，**通过筛选**，适合作为关联键
- `datetime`: 时间字段，**通过筛选**
- `enum`: 枚举字段，**通过筛选**
- `attribute`: 属性字段，**通过筛选**

**在评分阶段**:
不同的semantic_role匹配会获得不同的奖励分（详见4.6节）:
- identifier ↔ identifier（高置信度）: +1.0
- 相同角色（中等置信度）: +0.8
- 兼容角色: +0.5

**推断可靠性**:
- `semantic_confidence >= 0.8`: 高可信度，直接采纳
- `semantic_confidence < 0.8`: 需结合其他信息辅助判断

## 3. 算法执行的阶段和步骤

### 3.1 第一阶段: JSON元数据读取和解析

```
步骤1: 加载表的JSON元数据文件
├── 扫描指定目录，加载所有表的JSON文件（schema.table.json）
├── 解析JSON结构:
│   ├── table_info: 表基本信息
│   ├── column_profiles: 字段画像、统计信息、语义角色
│   ├── table_profile: 表类型、物理约束、逻辑主键
│   └── sample_records: 样例数据
├── 验证JSON完整性:
│   ├── 检查metadata_version兼容性（当前支持2.0）
│   ├── 验证必需字段存在性
│   └── 统计信息有效性检查
└── 构建内存索引:
    ├── schema.table → JSON对象映射
    ├── 物理约束快速查询索引
    └── 语义角色分类索引

步骤2: 提取约束和关键列信息
├── 物理外键提取:
│   ├── 来源: table_profile.physical_constraints.foreign_keys
│   ├── 构建外键映射: (from_table, source_columns) → (target_table, target_columns)
│   └── 标记为已知关系，后续候选生成时排除
├── 主键和唯一键提取:
│   ├── 物理主键: physical_constraints.primary_key
│   ├── 唯一约束: physical_constraints.unique_constraints
│   └── 候选逻辑主键: logical_keys.candidate_primary_keys
├── 索引提取:
│   ├── 单列索引: 标记列的is_indexed标志
│   └── 复合索引（>=2列）: 作为复合键候选来源
└── 语义角色统计:
    ├── 按角色分类列: identifier/datetime/enum/attribute等
    └── 构建高置信度标识符列表（confidence >= 0.85）
```

**性能特点**:
- ⏱️ 时间: 秒级
- 🔌 数据库访问: **0次**

### 3.2 第二阶段: 候选关系生成（优先复合键）

```
步骤3: 复合键候选生成（优先处理）
├── 源表复合键来源收集:
│   ├── 联合物理主键（primary_key.columns数量>=2）
│   ├── 联合唯一约束（unique_constraints，列数>=2）
│   ├── 联合物理外键（foreign_keys，source_columns数量>=2）
│   └── 复合索引（indexes，列数>=2）
├── 目标表复合键来源收集（扩展）:
│   ├── 物理复合约束（同源表）
│   ├── 候选逻辑主键（candidate_primary_keys，列数>=2，confidence>=0.8）
│   └── 动态发现: 与源表同名的字段组合
│       ├── 字段名集合完全相同（忽略大小写和顺序）
│       └── 每个对应字段类型必须兼容
├── 列数和来源约束:
│   ├── 列数必须完全相同
│   ├── 列数范围: [2, max_columns]（默认max_columns=3）
│   └── 来源类型一致性检查（可配置）
├── 逐列对验证:
│   ├── 物理约束匹配: 名称相似度 >= 0.7, 类型兼容度 >= 0.8
│   └── 动态同名匹配: 名称完全相同（忽略大小写）, 类型兼容度 >= 0.8
└── 生成复合键候选

步骤4: 单列候选生成
├── 源列（from_column）筛选:
│   ├── [排除] semantic_role = 'audit'（审计字段）
│   ├── [排除] semantic_role = 'metric'（度量值）
│   ├── [排除] data_type in ['JSON', 'JSONB', 'ARRAY']
│   ├── [排除] statistics.null_rate > 0.8（高空值率）
│   └── 其他semantic_role通过筛选（identifier/datetime/enum/attribute等）
├── 目标列（to_column）常规筛选:
│   ├── structure_flags.is_primary_key = true （物理主键）
│   ├── structure_flags.is_unique = true （唯一约束）
│   ├── structure_flags.is_indexed = true （有索引）
│   └── 在candidate_primary_keys中（单列或多列，confidence >= 0.8）
├── 主动同名字段发现（新增，v3.2核心特性）:
│   ├── 触发条件: 源字段有重要约束
│   │   └── 单字段物理主键/单字段唯一约束/单字段索引
│   ├── 执行逻辑:
│   │   └── 如果目标候选列表中没有同名字段
│   │       └── 在目标表JSON的column_profiles中查找
│   │           └── 如果存在，加入目标候选列表
│   └── 标记: discovery_method='active_search'
├── 排除已知外键关系
└── 生成单列候选
```

**性能特点**:
- ⏱️ 时间: 秒级
- 🔌 数据库访问: **0次**

**重要约束的定义**:
```python
def has_important_constraint(column_name, table_json):
    """
    判断字段是否有重要的单字段约束
    
    用途：决定是否对该字段触发"主动搜索同名字段"
    
    检查范围（只检查单字段约束）：
    1. 单字段物理主键: PRIMARY KEY (column_name)
    2. 单字段唯一约束: UNIQUE (column_name)
    3. 单字段索引: INDEX idx_name (column_name)
    
    不检查的情况：
    - 复合主键: PRIMARY KEY (col1, col2)  ← 在步骤3"复合键候选生成"中处理
    - 复合唯一约束: UNIQUE (col1, col2)  ← 在步骤3"复合键候选生成"中处理
    - 复合索引: INDEX idx (col1, col2)   ← 在步骤3"复合键候选生成"中处理
    
    特殊情况：
    如果字段既有单独约束，又在复合约束中，仍返回True
    例如：
      PRIMARY KEY (store_id, date_day)  -- 复合主键
      UNIQUE (store_id)                 -- 单独唯一约束
    
    此时 has_important_constraint('store_id') = True
    因为检测到了单独的 UNIQUE (store_id)
    
    注意: 检查是否有独立的单字段约束
    说明: 如果字段同时在复合约束中，不影响判断结果
          只要存在单字段约束（PRIMARY KEY (col)、UNIQUE (col)、INDEX (col)），就返回True
    """
    physical_constraints = table_json['table_profile']['physical_constraints']
    
    # 检查单字段主键
    pk = physical_constraints.get('primary_key')
    if pk and pk['columns'] == [column_name]:
        return True, 'single_field_primary_key'
    
    # 检查单字段唯一约束
    for uk in physical_constraints.get('unique_constraints', []):
        if uk['columns'] == [column_name]:
            return True, 'single_field_unique_constraint'
    
    # 检查单字段索引
    for idx in physical_constraints.get('indexes', []):
        if idx['columns'] == [column_name]:
            return True, 'single_field_index'
    
    return False, None
```

**示例场景**:

```sql
-- 示例1: 只有单字段约束
CREATE TABLE dim_store (
    store_id INTEGER PRIMARY KEY  -- 单字段主键
);
```
```python
# has_important_constraint('store_id') = True
# 原因: 检测到单字段主键
# 触发: 主动搜索同名字段
```

```sql
-- 示例2: 只有复合主键
CREATE TABLE fact_sales (
    store_id INTEGER,
    date_day DATE,
    PRIMARY KEY (store_id, date_day)  -- 复合主键
);
```
```python
# has_important_constraint('store_id') = False
# 原因: store_id 只在复合主键中，没有独立约束
# 不触发: 不会主动搜索，使用常规筛选
```

```sql
-- 示例3: 既有复合主键，又有单独约束
CREATE TABLE fact_sales (
    store_id INTEGER,
    date_day DATE,
    PRIMARY KEY (store_id, date_day),  -- 复合主键
    UNIQUE (store_id)                  -- 单独唯一约束 ✓
);
```
```python
# has_important_constraint('store_id') = True
# 原因: 检测到单独的 UNIQUE (store_id)
# 触发: 主动搜索同名字段
# 说明: 虽然store_id也在复合主键中，但单独的UNIQUE约束使其满足条件
```

**动态复合键发现**:
```python
def find_dynamic_composite(source_columns, target_table_json, source_table_json):
    """
    在目标表中查找与源表同名的字段组合
    
    Args:
        source_columns: 源表复合键字段列表 ['col1', 'col2', 'col3']
        target_table_json: 目标表的JSON元数据
        source_table_json: 源表的JSON元数据
    
    Returns:
        动态复合键候选，或None
    
    逻辑：
    1. 字段名集合必须完全相同（忽略大小写和顺序）
    2. 每个对应字段的类型必须兼容
    """
    target_column_profiles = target_table_json['column_profiles']
    source_column_profiles = source_table_json['column_profiles']
    
    # 1. 字段名集合检查（忽略大小写）
    source_set = {col.lower() for col in source_columns}
    target_set = {col.lower() for col in target_column_profiles.keys()}
    
    # 检查字段集合是否完全相同
    if source_set != target_set:
        return None  # 字段集合不相等，失败
    
    # 2. 逐列类型兼容性检查
    target_columns = []
    for source_col_name in source_columns:
        # 在目标表中查找同名字段（忽略大小写）
        target_col_name = None
        for tcol in target_column_profiles.keys():
            if tcol.lower() == source_col_name.lower():
                target_col_name = tcol
                break
        
        if target_col_name is None:
            return None  # 字段不存在
        
        # 检查类型兼容性
        source_type = source_column_profiles[source_col_name]['data_type']
        target_type = target_column_profiles[target_col_name]['data_type']
        
        if not is_type_compatible(source_type, target_type):
            return None  # 类型不兼容，失败
        
        target_columns.append(target_col_name)
    
    # 所有条件满足，返回候选
    return {
        'columns': target_columns,
        'source_type': 'dynamic_same_name',
        'match_type': 'exact_name_and_type_compatible'
    }
```

**示例说明**:

```python
# 示例1: 字段顺序不同，但匹配成功
源表复合键: ['store_id', 'date_day', 'product_id']
目标表字段: {'product_id': {...}, 'store_id': {...}, 'date_day': {...}}

# 检查：
# - 字段名集合: {'store_id', 'date_day', 'product_id'} == {'product_id', 'store_id', 'date_day'} ✓
# - 类型兼容: store_id(INTEGER) ↔ store_id(INTEGER) ✓
#            date_day(DATE) ↔ date_day(DATE) ✓
#            product_id(INTEGER) ↔ product_id(INTEGER) ✓
# 结果: 匹配成功 ✅

# 示例2: 字段名大小写不同，但匹配成功
源表复合键: ['Store_ID', 'Date_Day']
目标表字段: {'store_id': {...}, 'date_day': {...}}

# 检查：
# - 字段名集合（忽略大小写）: {'store_id', 'date_day'} == {'store_id', 'date_day'} ✓
# - 类型兼容: Store_ID(INTEGER) ↔ store_id(INTEGER) ✓
#            Date_Day(DATE) ↔ date_day(DATE) ✓
# 结果: 匹配成功 ✅

# 示例3: 缺少字段，匹配失败
源表复合键: ['store_id', 'date_day', 'product_id']
目标表字段: {'store_id': {...}, 'date_day': {...}}

# 检查：
# - 字段名集合: product_id 不存在于目标表 ✗
# 结果: 匹配失败 ❌

# 示例4: 类型不兼容，匹配失败
源表复合键: ['store_id', 'date_day']
目标表字段: {'store_id': {..., 'data_type': 'INTEGER'}, 
            'date_day': {..., 'data_type': 'TEXT'}}

# 检查：
# - 字段名集合: {'store_id', 'date_day'} == {'store_id', 'date_day'} ✓
# - 类型兼容: store_id(INTEGER) ↔ store_id(INTEGER) ✓
#            date_day(DATE) ↔ date_day(TEXT) ✗
# 结果: 匹配失败 ❌
```

### 3.3 第三阶段: 候选关系评估（数据库访问）

```
步骤5: 数据库采样和度量计算
├── 采样策略（基于JSON统计信息）:
│   ├── 表行数 < 10000: 全量采样
│   ├── 表行数 >= 10000: 采样率 = min(10000 / row_count, 0.1)
│   ├── 优先使用索引列进行查询优化
│   └── 利用JSON中的value_distribution指导采样
├── 包含率计算:
│   ├── 单列: intersection(from_values, to_values) / len(from_values)
│   └── 复合键: intersection(from_tuples, to_tuples) / len(from_tuples)
├── Jaccard系数:
│   └── len(intersection) / len(union)
├── 唯一度评分:
│   ├── 优先使用JSON中的statistics.uniqueness
│   └── 如需更新: 计算实际采样的unique_count / sample_count
├── 语义角色奖励:
│   ├── 两者都是identifier且高置信度: +1.0
│   ├── 角色相同且中等置信度: +0.8
│   └── 角色兼容: +0.5
└── 综合评分计算: 基于权重配置的加权平均
```

**性能特点**:
- ⏱️ 时间: 分钟级
- 🔌 数据库访问: 候选数 × 2（源表+目标表采样）

### 3.4 第四阶段: 决策和抑制规则

```
步骤6: 评分排序和决策
├── 评分排序: 按composite_score降序排列
├── 阈值过滤: 低于accept_threshold（默认0.80）的候选被丢弃，不写入结果JSON
└── 置信度分级（用于结果报告展示）:
    ├── high: composite_score >= 0.90
    ├── medium: 0.80 <= composite_score < 0.90
    └── low: composite_score < 0.80（通常仅在调试/诊断场景中保留）

步骤7: 抑制规则应用（默认启用，v3.2核心特性）
├── 核心规则: 同一对表，复合键成功 → 抑制单字段
│   ├── 条件1: 存在被接受的复合键关系（A → B）
│   ├── 条件2: 单字段关系也是A → B（同一对表）
│   ├── 条件3: 单字段在复合键的列中
│   └── 条件4: 列的对应关系匹配
├── 例外规则（自动检测）:
│   └── 源字段有独立的单字段约束
│       ├── 单字段主键: primary_key.columns = [column_name]
│       ├── 单字段唯一约束: unique_constraints中只有该列
│       └── 单字段索引: indexes中只有该列
├── 不抑制的情况:
│   ├── 目标表不同（单字段关联到其他表，如维度表）
│   ├── 源字段有独立约束（例外规则）
│   └── 复合键关系未被接受
└── 记录抑制信息:
    ├── 抑制原因记录
    ├── 原始评分保存
    ├── 判断是否本可被接受（could_have_been_accepted = composite_score >= decision.accept_threshold）
    └── 将记录嵌套保存到对应复合键关系的suppressed_single_relations数组中
```

**性能特点**:
- ⏱️ 时间: 秒级
- 🔌 数据库访问: **0次**

**抑制逻辑示例**:

场景A: 典型情况（应该抑制）
```sql
CREATE TABLE fact_sales (
    store_id INTEGER,
    date_day DATE,
    product_id INTEGER,
    PRIMARY KEY (store_id, date_day, product_id)  -- 只有复合主键
);
```

```
复合键关系: (store_id, date_day, product_id) → ... ✅ 接受

单字段候选（同一对表）:
  store_id → ...    ❌ 抑制（在复合键中，无独立约束）
  date_day → ...    ❌ 抑制（在复合键中，无独立约束）
  product_id → ...  ❌ 抑制（在复合键中，无独立约束）

单字段候选（不同目标表）:
  store_id → dim_store.store_id     ✅ 保留（目标表不同）
  date_day → dim_date.date_key      ✅ 保留（目标表不同）
  product_id → dim_product.product_id ✅ 保留（目标表不同）
```

场景B: 例外情况（不应该抑制）
```sql
CREATE TABLE fact_sales (
    store_id INTEGER,
    date_day DATE,
    product_id INTEGER,
    PRIMARY KEY (store_id, date_day, product_id),
    UNIQUE (store_id)  -- ✅ store_id有独立唯一约束
);
```

```
复合键关系: (store_id, date_day, product_id) → ... ✅ 接受

单字段候选（同一对表）:
  store_id → ...    ✅ 保留（有独立唯一约束，例外）
  date_day → ...    ❌ 抑制（无独立约束）
  product_id → ...  ❌ 抑制（无独立约束）
```

### 3.5 第五阶段: 结果输出

```
步骤8: 结果生成和报告
├── 关系对象创建:
│   ├── 为每个关系生成唯一ID（relationship_id）
│   ├── 包含完整的度量信息（metrics，涵盖6个评分维度）
│   ├── 附加JSON来源标记和发现方法（discovery_method/source_type等）
│   ├── 记录semantic_role信息
│   └── 保存抑制信息（嵌套在复合键对象的suppressed_single_relations中）
├── 统计信息汇总:
│   ├── 关系数量统计（复合键/单字段/被抑制单字段数等）
│   ├── 发现方法统计（active_search/dynamic_same_name/logical_key_matching等）
│   ├── 抑制关系统计（total_suppressed_single_relations等）
│   └── 性能优化统计（database_queries_saved、performance_improvement等）
├── JSON详细报告:
│   ├── 顶层统计信息（statistics节点）
│   ├── 性能优化统计（optimization_stats节点）
│   ├── 关系数组（relationships，包含被抑制关系的嵌套信息）
│   └── 元数据来源标记（metadata_source/json_metadata_version等）
└── Markdown摘要报告:
    ├── 按置信度分级展示
    ├── 标注发现方法
    ├── 列出被抑制的关系
    └── 提供统计概览
```

## 4. 评分系统

### 4.1 评分维度和权重

```yaml
weights:
  inclusion_rate: 0.30          # 包含率（最重要）
  jaccard_index: 0.15           # Jaccard系数
  uniqueness: 0.10              # 唯一度（从JSON获取）
  name_similarity: 0.20         # 名称相似度
  type_compatibility: 0.20      # 类型兼容性（从JSON获取）
  semantic_role_bonus: 0.05     # 语义角色匹配奖励
```

### 4.2 包含率计算（数据库访问）

**单列包含率**:
```python
def calculate_inclusion_rate(from_table, from_col, to_table, to_col):
    """
    计算FROM表中有多少值在TO表中存在
    """
    # 根据JSON中的行数决定采样策略
    from_sample = db.sample_column(from_table, from_col, sample_size)
    to_sample = db.sample_column(to_table, to_col, to_sample_size)
    
    from_clean = {v for v in from_sample if v is not None}
    to_clean = {v for v in to_sample if v is not None}
    
    if not from_clean:
        return 0.0
    
    intersection = from_clean & to_clean
    return len(intersection) / len(from_clean)
```

**复合键元组包含率**:
```python
def calculate_composite_inclusion_rate(from_table, from_cols, to_table, to_cols):
    """
    计算复合键的元组包含率
    """
    from_tuples = db.sample_columns_tuple(from_table, from_cols, sample_size)
    to_tuples = db.sample_columns_tuple(to_table, to_cols, to_sample_size)
    
    from_clean = {tuple(t) for t in from_tuples if all(v is not None for v in t)}
    to_clean = {tuple(t) for t in to_tuples if all(v is not None for v in t)}
    
    if not from_clean:
        return 0.0
    
    intersection = from_clean & to_clean
    return len(intersection) / len(from_clean)
```

### 4.3 唯一度评分（优先从JSON）

```python
def get_uniqueness_score(col_profile):
    """
    从JSON直接获取唯一度，无需数据库访问
    """
    uniqueness = col_profile['statistics'].get('uniqueness', 0)
    
    # 校验有效性
    if uniqueness is None or uniqueness < 0 or uniqueness > 1:
        # 异常值，需要数据库重新计算
        return None
    
    return uniqueness
```

### 4.4 名称相似度计算（仅使用字段名）

**确定性算法**:
```python
def calculate_name_similarity(from_col_name, to_col_name):
    """
    基于字段名计算相似度
    """
    # 1. 标准化
    from_normalized = normalize_name(from_col_name)
    to_normalized = normalize_name(to_col_name)
    
    # 2. 通用标识符过滤
    if (from_normalized in generic_tokens and 
        to_normalized in generic_tokens and
        from_normalized == to_normalized):
        return 0.0  # 避免"id vs id"垄断
    
    # 3. 完全匹配
    if from_normalized == to_normalized:
        return 1.0
    
    # 4. 同义词匹配
    if are_synonyms(from_normalized, to_normalized):
        return 0.9
    
    # 5. 包含关系
    if from_normalized in to_normalized or to_normalized in from_normalized:
        return 0.8
    
    # 6. 特殊模式: xxx_id ↔ id
    if (from_normalized.endswith('_id') and to_normalized == 'id') or \
       (to_normalized.endswith('_id') and from_normalized == 'id'):
        return 0.7
    
    # 7. 向量相似度（可选）
    if use_embedding and embedding_service.is_available():
        return embedding_service.calculate_similarity(from_col_name, to_col_name)
    
    # 8. 编辑距离兜底
    return difflib.SequenceMatcher(None, from_normalized, to_normalized).ratio()
```

### 4.5 类型兼容性（从JSON）

```python
def calculate_type_compatibility(from_type, to_type):
    """
    从JSON的data_type计算兼容性
    """
    if from_type == to_type:
        return 1.0
    
    # 使用预定义的类型兼容性组
    for group in type_compatibility_groups:
        if from_type in group and to_type in group:
            return 0.8
    
    # 数值类型宽松兼容
    if from_type in numeric_types and to_type in numeric_types:
        return 0.6
    
    # 字符串类型宽松兼容
    if from_type in string_types and to_type in string_types:
        return 0.6
    
    return 0.0
```

### 4.6 语义角色奖励（从JSON）

**说明**: 源列筛选时，除audit和metric外的所有semantic_role都可以通过筛选。但在**评分阶段**，不同的semantic_role匹配会获得不同的奖励分。

```python
def calculate_semantic_role_bonus(from_col_profile, to_col_profile):
    """
    基于semantic_role的匹配度计算奖励分
    
    注意：这是评分阶段的逻辑，不影响候选筛选
    """
    from_role = from_col_profile['semantic_analysis']['semantic_role']
    to_role = to_col_profile['semantic_analysis']['semantic_role']
    from_conf = from_col_profile['semantic_analysis']['semantic_confidence']
    to_conf = to_col_profile['semantic_analysis']['semantic_confidence']
    
    # 两者都是identifier且高置信度
    if (from_role == 'identifier' and to_role == 'identifier' and
        from_conf >= 0.85 and to_conf >= 0.85):
        return 1.0
    
    # 角色相同且中等置信度
    if from_role == to_role and from_conf >= 0.7 and to_conf >= 0.7:
        return 0.8
    
    # 角色兼容
    compatible_pairs = [
        ('datetime', 'identifier'),
        ('enum', 'identifier'),
        ('identifier', 'enum')
    ]
    if (from_role, to_role) in compatible_pairs:
        return 0.5
    
    return 0.0
```

### 4.7 综合评分计算

```python
def calculate_composite_score(metrics, weights, col_profiles):
    """
    计算综合评分
    """
    # 基础评分（5个维度）
    base_score = (
        weights['inclusion_rate'] * metrics.inclusion_rate +
        weights['jaccard_index'] * metrics.jaccard_index +
        weights['uniqueness'] * metrics.uniqueness_score +
        weights['name_similarity'] * metrics.name_similarity +
        weights['type_compatibility'] * metrics.type_compatibility
    )
    
    # 语义角色奖励
    semantic_bonus = (
        weights['semantic_role_bonus'] * 
        calculate_semantic_role_bonus(
            col_profiles['from'], 
            col_profiles['to']
        )
    )
    
    # 综合评分
    score = base_score + semantic_bonus
    metrics.composite_score = min(1.0, max(0.0, score))
    
    return metrics.composite_score
```

## 5. 配置说明

### 5.1 完整配置示例

```yaml
# JSON元数据配置
json_metadata:
  enabled: true
  # 表元数据目录（存储表的完整元数据和画像数据）
  metadata_directory: "./output/metaweave/metadata/json"
  # 关联关系输出目录
  output_directory: "./output/metaweave/metadata/rel"
  version: "2.0"
  validate_on_load: true

# 单字段候选配置
single_column:
  # 主动搜索同名字段（v3.2新增）
  active_search_same_name: true
  
  # 重要约束定义（触发主动搜索）
  important_constraints:
    - 'single_field_primary_key'
    - 'single_field_unique_constraint'
    - 'single_field_index'
  
  # 源列筛选
  exclude_semantic_roles:
    - 'audit'
    - 'metric'
  max_null_rate: 0.8
  
  # 目标列筛选
  logical_key_min_confidence: 0.8

# 复合键候选配置
composite:
  max_columns: 3
  
  # 源表复合键来源
  source_types:
    - 'primary_key'
    - 'unique_constraints'
    - 'foreign_keys'
    - 'indexes'
  
  # 目标表复合键来源（v3.2扩展）
  target_sources:
    - 'physical_constraints'        # 物理约束（主键、唯一约束、外键、索引）
    - 'candidate_logical_keys'      # 逻辑主键
    - 'dynamic_same_name'            # 动态同名发现
  
  # 阈值（仅用于物理约束之间的匹配，不用于动态同名匹配）
  min_name_similarity: 0.7          # 逐列名称相似度
  min_type_compatibility: 0.8       # 逐列类型兼容度

# 评分权重
weights:
  inclusion_rate: 0.30
  jaccard_index: 0.15
  uniqueness: 0.10
  name_similarity: 0.20
  type_compatibility: 0.20
  semantic_role_bonus: 0.05

# 决策配置
decision:
  # 接受/拒绝阈值：低于该值的候选不会写入结果JSON
  accept_threshold: 0.80              # 默认与 medium_confidence_threshold 一致
  # 置信度分级（仅用于结果报告展示）
  high_confidence_threshold: 0.90     # 高置信度分级线
  medium_confidence_threshold: 0.80   # 中等置信度分级线
  
  # 抑制规则（v3.2默认启用）
  suppress_single_if_composite: true
  # 例外规则自动检测，不需要配置
```

### 5.2 配置说明

**json_metadata**:
- `enabled`: 是否启用JSON元数据优先策略
- `metadata_directory`: 表元数据JSON文件存放目录（详见下方目录结构）
- `output_directory`: 关联关系分析结果输出目录（详见下方目录结构）
- `version`: 支持的JSON元数据版本（当前为"2.0"）
- `validate_on_load`: 是否在加载时验证JSON完整性

**目录结构**:
```
./output/metaweave/metadata/
├── json/                                    # 表元数据目录 (metadata_directory)
│   ├── public.dim_store.json                # 维度表元数据
│   ├── public.dim_date.json                 # 日期维表元数据
│   ├── public.fact_sales.json               # 事实表元数据
│   └── ...
│   
│   文件命名: {schema}.{table}.json
│   文件内容: 表的完整元数据和画像数据（JSON格式，v2.0版本）
│   用途: 算法从此目录读取物理约束、逻辑主键、字段画像等信息
│
└── rel/                                     # 关联关系目录 (output_directory)
    ├── relationships.json                   # 发现的关联关系
    ├── relationships_summary.md             # 关系摘要报告
    └── ...
    
    用途: 算法将关联关系分析结果写入此目录
```

**single_column.active_search_same_name**:
- `true`: 启用主动搜索，源字段有重要约束时主动在目标表查找同名字段
- `false`: 禁用，只使用常规筛选

**composite.target_sources**:
- `physical_constraints`: 目标表的物理复合约束
  - 包括：复合物理主键、复合唯一约束、复合外键、复合索引
  - 说明：所有来自 `table_profile.physical_constraints` 的复合约束（列数>=2）
- `candidate_logical_keys`: 目标表的候选逻辑主键（JSON推断）
  - 来源：`table_profile.logical_keys.candidate_primary_keys`
  - 条件：`confidence_score >= 0.8` 且列数 >= 2
- `dynamic_same_name`: 动态发现与源表同名的字段组合
  - 逻辑：字段名集合完全相同（忽略大小写和顺序）
  - 条件：每个对应字段的类型必须兼容
  - 说明：不需要置信度阈值，完全匹配即接受

**composite.min_name_similarity 和 min_type_compatibility**:
- 用途：仅用于物理约束之间的匹配（如主键↔主键、主键↔逻辑主键）
- 不用于：动态同名匹配（动态同名要求字段名完全相同）
- `min_name_similarity`: 逐列名称相似度阈值（默认0.7）
- `min_type_compatibility`: 逐列类型兼容度阈值（默认0.8）

**decision.high_confidence_threshold 和 medium_confidence_threshold**:
- 用途：仅用于对已被`decision.accept_threshold`接受的关系做结果报告分级展示
- 分级规则（在`composite_score >= accept_threshold`的前提下）：
  - `composite_score >= 0.90`: 高置信度（high）
  - `0.80 <= composite_score < 0.90`: 中等置信度（medium）
  - `composite_score < 0.80`: 低置信度（low）
- 说明：所有评分达到接受阈值的关系都会被接受，无论其置信度级别

**decision.suppress_single_if_composite**:
- `true`（默认）: 同一对表，复合键成功后自动抑制单字段关系
- `false`: 不抑制，所有关系都保留

## 6. 输出报告示例

### 6.1 JSON详细报告

```json
{
  "metadata_source": "json_files",
  "json_metadata_version": "2.0",
  "json_files_loaded": 5,
  "database_queries_executed": 123,
  
  "analysis_timestamp": "2025-11-24T16:00:00Z",
  
  "statistics": {
    "total_relationships_found": 8,
    "composite_key_relationships": 2,
    "single_column_relationships": 6,
    "total_suppressed_single_relations": 12,
    "active_search_discoveries": 5,
    "dynamic_composite_discoveries": 2
  },
  
  "optimization_stats": {
    "metadata_from_json_percentage": 100,
    "statistics_from_json_percentage": 95,
    "database_queries_saved": 677,
    "performance_improvement": "6.5x",
    "performance_improvement_factor": 6.5
  },
  
  "relationships": [
    {
      "relationship_id": "rel_001",
      "type": "composite_key",
      "from_table": {
        "schema": "public",
        "table": "fact_sales_day"
      },
      "source_columns": ["store_id", "date_day", "product_id"],
      "to_table": {
        "schema": "public",
        "table": "fact_sales_month"
      },
      "target_columns": ["store_id", "date_month", "product_id"],
      "source_type": "candidate_logical_key",
      "discovery_method": "logical_key_matching",
      "composite_score": 0.85,
      "confidence_level": "high",
      "metrics": {
        "inclusion_rate": 0.75,
        "jaccard_index": 0.68,
        "name_similarity": 0.9,
        "type_compatibility": 1.0,
        "uniqueness": 1.0,
        "semantic_role_bonus": 0.8
      },
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
          "to_column": "date_month",
          "original_score": 0.76,
          "suppression_reason": "在复合键中，无独立约束",
          "could_have_been_accepted": false
        },
        {
          "from_column": "product_id",
          "to_column": "product_id",
          "original_score": 0.90,
          "suppression_reason": "在复合键中，无独立约束",
          "could_have_been_accepted": true
        }
      ]
    },
    {
      "relationship_id": "rel_002",
      "type": "single_column",
      "from_table": {
        "schema": "public",
        "table": "fact_sales_day"
      },
      "from_column": "store_id",
      "to_table": {
        "schema": "public",
        "table": "dim_store"
      },
      "to_column": "store_id",
      "composite_score": 0.95,
      "confidence_level": "high",
      "discovery_method": "active_search",
      "source_constraint": "single_field_index",
      "metrics": {
        "inclusion_rate": 1.0,
        "jaccard_index": 0.98,
        "uniqueness": 1.0,
        "name_similarity": 1.0,
        "type_compatibility": 1.0,
        "semantic_role_bonus": 1.0
      },
      "semantic_roles": {
        "from_column": "identifier",
        "to_column": "identifier",
        "from_confidence": 0.95,
        "to_confidence": 0.98
      },
      "note": "源字段有独立索引，主动发现目标字段"
    },
    {
      "relationship_id": "rel_003",
      "type": "single_column",
      "from_table": {
        "schema": "public",
        "table": "fact_sales_day"
      },
      "from_column": "date_day",
      "to_table": {
        "schema": "public",
        "table": "dim_date"
      },
      "to_column": "date_key",
      "composite_score": 0.92,
      "confidence_level": "high",
      "discovery_method": "standard_matching",
      "metrics": {
        "inclusion_rate": 0.98,
        "jaccard_index": 0.95,
        "uniqueness": 1.0,
        "name_similarity": 0.85,
        "type_compatibility": 1.0,
        "semantic_role_bonus": 0.8
      }
    }
  ]
}
```

### 6.2 Markdown摘要报告

```markdown
# DB2Graph 分析报告

**运行时间**: 2025-11-23T16:00:00
**数据库**: mydb（schema: public）
**JSON文件**: 5个
**执行时间**: 28秒

## 统计信息

- 分析表数量: 5
- 分析列数量: 25
- 生成候选数: 150
- 发现关系数: 8
- 被抑制关系数: 12

## 元数据来源统计

- JSON元数据覆盖率: 100%
- 数据库查询次数: 123（vs传统方法800+）
- 性能提升: 约6.5倍
- 主动搜索发现: 5个关系
- 动态复合键匹配: 2个关系

## 发现的关系

### 复合键关系（2个）

#### 1. fact_sales_day → fact_sales_month
- **关联字段**: （store_id, date_day, product_id） → （store_id, date_month, product_id）
- **来源**: 候选逻辑主键匹配 🔍
- **评分**: 0.85
- **置信度**: high
- **抑制的单字段**（3个）:
  - ⛔ store_id → store_id（评分0.88，在复合键中，无独立约束）
  - ⛔ date_day → date_month（评分0.76，在复合键中，无独立约束）
  - ⛔ product_id → product_id（评分0.90，在复合键中，无独立约束）

### 高置信度单列关系（5个）

#### 1. fact_sales_day.store_id → dim_store.store_id
- **评分**: 0.95
- **发现方法**: 主动搜索 🔍
- **说明**: 源字段有独立索引，主动在目标表中发现同名字段

#### 2. fact_sales_day.date_day → dim_date.date_key
- **评分**: 0.92
- **发现方法**: 常规匹配
- **说明**: 标准的外键关系

### 被抑制的关系（12个）

详见复合键关系中的说明

## 配置信息

- 主动搜索: 启用
- 动态复合键: 启用
- 抑制规则: 默认启用
- 最大复合键列数: 3
```

## 7. 算法流程总结图

```
┌─────────────────────────────────────────────────────┐
│  阶段1: JSON元数据加载                               │
│  • 加载所有JSON文件                                  │
│  • 提取physical_constraints                         │
│  • 提取logical_keys                                 │
│  • 构建内存索引                                      │
│  ⏱️  时间: 秒级                                      │
│  🔌 数据库访问: 0次                                  │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│  阶段2: 候选关系生成（优先复合键）                   │
│  • 复合键候选（物理+逻辑+动态）                      │
│  • 单字段常规筛选                                    │
│  • 主动搜索同名字段（v3.2新增）                      │
│  • 基于semantic_role筛选                            │
│  ⏱️  时间: 秒级                                      │
│  🔌 数据库访问: 0次                                  │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│  阶段3: 候选关系评估                                 │
│  • 数据库采样（优化策略）                            │
│  • 计算包含率（单列/复合键）                         │
│  • 计算Jaccard系数                                  │
│  • 唯一度（优先用JSON）                             │
│  • 语义角色奖励                                      │
│  ⏱️  时间: 分钟级                                    │
│  🔌 数据库访问: 候选数×2                             │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│  阶段4: 决策和抑制规则                               │
│  • 评分排序                                          │
│  • 置信度分级                                        │
│  • 抑制规则应用（v3.2默认）                          │
│    - 同一对表，复合键成功→抑制单字段                 │
│    - 例外: 源字段有独立约束                          │
│  ⏱️  时间: 秒级                                      │
│  🔌 数据库访问: 0次                                  │
└─────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────┐
│  阶段5: 结果输出                                     │
│  • 关系对象创建与持久化（relationships等）           │
│  • JSON详细报告                                      │
│  • Markdown摘要                                      │
│  • 标注发现方法和抑制信息                            │
│  ⏱️  时间: 秒级                                      │
│  🔌 数据库访问: 0次                                  │
└─────────────────────────────────────────────────────┘
```

## 8. 核心特性总结

### 8.1 JSON元数据优先

- **阶段1-2完全零数据库访问**
- **统计信息直接从JSON获取**
- **性能提升5-10倍**

### 8.2 主动发现机制（v3.2）

- **源字段有重要约束时主动寻找同名字段**
- **不再被动等待目标表满足筛选条件**
- **提高关联发现覆盖率**

### 8.3 动态复合键匹配（v3.2）

- **字段名完全匹配**：字段名集合相同（忽略大小写和顺序）
- **类型兼容检查**：每个对应字段的类型必须兼容
- **简单明确**：不需要相似度计算，完全匹配即接受
- **不依赖完整的物理约束定义**

### 8.4 智能抑制规则（v3.2）

- **默认启用，自动检测**
- **同一对表，复合键成功→抑制单字段**
- **自动识别例外（源字段有独立约束）**
- **避免语义错误的多对多匹配**

### 8.5 简化配置（v3.2）

- **移除复杂的例外规则配置**
- **自动检测独立约束**
- **规则简单明确: 同一对表就抑制**

## 9. 最佳实践

### 9.1 JSON文件准备

1. **定期生成**: 每日或每周重新生成JSON元数据
2. **完整性检查**: 确保physical_constraints和logical_keys完整
3. **版本控制**: 保留历史JSON用于回溯分析

### 9.2 配置调优

**小型数据库（<10张表）**:
```yaml
single_column:
  active_search_same_name: true
composite:
  max_columns: 3
  target_sources:
    - 'physical_constraints'
    - 'candidate_logical_keys'
    - 'dynamic_same_name'
```

**中型数据库（10-50张表）**:
```yaml
single_column:
  active_search_same_name: true
  max_null_rate: 0.7
composite:
  max_columns: 3
```

**大型数据库（50+张表）**:
```yaml
single_column:
  active_search_same_name: true
  logical_key_min_confidence: 0.85
composite:
  max_columns: 2
  min_name_similarity: 0.75
```

### 9.3 结果验证

1. **检查抑制的关系是否合理**
2. **验证主动搜索发现的关系**
3. **对比复合键和单字段的评分**
4. **SQL验证包含率计算的准确性**

---

**文档版本**: v3.2  
**更新日期**: 2025-11-24  
**作者**: DB2Graph Team
