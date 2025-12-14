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
- **阈值过滤顺序（重要）**：
  1. **先用 raw_similarity 做阈值过滤**：`raw_similarity >= threshold`（保持与 PgVector 语义一致）
  2. **再 clamp 用于返回值**：`similarity = clamp(raw_similarity, 0.0, 1.0)`（数值规范化）
- 这样当 threshold=0 时，负相似度（如 -0.2）会被正确排除，而不是 clamp 成 0 后误通过

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
| `embedding` | `embedding` | 向量（维度取决于 embedding 模型，见下方约束） |
| `updated_at` | `updated_at` | 更新时间戳 |
| `lang` | ❌ | Milvus 不需要 |
| `boost` | ❌ | Milvus 不需要 |
| `attrs` | ❌ | Milvus 不需要 |

**关键差异：**
- ✅ Milvus **缺少 `grain_hint`** 字段
- ✅ 解决方案：在适配器中返回 `None`
- ℹ️ **影响说明**：当前 SQL 生成子图虽然读取该字段，但实际未在提示词中使用，因此缺失不影响 SQL 生成质量
- ℹ️ **设计说明**：虽然当前不使用 `grain_hint`，但为保持适配器接口一致性，`MilvusSearchAdapter` 仍在返回结构中包含此字段并统一返回 `None`。这样上层代码无需判断当前使用的是哪个适配器，简化了调用逻辑

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

**重要：配置分层策略**
- **连接配置**（host/port/database 等）：统一在 `src/configs/config.yaml` 的 `vector_database` 段管理
- **检索参数**（metric_type/ef 等）：在 `sql_generation_subgraph.yaml` 的 `schema_retrieval.milvus_search_params` 管理
- **运行时隔离**：NL2SQL 运行时不读取 `configs/metaweave/` 目录（索引由 Loader 创建/维护，当前实现固定 HNSW+COSINE，搜索参数需与其保持一致）

在系统级配置文件 `src/configs/config.yaml` 中新增 `vector_database` 配置段：

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

      # ⚠️ 搜索参数（search_params）不在此处配置
      # 搜索参数仅影响 SQL 生成子图，已移至 sql_generation_subgraph.yaml
      # 见：schema_retrieval.milvus_search_params
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
- ✅ 向量数据库连接配置：`src/configs/config.yaml`
- ✅ 向量检索参数配置：`src/modules/sql_generation/config/sql_generation_subgraph.yaml`
- ❌ **不要访问**：`configs/metaweave/metadata_config.yaml`（数据加载模块专用）

### 2.1.1 子图配置：`sql_generation_subgraph.yaml`

Milvus 向量检索参数配置在子图配置文件中（因为这些参数仅影响 SQL 生成子图的检索行为）：

```yaml
# src/modules/sql_generation/config/sql_generation_subgraph.yaml

schema_retrieval:
  # 现有配置...
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

  # --------------------------------------------------------------------------
  # Milvus 向量检索参数（仅当 vector_database.active=milvus 时生效）
  # --------------------------------------------------------------------------
  # 当前默认：HNSW + COSINE（与 MetaWeave Loader 创建的索引一致）
  # - 索引由 Loader 创建，当前实现固定 HNSW + COSINE（见 57/58 文档或 Loader 代码）
  # - 搜索参数必须与索引类型匹配，否则会检索失败
  # - NL2SQL 运行时不读取 Loader 配置
  # 
  # 【未来扩展】如需支持 IVF 索引，需同时修改：
  # - MetaWeave Loader 代码中的 index_params
  # - 此处 params 改为 nprobe（IVF 参数）
  # --------------------------------------------------------------------------
  milvus_search_params:
    metric_type: COSINE              # 必须与索引的 metric_type 一致
    params:
      ef: 100                        # HNSW 参数：越大召回越高，延迟越高
```

**配置分层说明：**

| 配置项 | 配置文件 | 说明 |
|-------|---------|------|
| `vector_database.active` | `config.yaml` | 全局：选择使用哪个向量数据库 |
| `vector_database.providers.milvus.*` | `config.yaml` | 全局：Milvus 连接参数（host/port/database 等） |
| `schema_retrieval.milvus_search_params` | `sql_generation_subgraph.yaml` | 子图：Milvus 检索参数（metric_type/ef 等） |

**命名约定：**
- **配置键**：固定使用 `milvus_search_params`（在 yaml 文件中）
- **代码变量**：可使用简称 `search_params`（在 Python 代码中）
- 示例：`milvus_search_params = config.get("milvus_search_params")` → 变量名 `search_params`

**📝 实施提醒：配置文件注释同步**

实施时需要在实际配置文件 `sql_generation_subgraph.yaml` 中添加以下注释（方便运维人员理解）：
- 在 `sql_embedding_top_k` 配置项下方添加：`# 注意：当使用 Milvus 时，暂不支持 sql_embedding 检索，系统会自动降级为空结果`
- 新增 `milvus_search_params` 配置段及其说明注释

