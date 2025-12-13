# 60_NL2SQL 模块 Milvus 支持改造方案

## 1. 需求概述

### 1.1 改造目标

在 NL2SQL 模块（特别是 SQL 生成子图）现有 PgVector 支持的基础上，**增加对 Milvus 向量数据库的支持**，使系统能够根据配置灵活选择使用 PgVector 或 Milvus 作为向量检索后端。

**核心原则：**
- ✅ **增量改造**：不移除现有 PgVector 支持，仅新增 Milvus 支持
- ✅ **配置驱动**：通过配置文件控制使用哪个向量数据库
- ✅ **接口统一**：两种向量数据库对外提供统一的检索接口
- ✅ **向量数据二选一**：运行时根据配置只使用一个向量数据库
- ✅ **长期并存**：两种向量数据库选项将长期保持，用户根据部署环境自由选择
- ❌ **不涉及数据迁移**：不需要从 PgVector 迁移数据到 Milvus

### 1.2 业务数据流

```
┌─────────────────┐
│  PostgreSQL     │  ← 业务数据源（表、列、维度值等）
│  (业务数据库)   │
└────────┬────────┘
         │
         │ 数据加载（通过 MetaWeave Loader）
         │
         ├────────────┬─────────────┐
         │            │             │
         ▼            ▼             ▼
    ┌────────┐  ┌─────────┐  ┌──────────┐
    │ Neo4j  │  │PgVector │  │ Milvus   │
    │(关系图)│  │(向量)   │  │(向量)    │
    └────────┘  └─────────┘  └──────────┘
                     │              │
                     └──── 二选一 ───┘
                           ▼
                    ┌──────────────┐
                    │ NL2SQL 模块  │
                    │(SQL生成子图) │
                    └──────────────┘
```

### 1.3 向量数据库对比

#### PgVector（当前实现）

**表结构：**
- `system.sem_object_vec` - 表和列语义向量
- `system.dim_value_index` - 维度值索引（使用 pg_trgm 模糊匹配）
- `system.sql_embedding` - 历史 SQL 向量

**特点：**
- 与业务数据库在同一 PostgreSQL 实例
- 使用 SQL 查询，支持复杂 JOIN 和聚合
- 维度值使用 pg_trgm 模糊匹配（非向量检索）

#### Milvus（新增支持）

**Collection 结构（完整命名：database.collection）：**
- `nl2sql.table_schema_embeddings` - 表和列语义向量（对应 PgVector 的 `system.sem_object_vec`）
- `nl2sql.dim_value_embeddings` - 维度值向量（对应 PgVector 的 `system.dim_value_index`）
- ~~`nl2sql.sql_embeddings`~~ - 历史 SQL 向量（暂不实现，对应 PgVector 的 `system.sql_embedding`）

**命名说明：**
- Milvus database 名称：`nl2sql`（在 Milvus 中，database 相当于 PostgreSQL 的 schema）
- Collection 名称：`table_schema_embeddings`、`dim_value_embeddings`
- 完整引用格式：`database.collection`（如 `nl2sql.table_schema_embeddings`）

**特点：**
- 独立的向量数据库服务
- 高性能向量检索（HNSW 索引）
- 维度值使用向量相似度匹配（区别于 PgVector 的 pg_trgm 模糊匹配）

**⚠️ 重要：Milvus COSINE 距离转换**
- Milvus 使用 `metric_type: "COSINE"` 时，`search()` 返回的是 **cosine distance**
- **Cosine distance = 1 - cosine similarity**（距离越小，相似度越高）
- distance 理论范围：0 到 2（0 表示完全相同，2 表示完全相反）
- 转换公式（原始相似度）：**`raw_similarity = 1.0 - distance`**（cosine similarity，理论范围 -1 到 1）
- **工程约定（对外 score 范围）**：**`similarity = clamp(raw_similarity, 0.0, 1.0)`**，用于阈值过滤与展示（避免负值影响阈值语义/校验）
- 阈值过滤：`similarity >= threshold`（threshold 约定为 0 到 1，与现有配置保持一致）

### 1.4 字段映射关系

#### 表/列语义向量映射

| PgVector | Milvus | 说明 |
|----------|--------|------|
| **表名** | **Collection 名** | **映射关系** |
| `system.sem_object_vec` | `nl2sql.table_schema_embeddings` | 表和列语义向量 |

**字段映射：**

| PgVector 字段 | Milvus 字段 | 说明 |
|-----------------------------------|----------------------------------|------|
| `object_type` | `object_type` | 'table' or 'column' |
| `object_id` | `object_id` (主键) | 如 "public.fact_sales" |
| `parent_id` | `parent_id` | 列的父表ID |
| `text_raw` | `object_desc` | 完整描述文本 |
| `grain_hint` | ❌ (不存在) | **差异：Milvus 无此字段** |
| `time_col_hint` | `time_col_hint` | 时间列提示 |
| `table_category` | `table_category` | 表分类（fact/dimension/bridge） |
| `embedding` | `embedding` | 1024维向量 |
| `updated_at` | `updated_at` | 更新时间戳 |
| `lang` | ❌ | Milvus 不需要 |
| `boost` | ❌ | Milvus 不需要 |
| `attrs` | ❌ | Milvus 不需要 |

**关键差异：**
- ✅ Milvus **缺少 `grain_hint`** 字段
- ✅ 解决方案：在适配器中返回 `None`
- ℹ️ **影响说明**：当前 SQL 生成子图虽然读取该字段，但实际未在提示词中使用，因此缺失不影响 SQL 生成质量

#### 维度值向量映射

| PgVector | Milvus | 说明 |
|----------|--------|------|
| **表名** | **Collection 名** | **映射关系** |
| `system.dim_value_index` | `nl2sql.dim_value_embeddings` | 维度值向量 |

**字段映射：**

| PgVector 字段 | Milvus 字段 | 说明 |
|-----------------------------------|--------------------------------|------|
| `dim_table` | `table_name` | 维表名 |
| `dim_col` | `col_name` | 列名 |
| `value_text` | `col_value` | 维度值文本 |
| `key_col` | ❌（不提供） | 本期 Milvus dim_value 不维护主键信息 |
| `key_value` | ❌（不提供） | 本期 Milvus dim_value 不维护主键值 |
| ~~`value_norm`~~ (pg_trgm) | `embedding` | PgVector用模糊匹配，Milvus用向量 |
| `score` (word_similarity) | `similarity` (cosine) | 匹配分数 |

