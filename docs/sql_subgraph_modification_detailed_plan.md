# SQL生成子图改造实施计划（简化版 v2.5）

## 文档说明

- **版本**: v2.5（修正版）
- **更新日期**: 2025-11-02
- **改造原则**: 最小化改动，聚焦核心功能
- **参考文档**:
  - `docs/13.SQL生成流程文档.md` - Parser节点设计
  - `docs/15.完整提示词与真实案例.md` - 提示词结构

**注**：历史SQL检索保持简单，只根据问题向量检索相似案例，作为一般性参考。候选表筛选已在Schema检索阶段通过向量+图检索完成。

---

## 1. 核心问题与改造目标

### 1.1 当前问题

基于 `docs/16.重要修改建议.txt` 的分析，当前子图有两个主要问题：

**问题1：缺少问题解析节点**
- **现状**: 子图直接依赖外部传入的 `parse_hints`，无法自主解析问题
- **位置**: `src/modules/sql_generation/subgraph/create_subgraph.py:58-92`
- **流程**: `START → schema_retrieval → sql_generation → validation`

**问题2：历史SQL检索位置不当**
- **现状**: 在 Schema检索阶段调用 `search_similar_sqls`（`retriever.py:100-104`）
- **问题**: 应该在 SQL生成阶段作为参考，历史SQL只是辅助信息，不应影响Schema检索

### 1.2 改造目标

1. ✅ 新增 Parser 节点，支持自主解析问题
2. ✅ 将历史SQL检索从 Schema检索阶段移到 SQL生成阶段
3. ✅ 共享查询向量，避免重复计算
4. ✅ 调整提示词顺序，添加解析摘要
5. ✅ 保持向后兼容（外部可继续传入 `parse_hints`）

**不做的事情**：
- ❌ 不扩展数据库表结构（保持现有 `system.sql_embedding` 表）
- ❌ 不增加复杂的表过滤、质量评分逻辑
- ❌ 历史SQL只返回基本信息：`question`、`sql`、`similarity`

---

## 2. 改造任务清单

### 任务 2.1：新增问题解析节点（P0 - 核心）

#### 2.1.1 创建 Parser 节点

**文件**: `src/modules/sql_generation/subgraph/nodes/question_parsing.py`（新建）

**实现**:

```python
"""问题解析节点 - 将自然语言问题转换为结构化 QueryParseResult"""

from typing import Dict, Any, Optional
from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import SystemMessage, HumanMessage
import json
from datetime import datetime

from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config


class QuestionParsingAgent:
    """问题解析 Agent"""

    def __init__(self, config: Dict[str, Any]):
        self.llm = ChatTongyi(
            model=config.get("parser_model", "qwen-plus"),
            dashscope_api_key=config.get("api_key"),
            temperature=0,
            max_tokens=1500
        )

    def parse(self, query: str, current_date: str = None) -> Dict[str, Any]:
        """
        解析问题为 QueryParseResult

        Returns:
            {
                "keywords": List[str],
                "time": {...} | None,
                "metric": {...},
                "dimensions": [...],
                "intent": {...},
                "signals": [...]
            }
        """
        if current_date is None:
            current_date = datetime.now().strftime("%Y-%m-%d")

        # 构建提示词
        system_prompt = """You are a Chinese business intelligence analyst who extracts structured intents from natural language questions.
Follow these rules strictly:
1. **IMPORTANT**: Time field handling:
   - If the question does NOT explicitly mention any time constraint, the time field MUST be null.
   - Do NOT infer, guess, or create default time ranges when no time is mentioned.
2. Always emit valid JSON that matches the QueryParseResult schema.
3. Classify each dimension as either a column name (column) or a literal value (value).
"""

        user_prompt = f"""今天的日期是: {current_date} (Asia/Shanghai 时区)

请分析下述问题, 给出严格 JSON 输出。
问题: {query}

JSON schema:
{{
  "keywords": [str],
  "time": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "grain_inferred": str, "is_full_period": bool}} | null,
  "metric": {{"text": str, "is_aggregate_candidate": bool}},
  "dimensions": [{{"text": str, "role": "column|value", "evidence": str}}],
  "intent": {{"task": "plain_agg|topn|rank|compare_yoy|compare_mom", "topn": int|null}},
  "signals": [str]
}}

注意: time 字段仅在问题中明确提及时间约束时才填充, 否则必须为 null。
输出要求: 仅输出 JSON, 不要额外说明。
"""

        # 调用LLM
        response = self.llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])

        # 解析JSON
        try:
            result = json.loads(response.content.strip())
            return result
        except Exception as e:
            raise ValueError(f"JSON解析失败: {e}, 原始输出: {response.content[:200]}")


def question_parsing_node(state: SQLGenerationState) -> Dict[str, Any]:
    """
    问题解析节点

    功能：
    1. 如果 state 中已有 parse_hints，直接使用（向后兼容）
    2. 否则，调用 LLM 解析问题
    """
    # 检查是否已有 parse_hints（外部注入）
    if state.get("parse_hints"):
        print(f"[{state['query_id']}] 使用外部传入的 parse_hints")
        return {
            "parse_result": state["parse_hints"],
            "parsing_source": "external"
        }

    # 调用 Parser Agent
    config = load_subgraph_config("sql_generation")
    parser_config = config.get("question_parsing", {})

    # ⭐ 检查是否启用内部解析
    if not parser_config.get("enable_internal_parser", True):
        print(f"[{state['query_id']}] 内部解析已禁用，使用空解析结果")
        return {
            "parse_result": {},
            "parsing_source": "disabled"
        }

    agent = QuestionParsingAgent(parser_config)

    try:
        print(f"[{state['query_id']}] 开始解析问题...")
        parse_result = agent.parse(query=state["query"])
        print(f"[{state['query_id']}] 问题解析完成")

        return {
            "parse_result": parse_result,
            "parsing_source": "llm"
        }
    except Exception as e:
        print(f"[{state['query_id']}] ❌ 问题解析失败: {e}")

        # ⭐ 根据配置决定是否返回空结构
        fallback_to_empty = parser_config.get("fallback_to_empty", True)
        if fallback_to_empty:
            print(f"[{state['query_id']}] 使用空解析结果作为回退")
            return {
                "parse_result": {},
                "parsing_source": "fallback",
                "parsing_error": str(e)
            }
        else:
            return {
                "parse_result": None,
                "error": f"问题解析失败: {str(e)}",
                "error_type": "parsing_failed"
            }
```