**⚠️ 配置独立性说明：**
- NL2SQL 模块和 MetaWeave 数据加载模块各自维护独立的 `vector_database` 配置
- NL2SQL 使用：`src/configs/config.yaml`
- MetaWeave 使用：`configs/metaweave/metadata_config.yaml`
- 原因：MetaWeave 是相对独立的模块，未来可能从 NL2SQL 项目中分离，因此不应产生配置依赖
- 两份配置需要保持一致（手动管理）：`active` 字段和对应 provider 的连接参数应相同
- **代码依赖解耦（方案选择）**：NL2SQL 运行时不应直接依赖 `src/metaweave/` 下的实现；Milvus 客户端下沉到 `src/services/` 作为公共组件，供 NL2SQL 与 MetaWeave 共同复用

### 2.2 配置读取逻辑

```python
# ✅ 推荐方式：通过工厂函数创建适配器（统一入口）
# SchemaRetriever 入参 config 是子图配置（sql_generation_subgraph.yaml）
def __init__(self, config: Dict[str, Any] = None):
    self.config = config or {}

    # 通过工厂函数创建向量检索适配器
    # - 工厂函数内部读取全局 config.yaml 获取连接配置和 active 类型
    # - 工厂函数从子图配置读取 milvus_search_params
    # - 配置缺失时工厂函数会抛出明确的异常
    from src.services.vector_adapter import create_vector_search_adapter
    self.vector_client = create_vector_search_adapter(self.config)
```

**⚠️ 重要：统一使用工厂函数**

SchemaRetriever 必须通过 `create_vector_search_adapter()` 工厂函数创建适配器，**禁止直接实例化** `MilvusSearchAdapter` 或 `PgVectorSearchAdapter`。

理由：
- 工厂函数封装了适配器选择逻辑和配置读取
- 保持单一入口，便于维护和测试
- 配置校验逻辑集中管理

**配置加载路径：**
```python
# 在 schema_retrieval_node 中
from src.services.config_loader import load_subgraph_config

def schema_retrieval_node(state: SQLGenerationState):
    # 加载子图配置（sql_generation_subgraph.yaml）
    # 注意：load_subgraph_config 内部会先读取全局 config.yaml 获取子图配置路径，
    #       但返回的 dict 仅包含子图配置内容，不包含全局配置
    config = load_subgraph_config("sql_generation")

    # 初始化 SchemaRetriever：
    # - 子图参数：从 config（子图配置）读取
    # - 向量数据库连接：SchemaRetriever 内部单独调用 get_config() 读取全局 vector_database
    retriever = SchemaRetriever(config)

    # 后续所有向量数据库操作通过 retriever.vector_client 完成
    # ⚠️ 不再直接使用 retriever.pg_client 访问向量表
```

**SchemaRetriever 改造要点：**

改造后的 `SchemaRetriever` 类结构：
```python
from src.services.db.pg_client import get_pg_client
from src.services.db.neo4j_client import get_neo4j_client
from src.services.vector_adapter import create_vector_search_adapter  # 新增


class SchemaRetriever:
    def __init__(self, config: Dict[str, Any] = None):
        # 业务数据库客户端（仍然保留，用于执行生成的 SQL、验证结果等）
        self.pg_client = get_pg_client()

        # 图数据库客户端（用于 JOIN 路径查询）
        self.neo4j_client = get_neo4j_client()

        # 向量数据库客户端（通过工厂函数创建）
        # config 是子图配置，包含 schema_retrieval.milvus_search_params
        self.vector_client = create_vector_search_adapter(config)  # 新增

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
│   BaseVectorSearchAdapter (抽象基类)     │
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
│SearchAdapter│   │SearchAdapter │
└────────────┘    └──────────────┘
      │                  │
      ▼                  ▼
┌────────────┐    ┌──────────────┐
│ PGClient   │    │MilvusClient  │
│ (现有)     │    │  (新增)      │
└────────────┘    └──────────────┘
```

**命名约定说明：**
- `BaseVectorSearchAdapter`：向量**检索**适配器基类（本方案新增，用于 NL2SQL 查询阶段）
- `BaseVectorClient`：向量**加载**客户端基类（MetaWeave 已有，用于数据写入阶段）
- 两者用途不同，互不冲突

### 3.2 统一返回格式

所有适配器方法返回统一的数据格式。

**字段约定：**
- **核心字段**：下方列出的字段为必有字段（除特别标注"可选"外）
- **透传字段**：PgVector 适配器可能透传额外字段（如 `lang`），这些字段不参与提示词构建，下游代码应忽略
- **设计原则**：适配器不做字段裁剪，但调用方只依赖核心字段

#### `search_tables()` 返回格式

