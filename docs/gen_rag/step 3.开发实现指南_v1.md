# Step 3 开发实现指南 v3.2

本指南面向实现“表之间关联关系发现（Step 3）”的开发者，描述 CLI 集成方式、输入输出路径、需要落地的模块/函数以及数据结构约束。实现时需与 `docs/gen_rag/step 3.关联字段查找算法详解_v3.2.md`（算法规范）和 `docs/gen_rag/step 3.关联关系发现完整流程示例_v3.2.md`（示例流程）保持一致。

## 1. CLI 集成说明

### 1.1 命令入口

Step 3 继续沿用现有 `metadata` CLI，命令格式如下：

```bash
python -m src.metaweave.cli.main metadata \
  --config configs/metaweave/metadata_config.yaml \
  --step rel [其余可选参数]
```

> ⚠️ **实现注意**：当前 CLI 仅支持 `ddl/json/md/cql/all`，`rel` 选项尚未在代码中实现。开发 Step 3 时必须同步扩展 `metadata_cli.py` 和 `MetadataGenerator.SUPPORTED_STEPS`，确保 `--step rel` 可以正确路由到关系管线后再使用上述命令。

- `--step rel`：仅执行关联关系发现；保留现有 `ddl/json/md/cql/all` 选项，新增 `rel`。`all` 模式下应在 Step 2 成功后自动衔接 Step 3。
- 其余参数（`--schemas`、`--tables`、`--incremental`、`--max-workers`）保持原语义，可被 Step 3 复用以限定需要分析的表集。

### 1.2 输入目录与命名

- JSON 画像输入：`output/metaweave/metadata/json/{schema}.{table}.json`（Step 2 产物，版本号需>=2.0）。
- 运行时需根据 CLI 传入的 schema/table 范围挑选对应的 JSON 文件；若未传入则遍历 `json` 目录下全部文件。
- JSON 结构详见算法文档第 1 章，必须解析 `table_info`、`column_profiles`、`table_profile`、`sample_records` 等节点。

### 1.3 输出目录与命名

**输出目录**：
- 路径：`output/metaweave/metadata/rel/`
- 配置项：`output.rel_directory`（需要在配置文件的顶层 `output` 节点下新增；目前默认配置尚未包含该键，实施 Step 3 时记得补充并下发）

**文件命名方案（v3.2 Phase 1实现）**：

支持两种模式，通过配置切换：

**模式1：Global（默认）**
```yaml
output:
  rel_granularity: "global"
```

输出：
```
output/metaweave/metadata/rel/
├── relationships.json           # 所有schema的所有关系
└── relationships_summary.md     # 全局汇总报告
```

特点：
- ✅ 最简单（1个文件）
- ✅ 便于全局分析和可视化
- ✅ 适合单schema或小型项目（<30表）

---

**模式2：Schema**
```yaml
output:
  rel_granularity: "schema"
```

输出：
```
output/metaweave/metadata/rel/
├── public_relationships.json            # public schema的关系
├── public_relationships_summary.md
├── analytics_relationships.json
└── analytics_relationships_summary.md
```

特点：
- ✅ 按schema隔离
- ✅ 适合多schema项目

---

**配置示例**（以下字段均需在实施 Step 3 时新增到 `metadata_config.yaml`）：
```yaml
output:
  rel_directory: "./output/metaweave/metadata/rel"
  rel_granularity: "global"  # "global"（默认）| "schema"
```

**未来扩展**（Phase 2/3规划）：
- `rel_granularity: "table"`：按表拆分（文件名：`{schema}.{table}_relationships.json`）
- `rel_granularity: "auto"`：自动选择（基于schema数量和表数量阈值）

**输出JSON格式要求**：
- 必须包含：`metadata_source`, `statistics`, `relationships`
- `statistics` 节点需包含 `foreign_key_relationships`、`composite_key_relationships`、`single_column_relationships` 等计数
- 复合键关系需嵌套 `suppressed_single_relations` 数组
- 结构与算法详解 v3.2 第6.1节保持一致

### 1.4 与既有步骤的协作

- Step 3 不得修改 Step 1/Step 2 的输出格式；仅读取 JSON。
- 若 `--step all`，应保证执行顺序：DDL → JSON → REL → CQL/MD（如用户也要求）。当 Step 2 失败时，不得继续 Step 3。
- 与 `MetadataGenerator` 集成时，应在 `SUPPORTED_STEPS` 与 CLI `click.Choice` 中新增 `"rel"`，并在 `_resolve_formats_for_step` 中把 `rel` 映射到新管道，而非复用 `OutputFormatter` 现有格式列表。

## 2. 开发实现清单

### 2.1 模块划分建议

在 `src/metaweave/core/relationships/`（或 `core/metadata/relationships/`）新增以下模块，保持与现有 `MetadataGenerator` 类似的分层：

| 模块/类 | 职责 |
| --- | --- |
| `RelationshipDiscoveryPipeline` | Orchestrator，读取 JSON、驱动各阶段、写出结果 |
| `MetadataRepository` | 封装对 Step 2 JSON 的加载/缓存，提供 `get_table(schema, table)` |
| `CandidateGenerator` | 实现算法文档第 3.2 节（复合键 + 单字段）逻辑，输出候选列表（接收 `fk_signature_set` 用于排除已知外键） |
| `RelationshipScorer` | 负责数据库采样、度量计算、评分，复用并扩展 `DatabaseConnector`（支持列/元组采样）与 `MetadataProfiler` |
| `RelationshipWriter` | 负责结果 JSON/Markdown 输出、ID 生成（确定性哈希）、统计聚合（合并 `pre_existing_relations` 与 `discovered_relations`） |

