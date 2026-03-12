# 92 - Column 维度文本向量检索增强设计

## 1. 问题背景

当前 Schema Retrieval 流程中，`question_parsing` 节点会将用户问题解析为 `parse_result`，其中 `dimensions` 列表包含两种角色：

- `role="value"`：具体的维度值（如 "Mike Hillyer"、"Jon Stephens"）
- `role="column"`：维度列描述（如 "城市"）

**现状**：步骤 2.3（`_retrieve_dim_value_hits`）仅处理 `role="value"` 的维度，将其送入 `dim_value_embeddings` 进行向量检索。`role="column"` 的维度信息仅用于提示词格式化，**不参与任何向量检索**。

**问题**：当用户问题以人名等专有名词为主时（如"Mike Hillyer和Jon Stephens分别在哪个城市"），全句 embedding 被人名语义主导，无法有效召回"城市"相关的表（如 `address`、`city`）。而"城市"作为 `role="column"` 维度被正确提取，却未被利用。

## 2. 目标

在步骤 2.3 中增加对 `role="column"` 维度的向量检索，通过在 `table_schema_embeddings` 中搜索匹配列，提取其父表并补充到候选表集合中，提高候选表召回率。

## 3. 设计方案

### 3.1 新增方法：`_retrieve_column_dimension_hits`

在 `retriever.py` 中新增一个私有方法：

```python
def _retrieve_column_dimension_hits(
    self,
    parse_result: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
```

**返回结构**（与 `search_columns` 一致）：

```python
{
    "object_id": "dvdrental.public.city.city",       # 命中的列
    "parent_id": "dvdrental.public.city",             # 父表
    "object_type": "column",
    "similarity": 0.87,
    "table_category": "",                              # ⚠️ Milvus 中 column 记录此字段为空，需通过 3.3 补全
    "source_dimension_text": "城市",                   # 触发检索的维度文本（新增，便于日志追踪）
}
```

**逻辑步骤**：

1. 从 `parse_result["dimensions"]` 中筛选 `role="column"` 的条目
2. 按 `text` 去重（同一列词被重复抽取时，避免重复的 embedding 生成 + Milvus 检索）
3. 对每个 column 维度的 `text` 字段，调用 `self.embedding_client.embed_query(text)` 生成 embedding
4. 调用 `self.vector_client.search_columns(embedding, top_k, similarity_threshold)` 在 `table_schema_embeddings`（`object_type="column"`）中检索
5. 为每条命中结果附加 `source_dimension_text`（触发检索的维度文本）
6. 汇总所有命中结果并返回

**参数来源**：
- `top_k`：复用现有配置 `self.topk_columns`（来自 `sql_generation_subgraph.yaml` 的 `schema_retrieval.topk_columns`）
- `similarity_threshold`：复用现有配置 `self.similarity_threshold`（来自 `schema_retrieval.similarity_threshold`，表和列检索共用）

### 3.2 调用位置

在 `_collect_and_classify_tables` 方法中，在现有步骤 1（维度值检索）之后、步骤 3（列命中收集父表）之前插入调用：

```python
def _collect_and_classify_tables(self, semantic_tables, semantic_columns, parse_result):
    # 1) 维度值检索（已有）
    dim_value_hits = self._retrieve_dim_value_hits(parse_result)

    # 2) 通过维度值命中获取维度表（已有）
    dim_tables_from_values = ...

    # ✅ 2.5) 【新增】通过 column 维度文本检索补充候选列命中
    column_dim_hits = self._retrieve_column_dimension_hits(parse_result)

    # 3) 通过列命中收集父表（已有）
    ...
```

### 3.3 table_category 补全与候选表合并

**关键约束**：Milvus 中 `object_type="column"` 的记录 `table_category` 字段为空。`search_columns` 虽然请求了该字段（`milvus_adapter.py:185`），但返回值是空字符串。因此不能直接使用列命中自带的 `table_category` 进行分类。

**处理方案**：在步骤 3 的分类循环之前，对 `column_dim_hits` 中的父表批量补全 `table_category`：