**关键差异：**
- 当前 MetaWeave 的 `dim_value_embeddings`（`table_name/col_name/col_value`）默认不包含主键列/主键值
- **本方案决策（明确）**：Milvus 维度值检索结果不返回 `key_col/key_value`，提示词侧实现无主键降级展示（避免要求加载侧做主键回填）

#### 历史 SQL 向量映射

| PgVector | Milvus | 说明 |
|----------|--------|------|
| **表名** | **Collection 名** | **映射关系** |
| `system.sql_embedding` | ~~`nl2sql.sql_embeddings`~~ | 历史 SQL 向量 |

**实现状态：**

| PgVector | Milvus | 说明 |
|----------|--------|------|
| ✅ 已实现 | ❌ **暂不实现** | Milvus 适配器当前版本返回空列表，预留接口供未来扩展 |

---

## 2. 配置设计

### 2.1 新增配置：`src/configs/config.yaml`

**重要：** SQL 生成子图模块的配置统一在 `src/configs/config.yaml` 中管理，不访问 `configs/metaweave/` 目录（那是数据加载模块的配置）。

在系统级配置文件 `src/configs/config.yaml` 中新增 `vector_database` 配置段（已添加）：

```yaml
# ==============================================================================
# NL2SQL v3 系统级配置文件
# ==============================================================================

# ------------------------------------------------------------------------------
# 向量数据库配置（用于 SQL 生成子图的向量检索）
# ------------------------------------------------------------------------------
vector_database:
  # 当前激活的向量数据库类型（必填，必须显式填写）
  active: milvus                     # 可选值: pgvector | milvus
                                     # ⚠️ 缺失或为空将导致启动失败（不会自动选择）

  # 提供商配置
  providers:
    # PgVector 配置（复用 database 配置）
    pgvector:
      use_global_config: true        # 使用全局 database 配置
      schema: system                 # 向量数据存储的 schema

    # Milvus 配置
    milvus:
      host: ${MILVUS_HOST:localhost}
      port: ${MILVUS_PORT:19530}
      database: ${MILVUS_DATABASE:nl2sql}  # Milvus database
      user: ${MILVUS_USER:}          # 可选，开源版通常无认证
      password: ${MILVUS_PASSWORD:}  # 可选
      alias: default                 # 连接别名

      # 连接选项
      timeout: 30                    # 连接超时（秒）
      shards_num: 2                  # Collection 分片数

      # 检索参数（可选）
      # - 本方案默认绑定 57/58 的索引：HNSW + COSINE（因此 params 使用 ef）
      # - 若线上索引类型不是 HNSW，需要同步调整 loaders 与此处 params（例如 IVF 用 nprobe）
      search_params:
        metric_type: COSINE
        params:
          ef: 100                    # HNSW 搜索参数：越大召回越高，延迟越高（建议先配置化）

# ------------------------------------------------------------------------------
# Schema 检索配置（现有配置，需调整注释）
# ------------------------------------------------------------------------------
schema_retrieval:
  # 向量检索配置
  topk_tables: 10                    # 表向量检索 Top-K
  topk_columns: 10                   # 列向量检索 Top-K
  similarity_threshold: 0.45         # 相似度阈值（0.0-1.0）

  # 维度值检索配置
  dim_index_topk: 3                  # 维度值检索 Top-K
  dim_value_min_score: 0.4           # 维度值匹配最小分数

  # 历史 SQL 检索配置
  sql_embedding_top_k: 3             # 历史 SQL 相似案例数量
  sql_similarity_threshold: 0.6      # SQL 相似度阈值

  # 注意：当使用 Milvus 时，暂不支持 sql_embedding 检索
  # 系统会自动降级为空结果，不影响 SQL 生成

  # ... 其他现有配置保持不变 ...
```

**向量数据源映射说明：**

根据 `vector_database.active` 配置，系统会访问不同的数据源：

| 检索类型 | `active: pgvector` | `active: milvus` |
|---------|-------------------|------------------|
| **表/列语义检索** | `system.sem_object_vec` | `nl2sql.table_schema_embeddings` |
| **维度值检索** | `system.dim_value_index` | `nl2sql.dim_value_embeddings` |
| **历史 SQL 检索** | `system.sql_embedding` | ❌ 暂不支持（返回空列表） |

**⚠️ 重要提示：**
- 两个向量数据库的数据是**独立加载**的，使用不同的数据加载器
- PgVector 数据由现有流程加载到 PostgreSQL 的 `system` schema
- Milvus 数据由 MetaWeave Loader（参考文档 57、58）加载到 `nl2sql` database
- 运行时根据配置**只使用一个**向量数据库，不会同时访问两个数据源

**配置说明：**
- `active`: 决定使用哪个向量数据库（`pgvector` 或 `milvus`）
  - ⚠️ **必须明确指定**，配置缺失将抛出异常
  - 示例中使用 `milvus` 作为推荐配置，两种选项长期并存，用户根据环境选择
- PgVector 通过 `use_global_config: true` 复用 `database` 配置
- Milvus 配置独立，使用环境变量支持部署灵活性

**配置文件位置：**
- ✅ SQL 生成子图模块配置：`src/configs/config.yaml`（已添加）
- ❌ **不要访问**：`configs/metaweave/metadata_config.yaml`（数据加载模块专用）

**⚠️ 配置独立性说明：**
- NL2SQL 模块和 MetaWeave 数据加载模块各自维护独立的 `vector_database` 配置
- NL2SQL 使用：`src/configs/config.yaml`
- MetaWeave 使用：`configs/metaweave/metadata_config.yaml`
- 原因：MetaWeave 是相对独立的模块，未来可能从 NL2SQL 项目中分离，因此不应产生配置依赖
- 两份配置需要保持一致（手动管理）：`active` 字段和对应 provider 的连接参数应相同
- **代码依赖解耦（方案选择）**：NL2SQL 运行时不应直接依赖 `src/metaweave/` 下的实现；Milvus 客户端下沉到 `src/services/` 作为公共组件，供 NL2SQL 与 MetaWeave 共同复用

### 2.2 配置读取逻辑

