# 57_dim_value 加载到向量数据库的概要设计

## 1. 需求概述

将维度表（dim表）的指定列数据加载到向量数据库（Milvus），用于后续的维度值语义匹配功能。当前阶段仅实现 Milvus 支持，预留 PgVector 扩展接口。

**核心目标：**
- 从 PostgreSQL 读取维表数据
- 调用 Embedding 模型进行向量化
- 将维度值及其向量存储到 Milvus 的 `dim_value_embeddings` Collection
- 支持增量更新和清空重建两种模式

## 2. 配置设计

### 2.1 metadata_config.yaml 扩展

**⚠️ 重要说明：** 这是**新增配置段**，需要在开发实施时添加到现有的 `metadata_config.yaml` 文件中。

在现有配置文件中新增 `vector_database` 配置段，与 `database`、`llm`、`embedding` 平级：

```yaml
# 向量数据库配置
vector_database:
  # 当前激活的向量数据库类型
  active: milvus                    # 可选值: milvus | pgvector

  # 各向量数据库提供商配置
  providers:
    # Milvus 配置
    milvus:
      host: ${MILVUS_HOST:localhost}
      port: ${MILVUS_PORT:19530}
      database: ${MILVUS_DATABASE:nl2sql}  # 等价于 PostgreSQL 的 schema
      user: ${MILVUS_USER:}                # 可选，开源版通常无认证
      password: ${MILVUS_PASSWORD:}        # 可选

      # 连接选项
      timeout: 30
      pool_size: 10

    # PgVector 配置（预留）
    pgvector:
      use_global_config: true   # 复用 database 配置
      # 如果 use_global_config=false，需提供以下配置：
      # host: localhost
      # port: 5432
      # database: your_database
      # user: postgres
      # password: your_password
      schema: vectors             # 向量数据存储的 schema
```

**设计说明：**
- 复用现有 `embedding` 配置，不需要额外配置 embedding 模型
- 使用环境变量支持，便于部署配置
- 预留 PgVector 接口，便于未来扩展

**实施说明：**
- 开发时，将此配置段追加到 `metadata_config.yaml` 文件的 `embedding` 配置段之后
- 插入位置：第 205 行之后（`embedding` 配置段结束后）
- 需要同步更新 `.env.example` 示例环境变量：
  ```bash
  # Milvus 向量数据库配置
  MILVUS_HOST=localhost
  MILVUS_PORT=19530
  MILVUS_DATABASE=nl2sql
  MILVUS_USER=
  MILVUS_PASSWORD=
  ```

### 2.2 dim_tables.yaml 新增配置文件

**位置：** `configs/metaweave/dim_tables.yaml`

**结构：**
```yaml
# 维度表加载配置
# 说明：此文件由 dim_config --generate 自动生成维表列表，需人工填写 embedding_col

tables:
  public.dim_company:
    embedding_col: null  # 请填写要向量化的列名，如: company_name

  public.dim_product_type:
    embedding_col: null  # 请填写要向量化的列名，如: product_type_name

  public.dim_region:
    embedding_col: null  # 请填写要向量化的列名，如: region_name

  public.dim_store:
    embedding_col: null  # 请填写要向量化的列名，如: store_name
```

**设计说明：**
- 采用扁平化结构，易于人工编辑
- 键名格式：`schema.table_name`（完整表名）
- 值：`embedding_col` 初始值为 `null`，**需人工填写**要向量化的列名
- 自动生成工作流：自动扫描维表 → 生成列表框架 → 人工补充列名

### 2.3 loader_config.yaml 完善

完善现有的 `dim_loader` 配置（第74-86行）：

```yaml
dim_loader:
  # 维表列表配置文件路径（相对于项目根目录）
  config_file: "configs/metaweave/dim_tables.yaml"

  # 注意：向量数据库配置统一在 metadata_config.yaml 的 vector_database 段中配置
  # 当前版本固定使用全局配置，不支持本地配置覆盖

  # 加载选项（以下字段均为可选，未配置时使用代码默认值）
  options:
    batch_size: 100           # 批量加载大小（默认 100）
    # max_records_per_table: 0  # 每表最大加载记录数（默认 0=不限制）
    # skip_empty_values: true   # 跳过空值（默认 true）
    # truncate_long_text: true  # 截断超长文本（默认 true）
    # max_text_length: 1024     # 最大文本长度（默认 1024）
```