允许根据实际情况调整命名，但需覆盖以上职责。

#### 2.1.1 模块调用关系图（概览）

```
┌─────────────────────────────────────┐
│  MetadataGenerator (CLI入口)        │
└─────────────┬───────────────────────┘
              │  --step rel
              ↓
┌─────────────────────────────────────┐
│  RelationshipDiscoveryPipeline      │  (总控制器)
└─────────────┬───────────────────────┘
              │
              ├─→ MetadataRepository.load_json()
              │    └─→ _collect_pre_existing_foreign_keys()  # 生成外键直通 + fk_signature_set
              │
              ├─→ [可选] discover_relationships_parallel(table_pairs, max_workers)
              │       └─→ _analyze_pair(src, tgt)
              │
              ├─→ CandidateGenerator.generate_for_pair(src, tgt, fk_signature_set)
              │    ├─→ _generate_composite_candidates()  # 物理/逻辑/动态同名
              │    └─→ _generate_single_candidates()     # 主动同名/常规筛选
              │
              ├─→ RelationshipScorer.evaluate(candidates)
              │    └─→ DatabaseConnector
              │         ├─ sample_column()/sample_columns()  # Phase 2
              │         └─ sample_data() + 内存投影          # Phase 1 回退
              │
              ├─→ DecisionEngine.apply()
              │    └─→ apply_suppression_rules()  # 同表对：复合键→抑制单字段（无独立约束）
              │
              └─→ RelationshipWriter.write_report(merged)
                   ├─→ compute_relationship_id()       # 确定性哈希ID
                   ├─→ 去重（按关系ID）
                   └─→ _calculate_statistics()         # 统计顶层 statistics
```

说明与约束：
- 生成候选时使用 `fk_signature_set` 排除已知外键；评分阶段按表对并发，合并/抑制/统计在主线程完成。
- DatabaseConnector 在 Phase 1 可用 `sample_data()` 回退，Phase 2 提升为列/元组采样接口。
- 决策/抑制只影响同一对表的单字段候选；被抑制的单字段嵌套入复合键关系对象。


### 2.2 需要暴露的关键函数

1. `discover_relationships(tables: list[TableJson]) -> RelationshipReport`
   - 输入：源/目标表 JSON 对象（需要建立所有表的两两组合）。
   - 输出：包含 `relationships`, `statistics` 的报告对象。

2. Stage 函数（可作为 `RelationshipDiscoveryPipeline` 的私有方法）：
  - `_load_json_metadata()`：扫描输入目录，加载 JSON 并建立 `{schema.table: TableMetadata}` 索引。
  - `_collect_pre_existing_foreign_keys()`：从每张表的 `physical_constraints.foreign_keys` 生成 `foreign_key` 关系对象列表与 `fk_signature_set`
  - `_generate_candidates(source, target)`：返回复合键候选、单字段候选，遵循算法文档 3.2 节的筛选条件、主动搜索与抑制规则。
  - `_evaluate_candidate(candidate)`：调用评分器；评分器需提供 `calculate_metrics()`、`calculate_composite_score()`、`apply_thresholds()` 等接口，并依赖 `DatabaseConnector` 的列/元组采样接口。
  - `_persist_results(report)`：写入 `rel` 目录，并触发 Markdown 汇总（可选）。

  参考伪代码（阶段1紧邻执行）：
  ```python
  def _load_json_metadata(self) -> dict[str, dict]:
      """
      阶段1：加载JSON
      返回: tables 映射 {"schema.table": table_json}
      """
      tables = load_all_json_files(input_dir=self.config.output.json_directory)
      # 可在此处完成基本校验与索引构建
      return tables

  def _collect_pre_existing_foreign_keys(self, tables: dict[str, dict]) -> tuple[list[Relation], set[str]]:
      """
      阶段1：收集外键直通关系（紧接JSON加载后）
      返回:
        pre_existing_relations: List[Relation]
        fk_signature_set: Set[str]  # 用于候选阶段排除
      """
      pre_existing_relations: list[Relation] = []
      fk_signature_set: set[str] = set()

      for key, table in tables.items():
          pc = table.get('table_profile', {}).get('physical_constraints', {})
          for fk in pc.get('foreign_keys', []) or []:
              from_schema = table['table_info']['schema_name']
              from_table = table['table_info']['table_name']
              from_cols = sorted([c.lower() for c in fk.get('source_columns', [])])
              to_schema = fk.get('target_schema')
              to_table = fk.get('target_table')
              to_cols = sorted([c.lower() for c in fk.get('target_columns', [])])

              # 关系对象（直通，高置信度）
              rel = Relation(
                  type='foreign_key',
                  from_table={'schema': from_schema, 'table': from_table},
                  to_table={'schema': to_schema, 'table': to_table},
                  source_columns=from_cols,
                  target_columns=to_cols,
                  target_source_type='foreign_key',
                  discovery_method='physical_constraint',
                  source_constraint=None,
                  composite_score=1.0,
                  confidence_level='high',
                  metrics=None,
              )
              pre_existing_relations.append(rel)

              # 外键签名（用于候选阶段精确排除）
              signature = (
                  f"foreign_key|{from_schema}.{from_table}|{','.join(from_cols)}|"
                  f"{to_schema}.{to_table}|{','.join(to_cols)}"
              ).lower()
              fk_signature_set.add(signature)

      return pre_existing_relations, fk_signature_set
  ```

