# Step 5 生成 Markdown 设计

## 1. 范围与目标
- **前置输入**：Step 1 的 DDL、Step 2 的表/列画像（JSON）、数据库采样数据
- **产出**：`output/metaweave/metadata/md/*.md`，每张表对应一份 Markdown 文档
- **执行方式**：`python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step md`
- **角色**：为 Step 7 的 MD 向量化加载和人工审阅提供结构化文档

## 2. 生成逻辑概览
```
MetadataGenerator
  └─ MetadataFormatter
       ├─ generate_markdown(metadata, sample_df)
       │   1) 表标题 + 注释
       │   2) 字段行：类型、注释、示例值（可多值）
       │   3) 补充说明：主键/外键/唯一约束/索引等
       └─ _save_markdown -> output_dir/md/{schema}.{table}.md
```
- Markdown 文档依赖 `TableMetadata`（含列信息、约束、注释）以及采样数据（用于示例值）
- 若 Step 2 启用采样，Formatter 会从样本 DataFrame 获取示例值；否则输出 `null`
- 约束和索引信息来自 Step 1 DDL 解析结果与 Step 2 画像

## 3. 核心配置
配置文件：`configs/metaweave/metadata_config.yaml`

### 3.1 输出目录
```yaml
output:
  output_dir: output/metaweave/metadata
  formats:
    - ddl
    - markdown
    - json
```
- `formats` 决定执行 Step 5 时启用 Markdown 模块
- Formatter 始终将 Markdown 写入 `${output_dir}/md`

### 3.2 Markdown 选项
```yaml
markdown_options:
  include_sample_data: true      # 是否显示示例值
  sample_rows: 5                 # 采样行数（信息性字段）
  include_statistics: true       # 是否展示统计提示
  sample_value_count: 2          # 每个字段示例值的数量（>=1）
```
- `sample_value_count` 控制 `[..示例: v1, v2]` 中的值数量；若采样不足会自动降级
- `include_sample_data=false` 时示例值统一输出 `null`

### 3.3 DDL 样例记录
```yaml
ddl_options:
  sample_records:
    enabled: true
    count: 2
    include_placeholders: true
```
- Markdown 依赖 DDL 中的 SAMPLE_RECORDS 注释块作为 Step 7 维度加载的额外上下文
- `count` 至少设为 2，以满足需求中的“两条样例记录”

## 4. 数据采样与示例值
- `sampling.sample_size` 控制数据库采样行数，默认 1000
- Formatter `_get_sample_value` 会取指定数量的非空值并串联
- 若无法采样到数据：示例值 `null`; 相关字段仍会生成

## 5. 文件结构
```
output/metaweave/metadata/md/
└── schema.table.md
```
Markdown内容标准化：
1. `# schema.table（表注释）`
2. `## 字段列表` → `- column (type) - comment [示例: v1, v2]`
3. `## 字段补充说明` → 主键 / 外键 / 唯一约束 / 索引 / 数值精度等
4. 若配置允许，可附带统计或逻辑提示

## 6. 执行流程
1. `metadata` CLI 解析 `--step md`，加载 YAML 配置
2. MetadataGenerator 读取表元数据、采样数据、注释与约束
3. Formatter 根据 `formats_override=['markdown']` 仅写 `.md`
4. 结果路径记录在 `GenerationResult.output_files`

## 7. 验证要点
- 目录：`output/metaweave/metadata/md` 存在并包含 `{schema}.{table}.md`
- 文档示例值数量与 `sample_value_count` 一致，默认 2 条
- 字段补充说明覆盖主外键、唯一约束、索引
- DDL `SAMPLE_RECORDS` 块包含至少 2 条样例记录，供 Step 7 使用

## 8. 与 Step 7 的衔接
- Step 7 的 MDLoader 将遍历 `output/metaweave/metadata/md/*.md`，分块向量化
- 文档规范需保持稳定，以便 chunking 与检索模板复用