**设计说明：**
- **简化配置：** 不需要 `vector_db` 配置段，固定使用全局配置
- 向量数据库配置统一在 `metadata_config.yaml` 的 `vector_database` 段管理
- **可选配置：** `options` 下的所有字段均为可选，未配置时代码使用默认值
- 建议的扩展配置：
  - `batch_size`: 批量加载大小，根据性能调优
  - `max_records_per_table`: 限制每表加载记录数（测试用）
  - `skip_empty_values`: 是否跳过空值
  - `truncate_long_text`: 是否截断超长文本
  - `max_text_length`: 最大文本长度限制

**配置读取逻辑：**

```python
# 固定读取全局配置
metadata_config = load_yaml("metadata_config.yaml")
db_type = metadata_config["vector_database"]["active"]  # 当前必须是 "milvus"
db_config = metadata_config["vector_database"]["providers"][db_type]
```

**配置管理优势：**
- 单一配置源，避免配置不一致
- 减少配置复杂度，降低出错风险
- 便于统一管理向量数据库连接

**配置落地与兼容性策略：**

由于 `vector_database` 是新增配置段，**开发实施时必须先添加此配置**，否则运行时会直接失败。

**配置策略：严格检测模式（固定使用全局配置）**

根据需求"当前仅开发 Milvus"，固定使用全局配置，不实现本地配置覆盖：

1. **配置缺失检测（必须通过）：**
   ```python
   # 在 DimValueLoader._get_vector_db_config() 中
   if "vector_database" not in metadata_config:
       raise ConfigurationError(
           "metadata_config.yaml 缺少 'vector_database' 配置段。\n"
           "请参考文档添加配置: docs/gen_rag/57_dim_value加载到向量数据库的概要设计.md (第 2.1 节)"
       )
   ```

2. **配置验证（必须通过）：**
   ```python
   # 验证必填字段
   required_fields = ["active", "providers"]
   for field in required_fields:
       if field not in vector_database:
           raise ConfigurationError(f"vector_database 缺少必填字段: {field}")

   # 验证 active 值为 milvus（当前版本仅支持 Milvus）
   active = vector_database["active"]
   if active != "milvus":
       raise ConfigurationError(
           f"当前版本仅支持 Milvus 向量数据库，但配置为: {active}\n"
           f"请修改 metadata_config.yaml: vector_database.active = 'milvus'"
       )

   # 验证 Milvus provider 配置存在
   if "milvus" not in vector_database["providers"]:
       raise ConfigurationError("未找到 Milvus 的配置: vector_database.providers.milvus")
   ```

**当前版本不实现的功能（预留未来扩展）：**
- ❌ 本地配置覆盖（`dim_loader.vector_db`）- 不实现
- ❌ 配置优先级逻辑（`use_global_config`）- 不需要
- ❌ PgVector 向量数据库支持（仅预留接口）
- ❌ 多向量数据库动态切换（不实现）

**开发实施要求：**
- **首要任务：** 完成 `metadata_config.yaml` 的配置追加
- 配置追加后，立即验证 YAML 语法和必填字段
- 确保 `vector_database.active = "milvus"`
- CLI 运行时固定读取全局配置，缺失或错误会立即报错并终止
- `loader_config.yaml` 不包含 `vector_db` 配置段，保持简洁

## 3. 模块结构设计

### 3.1 新增模块

```
src/metaweave/
├── core/
│   ├── loaders/
│   │   ├── base.py                       # 已存在：加载器基类
│   │   ├── factory.py                    # 已存在：加载器工厂
│   │   ├── cql_loader.py                 # 已存在：CQL加载器
│   │   └── dim_value_loader.py           # 新增：维度值加载器
│   │
│   └── dim_value/
│       ├── __init__.py                   # 新增：dim_value子模块
│       ├── config_generator.py           # 新增：dim_tables.yaml 生成器
│       └── models.py                     # 新增：数据模型
│
├── services/
│   └── vector_db/
│       ├── __init__.py                   # 新增：向量数据库服务
│       ├── base.py                       # 新增：向量数据库客户端基类
│       ├── milvus_client.py              # 新增：Milvus客户端
│       └── pgvector_client.py            # 预留：PgVector客户端
│
└── cli/
    ├── main.py                           # 已存在：CLI主入口
    └── loader_cli.py                     # 已存在：加载CLI（无需修改）
```

### 3.2 核心类设计

#### 3.2.1 DimValueLoader (dim_value_loader.py)