3. CLI 集成函数：在 `MetadataGenerator.generate()` 中新增 `if self.active_step in {"rel", "all"}` 分支，调用 `RelationshipDiscoveryPipeline.run()`，并把生成的文件路径添加到 `GenerationResult.output_files`。

### 2.3 数据结构定义

建议使用 `dataclasses` 或 `TypedDict` 描述以下结构，以便在多个模块之间共享：

```python
@dataclass
class TableJson:
    schema: str
    name: str
    table_type: str
    profile: dict   # table_profile 节点
    columns: dict   # column_profiles
    samples: list[dict]
```

`RelationshipCandidate`：
- `type`: `"composite_key" | "single_column"`
- `from_table` / `to_table`: `{schema, table}`
- `from_columns` / `to_columns`: list[str]
- ~~`source_type`~~ → `target_source_type`: 枚举值（见下方字段重命名说明）
- `discovery_method`: `"standard_matching" | "active_search" | "logical_key_matching" | ...`
- `source_constraint`: 源列的物理约束类型（见下方字段说明）

`CandidateMetrics`：与算法文档第 4 章一致，包括 `inclusion_rate`, `jaccard_index`, `uniqueness`, `name_similarity`, `type_compatibility`, `semantic_role_bonus`, `composite_score`, `confidence_level`。

`RelationshipReport`：
```python
@dataclass
class RelationshipReport:
    metadata_source: str
    statistics: RelationshipStats
    relationships: list[RelationshipRecord]
```

其中 `RelationshipRecord` 需支持嵌套 `suppressed_single_relations` 数组，以存储被抑制的候选（algorithm v3.2 核心特性）。

#### 2.3.1 关系字段重命名与约束检测（v3.2.1 更新）

**背景**：原设计中 `source_type` 字段命名容易混淆（看似指源列类型，实际指目标列的来源），且 `source_constraint` 未正确检测源列的实际物理约束，导致信息丢失。

**修改内容**（已实施）：

1. **字段重命名**：`source_type` → `target_source_type`
   - **新语义**：目标列（to_column）是从什么类型的约束/键列表中筛选出来的
   - **取值**：
     - `null`：不从目标列的约束中筛选（如 active_search 只依据同名）
     - `"candidate_logical_key"`：从目标表的候选逻辑主键中筛选
     - `"physical_constraints"`：从目标表的物理约束中筛选
     - `"foreign_key"`：外键直通关系

2. **`source_constraint` 修复**：正确检测源列的实际物理约束
   - **实现**：新增 `_get_source_constraint(rel)` 方法，从源表的 `column_profiles.structure_flags` 检测
   - **检测优先级**：
     1. `is_primary_key` → `"single_field_primary_key"`
     2. `is_unique_constraint` → `"single_field_unique_constraint"`
     3. `is_indexed` → `"single_field_index"`
     4. 其他（如仅 `is_unique: true`）→ `null`（无物理约束）
   - **修改前问题**：硬编码返回 `"single_field_index"`，未区分物理约束和逻辑唯一
   - **修改后效果**：准确反映源列的物理约束类型

**映射表**（修改后）：

| discovery_method | target_source_type | source_constraint | 说明 |
|-----------------|-------------------|-------------------|------|
| `active_search` | `null` | 检测源列实际约束 | 主动搜索同名列 |
| `logical_key_matching` | `"candidate_logical_key"` | `null` | 目标列是逻辑主键 |
| `physical_constraint_matching` | `"physical_constraints"` | `null` | 目标列有物理约束 |
| `dynamic_same_name` | `"candidate_logical_key"` | `null` | 动态同名复合键 |
| `foreign_key_constraint` | `"foreign_key"` | `null` | 外键直通 |

**示例**（修改后）：

```json
{
  "from_table": {"schema": "public", "table": "dim_store"},
  "to_table": {"schema": "public", "table": "fact_store_sales_day"},
  "from_column": "store_id",
  "to_column": "store_id",
  "discovery_method": "active_search",
  "target_source_type": null,
  "source_constraint": null,
  "composite_score": 0.90625,
  "confidence_level": "high"
}
```

**说明**：
- `target_source_type: null` - 目标列不是从特定约束筛选的（只是同名）
- `source_constraint: null` - 源列虽然数据唯一（`is_unique: true`），但没有物理约束

**实现位置**：
- `src/metaweave/core/relationships/writer.py`
  - `_parse_discovery_info()` - 字段重命名和映射
  - `_get_source_constraint()` - 新增，检测源列实际约束

**向后兼容性**：
- CQL 生成器不受影响（不读取这两个字段）
- 仅影响 JSON 输出格式
- 旧版本的 JSON 文件无法直接使用，需重新生成

**验证建议**：
- 检查 `relationships_global.json` 中所有关系的 `target_source_type` 和 `source_constraint` 字段
- 对于 `active_search` 类型，验证 `source_constraint` 是否准确反映源列的物理约束
- 确保没有硬编码的 `"single_field_index"` 出现在实际没有索引的列上

### 2.4 阶段到函数的映射

