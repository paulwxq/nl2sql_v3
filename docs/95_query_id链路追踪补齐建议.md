# 95 Query ID 链路追踪补齐建议

## 1. 背景

当前项目的核心链路日志已经基本具备 `query_id` 追踪能力：

- 父图日志通常带有 `[query_id]`
- SQL 生成子图日志通常带有 `[query_id]`
- 检索、执行、总结等主链路日志通常带有 `[query_id]`

但在少数基础设施日志中，这个约定还没有完全统一。

典型例子是对话历史写入链路。当前实际情况更准确的描述是：

- 写入成功日志里能看到 `key=q_xxx`
- 写入超时日志里也能看到 `key=q_xxx`
- 其中 `key` 本质上就是 `query_id`
- 但这两类日志没有统一采用 `[query_id]` 前缀
- 更重要的是，写入失败日志当前既没有 `[query_id]` 前缀，也没有 `key=query_id`

因此，这里的问题不是“完全拿不到 `query_id`”，而是：

1. 三条日志的链路追踪表达方式不统一
2. 失败分支存在实际的信息缺失

这会削弱“按 `query_id` 全链路 grep 日志”的效果。

这个问题不建议理解为“所有日志都必须带 `query_id`”，而应理解为：

**凡是属于某一次用户查询执行路径的日志，都应尽量稳定带上 `query_id`。**

---

## 2. 建议先明确一条硬规则

建议在项目内统一以下规则：

### 2.1 必须带 `query_id` 的日志

只要该日志属于某一次用户查询的执行路径，就必须带 `query_id`。

典型包括：

- 父图执行
- 子图执行
- Router / Planner / Summarizer
- Schema Retrieval
- SQL Validation / SQL Execution
- 当前请求触发的历史读取
- 当前请求触发的历史写入

### 2.2 可以不带 `query_id` 的日志

如果该日志不属于某一次具体查询，而是系统级、进程级、全局级事件，则可以不带 `query_id`。

典型包括：

- 服务启动 / 关闭
- 连接池初始化
- 全局配置加载
- 持久化组件初始化
- 健康状态重置
- 与某次具体查询无关的后台日志

---

## 3. 建议把日志分成三类

为了避免后续每次都争论“这条日志该不该带 `query_id`”，建议从治理上分成三类：

### 3.1 请求链路日志

定义：

- 明确属于某一次用户查询
- 能直接关联到 `query_id`

要求：

- 必须带 `query_id`

### 3.2 会话链路日志

定义：

- 明确属于某个会话
- 不一定对应单次查询

要求：

- 没有 `query_id` 时，至少带 `thread_id`

### 3.3 系统/进程日志

定义：

- 启动、关闭、初始化、全局状态类日志

要求：

- 可以没有业务 ID

这样划分后，判断成本会大幅降低。

---

## 4. 当前最值得优先补齐的地方

### 4.1 `append_turn()` 是最适合优先处理的点

当前最容易补齐、且收益最高的点是：

- `src/services/langgraph_persistence/chat_history_writer.py`
- `append_turn()`

原因很简单：

1. 这个函数本身已经直接拿到了 `query_id`
2. 它记录的是某次请求收尾阶段的关键链路日志
3. 成功 / 超时分支已经通过 `key=query_id` 间接带出了查询标识
4. 失败分支则存在真实的信息缺失
5. 因此这里的问题不是“拿不到”，而是“没有统一使用，且失败分支漏打了关键上下文”

因此，历史写入成功/超时/失败日志，是本轮最值得补齐的地方。

### 4.2 典型要补的日志点

建议优先覆盖：

- 对话历史写入成功
- 对话历史写入超时
- 对话历史写入失败
- 与当前请求直接相关的 Store 降级或跳过日志

这里建议不要只做“补一个失败日志”，而是一起完成两件事：

1. 修复失败日志缺少 `query_id` / `key` 的现存问题
2. 将成功 / 超时 / 失败三类日志统一成同一种链路追踪表达方式

这些日志一旦统一带上 `[query_id]`，`grep q_xxx logs/app/nl2sql.log` 的价值会明显提高。

---

## 5. 推荐实现方式

### 5.1 推荐局部使用 `with_query_id()`

当前项目已经有成熟的工具：

- `get_module_logger()`
- `with_query_id()`

因此，对像 `append_turn()` 这类函数，推荐做法不是引入新的全局机制，而是直接在函数内创建局部 logger adapter。

建议模式：

```python
qlog = with_query_id(logger, query_id)
qlog.debug("...")
qlog.warning("...")
qlog.error("...")
```

对于 `append_turn()`，推荐理解为“两步一起做”：

1. 先用 `with_query_id(logger, query_id)` 统一前缀
2. 再决定是否保留 `key=query_id` 作为 Store 语义字段

