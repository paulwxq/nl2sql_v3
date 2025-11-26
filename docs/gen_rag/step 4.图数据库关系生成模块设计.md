# 图数据库关系生成模块设计

## 概述

图数据库关系生成模块（Step 3）是 MetaWeave 平台中的核心模块，负责基于表画像和字段画像自动发现表之间的关联关系，并生成可直接执行的 Neo4j Cypher 语句。该模块结合了确定性规则匹配和数据实际分析，能够从元数据和数据样本中自动发现逻辑外键关系。

## 1. 模块定位与职责

### 1.1 输入

- **JSON 画像文件**：从 `output/metaweave/metadata/json/` 目录读取
  - 表画像信息（table_profile）
  - 字段画像信息（column_profiles）
  - 统计信息（statistics）
  - 样例数据（sample_records）
  - 逻辑主键信息（logical_keys）
  
- **数据库实时访问**：连接到数据库获取实际数据用于关系验证
  - 字段值采样
  - 数据分布分析
  - 关系验证查询

### 1.2 输出

- **Cypher 文件**：保存到 `output/metaweave/metadata/cql/` 目录
  - 文件命名格式：`relationships_{run_id}_{timestamp}.cypher`
  - 示例：`relationships_0af644bd-a559-40ee-883c-cd4b692d5bc5_20250922_103153.cypher`
  - 包含表节点创建、关系创建和统计信息

### 1.3 核心职责

1. **关系发现**：基于字段名、类型、统计特征自动发现表之间的潜在关联关系
2. **关系验证**：通过数据实际匹配验证关系的有效性和置信度
3. **关系评分**：基于多维度指标计算关系的综合评分
4. **Cypher 生成**：生成符合 Neo4j 语法的可执行语句

## 2. 算法设计

### 2.1 关系发现流程

```
┌─────────────────────────────────────────────────────────────┐
│                     Step 3: 关系生成流程                      │
└─────────────────────────────────────────────────────────────┘

第一阶段：元数据加载
├── 1. 读取 JSON 画像文件
│   ├── 解析表结构信息
│   ├── 提取字段画像
│   ├── 获取统计信息
│   └── 识别逻辑主键
│
├── 2. 构建元数据索引
│   ├── 表索引（按表名）
│   ├── 列索引（按语义角色）
│   └── 主键索引（物理+逻辑）
│
第二阶段：候选关系生成
├── 3. 单列关系候选
│   ├── 表对枚举（两两组合）
│   ├── 列对筛选
│   │   ├── 源列：identifier 类型
│   │   ├── 目标列：逻辑主键或高唯一性
│   │   └── 类型兼容性检查
│   ├── 名称相似度计算
│   │   ├── 完全匹配（如 store_id = store_id）
│   │   ├── 同义词匹配（如 product_id = prod_id）
│   │   ├── 包含关系（如 company_id 包含 id）
│   │   └── 编辑距离（兜底计算）
│   └── 候选生成（name_similarity >= 0.6）
│
├── 4. 复合键关系候选
│   ├── 弱候选筛选（0.5 <= name_sim < 0.8）
│   ├── 按表对分组
│   ├── 组合生成（2-3列）
│   └── 优先模式匹配
│
第三阶段：关系验证与评分
├── 5. 数据采样
│   ├── 从数据库获取字段值样本
│   ├── 采样策略：1% 或最多 10000 行
│   └── 去重和清洗
│
├── 6. 度量计算
│   ├── 包含率（inclusion_rate）
│   │   └── from_values 中有多少在 to_values 中
│   ├── Jaccard 系数（jaccard_index）
│   │   └── 交集/并集
│   ├── 唯一度（uniqueness_score）
│   │   └── 目标列的唯一性
│   ├── 名称相似度（name_similarity）
│   ├── 类型兼容性（type_compatibility）
│   └── 名称复杂度（name_complexity）
│
├── 7. 综合评分
│   ├── 加权计算
│   │   ├── inclusion_rate × 0.30
│   │   ├── jaccard_index × 0.15
│   │   ├── uniqueness × 0.10
│   │   ├── name_similarity × 0.20
│   │   ├── type_compatibility × 0.20
│   │   └── name_complexity × 0.05
│   └── 置信度分级
│       ├── high: composite_score >= 0.90
│       ├── medium: 0.80 <= composite_score < 0.90
│       └── low: composite_score < 0.80（可选择过滤）
│
第四阶段：Cypher 生成
├── 8. 表节点生成
│   ├── 创建唯一约束
│   └── MERGE 表节点（附带元数据属性）
│
├── 9. 关系语句生成
│   ├── 单列关系：JOIN 关系
│   ├── 复合键关系：COMPOSITE_JOIN 关系
│   └── 附加度量属性
│
└── 10. 输出与统计
    ├── 写入 .cypher 文件
    ├── 生成统计信息
    └── 日志记录
```