```python
class DimValueLoader(BaseLoader):
    """维度值加载器

    从 PostgreSQL 读取维表数据，调用 Embedding 模型向量化后，
    加载到向量数据库（Milvus/PgVector）的 dim_value_embeddings Collection。

    配置策略：固定使用 metadata_config.yaml 的 vector_database 配置
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化加载器

        Args:
            config: 完整配置字典（包含 dim_loader、metadata_config）

        Note:
            dim_loader.options 中的字段均为可选，未配置时使用默认值：
            - batch_size: 100
            - max_records_per_table: 0 (不限制)
            - skip_empty_values: True
            - truncate_long_text: True
            - max_text_length: 1024
        """
        pass

    def _get_vector_db_config(self) -> Dict[str, Any]:
        """获取向量数据库配置（固定使用全局配置）

        从 metadata_config.yaml 读取 vector_database 配置
        不支持本地配置覆盖，严格检测模式

        Returns:
            Dict: Milvus 连接配置字典
                包含 host, port, database 等连接参数

        Raises:
            ConfigurationError: 配置缺失或 active != 'milvus'
        """
        pass

    def validate(self) -> bool:
        """验证配置和数据源

        检查：
        - dim_tables.yaml 是否存在
        - PostgreSQL 连接是否正常
        - Milvus 连接是否正常
        - Embedding 服务是否可用
        """
        pass

    def load(self, clean: bool = False) -> Dict[str, Any]:
        """执行加载操作

        Args:
            clean: 是否清空 Collection 后重建

        Returns:
            Dict: 加载结果（成功/失败、统计信息）
        """
        pass

    def _ensure_collection(self, clean: bool = False):
        """确保 Collection 存在并创建索引"""
        pass

    def _load_table(self, schema: str, table: str, embedding_col: str) -> Dict[str, int]:
        """加载单个维表

        Returns:
            Dict: {"loaded": 100, "skipped": 5}
        """
        pass

    def _fetch_table_data(self, schema: str, table: str, column: str) -> List[Tuple]:
        """从 PostgreSQL 获取维表数据"""
        pass

    def _batch_embed_and_insert(self, records: List[Dict[str, Any]]):
        """批量向量化并插入 Milvus"""
        pass
```

#### 3.2.2 DimTableConfigGenerator (config_generator.py)

```python
class DimTableConfigGenerator:
    """dim_tables.yaml 配置文件生成器

    自动从 json_llm 目录扫描维表（table_category='dim'），
    生成初始配置文件框架，embedding_col 字段留空，由人工填写。
    """

    def __init__(self, json_llm_dir: Path, output_path: Path):
        """初始化生成器

        Args:
            json_llm_dir: json_llm 文件目录路径
            output_path: 输出的 dim_tables.yaml 路径
        """
        pass

    def generate(self) -> Dict[str, Any]:
        """生成配置文件

        Returns:
            Dict: 生成的配置字典，格式：
                {
                    "tables": {
                        "schema.table": {"embedding_col": None},
                        ...
                    }
                }
        """
        pass

    def _scan_dim_tables(self) -> List[Tuple[str, str]]:
        """扫描 json_llm 目录，识别 dim 表

        Returns:
            List[Tuple]: [(schema, table), ...]
                根据 table_profile.table_category='dim' 过滤
        """
        pass

    def _write_yaml(self, config: Dict[str, Any]):
        """写入 YAML 文件（带格式化注释）

        Args:
            config: 配置字典
        """
        pass
```

#### 3.2.3 MilvusClient (milvus_client.py)

```python
class MilvusClient:
    """Milvus 向量数据库客户端

    封装 Milvus 的连接、Collection 管理、索引创建、数据插入等操作。
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化 Milvus 客户端

        Args:
            config: Milvus 配置（host, port, database, ...）
        """
        pass

    def connect(self):
        """连接到 Milvus 服务器"""
        pass

    def test_connection(self) -> bool:
        """测试连接是否正常"""
        pass

    def ensure_collection(
        self,
        collection_name: str,
        schema: CollectionSchema,
        index_params: Dict,
        clean: bool = False
    ):
        """确保 Collection 存在并创建索引

        Args:
            collection_name: Collection 名称
            schema: Collection Schema
            index_params: 向量索引参数
            clean: 是否清空重建
        """
        pass

    def insert_batch(
        self,
        collection_name: str,
        data: List[Dict[str, Any]]
    ) -> int:
        """批量插入数据

        Args:
            collection_name: Collection 名称
            data: 数据列表（字段映射）

        Returns:
            int: 插入成功的记录数
        """
        pass

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """获取 Collection 统计信息"""
        pass

    def close(self):
        """关闭连接"""
        pass
```

