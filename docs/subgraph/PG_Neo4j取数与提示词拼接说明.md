## PG 两张表与 Neo4j 的取数逻辑，以及最终提示词拼接说明

本文基于 `gen_sql` 代码与最近一次运行日志，梳理：
- PostgreSQL 中 `system.dim_value_index` 与 `system.sem_object_vec` 的访问与取数逻辑
- Neo4j 的 JOIN 路径查询逻辑
- 最终发给 LLM 的提示词如何拼接

参考实现位置：
- PG 访问：`agent/db/pg_client.py`
- Neo4j 访问：`agent/db/neo4j_client.py`
- 检索与汇总：`agent/agents/retriever.py` 与 `agent/tools/*`
- 提示词拼接与生成：`agent/tools/generate_sql_tool.py` 与 `agent/prompts/generator_prompt.py`
- 运行配置：`sql_agent.yaml`
- 日志参考：`gen_sql/logs/sql_agent.log`

---

## 一、PostgreSQL：system.dim_value_index 的取数逻辑

实现入口：`PostgreSQLClient.search_dim_values(text, limit)`（`agent/db/pg_client.py`）

- 连接：使用 `psycopg2`，连接串来自 `settings.database.get_connection_string()`，目标 schema 来自 `settings.database.target_schema`（默认 `system`）。
- 查询 SQL（相似度检索）：

```sql
SELECT dim_table, dim_col, key_col, key_value, value_text,
       word_similarity(value_norm, norm_zh(%s)) AS score
FROM system.dim_value_index
WHERE value_norm %% norm_zh(%s)
ORDER BY score DESC
LIMIT %s;
```

> 注：代码使用 psycopg2 的参数占位符 `%s`，执行时会被转换为 PostgreSQL 的参数化查询格式。

- 关键点：
  - 使用 `pg_trgm` 的 `%%` 与自定义 `norm_zh()` 进行中文归一化后相似匹配。
  - 相似度分数通过 `word_similarity(value_norm, norm_zh(%s))` 计算，并按分数降序取 TopK。
  - TopK 默认由 `sql_agent.yaml` 的 `retrieve.dim_index_topk` 控制（默认为 3），可通过 `search_dim_values_tool(value, limit)` 的 `limit` 传参覆盖。

- 命中结果的来源绑定：
  - 在 `agent/agents/retriever.py` 中，对解析结果里的每个 `role="value"` 的维度逐一调用 `search_dim_values_tool` 并将命中集标注 `source_text` 与 `source_index`（维度在 `parse.dimensions` 数组中的索引）。
  - 命中去重规则：按键 `(source_index, dim_table, key_value)` 去重，保留 `score` 更高者。
  - **注意**：返回的 `dim_table` 字段不包含 schema 前缀（如 `dim_company` 而非 `public.dim_company`），后续代码会根据需要添加 schema 前缀。

- 后续用途（维度值优化替换）：
  - 在生成提示词时，若 `sql_agent.yaml` 的 `retrieve.optimize_dim_value_filter=true`，则对每个 `role="value"` 的维度：
    - 仅在该维度的命中集合中（`source_index` 匹配），取 `score` 最高的一条；
    - 若其 `score >= retrieve.optimize_dim_value_min_score`（默认 0.5）且存在 `value_text`，用此 `value_text` 覆盖用户原始输入，以指导 SQL 等值过滤（详见下文“提示词拼接”）。

---

## 二、PostgreSQL：system.sem_object_vec 的取数逻辑

实现入口：`PostgreSQLClient.search_semantic_tables` 与 `PostgreSQLClient.search_semantic_columns`（`agent/db/pg_client.py`）

- 访问场景：
  - 表候选检索：`object_type='table'`
  - 列候选检索：`object_type='column'`（并 LEFT JOIN 表对象拿到 `table_category`）
  - 表卡片拉取：`fetch_table_cards(object_ids)`（用于拼接提示词中的表结构摘要）

- 向量检索 SQL（表）：

```sql
SELECT object_id, lang, grain_hint, time_col_hint, table_category,
       1 - (embedding <=> %s::vector) AS similarity
FROM system.sem_object_vec
WHERE object_type = 'table'
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

- 向量检索 SQL（列）：

```sql
SELECT col.object_id, col.parent_id, tbl.table_category AS parent_category,
       1 - (col.embedding <=> %s::vector) AS similarity
FROM system.sem_object_vec AS col
LEFT JOIN system.sem_object_vec AS tbl
  ON tbl.object_id = col.parent_id AND tbl.object_type = 'table'
WHERE col.object_type = 'column'
ORDER BY col.embedding <=> %s::vector
LIMIT %s;
```

- 表卡片拉取 SQL：

```sql
SELECT object_id, text_raw, grain_hint, time_col_hint, attrs
FROM system.sem_object_vec
WHERE object_type = 'table'
  AND object_id = ANY(%s);