### 2.2 关键算法细节

#### 2.2.1 列对筛选规则

**源列筛选条件：**
```python
def is_candidate_source_column(column_profile):
    """判断字段是否适合作为源列（外键候选）"""
    # 1. 必须是 identifier 类型
    if column_profile['semantic_role'] != 'identifier':
        return False
    
    # 2. 排除噪声字段
    noise_patterns = ['_ts', '_time', 'created_', 'updated_', 'deleted_']
    if any(p in column_profile['column_name'].lower() for p in noise_patterns):
        return False
    
    # 4. 检查空值率（从 statistics 获取）
    if column_profile.get('statistics', {}).get('null_rate', 0) > 0.8:
        return False
    
    return True
```

**目标列筛选条件：**
```python
def is_candidate_target_column(column_profile, table_profile):
    """判断字段是否适合作为目标列（主键候选）"""
    # 1. 必须是逻辑主键或高唯一性
    logical_keys = table_profile['key_columns']['logical_keys']
    is_logical_key = column_profile['column_name'] in logical_keys
    
    # 2. 或者唯一性 >= 0.95
    uniqueness = column_profile.get('statistics', {}).get('uniqueness', 0)
    
    # 3. 或者被标记为 is_unique
    is_unique = column_profile['structure_flags']['is_unique']
    
    return is_logical_key or uniqueness >= 0.95 or is_unique
```

#### 2.2.2 名称相似度计算

```python
def calculate_name_similarity(name1, name2):
    """计算字段名相似度（0.0-1.0）"""
    # 标准化：转小写，去除下划线、连字符
    norm1 = name1.lower().replace('_', '').replace('-', '')
    norm2 = name2.lower().replace('_', '').replace('-', '')
    
    # 1. 完全匹配
    if norm1 == norm2:
        return 1.0
    
    # 2. 同义词匹配（可配置）
    synonyms = [
        ['id', 'identifier', 'key'],
        ['name', 'title', 'label'],
        ['type', 'category', 'kind'],
        ['amount', 'value', 'total']
    ]
    for group in synonyms:
        if norm1 in group and norm2 in group:
            return 0.9
    
    # 3. 包含关系
    if norm1 in norm2 or norm2 in norm1:
        return 0.8
    
    # 4. 特殊模式：xxx_id 匹配 id
    if norm1.endswith('id') and norm2 == 'id':
        return 0.7
    if norm2.endswith('id') and norm1 == 'id':
        return 0.7
    
    # 5. 编辑距离（SequenceMatcher）
    from difflib import SequenceMatcher
    return SequenceMatcher(None, norm1, norm2).ratio()
```

#### 2.2.3 类型兼容性映射

