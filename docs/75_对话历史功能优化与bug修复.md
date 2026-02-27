# 75 对话历史功能：优化与 Bug 修复记录（仅使用原生 PostgresStore）

> 本文用于持续记录 75 需求实现过程中发现的问题、已确认的决策、以及需要修改的代码清单。
> 后续讨论的新问题将继续追加到本文中。

## 1. 背景与目标

目标：在项目中回答 NL 问题或生成 SQL 时，注入用户最近 N 轮历史对话（仅 QUESTION/ANSWER），提升多轮对话（尤其省略式提问，如“那上海呢/它呢”）的理解与 SQL 生成质量；N 可配置；数据来自 `langgraph.store`（PostgresStore）。

现状：已实现写入——`src/services/langgraph_persistence/chat_history_writer.py` 的 `append_turn()` 会把一轮对话写入 PostgresStore（落库到 `langgraph.store`）。

## 2. 统一约束与已确认决策

- 仅使用 **原生 PostgresStore API**（`put/search/get/...`），不走“自定义 SQL + 自建索引”查询路径
- 不考虑旧数据/历史数据迁移与兼容（切换后只使用新写入的数据）
- history 的提示词展示顺序：**旧 → 新**
- history 返回数量策略（已确认）：
  - 配置名使用 `history_max_turns`（1 turn = 1 组 Q/A）
  - 读取时固定超量拉取：`limit = history_max_turns * 2`（k 固定为 2）
  - 仅做一次 `search`，不做翻页补齐：若过滤后不足则直接返回不足；若全被过滤则返回空
- history 截断规则（已确认）：
  - `max_history_content_length` **只约束 history 文本**（每条 question/answer 的最大字符数），不约束整个提示词
  - 仅当文本长度超过阈值时才截断，并在截断后的末尾追加 `...`；未截断则不追加省略号
- 历史 turn 过滤规则（已确认）：
  - `value.success` **必须存在且为 true** 才允许进入 history 注入
  - `success` 缺失或 `success == false`：一律跳过
  - `question` 为空：一律跳过
  - `answer` 为空：一律跳过
- history 读取容错（已确认）：
  - 读取超时：10 秒；超时后放弃本次读取
  - fail-open：任何异常/失败/超时均返回空列表 `[]`，不影响主流程
  - 不做“健康降级/熔断”（当前不需要）
- namespace 字符约束（已确认）：
  - Store 的 namespace 会用 `.` 拼接为 `prefix`（例如 `chat_history.<thread_id>`）
  - 约束：`thread_id` 不应包含 `.`（由 `user_id` 字符集约束保证：`user_id` 不包含 `.`，且 `thread_id={user_id}:{timestamp}`）
- 采用方案 **X**：在 SQL 子图 `question_parsing` 的单次 LLM 调用中同时产出：
  - `rewritten_query`（补全指代后的独立问题）
  - `parse_result`（现有结构化输出）
- 在 **5 个位置**注入/使用 history：
  1) SQL 子图 `question_parsing`
  2) SQL 子图 `schema_retrieval`（通过使用 `rewritten_query` 间接生效）
  3) SQL 子图 `sql_generation`
  4) 父图 `planner`
  5) 父图 `summarizer`

## 3. 问题 1：Store 查询能力与落库 keyspace 不匹配

### 3.1 问题描述（Bug/偏差）

概要设计中曾出现类似 `store.search(namespace=(namespace,), prefix=thread_id)` 的调用，但 **原生 `PostgresStore.search()` 不存在 `prefix=` 参数**。

真实签名为：

`search(namespace_prefix: tuple[str, ...], *, filter: dict | None, limit: int, offset: int, ...)`

因此，“按 key 前缀（`{thread_id}#...`）过滤”的方案无法直接通过 `PostgresStore.search()` 实现。

### 3.2 根因

当前写入方式（现状）：
- `langgraph.store.prefix` 恒定为 `chat_history`（来自 `src/configs/config.yaml` 的 `langgraph_persistence.store.namespace`）
- `langgraph.store.key` 为 `{thread_id}#{query_id}`