| 阶段 (v3.2) | 实现要点 | 建议函数 |
| --- | --- | --- |
| 第一阶段：JSON 读取 | 遍历 `json` 目录、验证 `metadata_version`=2.0、构建索引；收集外键直通关系并建立签名集 | `_load_json_metadata`, `_collect_pre_existing_foreign_keys`, `_index_constraints` |
| 第二阶段：候选生成 | 复合键优先、单列候选、主动同名搜索、抑制机制 | `CandidateGenerator.generate_for_pair()` |
| 第三阶段：候选评估 | 数据采样、度量计算、评分权重 | `RelationshipScorer.evaluate()` |
| 第四阶段：决策与抑制 | `accept_threshold`/`medium_confidence_threshold`、suppression | `DecisionEngine.apply()` |
| 第五阶段：输出 | 生成 JSON+Markdown、统计信息、日志 | `RelationshipWriter.write_report()` |

### 2.5 与现有组件的复用

- **数据库连接**：沿用 `DatabaseConnector`，通过 `MetadataGenerator` 初始化，传入 `RelationshipScorer` 用于计算包含率/Jaccard（见下方接口扩展）。
- **采样/统计**：可以直接复用 `MetadataProfiler` 和 `sampling` 配置，避免重复实现采样策略。
- **配置读取**：
  - 输出目录：从 `output.rel_directory` 读取（需在配置中新增；若无则默认 `output/metaweave/metadata/rel`）
  - 文件粒度：从 `output.rel_granularity` 读取（需新增，默认 `"global"`）
    - Phase 1支持：`"global"`, `"schema"`
    - Phase 2/3预留：`"table"`, `"auto"`
  - JSON输入目录：使用 `output.json_directory`（Step 2 的输出目录，Step 3 的输入目录）。未设置时默认 `output/metaweave/metadata/json`
- **日志**：沿用 `logging.getLogger("metaweave.generator")` 或为关系模块单独创建 logger，以便在 CLI 中得到统一输出。

【迁移说明】
- 以前文档中出现过 `json_metadata.metadata_directory`，用于指定 JSON 画像目录。自 v3.2 起，统一使用 `output.json_directory` 表示 Step 2 的输出目录（同时也是 Step 3 的输入目录）。
- 请勿再使用 `json_metadata.metadata_directory`；如历史配置中存在该键，请迁移到 `output.json_directory`。

#### 2.5.1 数据库采样接口扩展（必须）

为支持“复合键元组包含率”与更精准的单列包含率计算，需要在 `DatabaseConnector` 中新增以下接口（不修改现有 `sample_data`，以免影响 Step 1/2）：

- `sample_column(schema: str, table: str, column: str, limit: int = 1000, distinct: bool = False, not_null: bool = True) -> list`
  - SQL（limit 策略）：
    - 非去重：`SELECT {col} FROM {schema}.{table} WHERE {col} IS NOT NULL LIMIT %s;`
    - 去重：`SELECT DISTINCT {col} FROM {schema}.{table} WHERE {col} IS NOT NULL LIMIT %s;`

- `sample_columns(schema: str, table: str, columns: list[str], limit: int = 1000, distinct: bool = False, not_null: bool = True) -> list[tuple]`
  - 别名：`sample_tuples(...)`
  - SQL（limit 策略）：
    - 非去重：`SELECT col1, col2, ... FROM {schema}.{table} WHERE col1 IS NOT NULL AND col2 IS NOT NULL ... LIMIT %s;`
    - 去重：`SELECT DISTINCT col1, col2, ... FROM {schema}.{table} WHERE col1 IS NOT NULL AND col2 IS NOT NULL ... LIMIT %s;`

可选：对大表允许 `TABLESAMPLE SYSTEM(%s)`；采样率由 `sampling.sample_size` 与行数推导。

评分器应对相同 `(schema, table, columns, distinct, not_null)` 的请求做缓存，避免重复查询。

短期回退策略：若接口未就绪，可临时使用现有 `sample_data(schema, table, limit)` 返回的 DataFrame 在内存中选取所需列并构造集合/元组进行计算（性能较差，仅作过渡）。

#### 2.5.2 分阶段实现计划

为保证尽快打通功能，同时给后续优化留出空间，按阶段推进数据库采样接口（当前迭代仅需完成 Phase 1；Phase 2 为后续优化目标，不在本迭代范围，不影响功能正确性）：

- Phase 1（MVP，功能优先）
  - 依赖现有 `sample_data()` 获取整表样本；在内存中选择所需列并构造集合/元组计算包含率与 Jaccard。
  - 仅支持 `LIMIT` 策略采样；不强制 `distinct`/`not_null` 参数（可在内存层做去重与非空过滤）。
  - 预期功能完整，但性能一般；代码需保留清晰的接口边界，方便替换为 Phase 2 实现。

- Phase 2（优化，性能优先）
  - 扩展 `DatabaseConnector`：实现 `sample_column()` 与 `sample_columns()`（别名 `sample_tuples()`），支持 `distinct` 与 `not_null` 参数，尽量下推到 SQL 层。
  - 可选加入 `TABLESAMPLE` 策略；在评分器中做结果缓存，按 `(schema, table, columns, distinct, not_null)` 维度去重请求。
  - 预期相对 MVP 有 5–10 倍的性能提升，具体视表规模、索引与网络环境而定。

运行可用性评估：Phase 1 即可支撑 Step 3 全部功能（候选生成、评分与输出），能够正常运行并产出结果；Phase 2 主要用于性能与可扩展性优化，可在后续性能冲刺阶段实施。

里程碑与验收（本迭代）：
- [必须] Phase 1 完成并通过端到端验证（含示例数据）
- [必须] 文档/代码中为 Phase 2 预留接口与注释，但不要求实现
- [可选] 基于真实库做一次性能采样，记录待优化点（作为 Phase 2 输入）