```python
# 类型兼容性分组配置
TYPE_COMPATIBILITY_GROUPS = {
    'integer_group': ['integer', 'bigint', 'smallint', 'int', 'int4', 'int8'],
    'numeric_group': ['numeric', 'decimal', 'real', 'double precision', 'float'],
    'text_group': ['character varying', 'varchar', 'text', 'char', 'character'],
    'date_group': ['date', 'timestamp', 'timestamp without time zone', 'timestamp with time zone'],
    'boolean_group': ['boolean', 'bool']
}

def calculate_type_compatibility(type1, type2):
    """计算类型兼容性（0.0-1.0）"""
    # 完全相同
    if type1 == type2:
        return 1.0
    
    # 同组兼容
    for group in TYPE_COMPATIBILITY_GROUPS.values():
        if type1 in group and type2 in group:
            return 0.8
    
    # 不兼容
    return 0.0
```

#### 2.2.4 数据验证与度量计算

```python
def calculate_relationship_metrics(from_table, from_column, to_table, to_column, db_conn):
    """计算关系度量指标"""
    
    # 1. 数据采样
    sample_size = 10000
    from_values = get_column_sample(db_conn, from_table, from_column, sample_size)
    to_values = get_column_sample(db_conn, to_table, to_column, sample_size)
    
    # 2. 去除 NULL 值
    from_clean = {v for v in from_values if v is not None}
    to_clean = {v for v in to_values if v is not None}
    
    # 3. 包含率：from 中有多少在 to 中
    intersection = from_clean & to_clean
    inclusion_rate = len(intersection) / len(from_clean) if from_clean else 0.0
    
    # 4. Jaccard 系数
    union = from_clean | to_clean
    jaccard_index = len(intersection) / len(union) if union else 0.0
    
    # 5. 唯一度（来自 JSON 的 statistics.uniqueness）
    uniqueness_score = to_column_profile['statistics']['uniqueness']
    
    # 6. 综合评分
    weights = {
        'inclusion_rate': 0.30,
        'jaccard_index': 0.15,
        'uniqueness': 0.10,
        'name_similarity': 0.20,
        'type_compatibility': 0.20,
        'name_complexity': 0.05
    }
    
    composite_score = (
        inclusion_rate * weights['inclusion_rate'] +
        jaccard_index * weights['jaccard_index'] +
        uniqueness_score * weights['uniqueness'] +
        name_similarity * weights['name_similarity'] +
        type_compatibility * weights['type_compatibility'] +
        name_complexity * weights['name_complexity']
    )
    
    # 7. 保留两位小数
    return {
        'inclusion_rate': round(inclusion_rate, 2),
        'jaccard_index': round(jaccard_index, 2),
        'uniqueness_score': round(uniqueness_score, 2),
        'composite_score': round(composite_score, 2),
        'confidence_level': get_confidence_level(composite_score)
    }

def get_confidence_level(score):
    """根据综合评分确定置信度等级"""
    if score >= 0.90:
        return 'high'
    elif score >= 0.80:
        return 'medium'
    else:
        return 'low'
```

#### 2.2.5 复合键关系识别

```python
def find_composite_relationships(weak_candidates, max_columns=3):
    """识别复合键关系"""
    # 1. 按表对分组
    table_pairs = {}
    for candidate in weak_candidates:
        key = (candidate['from_table'], candidate['to_table'])
        if key not in table_pairs:
            table_pairs[key] = []
        table_pairs[key].append(candidate)
    
    # 2. 对每个表对，尝试组合
    composite_candidates = []
    for (from_table, to_table), candidates in table_pairs.items():
        # 尝试 2 列组合
        for combo in combinations(candidates, 2):
            if is_valid_composite_key(combo, from_table, to_table):
                composite_candidates.append({
                    'from_table': from_table,
                    'to_table': to_table,
                    'column_pairs': combo,
                    'relationship_type': 'composite'
                })
        
        # 尝试 3 列组合（如果需要）
        if max_columns >= 3:
            for combo in combinations(candidates, 3):
                if is_valid_composite_key(combo, from_table, to_table):
                    composite_candidates.append({
                        'from_table': from_table,
                        'to_table': to_table,
                        'column_pairs': combo,
                        'relationship_type': 'composite'
                    })
    
    return composite_candidates

def is_valid_composite_key(column_pairs, from_table, to_table):
    """验证复合键有效性"""
    # 1. 检查目标列是否组成逻辑主键
    to_columns = [pair['to_column'] for pair in column_pairs]
    logical_keys = get_logical_keys(to_table)
    
    # 查找是否存在匹配的逻辑主键组合
    for key in logical_keys:
        if set(to_columns) == set(key['columns']):
            return True
    
    return False
```