```python
# ✅ 初始化 table_category_map（由 semantic_tables 构造，原已有逻辑）
table_category_map = {
    t.get("object_id"): (t.get("table_category") or t.get("category") or "")
    for t in semantic_tables
    if t.get("object_id")
}

# ✅ 提前初始化 table_similarities 和 table_categories（原在步骤 4，详见 3.4 节）
table_similarities: Dict[str, float] = {}
table_categories: Dict[str, str] = {}

# ✅ 2.5) 【新增】通过 column 维度文本检索补充候选列命中
column_dim_hits = self._retrieve_column_dimension_hits(parse_result)

# ✅ 2.6) 【新增】补全 column_dim_hits 父表的 table_category
#   Milvus 中 object_type="column" 的 table_category 为空，需通过父表 ID 查询
column_parent_ids = list({
    col.get("parent_id") for col in column_dim_hits if col.get("parent_id")
})
# 仅查询 table_category_map 中缺失的父表（semantic_tables 已有的不必重复查）
missing_parents = [pid for pid in column_parent_ids if pid not in table_category_map]
if missing_parents:
    extra_categories = self.vector_client.fetch_table_categories(missing_parents)
    table_category_map.update(extra_categories)
    # ✅ 同步写入 table_categories（确保最终 schema_context 中分类完整，避免步骤 6 重复查询）
    table_categories.update(extra_categories)

# 3) 通过列命中收集父表（已有逻辑 + column_dim_hits 合并）
all_column_hits = semantic_columns + column_dim_hits

for col in all_column_hits:
    parent_id = col.get("parent_id")
    category = table_category_map.get(parent_id, "")
    category_group = self._classify_table_category(category)
    # → 归入 fact_from_columns / dim_from_columns / bridge_from_columns
```

**说明**：
- `table_category_map` 由 `semantic_tables` 构造（已有逻辑，此处显式写出以明确初始化时序）
- `fetch_table_categories` 查询 `table_schema_embeddings` 中 `object_type="table"` 的记录，能正确返回 `table_category`（参考 `milvus_adapter.py:326-356`）
- 仅对 `table_category_map` 中缺失的父表发起查询，避免重复请求
- 查询结果同时写入 `table_category_map`（步骤 3 分类用）和 `table_categories`（最终进入 `schema_context.table_categories`，供提示词展示和后续缺失分类补全逻辑使用），避免 `_collect_and_classify_tables` 末尾的 `fetch_table_categories` 重复查询同一批表
- 如果 `fetch_table_categories` 仍未返回某父表的分类（如该表不在 Milvus 中），`_classify_table_category("")` 会将其归为 dimension（空值默认行为）

### 3.4 同一父表多列命中时的相似度合并

同一父表可能通过多个列命中（如"城市"同时命中 `city.city` 和 `address.city_id`），需明确 `table_similarities` 的合并规则。

**前置条件：调整变量初始化时机**

当前代码中 `table_similarities` 和 `table_categories` 在步骤 4 才初始化（`retriever.py:428-429`）。为了在步骤 3 的循环中写入相似度，需将这两个变量的初始化提前到步骤 3 之前：

```python
# ✅ 提前初始化（原在步骤 4，现提到步骤 3 之前）
table_similarities: Dict[str, float] = {}
table_categories: Dict[str, str] = {}

# 3) 通过列命中收集父表（已有 + column_dim_hits 合并）
all_column_hits = semantic_columns + column_dim_hits

for col in all_column_hits:
    parent_id = col.get("parent_id")
    ...
    # 写入相似度（取 max）
    similarity = col.get("similarity")
    if parent_id and similarity is not None:
        existing = table_similarities.get(parent_id, 0.0)
        table_similarities[parent_id] = max(existing, float(similarity))

# 4) 语义检索结果分类（已有逻辑不变，继续往同一个 dict 里写）
for table in semantic_tables:
    ...
    table_similarities[table_id] = float(similarity)  # 表级检索的分数可能更高，直接覆盖
```

步骤 4 的赋值是对表级检索结果的直接写入（每个 table_id 只出现一次），如果同一个表在步骤 3 已通过列命中写入了分数，步骤 4 的表级分数会直接覆盖。这是按**信号优先级**设计的：表级语义匹配是对表整体的直接检索，信号优先级高于列级命中推导出的间接相似度，因此覆盖是正确的行为。