#### 2.5.3 Phase 1 评分缓存与过滤指引（推荐）

为减少重复采样/计算，建议在评分器中加入轻量缓存与统一过滤约定（不增加复杂度）：

- 缓存键约定
  - 表级样本缓存：`table_df_cache[(schema, table)] -> pandas.DataFrame`（来自 `sample_data`，每表一次）
  - 单列集合缓存：`single_set_cache[(schema, table, col)] -> frozenset(values)`
  - 复合元组集合缓存：`tuple_set_cache[(schema, table, cols_tuple)] -> frozenset(tuple_rows)`（`cols_tuple`保持候选时的列顺序）

- 非空与去重规则
  - 单列：`series.dropna().unique()` → 转 `frozenset`
  - 复合：`df[list(cols)].dropna(how='any').drop_duplicates()` → `itertuples(index=False, name=None)` → `frozenset`

- 计算公式（示意）
  - 单列包含率：`len(from_set & to_set) / max(1, len(from_set))`
  - 复合元组包含率：`len(from_tuples & to_tuples) / max(1, len(from_tuples))`

- 注意事项
  - 复合包含率计算时“列顺序不可排序”，应与候选的 `from_cols/to_cols` 顺序一致；仅在“签名/ID 生成或外键签名”中使用排序列名。
  - 尽量重用同一表的 DataFrame，避免对同一表多次调用 `sample_data`。
  - 采样 `LIMIT`（默认 1000）与缓存大小按项目规模调整，避免内存压力。

### 2.6 开发注意事项

1. **不要破坏既有步骤**：`SUPPORTED_STEPS`/CLI 选项扩展时务必保持向后兼容，`--step ddl/json/md/cql/all` 的行为不可改变。
2. **容错**：当某张表缺失 JSON 或 JSON 格式无效时，记录 warning 并跳过，不应导致整个 CLI 失败。
3. **性能**：
   - JSON 加载后建立内存索引，避免重复解析。
   - 候选生成阶段不访问数据库，评分阶段才访问数据库，遵守设计文档要求。
4. **输出一致性**：`relationships` 数组需记录 `relationship_id`（确定性哈希ID，见下文）、`type`（含 `foreign_key`/`composite_key`/`single_column`）、`from_table`、`to_table`、`metrics`、`confidence_level`、`discovery_method`、`target_source_type`、`source_constraint`、`suppressed_single_relations` 等字段。`foreign_key` 类型为直通关系，不参与评分，`metrics` 可为 `null`。
5. **扩展性**：代码结构应允许未来加入 LLM/Embedding 评分（v3.2 预留 `semantic_analysis`，请勿在数据结构中写死字段）。

---

完成以上开发准备后，可按照算法文档逐步实现：先搭建 JSON 装载 & CLI 集成骨架，再落地候选生成/评分/输出各阶段，最后对照 `step 3.关联关系发现完整流程示例_v3.2.md` 中的样例进行端到端验证。

## 2.11 配置迁移清单（本迭代）

目的：最小化对现有配置的影响，同时为 Step 3 提供必要的开关与默认值。本迭代仅需将以下键加入 `configs/metaweave/metadata_config.yaml`；若未添加，也会走文档中声明的默认值，不阻塞运行。

新增配置项（推荐加入）
- `output`（路径与粒度）
  - `json_directory`: `"./output/metaweave/metadata/json"`（推荐新增；Step 2 输出与 Step 3 输入目录；缺省时从 `output.output_dir + "/json"` 推导）
  - `rel_directory`: `"./output/metaweave/metadata/rel"`（推荐新增；缺省时从 `output.output_dir + "/rel"` 推导）
  - `rel_granularity`: `"global"`（可选：`global|schema`，默认 `global`）
  - `rel_id_salt`: `""`（可选；关系ID哈希盐，默认空）

- `single_column`（单字段候选）
  - `active_search_same_name`: true（默认 true）
  - `important_constraints`: `[ 'single_field_primary_key', 'single_field_unique_constraint', 'single_field_index' ]`（默认如左）
  - `logical_key_min_confidence`: 0.8（默认 0.8）

- `composite`（复合键候选）
  - `max_columns`: 3（默认 3）
  - `target_sources`: `[ 'physical_constraints', 'candidate_logical_keys', 'dynamic_same_name' ]`（默认如左）
  - `min_name_similarity`: 0.7（默认 0.7；仅用于物理/逻辑匹配）
  - `min_type_compatibility`: 0.8（默认 0.8；仅用于物理/逻辑匹配）

- `decision`（阈值与抑制）
  - `accept_threshold`: 0.80（默认 0.80）
  - `high_confidence_threshold`: 0.90（默认 0.90）
  - `medium_confidence_threshold`: 0.80（默认 0.80）
  - `suppress_single_if_composite`: true（默认 true）

示例片段（可直接合并到现有配置）
```yaml
output:
  json_directory: "./output/metaweave/metadata/json"
  rel_directory: "./output/metaweave/metadata/rel"
  rel_granularity: "global"
  rel_id_salt: ""

single_column:
  active_search_same_name: true
  important_constraints:
    - 'single_field_primary_key'
    - 'single_field_unique_constraint'
    - 'single_field_index'
  logical_key_min_confidence: 0.8

composite:
  max_columns: 3
  target_sources:
    - 'physical_constraints'
    - 'candidate_logical_keys'
    - 'dynamic_same_name'
  min_name_similarity: 0.7
  min_type_compatibility: 0.8

decision:
  accept_threshold: 0.80
  high_confidence_threshold: 0.90
  medium_confidence_threshold: 0.80
  suppress_single_if_composite: true
```

