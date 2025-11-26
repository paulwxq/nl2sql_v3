# 关联字段查找算法详解

## 概述

DB2Graph项目中的关联字段查找算法是一个多阶段、多维度的智能关系发现系统。该算法结合了确定性规则匹配以及可选的嵌入/LLM语义增强（默认仅启用确定性 + 嵌入），能够从数据库元数据和实际数据中自动发现表之间的潜在关联关系。

## 1. 主键、外键和索引的特殊处理

### 1.1 现有外键的处理
- **直通转换**：已存在的外键约束被直接转换为高置信度关系（confidence=1.0）
- **排除机制**：在候选生成阶段，已存在的外键关系会被排除，避免重复分析
- **关系类型**：外键关系被标记为`foreign_key`类型，具有最高优先级

### 1.2 主键和唯一键的处理
- **目标列限制**：在单列关系候选生成中，目标列（to_column）必须满足以下条件之一：
  - 是主键（`is_primary_key = true`）
  - 是唯一键（`is_unique = true`）
  - 拥有索引标记（`has_index = true`），包括复合索引拆分后的单列索引
  - 具有高唯一性（`uniqueness >= 0.95`）
- **来源标记**：候选对象仅记录 `from_source`/`to_source` 是否来自主键（例如 `primary_key`），以便决策阶段执行 PK↔PK 分数封顶或在报告中展示来源；不会直接对名称相似度做加权。

### 1.3 索引的处理
- **复合键阈值配置**：新增 `discovery.composite` 节点用于控制复合主键/索引/外键的候选生成，支持 `min_name_similarity` 与 `min_type_compatibility` 阈值、最大列数、来源控制以及是否允许跨来源组合。
- **显式采集**：元数据阶段会抓取所有单列与复合索引并写入 `TableMetadata.indexes`，列对象同步标记 `has_index`。
- **候选优先级**：拥有索引的列（含复合索引拆分后的单列）在候选/目标筛选时自动视为合格，即便不是 PK/UK 也能进入评估。
- **性能与准确性**：索引既用于后续采样的查询优化，也作为结构提示配合唯一性阈值降低误判。

### 1.4 字段注释的参与
目前算法**暂未**使用字段注释信息进行关系判断，主要依赖以下信息：
- 字段名称的语义相似度
- 数据类型兼容性
- 实际数据样本的匹配度
- 数据分布特征（唯一性、空值率等）

## 2. 算法执行的阶段和步骤

### 2.1 第一阶段：元数据读取和预处理
```
步骤1: 读取数据库元数据
├── 获取表结构信息（列、数据类型、约束）
├── 提取现有外键关系
├── 识别主键和唯一键
└── 生成表统计信息

步骤2: 数据采样和画像分析
├── 对每个表进行数据采样（默认1%或最多10000行）
├── 计算列的数据画像（唯一性、空值率、基数等）
├── 识别候选关系列（排除时间戳、审计列等噪声列）
└── 生成数据模式摘要（UUID、邮箱、数值等模式）
```

### 2.2 第二阶段：关系候选生成
```
步骤3: 单列关系候选生成
├── 表对枚举：对所有表进行两两组合（包括双向检查）
├── 列对筛选：
│   ├── 源列筛选：排除噪声列、高空值率列
│   ├── 目标列筛选：必须是PK/UK、has_index列或高唯一性列
│   └── 类型兼容性检查：compatibility >= 0.5（依据 discovery.type_compatibility.groups 配置）
├── 名称相似度计算：
│   ├── 确定性算法：标准化名称、同义词组匹配、包含关系与 `id` 结尾规则
│   └── 向量相似度（可选）：当 `discovery.name_similarity.use_embedding_similarity = true` 且 `EmbeddingSimilarityService` 可用时，批量计算向量相似度；若服务不可用则回退到 `SequenceMatcher` 编辑距离
└── 候选对象创建：生成RelationshipCandidate对象

步骤4: 复合键关系候选生成（可选）
├── 复合键来源收集：`_collect_composite_key_groups()` 根据 `composite.candidate_sources`（默认包含主键/唯一键/外键/索引）提取长度在 `[2, max_columns]` 范围内的列集合
├── 来源约束：若 `composite.allow_mixed_sources = false`，只比较来源一致的 from/to 组合
├── 排列与阈值：对候选列做全排列配对，只有当所有列对的名称相似度 ≥ `composite.min_name_similarity` 且类型兼容度 ≥ `composite.min_type_compatibility` 时才保留
├── 去重与限流：使用 `(from_columns, ordered_to_columns)` 签名去重，并通过 `composite.max_candidates_per_pair` 控制每个表对的候选数量
└── 列配对记录：为每个复合候选保存列映射的名称/类型得分，供报告与评估阶段复用
```

