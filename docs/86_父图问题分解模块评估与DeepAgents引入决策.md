# 86_父图问题分解模块评估与 DeepAgents 引入决策

## 1. 文档目的

本文在前序文档（83、84、85）的基础上，从整体视角完成三件事：

1. 系统评估当前父图问题分解模块的能力与边界
2. 客观分析 `langchain-ai/deepagents` SDK 的核心能力与适用场景
3. 给出是否引入 DeepAgents 的最终决策建议，以及推荐的演进路线

本文不包含大段代码实现，重点在于讲清思路、明确需要优化的模块边界和优先级。

---

## 2. 当前父图问题分解模块的完整能力评估

### 2.1 模块构成

当前父图的"问题分解"并不是单一节点完成的，而是由以下节点协同构成：

| 节点 | 文件 | 职责 |
| :--- | :--- | :--- |
| Router | `nodes/router.py` | 用轻量 LLM 判定问题复杂度，路由到 Fast Path 或 Complex Path |
| Simple Planner | `nodes/simple_planner.py` | 简单问题直接包装为单个 sub_query，无依赖 |
| Planner | `nodes/planner.py` | 复杂问题一次性分解为 2-5 个带依赖关系的子查询 |
| Inject Params | `nodes/inject_params.py` | 按拓扑序将已完成子查询的执行结果注入到下游子查询 |
| Check Completion | `nodes/check_completion.py` | 循环控制：判断是否所有子查询已完成或达到最大轮次 |
| Summarizer | `nodes/summarizer.py` | 聚合所有子查询结果，生成自然语言回答 |

两条路径的完整流程：

```
Fast Path:    Router -> Simple Planner -> SQL子图 -> SQL执行 -> Summarizer

Complex Path: Router -> Planner -> Inject Params -> SQL Gen Batch -> SQL执行
                                   ^                                   |
                                   |_____ Check Completion ____________|
                                                  |
                                            Summarizer
```

### 2.2 当前设计的优势

#### 确定性与可追踪性

整个图拓扑是固定的，每个节点的输入输出都有明确的 TypedDict 契约。这意味着：

- 每一步的状态变化都可以通过日志和 Checkpoint 完整回溯
- 问题出在哪个节点、哪一轮、哪个子查询，都可以精确定位
- 测试可以针对单个节点编写，不依赖 Agent 的自由决策

#### 状态管理精细

`NL2SQLFatherState` 和 `SubQueryInfo` 提供了完整的结构化状态，包括：

- 每个子查询的独立状态追踪（status、error、iteration_count）
- 依赖图的显式表示（dependency_graph）
- 执行路径记录（path_taken、current_round）
- 全链路时间度量（router_latency_ms、planner_latency_ms、total_execution_time_ms）

#### 配置驱动

通过 `nl2sql_father_graph.yaml` 可以控制：

- 路径开关（fast_path_enabled、complex_path_enabled）
- 各节点的 LLM 选型和参数
- 重试策略和超时限制
- 最大子查询数、最大轮次等约束

这种配置化设计在生产环境中非常有价值。

### 2.3 当前设计的边界与不足

#### 边界一：Planner 的一次性静态规划

`Planner` 在问题开始阶段就一次性输出全部子查询和依赖关系。这种设计的假设是：

- 问题拆解方案在开始时就可以完全确定
- 中间结果不会影响后续拆解策略

这个假设对结构稳定的问题成立，但对以下场景不适用：

- 第一步查出为空，后续步骤本来就不该继续
- 第一步结果与预期不符，需要改写第二步的查询方向
- 某一步虽然成功，但结果不足以支撑后续问题，需要补查

#### 边界二：Check Completion 只做收敛判定，不做重规划

当前 `Check Completion` 的逻辑是：

- 所有子查询 completed/failed → 退出到 Summarizer
- 还有 pending 且依赖可满足 → 继续下一轮
- 达到 max_rounds 或无法推进 → 强制退出

它不具备"根据中间结果重新调整计划"的能力。当某个子查询失败或结果为空时，系统只会继续执行剩余计划或直接收敛，不会尝试调整策略。

#### 边界三：依赖注入链路不完整

这是 85 号文档已经识别的真实缺陷：

