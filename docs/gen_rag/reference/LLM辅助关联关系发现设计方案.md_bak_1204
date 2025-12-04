# LLM 辅助关联关系发现设计方案

## 1. 需求概述

### 1.1 背景

当前关联关系发现流程依赖复杂的启发式规则（语义分析、逻辑主键推断等），引入 LLM 可以简化流程并提高准确性。

### 1.2 目标

1. 新增 `json_llm` 步骤：生成简化版 JSON 数据画像
2. 新增 `rel_llm` 步骤：使用 LLM 发现候选关联关系，复用现有评分逻辑
3. 调整 CQL 生成：根据基数决定箭头方向

### 1.3 命令行接口

```bash
# 现有步骤（保持不变）
python -m src.metaweave.cli.main metadata --step ddl
python -m src.metaweave.cli.main metadata --step json
python -m src.metaweave.cli.main metadata --step rel

# 新增步骤
python -m src.metaweave.cli.main metadata --step json_llm  # 简化版 JSON
python -m src.metaweave.cli.main metadata --step rel_llm   # LLM 辅助关联发现

# 后续步骤（保持不变）
python -m src.metaweave.cli.main metadata --step cql
python -m src.metaweave.cli.main load --type cql --clean
```

### 1.4 rel 与 rel_llm 共存策略

#### 1.4.1 覆盖语义

`--step rel` 和 `--step rel_llm` **写入同一个 `rel/` 目录**，输出文件名相同（如 `relationships_global.json`）。

- **谁最后执行，谁的结果生效**
- `--step cql` 只读取 `rel/` 目录，不区分来源

典型场景：

| 执行顺序 | `rel/` 目录内容 | `cql` 使用的数据 |
|----------|-----------------|------------------|
| `rel` → `cql` | 启发式规则结果 | 启发式规则结果 |
| `rel_llm` → `cql` | LLM 辅助结果 | LLM 辅助结果 |
| `rel` → `rel_llm` → `cql` | LLM 辅助结果（覆盖） | LLM 辅助结果 |
| `rel_llm` → `rel` → `cql` | 启发式规则结果（覆盖） | 启发式规则结果 |

#### 1.4.2 调试与回滚

如需**禁用 LLM 结果**，只需重新执行旧流程：

```bash
# 回滚到启发式规则结果
python -m src.metaweave.cli.main metadata --step rel
python -m src.metaweave.cli.main metadata --step cql
```

如需**对比两种结果**，可手动备份：

```bash
# 备份 LLM 结果
cp -r output/metaweave/metadata/rel output/metaweave/metadata/rel_llm_backup

# 重新生成启发式结果
python -m src.metaweave.cli.main metadata --step rel

# 对比差异
diff rel_llm_backup/relationships_global.json rel/relationships_global.json
```

#### 1.4.3 推荐工作流

**生产环境**（LLM 辅助流程）：
```bash
ddl → json_llm → rel_llm → cql → load
```

**调试/回退**（传统流程）：
```bash
ddl → json → rel → cql → load
```

**完整流程**（两条路径都执行，便于对比）：
```bash
ddl → json → rel → (备份) → json_llm → rel_llm → cql → load
```

---