## 3. Cypher 语句生成

### 3.1 文件结构

```cypher
// DB2Graph - 自动生成的 Cypher 语句
// run_id: {run_id}
// 作业启动时间: {timestamp}
// 模型类型: lightweight
// ================================================

// 第一部分：创建唯一约束
CREATE CONSTRAINT table_name_unique IF NOT EXISTS
FOR (t:Table) REQUIRE t.name IS UNIQUE;

// 第二部分：创建表节点
MERGE (t:Table {name: '{table_name}'})
SET t.schema = '{schema}',
    t.full_name = '{schema}.{table_name}',
    t.column_count = {count},
    t.primary_keys = {primary_keys},
    t.row_count = {row_count},
    t.has_primary_key = {bool},
    t.foreign_key_count = {count},
    t.unique_key_count = {count},
    t.updated_at = datetime();

// 第三部分：创建关系
MATCH (from:Table {name: '{from_table}'})
MATCH (to:Table {name: '{to_table}'})
MERGE (from)-[r:JOIN]->(to)
SET r.from_fields = ['{column}'],
    r.to_fields = ['{column}'],
    r.join_type = 'LEFT',
    r.relationship_type = 'inferred',
    r.inclusion_rate = {value},
    r.jaccard_index = {value},
    r.uniqueness_score = {value},
    r.name_similarity = {value},
    r.type_compatibility = {value},
    r.composite_score = {value},
    r.confidence_level = '{level}',
    r.source = 'auto_detected',
    r.verified = {bool},
    r.discovered_at = datetime(),
    r.label = '{from_col} = {to_col}';

// 第四部分：统计信息
// ================================================
// 总关系数: {total}
// 高置信度: {high_count}
// 中置信度: {medium_count}
// 低置信度: {low_count}
// 平均包含率: {avg_inclusion}%
// 平均置信度: {avg_confidence}%
// ================================================
```

### 3.2 表节点属性设计

从 JSON 画像提取的表节点属性：

| 属性名 | 来源 | 说明 |
|--------|------|------|
| `name` | `table_name` | 表名（唯一标识） |
| `schema` | `schema_name` | 模式名 |
| `full_name` | 拼接 | 完整表名 |
| `column_count` | `len(columns)` | 列数量 |
| `primary_keys` | `table_profile.key_columns.logical_keys` | 主键列表 |
| `row_count` | `row_count` | 行数 |
| `has_primary_key` | 判断 | 是否有主键 |
| `foreign_key_count` | `len(foreign_keys)` | 外键数量 |
| `unique_key_count` | `len(unique_constraints)` | 唯一约束数量 |
| `table_category` | `table_profile.table_category` | 表类型（fact/dim/bridge） |
| `comment` | `comment` | 表注释 |
| `updated_at` | 动态 | 更新时间 |

### 3.3 关系属性设计

#### 3.3.1 单列关系（JOIN）

| 属性名 | 类型 | 说明 |
|--------|------|------|
| `from_fields` | List[String] | 源字段列表 |
| `to_fields` | List[String] | 目标字段列表 |
| `join_type` | String | JOIN 类型（LEFT/INNER） |
| `relationship_type` | String | 关系类型（inferred） |
| `inclusion_rate` | Float | 包含率（0-1） |
| `jaccard_index` | Float | Jaccard 系数（0-1） |
| `uniqueness_score` | Float | 唯一度（0-1） |
| `name_similarity` | Float | 名称相似度（0-1） |
| `type_compatibility` | Float | 类型兼容性（0-1） |
| `composite_score` | Float | 综合评分（0-1） |
| `confidence_level` | String | 置信度（high/medium/low） |
| `source` | String | 来源（auto_detected） |
| `verified` | Boolean | 是否已验证 |
| `discovered_at` | DateTime | 发现时间 |
| `label` | String | 关系标签（用于显示） |