- `dependencies_results` 会进入 `sql_generation` 阶段
- 但不会进入 `question_parsing` 阶段的语义重写与结构化解析
- 导致子图前半段看到的是不完整的问题描述

#### 边界四：Complex Path 默认关闭，配置开关未真正生效

`complex_path_enabled: false` 在路由代码中未被实际检查，Router 判定为 complex 后仍会进入 Planner。这是一个需要先修复的基础 bug。

---

## 3. DeepAgents SDK 能力分析

### 3.1 定位与架构

DeepAgents 是 LangChain 基于 LangGraph 构建的高级 Agent 框架，灵感来自 Claude Code。它的核心定位是：为复杂、非确定性、长时间运行的任务提供开箱即用的自主 Agent 能力。

关键架构特征：

- 底层仍是 LangGraph，`create_deep_agent()` 返回的是 `CompiledStateGraph`
- 通过中间件管道扩展能力：Memory → Skills → TodoList → Filesystem → SubAgent → Summarization
- 内置 9 个工具：文件系统操作（ls、read_file、write_file、edit_file、glob、grep）、shell 执行（execute）、任务规划（write_todos）、子任务委派（task）

### 3.2 write_todos 机制

`write_todos` 是 DeepAgents 的核心规划工具，通过 `TodoListMiddleware` 实现：

- Agent 调用 `write_todos` 创建结构化 Todo 列表，存储在 `AgentState['todos']`
- 每完成一步立即标记完成，不批量更新
- Agent 可以随时修改 Todo 列表——新增、删除、调整顺序
- 只在复杂多步问题中使用，简单问题跳过以节省 Token

这个机制的核心价值是**动态重规划**：Agent 可以根据中间结果持续修正计划，而不是一开始就固定全部步骤。

### 3.3 task 子 Agent 机制

`task` 工具可以派生子 Agent 处理子任务，每个子 Agent 有：

- 独立的上下文窗口（防止上下文膨胀）
- 独立的工具集（可以与父 Agent 不同）
- 独立的系统提示词

结果会冒泡回父 Agent。这实现了分层式任务委派。

### 3.4 上下文管理

`SummarizationMiddleware` 在对话超过约 80,000 字符时自动触发：

- 将历史消息压缩为摘要
- 大工具结果自动淘汰到外部存储
- 使得 Agent 可以在不触达上下文窗口限制的情况下持续运行多轮

### 3.5 DeepAgents 的适用边界

DeepAgents 更适合的场景：

- 开放式研究类任务（搜索、阅读、综合）
- 代码操作类任务（编辑、测试、调试）
- 需要 Agent 自主探索和决策的场景

DeepAgents 相对不适合的场景：

- 需要严格可控、可审计的确定性流水线
- 对延迟和 Token 成本敏感的高频场景
- 需要精细结构化状态追踪的专业领域

---

## 4. 核心决策：是否使用 DeepAgents 重构父图

### 4.1 决策结论

**不建议对父图进行整体重构。建议保持当前 LangGraph 架构，在 Complex Path 中针对性增强动态规划能力。**

### 4.2 不建议整体重构的理由

#### 理由一：架构层级不匹配

DeepAgents 是通用自主 Agent 框架，设计目标是处理开放式、非确定性任务。NL2SQL 是领域特定的确定性流水线，每个步骤有明确的输入输出契约。

用通用 Agent 替代专业流水线，会导致：

- 行为可预测性下降（Agent 可能走偏方向）
- 调试难度增加（中间件管道 + Agent 自主决策 = 黑盒化）
- 可观测性倒退（从结构化状态追踪退化为自然语言过程）

#### 理由二：write_todos 不等于"问题分解"

`write_todos` 是 Agent 给自己写的工作计划，本质是自由文本的 TODO 列表。而当前 `Planner` 做的是语义层面的结构化问题分解：

- 输出带 `sub_query_id`、`query`、`dependencies` 的结构化 JSON
- 构建可检测环的依赖图
- 每个子查询有独立的状态追踪（status、error、iteration_count、execution_result）

用自由文本 TODO 替代结构化 DAG，会丢失：

- 严格的依赖图管理
- 子查询级别的状态追踪
- 确定性的批次调度逻辑

#### 理由三：已有能力不应轻易放弃

当前 SQL 子图已经沉淀了完整的专业能力链：

