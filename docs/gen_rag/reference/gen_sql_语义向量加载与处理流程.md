# gen_sql - 数据库元数据语义向量加载与处理流程

## 文档信息

- **版本**: v1.0
- **日期**: 2025-11-17
- **模块**: gen_sql（SQL 生成 Agent 的基础数据加载模块）

---

## 1. 功能概述

### 1.1 模块定位

**gen_sql 语义向量加载模块**是一个独立的 ETL 工具，用于将 PostgreSQL 数据库中的表结构和列信息转换为语义向量，并存储到 pgvector 向量数据库中，为后续的 SQL 生成 Agent 提供语义检索能力。

### 1.2 核心价值

- **语义理解**：将数据库表结构转换为自然语言描述，便于语义检索
- **向量检索**：使用 1024 维语义向量，支持基于相似度的快速检索
- **智能 SQL 生成**：为 SQL Agent 提供表/列选择的语义依据
- **知识管理**：统一管理数据库对象的语义知识库

### 1.3 主要功能

| 功能 | 说明 |
|------|------|
| **元数据提取** | 从 PostgreSQL 读取表结构、列信息、约束、注释 |
| **数据采样** | 采样表数据，提取字段示例值 |
| **语义描述生成** | 将结构化元数据转换为自然语言描述 |
| **向量编码** | 调用 Embedding 模型生成 1024 维向量 |
| **pgvector 存储** | 写入 system.sem_object_vec 表，支持 UPSERT |
| **向量检索** | 基于 HNSW 索引的高效相似度搜索 |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      输入层                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   │
│  │ PostgreSQL   │   │  config.yaml │   │    .env      │   │
│  │ (public.*)   │   │  (embedding) │   │  (db config) │   │
│  └──────────────┘   └──────────────┘   └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                      处理层                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  CLI 入口 (gen_sql/cli.py)                           │  │
│  │  • 参数解析  • 流程编排  • 进度显示                  │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │MetadataLoader│   │ DataSampler  │   │SemTextBuilder│  │
│  │元数据读取    │ → │ 数据采样     │ → │语义文本生成  │  │
│  └──────────────┘   └──────────────┘   └──────────────┘  │
│                            ↓                                │
│  ┌──────────────┐   ┌──────────────┐                      │
│  │EmbeddingClient│ → │   Writer     │                      │
│  │向量生成      │   │ pgvector写入 │                      │
│  └──────────────┘   └──────────────┘                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                      存储层                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  PostgreSQL + pgvector 扩展                          │  │
│  │  system.sem_object_vec 表                            │  │
│  │  • 表对象向量                                         │  │
│  │  • 列对象向量                                         │  │
│  │  • HNSW 向量索引                                      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                      应用层                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │ SQL Agent    │   │语义检索工具  │   │相似度查询    │  │
│  │智能查询生成  │   │表/列选择     │   │test_similarity│  │
│  └──────────────┘   └──────────────┘   └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 文件路径 | 核心职责 |
|------|---------|---------|
| **配置管理** | `gen_sql/settings.py` | 从 .env 读取数据库配置，从 config.yaml 读取 embedding 配置 |
| **元数据读取** | `gen_sql/metadata_loader.py` | 扫描表、读取结构、约束、注释；支持表过滤 |
| **数据采样** | `gen_sql/data_sampler.py` | 采样表数据（默认 5 行），提取示例值 |
| **语义文本构建** | `gen_sql/sem_text_builder.py` | 生成表/列的语义描述文本（text_raw）和属性（attrs） |
| **向量客户端** | `gen_sql/embedding_client.py` | 调用 Qwen/OpenAI embedding 模型，生成 1024 维向量 |
| **数据写入** | `gen_sql/writer.py` | UPSERT 写入 system.sem_object_vec 表 |
| **CLI 入口** | `gen_sql/cli.py` | 命令行工具，串联所有模块 |
| **连接测试** | `gen_sql/test_connection.py` | 测试数据库和 embedding 服务连接 |
| **相似度查询** | `gen_sql/test_similarity.py` | 测试向量相似度检索功能 |