```python
# ✅ 方案A：vector_database 由全局配置提供（src/configs/config.yaml）
# SchemaRetriever 入参 config 仍然是子图配置（sql_generation_subgraph.yaml），仅用于读取 schema_retrieval 等子图参数。
def __init__(self, config: Dict[str, Any] = None):
    self.config = config or {}

    # 从全局配置读取向量数据库配置（不依赖子图配置传入）
    from src.services.config_loader import get_config
    vector_db_config = get_config().get("vector_database")

    # ⚠️ 配置缺失检查：必须明确指定向量数据库类型
    if not vector_db_config:
        raise ValueError(
            "缺少 vector_database 配置，请在 src/configs/config.yaml 中配置 "
            "vector_database.active (pgvector 或 milvus)"
        )

    self.vector_db_type = vector_db_config.get("active")
    if not self.vector_db_type:
        raise ValueError(
            "缺少 vector_database.active 配置，请明确指定使用 pgvector 或 milvus"
        )

    # 根据配置创建适配器
    if self.vector_db_type == "milvus":
        self.vector_client = MilvusAdapter(vector_db_config)
    elif self.vector_db_type == "pgvector":
        self.vector_client = PgVectorAdapter(vector_db_config)
    else:
        raise ValueError(
            f"不支持的向量数据库类型: {self.vector_db_type}，"
            f"仅支持 pgvector 或 milvus"
        )
```

**配置加载路径：**
```python
# 在 schema_retrieval_node 中
from src.services.config_loader import load_subgraph_config

def schema_retrieval_node(state: SQLGenerationState):
    # 仅加载子图配置（sql_generation_subgraph.yaml），不包含全局 config.yaml
    config = load_subgraph_config("sql_generation")

    # 初始化 SchemaRetriever：
    # - 子图参数：从 config（子图配置）读取
    # - 向量数据库参数：SchemaRetriever 内部从全局 src/configs/config.yaml 读取 vector_database
    retriever = SchemaRetriever(config)

    # 后续所有向量数据库操作通过 retriever.vector_client 完成
    # ⚠️ 不再直接使用 retriever.pg_client 访问向量表
```

**SchemaRetriever 改造要点：**

改造后的 `SchemaRetriever` 类结构：
```python
class SchemaRetriever:
    def __init__(self, config: Dict[str, Any] = None):
        # 业务数据库客户端（仍然保留，用于执行生成的 SQL、验证结果等）
        self.pg_client = get_pg_client()

        # 图数据库客户端（用于 JOIN 路径查询）
        self.neo4j_client = get_neo4j_client()

        # 向量数据库客户端（通过适配器访问）
        self.vector_client = create_vector_adapter(config)  # 新增

    def retrieve(self, query: str, ...):
        # ✅ 正确：通过适配器访问向量数据库（包括向量检索和精确查询）
        # 向量检索
        semantic_tables = self.vector_client.search_tables(...)
        semantic_columns = self.vector_client.search_columns(...)
        dim_value_hits = self.vector_client.search_dim_values(...)
        similar_sqls = self.vector_client.search_similar_sqls(...)
        
        # 精确查询（基于表名查询表定义信息）
        table_cards = self.vector_client.fetch_table_cards(...)
        table_categories = self.vector_client.fetch_table_categories(...)

        # ❌ 错误：不再直接调用 pg_client 的向量相关方法
        # semantic_tables = self.pg_client.search_semantic_tables(...)
```

**⚠️ 关键原则：**
- `self.pg_client` 仅用于**业务数据库**操作（执行生成的 SQL、验证结果等）
- `self.vector_client` 用于**向量数据库**的所有操作：
  - 向量检索：`search_tables()`, `search_columns()`, `search_dim_values()`, `search_similar_sqls()`
  - 精确查询：`fetch_table_cards()`, `fetch_table_categories()`（基于表名查询表定义信息）
- **⚠️ 重要**：在 Milvus 模式下，SQL 生成过程（查询元数据、构建提示词）的所有“向量/索引元数据”均从 Milvus 获取，不会访问 PostgreSQL 的 `system.sem_object_vec`、`system.dim_value_index` 等向量索引表
- 注意：`fetch_table_cards()` 和 `fetch_table_categories()` 是**精确查询**（使用 `collection.query()`），不是向量检索

---

### 2.3 现状差距（必须改哪里）

本节用于对齐“方案 vs 现状代码”的差距点，明确实现 Milvus 支持时**必须改动**的位置，避免出现 `vector_database.active: milvus` 但仍访问 PgVector/PG 向量索引表的情况。

#### 2.3.1 SchemaRetriever 当前仍写死 PgVector 的点（必须替换为适配器）

以下位置即使配置 `active: milvus` 也会访问 PG 向量索引表，必须替换为 `vector_client`：

- `src/tools/schema_retrieval/retriever.py:102`：日志写死 “pgvector”，且表/列检索调用 `self.pg_client.search_semantic_tables()`、`self.pg_client.search_semantic_columns()`（实际查询 `system.sem_object_vec`）
- `src/tools/schema_retrieval/retriever.py:224`：表卡片直接从 `system.sem_object_vec` 读取：`self.pg_client.fetch_table_cards()`
- `src/tools/schema_retrieval/retriever.py:451`：表分类补全直接从 `system.sem_object_vec` 读取：`self.pg_client.fetch_table_categories()`
- `src/tools/schema_retrieval/retriever.py:236`：历史 SQL 检索调用 `self.pg_client.search_similar_sqls()`（`active: milvus` 需明确走 Milvus 适配器的“降级空列表”逻辑）
- `src/tools/schema_retrieval/retriever.py:762`：维度值检索调用 `self.pg_client.search_dim_values()`（实际查询 `system.dim_value_index`）

#### 2.3.2 维度值提示词对字段的硬依赖（容易漏）

维度值命中不仅用于“回填候选维表”，还会直接进入提示词：

- `src/modules/sql_generation/subgraph/nodes/sql_generation.py:170` 调用 `format_dim_value_matches_for_prompt(dim_value_hits)`
- `src/tools/schema_retrieval/value_matcher.py:115` 当前会构造 `"{dim_table}.{key_col}='{key_value}'"`（对 `key_col/key_value` 存在硬依赖）

**本方案决策（明确）：**
- Milvus 维度值检索结果不返回 `key_col/key_value`（原因：加载侧目前不维护主键信息，回填成本高且耦合业务表结构）
- 因此必须在实现阶段修改 `value_matcher.format_dim_value_matches_for_prompt()`：当缺失 `key_col/key_value` 时，降级为“展示匹配到的维表/列/文本 + 分数”，不再拼接主键过滤条件

## 3. 架构设计

### 3.1 向量检索适配器模式

引入**适配器模式**统一 PgVector 和 Milvus 的检索接口：