## 4. 核心流程设计

### 4.1 配置文件生成流程

```
用户执行：
  python -m src.metaweave.cli.main dim_config --generate

流程：
  1. 读取 metadata_config.yaml 获取 output.json_llm_directory
  2. 扫描 json_llm 目录下所有 *.json 文件
  3. 解析每个文件，检查 table_profile.table_category
  4. 过滤出 table_category='dim' 的表
  5. 对每个 dim 表：
     a. 提取 schema_name 和 table_name
     b. 添加到配置字典，embedding_col 设为 null
  6. 生成 dim_tables.yaml 文件（带格式化注释）
  7. 输出提示信息：
     - 识别的维表数量
     - 提醒用户手工填写 embedding_col
```

**示例输出：**
```
✅ 已生成 configs/metaweave/dim_tables.yaml
📊 识别到 4 个维度表：
  - public.dim_company
  - public.dim_product_type
  - public.dim_region
  - public.dim_store

⚠️  下一步：请手工编辑 dim_tables.yaml，为每个表指定 embedding_col（要向量化的列名）
📝 示例：
    public.dim_company:
      embedding_col: company_name  # 修改 null 为实际列名
```

### 4.2 数据加载流程

```
用户执行：
  python -m src.metaweave.cli.main load --type dim_value --clean

流程：
  1. 加载配置文件
     ├─ loader_config.yaml (dim_loader 配置)
     ├─ metadata_config.yaml (vector_database + embedding 配置)
     └─ dim_tables.yaml (维表列表)

  2. 初始化依赖服务
     ├─ PostgreSQL 连接 (PGConnectionManager)
     ├─ Milvus 连接 (MilvusClient)
     │  ├─ 读取 vector_database.active，验证必须为 'milvus'
     │  ├─ 读取 vector_database.providers.milvus 配置
     │  └─ 初始化 MilvusClient
     └─ Embedding 服务 (复用 metadata_config.yaml 的 embedding 配置)

  3. 验证阶段 (validate)
     ├─ 检查 dim_tables.yaml 是否存在
     ├─ 验证 metadata_config.yaml 包含 vector_database 配置
     ├─ 验证 vector_database.active = 'milvus'
     ├─ 测试 PostgreSQL 连接
     ├─ 测试 Milvus 连接
     └─ 测试 Embedding 服务

  4. 确保 Collection 存在
     ├─ 如果 clean=True: 删除现有 Collection
     ├─ 如果不存在: 创建 Collection + 定义 Schema
     └─ 创建向量索引 (HNSW + COSINE)

  5. 加载数据（逐表处理）
     对每个 dim 表：
       ├─ 检查 embedding_col 是否为 null
       │  └─ 如果为 null: 跳过该表，输出警告日志
       │
       ├─ 从 PostgreSQL 读取数据 (schema, table, embedding_col)
       │  SELECT DISTINCT {embedding_col} FROM {schema}.{table}
       │  WHERE {embedding_col} IS NOT NULL AND LENGTH({embedding_col}) > 0
       │
       ├─ 数据清洗
       │  - 跳过空值 / 空字符串
       │  - 截断超长文本 (>1024 字符)
       │  - 去重（基于 table_name + col_value）
       │
       ├─ 批量向量化（batch_size=100）
       │  - 调用 Embedding 服务（text-embedding-v3）
       │  - 生成 1024 维向量
       │
       └─ 批量插入 Milvus
          - 构造记录：(table_name, col_name, col_value, embedding[1024], update_ts)
          - 调用 insert_batch()

  6. 输出统计信息
     ├─ 总表数
     ├─ 总记录数
     ├─ 跳过记录数
     └─ 执行时间
```

**流程图：**
```
┌─────────────────┐
│ 读取配置文件     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 初始化依赖服务   │
│ - PG / Milvus   │
│ - Embedding     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 验证连接        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      No
│ 清空模式?       ├──────────┐
└────────┬────────┘          │
         │ Yes               │
         ▼                   ▼
┌─────────────────┐   ┌─────────────┐
│ DROP Collection │   │ 检查/创建   │
└────────┬────────┘   │ Collection  │
         │            └──────┬──────┘
         │                   │
         └─────────┬─────────┘
                   │
                   ▼
┌────────────────────────────────┐
│ 遍历 dim_tables.yaml          │
└───────────┬────────────────────┘
            │
            ▼
      ┌─────────┐
      │ 读取表数据│
      └────┬─────┘
           │
           ▼
      ┌─────────┐
      │ 数据清洗 │
      └────┬─────┘
           │
           ▼
      ┌─────────┐
      │ 批量向量化│
      └────┬─────┘
           │
           ▼
      ┌─────────┐
      │ 插入Milvus│
      └────┬─────┘
           │
           ▼
      [ 下一张表 ] ──> 全部完成
           │
           ▼
      ┌─────────┐
      │ 输出统计 │
      └─────────┘
```