---

## 3. 完整处理流程

### 3.1 流程概览

```
开始
  ↓
[1] 加载配置
  • 从 .env 读取数据库连接
  • 从 config.yaml 读取 embedding 配置
  • 验证配置完整性
  ↓
[2] 连接数据库
  • 连接 PostgreSQL
  • 检查 pgvector 扩展
  • 确保目标表存在
  ↓
[3] 扫描表列表
  • 获取 public schema 下所有表
  • 应用 include/exclude 过滤规则
  • 记录表数量
  ↓
[4] 逐表处理（并行/串行）
  │
  ├─ [4.1] 读取表元数据
  │    • 表名、注释
  │    • 列信息（名称、类型、可空性、注释）
  │    • 主键、唯一键、外键
  │    • 索引信息
  │
  ├─ [4.2] 采样表数据
  │    • 随机采样 5 行（可配置）
  │    • 提取每列的示例值（去重、非空）
  │    • 限制示例值长度（50 字符）
  │
  ├─ [4.3] 生成表对象
  │    • 构建语义描述文本
  │    •   格式：表名（注释）：描述。字段：字段1(类型) 注释[例:值]...
  │    • 推断粒度（txn/daily/monthly）
  │    • 识别时间列
  │    • 构建 attrs（主键、外键、度量字段）
  │
  └─ [4.4] 生成列对象
       • 为每个列构建语义描述
       •   格式：列名：注释；角色。示例值：值1, 值2, 值3
       • 标记列角色（主键/外键/度量/时间）
       • 构建 attrs（is_pk, is_fk, ref 等）
  ↓
[5] 批量生成向量
  • 收集所有 text_raw
  • 批量调用 embedding 模型
  • 验证向量维度（必须 1024）
  • 处理重试和错误
  ↓
[6] 写入 pgvector
  • 构造 UPSERT 语句
  • 批量写入（默认 500 条/批）
  • 记录写入统计
  ↓
[7] 创建索引
  • parent_id 索引（便于按表查询）
  • embedding HNSW 索引（向量相似度搜索）
  ↓
[8] 输出统计
  • 处理表数
  • 生成对象数（表/列）
  • 执行耗时
  ↓
结束
```

### 3.2 关键步骤详解

#### 步骤 4.3: 表对象语义描述生成

**输入**：表元数据 + 采样数据

**处理逻辑**：
1. **基础信息**：`表名（注释）`
2. **描述部分**：
   - 粒度判断：按日/按月汇总 or 明细表
   - 时间列识别：date_day, date_month 等
   - 主键说明
   - 外键关系
3. **字段列表**：`字段1(类型) 注释[例:值]；字段2(类型) 注释[例:值]...`

**输出示例**：
```
public.fact_store_sales_month（店铺销售月汇总事实表）：按月汇总数据，时间字段为 date_month，主键 (store_id, date_month, product_type_id)，关联表：store_id 关联 dim_store, product_type_id 关联 dim_product_type。字段：store_id(integer) 店铺ID（外键）[例:203]；date_month(date) 月份[例:2025-08-01]；product_type_id(integer) 商品类型ID（外键）[例:1]；amount(numeric) 销售金额[例:666.00]
```

#### 步骤 4.4: 列对象语义描述生成

**输入**：列元数据 + 示例值

**处理逻辑**：
1. **列名和注释**：`列名：注释`
2. **角色识别**：
   - 主键：`主键字段`
   - 外键：`外键，引用 schema.table.column`
   - 度量：`度量字段（数值类型）`
   - 时间：`时间字段`
3. **示例值**：取 3-5 个示例值

**输出示例**：
```
store_id：店铺ID（外键）；外键，引用 public.dim_store.store_id。示例值：101, 102, 103
```

#### 步骤 5: 向量生成