- 多轮对话指代消解与问题重写
- 结构化意图解析（时间、指标、维度、查询意图）
- 多源 Schema 检索（向量检索 + Neo4j JOIN 规划 + 维度值匹配）
- 三层 SQL 验证（语法、安全、语义）
- 失败重试机制

这些能力是本项目最核心的业务价值沉淀。整体重构意味着要在 DeepAgents 框架内重新组织这些能力，风险大、收益小。

#### 理由四：依赖稳定性风险

DeepAgents 当前版本为 0.4.x，仍在快速迭代，API 可能不稳定。当前系统直接基于 LangGraph，而 LangGraph 已经是较成熟的基础设施。引入一个快速变化的上层框架，会增加维护负担。

#### 理由五：性能与成本影响

Agent Loop 天然比确定性图更消耗 Token 和时间：

- 每一轮规划决策都需要 LLM 推理
- write_todos 本身也消耗 Token
- 多轮反思会显著增加响应延迟

对于高频的简单查询（Fast Path），这种额外成本完全不可接受。即使只在 Complex Path 使用，也需要严格评估成本收益。

---

## 5. 推荐的演进方案：在现有架构上增强动态规划

### 5.1 方案总体思路

不替换现有架构，而是在 Complex Path 的关键节点上增加"动态调整"能力，使系统从"静态 DAG 执行"升级为"带反馈的 DAG 执行"。

核心改动集中在三个地方：

```
改动前: Planner(静态) -> Inject Params -> SQL Gen -> Execution -> Check Completion(收敛)
改动后: Planner(静态) -> Inject Params(增强) -> SQL Gen -> Execution -> Adaptive Check(反馈+重规划)
```

### 5.2 需要增强的模块一：Check Completion → Adaptive Check

这是最关键的改动点。

**当前状态：**

`Check Completion` 只做二元判断——继续或退出。不关心中间结果的质量，不尝试调整计划。

**目标状态：**

将 `Check Completion` 升级为 `Adaptive Check`，增加以下能力：

1. **失败分类诊断**
   - 区分"依赖节点失败导致不可推进"、"空结果导致无意义继续"、"轮次耗尽强制终止"三种情况
   - 将分类结果传递给 Summarizer，使最终回答能解释失败原因

2. **轻量重规划触发**
   - 当某个子查询执行成功但结果为空时，不是简单标记完成，而是触发一次轻量 LLM 调用
   - LLM 评估：空结果是否影响后续子查询的意义？是否需要调整后续子查询的问题描述？
   - 如果需要调整，修改 `sub_queries` 中后续子查询的 `query` 字段

3. **补查能力**
   - 当所有子查询完成但 LLM 判断结果不足以回答原始问题时，允许新增最多 1-2 个补充子查询
   - 补查子查询不应有复杂依赖，应是独立的补充查询

**约束条件：**

- 重规划次数上限（建议 max_replans=2）
- 补查子查询数量上限（建议 max_补查=2）
- 总轮次上限不变（max_rounds 仍然生效）
- 重规划使用轻量 LLM（与 Router 同级别），控制成本

### 5.3 需要增强的模块二：Inject Params 增强依赖上下文

**当前状态：**

`Inject Params` 将已完成子查询的执行结果收集到 `dependencies_results`，但这些结果只进入 `sql_generation` 阶段，不进入 `question_parsing` 阶段。

**目标状态：**

在 `Inject Params` 中增加一个轻量的问题重写步骤：

1. 当子查询有依赖且依赖已完成时，将原始 `query` 与 `dependencies_results` 组合
2. 调用轻量 LLM 生成一个 dependency-aware 的完整自然语言子问题
3. 用重写后的问题替换原始 `query`，再送入 SQL 子图

这样做的好处是：

- 子图的 `question_parsing` 阶段从一开始就能看到完整问题
- 不需要修改子图内部接口
- 子图仍然可以独立工作（无依赖时 query 不变）

**替代方案：**

也可以不在 `Inject Params` 中重写问题，而是增强子图的 `question_parsing` 节点，让它在 `dependencies_results` 存在时自动将依赖信息纳入解析上下文。85 号文档称这为"方案 B"。两种方案各有优劣：

- 方案 A（父图侧重写）：子图接口更干净，但父图逻辑更重
- 方案 B（子图侧增强）：子图更智能，但增加了子图的复杂度