**规则：取 max(similarity)**

在步骤 3 的循环中，同一父表多列命中时取较大者：

```python
existing = table_similarities.get(parent_id, 0.0)
table_similarities[parent_id] = max(existing, float(similarity))
```

**理由**：
- 下游 base 表选择使用 `key=lambda t: table_similarities.get(t, 0.0)` 排序（`retriever.py:542`），取 max 与排序语义一致
- 步骤 4 的表级检索分数按信号优先级覆盖步骤 3 的列级推导分数（表级直接检索 > 列级间接推导）
- 注意：现有步骤 3（`semantic_columns` 处理）也存在同样的问题——列命中的父表从未写入 `table_similarities`，导致这些表在下游排序中被当作 0 分。本次改动一并修复

## 4. 数据流示意

```
parse_result.dimensions
    ├── role="value"  → dim_value_embeddings 检索 → dim_tables_from_values      （已有）
    └── role="column" → 【新增】embed_query(text)
                          → search_columns(embedding) in table_schema_embeddings
                          → column_dim_hits（含 parent_id, similarity）
                          → fetch_table_categories(parent_ids) 补全 table_category
                          → 合并到步骤 3 的列→父表分类循环
                          → 按 table_category 归入 fact/dim/bridge_from_columns
```

## 5. 预期效果

以问题 "系统中Mike Hillyer和Jon Stephens分别在哪个城市？" 为例：

- `parse_result` 包含 `role="column"` 维度 `text="城市"`
- 对"城市"生成 embedding，在 `table_schema_embeddings` 中搜索 `object_type="column"`
- 预期匹配：`city.city`（城市名列）、`address.city_id`（城市外键）等
- 提取父表：`dvdrental.public.city`、`dvdrental.public.address`
- 这两个表被补充到候选表集合中，并按 `table_category` 分类进入 fact/dimension/bridge，后续 Neo4j JOIN 路径规划可正确生成 `staff → address → city` 的 JOIN 链

## 6. 影响范围

| 文件 | 变更类型 |
|------|---------|
| `src/tools/schema_retrieval/retriever.py` | 新增 `_retrieve_column_dimension_hits` 方法；修改 `_collect_and_classify_tables`（变量初始化前移 + 步骤 3 循环合并 column_dim_hits + 写入 table_similarities/table_categories）；修改 `_collect_table_names` 或 `metadata.table_count` 统计口径 |

**不涉及的变更**：
- 不需要修改 Milvus adapter（`search_columns` 方法已存在）
- 不需要修改 embedding client（`embed_query` 方法已存在）
- 不需要修改配置文件（复用现有 `topk_columns` 和 `similarity_threshold`）
- 不需要修改 question_parsing（`role="column"` 已被正确提取）

### 6.1 统计口径调整

当前 `metadata.table_count` 仅统计整句语义召回的表和列的父表（`_collect_table_names` 只接收 `semantic_tables` + `semantic_columns`，`retriever.py:245`）。本次新增的 column-dimension backfill 补入的候选表不在统计范围内，会导致调试日志显示"0表"但实际候选表已被补入的困惑。

**修复**：将 `column_dim_hits` 的父表也纳入统计。两种方案二选一：
- **方案 A**：扩展 `_collect_table_names` 参数，传入 `column_dim_hits`，在其中也提取 `parent_id`
- **方案 B**：改用候选表集合总去重后的实际数量作为 `table_count`

推荐方案 B，因为它直接反映最终候选表数量，不会随来源增加而遗漏。注意需对三个列表总去重后再计数，避免同一张表因不同来源进入多个 bucket 导致重复计数：

```python
all_candidates = dict.fromkeys(
    candidate_fact_tables + candidate_dim_tables + candidate_bridge_tables
)
table_count = len(all_candidates)
```

## 7. 日志与测试

### 7.1 日志记录

**日志分层规则**：
- **私有 helper 内**：只打无 `query_id` 的细粒度日志（`with_query_id(logger, "")`）
- **`retrieve()` 上层**：打带 `query_id` 的汇总日志（已有的 `qlog`）

在 `_retrieve_column_dimension_hits` 方法中（细粒度，无 `query_id`）：