```

- 检索流程与过滤：
  - 文本通过 `EmbeddingClient` 生成向量（维度由配置固定为 1024），再以 `pgvector` 运算 `<=>` 做近邻排序。
  - 阈值过滤：`sql_agent.yaml` 中 `retrieve.similarity_threshold`（默认 0.45）用于对命中结果二次过滤。
  - TopK：`sql_agent.yaml` 中 `retrieve.topk_tables` 与 `retrieve.topk_columns` 控制表与列的候选数量（默认各 10）。
  - **表/列候选的分类（事实/维度）**：
    - 分类依据：使用 `table_category` 字段（通过 `normalize_table_category` 归一化处理），而**不是** `text_raw` 中的描述文本。
    - `text_raw` 字段仅用于生成表结构卡片的摘要，其中可能包含"类型：XXX"的描述文本，但这些文本不作为分类依据（实际分类逻辑见 `agent/tools/search_semantic_objects_tool.py` 的 `_classify_tables` 函数）。
    - 列检索时，SQL 查询通过 LEFT JOIN 获取的 `parent_category` 字段会在 `search_semantic_columns_tool` 中被移除（pop），经 `normalize_table_category` 归一化后重新存储为 `table_category` 字段返回给调用者。
  - 列候选的 `parent_id` 会被提取为表候选之一（见 `agent/agents/retriever.py`）。

---

## 三、Neo4j：JOIN 路径取数逻辑

实现入口：`Neo4jClient.plan_join_paths(base, targets)` 与 `_find_shortest_path(base, target)`（`agent/db/neo4j_client.py`），由 `plan_join_path_tool`（`agent/tools/plan_join_path_tool.py`）调用。

- 连接：读取环境变量 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`，用官方驱动 `GraphDatabase.driver` 建立连接。
- 路径查询：
  - 首选 APOC：

```cypher
MATCH (src:Table {id: $base}), (dst:Table {id: $target})
CALL apoc.algo.dijkstraWithDefaultWeight(src, dst, 'JOIN_ON', 'cost', 1.0)
YIELD path, weight
RETURN path
ORDER BY weight ASC
LIMIT 1;
```

  - 回退最短路：

```cypher
MATCH path = shortestPath((src:Table {id: $base})-[:JOIN_ON*..5]-(dst:Table {id: $target}))
RETURN path
LIMIT 1;
```

- 结果展开为边列表（顺序即遍历顺序），每条边包含：
  - `src_table`、`dst_table`
  - `constraint_name`、`join_type`（默认 `INNER JOIN`）
  - `cardinality`（例如 `N:1`）
  - `on`（JOIN ON 模板字符串，如 `SRC.store_id = DST.store_id`）
  - `cost`（默认 1.0）

- 规划策略补充：
  - 若仅 1 个候选表或符合"维度表优化"条件（由 `planner.enable_dim_only_optimization` 和 `planner.dim_only_gap_threshold` 控制），会跳过 Neo4j 查询，直接返回单表计划（详见 `plan_join_path_tool.py`）。

- 多 Base 表规划：
  - 当存在多个候选事实表时（如 `fact_store_sales_month` 和 `fact_store_sales_day`），`planner_agent` 会为每个事实表作为独立的 Base 进行规划。
  - **实现机制**：`planner_agent` 循环遍历事实表列表，每次以单个表为 base 调用 `plan_join_path_tool`（传入 `candidate_fact_tables=[base]`），该工具每次返回一个 `JoinPlan`；多次调用的结果累积到 `List[JoinPlan]` 中（见 `agent/agents/planner.py` 第27-38行）。
  - **Generator 阶段处理方式**：所有 `JoinPlan` 都会被完整拼接到最终提示词中（使用 `_format_join_plans` 函数遍历并格式化），Generator 阶段本身不做筛选或剪裁，而是将完整信息交给 LLM，由 LLM 根据查询语义决定使用哪个计划或如何组合使用。
  - 例如：Base #1 为 `public.fact_store_sales_month`、Base #2 为 `public.fact_store_sales_day`，两者都会出现在提示词的"JOIN 计划"部分。

---

## 四、提示词拼接逻辑（最终发给 LLM）

实现入口：`generate_sql_tool(context)`（`agent/tools/generate_sql_tool.py`）与模板 `build_generator_prompt(...)`（`agent/prompts/generator_prompt.py`）。

1) 维度过滤串（dimension_filters）
- 遍历 `parse.dimensions`：
  - `role="value"`：默认 `value=原文`；若开启维度值优化，则在该维度对应的 `dim_value_hits` 中取 `score` 最高且 `score>=optimize_dim_value_min_score` 的命中，用其 `value_text` 覆盖原文（每个维度独立处理，依靠 `source_index` 绑定）。
  - `role="column"`：写成 `column=文本`。