推荐结果是：

- 成功日志：保留 `key=...`，同时带 `[query_id]`
- 超时日志：保留 `key=...`，同时带 `[query_id]`
- 失败日志：至少带 `[query_id]`，最好也补上 `key=...`

这样既保留了 Store key 的业务含义，又统一了链路追踪方式。

### 5.2 不建议一开始就引入 thread-local / contextvars

虽然从长期演进看，`contextvars` 也是一个方向，但对当前项目而言，直接这样做的收益不高，反而会增加复杂度：

- 理解成本更高
- 调试成本更高
- 异步 / 线程池边界更容易出问题

当前更稳妥的做法是：

- 在真正拿得到 `query_id` 的函数里，显式使用 `with_query_id()`

这与现有代码风格也更一致。

---

## 6. `chat_history_reader` 不应一刀切

读取器和写入器不同，不能简单要求“全部补 `query_id`”。

### 6.1 适合带 `query_id` 的读取场景

如果读取行为明确属于某次当前请求，例如：

- 为当前问题注入历史上下文
- 读取历史时显式排除当前 `query_id`

这种场景建议带上 `query_id`。

这里建议把一个现有代码事实说得更明确：

- `get_recent_turns()` 已经提供了 `exclude_query_id` 参数
- 在当前主链路语义下，`exclude_query_id` 通常就等于“本次请求的 `query_id`”
- 它的作用是防止把当前轮次自己再次读回历史上下文中

这意味着 `get_recent_turns()` 不是“未来也许能拿到 `query_id`”，而是**在当前部分调用场景里，本来就已经天然拿到了当前请求的 `query_id`**。

因此，对于 `get_recent_turns()` 内部日志，建议采用以下判断规则：

- 如果 `exclude_query_id is not None`
  说明这次读取明确属于某次当前请求，建议使用它作为 `query_id` 上下文
- 如果 `exclude_query_id is None`
  说明这次读取更偏会话级或通用读取场景，不必强行补 `query_id`

### 6.2 不适合强行带 `query_id` 的读取场景

如果读取行为本身并不属于某次具体查询，例如：

- 侧边栏加载历史会话列表
- 页面初始化时获取最近 session

这种场景就不必强行带 `query_id`。如果需要补充上下文，更适合带：

- `thread_id`
- `user_id`

也就是说：

**reader 需要按函数语义区分，而不是统一机械加前缀。**

进一步说，对 `chat_history_reader.get_recent_turns()` 而言，最值得优先补齐的是以下几类日志：

- 超时日志
- 失败日志
- 读取成功摘要日志（如返回多少轮历史）

推荐做法是：

- 当 `exclude_query_id` 不为空时，使用 `with_query_id(logger, exclude_query_id)`
- 同时在日志正文中继续保留 `thread_id`

这样既能满足：

- 按 `query_id` 检索单次请求链路

也能保留：

- 按 `thread_id` 检索会话级问题

---

## 7. 不建议过度下沉到最底层基础设施

这次补齐 `query_id` 的目标，应控制在“真正能提升链路追踪”的范围内。

不建议为了日志统一，把 `query_id` 继续层层下传到所有最底层工具函数中，例如：

- 纯工具函数
- 标识符解析函数
- 通用连接工厂
- 与当前请求无关的初始化逻辑

原因：

- 会增加大量无业务价值的参数透传
- 会抬高函数签名复杂度
- 会让代码变成“为了日志而改业务参数”

因此建议坚持一个原则：

**谁天然已经拿到了 `query_id`，谁优先负责把这份上下文记录好。**

---

## 8. API 路由层日志也应纳入规则

除了父图、子图、历史读写链路之外，API 路由层本身也是整条请求链路的一部分，因此不应被忽略。

以 `src/api/routers/query.py` 为例，可以把路由日志拆成两种情况：

### 路由入口日志

请求刚进入路由时，`query_id` 往往尚未生成。

因此，这一类日志可以不强行要求带 `query_id`，更适合记录：

- `user_id`
- `thread_id`
- 截断后的用户问题

也就是说：

- **入口日志没有 `query_id` 是正常的**

### 路由完成日志

当 `run_nl2sql_query()` 返回后，路由层通常已经可以拿到：

- `result["query_id"]`
- `complexity`
- `total_execution_time_ms`

这时如果仍然只是把 `query_id=xxx` 拼在消息体里，而不使用统一的 `with_query_id()` 格式，就会导致 API 层完成日志与核心链路日志的追踪格式不一致。

因此建议：

- **API 路由层的完成日志，在已经拿到 `query_id` 的情况下，应使用 `with_query_id()` 标准化**

### 路由异常日志