兼容策略（未配置时的默认行为）
- 路径：`output.json_directory` 与 `output.rel_directory` 缺省时，从 `output.output_dir` 推导（分别追加 `/json` 与 `/rel`）
- 粒度：`output.rel_granularity` 缺省为 `global`
- ID 盐：`output.rel_id_salt` 缺省为空
- 规则：`single_column`、`composite`、`decision` 下的各项如未配置，均按“2.8 配置默认值与健壮性”所列默认值使用

迁移步骤（建议）
1) 在现有 `output` 节点下新增 `json_directory` 与 `rel_directory`；
2) 按需新增 `rel_granularity` 与 `rel_id_salt`；
3) 复制本节 `single_column`、`composite`、`decision` 配置块（或仅加入与默认不同的值）；
4) 保存并用 `--step rel`（功能开发完成后）做一次端到端验证。

## 2.12 并发与资源管理（表对级并发）

并发目标：在候选评估（需要访问数据库）阶段，按“表对（source_table, target_table）”粒度并发，提高吞吐量。

- 并发粒度：表对级（table_pair）。候选生成不访问 DB，可并发或单线程执行；评分阶段按表对分发到线程。
- 线程安全：每个 worker 通过 `DatabaseConnector` 的连接池获取独立连接；确保 `database.pool_max_size >= effective_workers`，避免阻塞。
- 有效并发数：
  - `effective_workers = min(max_workers, database.pool_max_size)`（也可再与 CPU 数、I/O 预算取 min）。
- 结果合并：主线程收集各 worker 的结果（候选关系列表），统一去重、抑制、统计与写出。
- 锁与缓存：
  - Phase 1 推荐使用“每个 worker 自身的评分缓存”（见 2.5.3），避免共享锁；
  - 只在主线程做最终合并与抑制，减少同步复杂度。

参考伪代码：
```python
def discover_relationships_parallel(self, table_pairs: list[tuple], max_workers: int):
    """
    表对级并发分析
    - 评分阶段访问 DB，需配合连接池
    - 结果合并在主线程完成
    """
    effective_workers = min(max_workers, self.db_pool_max_size)
    results = []
    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = [executor.submit(self._analyze_pair, src, tgt) for (src, tgt) in table_pairs]
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                self.logger.error(f"analyze_pair failed: {e}")

    # 主线程统一合并与抑制
    merged = self._merge_results(results)  # 去重（按确定性ID）、合并suppressed
    self.decision_engine.apply_suppression_rules(
        accepted_composite_relations=merged.composites,
        all_single_candidates=merged.singles,
        tables_json_map=self.tables_json_map,
    )
    stats = self._calculate_statistics(merged.pre_existing, merged.accepted)
    self.writer.write(merged, stats)
    return merged
```

实现要点：
- 连接池：`database.pool_max_size`（默认 5）不足以支撑较高并发时，适当增大；但过高会给数据库带来压力。
- 去重：合并时优先用“确定性哈希ID”去重；同一对表同列集来源不同（物理/逻辑/动态）的候选合并为一条。
- 稳定性：任何单表对失败不应中断整体流程；主线程收集异常并汇总报告。

## 2.13 测试计划（必须）

采用 `pytest`，以“单元测试 + 集成测试”两层覆盖核心逻辑与端到端正确性。可在 `tests/` 下新增如下结构：

```
tests/
├── unit/relationships/
│   ├── test_metadata_repository.py
│   │   ├── test_load_json_with_invalid_version()
│   │   └── test_collect_pre_existing_foreign_keys_generates_fk_and_signatures()
│   ├── test_candidate_generator.py
│   │   ├── test_generate_composite_candidates()
│   │   ├── test_generate_single_candidates()
│   │   ├── test_active_search_discovery()
│   │   ├── test_dynamic_same_name_matching()
│   │   └── test_exclude_known_foreign_keys_by_signature()
│   ├── test_relationship_scorer.py
│   │   ├── test_calculate_inclusion_rate_phase1_fallback()
│   │   ├── test_calculate_composite_score_weights_applied()
│   │   └── test_semantic_role_bonus()
│   ├── test_decision_engine.py
│   │   ├── test_apply_thresholds_accept_and_reject()
│   │   └── test_suppression_rules_with_and_without_important_constraint()
│   └── test_relationship_writer.py
│       ├── test_compute_relationship_id_deterministic_and_collision_guard()
│       └── test_calculate_statistics_counts_and_suppressed_nesting()
└── integration/relationships/
    ├── test_end_to_end_simple.py          # 对应流程示例_v2 的单字段场景
    ├── test_end_to_end_composite.py       # 复合键 + 抑制场景（含独立约束例外）
    ├── test_end_to_end_dynamic.py         # 动态复合同名匹配场景
    └── test_end_to_end_foreign_key.py     # 外键直通 + 排除候选 + 合并输出
```

说明与要点：
- 基础夹具（fixtures）
  - `tests/fixtures/json/` 放置最小 JSON 表画像（v2.0），覆盖：无约束、物理复合键、逻辑主键、外键、单列索引/唯一等组合。
  - 为 `RelationshipScorer` 的 Phase 1 测试，用 monkeypatch 注入 `DatabaseConnector.sample_data()` 返回的 DataFrame，避免真实 DB 依赖。