```
┌──────────────────────────────────────────┐
│         SchemaRetriever                  │
│      (Schema 检索协调器)                  │
└──────────────┬───────────────────────────┘
               │
               │ 依赖
               ▼
┌──────────────────────────────────────────┐
│     BaseVectorAdapter (抽象基类)         │
│  - search_tables(embedding, top_k)       │
│  - search_columns(embedding, top_k)      │
│  - search_dim_values(query, top_k)       │
│  - search_similar_sqls(embedding, top_k) │
└──────────────┬───────────────────────────┘
               │
      ┌────────┴─────────┐
      │                  │
      ▼                  ▼
┌────────────┐    ┌──────────────┐
│ PgVector   │    │   Milvus     │
│  Adapter   │    │   Adapter    │
└────────────┘    └──────────────┘
      │                  │
      ▼                  ▼
┌────────────┐    ┌──────────────┐
│ PGClient   │    │MilvusClient  │
│ (现有)     │    │  (新增)      │
└────────────┘    └──────────────┘
```

### 3.2 统一返回格式

所有适配器方法返回统一的数据格式：

#### `search_tables()` 返回格式

```python
[
    {
        "object_id": "public.fact_sales",
        "grain_hint": "交易明细",           # PgVector 有，Milvus 返回 None
        "time_col_hint": "order_date,created_at",
        "table_category": "事实表",
        "similarity": 0.85
    },
    # ...
]
```

#### `search_columns()` 返回格式

```python
[
    {
        "object_id": "public.fact_sales.amount",
        "parent_id": "public.fact_sales",
        "table_category": "事实表",          # 列的父表分类
        "similarity": 0.78
    },
    # ...
]
```

#### `search_dim_values()` 返回格式

```python
[
    {
        "query_value": "京东便利店",        # 用户查询的原始值
        "dim_table": "public.dim_store",    # 维表全名
        "dim_col": "store_name",            # 列名
        "matched_text": "京东便利店(西湖店)", # 匹配到的文本
        "score": 0.92,                      # 相似度分数
    },
    # ...
]
```

#### `search_similar_sqls()` 返回格式

```python
# PgVector 正常返回
[
    {
        "question": "查询上个月销售额",
        "sql": "SELECT SUM(amount) FROM ...",
        "similarity": 0.75
    },
    # ...
]

# Milvus 返回空列表（暂不支持）
[]
```

---

## 4. 模块结构设计

### 4.1 文件变更清单

**新增文件：**

```
src/
└── services/
    ├── vector_db/                         # 新增：向量数据库公共客户端（NL2SQL/MetaWeave 共用）
    │   ├── __init__.py
    │   └── milvus_client.py               # 新增：MilvusClient（从 metaweave 下沉）
    └── vector_adapter/                    # 新增：向量适配器模块
        ├── __init__.py                    # 新增：模块导出
        ├── base.py                        # 新增：BaseVectorAdapter 抽象基类
        ├── pgvector_adapter.py            # 新增：PgVector 适配器实现
        ├── milvus_adapter.py              # 新增：Milvus 适配器实现
        └── factory.py                     # 新增：适配器工厂函数
```

**修改文件：**

```
src/
├── configs/
│   └── config.yaml                        # 修改：新增 vector_database 配置段
│
└── tools/
    └── schema_retrieval/
        └── retriever.py                   # 修改：使用适配器替换直接调用 PGClient
```

**受影响文件（按“必须改/必须评估/需要迁移/可能受影响”拆分）：**

**必须修改（Milvus 模式不得再访问 PG 向量索引表）：**
- `src/tools/schema_retrieval/retriever.py`（5 处写死：102、224、236、451、762；见 2.3.1）

**必须修改（按本方案决策）：**
- `src/tools/schema_retrieval/value_matcher.py`（实现无主键降级展示；Milvus dim_value 不返回 `key_col/key_value`）

**必须评估（可能无需改，但必须验证）：**
- `src/modules/sql_generation/subgraph/nodes/sql_generation.py`（消费 `dim_value_hits` 的提示词展示效果与降级分支）

**需要迁移/调整（模块解耦，方案 1）：**
- `src/services/vector_db/milvus_client.py`（公共 MilvusClient：从 MetaWeave 下沉）
- `src/metaweave/services/vector_db/__init__.py`（改为复用 `src/services/vector_db` 或保留兼容 re-export）
- `src/metaweave/services/vector_db/milvus_client.py`（改为复用/兼容层；NL2SQL 不再直接依赖此路径）

**可能受影响（本期不改；仅在未来补主键信息时才改）：**
- `src/metaweave/core/loaders/dim_value_loader.py`（本方案不回填 `key_col/key_value`，保持现状）

**说明：**
- ⚠️ `vector_database` 选择与连接参数仅在 `src/configs/config.yaml` 中管理
- ✅ `sql_generation_subgraph.yaml` 仅保留检索阈值/TopK 等参数，不包含 `vector_database`
- ❌ **不要**在 `sql_generation_subgraph.yaml` 中添加 `vector_database` 配置

### 4.2 核心类设计

#### 4.2.1 BaseVectorAdapter (base.py)

```python
"""向量数据库适配器基类"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseVectorAdapter(ABC):
    """向量检索适配器基类

    统一 PgVector 和 Milvus 的检索接口
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化适配器

        Args:
            config: 向量数据库配置
        """
        self.config = config

    @abstractmethod
    def search_tables(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索语义相关的表

        Args:
            embedding: 查询向量
            top_k: 返回 Top-K 个结果
            similarity_threshold: 相似度阈值

        Returns:
            表信息列表，每个元素包含：
            - object_id: 表ID
            - grain_hint: 粒度提示（Milvus 可能为 None）
            - time_col_hint: 时间列提示
            - table_category: 表分类
            - similarity: 相似度分数
        """
        pass

    @abstractmethod
    def search_columns(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索语义相关的列

        Args:
            embedding: 查询向量
            top_k: 返回 Top-K 个结果
            similarity_threshold: 相似度阈值

        Returns:
            列信息列表，每个元素包含：
            - object_id: 列ID
            - parent_id: 父表ID
            - table_category: 父表分类
            - similarity: 相似度分数
        """
        pass

    @abstractmethod
    def search_dim_values(
        self,
        query_value: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """检索维度值匹配

        Args:
            query_value: 查询的维度值
            top_k: 返回 Top-K 个结果

        Returns:
            维度值匹配列表，每个元素包含：
            - query_value: 查询值
            - dim_table: 维表名
            - dim_col: 列名
            - matched_text: 匹配到的文本
            - score: 相似度分数
        """
        pass

    @abstractmethod
    def search_similar_sqls(
        self,
        embedding: List[float],
        top_k: int = 3,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索历史相似 SQL

        Args:
            embedding: 查询向量
            top_k: 返回 Top-K 个结果
            similarity_threshold: 相似度阈值

        Returns:
            相似 SQL 列表，每个元素包含：
            - question: 问题文本
            - sql: SQL 语句
            - similarity: 相似度分数

        Note:
            Milvus 适配器当前版本返回空列表
        """
        pass

    @abstractmethod
    def fetch_table_cards(self, table_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """获取表卡片（表的详细描述）

        Args:
            table_names: 表名列表

        Returns:
            表卡片字典，key为表名，value为表卡片信息
        """
        pass

    @abstractmethod
    def fetch_table_categories(self, table_names: List[str]) -> Dict[str, str]:
        """批量查询表的 table_category 字段

        Args:
            table_names: 表名列表

        Returns:
            {table_id: table_category} 字典
        """
        pass
```