```python
[
    {
        "object_id": "public.fact_sales",
        "grain_hint": "交易明细",           # PgVector 有，Milvus 返回 None
        "time_col_hint": "order_date,created_at",
        "table_category": "事实表",
        "similarity": 0.85
        # 注意：PgVector 可能透传 lang 等额外字段，下游代码应忽略
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
        "table_category": "事实表",          # 列的父表分类（可选，允许为空）
        "similarity": 0.78
    },
    # ...
]

# 注意：table_category 对 columns 允许为空字符串
# - PgVector：通过 LEFT JOIN 从父表获取
# - Milvus：column 记录本身可能不含此字段，返回空字符串
# - 下游逻辑（SchemaRetriever）实际通过 parent_id 从 tables 结果查找分类，不依赖此字段
```

#### `search_dim_values()` 返回格式

```python
# 适配器返回格式（不含 query_value）
[
    {
        "dim_table": "public.dim_store",    # 维表全名
        "dim_col": "store_name",            # 列名
        "matched_text": "京东便利店(西湖店)", # 匹配到的文本
        "score": 0.92,                      # 相似度分数
    },
    # ...
]

# 注意：query_value 和 source_index 字段由 SchemaRetriever 
# 通过 add_source_index_to_matches() 统一添加，适配器不负责
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

**⚠️ 实施顺序（重要）：**

由于 NL2SQL 代码不能直接依赖 `src/metaweave/` 下的实现（MetaWeave 模块未来会独立），必须按以下顺序实施：

1. **先完成 MilvusClient 下沉（同一 PR 内完成，避免中间态不可运行）**：
   - **复制**（非移动）`src/metaweave/services/vector_db/milvus_client.py` 到 `src/services/vector_db/milvus_client.py`
   - **⚠️ 解耦关键**：下沉后的 `MilvusClient` 必须移除对 `BaseVectorClient`（位于 `src/metaweave/...`）的继承，否则会造成 shared 组件反向依赖 MetaWeave。解耦方式二选一：
     - A) 不继承任何基类（推荐，NL2SQL 只需要连接能力，不需要 Loader 的写入接口）
     - B) 同时下沉 `BaseVectorClient` 到 `src/services/vector_db/base.py`
   - **保留旧路径兼容**：在 `src/metaweave/services/vector_db/milvus_client.py` 改为 re-export：
     ```python
     # 兼容 shim：保持 MetaWeave 侧引用不断
     # ⚠️ 必须 re-export 所有被外部引用的符号
     from src.services.vector_db.milvus_client import (  # noqa: F401
         MilvusClient,
         _lazy_import_milvus,
     )
     ```
   - 这样 MetaWeave 侧现有 import（包括 `from ...milvus_client import MilvusClient, _lazy_import_milvus`）不会断
2. **再开发向量检索适配器**：基于下沉后的公共 MilvusClient 开发 `MilvusSearchAdapter`
3. **（可选）清理旧路径**：待 MetaWeave 独立后，移除兼容 shim

**新增文件：**

```
src/
└── services/
    ├── vector_db/                         # 新增：向量数据库公共客户端（NL2SQL/MetaWeave 共用）
    │   ├── __init__.py
    │   └── milvus_client.py               # 从 metaweave 下沉（实施步骤 1）
    └── vector_adapter/                    # 新增：向量检索适配器模块（实施步骤 2）
        ├── __init__.py                    # 新增：模块导出
        ├── base.py                        # 新增：BaseVectorSearchAdapter 抽象基类
        ├── pgvector_adapter.py            # 新增：PgVectorSearchAdapter 实现
        ├── milvus_adapter.py              # 新增：MilvusSearchAdapter 实现
        └── factory.py                     # 新增：适配器工厂函数
```

**修改文件：**

```
src/
├── configs/
│   └── config.yaml                        # 修改：新增 vector_database 配置段
│
├── modules/
│   └── sql_generation/
│       └── config/
│           └── sql_generation_subgraph.yaml  # 修改：新增 milvus_search_params 配置段
│
├── tools/
│   └── schema_retrieval/
│       ├── retriever.py                   # 修改：使用适配器替换直接调用 PGClient（5 处）
│       └── value_matcher.py               # 修改：无主键降级、去重键兼容、校验调整
│
└── metaweave/
    └── services/
        └── vector_db/
            ├── __init__.py                # 修改：改为复用公共层或兼容 re-export
            └── milvus_client.py           # 修改：改为复用公共层（原实现下沉）