**支持的模型**：
- 通义千问 `text-embedding-v3`（1024 维）
- OpenAI 兼容 API（需验证维度）

**批处理策略**：
- 每批 10-25 个文本（根据 API 限制）
- 超时 30 秒
- 失败重试 3 次，指数退避

**维度校验**：
- 严格要求 1024 维
- 不符合则中止运行（不做截断或填充）

#### 步骤 6: pgvector 写入

**UPSERT 策略**：
```sql
INSERT INTO system.sem_object_vec (
  object_type, object_id, text_raw, lang, 
  grain_hint, time_col_hint, attrs, embedding
)
VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::vector)
ON CONFLICT (object_type, object_id) DO UPDATE SET
  text_raw = EXCLUDED.text_raw,
  lang = EXCLUDED.lang,
  grain_hint = EXCLUDED.grain_hint,
  time_col_hint = EXCLUDED.time_col_hint,
  attrs = EXCLUDED.attrs,
  embedding = EXCLUDED.embedding,
  updated_at = now()
```

**幂等性保证**：
- 以 `(object_type, object_id)` 为主键
- 重复运行自动更新，不产生重复记录

---

## 4. 数据模型

### 4.1 目标表结构

```sql
CREATE TABLE system.sem_object_vec (
  -- 对象类型：表 / 列 / 指标
  object_type   text NOT NULL 
                CHECK (object_type IN ('table','column','metric')),
  
  -- 对象ID：
  --   table = schema.table
  --   column = schema.table.column
  --   metric = metric:<id>
  object_id     text NOT NULL,
  
  -- 归属表ID（自动计算）
  parent_id     text GENERATED ALWAYS AS (
                   CASE
                     WHEN object_type = 'column'
                       THEN split_part(object_id, '.', 1) || '.' || split_part(object_id, '.', 2)
                     WHEN object_type = 'table' THEN object_id
                     ELSE NULL
                   END
                 ) STORED,
  
  -- 语义描述文本（供 embedding）
  text_raw      text NOT NULL,
  
  -- 元信息
  lang          text,                 -- 'zh' | 'en'
  grain_hint    text,                 -- 'txn' | 'daily' | 'monthly' | ...
  time_col_hint text,                 -- 时间列名
  boost         real DEFAULT 1.0,     -- 人工加权
  attrs         jsonb,                -- 结构化属性
  updated_at    timestamptz DEFAULT now(),
  
  -- 🔥 向量字段（1024 维）
  embedding     vector(1024) NOT NULL,
  
  PRIMARY KEY (object_type, object_id)
);

-- 索引
CREATE INDEX idx_sem_object_vec_type_parent
  ON system.sem_object_vec (object_type, parent_id);

-- 🔥 HNSW 向量索引（高效相似度搜索）
CREATE INDEX idx_sem_object_vec_emb_hnsw
  ON system.sem_object_vec 
  USING hnsw (embedding vector_cosine_ops);
```

### 4.2 对象类型

#### 表对象（table）

| 字段 | 说明 | 示例 |
|------|------|------|
| object_type | `'table'` | - |
| object_id | `schema.table` | `public.fact_sales` |
| text_raw | 表卡片：描述+字段列表 | 见上文示例 |
| grain_hint | 时间粒度 | `'daily'` / `'monthly'` / `'txn'` |
| time_col_hint | 时间列名 | `'date_day'` / `'order_date'` |
| attrs | 主键、外键、度量字段 | `{"keys":["id"],"fks":[...],"measures":[...]}` |

#### 列对象（column）

| 字段 | 说明 | 示例 |
|------|------|------|
| object_type | `'column'` | - |
| object_id | `schema.table.column` | `public.fact_sales.store_id` |
| text_raw | 列描述+角色+示例 | 见上文示例 |
| attrs | 列属性 | `{"is_fk":true,"ref":"dim_store.store_id"}` |

### 4.3 粒度类型（grain_hint）