#### 2.1.2 扩展 State 定义

**文件**: `src/modules/sql_generation/subgraph/state.py`

**在第22行后添加**:

```python
# ========== 新增：解析阶段 ==========
parse_result: Optional[Dict[str, Any]] = None  # 解析结果（结构化）
parsing_source: Optional[str] = None  # "external" | "llm"
query_embedding: Optional[List[float]] = None  # 查询向量（共享）
```

**完整修改后的关键部分**:

```python
class SQLGenerationState(MessagesState):
    """SQL 生成子图的状态"""

    # ========== 输入字段 ==========
    query: str
    query_id: str
    dependencies_results: Dict[str, Any]
    user_query: str
    parse_hints: Optional[Dict[str, Any]]  # 保留，用于向后兼容

    # ========== 新增：解析阶段 ==========
    parse_result: Optional[Dict[str, Any]] = None  # ⭐ 新增
    parsing_source: Optional[str] = None  # ⭐ 新增
    query_embedding: Optional[List[float]] = None  # ⭐ 新增

    # ========== Schema检索阶段 ==========
    schema_context: Optional[Dict[str, Any]] = None

    # ... 其他字段保持不变 ...
```

#### 2.1.3 调整子图拓扑

**文件**: `src/modules/sql_generation/subgraph/create_subgraph.py`

**修改 `create_sql_generation_subgraph` 函数**:

```python
def create_sql_generation_subgraph():
    """创建 SQL 生成子图"""
    subgraph = StateGraph(SQLGenerationState)

    # ⭐ 添加解析节点
    from src.modules.sql_generation.subgraph.nodes.question_parsing import question_parsing_node

    # 添加节点
    subgraph.add_node("question_parsing", question_parsing_node)  # ⭐ 新增
    subgraph.add_node("schema_retrieval", schema_retrieval_node)
    subgraph.add_node("sql_generation", sql_generation_node)
    subgraph.add_node("validation", validation_node)

    # ⭐ 修改入口：START -> question_parsing
    subgraph.add_edge(START, "question_parsing")

    # ⭐ 条件边：question_parsing -> schema_retrieval 或 END
    def check_parsing(state):
        if state.get("error_type") == "parsing_failed":
            return "fail"
        return "continue"

    subgraph.add_conditional_edges(
        "question_parsing",
        check_parsing,
        {
            "continue": "schema_retrieval",
            "fail": END
        }
    )

    # 固定边：schema_retrieval -> sql_generation
    subgraph.add_edge("schema_retrieval", "sql_generation")

    # ... 其余边保持不变 ...

    return subgraph.compile()
```

#### 2.1.4 配置扩展

**文件**: `src/modules/sql_generation/config/sql_generation_subgraph.yaml`

**在文件开头添加**:

```yaml
# ------------------------------------------------------------------------------
# 问题解析配置
# ------------------------------------------------------------------------------
question_parsing:
  # Parser LLM 配置
  parser_model: qwen-plus
  api_key: ${DASHSCOPE_API_KEY}
  temperature: 0
  max_tokens: 1500
  timeout: 20

  # 解析策略
  enable_internal_parser: true         # 是否启用内部解析（false时跳过LLM调用）
  fallback_to_empty: true              # 解析失败时返回空结构（false时抛出错误中断流程）
```

**配置项说明**：
- `enable_internal_parser`:
  - `true`: 正常调用LLM解析
  - `false`: 跳过LLM解析，返回空的 `parse_result`（用于测试或强制使用外部 `parse_hints`）

- `fallback_to_empty`:
  - `true`: 解析失败时返回空结构，继续后续流程（降级模式）
  - `false`: 解析失败时返回错误，中断子图执行（严格模式）