建议优先尝试方案 A，因为它不侵入已经稳定运行的子图。

### 5.4 需要修复的基础问题：配置开关生效

在进行上述增强之前，必须先修复 `complex_path_enabled` 配置开关不生效的问题。

修复方式：在 `route_by_complexity` 函数中，显式检查 `graph_control.complex_path_enabled`：

- 若为 `false` 且 Router 判定为 complex → 降级为 Fast Path 或返回"复杂问题暂未开启"提示
- 若为 `true` → 正常进入 Complex Path

这是一个 P0 级别的基础修复，应在任何增强工作之前完成。

### 5.5 可选增强：子查询并行执行

当前 `sql_gen_batch_wrapper` 对同一批次的子查询是串行调用子图的。对于同一批次内无依赖关系的子查询，可以考虑并行调用子图以降低延迟。

这个优化与动态规划无关，但能提升 Complex Path 的响应速度。建议在核心问题修复之后再考虑。

### 5.6 借鉴 write_todos 的过程可见性：Streaming 进度推送

DeepAgents 的 write_todos 机制中，最值得当前项目借鉴的不是"动态规划"（已在 Adaptive Check 中解决），而是**"执行过程对用户实时可见"**这一理念。

当前系统无论 Fast Path 还是 Complex Path，用户看到的都是"等待 → 最终结果"，中间过程完全黑盒。

#### 建议做法

将 `run_nl2sql_query` 的 `app.invoke` 改为 `app.stream`（LangGraph 原生支持 `stream_mode="updates"`），在每个节点完成后向前端推送进度事件：

- Fast Path 推送：`正在解析问题 → 正在检索表结构 → 正在生成SQL → 正在执行 → 正在生成回答`
- Complex Path 推送：`已拆解为3个子问题 → 子问题1/3执行中 → 子问题1/3完成(返回5行) → 子问题2/3执行中 → ...`

这不需要引入任何新框架，只需要：

1. 在 `graph.py` 中将 `invoke` 替换为 `stream`，收集中间事件
2. 在 API 层（FastAPI）将事件通过 SSE 或 WebSocket 推送给前端
3. 每个节点返回时附带一个 `progress_message` 字段供前端展示

#### 价值

- 用户体验提升明显（从黑盒等待变为可见进度）
- 改动量小，不影响现有节点逻辑
- Fast Path 和 Complex Path 都能受益

### 5.7 借鉴 write_todos 的过程记录：子图重试链路透明化

当前子图的验证重试循环（`sql_generation → validation → 失败 → sql_generation`）对父图是不透明的。父图只知道最终结果和 `iteration_count`，不知道每次重试的具体原因。

#### 当前状态

子图的 `validation_history` 已经存了每次验证结果，但只是列表堆积，不会传回父图。父图层面只能看到"重试了 3 次"，看不到"第 1 次语法错误、第 2 次安全检查不通过、第 3 次通过"。

#### 建议做法

1. 在子图的 `extract_output` 中增加一个 `retry_summary` 字段，从 `validation_history` 中提取每次重试的失败原因
2. 在 `sql_gen_wrapper` 和 `sql_gen_batch_wrapper` 中将 `retry_summary` 写入对应的 `SubQueryInfo`
3. Summarizer 在最终回答失败时，可以引用这些信息向用户解释"尝试了什么、为什么最终失败"

#### 价值

- 提升失败场景下的可解释性
- 帮助开发者定位 SQL 生成的系统性问题（如某类验证错误反复出现）
- 改动集中在数据传递层，不影响子图核心逻辑

---

## 6. 分阶段实施计划

本方案分为四个阶段，每个阶段独立可验证、可回退。前两个阶段在现有架构上工作，第三阶段验证效果，第四阶段根据验证结果决定是否引入 DeepAgents。

### 阶段一：修复基础问题（前置条件）

本阶段的目标是让 Complex Path 具备稳定运行的基础条件。在此之前不应进行任何增强工作。

#### 步骤 1.1：修复 `complex_path_enabled` 配置开关（P0）

| 文件 | 改动内容 |
| :--- | :--- |
| `graph.py` → `route_by_complexity` | 读取 `graph_control.complex_path_enabled`，为 `false` 时降级为 Fast Path 或返回受控提示 |

