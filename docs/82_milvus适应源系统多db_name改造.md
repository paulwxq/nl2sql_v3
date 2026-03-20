# 82_Milvus适应源系统多db_name改造

## table_schema_embeddings

### 一、当前状态

`table_schema_embeddings` 已完成两轮迁移：

1. 增加 `db_name`
2. 将字段名 `parent_id` 改为 `table_name`

当前已通过项目中的 Milvus 连接配置，实际对 `nl2sql` 数据库执行迁移并验证完成。当前 collection 的业务语义是：

- `object_id`：原始唯一标识
  - 表记录：`db.schema.table`
  - 字段记录：`db.schema.table.column`
- `db_name`：数据库名称，来自 `object_id` 第一段
- `table_name`：业务层表名，固定为两段式 `schema.table`

当前 Milvus 中保留了两个历史备份：

- `table_schema_embeddings_old`
- `table_schema_embeddings_parent_id_old`

### 二、达成共识的字段规则

1. `object_id` 当前值保持不变：
   - 表记录：三段式 `db.schema.table`
   - 字段记录：四段式 `db.schema.table.column`
2. `db_name` 字段：
   - 类型：`varchar(64)`
   - 用途：标识当前记录所属数据库，并作为查询默认过滤条件
   - 配置来源：`config.yaml` 中的 `database.database`
3. `table_name` 存储两段式表名：
   - 表记录：`schema.table`
   - 字段记录：该字段所属表的两段式表名 `schema.table`
4. 查询流程约定：
   - 如果要返回 table name，使用 `table_name`
   - 如果要获取当前记录的原始唯一标识，继续使用 `object_id`

### 三、为什么这样改

当前链路里，`object_id` 既承担“原始唯一标识”的角色，也容易被误用为“业务表名”。这会导致当 `object_id` 为三段式 `db.schema.table` 时，后续候选表、表卡片、表分类、提示词都会继续使用三段式，最终将数据库名带入 SQL 生成链路。

本次改造后：

- `object_id` 只保留为底层唯一标识
- `table_name` 统一承担上层业务表名职责
- `db_name` 用于限制当前查询只命中当前数据库的数据

这样可以在不破坏现有唯一性的前提下，完成“多数据库隔离”和“业务表名两段式规范化”。

### 四、建表语句

当前 `table_schema_embeddings` 已经落到如下结构。

```sql
CREATE TABLE table_schema_embeddings (
    object_id VARCHAR(256) PRIMARY KEY,
    object_type VARCHAR(64) NOT NULL,
    db_name VARCHAR(64) NOT NULL,
    table_name VARCHAR(256) NOT NULL,
    object_desc VARCHAR(8192) NOT NULL,
    embedding FLOAT_VECTOR(1024) NOT NULL,
    time_col_hint VARCHAR(512) NOT NULL,
    table_category VARCHAR(64) NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX embedding ON table_schema_embeddings
USING HNSW
WITH (metric_type = 'COSINE', M = 16, efConstruction = 200);
```

字段语义如下：

- `object_id`：原始对象唯一标识
- `object_type`：`table` / `column`
- `db_name`：数据库名称
- `table_name`：业务层表名
- `object_desc`：表或字段描述
- `embedding`：向量字段
- `time_col_hint`：时间列提示
- `table_category`：表分类
- `updated_at`：更新时间

其中：

- `object_id` 保持原始唯一标识，不做变更
- `db_name` 的值来自 `config.yaml` 中的 `database.database`
- `table_name` 统一使用两段式 `schema.table`

### 五、需要修改的查询代码或接口

当前凡是查询 `table_schema_embeddings` 并向上层返回“表名”的地方，都需要从返回 `object_id` 调整为返回 `table_name`，并增加 `db_name` 过滤条件。

其中 `db_name` 的默认绑定值来自：

- [config.yaml](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/configs/config.yaml) 中的 `database.database`

即：

- 查询 `table_schema_embeddings` 时，默认附加 `db_name == config.database.database`

需要重点修改的代码点如下。

#### 5.1 表检索接口 `search_tables`