- 若未解析出维度过滤，但有 `dim_value_hits`，则回退输出命中预览（`dim_table -> value_text`）。

2) 表结构卡片（table_cards）
- 对每个表对象（来自表卡片拉取），取 `text_raw` 单行摘要，拼为：`- **schema.table**  摘要...`

3) JOIN 计划（join_plan）
- 对**所有** `JoinPlan`（通过 `_format_join_plans` 函数遍历 `envelope.join_plans`）：首行显示 Base 表；随后逐条边按 `src_table --JOIN(cardinality)--> dst_table ON on_clause` 展示。
- 多个 JoinPlan 之间用空行分隔，全部拼接到提示词中，由 LLM 根据查询需求自行选择使用哪个或如何组合。

4) 时间列块（time_column）
- 从每个 Base 表的表卡片中抽取 `time_col_hint`，列为 `- schema.table.time_col` 列表。

5) 模板汇总（生成完整提示词）：
- 由 `generator_prompt.py` 的 `build_generator_prompt(...)` 按以下结构拼接：
  - Header（约束与规范）
  - 方言/问题/时间窗/维度过滤/指标
  - 表结构卡片
  - JOIN 计划
  - 时间列
- 发送给 LLM 的消息：
  - system: `You are an expert PostgreSQL SQL writer. Return valid SQL only.`
  - user: 上述完整提示词（纯文本）

---

## 五、日志（最近一次执行）要点摘录

来源：`gen_sql/logs/sql_agent.log` 末尾（时间：2025-10-27）

- JOIN 计划（示例）：
  - Base #1：`public.fact_store_sales_month`，边包含：
    - `public.fact_store_sales_month` → `public.dim_store` ON `SRC.store_id = DST.store_id`
    - `public.dim_store` → `public.dim_company` ON `SRC.company_id = DST.company_id`
    - `public.fact_store_sales_month` → `public.dim_product_type` ON `SRC.product_type_id = DST.product_type_id`
  - Base #2：`public.fact_store_sales_day`，边包含相同语义的 3 条。

- 维度值优化替换：
  - `京东便利` 与 `全家` 在 `dim_value_index` 中均命中且 `score=1.0`，保持为原文字面（满足阈值）。

- 生成的最终提示词（片段）：

```text
方言：postgresql
问题：请对比一下9月份京东便利和全家这两个公司的销售金额
时间窗口：2025-09-01 ~ 2025-10-01
维度过滤：value=京东便利, value=全家
指标：销售金额

表结构：
- **public.dim_company**  public.dim_company（公司维表，类型：维度表）：字段：company_id(integer) 公司ID（主键）[例:3]；company_name(character varying) 公司名称，唯一[例:喜士多]。
- **public.dim_product_type**  public.dim_product_type（商品类型维表）：。字段：product_type_id(integer) 商品类型ID（主键）[例:3]；product_type_name(character varying) 商品类型名称，唯一[例:零食]。
- **public.dim_store**  public.dim_store（店铺维表，类型：维度表）：字段：store_id(integer) 店铺ID（主键）[例:101]；store_name(character varying) 店铺名称（同一公司下唯一）[例:全家苏州姑苏店]；company_id(integer) 所属公司ID（外键）[例:3]；region_id(integer) 所属区（县）ID（外键）[例:320508]。
- **public.fact_store_sales_day**  ...（略）
- **public.fact_store_sales_month**  ...（略）

JOIN 计划：
Base #1：**public.fact_store_sales_month**
- public.fact_store_sales_month --INNER JOIN (N:1)--> public.dim_store ON SRC.store_id = DST.store_id
- public.dim_store --INNER JOIN (N:1)--> public.dim_company ON SRC.company_id = DST.company_id
- public.fact_store_sales_month --INNER JOIN (N:1)--> public.dim_product_type ON SRC.product_type_id = DST.product_type_id

Base #2：**public.fact_store_sales_day**
- public.fact_store_sales_day --INNER JOIN (N:1)--> public.dim_store ON SRC.store_id = DST.store_id
- public.dim_store --INNER JOIN (N:1)--> public.dim_company ON SRC.company_id = DST.company_id
- public.fact_store_sales_day --INNER JOIN (N:1)--> public.dim_product_type ON SRC.product_type_id = DST.product_type_id

时间列：
- public.fact_store_sales_month.date_month
- public.fact_store_sales_day.date_day
```

- LLM 输出 SQL（实际格式）：