#### 3.3.2 复合键关系（COMPOSITE_JOIN）

在单列关系属性基础上，增加：

| 属性名 | 类型 | 说明 |
|--------|------|------|
| `from_source` | String | 源列来源（foreign_key/primary_key/unique_key） |
| `to_source` | String | 目标列来源 |
| `column_pairs` | JSON String | 列对详情 |

`column_pairs` 示例：
```json
[
  {
    "from_column": "product_id",
    "to_column": "product_id",
    "name_similarity": 1.0,
    "name_source": "deterministic",
    "type_compatibility": 1.0
  },
  {
    "from_column": "price_list_id",
    "to_column": "price_list_id",
    "name_similarity": 1.0,
    "name_source": "deterministic",
    "type_compatibility": 1.0
  }
]
```

### 3.4 生成逻辑伪代码

```python
def generate_cypher_file(tables, relationships, output_path):
    """生成 Cypher 文件"""
    run_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"relationships_{run_id}_{timestamp}.cypher"
    
    with open(os.path.join(output_path, filename), 'w', encoding='utf-8') as f:
        # 1. 文件头
        write_header(f, run_id)
        
        # 2. 唯一约束
        write_constraints(f)
        
        # 3. 表节点
        write_table_nodes(f, tables)
        
        # 4. 关系
        write_relationships(f, relationships)
        
        # 5. 统计信息
        write_statistics(f, relationships)

def write_table_nodes(f, tables):
    """写入表节点创建语句"""
    f.write("// 创建表节点\n\n")
    
    for table in tables:
        # 从 JSON 画像提取属性
        table_name = table['table_name']
        schema_name = table['schema_name']
        column_count = len(table['columns'])
        
        # 逻辑主键
        logical_keys = table['table_profile']['key_columns']['logical_keys']
        
        # 行数
        row_count = table.get('row_count', 0)
        
        # 外键和唯一键数量
        fk_count = len(table.get('foreign_keys', []))
        uk_count = len(table.get('unique_constraints', []))
        
        has_pk = len(logical_keys) > 0
        
        # 生成 MERGE 语句
        f.write(f"MERGE (t:Table {{name: '{table_name}'}})\n")
        f.write(f"SET t.schema = '{schema_name}',\n")
        f.write(f"    t.full_name = '{schema_name}.{table_name}',\n")
        f.write(f"    t.column_count = {column_count},\n")
        f.write(f"    t.primary_keys = {logical_keys},\n")
        f.write(f"    t.row_count = {row_count},\n")
        f.write(f"    t.has_primary_key = {str(has_pk).lower()},\n")
        f.write(f"    t.foreign_key_count = {fk_count},\n")
        f.write(f"    t.unique_key_count = {uk_count},\n")
        f.write(f"    t.updated_at = datetime();\n\n")

def write_relationships(f, relationships):
    """写入关系创建语句"""
    f.write("// 创建关系\n\n")
    
    # 按置信度排序
    sorted_rels = sorted(relationships, 
                        key=lambda x: x['metrics']['composite_score'], 
                        reverse=True)
    
    for rel in sorted_rels:
        if rel['relationship_type'] == 'composite':
            write_composite_relationship(f, rel)
        else:
            write_single_relationship(f, rel)

def write_single_relationship(f, rel):
    """写入单列关系"""
    f.write(f"// 关系: {rel['from_table']} -> {rel['to_table']}\n")
    f.write(f"MATCH (from:Table {{name: '{rel['from_table']}'}})\n")
    f.write(f"MATCH (to:Table {{name: '{rel['to_table']}'}})\n")
    f.write(f"MERGE (from)-[r:JOIN]->(to)\n")
    
    metrics = rel['metrics']
    f.write(f"SET r.from_fields = ['{rel['from_column']}'],\n")
    f.write(f"    r.to_fields = ['{rel['to_column']}'],\n")
    f.write(f"    r.join_type = 'LEFT',\n")
    f.write(f"    r.relationship_type = 'inferred',\n")
    f.write(f"    r.inclusion_rate = {metrics['inclusion_rate']},\n")
    f.write(f"    r.jaccard_index = {metrics['jaccard_index']},\n")
    f.write(f"    r.uniqueness_score = {metrics['uniqueness_score']},\n")
    f.write(f"    r.name_similarity = {metrics['name_similarity']},\n")
    f.write(f"    r.type_compatibility = {metrics['type_compatibility']},\n")
    f.write(f"    r.composite_score = {metrics['composite_score']},\n")
    f.write(f"    r.confidence_level = '{metrics['confidence_level']}',\n")
    f.write(f"    r.source = 'auto_detected',\n")
    f.write(f"    r.verified = {str(rel['verified']).lower()},\n")
    f.write(f"    r.discovered_at = datetime(),\n")
    f.write(f"    r.label = '{rel['from_column']} = {rel['to_column']}';\n\n")

def write_composite_relationship(f, rel):
    """写入复合键关系"""
    f.write(f"// 关系: {rel['from_table']} -> {rel['to_table']}\n")
    f.write(f"MATCH (from:Table {{name: '{rel['from_table']}'}})\n")
    f.write(f"MATCH (to:Table {{name: '{rel['to_table']}'}})\n")
    f.write(f"MERGE (from)-[r:COMPOSITE_JOIN]->(to)\n")
    
    from_fields = "', '".join(rel['from_columns'])
    to_fields = "', '".join(rel['to_columns'])
    
    metrics = rel['metrics']
    f.write(f"SET r.from_fields = ['{from_fields}'],\n")
    f.write(f"    r.to_fields = ['{to_fields}'],\n")
    f.write(f"    r.join_type = 'LEFT',\n")
    f.write(f"    r.relationship_type = 'composite',\n")
    f.write(f"    r.inclusion_rate = {metrics['inclusion_rate']},\n")
    f.write(f"    r.jaccard_index = {metrics['jaccard_index']},\n")
    f.write(f"    r.uniqueness_score = {metrics['uniqueness_score']},\n")
    f.write(f"    r.name_similarity = {metrics['name_similarity']},\n")
    f.write(f"    r.type_compatibility = {metrics['type_compatibility']},\n")
    f.write(f"    r.composite_score = {metrics['composite_score']},\n")
    f.write(f"    r.confidence_level = '{metrics['confidence_level']}',\n")
    f.write(f"    r.source = 'auto_detected',\n")
    f.write(f"    r.verified = {str(rel['verified']).lower()},\n")
    f.write(f"    r.discovered_at = datetime(),\n")
    f.write(f"    r.from_source = '{rel['from_source']}',\n")
    f.write(f"    r.to_source = '{rel['to_source']}',\n")
    
    # column_pairs 序列化为 JSON 字符串
    import json
    column_pairs_json = json.dumps(rel['column_pairs'])
    f.write(f"    r.column_pairs = '{column_pairs_json}',\n")
    
    # label
    label_parts = [f"{fc} = {tc}" for fc, tc in zip(rel['from_columns'], rel['to_columns'])]
    label = " AND ".join(label_parts)
    f.write(f"    r.label = '{label}';\n\n")
```