#### 4.2.2 PgVectorAdapter (pgvector_adapter.py)

```python
"""PgVector 适配器 - 封装现有 PGClient"""

from typing import Any, Dict, List

from src.services.db.pg_client import get_pg_client
from src.services.vector_adapter.base import BaseVectorAdapter


class PgVectorAdapter(BaseVectorAdapter):
    """PgVector 适配器

    封装现有 PGClient，保持接口一致性
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.pg_client = get_pg_client()

    def search_tables(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索表（直接调用 PGClient）"""
        return self.pg_client.search_semantic_tables(
            embedding=embedding,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

    def search_columns(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索列（直接调用 PGClient）"""
        return self.pg_client.search_semantic_columns(
            embedding=embedding,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

    def search_dim_values(
        self,
        query_value: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """检索维度值（直接调用 PGClient）"""
        results = self.pg_client.search_dim_values(
            query_value=query_value,
            top_k=top_k,
        )

        # 添加 query_value 字段（统一格式）
        for r in results:
            r["query_value"] = query_value

        return results

    def search_similar_sqls(
        self,
        embedding: List[float],
        top_k: int = 3,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索历史 SQL（直接调用 PGClient）"""
        return self.pg_client.search_similar_sqls(
            embedding=embedding,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )

    def fetch_table_cards(self, table_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """获取表卡片（直接调用 PGClient）"""
        return self.pg_client.fetch_table_cards(table_names)

    def fetch_table_categories(self, table_names: List[str]) -> Dict[str, str]:
        """批量查询表的 table_category 字段（直接调用 PGClient）"""
        return self.pg_client.fetch_table_categories(table_names)
```

#### 4.2.3 MilvusAdapter (milvus_adapter.py)