| 值 | 含义 | 适用场景 |
|----|------|----------|
| `txn` | 交易/明细级 | 每行一笔交易，需要聚合 |
| `daily` | 按日汇总 | 预汇总到天粒度 |
| `monthly` | 按月汇总 | 预汇总到月粒度 |
| `yearly` | 按年汇总 | 预汇总到年粒度 |
| `NULL` | 无时间粒度 | 维度表 |

### 4.4 属性结构（attrs）

#### 表对象 attrs

```json
{
  "keys": ["id", "code"],           // 主键列
  "measures": ["amount", "count"],  // 度量字段
  "fks": [                          // 外键关系
    {"from": "store_id", "ref": "public.dim_store.store_id"},
    {"from": "product_id", "ref": "public.dim_product.product_id"}
  ],
  "indexes": ["store_id", ["store_id","date"]],  // 索引
  "sample": {                       // 示例值（部分字段）
    "amount": ["100.00", "200.50"],
    "status": ["active", "closed"]
  },
  "notes": "明细级别；可对 amount 聚合"
}
```

#### 列对象 attrs

```json
// 主键列
{"is_pk": true}

// 外键列
{"is_fk": true, "ref": "public.dim_store.store_id"}

// 时间列
{"is_time": true}

// 度量字段
{"is_measure": true}

// 复合
{"is_fk": true, "is_time": true, "ref": "..."}
```

---

## 5. 使用指南

### 5.1 环境准备

#### 1. 安装 pgvector 扩展

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

#### 2. 配置环境变量（.env）

```bash
# 数据库连接
DB_HOST=localhost
DB_PORT=5432
DB_NAME=your_database
DB_USER=postgres
DB_PASSWORD=your_password

# Schema 配置
DB_SCHEMA=public          # 源数据 schema
TARGET_SCHEMA=system      # 向量存储 schema

# Embedding API
DASHSCOPE_API_KEY=sk-xxx  # 通义千问 API Key
```

#### 3. 配置 embedding（config.yaml）

```yaml
embedding:
  enabled: true
  provider: qwen
  qwen:
    model: text-embedding-v3  # 必须是 1024 维模型
    api_key: ${DASHSCOPE_API_KEY}
    base_url: https://dashscope.aliyuncs.com/api/v1
    batch_size: 10
    timeout_ms: 30000
    retry:
      max_attempts: 3
      backoff_ms: 500
      jitter_ms: 100
```

### 5.2 命令行使用

#### 测试连接

```bash
python -m gen_sql.test_connection
```

检查项：
- ✅ 数据库连接
- ✅ pgvector 扩展
- ✅ Embedding 服务
- ✅ 向量维度（1024）

#### 数据加载

```bash
# 演练模式（不写入，查看将要处理的内容）
python -m gen_sql.cli --dry-run

# 正式加载所有表
python -m gen_sql.cli

# 只加载特定表（支持通配符）
python -m gen_sql.cli --tables "fact_*,dim_*"

# 指定采样行数
python -m gen_sql.cli --sample-rows 10

# 指定批次大小
python -m gen_sql.cli --batch-size 100
```

#### 向量相似度查询

```bash
# 查询"销售额"相关的对象（表+列）
python -m gen_sql.test_similarity --query "销售额"

# 只查询表对象
python -m gen_sql.test_similarity --query "便利店" --type table

# 只查询列对象
python -m gen_sql.test_similarity --query "月份" --type column

# 指定返回数量
python -m gen_sql.test_similarity --query "金额" --top-k 20
```

### 5.3 SQL 查询示例

#### 统计对象数量

```sql
SELECT object_type, COUNT(*) AS count
FROM system.sem_object_vec
GROUP BY object_type;
```

#### 查看表对象

```sql
SELECT object_id, text_raw, grain_hint, time_col_hint
FROM system.sem_object_vec
WHERE object_type = 'table'
ORDER BY object_id;
```

#### 查看列对象