## 5. 数据模型设计

### 5.1 Milvus Collection Schema

**Collection 名称：** `dim_value_embeddings`

**字段定义：**

| 字段名 | 类型 | 说明 | 约束 |
|--------|------|------|------|
| id | INT64 | 主键ID | PRIMARY KEY, AUTO_ID |
| table_name | VARCHAR(128) | 表全名 (schema.table) | NOT NULL |
| col_name | VARCHAR(128) | 列名 | NOT NULL |
| col_value | VARCHAR(1024) | 列值（原始文本） | NOT NULL |
| embedding | FLOAT_VECTOR(1024) | 向量（text-embedding-v3） | NOT NULL |
| update_ts | INT64 | 更新时间戳（Unix秒） | NOT NULL |

**索引定义：**
```python
from pymilvus import FieldSchema, CollectionSchema, DataType

# 完整的 Collection 创建示例
index_params = {
    "index_type": "HNSW",
    "metric_type": "COSINE",
    "params": {
        "M": 16,
        "efConstruction": 200
    }
}

# Schema 定义示例
fields = [
    FieldSchema(
        name="id",
        dtype=DataType.INT64,
        is_primary=True,
        auto_id=True
    ),
    FieldSchema(
        name="table_name",  # 格式 schema_name.table_name
        dtype=DataType.VARCHAR,
        max_length=128
    ),
    FieldSchema(
        name="col_name",
        dtype=DataType.VARCHAR,
        max_length=128
    ),
    FieldSchema(
        name="col_value",
        dtype=DataType.VARCHAR,
        max_length=1024
    ),
    FieldSchema(
        name="embedding",
        dtype=DataType.FLOAT_VECTOR,
        dim=1024  # 阿里云 text-embedding-v3 模型
    ),
    FieldSchema(
        name="update_ts",
        dtype=DataType.INT64
    )
]

schema = CollectionSchema(
    fields=fields,
    description="Embedding index for dimension value text fields"
)
```

**设计说明：**
- `id` 自增主键，避免手工管理
- `table_name` 格式为 `schema.table`，便于过滤查询
- `col_value` 限制 1024 字符，避免超长文本
- `embedding` 维度 1024，匹配阿里云 text-embedding-v3 模型
- `update_ts` 支持增量更新场景（预留）

### 5.2 dim_tables.yaml 数据结构

```yaml
tables:
  <schema>.<table>:
    embedding_col: <column_name>
```

**Python 数据模型：**
```python
from dataclasses import dataclass
from typing import Dict

@dataclass
class DimTableConfig:
    """单个维表配置"""
    schema: str
    table: str
    embedding_col: str

    @property
    def full_table_name(self) -> str:
        return f"{self.schema}.{self.table}"

@dataclass
class DimTablesConfig:
    """维表配置集合"""
    tables: Dict[str, DimTableConfig]

    @classmethod
    def from_yaml(cls, yaml_data: Dict) -> 'DimTablesConfig':
        tables = {}
        for full_name, config in yaml_data.get('tables', {}).items():
            schema, table = full_name.split('.', 1)
            tables[full_name] = DimTableConfig(
                schema=schema,
                table=table,
                embedding_col=config['embedding_col']
            )
        return cls(tables=tables)

@dataclass
class LoaderOptions:
    """加载器选项配置（带默认值）"""
    batch_size: int = 100
    max_records_per_table: int = 0  # 0 = 不限制
    skip_empty_values: bool = True
    truncate_long_text: bool = True
    max_text_length: int = 1024

    @classmethod
    def from_dict(cls, options: Dict[str, Any]) -> 'LoaderOptions':
        """从配置字典创建，未提供的字段使用默认值"""
        return cls(
            batch_size=options.get('batch_size', 100),
            max_records_per_table=options.get('max_records_per_table', 0),
            skip_empty_values=options.get('skip_empty_values', True),
            truncate_long_text=options.get('truncate_long_text', True),
            max_text_length=options.get('max_text_length', 1024)
        )
```

## 6. CLI 命令设计

### 6.1 生成配置文件命令

**新增命令：** `dim_config`

```bash
python -m src.metaweave.cli.main dim_config --generate
```