#### 步骤 1.2：补充 Complex Path 端到端成功链路测试

在修复配置开关后，临时启用 Complex Path，编写至少一条典型的多步依赖查询的 E2E 测试，确认当前 Complex Path 的基本链路是通的。

#### 步骤 1.3：修复依赖注入链路（P1）

| 文件 | 改动内容 |
| :--- | :--- |
| `nodes/inject_params.py` | 对有依赖的子查询，增加轻量 LLM 问题重写步骤：将原始 query 与 dependencies_results 组合为完整自然语言子问题 |
| `config/nl2sql_father_graph.yaml` | inject_params 段新增 `query_rewrite` 配置（llm_profile、enabled 开关） |

重写在父图侧完成（方案 A），不侵入子图。子图接口保持不变。

#### 步骤 1.4：统一 in-place 状态修改为函数式更新（P3）

| 文件 | 改动内容 |
| :--- | :--- |
| `nodes/inject_params.py` | 构造新的 sub_queries 副本后返回 |
| `nodes/check_completion.py` | 同上 |
| `nodes/sql_execution.py` | 同上 |

三个节点统一改造，保持行为一致性。

#### 阶段一完成标志

- `complex_path_enabled: false` 时，complex 问题不会进入 Planner
- E2E 测试通过：一条多步依赖查询从 Planner → 子图 → 执行 → Summarizer 全链路成功
- 依赖子查询的 `question_parsing` 阶段能看到完整问题
- 三个节点的状态更新方式统一为函数式

---

### 阶段二：增强 Complex Path 动态规划能力

本阶段在已修复的 Complex Path 基础上，增加"带反馈的 DAG 执行"能力。

#### 步骤 2.1：Check Completion 升级为 Adaptive Check

| 文件 | 改动内容 |
| :--- | :--- |
| `nodes/check_completion.py` | 增加三项能力（见下） |
| `state.py` | 新增 `replan_count`、`supplement_query_count`、`failure_category` 字段 |
| `config/nl2sql_father_graph.yaml` | 新增 `adaptive_check` 配置段 |

三项新增能力：

**能力一：失败分类诊断**

区分三种失败场景，将分类结果传递给 Summarizer：

- 依赖节点失败导致不可推进
- 空结果导致无意义继续
- 轮次耗尽强制终止

同时增加 failed 依赖的即时传播：当依赖节点 failed 时，立即标记下游 pending 子查询为 failed，不再等下一轮依赖环检测。

**能力二：轻量重规划**

当某个子查询执行成功但结果为空时，触发一次轻量 LLM 调用：

- 评估空结果是否影响后续子查询的意义
- 如果需要调整，修改后续子查询的 query 字段
- 受 `max_replans`（建议默认 2）约束

**能力三：补查**

当所有子查询完成但 LLM 判断结果不足以回答原始问题时：

- 允许新增最多 1-2 个补充子查询
- 补查子查询应是独立的，不依赖已有子查询
- 受 `max_supplement_queries`（建议默认 2）约束

配置结构建议：

```yaml
adaptive_check:
  enabled: true                    # 总开关，false 时回退到原始 Check Completion 行为
  failed_dependency_propagation: true  # 即时传播 failed 依赖
  replan:
    enabled: true
    llm_profile: qwen_turbo        # 轻量模型，控制成本
    max_replans: 2
  supplement:
    enabled: true
    llm_profile: qwen_turbo
    max_supplement_queries: 2
```

#### 步骤 2.2：Summarizer 适配失败分类

| 文件 | 改动内容 |
| :--- | :--- |
| `nodes/summarizer.py` | 读取 `failure_category`，在最终回答中解释失败原因 |

#### 步骤 2.3：Streaming 进度推送

| 文件 | 改动内容 |
| :--- | :--- |
| `graph.py` → `run_nl2sql_query` | 将 `app.invoke` 改为 `app.stream`，收集中间节点事件 |
| API 层（FastAPI） | 新增 SSE 或 WebSocket 端点，将进度事件推送给前端 |

Fast Path 推送示例：`正在解析问题 → 正在检索表结构 → 正在生成SQL → 正在执行 → 正在生成回答`

Complex Path 推送示例：`已拆解为3个子问题 → 子问题1/3执行中 → 子问题1/3完成 → 子问题2/3执行中 → ...`