- 单元测试关注点
  - MetadataRepository：版本校验、必需节点缺失、外键直通与签名生成。
  - CandidateGenerator：
    - 复合键候选（物理/逻辑/动态同名），列数范围与类型约束；
    - 单列候选（常规筛选 + 主动同名触发）；
    - 外键签名排除（同表对、同列集不再生成候选）。
  - RelationshipScorer：
    - Phase 1 回退路径（sample_data + 内存投影）下的包含率/Jaccard 计算；
    - 评分权重与综合分；语义角色奖励。
  - DecisionEngine：
    - 阈值过滤与置信度分级；
    - 抑制规则：同表对、列覆盖、无独立约束 → 被抑制；有独立约束 → 保留。
  - RelationshipWriter：
    - 确定性哈希 ID（相同输入多次运行一致；不同 salt 变化）；
    - 统计口径：被抑制的单列不计入 single_column，总数/外键/复合/active_search/dynamic_same_name 计数正确。
- 集成测试覆盖点
  - simple：单字段完美匹配（store_id → store_id），确保仅一条关系写出；
  - composite：有复合键且触发抑制（含“独立约束”例外），确认 suppressed_single_relations 嵌套；
  - dynamic：目标表未声明复合约束，动态同名 + 类型兼容成功产出复合关系；
  - foreign_key：外键直通写出、候选生成阶段不重复分析、最终合并；
  - 并发（可选标记 slow）：表对级并发执行 end-to-end，用小型连接池验证 `effective_workers = min(max_workers, pool_max_size)` 行为。

不纳入本迭代的测试（可为后续预留标记）
- Phase 2 的列/元组采样接口（`sample_column/sample_columns`）与 TABLESAMPLE 的性能验证；
- LLM/Embedding 语义增强相关测试。
## 2.8 配置默认值与健壮性（必须）

为避免缺失配置导致运行失败，Step 3 实现需对关键参数设置内置默认值，并在读取时做类型与范围校验：

- 默认值约定（未配置时使用）：
  - `composite.max_columns`: 3（建议运行时钳制到区间 [2, 10]）
  - `composite.min_name_similarity`: 0.7
  - `composite.min_type_compatibility`: 0.8
  - `single_column.logical_key_min_confidence`: 0.8
  - `single_column.active_search_same_name`: true
  - `decision.accept_threshold`: 0.80
  - `decision.high_confidence_threshold`: 0.90
  - `decision.medium_confidence_threshold`: 0.80

- 读取示例（Python）：
  ```python
  cfg = config or {}
  composite_cfg = cfg.get('composite', {}) if isinstance(cfg.get('composite', {}), dict) else {}
  single_cfg = cfg.get('single_column', {}) if isinstance(cfg.get('single_column', {}), dict) else {}
  decision_cfg = cfg.get('decision', {}) if isinstance(cfg.get('decision', {}), dict) else {}

  max_columns = composite_cfg.get('max_columns', 3)
  if not isinstance(max_columns, int):
      max_columns = 3
  max_columns = max(2, min(10, max_columns))

  min_name_sim = float(composite_cfg.get('min_name_similarity', 0.7))
  min_type_comp = float(composite_cfg.get('min_type_compatibility', 0.8))
  logical_key_min_conf = float(single_cfg.get('logical_key_min_confidence', 0.8))
  accept_threshold = float(decision_cfg.get('accept_threshold', 0.80))
  ```

上述默认值需在候选生成与评分阶段统一使用，保证即使配置文件未提供相关字段也能稳定运行。

## 2.7 关系ID生成策略（必须）

为确保增量与并发运行下 ID 稳定、可追踪，关系ID必须使用“确定性哈希”生成，而非自增序号。

- 规范化签名（signature）规则：全部转小写，去首尾空格，使用竖线 `|` 分隔段、逗号 `,` 分隔列名；复合键列名按字母序排序。
  - 单字段：
    - `single|{from_schema}.{from_table}|{from_col}|{to_schema}.{to_table}|{to_col}`
  - 复合键：
    - `composite|{from_schema}.{from_table}|{sorted_from_cols}|{to_schema}.{to_table}|{sorted_to_cols}`
  - 外键直通：
    - `foreign_key|{from_schema}.{from_table}|{sorted_from_cols}|{to_schema}.{to_table}|{sorted_to_cols}`
- 哈希算法与格式：
  - 使用 `md5(signature)` 的十六进制结果，取前12位作为前缀：`relationship_id = "rel_" + hash_hex[:12]`
  - 碰撞处理（同一输出批次内极低概率）：如检测到重复ID，追加短标记（如 `_b`）重算或直接改后缀，保证唯一。
- 可选命名空间：
  - 若需要在不同环境隔离ID，可在配置中提供 `output.rel_id_salt`，生成签名前拼接：`signature = f"{salt}|" + signature`。

实现位置建议：在 `RelationshipWriter` 中提供 `compute_relationship_id(record)` 工具函数集中实现上述逻辑，写出前为每个关系赋值 `relationship_id`。

## 2.9 抑制规则实现（DecisionEngine）

抑制规则在“阶段4：决策与抑制”执行，建议集中放在 `DecisionEngine` 中，接口清晰、便于单测。

职责：
- 接收“已接受的复合键关系”和“全量单字段候选（含评分）”，在同一对表范围内，按规则抑制被复合键覆盖且无独立约束的单字段关系；
- 被抑制的单字段关系不出现在顶层 `relationships`，而是嵌套到对应复合键对象的 `suppressed_single_relations` 中；
- 具有独立约束（`has_important_constraint` 为真）的单字段关系不被抑制，继续作为独立关系输出。

