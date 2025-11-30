# Step 4 生成 Neo4j CQL 设计 v3.2

本设计描述如何基于 Step 2 的表/列画像（JSON）与 Step 3 的表间关系（JSON），生成符合 v3.2 规范的 Neo4j Cypher 脚本（.cypher），供 Step 5 执行导入到 Neo4j 图数据库。Step 4 只负责“离线产出 .cypher 文件”，不直接连接 Neo4j。

## 1. 范围与目标
- 输入：
  - Step 2 画像目录：`./output/metaweave/metadata/json/*.json`
  - Step 3 关系目录：`./output/metaweave/metadata/rel/*.json`（v3.2 格式）
- 输出：
  - Cypher 脚本目录：`./output/metaweave/metadata/cql/`
  - 产物（文件扩展名 .cypher）：
    - **global 模式**（默认）：`import_all.cypher` - 包含所有表和关系的完整 CQL 脚本
    - **schema 模式**（未来支持）：按 schema 拆分的多个 CQL 文件
    - **table 模式**（未来支持）：按 table 拆分的多个 CQL 文件
- Neo4j 版本：>= 5.7.x；Step 4 不需要连接 Neo4j（连接信息供 Step 5 使用）。

## 2. 图数据模型（节点/关系/属性）
### 2.1 节点标签
- `Table`
- `Column`

### 2.2 `Table` 节点属性（建议且与后续 SQL 子图兼容）
- `id`（string, unique）: `schema.table`（与 `full_name` 相同，用于兼容 SQL 子图模块查询）
- `full_name`（string, unique）: `schema.table`（语义更清晰的唯一键）
- `schema`（string）: schema 名
- `name`（string）: 表名
- `comment`（string, 可空）: 表注释
- `pk`（list<string>）: 物理主键列名列表（单列或多列）
- `uk`（list<list<string>>）: 物理唯一约束集合
- `fk`（list<object>）: 物理外键集合（对象结构见 3.1）
- `logic_pk`（list<list<string>>）: 候选逻辑主键集合（来自 Step 2 logical_keys）
- `logic_fk`（list<list<string>>）: 逻辑外键（来自 Step 3 关系，源端列集合）
- `logic_uk`（list<list<string>>）: 逻辑唯一集合（可空/预留，来自 Step 2 画像推断，若有）
- `indexes`（list<list<string>>）: 物理索引集合（含复合索引）

说明：
- 同时保留 `id` 和 `full_name` 两个属性，值相同，确保向后兼容（SQL 子图模块使用 `id` 查询）
- `full_name` 语义更清晰，建议优先使用
- 两者均建立唯一约束
- **物理约束与逻辑约束严格分离**：
  - 物理约束（`pk`、`uk`、`fk`、`indexes`）：来自数据库 DDL 的实际约束
  - 逻辑约束（`logic_pk`、`logic_fk`、`logic_uk`）：来自 Step 2/3 的推断和发现
  - Table 节点同时保留物理和逻辑约束，便于不同场景使用
  - Column 节点的 `is_pk`/`is_uk`/`is_fk` 仅反映物理约束，不包含逻辑约束

### 2.3 `Column` 节点属性
- `full_name`（string, unique）: `schema.table.column`
- `schema`（string）
- `table`（string）
- `name`（string）
- `comment`（string, 可空）
- `data_type`（string）
- `semantic_role`（string, 可空）: identifier/datetime/enum/metric/audit/attribute
- `is_pk`（boolean）：是否为物理主键
- `is_uk`（boolean）：是否在物理唯一约束中
- `is_fk`（boolean）：是否为物理外键
- `is_time`（boolean，来自 semantic_role=datetime）
- `is_measure`（boolean，来自 semantic_role=metric）
- `pk_position`（int，主键序号，非主键为 0）
- 可选统计：`uniqueness`（float），`null_rate`（float）

### 2.4 `HAS_COLUMN` 关系（Table → Column）
- 标签：`HAS_COLUMN`
- 属性：无（或可选 `position` 列序）