此时若想“按 thread_id 取最近 N 轮”，要么走 JSONB filter（`value.thread_id`），要么走 key 前缀匹配；但二者都不是 `PostgresStore.search()` 的最佳路径。

> 注意：此前“namespace 为空”的讨论是 checkpoint 的 `checkpoint_ns` 行为，不适用于 Store。Store 的 `prefix` 由 `store.put(namespace=...)` 决定。

补充：历史轮次排序不应依赖 key 中的时间戳。即使 key 中包含 thread_id 时间戳，在同一 thread 内该时间戳并不能区分轮次；应以 `store.updated_at/created_at` 或 value 内的 `created_at` 作为时间顺序依据。

### 3.3 解决方案（已确认）：thread_id 下钻到 prefix

将每个 thread 的历史写入独立 prefix（保留顶层域名 `chat_history`）：

- 写入：`store.put(namespace=("chat_history", thread_id), ...)`
- 读取：`store.search(("chat_history", thread_id), limit=N)`

落库效果（LangGraph 会用 `.` 拼接 namespace tuple）：
- `langgraph.store.prefix = "chat_history.<thread_id>"`
- `search()` 的 SQL 会走 `prefix LIKE 'chat_history.<thread_id>%'`，能有效利用 `store_prefix_idx(prefix text_pattern_ops)`，并把扫描范围收敛到单个 thread。

### 3.4 key 的选择（建议同步优化）

在 thread_id 已进入 `prefix` 后，`key` 不再需要携带 thread_id，推荐改为：
- `key = query_id`

## 4. 问题 2：省略式多轮（“那上海呢/它呢”）仅在 SQL 生成注入 history 不够

### 4.1 现象与影响链路

如果只在 SQL 生成节点注入 history：
- `question_parsing` 解析阶段只看当前 query，省略式问题难以补全指代，`parse_result` 可能缺关键维度/指标
- `schema_retrieval` 检索阶段会直接对短 query 做 embedding（`src/tools/schema_retrieval/retriever.py` 内部 `embed_query(query)`），很容易选错表/列
- 到 SQL 生成阶段再补 history 往往“救不回来”（检索与候选集已偏）

### 4.2 解决方案（已确认）：方案 X + 5 处注入

核心思路：尽量把“补全”前移，并让补全后的 `rewritten_query` 驱动检索与生成。

#### 4.2.1 冲突处理规则（已确认，直接落到提示词）

为避免旧历史误导当前生成，所有注入 history 的提示词需加入以下规则：
- 若历史对话与“当前问题”存在冲突，以**当前问题**为准。
- 若历史对话与“依赖子查询结果 / 当前执行结果”存在冲突，以**依赖子查询结果 / 当前执行结果**为准。
- history 仅作为理解上下文的参考，不得覆盖当前问题与本轮结果。

#### 4.2.2 子图单独运行兼容性（已确认）

要求：SQL 生成子图可单独运行用于调试；即使没有 history，也不能报错，只是提示词缺少 history。

约定：
- `conversation_history` 在子图 State 中为可选字段，所有使用处通过 `state.get("conversation_history")` 读取，为空即视为“无历史”，跳过注入
- `rewritten_query` 也为可选字段；为空则回退到 `state["query"]`
- 子图入口 `run_sql_generation_subgraph(...)` 中 `conversation_history` 参数为可选，缺省为 `None`

建议（实现层面）：
- 父图统一读取一次 history（旧→新），写入 `NL2SQLFatherState.conversation_history`，并透传给子图，避免重复读 Store
- 子图 `question_parsing` 在单次 LLM 调用中输出 `rewritten_query` + `parse_result`
- 子图 `schema_retrieval` 与 `sql_generation` 统一优先使用 `rewritten_query`

### 4.3 5 个注入点（明确落点）

1) SQL 子图 `question_parsing`
   - 注入：`conversation_history`
   - 产出：`rewritten_query`（若当前问题已完整，则等于原 query） + `parse_result`

2) SQL 子图 `schema_retrieval`
   - 不直接拼接 history 到检索器内部
   - 但使用 `rewritten_query` 作为 `SchemaRetriever.retrieve(query=...)` 的 query（embedding 的输入变成补全后的问题）

