# MetaWeave - 数据库元数据自动生成和增强平台

MetaWeave 是一个用于从 PostgreSQL 数据库中自动抽取元数据、生成数据画像、发现表关系，并导出到图数据库和向量数据库的工具平台。

## 功能特性

### 当前已实现功能

#### 1. 数据库元数据生成模块

- ✅ **元数据抽取**：从 PostgreSQL 数据库中提取表结构、字段、约束、索引等完整元数据
- ✅ **智能注释生成**：使用 LLM (qwen-plus/deepseek) 自动生成缺失的表注释和字段注释
- ✅ **逻辑主键识别**：通过样本数据分析识别潜在的逻辑主键（单字段和复合键）
- ✅ **多格式输出**：生成 DDL、Markdown、JSON 格式的元数据文档
- ✅ **缓存机制**：LLM 生成的注释支持缓存，避免重复调用
- ✅ **并发处理**：支持多线程并发处理多张表，提升效率

### 即将实现的功能

- 🔜 数据采样与画像模块
- 🔜 关系评估和决策模块
- 🔜 数据域与 SQL 样例生成模块
- 🔜 导出到 Neo4j 图数据库
- 🔜 导出到 Milvus 向量数据库

## 技术栈

- **Python**: 3.12+
- **Database**: PostgreSQL 17.x
- **LLM Framework**: LangChain 1.0.x
- **LLM Providers**: 通义千问 (qwen-plus), DeepSeek
- **数据处理**: pandas, psycopg3

## 快速开始

### 1. 安装依赖

```bash
# 使用 uv（推荐）
uv pip install -e .

# 或使用 pip
pip install -e .
```

### 2. 配置环境变量

创建 `.env` 文件：

```bash
# 数据库配置
DB_HOST=localhost
DB_PORT=5432
DB_NAME=your_database
DB_USER=postgres
DB_PASSWORD=your_password

# LLM API 配置
# 通义千问
DASHSCOPE_API_KEY=your_dashscope_api_key
DASHSCOPE_MODEL=qwen-plus  # 可选：qwen-turbo, qwen-plus, qwen-max, qwen-long

# DeepSeek（如果使用 deepseek）
# DEEPSEEK_API_KEY=your_deepseek_api_key
# DEEPSEEK_MODEL=deepseek-chat
# DEEPSEEK_API_BASE=https://api.deepseek.com/v1
```

### 3. 配置文件

编辑 `configs/metaweave/metadata_config.yaml`:

```yaml
database:
  host: ${DB_HOST:localhost}
  port: ${DB_PORT:5432}
  database: ${DB_NAME:your_database}
  user: ${DB_USER:postgres}
  password: ${DB_PASSWORD}
  schemas:
    - public

llm:
  provider: qwen-plus  # 或 deepseek
  model: qwen-plus
  api_key: ${LLM_API_KEY}
  temperature: 0.3

output:
  output_dir: output/metaweave/metadata
  formats:
    - ddl
    - markdown
    - json
```

### 4. 运行元数据生成

#### 方式 1：使用 CLI（推荐）

```bash
# 生成所有表的元数据
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml

# 指定 schema
python -m src.metaweave.cli.main metadata -c configs/metaweave/metadata_config.yaml --schemas public,myschema

# 指定表
python -m src.metaweave.cli.main metadata -c configs/metaweave/metadata_config.yaml --tables users,orders

# 调整并发数
python -m src.metaweave.cli.main metadata -c configs/metaweave/metadata_config.yaml --max-workers 8

# 启用调试模式
python -m src.metaweave.cli.main --debug metadata -c configs/metaweave/metadata_config.yaml
```

#### 方式 2：使用运行脚本

```bash
python scripts/metaweave/run_metadata_generation.py --config configs/metaweave/metadata_config.yaml
```

#### 方式 3：在代码中使用

```python
from src.metaweave.core.metadata.generator import MetadataGenerator

# 初始化生成器
generator = MetadataGenerator("configs/metaweave/metadata_config.yaml")

# 生成元数据
result = generator.generate(
    schemas=["public"],
    tables=None,  # None 表示处理所有表
    max_workers=4
)

# 查看结果
print(f"成功处理: {result.processed_tables} 张表")
print(f"生成注释: {result.generated_comments} 个")
print(f"识别逻辑主键: {result.logical_keys_found} 个")
```

## 输出文件说明

生成的文件位于 `output/metaweave/metadata/` 目录下：

### DDL 文件 (`ddl/`)