### 2.3 第三阶段：候选关系评估
```
步骤5: 度量计算
├── 数据采样：获取源列和目标列的实际值样本
├── 包含率计算：from_values中有多少在to_values中存在
├── Jaccard系数：交集/并集的比例
├── 唯一度评分：目标列的唯一性程度
├── 样本命中率：快速采样验证
└── 综合评分：基于权重配置的加权平均

步骤6: 决策和过滤
├── 评分排序：按composite_score降序排列
├── 阈值过滤：低于reject阈值的候选被排除
├── 冲突解决：避免重复和冲突的关系
└── 置信度分级：high/medium/low三个级别
```

### 2.4 第四阶段：结果输出和报告
```
步骤7: 结果生成
├── Cypher语句生成：用于Neo4j图数据库
├── 关系对象创建：包含完整的度量信息
└── 统计信息汇总：各类关系的数量统计

步骤8: 报告输出
├── JSON详细报告：包含所有候选和度量信息
├── Markdown摘要报告：人类可读的分析结果
└── 日志记录：详细的执行日志和LLM调用统计
    （LLM统计仅在手动启用相关模块时出现）
```

## 3. 字段查找的遍历策略

### 3.1 遍历方法：优化的穷举法
算法采用**两层嵌套循环**的遍历策略，但加入了多重优化：

```python
# 外层循环：表对组合
for table1, table2 in combinations(table_names, 2):
    # 双向检查（A->B 和 B->A）
    for from_table, to_table in [(table1, table2), (table2, table1)]:
        # 内层循环：列对组合
        for from_col in from_meta.columns:
            for to_col in to_meta.columns:
                # 预筛选条件
                if not _is_candidate_column(from_col): continue
                if not _is_target_qualified(to_col): continue
                if type_compatibility < 0.5: continue
                # 生成候选...
```

### 3.2 预筛选优化策略
为避免不必要的计算，算法在遍历过程中应用多重预筛选：

**源列筛选条件：**
- 排除JSON/JSONB/ARRAY类型
- 排除噪声列（时间戳、审计列等）
- 排除高空值率列（>80%）

**字段类型过滤规则：**

在`_is_candidate_column()`方法中，算法排除以下字段：

```python
def _is_candidate_column(column, profile):
    # 1. 数据类型排除
    if column.type in [ColumnType.JSON, ColumnType.JSONB, ColumnType.ARRAY]:
        return False
    
    # 2. 名称模式排除
    noise_patterns = [
        '_ts', '_time', 'timestamp', 
        'created_', 'updated_', 'deleted_', 'modified_',
        'create_ts', 'update_ts', 'delete_ts'
    ]
    if any(pattern in column.name.lower() for pattern in noise_patterns):
        return False
    
    # 3. 数据质量排除
    if profile and profile.null_ratio > 0.8:
        return False
```

**被排除的字段类型：**
- JSON、JSONB、ARRAY类型
- 包含时间戳模式的字段名（_ts、_time、timestamp、created_、updated_等）
- 空值率超过80%的字段

**未被排除的字段类型：**
- 数值类型（包括INTEGER、BIGINT、REAL、DOUBLE等）
- 字符串类型（VARCHAR、TEXT等）
- 日期时间类型（DATE、TIMESTAMP等）

**目标列筛选条件：**
- 必须是主键、唯一键、具有索引标记的列，或高唯一性列（>=95%）
- 类型必须与源列兼容（compatibility >= 0.5，来自 discovery.type_compatibility.groups）

**名称相似度门槛：**
- 基础相似度必须达到配置阈值（默认0.6）
- 或者类型完全兼容（compatibility >= 0.8）

### 3.3 复杂度分析
- **时间复杂度**：O(T² × C²)，其中T是表数量，C是平均列数
- **实际优化**：通过预筛选，实际计算的候选数量远小于理论上限
- **并发控制**：评估阶段采用批处理（默认3个并发）避免连接池耗尽

## 4. 评分系统的具体方法

### 4.1 评分维度和权重配置
```yaml
weights:
  inclusion_rate: 0.30      # 包含率（最重要）
  jaccard_index: 0.15       # Jaccard系数
  uniqueness: 0.10          # 唯一度
  name_similarity: 0.20     # 名称相似度
  type_compatibility: 0.20  # 类型兼容性
```
附注：所有导出的指标（composite_score、inclusion_rate、jaccard_index、uniqueness_score、type_compatibility）统一保留最多两位小数，便于人工审阅；若权重之和与1存在微小偏差，系统仅记录 warning，不会中断运行。

