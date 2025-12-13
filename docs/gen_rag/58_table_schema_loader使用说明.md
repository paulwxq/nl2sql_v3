# 58_table_schema_loader 使用说明

## 快速命令

- 首次加载（清空重建）：  
  `python -m src.metaweave.cli.main load --type table_schema --clean`
- 增量加载（upsert 覆盖）：  
  `python -m src.metaweave.cli.main load --type table_schema`

## 参数说明

- `--type table_schema`：必填，指定表结构加载器。
- `--clean`：可选。开启则删除并重建集合，使用 insert 性能更高；不带则走 upsert 增量覆盖。
- `--config/-c`：可选，默认 `configs/metaweave/loader_config.yaml`。相对路径基于项目根目录。
- `--debug`：可选，输出调试日志。

## 配置要求（来自 loader_config.yaml）

```yaml
table_schema_loader:
  md_directory: "output/metaweave/metadata/md"
  json_llm_directory: "output/metaweave/metadata/json_llm"
  options:
    batch_size: 50        # 可选
    # max_tables: 0       # 0=不限制
    # include_columns: true
    # skip_empty_desc: true
```

- Milvus/Embedding 连接与向量维度从 `configs/metaweave/metadata_config.yaml` 读取（embedding.providers.{active}.dimensions）。
- object_id 作为主键（schema.table / schema.table.column），增量模式会覆盖同名对象。

## 输入文件

- Markdown：`md_directory` 下的 `schema.table.md`，表头 `# schema.table（说明）`，字段行 `- col (type) - 注释 [示例: ...]`。
- JSON_LLM：`json_llm_directory` 下的同名 `schema.table.json`，用于读取 `table_category` 和时间列（data_type 包含 date/time/datetime/timestamp...）。

## 常见问题

- 集合不存在或版本不符：使用 `--clean` 先清空重建。
- 嵌入维度不匹配：确认 metadata_config.yaml 中的 embedding 维度与模型一致。
- 只加载部分表：在 `options.max_tables` 设定正整数用于调试。