```python
"""Milvus 适配器 - 实现 Milvus 向量检索"""

from typing import Any, Dict, List

from src.services.vector_db.milvus_client import MilvusClient, _lazy_import_milvus
from src.services.vector_adapter.base import BaseVectorAdapter
from src.utils.logger import get_module_logger

logger = get_module_logger("milvus_adapter")


class MilvusAdapter(BaseVectorAdapter):
    """Milvus 适配器

    从 Milvus 的 nl2sql.table_schema_embeddings 和 nl2sql.dim_value_embeddings
    Collection 检索数据

    注意：
    - 完整 Collection 引用格式：database.collection（如 nl2sql.table_schema_embeddings）
    - 代码中仅使用 collection 名称（如 table_schema_embeddings）
    - MilvusClient 连接时已通过 db.using_database("nl2sql") 切换到正确的 database
    """

    # Collection 名称（不含 database 前缀，MilvusClient 已切换到 nl2sql database）
    # 对应 PgVector: system.sem_object_vec → Milvus: nl2sql.table_schema_embeddings
    COLLECTION_TABLE_SCHEMA = "table_schema_embeddings"
    # 对应 PgVector: system.dim_value_index → Milvus: nl2sql.dim_value_embeddings
    COLLECTION_DIM_VALUE = "dim_value_embeddings"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # 从 vector_database 配置中读取 Milvus 配置
        # config 来自 src/configs/config.yaml 的 vector_database（包含 providers）
        providers = config.get("providers", {})
        milvus_config = providers.get("milvus", {})

        if not milvus_config:
            raise ValueError(
                "Milvus 配置缺失，请在 src/configs/config.yaml 中配置 "
                "vector_database.providers.milvus"
            )

        # 保存为实例变量，供各方法复用
        self.milvus_config = milvus_config

        # 初始化 Milvus 客户端
        self.milvus_client = MilvusClient(self.milvus_config)
        self.milvus_client.connect()

        logger.info(
            "Milvus 适配器初始化成功: %s:%s/%s",
            self.milvus_config.get("host"),
            self.milvus_config.get("port"),
            self.milvus_config.get("database"),
        )

    def _get_search_params(self) -> Dict[str, Any]:
        """读取检索参数（默认绑定 HNSW + COSINE；支持配置覆盖）。"""
        return self.milvus_config.get("search_params") or {
            "metric_type": "COSINE",
            "params": {"ef": 100},  # HNSW 搜索参数（IVF 等索引需用各自参数）
        }

    def search_tables(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """从 Milvus 检索表"""
        _, _, _, _, Collection, _, _ = _lazy_import_milvus()

        collection = Collection(self.COLLECTION_TABLE_SCHEMA, using=self.milvus_client.alias)

        search_params = self._get_search_params()

        results = collection.search(
            data=[embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            # ⚠️ expr 中的字符串字面量建议使用双引号（Milvus 官方示例通常使用双引号；以兼容性为优先）
            expr='object_type == "table"',
            output_fields=[
                "object_id",
                "time_col_hint",
                "table_category",
                "updated_at",
            ],
        )

        # 转换为统一格式
        tables = []
        for hit in results[0]:
            # ⚠️ 关键：Milvus COSINE distance 转换为 similarity
            # raw_similarity = 1 - distance  (cosine similarity，理论范围 [-1, 1])
            distance = float(hit.distance)
            raw_similarity = 1.0 - distance
            similarity = max(0.0, min(1.0, raw_similarity))  # 工程约定：clamp 到 [0, 1]

            # 过滤：与 PgVector 一致，使用 >= threshold
            if similarity < similarity_threshold:
                continue

            tables.append(
                {
                    "object_id": hit.entity.get("object_id"),
                    "grain_hint": None,  # Milvus 无此字段
                    "time_col_hint": hit.entity.get("time_col_hint"),
                    "table_category": hit.entity.get("table_category", ""),
                    "similarity": similarity,  # 返回相似度（0-1，clamp 后），与 PgVector 阈值语义一致
                }
            )

        return tables

    def search_columns(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """从 Milvus 检索列"""
        _, _, _, _, Collection, _, _ = _lazy_import_milvus()

        collection = Collection(self.COLLECTION_TABLE_SCHEMA, using=self.milvus_client.alias)

        search_params = self._get_search_params()

        results = collection.search(
            data=[embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr='object_type == "column"',
            output_fields=[
                "object_id",
                "parent_id",
                "table_category",
            ],
        )

        # 转换为统一格式
        columns = []
        for hit in results[0]:
            # ⚠️ COSINE distance 转换为 similarity
            distance = float(hit.distance)
            raw_similarity = 1.0 - distance  # cosine similarity，理论范围 [-1, 1]
            similarity = max(0.0, min(1.0, raw_similarity))  # 工程约定：clamp 到 [0, 1]

            if similarity < similarity_threshold:
                continue

            columns.append(
                {
                    "object_id": hit.entity.get("object_id"),
                    "parent_id": hit.entity.get("parent_id"),
                    "table_category": hit.entity.get("table_category", ""),
                    "similarity": similarity,  # 返回相似度（0-1，clamp 后）
                }
            )

        return columns

    def search_dim_values(
        self,
        query_value: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """从 Milvus 检索维度值（使用向量相似度）"""
        # 先对查询值向量化
        from src.services.embedding.embedding_client import get_embedding_client
        embedding_client = get_embedding_client()
        query_embedding = embedding_client.embed_query(query_value)

        _, _, _, _, Collection, _, _ = _lazy_import_milvus()

        collection = Collection(self.COLLECTION_DIM_VALUE, using=self.milvus_client.alias)

        # 与表/列一致：默认绑定 HNSW + COSINE；建议通过配置覆盖
        search_params = self._get_search_params()

        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            output_fields=[
                "table_name",
                "col_name",
                "col_value",
            ],
        )

        # 转换为统一格式
        matches = []
        for hit in results[0]:
            # ⚠️ COSINE distance 转换为 score（相似度）
            distance = float(hit.distance)
            raw_score = 1.0 - distance  # cosine similarity，理论范围 [-1, 1]
            score = max(0.0, min(1.0, raw_score))  # 工程约定：clamp 到 [0, 1]

            matches.append(
                {
                    "query_value": query_value,
                    "dim_table": hit.entity.get("table_name"),
                    "dim_col": hit.entity.get("col_name"),
                    "matched_text": hit.entity.get("col_value"),
                    "score": score,  # 相似度（0-1，clamp 后），与 PgVector 阈值语义一致
                }
            )

        return matches

    def search_similar_sqls(
        self,
        embedding: List[float],
        top_k: int = 3,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """检索历史 SQL（Milvus 当前版本暂不支持）"""
        logger.warning("Milvus 适配器暂不支持历史 SQL 检索，返回空列表")
        return []

    def fetch_table_cards(self, table_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """获取表卡片（精确查询，不是向量检索）
        
        基于表名列表，从 Milvus 精确查询表的定义信息。
        使用 collection.query()（精确匹配），不使用 collection.search()（向量检索）。
        """
        if not table_names:
            return {}

        import json
        _, _, _, _, Collection, _, _ = _lazy_import_milvus()

        collection = Collection(self.COLLECTION_TABLE_SCHEMA, using=self.milvus_client.alias)

        # ⚠️ 安全：构建查询表达式，使用 JSON 序列化确保格式正确
        # Milvus 表达式需要：object_id in ["table1", "table2"]
        # 不能是 Python 格式：object_id in ['table1', 'table2']
        expr = f"object_id in {json.dumps(table_names)}"

        # 精确查询（不需要向量检索，直接 query）
        results = collection.query(
            expr=expr,
            output_fields=[
                "object_id",
                "object_desc",
                "time_col_hint",
            ],
        )

        # 转换为字典格式
        cards = {}
        for row in results:
            cards[row["object_id"]] = {
                "text_raw": row.get("object_desc", ""),
                "grain_hint": None,  # Milvus 无此字段
                "time_col_hint": row.get("time_col_hint"),
            }

        return cards

    def fetch_table_categories(self, table_names: List[str]) -> Dict[str, str]:
        """批量查询表的 table_category 字段（精确查询，不是向量检索）
        
        基于表名列表，从 Milvus 精确查询表的分类信息。
        使用 collection.query()（精确匹配），不使用 collection.search()（向量检索）。
        """
        if not table_names:
            return {}

        import json
        _, _, _, _, Collection, _, _ = _lazy_import_milvus()

        collection = Collection(self.COLLECTION_TABLE_SCHEMA, using=self.milvus_client.alias)

        # ⚠️ 安全：构建查询表达式，使用 JSON 序列化确保格式正确
        # Milvus 表达式需要：object_id in ["table1", "table2"]
        expr = f"object_id in {json.dumps(table_names)}"

        # 精确查询（只需要 object_id 和 table_category）
        results = collection.query(
            expr=expr,
            output_fields=["object_id", "table_category"],
        )

        # 转换为字典格式
        categories = {}
        for row in results:
            category = row.get("table_category") or ""
            if category:  # 只记录非空的类型
                categories[row["object_id"]] = category

        return categories
```

---

## 5. 改造实施步骤

### 5.1 第一阶段：配置与适配器基础（优先级 P0）

#### 任务 1.1：新增向量适配器模块

**文件：** `src/services/vector_adapter/`

1. 创建 `base.py` - 定义 `BaseVectorAdapter` 抽象基类
2. 创建 `pgvector_adapter.py` - 封装现有 PGClient
3. 创建 `__init__.py` - 导出适配器类

**验收标准：**
- PgVectorAdapter 能够正常调用现有 PGClient 的所有方法
- 单元测试覆盖所有适配器方法

#### 任务 1.2：配置文件扩展

**文件：** `src/configs/config.yaml`

1. 在配置文件中新增 `vector_database` 配置段
2. 明确指定 `active` 字段（pgvector 或 milvus）

**验收标准：**
- 配置加载逻辑能够正确读取 `vector_database.active`
- 配置缺失时抛出明确的异常信息

#### 任务 1.3：SchemaRetriever 适配器集成

**文件：** `src/tools/schema_retrieval/retriever.py`

**改造步骤：**