### 4.2 各维度的具体计算方法

#### 4.2.1 包含率 (Inclusion Rate)
```python
def _calculate_inclusion_rate(from_values, to_values):
    """计算FROM表中有多少值在TO表中存在"""
    # 排除None值
    from_clean = {v for v in from_values if v is not None}
    to_clean = {v for v in to_values if v is not None}
    
    if not from_clean:
        return 0.0
    
    intersection = from_clean & to_clean
    return len(intersection) / len(from_clean)
```

#### 4.2.2 Jaccard系数
```python
def _calculate_jaccard_index(set1, set2):
    """计算交集/并集的比例"""
    # 排除None值
    set1_clean = {v for v in set1 if v is not None}
    set2_clean = {v for v in set2 if v is not None}
    
    intersection = set1_clean & set2_clean
    union = set1_clean | set2_clean
    
    return len(intersection) / len(union) if union else 0.0
```

#### 4.2.3 名称相似度计算

**关于表名的参与：**
- **基础算法（确定性）**：只比较字段名相似度，不使用表名信息
- **当前实现**：Orchestrator 尚未在候选阶段调用 LLM；语义增强完全由确定性逻辑 + 可选的向量服务完成

**确定性算法（默认路径）：**
```python
name_results = self._calculate_name_similarity_batch(pair_keys)
```
1. **标准化**：将列名转为小写并移除 `_`、`-`、空格
2. **通用标识符过滤**：如果标准化后命中 `generic_identifier_tokens`（默认含 `id`、`code` 等），且双方完全一致，则直接返回0，避免“id vs id”垄断高分
3. **完全匹配**：标准化后相同 → 1.0
4. **同义词匹配**：命中配置的同义词组 → 0.9
5. **包含关系**：一个名称包含另一个 → 0.8
6. **特殊模式**：`xxx_id` ↔ `id` → 0.7

**向量相似度（可选增强）：**
- 当 `discovery.name_similarity.use_embedding_similarity = true` 且 `EmbeddingSimilarityService` 判定可用（`embedding.enabled = true`）时，批量调用向量模型（当前实现支持 Qwen Embedding）
- 计算后的得分会缓存，重复列对不再调用外部服务
- 如果服务不可用（未启用、缺少密钥、或运行异常），系统会以 debug 级别提示并自动回退到后述的编辑距离

**编辑距离兜底（SequenceMatcher）：**
- 当既未命中确定性规则，也无法使用向量结果时，使用 `difflib.SequenceMatcher` 计算 Ratcliff-Obershelp 相似度
- 该算法对拥有公共前/后缀的列名更友好（如 `customer_id` vs `customer_code`），并产生 0~1 的连续分值
- 仍保持 Python 标准库实现，避免额外依赖

```
当前名称相似度的决策顺序：
│
├── 1. 完全/同义词/包含/特殊模式
├── 2. 向量相似度（若启用且可用）
└── 3. SequenceMatcher 兜底
```

这套管线保证了：即便 embedding/LLM 全部禁用，系统依然可以获得稳定的名称得分；在需要更高语义能力时，只需打开 embedding 配置即可获得增强。

#### 4.2.4 类型兼容性
```python
def _calculate_type_compatibility(type1, type2):
    """计算数据类型兼容性"""
    if type1 == type2:
        return 1.0  # 完全相同
    elif type1.is_compatible_with(type2):
        return 0.8  # 兼容类型（如int和bigint）
    else:
        return 0.0  # 不兼容
```

#### 4.2.5 名称复杂度（已停用）
`RelationshipMetrics` 目前只保留 `name_similarity`、`type_compatibility`、`inclusion_rate`、`jaccard_index`、`uniqueness_score` 五个维度。早期设计的 `name_complexity` 已从评分体系中移除，代码中不再计算或存储该指标。

### 4.3 综合评分计算
```python
def calculate_composite_score(metrics, weights):
    """计算综合评分"""
    score = (
        weights.get('inclusion_rate', 0.30) * metrics.inclusion_rate +
        weights.get('jaccard_index', 0.15) * metrics.jaccard_index +
        weights.get('uniqueness', 0.10) * metrics.uniqueness_score +
        weights.get('name_similarity', 0.20) * metrics.name_similarity +
        weights.get('type_compatibility', 0.20) * metrics.type_compatibility
    )
    metrics.composite_score = min(1.0, max(0.0, score))
    return metrics.composite_score
```