#### 步骤 2.4：子图重试链路透明化

| 文件 | 改动内容 |
| :--- | :--- |
| 子图 `state.py` → `extract_output` | 新增 `retry_summary` 字段，从 `validation_history` 提取每次重试的失败原因 |
| `graph.py` → `sql_gen_wrapper` / `sql_gen_batch_wrapper` | 将 `retry_summary` 写入 `SubQueryInfo` |
| `state.py` → `SubQueryInfo` | 新增 `retry_summary` 字段 |

#### 阶段二完成标志

- `adaptive_check.enabled: false` 时，行为与原始 Check Completion 完全一致
- 重规划和补查的次数受配置约束，不会无限循环
- 空结果场景下，系统能尝试调整后续查询
- 失败场景下，Summarizer 能给出更精确的失败原因
- 前端能实时展示执行进度
- 父图能看到子图每次重试的具体失败原因

---

### 阶段三：效果验证与决策

本阶段的目标是用真实数据验证阶段二的增强是否足够，以此决定是否需要进入阶段四。

#### 步骤 3.1：准备验证数据集

收集或构造以下类型的复杂问题：

- 结构化多跳查询（A 的结果作为 B 的条件）
- 需要先定位对象再查详情的问题
- 中间结果为空需要调整策略的问题
- 多指标复合问题

#### 步骤 3.2：对比评估

对每个问题，记录以下指标：

| 指标 | 说明 |
| :--- | :--- |
| 成功率 | 最终回答是否正确 |
| 重规划触发率 | 多少比例的问题触发了重规划 |
| 重规划有效率 | 触发重规划后，成功率是否提升 |
| 补查触发率 | 多少比例的问题触发了补查 |
| 平均工具调用次数 | 总共调用了多少次子图 |
| 平均耗时 | 端到端响应时间 |
| 平均 Token 成本 | 重规划和补查带来的额外 Token 消耗 |

#### 步骤 3.3：决策标准

根据验证结果，进入不同的后续路径：

**如果 Adaptive Check 已经足够：**

- 重规划和补查覆盖了绝大多数需要动态调整的场景
- 硬编码策略的灵活性足以应对实际问题分布
- → 不引入 DeepAgents，继续在现有架构上迭代

**如果 Adaptive Check 不够：**

表现为以下信号之一：

- 需要的重规划策略越来越多且难以穷举
- Adaptive Check 节点变得过重、难以维护
- 有大量需要"探索式查询"的场景（不能提前确定子查询数量和依赖关系）
- → 进入阶段四，引入 DeepAgents

---

### 阶段四（条件触发）：局部引入 DeepAgents

仅在阶段三验证结果表明需要更强动态性时进入本阶段。

#### 4.1 引入方式

采用 84 号文档的核心设计：

- 新增 `Deep Complex Orchestrator` 节点，替换 Complex Path 中的 Planner + Inject Params + Adaptive Check
- Fast Path 保持不动
- SQL 子图保持不动，封装为单个高层工具 `solve_subproblem_tool`
- Summarizer 保持不动

`solve_subproblem_tool` 的职责边界：

- 输入：一个子问题描述 + 可选的依赖结果摘要
- 内部：调用现有 SQL 子图（问题解析 → Schema 检索 → SQL 生成 → 验证）+ SQL 执行
- 输出：结构化结果（validated_sql、execution_result、成功/失败状态、失败原因）

不拆成多个底层工具（如 generate_sql_tool + execute_query_tool），原因是：

- 子图内部已有完整的生成-验证-重试闭环，拆开会破坏这个闭环
- 单个高层工具让 Agent 只需决定"查什么"，不需决定"怎么查"

#### 4.2 依赖结果传递

不依赖纯自然语言上下文传递依赖结果，保留结构化中间产物：

- 每次 `solve_subproblem_tool` 调用返回结构化结果对象
- Agent 在调用下一步时，将相关结果摘要作为参数传入
- `solve_subproblem_tool` 内部负责将依赖结果注入子图

#### 4.3 运行时保护

| 约束 | 建议默认值 | 说明 |
| :--- | :--- | :--- |
| 最大工具调用次数 | 10 | 防止 Agent 无限循环 |
| 最大重规划次数 | 3 | 限制 Todo 修改次数 |
| 单问题总时长 | 120s | 与现有 `total_timeout` 一致 |
| 工具白名单 | write_todos + solve_subproblem_tool | 不开放文件系统、shell 等无关工具 |