### 2.5 `JOIN_ON` 关系（Table → Table）
- 标签：`JOIN_ON`
- 属性：
  - `cardinality`（string）: N:1 | 1:N | 1:1 | M:N（来自 Step 3 或简化默认）
  - `constraint_name`（string, 可空）: 物理外键约束名（有则保留）
  - `join_type`（string）: 默认 `INNER JOIN`
  - `on`（string）: 连接表达式，如 `SRC.company_id = DST.company_id`，复合键以 AND 连接
  - 可选：`source_columns`/`target_columns`（list<string>）供程序化检索

## 3. 生成规则（来源映射）
### 3.1 从 Step 2（表/列画像 JSON）生成 `Table` 与 `Column`
- `Table`：
  - `full_name`: `table_info.schema_name + '.' + table_info.table_name`
  - `schema`/`name`/`comment`：来自 `table_info`
  - `pk`/`uk`/`indexes`：来自 `table_profile.physical_constraints`
  - `fk`：对象数组，每个对象包含：
    - `constraint_name`
    - `source_columns`
    - `target_schema`/`target_table`
    - `target_columns`
  - `logic_pk`：来自 `table_profile.logical_keys.candidate_primary_keys`（confidence_score >= 0.8）
  - `logic_fk`：初始化为空（将由 3.2 从 Step 3 关系补充源端列集合）

- `Column`：
  - `full_name`/`schema`/`table`/`name`
  - `data_type`，`comment`（若有）
  - `semantic_role`：来自 `column_profiles[*].semantic_analysis.semantic_role`
  - `is_pk`/`is_uk`/`is_fk`（仅物理约束，不包含逻辑约束）：
    - `is_pk`：若列在物理主键（physical_constraints.primary_key）中
    - `is_uk`：若列出现在任一物理唯一约束（physical_constraints.unique_constraints）集合中
    - `is_fk`：若列在任一物理外键（physical_constraints.foreign_keys）的 source_columns 中
  - `is_time`：semantic_role=datetime；`is_measure`：semantic_role=metric
  - `pk_position`：主键中的位置，否则 0

### 3.2 从 Step 3（关系 JSON v3.2）生成 `JOIN_ON`
- 遍历 `relationships`：
  - 源端/目标端 `Table` 以 `from_table.schema/table` 与 `to_table.schema/table` 关联，MERGE 节点后 MERGE 关系。
  - 关系类型（单列/复合/外键直通）不影响 CQL 的 MERGE 标签，但影响 `on` 表达式与 `source_columns/target_columns`。
  - `on` 表达式：
    - 单列：`SRC.{from_column} = DST.{to_column}`
    - 复合：`AND` 连接，按源列顺序与目标列一一对应：
      `SRC.{from_columns[i]} = DST.{to_columns[i]}`
  - 若类型为外键直通（foreign_key），保留 `constraint_name`。其余从 inference/discovery 字段生成辅助属性可选。
- 同时更新源端 `Table.logic_fk`：追加该关系的 `from_columns` 集合。

## 4. CQL 生成规范
### 4.1 约束与索引（建议）
- 唯一约束：
  - `CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE;`
  - `CREATE CONSTRAINT table_full_name IF NOT EXISTS FOR (t:Table) REQUIRE t.full_name IS UNIQUE;`
  - `CREATE CONSTRAINT column_full_name IF NOT EXISTS FOR (c:Column) REQUIRE c.full_name IS UNIQUE;`