**参数：**
- `--generate` / `-g`: 生成 dim_tables.yaml 配置文件
- `--config` / `-c`: 指定 metadata_config.yaml 路径（可选）
- `--output` / `-o`: 指定输出文件路径（可选，默认 configs/metaweave/dim_tables.yaml）

**示例：**
```bash
# 使用默认配置
python -m src.metaweave.cli.main dim_config --generate

# 指定配置文件
python -m src.metaweave.cli.main dim_config --generate \
  --config configs/my_metadata_config.yaml \
  --output configs/my_dim_tables.yaml
```

### 6.2 加载数据命令

**已存在命令：** `load --type dim_value`

```bash
python -m src.metaweave.cli.main load --type dim_value --clean
```

**参数：**
- `--type dim_value`: 指定加载类型为维度值
- `--clean`: 清空 Collection 后重建（可选）
- `--config` / `-c`: 指定 loader_config.yaml 路径（可选）
- `--debug`: 启用调试日志（可选）

**示例：**
```bash
# 增量加载（追加数据）
python -m src.metaweave.cli.main load --type dim_value

# 清空重建（删除旧数据）
python -m src.metaweave.cli.main load --type dim_value --clean

# 使用自定义配置
python -m src.metaweave.cli.main load --type dim_value \
  --config configs/my_loader_config.yaml \
  --debug
```

## 7. 错误处理与日志

### 7.1 异常处理

**主要异常类型：**
- `ConfigurationError`: 配置错误（缺少必填项、格式错误）
- `ConnectionError`: 连接失败（PostgreSQL / Milvus / Embedding）
- `DataValidationError`: 数据验证失败（空值、超长文本）
- `EmbeddingError`: 向量化失败（API 限流、超时）

**处理策略：**
- 配置阶段错误：立即终止，输出详细错误信息
- 连接错误：重试 3 次，间隔 2 秒
- 数据错误：跳过当前记录，记录警告日志
- Embedding 错误：重试 2 次，失败则跳过当前批次

### 7.2 日志设计

**日志级别：**
- `INFO`: 流程关键节点（开始/完成、表切换）
- `WARNING`: 跳过的记录（空值、超长文本、向量化失败）
- `ERROR`: 致命错误（连接失败、配置错误）
- `DEBUG`: 详细执行信息（SQL 语句、Milvus 调用）

**日志示例：**
```
INFO  | 开始加载维度值到 Milvus
INFO  | 读取配置: dim_tables.yaml (4 个维表)
INFO  | 连接 PostgreSQL: localhost:5432/your_database
INFO  | 连接 Milvus: localhost:19530/nl2sql
INFO  | 确保 Collection 存在: dim_value_embeddings
INFO  | [1/4] 加载表: public.dim_company (列: company_name)
INFO  |   - 读取 3 条记录
INFO  |   - 向量化完成 (batch_size=100)
INFO  |   - 插入 Milvus 成功: 3 条
INFO  | [2/4] 加载表: public.dim_product_type (列: product_type_name)
WARN  |   - 跳过空值: 2 条
INFO  |   - 读取 4 条记录
INFO  |   - 向量化完成
INFO  |   - 插入 Milvus 成功: 4 条
INFO  | 加载完成: 总计 4 表 / 7 条记录 / 2 条跳过 / 耗时 5.2s
```

## 8. 测试策略

### 8.1 单元测试

**测试文件：** `tests/unit/metaweave/dim_value/`

**测试覆盖：**
- `test_config_generator.py`: 配置文件生成逻辑
- `test_dim_value_loader.py`: 加载器核心逻辑
- `test_milvus_client.py`: Milvus 客户端（Mock）
- `test_models.py`: 数据模型解析

**测试用例示例：**
```python
def test_config_generator_scan_dim_tables():
    """测试扫描 dim 表功能"""
    generator = DimTableConfigGenerator(
        json_llm_dir=Path("tests/fixtures/json_llm"),
        output_path=Path("tests/output/dim_tables.yaml")
    )
    dim_tables = generator._scan_dim_tables()

    assert len(dim_tables) == 4
    assert ("public", "dim_company") in dim_tables

def test_config_generator_generate():
    """测试生成配置文件"""
    generator = DimTableConfigGenerator(
        json_llm_dir=Path("tests/fixtures/json_llm"),
        output_path=Path("tests/output/dim_tables.yaml")
    )
    config = generator.generate()

    # 验证生成的配置结构
    assert "tables" in config
    assert "public.dim_company" in config["tables"]
    # embedding_col 应该为 null（待人工填写）
    assert config["tables"]["public.dim_company"]["embedding_col"] is None

def test_dim_value_loader_clean_mode():
    """测试清空重建模式"""
    loader = DimValueLoader(mock_config)
    result = loader.load(clean=True)

    assert result["success"] is True
    assert result["records_loaded"] > 0
```