```sql
SELECT object_id, text_raw, attrs
FROM system.sem_object_vec
WHERE object_type = 'column' 
  AND parent_id = 'public.fact_sales'
ORDER BY object_id;
```

#### 验证向量维度

```sql
SELECT object_id, array_length(embedding, 1) AS dimension
FROM system.sem_object_vec
LIMIT 5;
```

#### 向量相似度搜索

```sql
-- 需要先生成查询向量
-- 假设查询"销售金额"的向量为 query_vec

SELECT 
  object_type,
  object_id, 
  text_raw,
  1 - (embedding <=> :query_vec::vector) AS similarity
FROM system.sem_object_vec
ORDER BY embedding <=> :query_vec::vector
LIMIT 10;
```

---

## 6. 配置说明

### 6.1 表过滤配置

在 `settings.py` 或通过环境变量配置：

```python
# 包含模式（白名单）
INCLUDE_TABLES = "fact_*,dim_*"

# 排除模式（黑名单）
EXCLUDE_TABLES = "tmp_*,test_*"
```

### 6.2 采样配置

```python
# 每表采样行数（默认 5）
SAMPLE_ROWS = 5

# 采样策略
SAMPLING_STRATEGY = "random"  # random | full
```

### 6.3 向量模型配置

#### 通义千问（推荐）

```yaml
embedding:
  provider: qwen
  qwen:
    model: text-embedding-v3      # 1024 维
    api_key: ${DASHSCOPE_API_KEY}
    batch_size: 10                # 每批文本数
    timeout_ms: 30000             # 超时 30 秒
```

#### OpenAI 兼容

```yaml
embedding:
  provider: openai
  openai:
    model: text-embedding-ada-002  # 需验证维度
    api_key: ${OPENAI_API_KEY}
    base_url: https://api.openai.com/v1
    batch_size: 100
```

---

## 7. 性能优化

### 7.1 批处理策略

- **向量生成**：每批 10-25 个文本（根据 API 限制）
- **数据库写入**：每批 500 条记录
- **事务提交**：每批提交一次，避免长事务

### 7.2 并发控制

当前实现为串行处理，未来可优化：
- 多表并行处理
- 向量生成并发调用
- 数据库写入异步化

### 7.3 索引优化

```sql
-- parent_id B-tree 索引（按表查询）
CREATE INDEX idx_sem_object_vec_type_parent
  ON system.sem_object_vec (object_type, parent_id);

-- HNSW 向量索引（相似度搜索）
CREATE INDEX idx_sem_object_vec_emb_hnsw
  ON system.sem_object_vec 
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

**HNSW 参数说明**：
- `m`：每个节点的连接数（默认 16，越大检索越快但空间越大）
- `ef_construction`：构建时的搜索深度（默认 64，越大构建越慢但质量越高）

---

## 8. 故障排查

### 8.1 常见问题

#### 问题 1: pgvector 扩展未安装

**错误信息**：
```
ERROR: type "vector" does not exist
```

**解决方案**：
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

#### 问题 2: 向量维度不匹配

**错误信息**：
```
ValueError: embedding model outputs 1536 dimensions, expected 1024
```

**解决方案**：
更换为 1024 维模型，如通义千问 `text-embedding-v3`

#### 问题 3: Embedding API 超时

**错误信息**：
```
TimeoutError: Qwen embedding request timeout
```

**解决方案**：
- 增加超时时间：`timeout_ms: 60000`
- 减小批次大小：`batch_size: 5`
- 检查网络连接

#### 问题 4: 表已存在但无法写入

**错误信息**：
```
RuntimeError: 目标表 system.sem_object_vec 不存在
```

**解决方案**：
启用 DDL 管理模式：
```python
writer = SemanticObjectWriter(
    connection_string=conn_str,
    manage_ddl=True  # 自动创建表
)
```

### 8.2 日志分析

日志位置：`gen_sql/logs/`

**关键日志**：
- 表扫描：`发现 N 个表`
- 向量生成：`批量生成向量: 成功 M/N`
- 写入进度：`已写入 X/Y 个对象`
- 错误信息：`ERROR: ...`

---

## 9. 扩展与限制

### 9.1 当前限制

1. **LLM 增强未实现**：语义描述完全基于规则，未使用 LLM 润色
2. **并发处理未实现**：当前为串行处理，性能有优化空间
3. **增量更新未实现**：每次全量 UPSERT，未检测变更
4. **metric 对象未支持**：仅支持 table 和 column 类型
5. **向量模型限制**：仅支持 1024 维模型

### 9.2 后续改进方向

- [ ] 实现 LLM 增强功能（调用 LLM 优化 text_raw）
- [ ] 增加并发处理能力（多表并行）
- [ ] 实现增量更新检测（结构变更才重新生成）
- [ ] 支持 metric 对象类型
- [ ] 支持本地 embedding 模型
- [ ] 添加更多粒度类型（weekly/quarterly）
- [ ] 优化大表采样策略
- [ ] 实现向量压缩和量化

### 9.3 与主模块的关系

**gen_sql 模块是独立的**，与主 DB2Graph 模块分离：

```
db2graph/
├── src/                    # 主模块：表关系发现 → Neo4j
│   ├── agent/
│   ├── tools/
│   └── ...
│
└── gen_sql/                # 独立模块：元数据 → pgvector
    ├── metadata_loader.py
    ├── embedding_client.py
    ├── writer.py
    └── ...