## 4. 配置参数

### 4.1 候选生成配置

```yaml
discovery:
  # 名称相似度阈值
  min_name_similarity: 0.6
  
  # 类型兼容性阈值
  min_type_compatibility: 0.5
  
  # 唯一性阈值（目标列）
  min_uniqueness: 0.95
  
  # 复合键配置
  composite:
    enabled: true
    max_columns: 3
    min_candidates: 2
    weak_similarity_range: [0.5, 0.8]
```

### 4.2 采样配置

```yaml
sampling:
  # 采样比例（1% = 0.01）
  ratio: 0.01
  
  # 最大采样行数
  max_rows: 10000
  
  # 最小采样行数
  min_rows: 100
  
  # 采样方法（random/tablesample）
  method: 'tablesample'
```

### 4.3 评分权重配置

```yaml
weights:
  inclusion_rate: 0.30      # 包含率
  jaccard_index: 0.15       # Jaccard 系数
  uniqueness: 0.10          # 唯一度
  name_similarity: 0.20     # 名称相似度
  type_compatibility: 0.20  # 类型兼容性
  name_complexity: 0.05     # 名称复杂度
```

### 4.4 决策阈值配置

```yaml
decision:
  # 自动接受阈值（高置信度）
  auto_accept: 0.90
  
  # 需要审查阈值（中置信度）
  review_required: 0.80
  
  # 拒绝阈值（低置信度）
  reject: 0.80
  
  # 是否输出低置信度关系
  include_low_confidence: false
```