```

---

### 任务 2.2：Schema检索阶段瘦身（P0 - 核心）

#### 2.2.1 调整 SchemaRetriever.retrieve

**文件**: `src/tools/schema_retrieval/retriever.py`

**修改 `retrieve` 方法签名和实现**:

```python
def retrieve(
    self,
    query: str,
    parse_result: Optional[Dict[str, Any]] = None,  # ⭐ 改名
    query_embedding: Optional[List[float]] = None,  # ⭐ 新增
) -> Tuple[Dict[str, Any], List[float]]:  # ⭐ 返回向量
    """
    检索 Schema 上下文

    Returns:
        (schema_context, query_embedding)
    """
    start_time = time.time()

    # 1) 生成或复用查询向量
    if query_embedding is None:
        query_embedding = self.embedding_client.embed_query(query)

    # 2) 向量检索：表和列
    semantic_tables = self.pg_client.search_semantic_tables(
        embedding=query_embedding,
        top_k=self.topk_tables,
        similarity_threshold=self.similarity_threshold,
    )

    semantic_columns = self.pg_client.search_semantic_columns(
        embedding=query_embedding,
        top_k=self.topk_columns,
        similarity_threshold=self.similarity_threshold,
    )

    # 3) 汇总候选表并分类（参考 docs/13 的 Retriever 阶段）
    candidate_set = self._collect_and_classify_tables(
        semantic_tables,
        semantic_columns,
        parse_result
    )
    # 返回：
    # {
    #   "candidate_fact_tables": [...],
    #   "candidate_dim_tables": [...],
    #   "table_similarities": {"table_id": 0.85, ...},
    #   "dim_value_hits": [...],  # 包含 source_index
    # }

    # 4) 图检索：JOIN 计划（参考 docs/13 的 Planner 阶段）
    join_plans = self._retrieve_join_plans(
        candidate_fact_tables=candidate_set["candidate_fact_tables"],
        candidate_dim_tables=candidate_set["candidate_dim_tables"],
        table_similarities=candidate_set["table_similarities"],
        parse_result=parse_result
    )

    # 5) 获取表卡片
    all_tables = list(set(
        candidate_set["candidate_fact_tables"] +
        candidate_set["candidate_dim_tables"]
    ))
    table_cards = self.pg_client.fetch_table_cards(all_tables)

    # ⭐ 6) 删除历史 SQL 检索（移到 Generator）
    # similar_sqls = self.pg_client.search_similar_sqls(...)  # ❌ 删除这行

    retrieval_time = time.time() - start_time

    schema_context = {
        # ⭐ 兼容历史字段，同时补充新版 CandidateSet 信息
        "tables": table_names,  # ← 保留旧字段，便于统计/测试沿用
        "columns": semantic_columns,
        "join_plans": join_plans,
        "table_cards": table_cards,
        "similar_sqls": [],  # 历史 SQL 移动到生成阶段时可置空/占位
        "dim_value_matches": candidate_set["dim_value_hits"],  # 旧字段沿用

        # ⭐ 新增字段（与 docs/13 CandidateSet 对齐）
        "candidate_fact_tables": candidate_set["candidate_fact_tables"],
        "candidate_dim_tables": candidate_set["candidate_dim_tables"],
        "table_similarities": candidate_set["table_similarities"],
        "dim_value_hits": candidate_set["dim_value_hits"],

        "metadata": {
            "retrieval_time": retrieval_time,
            "fact_table_count": len(candidate_set["candidate_fact_tables"]),
            "dim_table_count": len(candidate_set["candidate_dim_tables"]),
            "column_count": len(semantic_columns),
            "join_plan_count": len(join_plans),
            "dim_hit_count": len(candidate_set["dim_value_hits"]),
        },
    }

    return schema_context, query_embedding  # ⭐ 返回向量