标准的 PostgreSQL DDL 脚本，包含：
- CREATE TABLE 语句
- 字段定义和约束
- 主键、外键、唯一约束
- 索引定义
- 表和字段注释

示例：`public.users.sql`

### Markdown 文件 (`md/`)

可读性强的文档，包含：
- 表基本信息
- 字段详细信息
- 约束和索引信息
- 样本数据（可配置）
- 元数据增强记录

示例：`public.users.md`

### JSON 文件 (`json/`)

结构化数据，便于程序处理：
- 完整的元数据结构
- 便于导入其他系统
- 支持进一步处理

示例：`public.users.json`

## 配置说明

### 数据库配置

```yaml
database:
  host: localhost
  port: 5432
  database: your_database
  user: postgres
  password: your_password
  pool_min_size: 1
  pool_max_size: 5
  schemas:
    - public
  exclude_tables:
    - temp_*
    - test_*
```

### LLM 配置

#### 使用通义千问

```yaml
llm:
  provider: qwen-plus
  # 支持的模型：qwen-turbo（快速）, qwen-plus（平衡）, qwen-max（最强）, qwen-long（长文本）
  model: ${DASHSCOPE_MODEL:qwen-plus}  # 默认 qwen-plus
  api_key: ${DASHSCOPE_API_KEY}
  temperature: 0.3
  max_tokens: 500
```

#### 使用 DeepSeek

```yaml
llm:
  provider: deepseek
  model: ${DEEPSEEK_MODEL:deepseek-chat}  # 默认 deepseek-chat
  api_key: ${DEEPSEEK_API_KEY}
  api_base: ${DEEPSEEK_API_BASE:https://api.deepseek.com/v1}
  temperature: 0.3
  max_tokens: 500
```

### 注释生成配置

```yaml
comment_generation:
  enabled: true
  generate_table_comment: true
  generate_column_comment: true
  language: zh-CN
  cache_enabled: true
  cache_file: cache/metaweave/comment_cache.json
```

### 逻辑主键识别配置

```yaml
logical_key_detection:
  enabled: true
  min_confidence: 0.7
  max_combinations: 3
  name_patterns:
    - id
    - code
    - key
    - no
```

## 目录结构

```
src/metaweave/
├── core/
│   └── metadata/           # 元数据生成模块
│       ├── generator.py    # 主生成器
│       ├── connector.py    # 数据库连接器
│       ├── extractor.py    # 元数据提取器
│       ├── comment_generator.py  # 注释生成器
│       ├── logical_key_detector.py  # 逻辑主键检测器
│       ├── formatter.py    # 输出格式化器
│       └── models.py       # 数据模型
├── services/
│   ├── llm_service.py      # LLM 服务
│   └── cache_service.py    # 缓存服务
├── utils/
│   ├── file_utils.py       # 文件工具
│   ├── data_utils.py       # 数据处理工具
│   └── sql_templates.py    # SQL 查询模板
└── cli/
    ├── main.py             # CLI 主入口
    └── metadata_cli.py     # 元数据 CLI
```

## 常见问题

### 1. LLM API 调用失败

- 检查 API Key 是否正确
- 检查网络连接
- 查看日志文件 `logs/metaweave/metadata.log`
- 可以禁用注释生成：在配置文件中设置 `comment_generation.enabled: false`

### 2. 数据库连接失败

- 检查数据库配置是否正确
- 确认数据库用户权限
- 检查防火墙设置

### 3. 输出文件为空

- 检查 output_dir 配置
- 确认有写入权限
- 查看错误日志

### 4. 处理速度慢

- 增加并发数：`--max-workers 8`
- 减少采样数量：`sampling.sample_size: 100`
- 禁用注释生成（如果不需要）

## 日志

日志文件位于 `logs/metaweave/` 目录：

- `metadata.log`: 主日志文件
- 包含详细的执行信息和错误堆栈

调整日志级别：

```yaml
logging:
  level: DEBUG  # DEBUG | INFO | WARNING | ERROR
```

## 开发指南

### 运行测试

```bash
# 运行所有测试
pytest tests/metaweave/

# 运行特定测试
pytest tests/metaweave/unit/test_metadata/

# 带覆盖率
pytest --cov=src/metaweave tests/metaweave/
```

### 代码规范

- 使用 Python 3.12+ 类型注解
- 遵循 PEP 8 代码规范
- 所有公共方法需要 docstring
- 使用 logging 记录日志

## 许可证

MIT License

## 联系方式

- 项目维护者：MetaWeave Team
- 文档版本：v0.1.0