1. 在 `SchemaRetriever.__init__()` 中读取 `vector_database` 配置
2. 根据配置创建对应的适配器实例（`self.vector_client`）
3. 替换所有 `self.pg_client` 调用为 `self.vector_client`，包括：
   - ✅ `search_semantic_tables()` → `vector_client.search_tables()`
   - ✅ `search_semantic_columns()` → `vector_client.search_columns()`
   - ✅ `search_dim_values()` → `vector_client.search_dim_values()`
   - ✅ `fetch_table_cards()` → `vector_client.fetch_table_cards()`
   - ✅ `fetch_table_categories()` → `vector_client.fetch_table_categories()`
   - ✅ `search_similar_sqls()` → `vector_client.search_similar_sqls()`

**⚠️ 重要：** 所有与向量数据库交互的方法都必须通过适配器调用，确保在 Milvus 模式下不会访问 PostgreSQL 的向量表。
（现有 `retriever.py` 中表卡片/表类别/维度值/历史 SQL 仍使用 `pg_client`，需一并替换。）

**验收标准：**
- 使用 `active: pgvector` 配置时，能够正常调用 PgVectorAdapter
- 使用 `active: milvus` 配置时，能够正常调用 MilvusAdapter
- 配置缺失或无效时，抛出清晰的异常信息
- Milvus 模式下不会访问 PostgreSQL 的 `system.sem_object_vec` 等表
- 集成测试通过，SQL 生成结果正确

### 5.2 第二阶段：Milvus 适配器实现（优先级 P0）

#### 任务 2.1：MilvusAdapter 实现

**文件：** `src/services/vector_adapter/milvus_adapter.py`

**实现方法清单：**

1. 实现 `MilvusAdapter` 类，继承 `BaseVectorAdapter`
2. 实现 `search_tables()` 方法 - 从 `nl2sql.table_schema_embeddings` 检索表
   - ⚠️ 必须包含 COSINE distance → similarity 转换
3. 实现 `search_columns()` 方法 - 从 `nl2sql.table_schema_embeddings` 检索列
   - ⚠️ 必须包含 COSINE distance → similarity 转换
4. 实现 `search_dim_values()` 方法 - 从 `nl2sql.dim_value_embeddings` 检索维度值
   - ⚠️ 必须包含 COSINE distance → similarity 转换
5. 实现 `fetch_table_cards()` 方法 - 从 `nl2sql.table_schema_embeddings` 查询表卡片
   - ⚠️ 使用安全的查询表达式：`json.dumps(table_names)`
6. 实现 `fetch_table_categories()` 方法 - 从 `nl2sql.table_schema_embeddings` 查询表分类
   - ⚠️ 使用安全的查询表达式：`json.dumps(table_names)`
7. 实现 `search_similar_sqls()` 方法 - 返回空列表并记录日志
   - 当前版本暂不支持，预留接口供未来扩展

**验收标准：**
- 所有方法返回格式与 PgVectorAdapter 一致
- 字段缺失处理正确（`grain_hint` 返回 `None`）
- COSINE distance 转换正确（`raw = 1.0 - distance`，并按约定 `similarity = clamp(raw, 0.0, 1.0)`）
- 查询表达式安全（使用 `json.dumps`）
- Milvus 连接异常时能够友好报错

#### 任务 2.2：字段兼容性处理

**文件：**
- `src/tools/schema_retrieval/join_planner.py`
- `src/modules/sql_generation/subgraph/nodes/sql_generation.py`
- `src/tools/schema_retrieval/value_matcher.py`

1. 提示词生成时，兼容 `grain_hint` 为 `None` 的情况
2. 维度值匹配结果格式化：实现无主键降级展示（Milvus 不返回 `key_col/key_value`）

**修改示例（无主键降级）：**

```python
# 原逻辑（src/tools/schema_retrieval/value_matcher.py）
suggested_condition = f"{m['dim_table']}.{m['key_col']}='{m['key_value']}'"
lines.append(
    f"- '{m['query_value']}' → {suggested_condition} "
    f"(匹配: {m['matched_text']}, 相似度: {m['score']:.2f})"
)

# 修改后：当缺失 key_col/key_value 时降级展示（Milvus）
if m.get("key_col") and m.get("key_value"):
    suggested_condition = f"{m['dim_table']}.{m['key_col']}='{m['key_value']}'"
    lines.append(
        f"- '{m['query_value']}' → {suggested_condition} "
        f"(匹配: {m['matched_text']}, 相似度: {m['score']:.2f})"
    )
else:
    lines.append(
        f"- '{m.get('query_value', '')}' → {m.get('dim_table', '')}.{m.get('dim_col', '')} "
        f"(匹配值: {m.get('matched_text', '')}, 相似度: {m.get('score', 0.0):.2f}, 建议人工确认或使用 LIKE 匹配)"
    )
```

**验收标准：**
- 使用 Milvus 时，提示词中不包含 `grain_hint`（或显示为空）
- 维度值提示词格式正确

### 5.3 第三阶段：测试与验证（优先级 P1）

#### 任务 3.1：单元测试

**新增文件：**
- `tests/unit/vector_adapter/test_pgvector_adapter.py`
- `tests/unit/vector_adapter/test_milvus_adapter.py`

**测试覆盖：**
- 所有适配器方法的正常流程
- 边界条件：空结果、异常处理
- 字段映射正确性

#### 任务 3.2：集成测试

**新增文件：**
- `tests/integration/test_schema_retrieval_with_milvus.py`

**测试场景：**
1. 使用 PgVector 配置，验证 SQL 生成结果
2. 使用 Milvus 配置，验证 SQL 生成结果
3. ~~对比两种配置的结果差异~~（暂不实施，待 PgVector 改造完成后再进行对比）

#### 任务 3.3：端到端测试

**测试流程：**
1. 准备测试数据：加载数据到 Milvus
2. 运行测试查询，验证 Milvus 模式下的 SQL 生成
3. 验证生成的 SQL 能够正确执行

**注意：** PgVector 与 Milvus 的数据一致性测试暂不进行，待 PgVector 改造完成后再统一验证。

### 5.4 第四阶段：文档与部署（优先级 P2）

#### 任务 4.1：更新配置文档

**文件：** `docs/gen_rag/60.1_NL2SQL_Milvus配置指南.md`

1. 说明如何切换向量数据库
2. 配置示例
3. 常见问题

#### 任务 4.2：更新部署文档

**文件：** `docs/deployment/vector_database_setup.md`

1. Milvus 环境部署
2. 数据加载步骤
3. 性能对比

---

## 6. 关键决策与风险

### 6.1 设计决策