```python
qlog = with_query_id(logger, "")

# 入口：记录待检索的 column 维度
qlog.debug(f"column dimension 检索: {[d['text'] for d in column_dimensions]}")

# 每个维度检索后：记录命中列
qlog.debug(f"column dimension '{text}' 命中 {len(matches)} 列: {[m['object_id'] for m in matches]}")
```

在 `_collect_and_classify_tables` 方法中（细粒度，无 `query_id`），构造 `column_dim_summary` 并作为返回值的一部分带回上层：

```python
qlog = with_query_id(logger, "")

# 循环中收集（仅针对 column_dim_hits 来源的命中）
column_dim_summary: Dict[str, Dict] = {}
for col in column_dim_hits:
    parent_id = col.get("parent_id")
    if not parent_id:
        continue
    if parent_id not in column_dim_summary:
        column_dim_summary[parent_id] = {
            "best_similarity": 0.0,
            "raw_category": table_category_map.get(parent_id, ""),
            "category_group": "",
            "source_texts": [],
        }
    entry = column_dim_summary[parent_id]
    entry["best_similarity"] = max(entry["best_similarity"], float(col.get("similarity", 0)))
    entry["category_group"] = self._classify_table_category(entry["raw_category"])
    src = col.get("source_dimension_text", "")
    if src and src not in entry["source_texts"]:
        entry["source_texts"].append(src)

# 私有方法内打细粒度日志（无 query_id）
qlog.debug(f"column dimension 补充候选表: {column_dim_summary}")
```

`_collect_and_classify_tables()` 返回值新增 `column_dim_summary` 字段：

```python
return {
    "candidate_fact_tables": candidate_fact_tables,
    "candidate_dim_tables": candidate_dim_tables,
    "candidate_bridge_tables": candidate_bridge_tables,
    "table_similarities": table_similarities,
    "table_categories": table_categories,
    "dim_value_hits": dim_value_hits,
    "column_dim_summary": column_dim_summary,  # ✅ 新增：column dimension 补充候选表汇总（仅日志用）
}
```

在上层 `retrieve()` 方法中，从 `candidate_set` 读取并打印汇总日志（带 `query_id`）：

```python
# 已有 qlog = with_query_id(logger, query_id)
column_dim_summary = candidate_set.get("column_dim_summary", {})
qlog.debug(f"column dimension backfill 补充 {len(column_dim_summary)} 个父表: {list(column_dim_summary.keys())}")
# 示例输出:
# [q_abc123] column dimension backfill 补充 2 个父表: ['dvdrental.public.city', 'dvdrental.public.address']
```

### 7.2 单测覆盖

| 测试场景 | 验证点 |
|---------|--------|
| 单个 `role="column"` 维度 | 正确调用 `embed_query` + `search_columns`，父表进入候选集 |
| 多个 `role="column"` 维度 | 每个维度独立检索，结果合并 |
| 同一父表多列命中 | 候选表去重；`table_similarities` 取 max |
| `table_category` 补全三层回退 | 1) 列记录自带为空 → 2) `fetch_table_categories(parent_id)` 补全成功 → 正确分类；3) `fetch_table_categories` 也未返回 → `_classify_table_category("")` 归为 dimension |
| `fetch_table_categories` 部分命中 | 多个父表中部分有分类、部分无分类，验证有分类的正确归类、无分类的归为 dimension |
| 与 `semantic_tables` / `dim_tables_from_values` 合并 | `dict.fromkeys` 去重正确，不引入重复候选表 |
| 同一 `role="column"` 文本重复抽取 | 去重后只调用一次 `embed_query` + 一次 `search_columns`，验证性能优化生效 |
| 无 `role="column"` 维度 | 返回空列表，不影响现有流程 |

## 8. 风险与注意事项

1. **性能**：每个 `role="column"` 维度需额外一次 embedding 生成 + 一次 Milvus 检索。通常 column 维度数量较少（1-3个），性能影响可控。
2. **误召回**：如果 column 维度文本过于宽泛（如"数量"），可能召回过多不相关表。通过 `similarity_threshold` 控制。
3. **重复候选表**：新增的表可能与已有候选表重复。步骤 3 的 `if parent_id not in` 判断 + 步骤 5 的 `dict.fromkeys` 双重去重。