## 2. 整体流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LLM 辅助流程                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────┐       │
│  │ step    │     │ step        │     │ step        │     │ step    │       │
│  │ ddl     │────►│ json_llm    │────►│ rel_llm     │────►│ cql     │       │
│  └─────────┘     └─────────────┘     └─────────────┘     └─────────┘       │
│       │                │                    │                  │            │
│       ▼                ▼                    ▼                  ▼            │
│   ddl/*.sql      json_llm/*.json      rel/*.json         cql/*.cql        │
│   (物理DDL)       (简化画像)          (关联关系)          (图数据)          │
│                        │                    │                               │
│                        │    ┌───────────────┘                               │
│                        │    │                                               │
│                        ▼    ▼                                               │
│                   ┌─────────────┐                                           │
│                   │    LLM      │                                           │
│                   │  两两组合    │                                           │
│                   │  候选发现    │                                           │
│                   └─────────────┘                                           │
│                          │                                                  │
│                          ▼                                                  │
│                   ┌─────────────┐                                           │
│                   │  评分模块   │  ◄── 复用现有 RelationshipScorer          │
│                   │  (采样计算)  │                                           │
│                   └─────────────┘                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. json_llm 步骤设计

> **重要说明**：`json_llm` 完全独立于 `json`，不依赖 `json/` 目录的文件。它直接从 DDL 和数据库重新生成，而非从 `json/` 裁剪。这是设计取舍：虽然会重复部分 profiler 工作，但保证了两条流程的独立性。

### 3.1 输出内容

简化版 JSON 数据画像，包含：

| 内容 | 保留 | 说明 |
|------|------|------|
| 表基本信息 | ✅ | schema, table_name, comment |
| 列定义 | ✅ | column_name, data_type, is_nullable, column_default, comment |
| 物理约束 | ✅ | primary_key, foreign_keys, indexes |
| 基础统计 | ✅ | sample_count, unique_count, null_count, null_rate, uniqueness |
| 样例数据 | ✅ | sample_records |
| 语义分析 | ❌ | semantic_role, semantic_confidence |
| 逻辑主键 | ❌ | candidate_primary_keys |
| 维度表信息 | ❌ | dim_table_info, fact_table_info |

### 3.2 输出目录

```
output/metaweave/metadata/
├── ddl/                    # DDL 文件（现有）
├── json/                   # 完整 JSON 画像（现有）
├── json_llm/               # 简化 JSON 画像（新增）
│   ├── public.dim_product.json
│   ├── public.fact_sales.json
│   └── ...
└── rel/                    # 关联关系（现有）
```

### 3.3 JSON Schema（简化版）

```json
{
  "table_info": {
    "schema": "public",
    "table_name": "fact_store_sales_day",
    "comment": "门店日销售事实表",
    "row_count": 10000
  },
  "columns": {
    "sales_id": {
      "column_name": "sales_id",
      "ordinal_position": 1,
      "data_type": "integer",
      "is_nullable": false,
      "column_default": null,
      "comment": "销售记录ID",
      "statistics": {
        "sample_count": 1000,
        "unique_count": 1000,
        "null_count": 0,
        "null_rate": 0.0,
        "uniqueness": 1.0
      }
    }
  },
  "constraints": {
    "primary_key": {
      "columns": ["sales_id"],
      "constraint_name": "fact_store_sales_day_pkey"
    },
    "foreign_keys": [
      {
        "columns": ["product_type_id"],
        "references": {
          "schema": "public",
          "table": "dim_product_type",
          "columns": ["product_type_id"]
        },
        "constraint_name": "fk_product_type"
      }
    ],
    "indexes": []
  },
  "sample_records": {
    "sample_method": "random",
    "sample_size": 5,
    "total_rows": 10000,
    "records": [
      {"sales_id": 1, "product_type_id": 101, "amount": 100.00}
    ]
  }
}
```

#### 3.3.1 Schema 补充说明

| 字段 | 类型 | 必需/可选 | 说明 |
|------|------|-----------|------|
| `table_info` | object | **必需** | 表基本信息，始终存在 |
| `columns` | **dict** | **必需** | 列定义，key 为列名，value 为列信息对象 |
| `columns.*.statistics` | object | **可选** | 采样权限不足或出错时可能缺失，此时为 `null` |
| `constraints` | object | **必需** | 约束信息，无约束时相应字段为空数组或 `null` |
| `constraints.primary_key` | object | **可选** | 无主键时为 `null` |
| `constraints.foreign_keys` | array | **必需** | 无外键时为空数组 `[]` |
| `constraints.indexes` | array | **必需** | 无索引时为空数组 `[]` |
| `sample_records` | object | **可选** | 采样权限不足或出错时可能缺失，此时为 `null` |
| `sample_records.records` | array | **可选** | 采样失败时为空数组 `[]` |

**实现注意**：
- `LLMRelationshipDiscovery` 在解析 `json_llm` 时，需对 `statistics` 和 `sample_records` 做 null-safe 处理
- 缺失统计信息时，LLM 仍可根据字段名、类型、注释进行关联判断

### 3.4 实现方案

新增 `LLMJsonGenerator` 类，复用现有的：
- `MetadataExtractor`：提取 DDL 信息
- `get_column_statistics`：计算基础统计
- 采样逻辑：获取 sample_records

```python
# src/metaweave/core/metadata/llm_json_generator.py

class LLMJsonGenerator:
    """生成简化版 JSON 数据画像（供 LLM 使用）"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.extractor = MetadataExtractor(...)
        
    def generate(self, table_name: str) -> Dict:
        """生成单表的简化 JSON"""
        # 1. 提取 DDL 信息
        # 2. 计算基础统计
        # 3. 获取样例数据
        # 4. 组装输出（不含语义分析、逻辑主键等）
        pass
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
│  4. 逐对调用 LLM，获取候选关联                                  │
│                    │                              │             │
│                    ▼                              │             │
│  5. 解析 LLM 返回，过滤已有物理外键                             │
│                    │                              │             │
│                    ▼                              │             │
│  6. 调用 RelationshipScorer 评分                                │
│                    │                              │             │
│                    ▼                              │             │
│  7. 合并结果 ◄─────────────────────────────────────┘            │
│                    │                                            │
│                    ▼                                            │
│  8. 输出 rel/*.json（格式与现有一致）                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 LLM 调用策略

**方案**：两两组合，全部调用 LLM

```python
from itertools import combinations

tables = ["dim_product", "dim_region", "fact_sales", ...]
table_pairs = list(combinations(tables, 2))
# 10 个表 → 45 对
# 15 个表 → 105 对
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

## 输出要求
返回 JSON 格式，包含所有可能的关联关系。如果没有关联，返回空数组。

注意：
- 多列关联时，columns 数组中的字段顺序表示对应关系
- 不需要判断方向（哪个是源表/目标表），只需列出关联字段
- 请尽量识别从维度表/实体表到事实表/流水表的关联关系
- 为每个关联提供置信度评估（high/medium/low）

```json
{
  "relationships": [
    {
      "table1": {
        "schema": "public",
        "table": "表名",
        "columns": ["字段1", "字段2"]
      },
      "table2": {
        "schema": "public", 
        "table": "表名",
        "columns": ["字段1", "字段2"]
      },
      "confidence": "high",
      "reasoning": "关联理由说明"
    }
  ]
}
```
"""
```

### 4.4 LLM 返回格式

```json
{
  "relationships": [
    {
      "table1": {
        "schema": "public",
        "table": "maintenance_work_order",
        "columns": ["equipment_id", "config_version"]
      },
      "table2": {
        "schema": "public",
        "table": "equipment_config",
        "columns": ["equipment_id", "config_version"]
      },
      "confidence": "high",
      "reasoning": "复合字段名完全匹配，且 equipment_config 中这两个字段构成主键"
    }
  ]
}
```

#### 4.4.1 confidence 字段说明

| 值 | 含义 | 典型场景 |
|----|------|----------|
| `high` | 高置信度 | 字段名完全相同 + 类型兼容 + 注释语义一致 |
| `medium` | 中置信度 | 字段名相似或部分匹配 |
| `low` | 低置信度 | 仅根据注释或样例数据推测 |

无关联时：
```json
{
  "relationships": []
}
```

### 4.5 候选解析与评分

```python
# src/metaweave/core/relationships/llm_relationship_discovery.py

class LLMRelationshipDiscovery:
    """LLM 辅助关联关系发现"""
    
    def __init__(self, config: Dict, db_connector: DatabaseConnector):
        self.config = config
        self.db_connector = db_connector
        self.scorer = RelationshipScorer(config, db_connector)  # 复用现有评分
        self.llm_service = LLMService(config)
        
    def discover(self, json_llm_dir: str) -> List[Relation]:
        """发现关联关系"""
        # 1. 加载所有 json_llm 文件
        tables = self._load_all_tables(json_llm_dir)
        
        # 2. 提取物理外键（直通）
        fk_relations = self._extract_foreign_keys(tables)
        
        # 3. 两两组合调用 LLM
        candidates = []
        for table1, table2 in combinations(tables, 2):
            llm_candidates = self._call_llm(table1, table2)
            candidates.extend(llm_candidates)
        
        # 4. 过滤已有物理外键
        candidates = self._filter_existing_fks(candidates, fk_relations)
        
        # 5. 评分（复用 RelationshipScorer）
        scored_relations = self._score_candidates(candidates)
        
        # 6. 合并结果
        return fk_relations + scored_relations
        
    def _call_llm(self, table1: Dict, table2: Dict) -> List[Dict]:
        """调用 LLM 获取候选关联"""
        prompt = RELATIONSHIP_DISCOVERY_PROMPT.format(
            table1_name=table1["table_info"]["table_name"],
            table1_json=json.dumps(table1, ensure_ascii=False, indent=2),
            table2_name=table2["table_info"]["table_name"],
            table2_json=json.dumps(table2, ensure_ascii=False, indent=2),
        )
        response = self.llm_service.call(prompt)
        return self._parse_llm_response(response)
        
    def _score_candidates(self, candidates: List[Dict]) -> List[Relation]:
        """对候选关联进行评分"""
        results = []
        for candidate in candidates:
            # 转换为 scorer 需要的格式
            # 调用 scorer.score_candidates() 或 scorer._calculate_scores()
            # ...
            pass
        return results
```

### 4.6 方向与基数确定

LLM 返回的候选不包含方向信息。方向和基数在评分后确定。

#### 4.6.1 方向规则

| 来源 | 规则 | 说明 |
|------|------|------|
| **物理外键** | FK 表 → PK 表 | 固定方向，不翻转 |
| **推断关系 (1:N / N:1)** | N 侧 → 1 侧 | 箭头指向唯一性高的一侧 |
| **推断关系 (M:N)** | 大表 → 小表 | 按 row_count 比较 |
| **推断关系 (1:1)** | 保持原样 | 任意方向 |

#### 4.6.2 source_type 字段

在 rel JSON 输出中增加 `source_type` 字段，用于区分关系来源：

| source_type | 含义 |
|-------------|------|
| `physical_fk` | 物理外键约束（DDL 定义） |
| `llm_inferred` | LLM 推断 + 评分验证 |

#### 4.6.3 伪代码

```python
def _determine_direction(
    self, 
    table1: str, cols1: List[str], 
    table2: str, cols2: List[str],
    table1_row_count: int,
    table2_row_count: int,
) -> Tuple[str, str, str, str]:
    """确定关联方向和基数
    
    Returns:
        (source_table, target_table, cardinality, source_type)
    """
    # 计算基数
    cardinality = self._calculate_cardinality(table1, cols1, table2, cols2)
    
    if cardinality == "N:1":
        # table1 是 N 侧（源），table2 是 1 侧（目标）
        return (table1, table2, "N:1", "llm_inferred")
    
    elif cardinality == "1:N":
        # 翻转：table2 是 N 侧（源），table1 是 1 侧（目标）
        return (table2, table1, "N:1", "llm_inferred")
    
    elif cardinality == "M:N":
        # 大表 → 小表
        if table1_row_count >= table2_row_count:
            return (table1, table2, "M:N", "llm_inferred")
        else:
            return (table2, table1, "M:N", "llm_inferred")
    
    else:  # 1:1
        # 任意方向，保持原样
        return (table1, table2, "1:1", "llm_inferred")


def _process_physical_fk(self, fk: Dict) -> Tuple[str, str, str, str]:
    """处理物理外键（方向固定：FK → PK）"""
    return (
        fk["fk_table"],      # source: 外键表
        fk["pk_table"],      # target: 主键表
        fk["cardinality"],   # 基于 uniqueness 静态推断
        "physical_fk"        # 标记为物理外键
    )
```

#### 4.6.4 物理外键的 cardinality 推断

对于物理外键，`cardinality` 在**提取外键阶段**（`json_llm` 步骤加载 DDL 时）静态推断，无需采样计算：

| 条件 | 推断结果 |
|------|----------|
| PK 表的关联列是主键或唯一约束 + FK 表的关联列无唯一约束 | `N:1` |
| 两侧关联列都有唯一约束 | `1:1` |
| FK 表的关联列有唯一约束 + PK 表的关联列无唯一约束 | `1:N`（归一化为 `N:1`） |
| 两侧都无唯一约束（罕见） | `M:N` |

**推断依据**：
- 优先使用 DDL 中的物理约束（`PRIMARY KEY`、`UNIQUE`）
- 如物理约束不足，参考 `json_llm` 中的 `statistics.uniqueness`（uniqueness ≈ 1.0 视为唯一）

> 此逻辑复用现有 `MetadataRepository._infer_cardinality` 方法。

---

## 5. CQL 生成调整

### 5.1 方向决策规则

CQL 中箭头方向的决策优先级：

```
┌─────────────────────────────────────────────────────────────┐
│                    CQL 箭头方向决策                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  读取 rel JSON 中的 source_type                             │
│                    │                                        │
│                    ▼                                        │
│  source_type == "physical_fk"?                              │
│         │                    │                              │
│        Yes                  No                              │
│         │                    │                              │
│         ▼                    ▼                              │
│  ┌────────────┐      ┌────────────────────┐                │
│  │ 固定方向    │      │ 按 rel JSON 中的    │                │
│  │ FK → PK    │      │ source/target 输出  │                │
│  │ (不翻转)   │      │ (已在 rel_llm 确定) │                │
│  └────────────┘      └────────────────────┘                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**说明**：
- 物理外键（`source_type == "physical_fk"`）：方向固定为 FK → PK，不受 cardinality 影响
- LLM 推断关系（`source_type == "llm_inferred"`）：方向已在 `rel_llm` 步骤中根据 cardinality + row_count 确定，CQL 生成时直接使用

### 5.2 方向规则汇总

| source_type | cardinality | CQL 箭头方向 |
|-------------|-------------|--------------|
| `physical_fk` | 任意 | FK 表 → PK 表（固定） |
| `llm_inferred` | N:1 | N 侧 → 1 侧 |
| `llm_inferred` | M:N | 大表 → 小表 |
| `llm_inferred` | 1:1 | 保持原样 |

> **重要说明**：在 rel JSON 中，**一对多关系统一规范为 `cardinality = "N:1"`**。
> 
> - `_calculate_cardinality` 可能返回 `1:N`（当 table1 是 1 侧时）
> - 但在 `_determine_direction` 中会翻转方向并归一化为 `N:1`
> - 因此 **rel JSON 中不会出现 `cardinality = "1:N"`**
> - `source_table` 始终为 N 侧，`target_table` 始终为 1 侧

### 5.3 修改方案

修改 `src/metaweave/core/cql_generator/writer.py`：

```python
def _generate_relationship_cql(self, rel: Dict) -> str:
    """生成关系 CQL
    
    方向决策：
    1. physical_fk: 使用 rel JSON 中的 source/target（FK → PK）
    2. llm_inferred: 使用 rel JSON 中的 source/target（已在 rel_llm 确定）
    
    注意：rel_llm 步骤已根据 cardinality + row_count 确定了正确的方向，
    CQL 生成阶段直接使用，无需再次翻转。
    """
    source_type = rel.get("source_type", "llm_inferred")
    
    # 统一使用 rel JSON 中的 source/target
    # （物理外键和 LLM 推断都已在上游确定好方向）
    from_table = rel["source_table"]
    to_table = rel["target_table"]
    from_columns = rel["source_columns"]
    to_columns = rel["target_columns"]
    cardinality = rel.get("cardinality", "N:1")
    
    # 生成 CQL
    # MATCH (a:Table {name: from_table}), (b:Table {name: to_table})
    # CREATE (a)-[:RELATES_TO {cardinality: cardinality, ...}]->(b)
    ...
```

### 5.4 rel JSON 输出示例

```json
{
  "relationships": [
    {
      "source_table": "public.fact_store_sales_day",
      "target_table": "public.dim_product_type",
      "source_columns": ["product_type_id"],
      "target_columns": ["product_type_id"],
      "cardinality": "N:1",
      "source_type": "physical_fk",
      "discovery_method": "foreign_key_constraint"
    },
    {
      "source_table": "public.maintenance_work_order",
      "target_table": "public.equipment_config",
      "source_columns": ["equipment_id", "config_version"],
      "target_columns": ["equipment_id", "config_version"],
      "cardinality": "N:1",
      "source_type": "llm_inferred",
      "llm_confidence": "high",
      "discovery_method": "llm_relationship_discovery"
    }
  ]
}
```

#### 5.4.1 字段说明

| 字段 | 必需 | 说明 |
|------|------|------|
| `source_type` | ✅ | `physical_fk` 或 `llm_inferred` |
| `llm_confidence` | 仅 `llm_inferred` | LLM 返回的置信度（high/medium/low） |
| `discovery_method` | ✅ | 发现方法标识 |

---

## 6. 配置设计

### 6.1 metadata_config.yaml 新增配置

```yaml
# LLM 辅助关联发现配置
llm_relationship_discovery:
  enabled: true
  
  # LLM 调用配置
  llm:
    model: "gpt-4"        # 或其他模型
    temperature: 0.1      # 低温度，保证输出稳定
    timeout: 60           # 单次调用超时（秒）
    retry_times: 3        # 失败重试次数
    
  # json_llm 生成配置
  json_llm:
    max_sample_rows: 5    # 样例数据最大行数（控制 prompt 长度）
    
  # 评分阈值（复用现有配置）
  scoring:
    min_total_score: 0.6
```

#### 6.1.1 max_sample_rows 说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `json_llm.max_sample_rows` | 5 | `json_llm` 中 `sample_records.records` 的最大行数 |

**应用位置**：`LLMJsonGenerator` 在生成 `sample_records` 时读取此配置

**处理逻辑**：
```python
# LLMJsonGenerator._generate_sample_records()
max_rows = self.config.get("json_llm", {}).get("max_sample_rows", 5)
records = self._sample_from_db(table_name, limit=max_rows)
```

**设计考量**：
- 样例数据仅供 LLM 参考值域匹配，不需要大量行数
- 控制 prompt 长度，避免超出 LLM 上下文限制
- 减少 token 消耗

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
| `src/metaweave/cli/main.py` | 新增 `json_llm`, `rel_llm` 步骤 |
| `src/metaweave/core/metadata/generator.py` | 添加 `json_llm` 步骤调用 |
| `src/metaweave/core/relationships/manager.py` | 添加 `rel_llm` 步骤调用 |
| `src/metaweave/core/cql_generator/writer.py` | 根据基数决定箭头方向 |
| `configs/metaweave/metadata_config.yaml` | 新增 LLM 配置 |

---

## 8. 测试计划

### 8.1 单元测试

| 测试文件 | 测试内容 |
|----------|----------|
| `test_llm_json_generator.py` | 简化版 JSON 生成 |
| `test_llm_relationship_discovery.py` | LLM 候选解析、评分集成 |
| `test_cql_writer_direction.py` | CQL 箭头方向 |

### 8.2 集成测试

```bash
# 完整流程测试
python -m src.metaweave.cli.main metadata --step ddl
python -m src.metaweave.cli.main metadata --step json_llm
python -m src.metaweave.cli.main metadata --step rel_llm
python -m src.metaweave.cli.main metadata --step cql
python -m src.metaweave.cli.main load --type cql --clean
```

---

## 9. 风险与应对

| 风险 | 应对措施 |
|------|----------|
| LLM 输出格式不稳定 | JSON Schema 校验 + 重试机制（最多 `retry_times` 次） |
| LLM 调用连续失败 | 跳过该表对，记录警告日志，整批流程继续执行（见下方说明） |
| LLM 响应慢 | 超时控制（`timeout` 秒） |
| 新旧流程不兼容 | 保持 rel JSON 格式一致 |

### 9.1 LLM 调用失败处理策略

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
  记录警告日志：
  "LLM call failed for pair (table1, table2) after 3 retries, skipping"
     │
     ▼
  跳过该表对，继续处理下一对
```

**关键行为**：
- 单个表对失败 **不会中断** 整批流程
- 失败的表对会被跳过，不会产生候选关联
- 最终输出的 `rel/*.json` 中只包含成功处理的关联关系
- 日志中会记录所有跳过的表对，便于排查

---

## 10. 里程碑

| 阶段 | 内容 | 预计工作量 |
|------|------|------------|
| M1 | `json_llm` 步骤实现 | 1 天 |
| M2 | `rel_llm` 步骤实现（LLM 调用 + 解析） | 2 天 |
| M3 | 评分集成 + 方向确定 | 1 天 |
| M4 | CQL 生成调整 | 0.5 天 |
| M5 | 测试 + 文档 | 1 天 |

**总计**：约 5.5 天

---

## 附录 A：现有评分逻辑复用

当前 `RelationshipScorer` 的四个评分项：

1. **inclusion_rate**：源表值在目标表中的包含率
2. **jaccard_index**：源表和目标表值集合的 Jaccard 相似度
3. **uniqueness_score**：目标表字段的唯一性
4. **naming_score**：字段命名相似度

`rel_llm` 步骤将复用这些评分逻辑，只是候选来源从启发式规则变为 LLM 建议。

