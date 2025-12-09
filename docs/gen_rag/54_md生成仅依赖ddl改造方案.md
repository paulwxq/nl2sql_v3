# 54. MD 生成仅依赖 DDL 的改造方案

## 背景与目标
- 现状：`--step md` 走数据库通路（`_process_table_from_db`），会连接 DB 抽样、可选调用 LLM 补注释。  
- 需求：提供“仅依赖 DDL 目录、不访问 DB/LLM”的 MD 生成路径，复用已生成的 `output/metaweave/metadata/ddl/*.sql`（含 SAMPLE_RECORDS 注释块）输出 Markdown。

## 现状梳理（关键代码）
- CLI 步骤：`metadata --step md` → `MetadataGenerator.generate(...)` → `_process_table_from_db`。  
- DDL 解析：`DDLLoader` 解析 `ddl/{schema}.{table}.sql`，可抽取 SAMPLE_RECORDS、列/表注释、约束、索引等。  
- Markdown 输出：`OutputFormatter.generate_markdown` 依赖 `TableMetadata` + `sample_data`（DataFrame）；若无样本，示例值显示 `null`。`_save_json` 会尝试从 DDL 文件再抽 SAMPLE_RECORDS 作为 JSON 的样例数据。

## 改造目标
1) 新增“DDL-only”模式：MD 生成只读取 DDL，不访问 DB、不调用 LLM。  
2) 样例数据：优先使用 DDL 内的 SAMPLE_RECORDS；若缺失则允许为空，不回退数据库采样。  
3) 注释来源：仅用 DDL 中的 COMMENT 语句，不调用 LLM 补注释。  
4) 兼容性：保留现有 `--step md` 行为；新增独立入口/开关切换到 DDL-only。

## 方案设计
### A. 入口与切换
- 方案 A1（新 step，侵入最小）：在 CLI 增加 `--step md_ddl`，流程与 `md` 一致，但走 DDL-only 通路。  
- 方案 A2（配置开关）：在配置增加 `md.use_ddl_only: true`（或 `output.markdown_use_ddl_only`），`--step md` 时根据开关选择通路。  
推荐：A1 + A2 组合（step 优先，便于显式区分）。

### B. 处理流程（DDL-only）
1. `_process_table` 分支：当 step=md_ddl（或开关开启）时，走 DDL-only 处理函数。  
2. 载入元数据：使用 `DDLLoader.load_table(schema, table)` 获取 `TableMetadata` + `sample_records`。  
3. 禁用 DB 访问：不做行数查询、不做 `sample_data` 抽样，`sample_data=None` 传入 formatter。  
4. 禁用 LLM：强制 `comment_enabled=False`（或跳过 `CommentGenerator` 调用）。  
5. 样例数据：  
   - 将 DDL 中的 SAMPLE_RECORDS 写回 `metadata.sample_records`（`DDLLoader` 已赋值）。  
   - 在 `OutputFormatter.generate_markdown/_get_sample_value` 里增加兜底：当 `sample_data` 为空时，尝试从 `metadata.sample_records.records` 取前 N 条值作为示例；若仍为空，输出 `null`。  
   - `_save_json` 已有 `_extract_sample_records_from_ddl` 可复用；确保不再依赖 DB 样本。  
6. 行数 row_count：可保持 0，或从 SAMPLE_RECORDS 的 `total_rows` 字段补充（若存在）。  

### C. 配置与默认值
- 新增配置示例：
```yaml
markdown_generation:
  use_ddl_only: true          # 开启后 md 走 DDL-only
  sample_value_count: 2       # 依旧控制示例值数量
comment_generation:
  enabled: false              # DDL-only 场景建议关闭
sampling:
  enabled: false              # 避免误用 DB 抽样
```
- CLI step 新增：`md_ddl`（或 `md --ddl-only` flag）。

### D. 受影响模块与修改点
- `src/metaweave/cli/metadata_cli.py`：新增 step/flag 分支，调用生成器的 DDL-only 流程。  
- `src/metaweave/core/metadata/generator.py`：  
  - `_process_table` 分支选择 DDL-only。  
  - 新的 DDL-only 处理函数：复用 `_get_ddl_loader().load_table`，跳过 DB/LLM，传 `sample_data=None`。  
  - 关闭注释生成（或在 DDL-only 分支直接禁用）。  
- `src/metaweave/core/metadata/formatter.py`：  
  - `_get_sample_value` 增加从 `metadata.sample_records` 取样本的兜底逻辑。  
  - `generate_markdown` 在无 DataFrame 时仍能用 DDL 的样例数据填示例值。  
- （可选）`OutputFormatter._save_json`：若未来也希望 JSON 输出走 DDL-only，可保持现有 `_extract_sample_records_from_ddl` 逻辑即可。

### E. 执行与验证
1. 先跑 `--step ddl` 生成 `output/.../ddl/*.sql`，确保带 `/* SAMPLE_RECORDS {...} */`。  
2. 运行 `--step md_ddl`（或 `--step md` + 配置开关）。  
3. 验证 `output/metaweave/metadata/md/*.md`：  
   - 字段列表包含类型与注释；无 DB/LLM 也应有 DDL 自带注释。  
   - 示例值来自 SAMPLE_RECORDS；缺失时显示 `null`。  
   - 补充说明包含主键/外键/唯一/索引。  
4. 确认未发生数据库连接/LLM 调用（日志中无连接/调用信息）。

### F. 风险与限制
- DDL 必须完整且包含 COMMENT/SAMPLE_RECORDS，否则注释/示例会缺失。  
- 若 DDL 中没有样例数据，Markdown 示例值将显示 `null`。  
- 行数、统计信息在 DDL-only 模式下可能为 0/缺失。  
- 与现有 `--step md` 并存时，需要明确用户入口，避免混淆。

## 小结
通过增加 DDL-only 入口与 Formatter 的样本兜底，可以实现“仅依赖 DDL、无 DB/LLM”的 Markdown 生成路径，核心依赖已存在的 `DDLLoader` 与 `OutputFormatter`，改造面集中在入口选择、禁用外部依赖以及示例值获取方式。

