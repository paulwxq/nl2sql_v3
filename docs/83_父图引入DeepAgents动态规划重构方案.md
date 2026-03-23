# 83_父图引入 DeepAgents SDK 动态规划重构方案

## 1. 背景与动机

当前的 NL2SQL 父图架构采用的是 **静态 DAG 规划 (Static DAG Planning)** 模式。在处理复杂问题时，由 `Planner` 节点一次性生成所有子查询及依赖关系。

**核心瓶颈：**
- **缺乏灵活性**：如果中间某个 SQL 执行结果为空或不符合预期，系统无法动态调整后续计划。
- **状态管理复杂**：手动维护 `sub_queries` 列表、依赖注入 (`{{sq1.result}}`)、环检测等逻辑，导致代码耦合度高且难以扩展。
- **反思能力弱**：系统无法根据执行报错或中间数据进行自我修正（Self-Correction）。

引入 `langchain-ai/deepagents` SDK 旨在将“静态图”升级为“具备动态规划能力的自主 Agent”，利用其内置的 `write_todos` 机制实现更智能的任务拆解与执行。

---

## 2. 目标架构对比

### 2.1 当前架构 (Static Graph)
`Router` -> `Planner (Static JSON)` -> `Inject Params` -> `SQL Gen Batch` -> `SQL Execution` -> `Check Completion (Loop)`

### 2.2 重构后架构 (DeepAgent Orchestration)
`Router` -> 分支选择：
1. **Fast Path**: 保持原样（极简、低延迟）。
2. **Complex Path**: 进入 `DeepAgent` 模块。
   - **Internal Loop**: `DeepAgent` 通过 `write_todos` 自主管理任务。
   - **Tools**: 将 `SQL生成子图` 和 `SQL执行模块` 封装为 Agent 工具。

---

## 3. 核心重构逻辑

### 3.1 节点替换方案
重构将合并并替换 Complex Path 中的多个繁琐节点：

| 待替换节点 | 替换后的实现方式 | 理由 |
| :--- | :--- | :--- |
| `Planner` | `DeepAgent` + `write_todos` | 由一次性生成 JSON 改为动态维护 Todo 列表，支持中途增删改任务。 |
| `Inject Params` | Agent 上下文指代消解 | 依靠 LLM 的推理能力直接在工具调用中引用前序结果，无需手动正则替换字符串。 |
| `Check Completion` | Agent 自主终止逻辑 | Agent 根据 Todo 完成情况及目标达成度，自主决定何时输出 `Summarizer`。 |

### 3.2 DeepAgents 融入方式

1. **工具化封装**：
   - 将原有的 `run_sql_generation_subgraph` 封装为 `generate_sql_tool`。
   - 将 `sql_execution_node` 逻辑封装为 `execute_query_tool`。
   - （可选）增加 `inspect_schema_tool`，允许 Agent 在规划受阻时主动查看表结构。

2. **动态 Todo 管理**：
   - Agent 接收复杂问题后，首先调用 `write_todos` 初始化计划。
   - 每执行完一个工具，Agent 观察 `observation`（SQL结果），决定是标记 Todo 完成，还是因为数据异常而修改后续 Todo。

3. **状态对齐**：
   - 将 `DeepAgent` 的内部状态映射回 `NL2SQLFatherState`，确保父图的 `conversation_history` 和 `metadata` 能够持续累积。

---

## 4. 核心工作流描述

1. **意图路由**：`Router` 识别为 "complex"。
2. **Agent 初始化**：启动 `DeepAgent` 实例，加载 `write_todos` 中间件。
3. **循环推理 (The "Deep" Loop)**：
   - **Plan**: Agent 调用 `write_todos` 设定步骤（如：1. 查 A 统计量；2. 查 B 详情）。
   - **Act**: Agent 调用 `generate_sql_tool` 生成 SQL，随后调用 `execute_query_tool` 获取数据。
   - **Observe**: Agent 分析执行结果。若结果为空，Agent 可能会新增一个 Todo： “检查查询条件是否过严”。
   - **Reflect**: Agent 更新 Todo 状态。
4. **结果汇总**：所有关键 Todo 完成后，Agent 直接调用 `Summarizer` 逻辑输出最终答案。

---

## 5. 预期收益

1. **自愈能力**：当 SQL 执行出错或数据不符合逻辑时，Agent 能够尝试修复查询而非直接返回错误。
2. **逻辑简化**：移除大量手动的依赖追踪逻辑，利用 LLM 的自然语言推理处理子任务间的数据传递。
3. **易扩展性**：未来增加“图表生成”、“数据对比”等新功能只需增加对应的工具，无需修改复杂的图拓扑结构。

---

## 6. 潜在风险与应对

- **成本上升**：DeepAgent 的多轮反思会消耗更多 Token。**应对**：在系统提示词中严格限制 `max_steps`。
- **延迟增加**：顺序推理比静态并发慢。**应对**：对完全独立的子任务，在工具层面支持批量调用或保持 Fast Path 覆盖 80% 的常规场景。
- **SDK 稳定性**：`deepagents` 较新。**应对**：保持接口抽象，以便在必要时回退到纯 LangGraph 实现。