```

**受影响文件（需评估/可能受影响）：**

**必须评估（可能无需改，但必须验证）：**
- `src/modules/sql_generation/subgraph/nodes/sql_generation.py`（消费 `dim_value_hits` 的提示词展示效果与降级分支）

**可能受影响（本期不改；仅在未来补主键信息时才改）：**
- `src/metaweave/core/loaders/dim_value_loader.py`（本方案不回填 `key_col/key_value`，保持现状）

**说明：**
- ⚠️ `vector_database` 选择与连接参数仅在 `src/configs/config.yaml` 中管理
- ✅ `sql_generation_subgraph.yaml` 包含检索阈值/TopK 等参数，以及 Milvus 搜索参数（`milvus_search_params`）
- ❌ **不要**在 `sql_generation_subgraph.yaml` 中添加 `vector_database.active` 或连接参数

### 4.2 核心类设计

#### 4.2.1 BaseVectorSearchAdapter (base.py)

```python
"""向量数据库检索适配器基类

命名说明：
- BaseVectorSearchAdapter：向量检索适配器（本模块，用于 NL2SQL 查询阶段）
- BaseVectorClient：向量加载客户端（MetaWeave 模块，用于数据写入阶段）
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseVectorSearchAdapter(ABC):
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
            - table_category: 父表分类（可选，允许为空字符串）
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
            - dim_table: 维表名
            - dim_col: 列名
            - matched_text: 匹配到的文本
            - score: 相似度分数
            
        Note:
            query_value 字段不由适配器返回，而是由 SchemaRetriever 
            通过 add_source_index_to_matches() 统一添加（职责分离）。
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

#### 4.2.2 PgVectorSearchAdapter (pgvector_adapter.py)

```python
"""PgVector 检索适配器 - 封装现有 PGClient"""

from typing import Any, Dict, List

from src.services.db.pg_client import get_pg_client
from src.services.vector_adapter.base import BaseVectorSearchAdapter


class PgVectorSearchAdapter(BaseVectorSearchAdapter):
    """PgVector 检索适配器

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
        """检索维度值（直接调用 PGClient）
        
        注意：query_value 字段由 SchemaRetriever._retrieve_dim_value_hits() 
        通过 add_source_index_to_matches() 统一添加，适配器不负责添加。
        """
        return self.pg_client.search_dim_values(
            query_value=query_value,
            top_k=top_k,
        )

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

#### 4.2.3 MilvusSearchAdapter (milvus_adapter.py)

