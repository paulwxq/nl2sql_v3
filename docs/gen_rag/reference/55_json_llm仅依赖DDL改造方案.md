# 55. json_llm 仅依赖 DDL 的改造方案

## 背景与现状
- 现状：`--step json_llm` 入口在 `metadata_cli`，内部使用 `LLMJsonGenerator` 通过 `DatabaseConnector` 提取表结构与采样数据，然后基于 LLM 推断 `table_category`（可选 `table_domains`）。表/列注释与样例数据都依赖数据库实时获取。
- 已有 DDL 资产：`output/metaweave/metadata/ddl/*.sql` 内含 COMMENT 语句与 `/* SAMPLE_RECORDS {...} */`（最多 5 条，表为空时没有）。
- 新要求：`--step json_llm` **只有 DDL-only 模式**，结构与样例全部来源于 DDL（含 SAMPLE_RECORDS），**不再连接数据库获取表结构或采样数据**。LLM 推断逻辑保持。

## 改造目标
1) 结构与样例：仅从 DDL 解析表结构与 SAMPLE_RECORDS，彻底禁用数据库抽样与结构获取。  
2) 注释：仅用 DDL COMMENT（保持 comment/comment_source），不调用 CommentGenerator。  
3) 推断：继续用 LLM 推断 `table_category`/`table_domains`，prompt 仍包含结构+样例。  
4) 模式：唯一模式为 DDL-only，不做 DB 通路兼容。

## 方案设计
### A. 入口与模式
- `--step json_llm` 直接定义为 DDL-only 模式（无 DB 兜底/兼容分支）。  
- CLI 校验：仅检查 DDL 目录存在；无需数据库连接测试。

### B. 数据获取与样例
- 结构：使用 `DDLLoader`（与 `--step json` 共用）从 `{output_dir}/ddl/{schema}.{table}.sql` 解析 `TableMetadata`、约束、索引、COMMENT。  
- 样例：解析 `SAMPLE_RECORDS` JSON，并显式转换为 DataFrame：  
  ```python
  def sample_records_to_dataframe(sample_records: List[Dict]) -> pd.DataFrame:
      """将 DDL SAMPLE_RECORDS 转换为 DataFrame"""
      if not sample_records:
          return pd.DataFrame()
      data_list = [record.get("data", {}) for record in sample_records]
      return pd.DataFrame(data_list)
  ```
  - 若 SAMPLE_RECORDS 缺失或为空，返回空 DataFrame，不回退数据库。  
  - 字段不齐全时，pandas 自动填充 NaN，可按需在统计前填充空字符串或忽略。  
- 行数：可保持 0；如 SAMPLE_RECORDS 带 `total_rows` 字段可优先采用。

### C. 统计与结构标志
- 列统计：对转换后的 DataFrame 运行 `get_column_statistics`；DataFrame 为空则 `statistics=None` 并记录“无样例”提示。  
- structure_flags：依赖 DDL 约束即可正常生成。  
- 采样开关：视为无数据库采样，确保不触发 DB。

### D. 推断与输出
- `_build_simplified_json` 输入：DDL Loader 的 `TableMetadata` + SAMPLE_RECORDS DataFrame。  
- `_merge_and_save` 保持；prompt 继续包含样例（DataFrame 为空则样例段为空）。  
- 注释：沿用 DDL COMMENT，不调用 CommentGenerator。

### E. CLI 与校验
- 校验 DDL 目录存在，否则报错“请先执行 --step ddl”。  
- 跳过数据库连接测试，日志明确“DDL-only，无 DB 访问”。  
- schemas/tables/domain 行为保持，但不触发 DB。

## 受影响模块
- `src/metaweave/cli/metadata_cli.py`：新增 step/flag 入口，DDL-only 模式下不实例化 `DatabaseConnector` 或仅用于 domain 解析时的配置（若仍需）。  
- `src/metaweave/core/metadata/llm_json_generator.py`：  
  - 支持 DDL-only 初始化路径（注入 DDL Loader / ddl_dir）。  
  - 替换结构获取与采样为 DDL 解析与 SAMPLE_RECORDS DataFrame。  
  - 降级统计/样例缺失的处理。  
- `src/metaweave/core/metadata/ddl_loader.py`（若需要）：暴露 SAMPLE_RECORDS 解析/转换辅助，或增加工具函数将 SAMPLE_RECORDS 转 DataFrame。  
- （可选）`data_utils`：若需公共函数处理有限样本统计或安全取样。

## 验证场景
1) 有样例数据表：`--step json_llm` 输出含 COMMENT、样例、统计，table_category/domains 正常推断。  
2) 无样例数据表：样例为空，statistics 为 `null`，推断仍可执行。  
3) DDL 缺失：明确报错“请先执行 --step ddl”。  
4) 下游验证：`--step rel_llm`/`--step cql_llm` 能消费新的 json_llm 输出。

## 风险与缓解
- 样本量有限：统计精度有限 → 日志提示样本条数（≤5），接受降级。  
- DDL 不完整：缺 COMMENT / SAMPLE_RECORDS 时，输出缺注释/样例 → 不回退 DB，日志提示缺失。  
- domain 功能：仍可基于配置文件的 domains；若有依赖 DB 描述生成 domains 的路径，需要显式禁用或提前生成。

## 粗略工作量
- DDL-only 入口与校验：0.5d  
- LLMJsonGenerator DDL-only 实现（结构/样例替换，含 DataFrame 转换）：1d  
- 边界处理与验证：0.5d  
合计约 2d（单人），视回归范围调整。