文件：
- [milvus_adapter.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/services/vector_adapter/milvus_adapter.py#L120)

改造要求：

- 查询条件中增加 `db_name == config.database.database`
- 输出字段增加 `table_name`
- 返回给上层的“表名”改为 `table_name`
- `object_id` 仅在需要原始主键时保留

建议改造后的语义：

- `object_id`：原始唯一标识
- `table_name`：上层候选表 ID

#### 5.2 列检索接口 `search_columns`

文件：
- [milvus_adapter.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/services/vector_adapter/milvus_adapter.py#L168)

改造要求：

- 查询条件增加 `db_name == config.database.database`
- 返回字段改为 `table_name`
- 保证返回的 `table_name` 为两段式 `schema.table`
- `object_id` 保留为字段原始唯一标识

#### 5.3 表卡片查询接口 `fetch_table_cards`

文件：
- [milvus_adapter.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/services/vector_adapter/milvus_adapter.py#L286)

改造要求：

- 入参如果表示“表名”，统一使用两段式 `table_name`
- 查询条件改为按 `table_name in (...) and object_type == "table" and db_name == config.database.database`
- 返回结果字典的 key 改为 `table_name`
- 如需追踪底层原始主键，可在 value 中保留 `object_id`

#### 5.4 表分类查询接口 `fetch_table_categories`

文件：
- [milvus_adapter.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/services/vector_adapter/milvus_adapter.py#L329)

改造要求：

- 查询条件改为按 `table_name in (...) and object_type == "table" and db_name == config.database.database`
- 返回结果 key 改为 `table_name`

#### 5.5 Schema 检索与候选表收集逻辑

文件：
- [retriever.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/tools/schema_retrieval/retriever.py#L120)
- [retriever.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/tools/schema_retrieval/retriever.py#L332)
- [retriever.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/tools/schema_retrieval/retriever.py#L490)

改造要求：

- 表命中链路与列命中链路统一使用 `table_name` 作为候选表 ID
- `object_id` 只用于日志、排障、底层追踪

#### 5.6 SQL 提示词拼接

文件：
- [sql_generation.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/modules/sql_generation/subgraph/nodes/sql_generation.py#L340)

改造要求：

- 确保进入提示词的表名统一为 `table_name`
- 即表类型、表结构、时间列、JOIN 规划使用的业务表名都应是两段式 `schema.table`

### 六、查询与返回约定

对 `table_schema_embeddings` 的所有查询，统一遵循以下规则：

1. 默认增加 `db_name == config.database.database`
2. 查询“业务表名”时使用 `table_name`
3. 查询“原始记录主键”时使用 `object_id`
4. 上层候选表、表卡片、表分类、提示词展示统一使用 `table_name`
5. 日志、回溯、底层定位问题时可保留输出 `object_id`

### 七、相关脚本

本次迁移涉及的临时脚本位于：

- [inspect_milvus_table_schema.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/tmp/inspect_milvus_table_schema.py)
- [migrate_table_schema_embeddings.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/tmp/migrate_table_schema_embeddings.py)
- [migrate_table_schema_embeddings_parent_id_to_table_name.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/tmp/migrate_table_schema_embeddings_parent_id_to_table_name.py)

### 八、改造后预期效果

改造完成后，`table_schema_embeddings` 可以同时满足以下目标：

- 支持多 `db_name` 共存
- 保留原始 `object_id` 唯一性
- 上层统一使用两段式 `table_name`
- 避免在 SQL 生成链路中继续出现 `db.schema.table`

## dim_value_embeddings

### 一、当前状态

`dim_value_embeddings` 已完成一轮多 `db_name` 适配迁移。

已通过项目中的 Milvus 连接配置，实际读取 `nl2sql` 数据库中的 collection schema，结果如下：

- Collection 名称：`dim_value_embeddings`
- 描述：`Embedding index for dimension value text fields`
- 主键：`id`
- 主键属性：`INT64`，`auto_id=True`
- 当前字段结构：
  - `id`：`INT64`，主键，自增
  - `table_name`：`VARCHAR(128)`
  - `col_name`：`VARCHAR(128)`
  - `col_value`：`VARCHAR(1024)`
  - `embedding`：`FLOAT_VECTOR(1024)`
  - `update_ts`：`INT64`
- 当前向量索引：
  - 字段：`embedding`
  - 索引类型：`HNSW`
  - 相似度度量：`COSINE`
  - 参数：`M=16`，`efConstruction=200`

当前 Milvus 中保留了一个历史备份：

- `dim_value_embeddings_old`

### 二、达成共识的字段规则

1. 新增 `db_name` 字段：
   - 类型：`varchar(64)`
   - 值来源：从 `table_name` 三段式表名 `db_name.schema.table` 中提取第一段
   - 查询绑定来源：`config.yaml` 中的 `database.database`
2. `table_name` 字段保持字段名不变，但值需要规范化：
   - 原值：三段式 `db_name.schema.table`
   - 新值：两段式 `schema.table`
3. 其他字段保持不变：
   - `id`
   - `col_name`
   - `col_value`
   - `embedding`
   - `update_ts`

### 三、为什么这样改

`dim_value_embeddings` 当前的 `table_name` 携带了数据库名前缀，这会导致维度值命中的表名仍然可能向上游透出三段式表名，与 `table_schema_embeddings` 已经统一成两段式 `schema.table` 的方案不一致。

本次改造后：

- `db_name` 单独承担数据库隔离职责
- `table_name` 只承担业务层表名职责
- 维度值命中的 `dim_table` 将与 `table_schema_embeddings.table_name` 使用同一套命名规范

### 四、建表语句

根据实际读取到的当前 schema，可反向整理出当前建表语句如下（伪 DDL，表达结构用）：

```sql
CREATE TABLE dim_value_embeddings (
    id BIGINT PRIMARY KEY AUTO_ID,
    table_name VARCHAR(128) NOT NULL,
    col_name VARCHAR(128) NOT NULL,
    col_value VARCHAR(1024) NOT NULL,
    embedding FLOAT_VECTOR(1024) NOT NULL,
    update_ts BIGINT NOT NULL
);

CREATE INDEX embedding ON dim_value_embeddings
USING HNSW
WITH (metric_type = 'COSINE', M = 16, efConstruction = 200);
```

迁移后的当前建表语句如下：

```sql
CREATE TABLE dim_value_embeddings (
    id BIGINT PRIMARY KEY AUTO_ID,
    db_name VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    col_name VARCHAR(128) NOT NULL,
    col_value VARCHAR(1024) NOT NULL,
    embedding FLOAT_VECTOR(1024) NOT NULL,
    update_ts BIGINT NOT NULL
);

CREATE INDEX embedding ON dim_value_embeddings
USING HNSW
WITH (metric_type = 'COSINE', M = 16, efConstruction = 200);
```

其中：

- `db_name` 从旧数据的 `table_name` 第一段提取
- `table_name` 迁移后统一存储两段式 `schema.table`

### 五、需要修改的查询代码或接口

当前与 `dim_value_embeddings` 直接相关的查询入口主要是 Milvus 适配器中的维度值检索接口。

#### 5.1 维度值检索接口 `search_dim_values`

文件：
- [milvus_adapter.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/services/vector_adapter/milvus_adapter.py#L215)

当前问题：

- 查询时未绑定 `db_name`
- 返回结果中的 `dim_table` 直接取 `table_name`
- 如果 collection 中混有多个业务库的数据，当前实现存在串库风险

改造要求：

- 查询 `dim_value_embeddings` 时，默认附加 `db_name == config.database.database`
- 返回结果中的 `dim_table` 继续使用 `table_name`
- `table_name` 必须保证是两段式 `schema.table`

#### 5.2 维度值命中回填候选表

文件：
- [retriever.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/tools/schema_retrieval/retriever.py#L394)

改造要求：

- 继续使用 `dim_table` 作为候选维度表来源
- 由于 `dim_table` 将改为两段式，因此这里无需再处理数据库名前缀问题

### 六、查询与返回约定

对 `dim_value_embeddings` 的所有查询，统一遵循以下规则：

1. 默认增加 `db_name == config.database.database`
2. 业务层返回表名时使用 `table_name`
3. `table_name` 固定为两段式 `schema.table`
4. 其他字段保持原有含义和返回方式不变

### 七、相关脚本

本次 `dim_value_embeddings` 的 schema 读取脚本位于：

- [inspect_milvus_dim_value_schema.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/tmp/inspect_milvus_dim_value_schema.py)
- [migrate_dim_value_embeddings.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/tmp/migrate_dim_value_embeddings.py)

### 八、改造后预期效果

改造完成后，`dim_value_embeddings` 可以同时满足以下目标：

- 支持多 `db_name` 共存
- 维度值检索默认绑定当前业务库
- 上层拿到的 `dim_table` 统一为两段式 `table_name`
- 与 `table_schema_embeddings` 的表名规范保持一致

## sql_example_embeddings

### 一、当前状态

`sql_example_embeddings` 已完成一轮多 `db_name` 适配迁移。

已通过项目中的 Milvus 连接配置，实际读取 `nl2sql` 数据库中的 collection schema，结果如下：

- Collection 名称：`sql_example_embeddings`
- 描述：`SQL Example Embeddings`
- 主键：`example_id`
- 主键属性：`VARCHAR(256)`，`auto_id=False`
- 当前字段结构：
  - `example_id`：`VARCHAR(256)`，主键
  - `question_sql`：`VARCHAR(16384)`
  - `embedding`：`FLOAT_VECTOR(1024)`
  - `domain`：`VARCHAR(256)`
  - `updated_at`：`INT64`
- 当前向量索引：
  - 字段：`embedding`
  - 索引类型：`HNSW`
  - 相似度度量：`COSINE`
  - 参数：`M=16`，`efConstruction=200`

当前样例数据表明：

- `example_id` 的格式为 `db_name:uuid`
- 例如：`highway_db:0d9b615c`
- `question_sql` 存储的是 JSON 字符串，包含 `question` 和 `sql`

当前 Milvus 中保留了一个历史备份：

- `sql_example_embeddings_old`

### 二、达成共识的字段规则

1. 新增 `db_name` 字段：
   - 类型：`varchar(64)`
   - 值来源：从 `example_id` 的冒号前半段提取
   - 例如 `highway_db:0d9b615c` 中的 `highway_db`
   - 查询绑定来源：`config.yaml` 中的 `database.database`
2. 其他字段保持不变：
   - `example_id`
   - `question_sql`
   - `embedding`
   - `domain`
   - `updated_at`

### 三、为什么这样改

`sql_example_embeddings` 是历史 SQL 示例向量库。如果不同业务库的数据混存在一个 collection 中，而查询阶段没有 `db_name` 过滤，就会把其他业务库的 SQL 示例错误注入当前提示词。

本次改造后：

- `db_name` 单独承担业务库隔离职责
- `example_id` 继续保持原始唯一标识
- Milvus 历史 SQL 检索可以只返回当前业务库的示例

### 四、建表语句

根据实际读取到的当前 schema，可反向整理出当前建表语句如下（伪 DDL，表达结构用）：

```sql
CREATE TABLE sql_example_embeddings (
    example_id VARCHAR(256) PRIMARY KEY,
    question_sql VARCHAR(16384) NOT NULL,
    embedding FLOAT_VECTOR(1024) NOT NULL,
    domain VARCHAR(256) NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX embedding ON sql_example_embeddings
USING HNSW
WITH (metric_type = 'COSINE', M = 16, efConstruction = 200);
```

迁移后的当前建表语句如下：

```sql
CREATE TABLE sql_example_embeddings (
    example_id VARCHAR(256) PRIMARY KEY,
    db_name VARCHAR(64) NOT NULL,
    question_sql VARCHAR(16384) NOT NULL,
    embedding FLOAT_VECTOR(1024) NOT NULL,
    domain VARCHAR(256) NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE INDEX embedding ON sql_example_embeddings
USING HNSW
WITH (metric_type = 'COSINE', M = 16, efConstruction = 200);
```

其中：

- `db_name` 从 `example_id` 的冒号前半段提取
- `example_id` 保持原始唯一标识，不做变更

### 五、需要修改的查询代码或接口

当前与 `sql_example_embeddings` 直接相关的查询入口是 Milvus 适配器中的历史 SQL 检索接口。

#### 5.1 历史 SQL 检索接口 `search_similar_sqls`

文件：
- [milvus_adapter.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/services/vector_adapter/milvus_adapter.py#L279)

当前问题：

- 迁移前 Milvus 分支直接返回空列表，未真正访问 `sql_example_embeddings`
- 如果不绑定 `db_name`，会产生跨业务库的示例污染

改造要求：

- 将 `search_similar_sqls` 改为真正访问 `sql_example_embeddings`
- 查询时默认附加 `db_name == config.database.database`
- 从 `question_sql` JSON 字符串中解析出 `question` 和 `sql`
- 返回结构与现有上层约定保持一致：
  - `question`
  - `sql`
  - `similarity`

#### 5.2 Schema 检索阶段历史 SQL 注入

文件：
- [retriever.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/src/tools/schema_retrieval/retriever.py#L262)

改造要求：

- 保持当前调用方式不变
- 仅替换 Milvus 分支底层实现
- 上层继续接收 `similar_sqls` 列表，不感知 collection 字段变化

### 六、查询与返回约定

对 `sql_example_embeddings` 的所有查询，统一遵循以下规则：

1. 默认增加 `db_name == config.database.database`
2. `example_id` 仅作为原始唯一标识使用
3. 业务层返回值统一为解析后的：
   - `question`
   - `sql`
   - `similarity`

### 七、相关脚本

本次 `sql_example_embeddings` 的结构确认和后续迁移脚本，统一放在 `tmp/` 目录。

- [migrate_sql_example_embeddings.py](/mnt/c/projects/cursor_2025h2/nl2sql_v3/tmp/migrate_sql_example_embeddings.py)

### 八、改造后预期效果

改造完成后，`sql_example_embeddings` 可以同时满足以下目标：

- 支持多 `db_name` 共存
- Milvus 历史 SQL 检索默认绑定当前业务库
- 避免把其他业务库的 SQL 示例注入当前提示词