```python
"""Milvus 检索适配器 - 实现 Milvus 向量检索"""

from typing import Any, Dict, List, Optional

# ⚠️ 注意：MilvusClient 已从 metaweave 下沉到公共层（见 4.1 节实施顺序）
# 原路径：src/metaweave/services/vector_db/milvus_client.py
# 新路径：src/services/vector_db/milvus_client.py
from src.services.vector_db.milvus_client import MilvusClient, _lazy_import_milvus
from src.services.vector_adapter.base import BaseVectorSearchAdapter
from src.utils.logger import get_module_logger

logger = get_module_logger("milvus_search_adapter")


class MilvusSearchAdapter(BaseVectorSearchAdapter):
    """Milvus 检索适配器

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

    def __init__(
        self,
        config: Dict[str, Any],
        search_params: Optional[Dict[str, Any]] = None,
    ):
        """初始化 Milvus 适配器

        Args:
            config: 向量数据库配置（来自 src/configs/config.yaml 的 vector_database）
            search_params: Milvus 搜索参数（来自 sql_generation_subgraph.yaml 的
                           schema_retrieval.milvus_search_params）
        """
        super().__init__(config)

        # 从 vector_database 配置中读取 Milvus 连接配置
        providers = config.get("providers", {})
        milvus_config = providers.get("milvus", {})

        if not milvus_config:
            raise ValueError(
                "Milvus 配置缺失，请在 src/configs/config.yaml 中配置 "
                "vector_database.providers.milvus"
            )

        # 保存连接配置
        self.milvus_config = milvus_config

        # 保存搜索参数（来自子图配置）
        self.search_params = search_params

        # 初始化 Milvus 客户端
        self.milvus_client = MilvusClient(self.milvus_config)
        self.milvus_client.connect()

        # 预加载 Collection 到内存（避免首次查询延迟）
        _, _, _, _, Collection, _, _ = _lazy_import_milvus()
        self._collection_table_schema = Collection(
            self.COLLECTION_TABLE_SCHEMA, using=self.milvus_client.alias
        )
        self._collection_dim_value = Collection(
            self.COLLECTION_DIM_VALUE, using=self.milvus_client.alias
        )
        # load() 将 collection 加载到内存，search/query 前必须调用
        self._collection_table_schema.load()
        self._collection_dim_value.load()

        # ⚠️ 向量维度校验（确保 embedding 模型一致）
        self._validate_embedding_dimension()

        logger.info(
            "Milvus 适配器初始化成功: %s:%s/%s",
            self.milvus_config.get("host"),
            self.milvus_config.get("port"),
            self.milvus_config.get("database"),
        )

    def _validate_embedding_dimension(self):
        """校验向量维度一致性（确保 embedding 模型与 Milvus 数据一致）。
        
        ⚠️ 风险应对：如果维度不匹配，检索会静默返回错误结果或直接报错。
        """
        from src.services.embedding.embedding_client import get_embedding_client
        
        embedding_client = get_embedding_client()
        # 假设 embedding_client 有 get_dimensions() 方法，否则需要从配置读取
        expected_dim = getattr(embedding_client, 'dimensions', None)
        if expected_dim is None:
            logger.warning("无法获取 embedding 维度，跳过维度校验")
            return
        
        # 从 Milvus schema 读取实际维度
        for field in self._collection_table_schema.schema.fields:
            if field.name == "embedding":
                actual_dim = field.params.get("dim")
                if actual_dim and expected_dim != actual_dim:
                    raise ValueError(
                        f"向量维度不匹配: embedding_client={expected_dim}, "
                        f"milvus={actual_dim}. 请检查 embedding 模型配置或重新加载数据"
                    )
                break
        
        logger.info("向量维度校验通过: %d 维", expected_dim)

    def _get_search_params(self) -> Dict[str, Any]:
        """读取检索参数（从子图配置传入，或使用默认值）。
        
        搜索参数来源：sql_generation_subgraph.yaml 的 schema_retrieval.milvus_search_params
        默认值：HNSW + COSINE（ef=100）
        """
        return self.search_params or {
            "metric_type": "COSINE",
            "params": {"ef": 100},  # HNSW 搜索参数（IVF 等索引需用各自参数）
        }

    def search_tables(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """从 Milvus 检索表（使用预加载的 collection）"""
        search_params = self._get_search_params()

        results = self._collection_table_schema.search(
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
            distance = float(hit.distance)
            raw_similarity = 1.0 - distance  # cosine similarity，理论范围 [-1, 1]

            # ⚠️ 先用 raw_similarity 做阈值过滤（保持与 PgVector 语义一致）
            # 这样负相似度（如 -0.2）在 threshold=0 时会被正确排除
            if raw_similarity < similarity_threshold:
                continue

            # 再 clamp 用于返回值（数值规范化）
            similarity = max(0.0, min(1.0, raw_similarity))

            tables.append(
                {
                    "object_id": hit.entity.get("object_id"),
                    "grain_hint": None,  # Milvus 无此字段
                    "time_col_hint": hit.entity.get("time_col_hint"),
                    "table_category": hit.entity.get("table_category", ""),
                    "similarity": similarity,  # 返回 clamp 后的值（0-1）
                }
            )

        return tables

    def search_columns(
        self,
        embedding: List[float],
        top_k: int = 10,
        similarity_threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """从 Milvus 检索列（使用预加载的 collection）"""
        search_params = self._get_search_params()

        results = self._collection_table_schema.search(
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

            # ⚠️ 先用 raw_similarity 做阈值过滤（保持与 PgVector 语义一致）
            if raw_similarity < similarity_threshold:
                continue

            # 再 clamp 用于返回值
            similarity = max(0.0, min(1.0, raw_similarity))

            columns.append(
                {
                    "object_id": hit.entity.get("object_id"),
                    "parent_id": hit.entity.get("parent_id"),
                    # table_category 允许为空（column 记录可能不含此字段）
                    # 下游 SchemaRetriever 通过 parent_id 从 tables 结果查找分类
                    "table_category": hit.entity.get("table_category") or "",
                    "similarity": similarity,  # 返回 clamp 后的值（0-1）
                }
            )

        return columns

    def search_dim_values(
        self,
        query_value: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """从 Milvus 检索维度值（使用预加载的 collection）"""
        # 先对查询值向量化
        from src.services.embedding.embedding_client import get_embedding_client
        embedding_client = get_embedding_client()
        query_embedding = embedding_client.embed_query(query_value)

        # 与表/列一致：默认绑定 HNSW + COSINE；建议通过配置覆盖
        search_params = self._get_search_params()

        results = self._collection_dim_value.search(
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
            # clamp 用于返回值规范化（dim_values 无阈值过滤，由下游处理）
            score = max(0.0, min(1.0, raw_score))

            matches.append(
                {
                    # 注意：query_value 不在此添加，由 SchemaRetriever 统一 enrichment
                    "dim_table": hit.entity.get("table_name"),
                    "dim_col": hit.entity.get("col_name"),
                    "matched_text": hit.entity.get("col_value"),
                    "score": score,  # 返回 clamp 后的值（0-1）
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

#### 4.2.4 适配器工厂函数 (factory.py)

```python
"""向量检索适配器工厂函数"""

from typing import Any, Dict, Optional

from src.services.vector_adapter.base import BaseVectorSearchAdapter
from src.services.vector_adapter.pgvector_adapter import PgVectorSearchAdapter
from src.services.vector_adapter.milvus_adapter import MilvusSearchAdapter