### 4.4 置信度分级
```yaml
decision:
  high: 0.90                     # >=0.90 → high
  medium: 0.80                   # [0.80, 0.90) → medium
  prefer_composite: false        # 是否排序时优先复合关系
  suppress_single_if_composite: false
  suppress_single_if_existing_fk: false
  pk_pk_cap_enabled: true        # 对自动推断的 PK↔PK 关系封顶得分
  pk_pk_cap_score: 0.5
  max_relationships_per_table_pair: 0
```
说明：
- `high`/`medium` 仅用于标记置信度，不会屏蔽候选；低于 `medium` 自动标为 `low`
- `pk_pk_cap_enabled` 会在排序前将纯主键映射的综合分数封顶，避免“表结构完全一致”主导输出
- `suppress_single_if_composite` / `suppress_single_if_existing_fk` 可在接受复合关系或已知复合外键后，抑制被其严格包含的单列关系
- `max_relationships_per_table_pair` 可限制每个 (from_table, to_table) 最终保留的关系数量（0 表示不限）

## 5. 语义增强组件与当前使用状态

### 5.1 向量相似度是唯一的自动语义增强
- 只有当 `embedding.enabled = true` 且 `discovery.name_similarity.use_embedding_similarity = true` 时，`EmbeddingSimilarityService` 才会在候选阶段被调用
- 服务支持批量缓存，失败时自动回退到 `SequenceMatcher`，不会中断整个分析流程
- 该流程完全在 `CandidateGenerator` 内部处理，不依赖 LLM，也不会增加额外的数据库查询

### 5.2 LLMController / BusinessEnhancer 的定位
- 代码库中提供了 `LLMController` 与 `BusinessEnhancer`，用于未来或自定义场景的业务语义分析
- 默认的 `Orchestrator` 并未调用这些组件，因而标准运行流程不会触发 LLM 请求，也不会把 LLM 结果写入报告
- CLI 的 `--llm-stats` 与 `test_connection` 仅用于检查 LLM 配置是否可用，不会影响候选/评估逻辑
- 若业务需要，可以在自定义流程中显式实例化 `BusinessEnhancer.enhance_candidate_evaluation()`，该方法会在 `llm_controller.is_available()` 为真时调用 `suggest_business_rules`

### 5.3 日志与报告中的表现
- 因默认流程未接入 LLM，日志中看不到 “LLM 请求/响应” 相关输出；只有手动调用 `LLMController` 时才会写入
- 报告文件中的 `config.name_similarity_method` 字段仅区分 “deterministic / embedding”，不会出现 LLM 相关字段
- 如果未来接入 LLM，需要在 Orchestrator 的评估或决策阶段显式整合结果，并相应扩展报告结构

## 6. 输出结果文件的产生和修改时间点

### 6.1 JSON详细报告 (`analysis_report_YYYYMMDD_HHMMSS.json`)

**产生时间点**：
- 分析流程完全结束后
- 在`Orchestrator._save_report()`方法中生成
- 时机：所有关系决策完成，但在显示最终统计之前

**文件内容**：
```json
{
  "run_id": "uuid",
  "timestamp": "2025-09-17T00:52:43.726673",
  "database": "数据库名",
  "db_schema": "schema名",
  "tables_analyzed": 10,
  "columns_analyzed": 124,
  "candidates_generated": 878,
  "relationships_discovered": 28,
  "relationships": [
    {
      "from_table": "source_table",
      "from_columns": ["column1"],
      "to_table": "target_table", 
      "to_columns": ["column2"],
      "relationship_type": "inferred",
      "join_type": "LEFT",
      "metrics": {
        "candidate": {...},
        "inclusion_rate": 1.0,
        "jaccard_index": 0.99,
        "uniqueness_score": 1.0,
        "sample_hit_rate": 1.0,
        "composite_score": 0.994,
        "confidence_level": "high"
      },
      "source": "auto_detected",
      "confidence": 0.994,
      "verified": true
    }
  ],
  "execution_time_seconds": 45.2,
  "config": {
    "sampling_ratio": 0.01,
    "max_rows": 10000,
    "thresholds": {...},
    "discovery_strategies": [...]
  }
}
```

**修改时间点**：
- **首次创建**：分析完成时一次性写入
- **不会修改**：文件一旦创建就不再修改
- **版本控制**：每次运行产生新的时间戳文件

### 6.2 Markdown摘要报告 (`analysis_summary_YYYYMMDD_HHMMSS.md`)

**产生时间点**：
- 紧跟在JSON报告生成之后
- 在`Orchestrator._save_summary_report()`方法中生成
- 基于JSON报告的数据生成人类可读的摘要