### 4.2 节点生成（MERGE + SET）
- Table：
```
// 以 UNWIND 批量 MERGE
UNWIND $tables AS t
MERGE (n:Table {full_name: t.full_name})
SET n.id = t.full_name,
    n.schema = t.schema,
    n.name = t.name,
    n.comment = t.comment,
    n.pk = t.pk,
    n.uk = t.uk,
    n.fk = t.fk,
    n.logic_pk = t.logic_pk,
    n.logic_fk = t.logic_fk,
    n.logic_uk = t.logic_uk,
    n.indexes = t.indexes;
```
说明：
- `n.id` 设置为与 `full_name` 相同的值，确保兼容性
- `n.logic_fk` 直接设置（不累加），确保幂等性
- Column：
```
UNWIND $columns AS c
MERGE (n:Column {full_name: c.full_name})
SET n.schema = c.schema,
    n.table = c.table,
    n.name = c.name,
    n.comment = c.comment,
    n.data_type = c.data_type,
    n.semantic_role = c.semantic_role,
    n.is_pk = c.is_pk,
    n.is_uk = c.is_uk,
    n.is_fk = c.is_fk,
    n.is_time = c.is_time,
    n.is_measure = c.is_measure,
    n.pk_position = c.pk_position,
    n.uniqueness = c.uniqueness,
    n.null_rate = c.null_rate;
```

### 4.3 `HAS_COLUMN` 关系
```
UNWIND $hasColumns AS hc
MATCH (t:Table {full_name: hc.table_full_name})
MATCH (c:Column {full_name: hc.column_full_name})
MERGE (t)-[:HAS_COLUMN]->(c);
```

### 4.4 `JOIN_ON` 关系
```
UNWIND $joins AS j
MATCH (src:Table {full_name: j.src_full_name})
MATCH (dst:Table {full_name: j.dst_full_name})
MERGE (src)-[r:JOIN_ON]->(dst)
SET r.cardinality = j.cardinality,
    r.constraint_name = j.constraint_name,
    r.join_type = coalesce(j.join_type, 'INNER JOIN'),
    r.on = j.on,
    r.source_columns = j.source_columns,
    r.target_columns = j.target_columns;
```

说明：`$tables/$columns/$hasColumns/$joins` 为 Step 4 生成器填充的参数（Step 4 写入到 .cypher 文件时可展开为 `UNWIND` 的字面量数组，或在 Step 5 以参数式执行）。

## 5. 生成流程（实现建议）
1) 读取 Step 2 JSON，构建表与列模型：
   - 提取物理约束（PK/UK/FK/Indexes）、候选逻辑主键、列画像（类型、语义角色、统计）
   - 推导 Column 的 is_pk/is_uk/is_fk/is_time/is_measure/pk_position
   - 组织 `$tables`、`$columns`、`$hasColumns` 参数数组
2) 读取 Step 3 关系 JSON（v3.2）：
   - 遍历 `relationships`，按单列/复合/外键直通构造 `$joins` 参数（含 on/source_columns/target_columns/cardinality/constraint_name）
   - 同步更新 `$tables[*].logic_fk`
3) 写出 .cypher 文件（建议顺序）：
   - 01_constraints.cypher → 02_nodes_tables.cypher → 03_nodes_columns.cypher → 04_rels_has_column.cypher → 05_rels_join_on.cypher
   - 可附带 00_import_all.cypher（单文件纯 Cypher 脚本，便于一次性执行或由加载器统一提交）

## 6. 配置与默认值
- 读取顶层配置：`./configs/metaweave/metadata_config.yaml`
  - `output.json_directory`：Step 2 输入目录（默认 `./output/metaweave/metadata/json`）
  - `output.rel_directory`：Step 3 输入目录（默认 `./output/metaweave/metadata/rel`）
  - `output.cql_directory`：Step 4 输出目录（若无可默认 `./output/metaweave/metadata/cql`）
  - 其余与 Step 3 相同的阈值/权重不影响 Step 4
- Neo4j 连接信息（Step 5 使用）：
  - `.env` 中的 `NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD/NEO4J_DATABASE`

## 7. CLI 集成（Step 4 入口）
- 命令：
  - `python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step cql`
- 行为：
  - 读取 Step 2/Step 3 的 JSON 输入目录；
  - 在 `./output/metaweave/metadata/cql/`（或 `output.cql_directory`）下生成 `*.cypher` 文件；
  - 不连接 Neo4j，仅生成脚本。