def create_vector_search_adapter(
    subgraph_config: Optional[Dict[str, Any]] = None,
) -> BaseVectorSearchAdapter:
    """
    创建向量检索适配器（工厂函数）

    根据全局配置中的 vector_database.active 自动选择适配器类型。

    Args:
        subgraph_config: 子图配置（sql_generation_subgraph.yaml），
                         用于读取 schema_retrieval.milvus_search_params

    Returns:
        向量检索适配器实例（PgVectorSearchAdapter 或 MilvusSearchAdapter）

    Raises:
        ValueError: 配置缺失或向量数据库类型不支持时抛出

    Example:
        >>> from src.services.vector_adapter import create_vector_search_adapter
        >>> adapter = create_vector_search_adapter(subgraph_config)
        >>> tables = adapter.search_tables(embedding, top_k=10)
    """
    from src.services.config_loader import get_config

    # 从全局配置读取向量数据库连接配置
    vector_db_config = get_config().get("vector_database")

    if not vector_db_config:
        raise ValueError(
            "缺少 vector_database 配置，请在 src/configs/config.yaml 中配置 "
            "vector_database.active (pgvector 或 milvus)"
        )

    active_type = vector_db_config.get("active")
    if not active_type:
        raise ValueError(
            "缺少 vector_database.active 配置，请明确指定使用 pgvector 或 milvus"
        )

    # 从子图配置读取 Milvus 搜索参数
    subgraph_config = subgraph_config or {}
    retrieval_config = subgraph_config.get("schema_retrieval", {})
    milvus_search_params = retrieval_config.get("milvus_search_params")

    # 根据类型创建对应适配器
    if active_type == "milvus":
        return MilvusSearchAdapter(
            config=vector_db_config,
            search_params=milvus_search_params,
        )
    elif active_type == "pgvector":
        return PgVectorSearchAdapter(vector_db_config)
    else:
        raise ValueError(
            f"不支持的向量数据库类型: {active_type}，仅支持 pgvector 或 milvus"
        )
```

---

## 5. 改造实施步骤

### 5.1 第一阶段：配置与适配器基础（优先级 P0）

#### 任务 1.1：新增向量检索适配器模块

**文件：** `src/services/vector_adapter/`

1. 创建 `base.py` - 定义 `BaseVectorSearchAdapter` 抽象基类
2. 创建 `pgvector_adapter.py` - 实现 `PgVectorSearchAdapter`（封装现有 PGClient）
3. 创建 `factory.py` - 实现 `create_vector_search_adapter()` 工厂函数
4. 创建 `__init__.py` - 导出适配器类和工厂函数

**验收标准：**
- `PgVectorSearchAdapter` 能够正常调用现有 PGClient 的所有方法
- `create_vector_search_adapter()` 能够根据配置正确创建适配器
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

**⚠️ 日志/埋点规范：** 日志文本不要写死后端类型（如 "pgvector"），应使用 `self.vector_db_type` 或适配器名称动态输出，便于排查问题时区分当前使用的向量数据库。

**验收标准：**
- 使用 `active: pgvector` 配置时，能够正常调用 `PgVectorSearchAdapter`
- 使用 `active: milvus` 配置时，能够正常调用 `MilvusSearchAdapter`
- 配置缺失或无效时，抛出清晰的异常信息
- Milvus 模式下不会访问 PostgreSQL 的 `system.sem_object_vec` 等表
- 日志中不写死 "pgvector"，使用动态后端类型标识
- 集成测试通过，SQL 生成结果正确

### 5.2 第二阶段：Milvus 适配器实现（优先级 P0）

#### 任务 2.1：MilvusSearchAdapter 实现

**文件：** `src/services/vector_adapter/milvus_adapter.py`

**实现方法清单：**

1. 实现 `MilvusSearchAdapter` 类，继承 `BaseVectorSearchAdapter`
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
- 所有方法返回格式与 `PgVectorSearchAdapter` 一致
- 字段缺失处理正确（`grain_hint` 返回 `None`）
- COSINE distance 转换正确（`raw = 1.0 - distance`，并按约定 `similarity = clamp(raw, 0.0, 1.0)`）
- 查询表达式安全（使用 `json.dumps`）
- Milvus 连接异常时能够友好报错

#### 任务 2.2：字段兼容性处理

**文件：**
- `src/tools/schema_retrieval/value_matcher.py`
- `src/modules/sql_generation/subgraph/nodes/sql_generation.py`

**改造内容：**

1. 提示词生成时，兼容 `grain_hint` 为 `None` 的情况
2. `format_dim_value_matches_for_prompt()`：实现无主键降级展示
3. `deduplicate_dim_hits()`：修改去重键，兼容 Milvus 无 `key_value`
4. `validate_dim_value_match()`：移除 `key_col/key_value` 的必需校验

---

**修改示例 1：无主键降级展示（format_dim_value_matches_for_prompt）**

**⚠️ 开发阶段说明：** 当前阶段不需要评估"降级后的提示词效果对 SQL 生成质量的影响"。降级展示仅影响提示词中维度值部分的格式，LLM 仍可根据表名/列名/匹配值生成正确的 SQL（可能使用 LIKE 匹配或直接使用匹配值）。质量影响评估待后续迭代进行。

```python
# 原逻辑（src/tools/schema_retrieval/value_matcher.py:115）
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