#### 4.4 特性开关

通过配置控制 Complex Path 使用哪种模式：

```yaml
graph_control:
  complex_path_enabled: true
  complex_path_mode: static          # static | deepagents
```

- `static`：使用阶段二的 Adaptive Check 方案
- `deepagents`：使用 Deep Complex Orchestrator

两种模式并存，允许随时回退。

#### 4.5 可观测性保障

DeepAgent 执行完成后，将产物映射回父图状态：

- `execution_results`：所有子问题的执行结果列表
- `sub_queries`：从 Agent 的 Todo 和工具调用记录中还原
- `metadata`：附加 Agent 步骤数、工具调用数、重规划次数等指标

确保 Summarizer、API 输出、日志链路与 static 模式保持一致。

#### 阶段四完成标志

- `complex_path_mode: static` 时，行为与阶段二完全一致
- `complex_path_mode: deepagents` 时，Agent 能处理典型复杂问题
- 两种模式的输出格式一致，可做 A/B 对比
- 可按租户或问题类型灰度切换

---

## 7. 各阶段的文件改动汇总

### 阶段一

| 优先级 | 文件 | 改动 |
| :--- | :--- | :--- |
| P0 | `graph.py` | `route_by_complexity` 检查 `complex_path_enabled` |
| P1 | `nodes/inject_params.py` | 增加依赖感知的问题重写 |
| P1 | `config/nl2sql_father_graph.yaml` | inject_params 新增 query_rewrite 配置 |
| P3 | `nodes/inject_params.py` | 函数式状态更新 |
| P3 | `nodes/check_completion.py` | 函数式状态更新 |
| P3 | `nodes/sql_execution.py` | 函数式状态更新 |

### 阶段二

| 文件 | 改动 |
| :--- | :--- |
| `nodes/check_completion.py` | 升级为 Adaptive Check（失败分类、重规划、补查） |
| `state.py` | 新增 replan_count、supplement_query_count、failure_category |
| `state.py` → `SubQueryInfo` | 新增 retry_summary |
| `config/nl2sql_father_graph.yaml` | 新增 adaptive_check 配置段 |
| `nodes/summarizer.py` | 适配 failure_category |
| `graph.py` → `run_nl2sql_query` | invoke 改为 stream，收集中间事件 |
| API 层（FastAPI） | 新增 streaming 端点 |
| 子图 `state.py` → `extract_output` | 新增 retry_summary 字段 |
| `graph.py` → `sql_gen_wrapper` / `sql_gen_batch_wrapper` | 透传 retry_summary 到 SubQueryInfo |

### 阶段四（条件触发）

| 文件 | 改动 |
| :--- | :--- |
| 新增 `nodes/deep_complex_orchestrator.py` | DeepAgent 编排节点 |
| 新增 `tools/solve_subproblem.py` | 封装子图+执行为高层工具 |
| `graph.py` | 根据 complex_path_mode 路由到不同节点 |
| `state.py` | 新增 complex_artifacts、deep_agent_metrics 等字段 |
| `config/nl2sql_father_graph.yaml` | 新增 deepagents 配置段 |

---

## 8. 最终结论

### 8.1 核心建议

分四个阶段推进 Complex Path 的演进：

1. **阶段一**：修复基础 bug，补齐测试，让 Complex Path 能稳定运行
2. **阶段二**：在现有架构上增加 Adaptive Check，获得有限但可控的动态规划能力
3. **阶段三**：用真实数据验证 Adaptive Check 是否足够
4. **阶段四**（条件触发）：仅在验证表明需要更强动态性时，按 84 号文档方案局部引入 DeepAgents

### 8.2 不建议的做法

- 不建议跳过阶段一/二直接引入 DeepAgents——基础 bug 未修时，新旧方案都无法稳定运行
- 不建议将子图拆成多个底层工具供 Agent 调用——会破坏子图已有的能力闭环
- 不建议依赖纯自然语言传递依赖结果——NL2SQL 场景中数值精度和列结构会丢失

### 8.3 一句话总结

**先修地基，再加反馈，验证够了就停，不够再换引擎。**