## 5. 数据结构设计

### 5.1 关系候选对象

```python
@dataclass
class RelationshipCandidate:
    """关系候选"""
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    name_similarity: float
    type_compatibility: float
    name_complexity: float
    candidate_source: str  # 'deterministic' 或 'llm_enhanced'
```

### 5.2 关系度量对象

```python
@dataclass
class RelationshipMetrics:
    """关系度量指标"""
    candidate: RelationshipCandidate
    inclusion_rate: float
    jaccard_index: float
    uniqueness_score: float
    sample_hit_rate: float
    composite_score: float
    confidence_level: str  # 'high', 'medium', 'low'
```

### 5.3 关系对象

```python
@dataclass
class Relationship:
    """发现的关系"""
    from_table: str
    from_columns: List[str]
    to_table: str
    to_columns: List[str]
    relationship_type: str  # 'inferred', 'composite'
    join_type: str  # 'LEFT', 'INNER'
    metrics: RelationshipMetrics
    source: str  # 'auto_detected', 'foreign_key'
    verified: bool
    discovered_at: datetime
    
    # 复合键专用
    from_source: Optional[str] = None  # 'foreign_key', 'primary_key', 'unique_key'
    to_source: Optional[str] = None
    column_pairs: Optional[List[Dict]] = None
```

## 6. 实现步骤

### 6.1 第一阶段：元数据加载（Week 1）

**任务清单：**
1. ✅ 设计 JSON 解析器
2. ✅ 实现表索引构建
3. ✅ 实现列画像提取
4. ✅ 实现逻辑主键识别

**交付物：**
- `metadata_loader.py`：元数据加载器
- `index_builder.py`：索引构建器
- 单元测试

### 6.2 第二阶段：候选关系生成（Week 2）

**任务清单：**
1. ✅ 实现列对筛选逻辑
2. ✅ 实现名称相似度计算
3. ✅ 实现类型兼容性检查
4. ✅ 实现单列候选生成
5. ✅ 实现复合键候选生成

**交付物：**
- `candidate_generator.py`：候选生成器
- `similarity_calculator.py`：相似度计算器
- 单元测试

### 6.3 第三阶段：关系验证与评分（Week 3）

**任务清单：**
1. ✅ 实现数据采样模块
2. ✅ 实现度量计算器
3. ✅ 实现综合评分逻辑
4. ✅ 实现置信度分级

**交付物：**
- `data_sampler.py`：数据采样器
- `metrics_calculator.py`：度量计算器
- `scorer.py`：评分器
- 集成测试

### 6.4 第四阶段：Cypher 生成（Week 4）

**任务清单：**
1. ✅ 实现表节点生成器
2. ✅ 实现关系语句生成器
3. ✅ 实现文件输出器
4. ✅ 实现统计报告生成

**交付物：**
- `cypher_generator.py`：Cypher 生成器
- `file_writer.py`：文件写入器
- 端到端测试