- 约束：
  - 当前实现仅输出纯 Cypher 文件（无 Browser 元命令），便于后续加载器按顺序/批次提交。

## 8. 与“SQL 生成子图”模块的兼容
- 代码位置：
  - Neo4j 连接与业务客户端：`src/services/db/neo4j_connection.py`、`src/services/db/neo4j_client.py`
  - SQL 生成子图配置：`src/modules/sql_generation/config/sql_generation_subgraph.yaml`（`join_strategy: apoc_dijkstra`）
  - 路径检索策略：`apoc_dijkstra` 优先，失败回退 `shortestPath`。见 `neo4j_client._find_path_apoc_dijkstra()` 中 `CALL apoc.algo.dijkstra(...)`
- 结论：
  - 该模块使用 APOC（见 `RETURN apoc.version()` 与 `CALL apoc.algo.dijkstra`），Step 5 导入后应保证 APOC 可用。
  - 为兼容子图检索：
    - `Table` 节点需以 `full_name` 唯一；
    - `JOIN_ON` 关系的 `on/source_columns/target_columns` 属性可用于诊断；路径检索主要基于 `JOIN_ON` 标签与端点。
  - 如需调整属性名，请在 Step 4 定稿时与子图模块同步（本设计已保持常用属性与标签不变：`Table/Column/HAS_COLUMN/JOIN_ON`）。

## 9. 示例（简化）
### 9.1 约束
```
CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT table_full_name IF NOT EXISTS FOR (t:Table) REQUIRE t.full_name IS UNIQUE;
CREATE CONSTRAINT column_full_name IF NOT EXISTS FOR (c:Column) REQUIRE c.full_name IS UNIQUE;
```

### 9.2 Table/Column（展开后的 UNWIND 略）
```
MERGE (t:Table {full_name: 'public.dim_store'})
SET t.id='public.dim_store', t.schema='public', t.name='dim_store', t.pk=['store_id'], t.indexes=[['store_id']];
MERGE (c:Column {full_name: 'public.dim_store.store_id'})
SET c.schema='public', c.table='dim_store', c.name='store_id', c.is_pk=true, c.is_fk=false;
MERGE (t)-[:HAS_COLUMN]->(c);
```

### 8.3 JOIN_ON（单列 & 复合）
```
// 单列
MATCH (src:Table {full_name: 'public.fact_sales'}),(dst:Table {full_name: 'public.dim_store'})
MERGE (src)-[r:JOIN_ON]->(dst)
SET r.cardinality='N:1', r.join_type='INNER JOIN',
    r.source_columns=['store_id'], r.target_columns=['store_id'],
    r.on='SRC.store_id = DST.store_id';

// 复合
MATCH (src:Table {full_name: 'public.fact_sales_day'}),(dst:Table {full_name: 'public.fact_sales_month'})
MERGE (src)-[r:JOIN_ON]->(dst)
SET r.cardinality='N:1', r.join_type='INNER JOIN',
    r.source_columns=['store_id','date_day','product_id'],
    r.target_columns=['store_id','date_month','product_id'],
    r.on='SRC.store_id = DST.store_id AND SRC.date_day = DST.date_month AND SRC.product_id = DST.product_id';
```

## 10. 测试与验收
- 单元测试：
  - JSON 解析与属性映射（表/列）
  - JOIN_ON 构造（单列/复合；on 表达式；属性写入）
  - CQL 文件写出顺序与内容检查
- 集成测试：
  - 用小型样本执行 `cypher-shell -f 00_import_all.cypher` 验证节点/关系数量与属性
  - `neo4j_client` 路径检索（`apoc_dijkstra`）可在导入后成功返回路径

---

附注：本设计在 Step 4 仅生成 CQL 文件，不连接 Neo4j；Step 5 将负责连接 Neo4j 并执行上述脚本。若未来需要直接写库，可复用 `src/services/db/neo4j_connection.py` 的连接管理与 APOC 可用性检查。