---

**修改示例 2：去重键兼容（deduplicate_dim_hits）**

```python
# 原逻辑（src/tools/schema_retrieval/value_matcher.py:260）
# 问题：Milvus 不返回 key_value，导致去重键变成 (dim_table, dim_col, None)
# 同一维表同一列的不同匹配值会被错误去重
key = (hit.get("dim_table"), hit.get("dim_col"), hit.get("key_value"))

# 修改后：优先用 key_value（PgVector），无则用 matched_text（Milvus）
def deduplicate_dim_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对 dim_value_hits 进行去重与排序。

    规则：
    1) 按 (dim_table, dim_col, 去重标识) 分组，保留分数最高的元素
       - 去重标识：优先使用 key_value（PgVector），无则用 matched_text（Milvus）
    2) 最终按 score 降序排序
    """
    if not hits:
        return []

    best_by_key: Dict[tuple, Dict[str, Any]] = {}

    for hit in hits:
        # ⚠️ 兼容 PgVector 和 Milvus：优先用 key_value，无则用 matched_text
        dedup_id = hit.get("key_value") or hit.get("matched_text")
        key = (hit.get("dim_table"), hit.get("dim_col"), dedup_id)
        
        score = hit.get("score", 0.0)
        current_best = best_by_key.get(key)
        if current_best is None or score > current_best.get("score", 0.0):
            best_by_key[key] = hit

    # 按分数降序排序
    deduped = list(best_by_key.values())
    deduped.sort(key=lambda h: h.get("score", 0.0), reverse=True)
    return deduped
```

---

**修改示例 3：移除必需字段校验（validate_dim_value_match）**

```python
# 原逻辑（src/tools/schema_retrieval/value_matcher.py:229）
# 问题：将 key_col/key_value 设为必需，与 Milvus 不返回这些字段的决策矛盾
required_fields = ["dim_table", "dim_col", "key_col", "key_value", "matched_text", "score"]

# 修改后：key_col/key_value 改为可选字段
required_fields = ["dim_table", "dim_col", "matched_text", "score"]
optional_fields = ["key_col", "key_value", "query_value", "source_index"]
```

---

**验收标准：**
- 使用 Milvus 时，提示词中不包含 `grain_hint`（或显示为空）
- 维度值提示词格式正确（PgVector 显示主键条件，Milvus 显示降级格式）
- 去重逻辑正确（PgVector 按 key_value 去重，Milvus 按 matched_text 去重）
- 校验函数不再因缺少 key_col/key_value 而报错

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

**Milvus 模式验证清单：**
- [ ] 日志中不出现 `system.sem_object_vec` 等 PgVector 表名
- [ ] 日志显示正确的 Milvus collection 名称（`nl2sql.table_schema_embeddings`、`nl2sql.dim_value_embeddings`）
- [ ] 生成的 SQL 能够正确执行（与业务数据库交互正常）
- [ ] 维度值降级提示词格式正确（无主键时显示"建议人工确认或使用 LIKE 匹配"）
- [ ] `grain_hint` 为 `None` 不影响 SQL 生成

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
| **⚠️ COSINE 距离必须转换** | Milvus 返回 distance，需转换为 similarity | **关键**：`raw = 1.0 - distance`；**阈值过滤必须用 raw**（`raw >= threshold`），再 clamp 用于返回值（`similarity = clamp(raw, 0.0, 1.0)`） |
| **MilvusClient 下沉到公共层** | 与“模块可拆分”口径一致 | NL2SQL 不再直接依赖 `src/metaweave/`；MetaWeave/NL2SQL 共用 `src/services/vector_db` |
| **grain_hint 返回 None** | Milvus 无此字段，兼容处理 | 提示词生成需兼容 |
| **维度值不返回 key_col/key_value** | 降低加载侧耦合与成本 | 提示词侧必须实现无主键降级展示（不再拼接主键过滤条件） |
| **历史 SQL 暂不支持 Milvus** | 优先级低，预留接口 | 不影响主流程 |

### 6.1.1 重要：Milvus COSINE 距离转换详解

**问题：** Milvus 的 COSINE 距离与相似度方向相反