```

**新增 `_collect_and_classify_tables` 方法**（解决问题2、4）:

```python
def _collect_and_classify_tables(
    self,
    semantic_tables: List[Dict[str, Any]],
    semantic_columns: List[Dict[str, Any]],
    parse_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    汇总候选表并分类

    参考 docs/13 第588-648行的逻辑

    Returns:
        {
            "candidate_fact_tables": [...],
            "candidate_dim_tables": [...],
            "table_similarities": {...},
            "dim_value_hits": [...]  # 包含 source_index
        }
    """
    # 1) 维度值检索（参考 docs/13:319-375）
    dim_value_hits = []
    if parse_result and parse_result.get("dimensions"):
        for idx, dimension in enumerate(parse_result["dimensions"]):
            if dimension.get("role") != "value":
                continue

            text_value = dimension.get("text", "").strip()
            if not text_value:
                continue

            # 调用维度值搜索
            hits = self.pg_client.search_dim_values(
                text_value,
                top_k=self.dim_index_topk
            )

            # ⭐ 标注来源维度索引（用于后续替换）
            for h in hits:
                h["source_text"] = dimension["text"]
                h["source_index"] = idx  # ← 关键：绑定到 parse_result.dimensions 的索引
                dim_value_hits.append(h)

    # 2) 路径1: 从 dim_value_hits 提取维度表
    dim_tables_from_values = set()
    for hit in dim_value_hits:
        table_name = hit.get("dim_table")
        if table_name:
            table_str = str(table_name).strip()
            if "." not in table_str:
                table_str = f"public.{table_str}"
            dim_tables_from_values.add(table_str)

    # 3) 路径2: 从列的 parent_id 提取表（按 table_category 分类）
    fact_from_columns = []
    dim_from_columns = []
    for col in semantic_columns:
        parent_id = col.get("parent_id")
        if not parent_id:
            continue

        category = col.get("table_category") or col.get("parent_category") or "dimension"
        if category == "fact":
            if parent_id not in fact_from_columns:
                fact_from_columns.append(parent_id)
        else:
            if parent_id not in dim_from_columns:
                dim_from_columns.append(parent_id)

    # 4) 路径3: 从语义表检索（按 category 分类）
    semantic_fact_tables = []
    semantic_dim_tables = []
    table_similarities = {}

    for table in semantic_tables:
        table_id = table.get("object_id")
        if not table_id:
            continue

        category = table.get("table_category") or table.get("category") or "dimension"
        similarity = table.get("similarity")

        if similarity is not None:
            table_similarities[table_id] = float(similarity)

        if category == "fact":
            semantic_fact_tables.append(table_id)
        else:
            semantic_dim_tables.append(table_id)

    # 5) 合并并去重
    all_fact_tables = semantic_fact_tables + fact_from_columns
    final_fact_tables = list(dict.fromkeys(all_fact_tables))  # 去重保持顺序

    all_dim_tables = (
        list(dim_tables_from_values) +
        dim_from_columns +
        semantic_dim_tables
    )
    final_dim_tables = list(dict.fromkeys(all_dim_tables))

    return {
        "candidate_fact_tables": final_fact_tables,
        "candidate_dim_tables": final_dim_tables,
        "table_similarities": table_similarities,
        "dim_value_hits": dim_value_hits,  # ← 包含 source_index
    }
```

**新增 `_retrieve_join_plans` 方法**（解决问题1）:

> ⚠️ 现有 `Neo4jClient.plan_join_paths` 接口签名为 `plan_join_paths(base_tables: List[str], target_tables: List[str], ...) -> List[Dict]`。
> 为了复用文档中的 `target -> edges` 结构，需要新增一个轻量的包装函数 `_plan_join_paths_for_base`，在内部调用旧接口后进行数据透传。

```python
def _retrieve_join_plans(
    self,
    candidate_fact_tables: List[str],
    candidate_dim_tables: List[str],
    table_similarities: Dict[str, float],
    parse_result: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    检索 JOIN 计划

    参考 docs/13 第718-900行的 Planner 阶段逻辑

    包含三个关键逻辑：
    1. 维度表优化判断（_should_use_dimension_only）
    2. Base表选择策略
    3. 连通性分析（多维度表场景）
    """
    from src.services.db.neo4j_client import get_neo4j_client

    # 1) 维度表优化判断（参考 docs/13:727-784）
    should_use_dim_only, dim_only_table = self._should_use_dimension_only(
        parse_result,
        candidate_fact_tables,
        candidate_dim_tables,
        table_similarities
    )

    if should_use_dim_only and dim_only_table:
        # 单维度表查询，无需 JOIN
        print(f"[维度表优化] 跳过 Neo4j 查询，使用单表: {dim_only_table}")
        return [{
            "base": dim_only_table,
            "targets": [],
            "edges": []
        }]

    # 2) 选择 base 表
    if candidate_fact_tables:
        # 有事实表：选择第一个事实表作为 base（或根据相似度排序）
        base_tables = candidate_fact_tables
    elif candidate_dim_tables:
        # 只有维度表：通过连通性分析选择 base（参考 docs/13:798-829）
        base_tables = self._select_best_dim_base(
            candidate_dim_tables,
            table_similarities
        )
    else:
        # 无候选表
        return []

    # 3) 对每个 base 表查询 JOIN 路径
    join_plans = []
    neo4j_client = get_neo4j_client()

    for base in base_tables:
        # 确定 targets
        all_tables = list(set(candidate_fact_tables + candidate_dim_tables))
        targets = [t for t in all_tables if t != base]

        if not targets:
            # 只有一个表，无需 JOIN
            join_plans.append({
                "base": base,
                "targets": [],
                "edges": []
            })
            continue

        # 查询 Neo4j 获取 JOIN 路径
        try:
            # ⭐ 使用内部包装函数，兼容现有 Neo4jClient 接口
            path_map = _plan_join_paths_for_base(
                neo4j_client=neo4j_client,
                base_table=base,
                target_tables=targets,
            )

            # 构建 edges
            edges = []
            seen = set()
            for target in targets:
                path = path_map.get(target) or []
                for edge in path:
                    key = (edge["src_table"], edge["dst_table"])
                    if key not in seen:
                        edges.append(edge)
                        seen.add(key)

            join_plans.append({
                "base": base,
                "targets": targets,
                "edges": edges
            })
        except Exception as e:
            print(f"[JOIN规划] base={base} 查询失败: {e}")
            continue

    return join_plans

def _plan_join_paths_for_base(
    neo4j_client,
    base_table: str,
    target_tables: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """包装现有 plan_join_paths 接口，提供 target→edges 映射"""

    if not target_tables:
        return {}

    plans = neo4j_client.plan_join_paths(
        base_tables=[base_table],
        target_tables=target_tables,
    )

    # 现有实现返回 List[Dict]，需转换为 {target: edges}
    edges_map: Dict[str, List[Dict[str, Any]]] = {}
    for plan in plans or []:
        if plan.get("base") != base_table:
            continue
        for target in plan.get("targets", []):
            edges_map[target] = plan.get("edges", [])
    return edges_map

def _should_use_dimension_only(
    self,
    parse_result: Optional[Dict[str, Any]],
    fact_tables: List[str],
    dim_tables: List[str],
    table_similarities: Dict[str, float],
) -> tuple[bool, Optional[str]]:
    """
    判断是否可以只用维度表

    参考 docs/13:727-784

    Returns:
        (should_use_dim_only, dim_table_to_use)
    """
    # 规则1: 有时间约束，通常需要事实表
    if parse_result and parse_result.get("time"):
        return False, None

    # 规则2: 没有维度表候选
    if not dim_tables:
        return False, None

    # 规则3: 纯维度表场景
    if not fact_tables:
        if len(dim_tables) == 1:
            return True, dim_tables[0]
        else:
            # 多个维度表，需要通过 Neo4j 判断关系
            return False, None

    # 规则4: 相似度差异判断
    if not table_similarities:
        return False, None

    best_dim_table, best_dim_sim = max(
        [(t, table_similarities.get(t, 0)) for t in dim_tables],
        key=lambda x: x[1]
    )
    best_fact_table, best_fact_sim = max(
        [(t, table_similarities.get(t, 0)) for t in fact_tables],
        key=lambda x: x[1]
    )

    # 相似度差距阈值（默认 0.05）
    similarity_gap_threshold = 0.05

    if best_dim_sim > best_fact_sim + similarity_gap_threshold:
        if len(dim_tables) == 1:
            return True, best_dim_table

    return False, None

def _select_best_dim_base(
    self,
    dim_tables: List[str],
    table_similarities: Dict[str, float],
) -> List[str]:
    """
    多维度表场景下，通过连通性分析选择最优 base

    参考 docs/13:798-829

    Returns:
        [best_base_table]  # 只返回一个
    """
    from src.services.db.neo4j_client import get_neo4j_client

    if len(dim_tables) == 1:
        return dim_tables

    neo4j_client = get_neo4j_client()
    best_base = None
    max_connections = -1
    best_similarity = 0.0

    for candidate_base in dim_tables:
        candidate_targets = [t for t in dim_tables if t != candidate_base]

        try:
            path_map = _plan_join_paths_for_base(
                neo4j_client=neo4j_client,
                base_table=candidate_base,
                target_tables=candidate_targets,
            )
            connections = sum(1 for t in candidate_targets if path_map.get(t))
            similarity = table_similarities.get(candidate_base, 0.0)

            # 选择连接数最多的；如果连接数相同，选择相似度最高的
            if connections > max_connections or \
               (connections == max_connections and similarity > best_similarity):
                best_base = candidate_base
                max_connections = connections
                best_similarity = similarity
        except Exception as e:
            print(f"[连通性分析] base={candidate_base} 查询失败: {e}")
            continue

    return [best_base] if best_base else dim_tables[:1]
```

#### 2.2.2 更新 schema_retrieval_node

**文件**: `src/modules/sql_generation/subgraph/nodes/schema_retrieval.py`

**修改节点函数**:

```python
def schema_retrieval_node(state: SQLGenerationState) -> Dict[str, Any]:
    """Schema 检索节点"""
    config = load_subgraph_config("sql_generation")
    retriever = SchemaRetriever(config)

    try:
        # ⭐ 传入 parse_result 和 query_embedding
        schema_context, query_embedding = retriever.retrieve(
            query=state["query"],
            parse_result=state.get("parse_result"),  # ⭐ 使用 parse_result
            query_embedding=state.get("query_embedding"),  # ⭐ 复用向量
        )

        # 记录检索统计
        stats = retriever.get_retrieval_stats(schema_context)
        print(
            f"[{state['query_id']}] Schema检索完成: "
            f"{stats['table_count']}表, "
            f"{stats['column_count']}列, "
            f"{stats['join_plan_count']}个JOIN计划, "
            f"耗时{stats['retrieval_time']:.2f}秒"
        )

        # ⭐ 返回 schema_context 和 query_embedding
        return {
            "schema_context": schema_context,
            "query_embedding": query_embedding  # ⭐ 写回 state
        }

    except Exception as e:
        print(f"[{state['query_id']}] ❌ Schema检索失败: {e}")
        return {
            "schema_context": None,
            "error": f"Schema检索失败: {str(e)}",
            "error_type": "schema_retrieval_failed",
        }
```

#### 2.2.3 同步其他调用方（重要）

**需要检查和修改所有调用 `SchemaRetriever.retrieve` 的地方**：

1. **测试文件中的 mock**：
   - `src/tests/integration/sql_generation_subgraph/test_subgraph.py`
   - Mock 需要返回 `(schema_context, query_embedding)` 元组

2. **辅助函数**：
   - 搜索代码中是否有其他封装函数调用 `retrieve`
   - 例如：`src/tools/schema_retrieval/retriever.py` 中可能存在的辅助方法

3. **统计/兼容性辅助方法**：
   - `SchemaRetriever.get_retrieval_stats` 依赖 `tables` / `similar_sqls` / `dim_value_matches` 等旧字段，调整后需同时支持新旧命名（如 `dim_value_hits`）。
   - 更新所有测试夹具（`src/tests/conftest.py` 等）中构造的 `schema_context`，保持旧字段存在的同时补充新字段，避免 KeyError。

4. **便捷函数**：
   - `retrieve_schema`（`src/tools/schema_retrieval/retriever.py`）也要改为返回 `(schema_context, query_embedding)`，并在调用侧同步解包。

**示例修改（测试 mock）**:

```python
# 修改前（返回单个 dict）
mock_retriever.retrieve.return_value = {
    "tables": ["public.fact_sales"],
    ...
}

# 修改后（返回元组）
mock_retriever.retrieve.return_value = (
    {
        "tables": ["public.fact_sales"],
        ...
    },
    [0.1, 0.2, ...]  # query_embedding
)
```

---

### 任务 2.3：历史SQL检索移至生成阶段（P0 - 核心）

**设计说明**：
- 历史SQL作为**临时变量**，仅用于生成提示词
- **不写回state**，保持`schema_context`只读（语义清晰：schema_context仅表示Schema检索结果）
- 每次调用Generator都重新检索（虽然结果相同，但逻辑清晰，且检索性能开销小）
- 将`similar_sqls`作为**独立参数**传递给`agent.generate`，而非嵌入`schema_context`

#### 2.3.1 在 SQL Generation 节点调用历史SQL检索

**文件**: `src/modules/sql_generation/subgraph/nodes/sql_generation.py`

**修改 `sql_generation_node` 函数**:

```python
def sql_generation_node(state: SQLGenerationState) -> Dict[str, Any]:
    """SQL 生成节点"""
    config = load_subgraph_config("sql_generation")
    gen_config = config.get("sql_generation", {})

    # 初始化 Agent
    agent = SQLGenerationAgent(gen_config)

    # ⭐ 空值保护：确保 schema_context 存在
    schema_context = state.get("schema_context")
    if not schema_context:
        return {
            "generated_sql": None,
            "error": "Schema检索结果为空，无法生成SQL",
            "error_type": "generation_failed",
        }

    # ⭐ 检索历史 SQL（作为临时变量，不修改 schema_context）
    from src.services.db.pg_client import get_pg_client

    pg_client = get_pg_client()

    # ⭐ 从配置读取参数（而非写死）
    prompt_config = gen_config.get("prompt", {})
    similar_sqls = pg_client.search_similar_sqls(
        embedding=state["query_embedding"],  # ⭐ 复用向量
        top_k=prompt_config.get("max_similar_sqls", 2),  # ⭐ 从配置读取
        similarity_threshold=gen_config.get("sql_similarity_threshold", 0.6),
    )
    print(f"[{state['query_id']}] 检索到 {len(similar_sqls)} 个相似SQL案例")

    # 获取上一次的验证错误
    validation_errors = None
    if state.get("validation_result"):
        if not state["validation_result"].get("valid"):
            validation_errors = state["validation_result"].get("errors", [])

    try:
        # 生成 SQL
        generated_sql = agent.generate(
            query=state["query"],
            schema_context=schema_context,  # ⭐ 保持只读，不修改
            similar_sqls=similar_sqls,  # ⭐ 作为独立参数传入
            parse_result=state.get("parse_result"),  # ⭐ 使用 parse_result
            dependencies_results=state.get("dependencies_results"),
            validation_errors=validation_errors,
        )

        print(f"[{state['query_id']}] SQL生成完成（第 {state.get('iteration_count', 0) + 1} 次）")

        return {
            "generated_sql": generated_sql,
            # ❌ 不写回 schema_context（保持只读）
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    except Exception as e:
        print(f"[{state['query_id']}] ❌ SQL生成失败: {e}")
        return {
            "generated_sql": None,
            "error": f"SQL生成失败: {str(e)}",
            "error_type": "generation_failed",
        }
```

---

### 任务 2.4：提示词优化（P1 - 质量提升）

#### 2.4.1 调整提示词顺序和格式

**文件**: `src/modules/sql_generation/subgraph/nodes/sql_generation.py`

**修改 `_build_prompt` 方法的参数**:

```python
def _build_prompt(
    self,
    query: str,
    schema_context: Dict[str, Any],
    similar_sqls: List[Dict[str, Any]],  # ⭐ 作为独立参数
    parse_result: Optional[Dict[str, Any]],  # ⭐ 改名
    dependencies_results: Optional[Dict[str, Any]],
    validation_errors: Optional[List[str]],
) -> str:
    """构建 SQL 生成提示词"""

    # 格式化解析结果（与 docs/15 一致的平铺格式）
    time_info = self._format_time_hints(parse_result)
    dimension_filters = self._format_dimension_filters(parse_result, schema_context)
    metric_info = self._format_metric_hints(parse_result)
    dependencies_text = self._format_dependencies(dependencies_results)

    # 格式化 Schema 上下文
    table_cards_text = self._format_table_cards(schema_context.get("table_cards", {}))
    join_plans_text = format_join_plan_for_prompt(schema_context.get("join_plans", []))
    time_columns_text = self._format_time_columns(schema_context.get("table_cards", {}))
    dim_value_sources = schema_context.get("dim_value_hits") or \
        schema_context.get("dim_value_matches", [])  # ⭐ 兼容旧字段
    dim_values_text = format_dim_value_matches_for_prompt(dim_value_sources)

    # 格式化历史SQL（从参数获取，而非从 schema_context）
    similar_sqls_text = self._format_similar_sqls(similar_sqls)

    # 格式化验证错误
    errors_text = self._format_errors(validation_errors)

    # ⭐ 组装提示词（与 docs/15 一致的格式）
    prompt = f"""你是 PostgreSQL SQL 生成专家。根据以下上下文生成 SQL。

要求：
1. 仅输出 SQL，不附加说明。
2. 所有表必须包含 schema 前缀（例如 public.table）。
3. 时间过滤使用指定列，并遵循 >= start AND < end 的半开区间。
4. JOIN 条件必须严格按照 ON 模板，用实际别名替换 SRC/DST。
5. 如果提供了维度值匹配，优先使用主键过滤而非文本匹配。

---

方言：postgresql
问题：{query}
{time_info}
{dimension_filters}
{metric_info}

{dependencies_text}

---

表结构：
{table_cards_text}

---

JOIN 计划：
{join_plans_text}

---

时间列：
{time_columns_text}

---

维度值匹配：
{dim_values_text}

---

历史SQL参考（仅供参考）：
{similar_sqls_text}

---

{errors_text}
"""

    return prompt.strip()
```

#### 2.4.2 修改格式化方法的参数（解决问题5）

**需要将所有使用 `parse_hints` 的地方改为 `parse_result`**，并补充详细实现：

```python
def _format_time_hints(self, parse_result: Optional[Dict[str, Any]]) -> str:
    """格式化时间提示"""
    if not parse_result or "time" not in parse_result:
        return ""

    time_info = parse_result["time"]
    if not time_info:
        return ""

    start = time_info.get("start", "")
    end = time_info.get("end", "")

    if start and end:
        return f"时间窗口：{start} ~ {end}"
    return ""

def _format_dimension_filters(
    self,
    parse_result: Optional[Dict[str, Any]],
    schema_context: Dict[str, Any],
) -> str:
    """
    格式化维度过滤条件

    包含维度值优化逻辑（参考 docs/13:1073-1113）
    """
    if not parse_result or "dimensions" not in parse_result:
        return ""

    filters = []
    dim_value_hits = schema_context.get("dim_value_hits") or \
        schema_context.get("dim_value_matches", [])  # ⭐ 双字段兼容

    for idx, dimension in enumerate(parse_result["dimensions"]):
        role = dimension.get("role")
        text = dimension.get("text", "")

        if role == "value":
            effective_text = text

            # ⭐ 维度值优化：使用 dim_value_index 中匹配度最高的值替换用户输入
            # 选择当前维度的命中集合（通过 source_index 绑定）
            per_dim_hits = [
                h for h in dim_value_hits
                if h.get("source_index") == idx
            ]

            if per_dim_hits:
                # 选择分数最高的命中
                best_hit = max(per_dim_hits, key=lambda h: float(h.get("score") or 0.0))
                best_score = float(best_hit.get("score") or 0.0)

                # 分数阈值（默认 0.5）
                min_score = 0.5

                if best_score >= min_score and best_hit.get("value_text"):
                    # 替换为标准值
                    effective_text = str(best_hit.get("value_text"))
                    # 例如："京东便利店" -> "京东便利"

            filters.append(f"value={effective_text}")

        elif role == "column":
            filters.append(f"column={text}")

    if filters:
        return f"维度过滤：{', '.join(filters)}"
    return ""

def _format_metric_hints(self, parse_result: Optional[Dict[str, Any]]) -> str:
    """格式化指标提示"""
    if not parse_result or "metric" not in parse_result:
        return ""

    metric = parse_result["metric"]
    if not metric:
        return ""

    metric_text = metric.get("text", "")
    if metric_text:
        return f"指标：{metric_text}"
    return ""

def _format_time_columns(self, table_cards: Dict[str, Any]) -> str:
    """
    从表卡片中提取时间列

    参考 docs/13:1144-1152
    """
    if not table_cards:
        return ""

    time_lines = []
    for table_id, card in table_cards.items():
        time_col_hint = card.get("time_col_hint")
        if time_col_hint:
            time_lines.append(f"- {table_id}.{time_col_hint}")

    if time_lines:
        return "\n".join(time_lines)
    return ""
```

**同时修改 `SQLGenerationAgent.generate` 方法签名**:

```python
def generate(
    self,
    query: str,
    schema_context: Dict[str, Any],
    similar_sqls: List[Dict[str, Any]],  # ⭐ 新增参数
    parse_result: Optional[Dict[str, Any]] = None,  # ⭐ 改名
    dependencies_results: Optional[Dict[str, Any]] = None,
    validation_errors: Optional[List[str]] = None,
) -> str:
    """生成 SQL"""
    prompt = self._build_prompt(
        query=query,
        schema_context=schema_context,
        similar_sqls=similar_sqls,  # ⭐ 传入 similar_sqls
        parse_result=parse_result,  # ⭐ 传入 parse_result
        dependencies_results=dependencies_results,
        validation_errors=validation_errors,
    )
    # ... 其余逻辑不变
```

---

## 3. 实施顺序

### Phase 1: 核心功能（2-3天）

**Day 1: Parser 节点**
- [ ] 创建 `question_parsing.py`
- [ ] 扩展 State 定义
- [ ] 调整子图拓扑
- [ ] 更新配置文件
- [ ] 实现配置项使用逻辑（`enable_internal_parser`、`fallback_to_empty`）

**Day 2: Schema检索瘦身 + 向量共享**
- [ ] 修改 `SchemaRetriever.retrieve` 方法（返回元组）
- [ ] 更新 `schema_retrieval_node`
- [ ] **同步所有调用方**（测试 mock、辅助函数等）
- [ ] 删除历史SQL检索调用

**Day 3: 历史SQL检索移动 + 提示词优化**
- [ ] 在 `sql_generation_node` 中添加历史SQL检索
- [ ] 添加空值保护（`schema_context`）
- [ ] 从配置读取 `max_similar_sqls`（而非写死）
- [ ] 调整提示词顺序（errors_text 放最后）
- [ ] 添加解析摘要格式化
- [ ] 测试端到端流程

---

## 4. 验收标准

### 4.1 功能验收

- [ ] 子图流程：`START → question_parsing → schema_retrieval → sql_generation → validation`
- [ ] State 包含 `parse_result`、`query_embedding` 字段
- [ ] 外部传入 `parse_hints` 仍然可用（向后兼容）
- [ ] 历史SQL在生成阶段检索，只返回 `question/sql/similarity`
- [ ] 提示词包含解析摘要，历史SQL放在最后

### 4.2 质量验收

- [ ] 不传 `parse_hints` 时，Parser节点能正常工作
- [ ] 传入 `parse_hints` 时，跳过LLM解析
- [ ] 向量只生成一次，被复用
- [ ] 示例运行成功

---

## 5. 风险与注意事项

### 5.1 风险

1. **LLM解析不稳定**
   - 缓解：保留 `parse_hints` 兼容性
   - 缓解：解析失败时返回错误，不影响主流程

2. **向后兼容性**
   - 确保外部系统继续传入 `parse_hints` 时仍然可用

### 5.2 注意事项

1. **参数名改动**：以 `parse_result` 作为内部统一字段；保留对 `parse_hints` 的读取以兼容外部输入，逐步更新函数签名/调用参数（避免简单全局替换）。
2. **返回值改动**：`SchemaRetriever.retrieve` 返回元组，所有调用方需同步修改
3. **空值保护**：`schema_context.copy()` 前需检查是否为 None
4. **配置读取**：新增配置项需在代码中实际使用，避免"挂空"
5. **历史SQL简化**：只返回基本字段 `question/sql/similarity`，作为一般性参考
6. **数据库不动**：保持现有 `system.sql_embedding` 表结构不变

---

## 6. 关键代码位置

| 模块 | 文件 | 说明 |
|-----|------|------|
| Parser节点 | `src/modules/sql_generation/subgraph/nodes/question_parsing.py` | 新建 |
| State定义 | `src/modules/sql_generation/subgraph/state.py:22` | 添加3个字段 |
| 子图拓扑 | `src/modules/sql_generation/subgraph/create_subgraph.py:53-95` | 添加Parser节点 |
| Schema检索 | `src/tools/schema_retrieval/retriever.py:45-126` | 删除历史SQL检索 |
| SQL生成节点 | `src/modules/sql_generation/subgraph/nodes/sql_generation.py:257-307` | 添加历史SQL检索 |
| 提示词构建 | `src/modules/sql_generation/subgraph/nodes/sql_generation.py:81-156` | 重排顺序 |
| 配置文件 | `src/modules/sql_generation/config/sql_generation_subgraph.yaml` | 添加Parser配置 |

---

**文档版本**: v2.5（修正版）
**最后更新**: 2025-11-02

**修正说明**（v2.1 → v2.5）：
1. ✅ 明确历史SQL检索只是一般性参考，不需要候选表过滤
2. ✅ 增加配置项使用逻辑（`enable_internal_parser`、`fallback_to_empty`）
3. ✅ 添加 `SchemaRetriever.retrieve` 返回值改动后的调用方同步要求
4. ✅ 添加 `schema_context` 空值保护
5. ✅ 修正 `top_k` 从配置读取（而非写死为2）
6. ✅ 调整提示词顺序（`errors_text` 放在 `similar_sqls` 之后）
7. ✅ 删除 `parse_summary` 解析摘要，改为与 docs/15 一致的平铺格式（`时间窗口`、`维度过滤`、`指标`）
8. ✅ `similar_sqls` 不写回 `schema_context`，保持 `schema_context` 只读，将 `similar_sqls` 作为独立参数传递
9. ✅ **补充JOIN规划逻辑**（`_retrieve_join_plans`）：维度表优化判断、Base表选择策略、连通性分析（问题1）
10. ✅ **区分事实表和维度表**：`schema_context`包含`candidate_fact_tables`和`candidate_dim_tables`（问题2）
11. ✅ **添加表相似度信息**：`schema_context`包含`table_similarities`字段（问题3）
12. ✅ **维度值检索包含source_index**：`dim_value_hits`中每个命中包含`source_index`绑定到`parse_result.dimensions`的索引（问题4）
13. ✅ **补充提示词格式化逻辑**：维度值优化（`_format_dimension_filters`）、时间列提取（`_format_time_columns`）的详细实现（问题5）