| 决策 | 理由 | 影响 |
|------|------|------|
| **使用适配器模式** | 统一接口，易于扩展 | 增加一层抽象，但提高可维护性 |
| **配置驱动切换** | 灵活性高，无需修改代码 | 运行时只使用一种向量数据库 |
| **⚠️ COSINE 距离必须转换** | Milvus 返回 distance，需转换为 similarity | **关键**：`raw = 1.0 - distance`，并按约定 `similarity = clamp(raw, 0.0, 1.0)`，否则阈值过滤会错误 |
| **MilvusClient 下沉到公共层** | 与“模块可拆分”口径一致 | NL2SQL 不再直接依赖 `src/metaweave/`；MetaWeave/NL2SQL 共用 `src/services/vector_db` |
| **grain_hint 返回 None** | Milvus 无此字段，兼容处理 | 提示词生成需兼容 |
| **维度值不返回 key_col/key_value** | 降低加载侧耦合与成本 | 提示词侧必须实现无主键降级展示（不再拼接主键过滤条件） |
| **历史 SQL 暂不支持 Milvus** | 优先级低，预留接口 | 不影响主流程 |

### 6.1.1 重要：Milvus COSINE 距离转换详解

**问题：** Milvus 的 COSINE 距离与相似度方向相反

**原因：**
- PgVector 使用 `1 - (embedding <=> vector)` 计算相似度（`<=>` 是 cosine 距离）
  - 结果：这是 cosine similarity（理论范围 -1 到 1）；工程上通常只关心 >=0 的部分
  - 阈值过滤：`similarity >= threshold`

- Milvus 使用 `metric_type: "COSINE"` 时：
  - `search()` 返回的是 **cosine distance**（距离，不是相似度）
  - **Cosine distance = 1 - cosine similarity**
  - 范围：0 到 2（0 表示完全相同，2 表示完全相反）

**解决方案：**
```python
# ✅ 正确的转换方式
distance = float(hit.distance)
raw_similarity = 1.0 - distance  # cosine similarity，理论范围 [-1, 1]
similarity = max(0.0, min(1.0, raw_similarity))  # 工程约定：clamp 到 [0, 1]

# 过滤：与 PgVector 保持一致
if similarity >= similarity_threshold:
    # 通过
```

**错误示例：**
```python
# ❌ 错误：直接使用 distance 作为 similarity
similarity = float(hit.distance)  # 错误！distance 越小表示越相似
if similarity >= threshold:  # 这会排除高相似度结果！
    pass
```

**参考：**
- Milvus 官方文档：[Distance Metrics](https://milvus.io/docs/metric.md#COSINE)
- 57 号文档：`dim_value_embeddings` Collection 使用 COSINE 索引
- 58 号文档：`table_schema_embeddings` Collection 使用 COSINE 索引

### 6.2 风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| **⚠️ COSINE 距离转换错误** | **严重**：阈值过滤失效，检索结果错误 | **强制代码审查 + 自动化测试**：所有 Milvus 检索必须包含 `raw = 1.0 - distance` 且按约定 `similarity = clamp(raw, 0.0, 1.0)`，单元测试验证转换正确性 |
| **维度值不返回 key_col/key_value** | 维度值提示词无法给出“主键过滤”建议 | 明确降级：提示词仅展示匹配到的维表/列/文本与分数，并在测试中覆盖该分支 |
| **Milvus expr / search_params 兼容性** | 运行时查询失败或召回/延迟异常 | 1) 明确绑定 57/58 的索引（HNSW + COSINE）2) 将 `search_params` 配置化（HNSW 用 ef；其他索引用各自参数）3) expr 字符串字面量使用双引号，必要时做“无 expr + 结果后过滤”的降级 |
| **公共客户端迁移带来的引用调整** | MetaWeave / NL2SQL 引用路径不一致导致运行失败 | 1) 将 `MilvusClient` 下沉到 `src/services/vector_db` 2) MetaWeave 侧改为复用该实现或在原路径保留兼容 re-export（过渡期） |
| **Milvus 连接不稳定** | 服务不可用 | 1) 连接重试机制 2) 明确失败提示 |

---

## 7. 总结

### 7.1 改造要点

1. **增量改造**：在现有 PgVector 支持基础上新增 Milvus 支持，两种选项长期并存
2. **配置驱动**：通过 `src/configs/config.yaml` 的 `vector_database.active` 明确指定使用哪个向量数据库
3. **适配器模式**：统一检索接口，屏蔽底层差异
4. **字段兼容**：处理 `grain_hint` 缺失（当前未使用，不影响 SQL 生成），维度值提示词使用无主键降级展示（Milvus 不返回 `key_col/key_value`）
5. **配置必填**：`vector_database.active` 必须明确指定，配置缺失将抛出异常
6. **数据源隔离**：Milvus 模式下，SQL 生成过程的所有元数据查询均从 Milvus 获取，不访问 PostgreSQL 向量表

### 7.2 实施优先级

- **P0（必须）**：配置、适配器基础、Milvus 适配器实现
- **P1（重要）**：单元测试、集成测试
- **P2（可选）**：文档、性能优化

### 7.3 验收标准

- [ ] 配置 `active: pgvector` 时，能够正常使用 PgVector 检索并生成 SQL
- [ ] 配置 `active: milvus` 时，能够正常从 Milvus 检索并生成 SQL
- [ ] **Milvus 模式验证**：SQL 生成过程中不访问 PostgreSQL 的 `system.sem_object_vec` 或 `system.dim_value_index` 表
- [ ] 配置缺失或 `active` 字段为空时，抛出清晰的异常信息
- [ ] 配置 `active` 为不支持的值时，抛出明确的错误提示
- [ ] 单元测试覆盖率 > 80%，包含 COSINE 距离转换正确性测试
- [ ] 集成测试通过（分别测试 pgvector 和 milvus 两种配置）
- [ ] 生成的 SQL 能够正确执行
- [ ] 文档完整，部署步骤清晰

---

## 附录

### A. 参考文档

- 57_dim_value 加载到向量数据库的概要设计.md
- 58_table_schema_embedding 加载到向量数据库的概要设计.md
- src/modules/sql_generation/config/sql_generation_subgraph.yaml
- src/tools/schema_retrieval/retriever.py

### B. 相关代码文件

- `src/services/db/pg_client.py` - 现有 PgVector 检索逻辑
- `src/services/vector_db/milvus_client.py` - Milvus 客户端（公共组件）
- `src/tools/schema_retrieval/retriever.py` - Schema 检索协调器
- `src/modules/sql_generation/subgraph/nodes/sql_generation.py` - SQL 生成节点

---

**文档版本：** v1.0
**编写日期：** 2025-12-11
**编写人：** Claude (AI Assistant)