```

**设计原因**：
- 不同的目标：关系图谱 vs 语义向量
- 不同的存储：Neo4j vs pgvector
- 不同的应用：关系分析 vs SQL 生成

---

## 10. 应用场景

### 10.1 SQL 生成 Agent

```python
# 1. 用户查询：显示每个便利店本月的销售额
user_query = "显示每个便利店本月的销售额"

# 2. 语义检索相关表
tables = search_similar_objects(user_query, object_type='table', top_k=5)
# 返回：fact_store_sales_month, dim_store, ...

# 3. 语义检索相关列
columns = search_similar_objects(user_query, object_type='column', top_k=10)
# 返回：amount, store_name, date_month, ...

# 4. 生成 SQL
sql = generate_sql(user_query, tables, columns)
```

### 10.2 数据发现

```python
# 查找所有包含"金额"的列
columns = search_similar_objects("金额", object_type='column')

# 查找所有日粒度汇总表
daily_tables = query_by_grain_hint('daily')
```

### 10.3 知识图谱

结合 DB2Graph 主模块的关系图谱和语义向量，构建完整的数据知识图谱：

```
表语义向量 + 表关系图谱 + 列语义向量
          ↓
    智能数据助手
```

---

## 11. 总结

### 11.1 核心价值

- ✅ **自动化**：自动提取、转换、加载数据库元数据
- ✅ **语义化**：将结构化元数据转换为自然语言描述
- ✅ **向量化**：生成 1024 维语义向量，支持相似度搜索
- ✅ **标准化**：统一的数据模型和属性结构
- ✅ **可扩展**：支持多种 embedding 模型和配置

### 11.2 技术特点

- **幂等性**：重复运行安全，自动更新
- **批处理**：高效的批量处理和写入
- **容错性**：重试机制和错误处理
- **可观测**：详细的日志和进度显示
- **高性能**：HNSW 索引加速向量搜索

### 11.3 适用场景

- 🎯 SQL 生成 Agent 的基础数据源
- 🎯 数据库语义搜索和发现
- 🎯 知识图谱构建
- 🎯 智能数据助手

---

**文档版本**: v1.0  
**最后更新**: 2025-11-17  
**维护者**: DB2Graph 开发团队  
**相关文档**: 
- [DB2Graph 项目概览与架构理解](./DB2Graph%20项目概览与架构理解.md)
- [DB2Graph 详细设计文档](./DB2Graph_详细设计文档.md)