3) SQL 子图 `sql_generation`
   - 注入：`conversation_history`
   - 使用：`rewritten_query` 作为“问题”字段（可保留原 query 作为辅助信息）

4) 父图 `planner`
   - 注入：`conversation_history`（用于复杂问题拆分时的指代消解与口径延续）

5) 父图 `summarizer`
   - 注入：`conversation_history`（仅用于指代消解/上下文补全）
   - 强约束：最终总结必须以本次执行结果为准，history 不得覆盖结果

## 5. 代码修改清单（按模块分组）

### 5.1 Store 写入（prefix/keyspace）

- `src/services/langgraph_persistence/chat_history_writer.py`
  - `append_turn()`：
    - 现状：`store.put(namespace=(namespace,), key=f"{thread_id}#{query_id}", ...)`
    - 修改：`store.put(namespace=(namespace, thread_id), key=query_id, ...)`
  - `value` 顶层新增字段：
    - `success: bool`
    - 写入来源：由父图在写入时计算并传入（建议定义为：`success = any(r.success for r in execution_results)`）

### 5.2 Store 读取（原生 search）

- 新增 `src/services/langgraph_persistence/chat_history_reader.py`
  - `get_recent_turns(thread_id, history_max_turns, exclude_query_id, ...) -> List[{question, answer}]`
  - 读取：`store.search((namespace, thread_id), limit=history_max_turns * 2)`
  - 输出顺序：旧→新
    - 实现（防御性）：无论 `search()` 返回顺序如何，先在代码层按 `item.updated_at` 排序，再输出旧→新
  - 过滤规则（与第 2 节保持一致）：
    - `success` 缺失或 `success == false`：跳过
    - `question` 为空：跳过
    - `answer` 为空：跳过
  - 截断规则（与第 2 节保持一致）：
    - 对 `question` 与 `answer` 分别按 `max_history_content_length` 截断
    - 仅当发生截断时才追加 `...`
  - 超时与 fail-open：
    - 读取超时 10 秒；超时/异常返回空列表 `[]`，不阻塞主流程

### 5.3 父图：统一读取一次 history，并注入到 planner/summarizer（第 4/5 处）

- `src/modules/nl2sql_father/state.py`
  - 新增字段：`conversation_history: Optional[List[Dict[str, str]]]`

- `src/modules/nl2sql_father/graph.py`
  - 在执行父图前读取 history（使用 `thread_id`，排除当前 `query_id`）
  - 写入 `initial_state["conversation_history"]`
  - 写入 Store 时计算并传入 `success`：
    - 建议：`success = any(r.get("success") for r in result.get("execution_results", []))`

- `src/modules/nl2sql_father/nodes/planner.py`
  - prompt 注入 `conversation_history`（第 4 处）

- `src/modules/nl2sql_father/nodes/summarizer.py`
  - prompt 注入 `conversation_history`（第 5 处）

### 5.4 子图：方案 X 与第 1/2/3 处注入

- `src/modules/sql_generation/subgraph/state.py`
  - 新增字段声明：
    - 说明：当前 `SQLGenerationState` 为 `MessagesState` 子类（不是 TypedDict），按现有风格补充字段即可
    - `thread_id: Optional[str]`
    - `conversation_history: Optional[List[Dict[str, str]]]`
    - `rewritten_query: Optional[str]`

- `src/modules/sql_generation/subgraph/create_subgraph.py`
  - `run_sql_generation_subgraph(..., thread_id=..., conversation_history=...)`（用于调试时可不传 `conversation_history`）
  - 将 `thread_id` 与 `conversation_history` 写入 `initial_state`

- `src/modules/sql_generation/subgraph/nodes/question_parsing.py`（第 1 处）
  - 将 `conversation_history` 注入到 parsing prompt
  - 在同一次 LLM 调用输出 `rewritten_query` + `parse_result`

- `src/modules/sql_generation/subgraph/nodes/schema_retrieval.py`（第 2 处）
  - `retriever.retrieve(query=state.get("rewritten_query") or state["query"], ...)`