## 7. 质量保证

### 7.1 准确性验证

**验证策略：**
1. **样本验证**：对生成的关系进行随机抽样，执行实际 JOIN 查询验证
2. **人工审查**：中等置信度关系需要人工确认
3. **统计验证**：包含率和 Jaccard 系数应与实际数据一致

### 7.2 性能优化

**优化点：**
1. **采样优化**：使用 `TABLESAMPLE` 减少全表扫描
2. **并发处理**：候选生成和验证可并行化
3. **缓存机制**：缓存已计算的相似度和度量
4. **索引利用**：利用 JSON 中的统计信息，减少数据库访问

### 7.3 错误处理

**异常场景：**
1. JSON 文件损坏或缺失
2. 数据库连接失败
3. 采样数据不足
4. Cypher 语法错误

**处理策略：**
- 日志记录详细错误信息
- 优雅降级（跳过问题表，继续处理其他表）
- 生成错误报告文件

## 8. 输出示例

### 8.1 完整 Cypher 文件示例

参考：`relationships_0af644bd-a559-40ee-883c-cd4b692d5bc5_20250922_103153.cypher`

### 8.2 统计报告示例

```
// ================================================
// 总关系数: 27
// 高置信度: 23 (85.2%)
// 中置信度: 4 (14.8%)
// 低置信度: 0 (0.0%)
// 平均包含率: 100.00%
// 平均 Jaccard 系数: 96.30%
// 平均唯一度: 58.70%
// 平均置信度: 94.81%
// ================================================
// 
// 关系类型分布:
// - inferred: 25 (92.6%)
// - composite: 2 (7.4%)
//
// 处理统计:
// - 分析表数: 7
// - 生成候选数: 142
// - 通过验证: 27
// - 执行时间: 12.5s
// ================================================
```

## 9. 与 Step 1/2 的集成

### 9.1 依赖 Step 1（DDL 生成）

**使用的信息：**
- 表注释（comment）
- 字段注释（column.comment）
- 主键信息（primary_keys）
- 外键信息（foreign_keys）
- 唯一约束（unique_constraints）
- 索引信息（indexes）

### 9.2 依赖 Step 2（JSON 画像）

**使用的信息：**
- 表画像（table_profile）
  - 表类型（table_category）
  - 逻辑主键（key_columns.logical_keys）
  
- 字段画像（column_profiles）
  - 语义角色（semantic_role）
  - 结构标记（structure_flags）
  - 标识符信息（identifier_info）
  
- 统计信息（statistics）
  - 唯一性（uniqueness）
  - 空值率（null_rate）
  - 基数（unique_count）
  - 值分布（value_distribution）

## 10. 后续扩展

### 10.1 LLM 增强（可选）

**触发条件：**
- 名称相似度在临界区间 [0.5, 0.8]
- 类型兼容性较高 >= 0.8

**增强内容：**
- 语义相似度分析
- 业务规则推理
- 关系合理性评估

### 10.2 交互式审查工具

**功能：**
- Web 界面展示发现的关系
- 人工确认/拒绝关系
- 添加自定义关系
- 导出审查后的 Cypher 文件

### 10.3 增量更新

**功能：**
- 对比历史关系
- 仅生成新增/变更的关系
- 版本管理和追踪

## 11. 总结

本模块是 MetaWeave 平台的核心组件，通过结合元数据分析和数据实际验证，能够自动发现表之间的逻辑关联关系。生成的 Cypher 文件可直接导入 Neo4j，为后续的数据血缘分析、影响分析和智能查询提供基础。

**核心优势：**
1. ✅ **自动化**：无需人工定义关系
2. ✅ **准确性**：多维度评分确保高置信度
3. ✅ **可扩展**：支持复合键和自定义规则
4. ✅ **可执行**：生成标准 Neo4j Cypher 语句
5. ✅ **可追溯**：保留完整的发现过程和度量信息