异常场景要区分：

- 如果异常发生在 `query_id` 生成之前
  可以暂时只记录 `user_id` / `thread_id`
- 如果异常发生在 `query_id` 已可获得之后
  则应尽量带上 `query_id`

当前阶段不一定要为了这件事立刻修改入口设计，但文档上应先明确这条规则：

- **入口日志允许无 `query_id`**
- **完成日志拿到 `query_id` 后应使用统一追踪格式**

---

## 9. 推荐的优先级顺序

### 第一优先级

补齐当前请求相关的历史写入日志：

- `chat_history_writer.append_turn()`

目标：

- 成功 / 失败 / 超时都统一带 `[query_id]`
- 顺手修复失败日志缺少 `query_id` / `key` 的问题

### 第二优先级

补齐与当前请求直接相关的历史读取日志。

目标：

- 当前请求触发的历史注入过程可按 `query_id` 检索
- 无 `query_id` 的场景至少按 `thread_id` 检索

这里建议把范围写得更精确，避免执行时产生歧义：

- **第二优先级只针对 `chat_history_reader.get_recent_turns()`**
- 它属于“为当前请求注入历史上下文”的读取路径
- 在这条路径里，`exclude_query_id` 不为空时，通常就等于当前请求的 `query_id`

因此，本节的改造重点应是：

- `get_recent_turns()` 的超时日志
- `get_recent_turns()` 的失败日志
- `get_recent_turns()` 的读取成功摘要日志

而下面这类函数**不属于第二优先级的范围**：

- `chat_history_reader.list_recent_sessions()`

原因是它的语义不同：

- `list_recent_sessions()` 主要用于侧边栏或 API 获取最近会话列表
- 它通常没有当前请求级别的 `query_id`
- 它属于会话级 / 页面级读取，不属于单次请求链路日志补齐范围

换句话说：

- 第二优先级针对的是“请求链路中的历史读取”
- 当前代码里，主要就是 `get_recent_turns()`
- `list_recent_sessions()` 不应在这一轮被误纳入 `query_id` 补齐任务

### 第三优先级

如果后续仍觉得链路上下文不足，再考虑把日志上下文能力从：

- `with_query_id(logger, query_id)`

扩展为更通用的：

- `with_log_context(query_id, thread_id, sub_query_id, user_id)`

但这不建议在当前阶段立即推进。

---

## 10. 建议的目标状态

如果本轮只做最务实的改造，建议最终达到以下状态：

### 10.1 应带 `query_id` 的日志

- `nl2sql.father`
- `nl2sql.sql_subgraph`
- `nl2sql.retrieval`
- `nl2sql.execution`
- `nl2sql.summarizer`
- `nl2sql.persistence.history_writer` 中与当前请求直接相关的日志
- `nl2sql.api` 中已拿到 `query_id` 的完成日志（如 `query` 路由完成日志）

### 10.2 可以不带 `query_id` 的日志

- `nl2sql.persistence.postgres`
- `nl2sql.config_loader`
- 启动日志
- 关闭日志
- 连接初始化日志
- 与当前请求无关的后台系统日志

这里也需要补一个更精确的说明，避免把规则理解得过于绝对。

以 `nl2sql.persistence.postgres` 为例：

- 它虽然可能在请求路径中被间接触发
- 例如 `get_postgres_store()`、`get_postgres_saver()` 会被上层请求链路调用
- 但它记录的日志语义本质上仍以基础设施生命周期为主
- 典型内容包括：实例创建、setup、初始化完成、连接关闭、组件状态判断

因此，对这个模块更合理的治理原则是：

- **默认按基础设施日志处理，可以不带 `query_id`**
- 不建议为了让这个模块所有日志都带 `query_id`，而把 `query_id` 层层下传到最底层工厂函数中

如果未来发现某类 `postgres.py` 日志确实频繁出现在单次请求故障排查中，且仅靠上层日志无法定位，再单独评估是否为该类日志增加上下文，而不是现在就把整个模块纳入请求链路日志治理范围。

这意味着项目最终不需要追求“所有日志都带 query_id”，而是要追求：

**所有与某次查询直接相关的日志，都能稳定被 `query_id` 检索到。**

---

## 11. 一句话结论

这个问题最合理的处理方式，不是把 `query_id` 推到所有底层函数里，而是：

- 先定义清楚哪些日志必须带 `query_id`
- 优先在已经天然拿到 `query_id` 的函数里补齐
- 第一优先级先处理 `chat_history_writer.append_turn()`
- 不仅统一加 `[query_id]` 前缀，也同时修复失败分支缺少 `query_id` / `key` 的现存问题
- `reader` 按场景区分，不能一刀切

这样改动最小，但能显著提升全链路排障能力。