### 8.2 集成测试

**测试文件：** `tests/integration/metaweave/test_dim_value_loader.py`

**测试场景：**
- 端到端加载流程（PostgreSQL -> Milvus）
- 清空重建模式
- 增量加载模式（预留）
- 错误恢复（连接失败、向量化失败）

**测试环境准备：**
- 使用 Docker Compose 启动 Milvus Standalone
- 使用测试数据库（独立于生产环境）
- Mock Embedding 服务（避免 API 费用）

## 9. 实施步骤

**开发流程：** 按照以下步骤一次性完成所有功能开发。

### 步骤 1: 配置文件扩展（预计 0.5 小时）

**⚠️ 关键前置步骤：必须先完成配置文件修改，否则无法运行！**

1. **扩展 metadata_config.yaml**
   - 在第 205 行后添加 `vector_database` 配置段（参考第 2.1 节）
   - 确保 `active: milvus`（当前仅支持 Milvus）
   - 配置 Milvus 连接参数（host, port, database）
   - 更新 `.env.example` 添加 Milvus 环境变量
   - 验证 YAML 语法正确性（使用 yamllint 或 Python yaml.safe_load）

### 步骤 2: 基础框架实现（预计 2-3 小时）

1. **实现 MilvusClient**
   - 连接管理（connect, test_connection, close）
   - Collection 管理（ensure_collection, drop_collection）
   - 数据插入（insert_batch）
   - 获取统计信息（get_collection_stats）

2. **实现 DimValueLoader 框架**
   - 实现 `_get_vector_db_config()` 方法（严格检测模式）
   - 验证 vector_database 配置存在且 active='milvus'
   - 实现 validate() 和 load() 框架方法

3. **注册到 LoaderFactory**
   - 修改 factory.py 注册 DimValueLoader
   - 添加 "dim_value" 类型支持

### 步骤 3: 配置生成器实现（预计 1 小时）

1. **实现 DimTableConfigGenerator**
   - `_scan_dim_tables()` - 扫描 json_llm 目录，过滤 dim 表
   - `generate()` - 生成配置字典（embedding_col=null）
   - `_write_yaml()` - 格式化输出 YAML（带注释）

2. **实现 dim_config CLI 命令**
   - 在 cli/main.py 添加 dim_config 命令
   - 实现参数解析和调用逻辑

3. **单元测试**
   - test_config_generator.py

### 步骤 4: 数据加载器核心逻辑（预计 3-4 小时）

1. **实现 DimValueLoader 核心方法**
   - `_fetch_table_data()` - 从 PostgreSQL 读取数据
   - `_batch_embed_and_insert()` - 批量向量化和插入
   - `_ensure_collection()` - 确保 Collection 存在
   - `_load_table()` - 加载单个维表

2. **实现批量向量化逻辑**
   - 调用 Embedding 服务
   - 错误重试和降级

3. **实现数据清洗逻辑**
   - 空值过滤
   - 超长文本截断
   - 去重

4. **单元测试**
   - test_dim_value_loader.py
   - test_milvus_client.py

### 步骤 5: 集成测试与调试（预计 2 小时）

1. **准备测试环境**
   - 使用 Docker Compose 启动 Milvus
   - 准备测试数据库

2. **端到端集成测试**
   - 配置生成 → 数据加载 → 验证结果
   - 测试清空重建模式
   - 测试错误处理

3. **性能优化**
   - 批量大小调优（batch_size）
   - 连接池参数调优

4. **错误处理完善**
   - 完善日志输出
   - 完善错误提示

### 步骤 6: 文档与收尾（预计 1 小时）

1. **更新文档**
   - 更新 README（新增 CLI 命令说明）
   - 编写用户手册（配置指南）

2. **代码 Review**
   - 代码风格检查
   - 安全性检查

3. **完成开发**

**总计：预计 9-12 小时**

## 10. 后续扩展

### 10.1 PgVector 支持
- 实现 PgVectorClient（类似 MilvusClient 接口）
- 修改 DimValueLoader，支持动态切换向量数据库
- 更新配置文件和文档