**原因：**
- PgVector 使用 `1 - (embedding <=> vector)` 计算相似度（`<=>` 是 cosine 距离）
  - 结果：这是 cosine similarity（理论范围 -1 到 1）；工程上通常只关心 >=0 的部分
  - 阈值过滤：`similarity >= threshold`（这里 similarity 指 raw cosine similarity，未经 clamp）

- Milvus 使用 `metric_type: "COSINE"` 时：
  - `search()` 返回的是 **cosine distance**（距离，不是相似度）
  - **Cosine distance = 1 - cosine similarity**
  - 范围：0 到 2（0 表示完全相同，2 表示完全相反）

**解决方案：**
```python
# ✅ 正确的转换方式（先过滤再 clamp）
distance = float(hit.distance)
raw_similarity = 1.0 - distance  # cosine similarity，理论范围 [-1, 1]

# ⚠️ 先用 raw_similarity 做阈值过滤（保持与 PgVector 语义一致）
# 这样负相似度（如 -0.2）在 threshold=0 时会被正确排除
if raw_similarity < similarity_threshold:
    continue  # 不通过

# 再 clamp 用于返回值（数值规范化）
similarity = max(0.0, min(1.0, raw_similarity))
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
| **⚠️ Embedding 模型/维度不一致** | **严重**：检索质量极差或直接报错（维度不匹配） | **强约束**：NL2SQL 运行时 `get_embedding_client()` 必须与 MetaWeave Loader 写入 Milvus 时使用**同一 embedding 模型**。建议：1) 通过环境变量（如 `EMBEDDING_MODEL`）统一配置 2) 在部署文档中明确约定模型名称和维度 3) 启动时校验向量维度是否匹配 |
| **⚠️ COSINE 距离转换错误** | **严重**：阈值过滤失效，检索结果错误 | **强制代码审查 + 自动化测试**：所有 Milvus 检索必须包含 `raw = 1.0 - distance`，**阈值过滤用 raw**（`raw >= threshold`），再 clamp 用于返回值（`similarity = clamp(raw, 0.0, 1.0)`），单元测试验证转换正确性 |
| **维度值不返回 key_col/key_value** | 维度值提示词无法给出"主键过滤"建议 | 明确降级：提示词仅展示匹配到的维表/列/文本与分数，并在测试中覆盖该分支 |
| **Milvus expr / search_params 兼容性** | 运行时查询失败或召回/延迟异常 | 1) 明确绑定 57/58 的索引（HNSW + COSINE）2) 将 `search_params` 配置化（HNSW 用 ef；其他索引用各自参数）3) expr 字符串字面量使用双引号，必要时做"无 expr + 结果后过滤"的降级 |
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

**文档版本：** v1.2
**编写日期：** 2025-12-11
**更新日期：** 2025-12-13
**编写人：** Claude (AI Assistant)

**v1.2 更新内容（二轮审核）：**
- 配置口径统一：明确"连接配置在全局、检索参数在子图"（2.1 节）
- 修改文件清单：补充遗漏的必改文件（sql_generation_subgraph.yaml、value_matcher.py、metaweave/vector_db/*）
- query_value 责任归属：统一"适配器不带，SchemaRetriever 统一添加"，修正三处冲突
- 索引类型口径：明确 HNSW 为当前默认，IVF 为未来扩展（2.1.1 节）
- 工厂函数命名统一：`create_vector_adapter` → `create_vector_search_adapter`
- 配置加载链路说明：更精确描述 load_subgraph_config 的依赖关系
- 运行时隔离表述：修正"禁止访问 metaweave"为"运行时不读取"
- columns 的 table_category：明确允许为空（接口说明 + 统一返回格式）
- 统一使用工厂函数：明确禁止直接实例化适配器（2.2 节）
- 命名约定说明：配置键 `milvus_search_params` vs 代码变量 `search_params`
- SchemaRetriever 类结构示例：补充完整 import 语句

**v1.1 更新内容（首轮审核）：**
- 【问题1】明确 MilvusClient 下沉实施顺序（4.1 节），代码示例添加路径注释（4.2.3 节）
- 【问题2】将 Milvus 搜索参数从 config.yaml 移至 sql_generation_subgraph.yaml（2.1/2.1.1 节），更新适配器代码示例
- 【问题3】补充 `deduplicate_dim_hits()` 去重键兼容改造（4.1/5.2 节）
- 【问题4】补充 `validate_dim_value_match()` 移除必需字段校验（4.1/5.2 节）
- 【问题5】补充 `factory.py` 工厂函数代码设计（4.2.4 节）
- 【问题6】添加配置文件注释同步提醒（2.1.1 节）
- 【问题7】补充 `grain_hint` 返回 None 的设计说明（1.4 节）
- 【问题8】明确 `query_value` 由 SchemaRetriever 添加，适配器不负责（4.2.2 节）
- 【问题9】类名重命名：`BaseVectorAdapter` → `BaseVectorSearchAdapter`，添加命名约定说明（3.1 节）