**文件内容结构**：
```markdown
# DB2Graph 分析报告

**运行ID**: 882b5143-a8c5-4161-8160-64d629d2f7b9
**时间**: 2025-09-17T00:52:43.726673
**数据库**: highway_db (schema: public)
**执行时间**: 45.2秒

## 统计信息

- 分析表数量: 10
- 分析列数量: 124
- 生成候选数: 878
- 发现关系数: 28

## 发现的关系

### 高置信度关系 (15个)

- **bss_service_area_mapper** → **bss_service_area**: service_area_id → id (置信度: 99.43%)
- **bss_branch** → **bss_section_route**: section_route_id → id (置信度: 98.49%)
- ...

### 中置信度关系 (8个)

- table1 → table2: col1 → col2 (置信度: 85.20%)
- ...

### 低置信度关系 (5个)

- table3 → table4: col3 → col4 (置信度: 82.10%)
- ...

## 输出文件

- Cypher 文件: `output/cypher/relationships_uuid.cypher`
```

**修改时间点**：
- **首次创建**：JSON报告生成后立即创建
- **不会修改**：文件创建后不再修改
- **格式特点**：专注于高层次统计和最重要的关系

### 6.3 Cypher文件 (`relationships_UUID.cypher`)

**产生时间点**：
- 在`Orchestrator._output_results()`方法中
- 关系决策完成后，报告生成之前
- 仅在`output_mode`为`cypher`或`both`时生成

**文件内容示例**：
```cypher
// DB2Graph Auto-generated Relationships
// Generated at: 2025-09-17T00:52:43

// High Confidence Relationships
CREATE (:Table {name: 'bss_service_area_mapper'})-[:REFERENCES {
  from_columns: ['service_area_id'],
  to_columns: ['id'],
  confidence: 0.994,
  inclusion_rate: 1.0,
  source: 'auto_detected'
}]->(:Table {name: 'bss_service_area'});
```

**修改时间点**：
- **首次创建**：每次分析运行时创建
- **不会修改**：文件创建后不再修改
- **存储位置**：`output/cypher/`目录

### 6.4 日志文件 (`db2graph.log`)

**产生时间点**：
- **持续写入**：从应用启动开始，贯穿整个分析过程
- **实时更新**：每个操作步骤都会产生日志记录

**关键日志时间点**：
```
[开始] 元数据读取
[进行] 数据采样和画像分析  
[进行] 候选关系生成
[进行] LLM增强调用（如果启用）
[进行] 候选关系评估
[进行] 关系决策
[完成] 结果输出
[完成] 报告生成
```

**LLM调用日志**（仅在手动触发 `LLMController` / `BusinessEnhancer` 时出现）：
```
[DEBUG] LLM 请求: provider=deepseek, function=suggest_name_similarity
[DEBUG] LLM 响应: provider=deepseek, function=suggest_name_similarity  
[INFO] LLM增强完成: table1.col1 -> table2.col2 基础=0.65, 增强=0.75, 最终=0.72
```

### 6.5 文件生命周期总结

```
时间轴: 分析流程进行时
│
├── T0: 应用启动
│   └── 开始写入日志文件
│
├── T1-T5: 分析执行阶段  
│   ├── 持续写入日志
│   ├── LLM调用日志（仅在自定义流程手动接入时）
│   └── 进度和调试信息
│
├── T6: 关系决策完成
│   └── 生成Cypher文件（如果配置）
│
├── T7: 分析结果汇总
│   ├── 创建JSON详细报告
│   └── 创建Markdown摘要报告
│
└── T8: 分析完成
    ├── 输出最终统计信息到日志
    ├── 显示LLM使用统计（仅在运行 CLI 的 `--llm-stats` 或其他自定义命令时）
    └── 程序结束
```

**文件持久性**：
- 所有输出文件一旦创建就不再修改
- 每次运行产生独立的时间戳文件
- 支持历史版本的对比和追溯
- 日志文件可能被轮转（根据配置）

## 总结

DB2Graph的关联字段查找算法是一个多层次、多维度的智能系统，具有以下特点：

1. **渐进式精确度**：从粗粒度筛选到精细化评估，层层递进
2. **多维度评分**：结合名称、类型、数据分布等多个维度
3. **智能优化**：通过预筛选大幅减少计算量
4. **可选增强**：可按需启用向量相似度或自行接入 LLM 组件以提升语义理解
5. **全面记录**：详细的日志和报告支持结果追溯和优化

该算法在保证较高准确率的同时，通过各种优化策略确保了在大型数据库上的可行性和效率。
