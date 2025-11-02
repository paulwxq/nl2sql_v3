# SQL生成子图重要修改规划

## 修改背景
- 已上线的 SQL 生成子图目前直接接收自然语言 query，未在子图内部实现 LLM 解析阶段，与 docs/sql_generation_subgraph_design.md 及 docs/13.SQL生成流程文档.md 中“Parser 阶段”设计不符。
- SQL 提示词生成逻辑没有严格按照 docs/14.历史SQL检索功能改造方案.md 与 docs/15.完整提示词与真实案例.md 描述的检索与上下文拼接顺序执行，历史 SQL 检索缺少候选表过滤，提示词内容组织也未完全对齐。

## 修改目标
- 在子图内部补齐“问题解析 → Schema 检索 → SQL 生成 → 验证”的完整链路，保证解析结果进入状态树并驱动后续检索。
- 调整提示词与历史 SQL 检索流程，确保检索步骤、过滤策略与提示词结构与设计文档一致，提高生成 SQL 的准确性与可解释性。

## 任务拆解与实施步骤

### 任务一：新增 LLM 问题解析阶段
1. **新增解析节点**：在 src/modules/sql_generation/subgraph/nodes 新增 question_parsing.py（或同名）节点，调用 LLM（配置参考 docs/15.完整提示词与真实案例.md 的 Parser Prompt），输出 QueryParseResult 结构。
2. **扩展 State**：
   - 在 SQLGenerationState 中新增 parse_result 字段（完整 JSON）与派生的 parse_hints，默认值为空，在解析节点运行后写入。
   - 更新 create_initial_state / extract_output，确保解析结果对外可用，同时兼容现有从主流程传入 parse_hints 的场景（若上游已解析则跳过 LLM 调用）。
3. **子图拓扑调整**：修改 create_sql_generation_subgraph，使流程变更为 START → question_parsing → schema_retrieval → sql_generation → validation，并在解析失败时设置 error/error_type=parsing_failed，直接结束。
4. **Schema 检索对接**：
   - 调整 SchemaRetriever 入口签名，支持直接接收 parse_result 或 parse_hints。
   - 维度值匹配、候选表收集等逻辑优先使用解析节点输出，而非简单 query 文本。
5. **配置与提示**：在 sql_generation_subgraph.yaml 中新增 parser 配置段（模型、超时、重试、Prompt 模板路径），并在 src/services/config_loader 中补充加载逻辑。
6. **测试与样例**：
   - 补充解析节点的单元测试（使用固定 LLM Mock 或离线响应样本）。
   - 更新 examples/simple_example.py、集成测试 	ests/integration/sql_generation_subgraph，验证从空 parse_hints 到完整流程的执行。

### 任务二：修正 SQL 提示词与历史示例检索流程
1. **重构历史 SQL 检索**：
   - 将 SchemaRetriever 中的 search_similar_sqls 调用迁移到 SQL 生成节点前置步骤，确保在候选表集合、JOIN 计划确定后才触发历史示例检索。
   - 扩展 PGClient.search_similar_sqls，支持传入 	ables_used、quality_score 阈值、候选表列表，按 docs/14.历史SQL检索功能改造方案.md 中“查询方法 2/3”过滤排序；必要时新增 search_similar_sqls_with_tables 封装。
2. **共享查询向量**：
   - 在解析或 Schema 检索阶段缓存查询向量（例如 state 中新增 query_embedding 字段）以避免重复向量化。
   - 历史 SQL 检索与语义检索复用该向量，降低调用成本。
3. **提示词结构对齐**：
   - 按 docs/15.完整提示词与真实案例.md 重新审视 SQLGenerationAgent._build_prompt，确保段落顺序为：问题信息 → 解析结果（时间/维度/指标） → Schema（表卡片、JOIN 计划、时间列） → 历史 SQL 示例 → 维度值提示 → 验证反馈。
   - 对维度过滤展示逻辑进行检查，若 uild_optimized_filters 仅输出 alue= 占位，需改为 列=主键 或 列 IN (...) 等可执行提示。
4. **配置更新**：
   - 在 sql_generation.prompt 配置中新增历史 SQL 检索相关阈值（最小相似度、质量评分、候选表限制数量）。
   - 若使用新的 Prompt 模板文件，在 src/prompts/sql_generation 中新增/更新模板，并在配置中引用。
5. **校验流程**：
   - 确保验证阶段在 state 中可访问解析结果与历史示例，便于调试输出。
   - 更新集成测试覆盖：
     - 模拟含多个候选表场景，断言历史 SQL 检索结果按表重叠排序。
     - 检查提示词文本中是否包含 Parser 输出的时间窗口、维度过滤和历史 SQL 片段。

## 验收标准
- 子图能够在未提供 parse_hints 的情况下独立完成解析并生成有效 SQL，解析节点失败时返回明确错误类型。
- 历史 SQL 检索结果默认只包含与候选表有交集的示例，并按设计文档定义的优先级排序。
- 新提示词结构与 docs/15.完整提示词与真实案例.md 示例一致，维度值提示可直接指导 SQL 编写。
- 单元/集成测试覆盖解析节点、历史 SQL 检索过滤逻辑及提示词文本关键段落。

## 风险与依赖
- 解析节点引入 LLM 依赖，需在测试环境中准备 Mock 响应或录制结果，避免 CI 不稳定。
- 历史 SQL 检索依赖 system.sql_embedding.tables_used 等字段，需确认数据库 schema 已按 docs/14.历史SQL检索功能改造方案.md 部署。
- Prompt 模板调整后需评估 token 消耗与生成时延，必要时更新配置上限。