- `src/modules/sql_generation/subgraph/nodes/sql_generation.py`（第 3 处）
  - prompt 注入 `conversation_history`
  - 使用 `rewritten_query` 作为“问题”

## 6. 配置建议（保持父图/子图一致）

优先原则：避免“同一含义两处配置”导致不一致。

建议将 history 的“读取/截断”配置放在父图侧，由父图读取并透传给子图（子图不再重复读取 Store，也不再重复截断）。

- 在父图配置 `src/modules/nl2sql_father/config/nl2sql_father_graph.yaml` 增加：
  - `conversation_history.enabled`
  - `conversation_history.history_max_turns`
  - `conversation_history.max_history_content_length`
  - `conversation_history.read_timeout_seconds`

如果未来允许“子图独立运行时也读取 Store 并注入 history”（不依赖父图透传），则子图也需要相同含义的配置项：
- `src/modules/sql_generation/config/sql_generation_subgraph.yaml`
  - `sql_generation.history.enabled`
  - `sql_generation.history.history_max_turns`
  - `sql_generation.history.max_history_content_length`

并约定：
- 父图读取 history 使用 `conversation_history.*`
- 子图默认使用父图透传的 `conversation_history`（不重复读取/截断）
- 若子图启用独立读取，则 `sql_generation.history.*` 与 `conversation_history.*` 应保持同值

补充说明：
- `max_history_content_length` 用于控制 history 注入的文本长度（字符数），避免 history 过长撑爆提示词
- 整体提示词长度仍受其它因素影响（如 schema/table_cards/join_plans/依赖结果等），以及 LLM 自身的 `max_tokens` 配置；`max_history_content_length` 不负责对整个 prompt 做总预算控制

## 7. 问题 3：generator_prompt.txt 与实际提示词生成逻辑不一致

现状：
- SQL 生成提示词当前由代码拼接生成（`src/modules/sql_generation/subgraph/nodes/sql_generation.py` 内 `_build_prompt()`）
- `generator_prompt.txt` / `template_path` 目前未被 SQL 生成节点读取（配置中存在路径，但实现未使用模板渲染）

结论（本次实现对齐方式）：
- 以代码拼接的 prompt 为准，在对应节点中插入 history/rewritten_query
- 后续若要切换到模板驱动，需要单独立项（将 prompt 结构从代码抽到模板，并保证字段一致）

## 8. 安全注意事项：thread_id 的访问隔离（登录态接入前置）

现状：
- 父图允许外部传入 `thread_id`（见 `src/modules/nl2sql_father/graph.py` 的 `run_nl2sql_query(..., thread_id=...)`）
- `create_initial_state()` 在同时传入 `thread_id` 与 `user_id` 且不一致时，**以 thread_id 为准**（见 `src/modules/nl2sql_father/state.py` 的一致性规则）

风险：
- 当前实现默认用户为 `guest`，风险不显著
- 一旦未来接入真实登录态/多用户场景，如果仍允许客户端任意传入 `thread_id`，且未校验其归属，将存在越权读取他人对话历史的风险（history 读取按 thread_id 作为命名空间前缀）

建议（占位，待接入鉴权时落地）：
- 服务端生成并签名/绑定 `thread_id` 与 `user_id`（或会话主体），客户端不可伪造
- 或在 API 层校验：传入的 `thread_id` 必须属于当前登录用户（`thread_id` 前缀的 user_id 仅可作为弱校验，不能替代服务端绑定关系）
- 若无法校验，则不接受外部 `thread_id`，仅允许服务端生成新 thread

## 9. 验收点（最小可用）

- 同一 `thread_id` 连续提问多次后，SQL 生成提示词能稳定带上最近 `history_max_turns` 轮 Q/A（仅 Q/A，顺序旧→新）
- 省略式问题（“那上海呢/它呢”）在解析阶段得到 `rewritten_query`，且检索阶段使用 `rewritten_query`（表/列选择更稳定）
- Store 不可用/读超时/异常时不影响主流程（history 注入为空）

## 10. 后续待讨论问题（占位）

- history 的 token 总预算控制（是否需要对“history 区块总长度”设置上限，防止极端情况）