### 10.2 增量更新
- 新增 `--incremental` 参数
- 基于 `update_ts` 字段判断是否需要更新
- 实现 Upsert 逻辑（Milvus 2.3+ 支持）

### 10.3 多列向量化
- 支持一个表配置多个 embedding 列
- 配置格式扩展：`embedding_cols: [col1, col2]`
- 插入时生成多条记录

### 10.4 向量检索 API
- 新增 `dim_value_search.py` 模块
- 实现语义搜索功能（根据文本查询相似维度值）
- 用于 SQL 生成阶段的维度值匹配

## 11. 风险与注意事项

### 11.1 性能风险
- **问题：** 大表（百万级记录）加载时间过长
- **缓解：**
  - 使用 `max_records_per_table` 限制加载数量
  - 优化批量大小（batch_size=100）
  - 异步向量化（预留）

### 11.2 数据质量风险
- **问题：** 维表数据包含噪声（重复值、异常值）
- **缓解：**
  - 数据清洗逻辑（去重、截断）
  - 人工审核机制：dim_tables.yaml 由人工选择合适的列进行向量化
  - 加载前验证：检查 embedding_col 是否为 null，如果为 null 则跳过该表并警告

### 11.3 向量模型依赖
- **问题：** Embedding 服务不可用或限流
- **缓解：**
  - 重试机制（retry_times=2）
  - 降级策略（跳过失败批次）
  - 监控和告警

### 11.4 配置复杂度
- **问题：** 配置文件较多（3 个），容易混淆
- **缓解：**
  - 提供详细注释和示例
  - 实现配置验证器（validate_config 方法）
  - 编写用户手册
  - 默认使用全局配置（`use_global_config=true`），减少配置项

### 11.5 配置简化与一致性（已解决）
- **原问题：** `loader_config.yaml` 和 `metadata_config.yaml` 配置可能冲突
- **解决方案：**
  - Phase 1 删除 `dim_loader.vector_db` 配置段
  - 固定使用全局配置，不支持本地覆盖
  - 单一配置源，避免不一致问题
  - 日志输出：`INFO | 使用向量数据库: Milvus (来源: metadata_config.yaml)`

### 11.6 新增配置段缺失风险（高优先级）
- **问题：** `metadata_config.yaml` 缺少 `vector_database` 配置段导致运行时直接失败
- **缓解：**
  - **【关键】开发第一步：添加配置段，作为强制前置步骤**
  - 配置落地检查清单：
    - ✅ 配置段已添加到 metadata_config.yaml
    - ✅ `active: milvus`（不是 pgvector）
    - ✅ Milvus 连接参数已配置
    - ✅ YAML 语法验证通过
  - 在 `_get_vector_db_config()` 中实现严格检测
  - 错误提示示例：
    ```
    ❌ ConfigurationError: metadata_config.yaml 缺少 'vector_database' 配置段
    📖 请参考文档添加配置: docs/gen_rag/57_dim_value加载到向量数据库的概要设计.md (第 2.1 节)

    ❌ ConfigurationError: 当前版本仅支持 Milvus，但配置为: pgvector
    📖 请修改配置: vector_database.active = 'milvus'
    ```
  - 单元测试覆盖配置缺失和配置错误场景

### 11.7 过早引入 PgVector 复杂度风险
- **问题：** 实现降级逻辑和 PgVector 分支会增加复杂度和歧义
- **缓解：**
  - **【简化】当前版本仅实现 Milvus，不实现降级逻辑**
  - 配置验证时直接拒绝 active != 'milvus'
  - PgVector 仅在设计文档中预留接口，不实现代码
  - 待需求明确后再实现 PgVector 支持
  - 减少测试分支和维护成本

## 12. 总结

本设计方案完整实现了维度值加载到向量数据库的功能，具备以下特点：

✅ **模块化设计：** 各模块职责清晰，易于测试和维护
✅ **配置明确：** 严格检测模式，无降级歧义，当前仅支持 Milvus
✅ **可扩展性：** 预留 PgVector 接口，待需求明确后扩展
✅ **生产就绪：** 完善的错误处理、日志和测试策略
✅ **性能优化：** 批量处理、数据清洗、可配置参数

**开发实施重点：**
1. **【必须】首先完成配置文件追加**（metadata_config.yaml）
2. 采用严格检测模式，仅支持 Milvus，无降级逻辑
3. 配置验证失败时立即终止并提示文档
4. 完整的错误提示和日志输出
5. 按照实施步骤一次性完成所有功能开发

**下一步：** 开始开发，**首先完成配置文件修改**，然后按步骤实施。