参考接口：
```python
class DecisionEngine:
    def __init__(self, accept_threshold: float = 0.80):
        self.accept_threshold = accept_threshold

    def apply_suppression_rules(
        self,
        accepted_composite_relations: list[dict],
        all_single_candidates: list[dict],
        tables_json_map: dict[str, dict],  # key: "schema.table"
    ) -> None:
        """
        应用抑制规则（就地更新 accepted_composite_relations）

        步骤：
        1) 遍历每个已接受的复合键关系（type='composite_key'）
        2) 在同一对表范围内筛选单字段候选（type='single_column'）
        3) 若单字段候选的 from/to 列均被该复合键覆盖，检查源列是否有独立约束：
           has_important_constraint(from_column, source_table_json)
        4) 无独立约束 → 标记为抑制：记录 {from_column, to_column, original_score, suppression_reason,
           could_have_been_accepted = (original_score >= self.accept_threshold)}，并嵌入复合键的 suppressed_single_relations
        5) 有独立约束 → 不抑制，保持为独立关系
        """
        for comp in accepted_composite_relations:
            suppressed: list[dict] = []
            for single in all_single_candidates:
                if self._should_suppress(single, comp, tables_json_map):
                    suppressed.append({
                        'from_column': single['from_column'],
                        'to_column': single['to_column'],
                        'original_score': single.get('composite_score'),
                        'suppression_reason': '在复合键中，无独立约束',
                        'could_have_been_accepted': (single.get('composite_score', 0) >= self.accept_threshold),
                    })
            comp['suppressed_single_relations'] = suppressed

    def _should_suppress(self, single: dict, comp: dict, tables_json_map: dict[str, dict]) -> bool:
        # 仅同一对表；单字段必须被复合键列覆盖；源列无独立约束
        if not self._same_table_pair(single, comp):
            return False
        if not self._columns_covered(single, comp):
            return False
        source_key = f"{comp['from_table']['schema']}.{comp['from_table']['table']}"
        table_json = tables_json_map.get(source_key)
        if not table_json:
            return False
        return not has_important_constraint(single['from_column'], table_json)[0]
```

实现要点：
- “同一对表”指 from_table 与 to_table 完全一致；
- “列覆盖”指 single 的 from_column 在 comp 的 source_columns 中，且 to_column 在 comp 的 target_columns 中；
- `has_important_constraint` 实现遵循算法详解 v3.2（单字段主键/唯一/索引为真）；
- 若同一单字段候选与多个复合键重叠，默认挂载到“复合键评分更高/覆盖度更高”的那个复合键下（实现时可取“列重叠数量优先，其次 composite_score 优先”）；
- 抑制仅影响“同一对表”的单字段候选；该单字段对其它目标表的关系不受影响。

## 2.10 统计信息计算（RelationshipWriter）

`RelationshipWriter` 负责在写出 JSON 前计算顶层 `statistics` 节点。计数应基于“最终将写出的关系”，即：
- `pre_existing_relations`: 外键直通关系（不评分，必写出）
- `discovered_relations`: 通过阈值过滤后的新发现关系（单字段/复合键），不包含被抑制的单字段（它们已嵌套在复合键对象中）

参考实现：
```python
def _calculate_statistics(self, pre_existing_relations: list[dict], discovered_relations: list[dict]) -> dict:
    """
    计算统计信息（仅基于最终写出的关系；被抑制的单字段不计入单字段总数）
    """
    all_rel = list(pre_existing_relations) + list(discovered_relations)

    def is_fk(r):
        return r.get('type') == 'foreign_key'

    def is_comp(r):
        return r.get('type') == 'composite_key'

    def is_single(r):
        return r.get('type') == 'single_column'

    total = len(all_rel)
    fk_cnt = sum(1 for r in all_rel if is_fk(r))
    comp_cnt = sum(1 for r in all_rel if is_comp(r))
    single_cnt = sum(1 for r in all_rel if is_single(r))

    suppressed_cnt = 0
    for r in all_rel:
        if is_comp(r):
            suppressed_cnt += len(r.get('suppressed_single_relations', []) or [])

    active_search_cnt = sum(
        1 for r in all_rel
        if r.get('discovery_method') == 'active_search'
    )

    dynamic_comp_cnt = sum(
        1 for r in all_rel
        if is_comp(r) and (r.get('discovery_method') == 'dynamic_same_name' or r.get('target_source_type') == 'dynamic_same_name')
    )

    return {
        'total_relationships_found': total,
        'foreign_key_relationships': fk_cnt,
        'composite_key_relationships': comp_cnt,
        'single_column_relationships': single_cnt,
        'total_suppressed_single_relations': suppressed_cnt,
        'active_search_discoveries': active_search_cnt,
        'dynamic_composite_discoveries': dynamic_comp_cnt,
    }
```

实现要点：
- `discovered_relations` 不包含被抑制的单字段；被抑制的单字段仅在复合键对象的 `suppressed_single_relations` 中计数。
- `foreign_key_relationships` 通常仅来自 `pre_existing_relations`，但实现上可对 `all_rel` 做统一判定（兼容性更好）。
- `dynamic_composite_discoveries` 可依据 `discovery_method == 'dynamic_same_name'` 或 `target_source_type == 'dynamic_same_name'`，以防某些实现只填其中一个字段。