```sql
SELECT 
    dc.company_name AS company,
    SUM(fsm.amount) AS total_sales_amount
FROM 
    public.fact_store_sales_month fsm
INNER JOIN 
    public.dim_store ds ON fsm.store_id = ds.store_id
INNER JOIN 
    public.dim_company dc ON ds.company_id = dc.company_id
WHERE 
    fsm.date_month >= '2025-09-01' 
    AND fsm.date_month < '2025-10-01'
    AND dc.company_name IN ('京东便利', '全家')
GROUP BY 
    dc.company_name;
```

---

## 六、整体数据流概览

1) 解析（Parser）
- 从自然语言抽取 `metric`、`dimensions`（含 `role`=value/column）、时间窗等。

2) 检索（Retriever）
- 对 `role="value"` 的维度：查 `system.dim_value_index`，标注 `source_index`，去重合并。
- 语义向量检索：对问题与列/指标文本，查 `system.sem_object_vec` 的表与列候选；按阈值过滤并分类（事实/维度）。
- 汇总候选表：维度值查得的维表 > 列的 `parent_id` > 语义表检索；去重。

3) 规划（Planner）
- 维度表优化/单表优化（可配）。
- 否则调用 Neo4j 规划 JOIN 路径（APOC 或最短路）。

4) 生成（Generator）
- 拉取表卡片，拼接 `dimension_filters`、`table_cards`、`join_plan`、`time_column` 等，套用模板生成最终提示词。
- 以 system + user 两段消息喂给 LLM，得到最终 SQL。

---

## 七、关键配置项（sql_agent.yaml 结构说明）

配置文件位置：`gen_sql/sql_agent.yaml`

### 7.1 配置文件结构

YAML 配置文件包含 6 个顶级部分：

1. **join**：JOIN 规划策略
2. **retrieve**：检索参数（PG 表查询相关）
3. **planner**：JOIN 路径规划参数
4. **generation**：SQL 生成参数
5. **agent**：LLM 模型运行时配置
6. **logging**：日志配置

### 7.2 检索配置（retrieve）

与 PG 两张表（`dim_value_index` 和 `sem_object_vec`）的查询直接相关：

- `topk_tables: 10`：语义表检索的候选数量
- `topk_columns: 10`：语义列检索的候选数量
- `dim_index_topk: 3`：维度值检索返回条数（影响 `search_dim_values` 查询的 LIMIT）
- `similarity_threshold: 0.45`：向量相似度最低阈值（用于过滤 `sem_object_vec` 检索结果）
- `optimize_dim_value_filter: true`：是否启用维度值优化替换（用 `dim_value_index` 命中的 `value_text` 覆盖用户输入）
- `optimize_dim_value_min_score: 0.5`：维度值替换的最小 score 阈值（基于 `word_similarity`）
- `table_categories`：表分类映射规则
  - `fact: [事实表, 交易表, 明细表]`
  - `dimension: [维度表, 实体表, 枚举表]`
  - `bridge: [桥接表, 关联表]`

### 7.3 规划配置（planner）

与 Neo4j JOIN 路径规划相关：

- `enable_dim_only_optimization: true`：启用维度表优化（纯维度查询时跳过 Neo4j）
- `dim_only_gap_threshold: 0.05`：维度表相似度差距阈值（判断是否使用单维度表）

### 7.4 JOIN 策略配置（join）

影响 Neo4j 路径查询的行为：

- `prefer: shortest`：优先使用最短路径
- `default_join_type: INNER JOIN`：默认 JOIN 类型
- `cross_schema_cost: 1.5`：跨 schema JOIN 的成本惩罚

### 7.5 SQL 生成配置（generation）

影响最终生成的 SQL 格式：

- `dialect: postgresql`：SQL 方言
- `enforce_schema_prefix: true`：强制表名包含 schema 前缀
- `default_schema: public`：默认 schema 名称
- `default_limit: 100`：默认行数限制
- `max_limit: 5000`：最大行数限制

### 7.6 Agent 运行时配置（agent）

LLM 模型选择与参数：

- `orchestrator_model: qwen-plus`：编排器使用的模型
- `sub_agent_model: qwen-plus`：子 Agent（Parser、Retriever、Planner、Generator）使用的模型
- `temperature: 0.1`：LLM 温度参数

### 7.7 日志配置（logging）

控制日志输出行为：

- `level: INFO`：默认日志级别
- `file.enabled: true`：启用文件日志
- `file.level: DEBUG`：文件日志级别
- `file.path: gen_sql/logs/sql_agent.log`：日志文件路径
- `console.enabled: true`：启用控制台日志
- `console.level: INFO`：控制台日志级别
- `verbose_debug: true`：是否输出完整的 JSON 对象（调试用）

---

如需进一步对接或扩展，可从上述文件入口继续深入实现细节。


