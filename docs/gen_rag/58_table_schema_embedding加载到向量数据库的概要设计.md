# 58_table_schema_embedding 加载到向量数据库的概要设计

## 1. 需求概述

将表结构（schema）信息加载到 Milvus 向量数据库，用于 NL2SQL 场景中的表和字段语义检索。与 57 号需求（dim_value）配套，共同构建完整的元数据检索体系。

**核心目标：**
- 从 Markdown 文件读取表和字段的完整描述
- 从 JSON_LLM 文件提取表分类和时间列信息
  - **时间列识别**：使用关键词匹配（大小写不敏感），覆盖主流数据库的所有时间类型变体（如 `timestamp without time zone`、`datetime2`、`smalldatetime` 等）
- 将表和字段信息向量化后存储到 Milvus 的 `table_schema_embedding` Collection
- 支持清空重建和增量更新两种模式（使用 upsert 避免重复数据）

**与 57 号需求的关系：**
- 57 号：加载维度表的**值**（如 "上海"、"华东"）用于值匹配

- 58 号：加载表和字段的**结构描述**（如表定义、字段注释）用于 schema 检索

  注意，本文档只涉及对58号需求的设计。

---

## 2. 配置设计

### 2.1 复用现有配置

**尽量复用 `metadata_config.yaml` 的配置：**

- ✅ `vector_database` - Milvus 连接配置
- ✅ `embedding` - Embedding 模型配置

### 2.2 loader_config.yaml 扩展

在 `loader_config.yaml` 中新增 `table_schema_loader` 配置段：

```yaml
# 表结构加载器配置
table_schema_loader:
  # 输入目录配置（相对于项目根目录）
  md_directory: "output/metaweave/metadata/md"          # Markdown 文件目录
  json_llm_directory: "output/metaweave/metadata/json_llm"  # JSON_LLM 文件目录

  # 加载选项（可选，未配置时使用默认值）
  options:
    batch_size: 50              # 批量向量化大小（默认 50）
    # max_tables: 0             # 最多加载表数（0=不限制，用于测试）
    # include_columns: true     # 是否加载列信息（默认 true）
    # skip_empty_desc: true     # 跳过无描述的对象（默认 true）
```

**设计说明：**
- 配置结构与 57 号保持一致，易于理解
- 所有 `options` 字段均为可选，未配置时使用代码默认值
- 向量数据库和 Embedding 配置复用全局配置
- `table_schema_loader` 模块只从上述配置文件中读取 md_directory 和 json_llm_directory 的配置。

---

## 3. 模块结构设计

### 3.1 新增模块

```
src/metaweave/
├── core/
│   ├── loaders/
│   │   ├── base.py                       # 已存在：加载器基类
│   │   ├── factory.py                    # 已存在：加载器工厂
│   │   ├── dim_value_loader.py           # 已存在：维度值加载器
│   │   └── table_schema_loader.py        # 新增：表结构加载器
│   │
│   └── table_schema/                      # 新增：表结构子模块
│       ├── __init__.py
│       ├── models.py                      # 数据模型
│       ├── md_parser.py                   # Markdown 解析器
│       └── json_extractor.py              # JSON_LLM 信息提取器
│
└── cli/
    └── loader_cli.py                      # 已存在：加载CLI（需注册新加载器）
```

**复用模块：**
- `EmbeddingService`（已存在）- 用于生成 embedding 向量
- `MilvusClient`（已存在，需扩展）- 新增 `upsert_batch()` 方法支持增量更新

### 3.2 核心类设计

#### 3.2.1 TableSchemaLoader (table_schema_loader.py)

```python
class TableSchemaLoader(BaseLoader):
    """表结构加载器

    从 Markdown 和 JSON_LLM 文件读取表结构信息，
    调用 Embedding 模型向量化后，加载到 Milvus 的 table_schema_embedding Collection。

    配置策略：复用 metadata_config.yaml 的 vector_database 和 embedding 配置
    """

    COLLECTION_NAME = "table_schema_embedding"

    def __init__(self, config: Dict[str, Any]):
        """初始化加载器

        Args:
            config: 完整配置字典（包含 table_schema_loader、metadata_config）
        """
        pass

    def validate(self) -> bool:
        """验证配置和数据源

        检查：
        - md_directory 是否存在
        - json_llm_directory 是否存在
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

    def _load_table_objects(self) -> List[Dict[str, Any]]:
        """加载所有表对象（table + columns）

        Returns:
            List[Dict]: 待插入的对象列表
                [
                    {
                        "object_type": "table",
                        "object_id": "public.dim_company",
                        "parent_id": "public.dim_company",
                        "object_desc": "表的完整描述...",
                        "time_col_hint": "created_at,updated_at",
                        "table_category": "dim",
                        "updated_at": 1702345678
                    },
                    {
                        "object_type": "column",
                        "object_id": "public.dim_company.company_name",
                        "parent_id": "public.dim_company",
                        "object_desc": "公司名称，主键",
                        "time_col_hint": None,
                        "table_category": None,
                        "updated_at": 1702345678
                    },
                    ...
                ]
        """
        pass

    def _parse_table_from_md(self, md_file: Path, json_data: Dict) -> Dict[str, Any]:
        """从 MD 文件解析表对象

        Args:
            md_file: Markdown 文件路径
            json_data: 对应的 JSON_LLM 数据

        Returns:
            Dict: 表对象字典
        """
        pass

    def _parse_columns_from_md(self, md_file: Path, table_name: str) -> List[Dict[str, Any]]:
        """从 MD 文件解析列对象

        Args:
            md_file: Markdown 文件路径
            table_name: 表名（schema.table）

        Returns:
            List[Dict]: 列对象列表
        """
        pass

    def _batch_embed_and_upsert(self, objects: List[Dict[str, Any]]):
        """批量向量化并插入/更新 Milvus

        根据 clean 参数决定使用 insert 还是 upsert：
        - clean=True: 使用 insert（Collection 已清空）
        - clean=False: 使用 upsert（避免重复数据）
        """
        pass
```

#### 3.2.2 MDParser (md_parser.py)

```python
import re
from pathlib import Path
from typing import Dict

class MDParser:
    """Markdown 文件解析器

    从 MetaWeave 生成的 Markdown 文件中提取：
    - 表的完整描述（整个文件内容）
    - 每个字段的描述（字段注释部分）

    MetaWeave 生成的 MD 文件格式：
    ```markdown
    # schema.table_name（表中文说明）
    ## 字段列表：
    - col_name (data_type) - 列注释 [示例: val1, val2]
    - col_name (data_type) - 列注释 [示例: val1, val2]
    ...
    ## 字段补充说明：
    - col_name 补充说明
    ...
```

    实际示例：
    ```markdown
    # public.dim_company（公司维表）
    ## 字段列表：
    - company_id (integer(32)) - 公司ID（主键） [示例: 1, 2]
    - company_name (character varying(200)) - 公司名称，唯一 [示例: 京东便利, 喜士多]
    ```
    """
    
    def __init__(self, md_file: Path):
        """初始化解析器
    
        Args:
            md_file: Markdown 文件路径
        """
        pass
    
    def get_table_description(self) -> str:
        """获取表的完整描述（整个 MD 文件内容）
    
        Returns:
            str: 表描述文本（包括所有章节）
    
        实现策略：
            直接读取整个 MD 文件内容，无需解析分段
        """
        pass
    
    def get_column_descriptions(self) -> Dict[str, str]:
        """获取所有列的描述
    
        Returns:
            Dict[str, str]: {列名: 列描述}
                如: {"company_id": "公司ID（主键）", "company_name": "公司名称，唯一"}
    
        解析规则：
            1. 定位 "## 字段列表：" 章节
            2. 逐行解析字段行，格式：`- col_name (data_type) - 注释 [示例: ...]`
            3. 使用正则表达式提取列名和注释：
               ```python
               COLUMN_PATTERN = re.compile(
                   r'^-\s+(\w+)\s+\([^)]+\)\s+-\s+(.+?)(?:\s+\[示例:.*)?$'
               )
               ```
            4. 返回字典 {列名: 注释}，注释部分不包括 [示例: ...] 部分
    
        边界情况处理：
            - 列注释可能包含括号、逗号等特殊字符
            - [示例: ...] 部分可能不存在
            - 遇到 "## 字段补充说明：" 或其他章节时停止解析
            - 跳过空行和非字段行
    
        实现示例：
            ```python
            import re
    
            COLUMN_PATTERN = re.compile(
                r'^-\s+(\w+)\s+\([^)]+\)\s+-\s+(.+?)(?:\s+\[示例:.*)?$'
            )
    
            column_descriptions = {}
            in_field_section = False
    
            for line in md_lines:
                line = line.strip()
    
                # 进入字段列表章节
                if line.startswith("## 字段列表"):
                    in_field_section = True
                    continue
    
                # 退出字段列表章节（遇到其他章节）
                if in_field_section and line.startswith("##"):
                    break
    
                # 解析字段行
                if in_field_section and line.startswith("-"):
                    match = COLUMN_PATTERN.match(line)
                    if match:
                        col_name = match.group(1)
                        col_desc = match.group(2).strip()
                        column_descriptions[col_name] = col_desc
                    else:
                        logger.warning("无法解析字段行: %s", line)
    
            return column_descriptions
            ```
        """
        pass
    
    def extract_table_name(self) -> str:
        """从 MD 文件中提取表名
    
        Returns:
            str: 表名（schema.table）
    
        解析规则：
            从第一行标题提取：`# schema.table_name（表说明）`
            使用正则表达式：`^#\s+([\w.]+)`
    
        实现示例：
            ```python
            import re
    
            TABLE_NAME_PATTERN = re.compile(r'^#\s+([\w.]+)')
    
            first_line = md_lines[0].strip()
            match = TABLE_NAME_PATTERN.match(first_line)
            if match:
                return match.group(1)  # 返回 "schema.table"
            else:
                raise ValueError(f"无法从 MD 第一行提取表名: {first_line}")
            ```
        """
        pass
```

#### 3.2.3 JSONExtractor (json_extractor.py)

```python
class JSONExtractor:
    """JSON_LLM 信息提取器

    从 JSON_LLM 文件中提取：
    - table_category: 表分类（dim/fact/bridge）
    - time_col_hint: 时间列列表
    """

    def __init__(self, json_file: Path):
        """初始化提取器

        Args:
            json_file: JSON_LLM 文件路径
        """
        pass

    def get_table_category(self) -> Optional[str]:
        """获取表分类

        Returns:
            Optional[str]: dim/fact/bridge/None
                从 table_profile.table_category 读取
        """
        pass

    def get_time_columns(self) -> List[str]:
        """获取时间列列表

        Returns:
            List[str]: 时间列名列表
                遍历 column_profiles，筛选 data_type 为时间类型的列

        识别规则：
            1. 大小写不敏感（统一转小写比较）
            2. 使用部分匹配（关键词包含匹配）
            3. 支持的时间类型关键词：
               - date（含 "date"）
               - time（含 "time"，但排除 "datetime" 已匹配的情况）
               - datetime（含 "datetime"）
               - timestamp（含 "timestamp"）
               - timestamptz（含 "timestamptz"）
               - interval（含 "interval"）
               - year（含 "year"）

        覆盖的常见类型变体：
            PostgreSQL:
                - DATE
                - TIME, TIME WITHOUT TIME ZONE, TIME WITH TIME ZONE
                - TIMESTAMP, TIMESTAMP WITHOUT TIME ZONE, TIMESTAMP WITH TIME ZONE
                - TIMESTAMPTZ（timestamp with time zone 的别名）
                - INTERVAL
            MySQL:
                - DATE, TIME, DATETIME, TIMESTAMP, YEAR
            SQL Server:
                - DATE, TIME, DATETIME, DATETIME2, SMALLDATETIME, DATETIMEOFFSET
            Oracle:
                - DATE, TIMESTAMP, TIMESTAMP WITH TIME ZONE, TIMESTAMP WITH LOCAL TIME ZONE
                - INTERVAL YEAR TO MONTH, INTERVAL DAY TO SECOND

        实现示例：
            ```python
            import logging
            logger = logging.getLogger(__name__)

            TIME_TYPE_KEYWORDS = [
                "date", "time", "datetime", "timestamp",
                "timestamptz", "interval", "year"
            ]

            time_cols = []
            for col_name, col_profile in self.json_data.get("column_profiles", {}).items():
                data_type = col_profile.get("data_type", "").lower().strip()

                # 包含匹配（大小写不敏感）
                if any(keyword in data_type for keyword in TIME_TYPE_KEYWORDS):
                    time_cols.append(col_name)
                    logger.debug("识别为时间列: %s (data_type: %s)", col_name, data_type)

                # ⚠️ 记录可疑的未识别类型（包含 date/time 但未匹配）
                elif any(suspicious in data_type for suspicious in ["date", "time"]):
                    logger.warning(
                        "可疑的未识别时间类型: 列=%s, data_type=%s（请检查是否需要补充关键词）",
                        col_name, data_type
                    )

            return time_cols
```
        """
        pass
    
    def format_time_col_hint(self) -> Optional[str]:
        """格式化时间列提示（逗号分隔）
    
        Returns:
            Optional[str]: "created_at,updated_at" 或 None
        """
        pass
```

#### 3.2.4 MilvusClient 扩展 (vector_db/milvus_client.py)

**需新增方法：**

```python
def upsert_batch(
    self,
    collection_name: str,
    data: List[Dict[str, Any]],
) -> int:
    """批量 Upsert 数据到 Milvus Collection

    Args:
        collection_name: Collection 名称
        data: 数据列表，每个字典必须包含主键字段

    Returns:
        int: 成功 upsert 的记录数

    注意:
        - 要求 Milvus 版本 >= 2.2
        - 主键必须由用户提供（auto_id=False）
        - 如果主键已存在，会覆盖原有数据
    """
    *_, Collection, _, _ = _lazy_import_milvus()
    if not data:
        return 0

    collection = Collection(collection_name, using=self.alias)

    # 将字典列表转换为列式数据（与 insert_batch 类似）
    # 获取所有字段名
    fields = list(data[0].keys())
    columns: Dict[str, List[Any]] = {f: [] for f in fields}
    for row in data:
        for f in fields:
            columns[f].append(row[f])

    entities = [columns[f] for f in fields]

    # 使用 upsert 而非 insert
    mr = collection.upsert(entities)
    collection.flush()
    return len(mr.primary_keys) if mr and getattr(mr, "primary_keys", None) else len(data)
```

---

## 4. 核心流程设计

### 4.1 数据加载流程

```
用户执行：
  python -m src.metaweave.cli.main load --type table_schema --clean

流程：
  1. 加载配置文件
     ├─ loader_config.yaml (table_schema_loader 配置)
     ├─ metadata_config.yaml (vector_database + embedding 配置)
     └─ 验证目录存在性

  2. 初始化依赖服务
     ├─ Milvus 连接 (MilvusClient)
     └─ Embedding 服务 (复用 EmbeddingService)

  3. 验证阶段 (validate)
     ├─ 检查 md_directory 是否存在
     ├─ 检查 json_llm_directory 是否存在
     ├─ 测试 Milvus 连接
     └─ 测试 Embedding 服务

  4. 确保 Collection 存在
     ├─ 如果 clean=True: 删除现有 Collection
     ├─ 如果不存在: 创建 Collection + 定义 Schema
     └─ 创建向量索引 (HNSW + COSINE)

  5. 加载数据（逐表处理）
     对每个表：
       ├─ 读取 MD 文件（public.table.md）
       │  ├─ 提取表的完整描述
       │  └─ 提取每个列的描述
       │
       ├─ 读取对应的 JSON_LLM 文件
       │  ├─ 提取 table_category
       │  └─ 提取时间列列表
       │
       ├─ 构造 Table 对象
       │  ├─ object_type = "table"
       │  ├─ object_id = "schema.table"
       │  ├─ parent_id = "schema.table"
       │  ├─ object_desc = MD 文件全文
       │  ├─ time_col_hint = "col1,col2"
       │  ├─ table_category = "dim"
       │  └─ updated_at = 当前时间戳
       │
       ├─ 构造 Column 对象列表
       │  对每个列：
       │    ├─ object_type = "column"
       │    ├─ object_id = "schema.table.column"
       │    ├─ parent_id = "schema.table"
       │    ├─ object_desc = 列注释
       │    ├─ time_col_hint = None
       │    ├─ table_category = None
       │    └─ updated_at = 当前时间戳
       │
       ├─ 批量向量化（batch_size=50）
       │  - 调用 Embedding 服务（text-embedding-v3）
       │  - 生成 1024 维向量
       │
       └─ 批量插入 Milvus
          - 插入 1 个 Table 对象 + N 个 Column 对象

  6. 输出统计信息
     ├─ 总表数
     ├─ 总对象数（Table + Column）
     ├─ 跳过对象数
     └─ 执行时间
```

### 4.2 流程图

```
┌─────────────────┐
│ 读取配置文件     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 初始化依赖服务   │
│ - Milvus        │
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
│ 遍历 MD 文件                   │
└───────────┬────────────────────┘
            │
            ▼
      ┌─────────┐
      │ 读取 MD  │
      │ + JSON  │
      └────┬─────┘
           │
           ▼
      ┌─────────┐
      │ 构造对象 │
      │ Table+  │
      │ Columns │
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

---

## 5. 数据模型设计

### 5.1 Milvus Collection Schema

**Collection 名称：** `table_schema_embedding`

**字段定义：**

| 字段名 | Milvus 类型 | PostgreSQL 等价类型 | 说明 | 约束 |
|--------|------------|-------------------|------|------|
| object_id | VARCHAR(256) | VARCHAR(256) | 对象完整标识符 | **PRIMARY KEY**, 格式: schema.table 或 schema.table.column |
| object_type | VARCHAR(64) | VARCHAR(64) | 对象类型 | NOT NULL, 可选值: "table"/"column" |
| parent_id | VARCHAR(256) | VARCHAR(256) | 父对象标识符 | NOT NULL, 始终为表名 |
| object_desc | VARCHAR(8192) | TEXT | 对象描述文本 | NOT NULL, 表描述或列注释 |
| embedding | FLOAT_VECTOR(动态) | - | 向量，维度从配置读取 | NOT NULL, 维度必须与 embedding 模型一致 |
| time_col_hint | VARCHAR(512) | TEXT | 时间列提示 | NULLABLE, 仅 Table 对象有值 |
| table_category | VARCHAR(64) | VARCHAR(64) | 表分类 | NULLABLE, 仅 Table 对象有值 |
| updated_at | INT64 | TIMESTAMP | 更新时间戳（Unix秒） | NOT NULL |

**索引定义：**
```python
from pymilvus import FieldSchema, CollectionSchema, DataType

# ⚠️ 重要：向量维度必须从配置文件动态读取
# 从 metadata_config.yaml 的 embedding.providers.{active}.dimensions 读取
embedding_dimensions = metadata_config["embedding"]["providers"]["qwen"]["dimensions"]  # 例如 1024

index_params = {
    "index_type": "HNSW",
    "metric_type": "COSINE",
    "params": {
        "M": 16,
        "efConstruction": 200  # 与 57 号保持一致
    }
}

# Schema 定义
fields = [
    FieldSchema(
        name="object_id",
        dtype=DataType.VARCHAR,
        max_length=256,
        is_primary=True,  # ⚠️ 使用 object_id 作为主键，支持 upsert
        auto_id=False
    ),
    FieldSchema(
        name="object_type",
        dtype=DataType.VARCHAR,
        max_length=64
    ),
    FieldSchema(
        name="parent_id",
        dtype=DataType.VARCHAR,
        max_length=256
    ),
    FieldSchema(
        name="object_desc",
        dtype=DataType.VARCHAR,
        max_length=8192  # 表描述可能较长
    ),
    FieldSchema(
        name="embedding",
        dtype=DataType.FLOAT_VECTOR,
        dim=embedding_dimensions  # ⚠️ 动态读取，不要硬编码！
    ),
    FieldSchema(
        name="time_col_hint",
        dtype=DataType.VARCHAR,
        max_length=512
    ),
    FieldSchema(
        name="table_category",
        dtype=DataType.VARCHAR,
        max_length=64
    ),
    FieldSchema(
        name="updated_at",
        dtype=DataType.INT64
    )
]

schema = CollectionSchema(
    fields=fields,
    description="Table and column schema embeddings for NL2SQL"
)
```

**设计说明：**
- ⚠️ **向量维度必须动态读取**：从 `metadata_config.yaml` 的 `embedding.providers.{active}.dimensions` 读取，不要硬编码
- ⚠️ **索引参数与 57 号保持一致**：HNSW + COSINE，M=16，efConstruction=200，确保运维一致性和配置简化
- ⚠️ **主键使用 object_id（非 auto_id）**：支持 Milvus 2.2+ 的 upsert 功能，增量模式（clean=False）时自动覆盖同名对象，避免重复数据
- `object_id` 作为主键具有唯一性：表对象为 `schema.table`，列对象为 `schema.table.column`
- `object_desc` 长度限制 8192 字符，足以容纳完整表描述
- `time_col_hint` 使用逗号分隔多个时间列：`"created_at,updated_at,order_date"`
- `table_category` 支持：`dim`, `fact`, `bridge`, `other`
- `updated_at` 使用 Unix 时间戳（秒），便于比较和过滤

### 5.2 数据示例

#### Table 对象示例

```python
{
    "object_type": "table",
    "object_id": "public.fact_store_sales_day",
    "parent_id": "public.fact_store_sales_day",
    "object_desc": """# public.fact_store_sales_day

## 表说明
门店日销售额事实表，记录每个门店每天的销售情况...

## 字段列表
| 字段名 | 类型 | 说明 |
|--------|------|------|
| store_id | INTEGER | 门店ID |
| sale_date | DATE | 销售日期 |
| amount | NUMERIC(12,2) | 销售金额 |
...""",
    "embedding": [0.123, 0.456, ...],  # 1024维向量
    "time_col_hint": "sale_date,created_at",
    "table_category": "fact",
    "updated_at": 1702345678
}
```

#### Column 对象示例

```python
{
    "object_type": "column",
    "object_id": "public.fact_store_sales_day.amount",
    "parent_id": "public.fact_store_sales_day",
    "object_desc": "销售金额，单位：元，保留2位小数",
    "embedding": [0.789, 0.012, ...],  # 1024维向量
    "time_col_hint": None,
    "table_category": None,
    "updated_at": 1702345678
}
```

### 5.3 Python 数据模型

```python
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

class ObjectType(str, Enum):
    """对象类型枚举"""
    TABLE = "table"
    COLUMN = "column"

class TableCategory(str, Enum):
    """表分类枚举"""
    DIM = "dim"
    FACT = "fact"
    BRIDGE = "bridge"
    OTHER = "other"

@dataclass
class SchemaObject:
    """Schema 对象（Table 或 Column）"""
    object_type: ObjectType
    object_id: str
    parent_id: str
    object_desc: str
    time_col_hint: Optional[str] = None
    table_category: Optional[str] = None
    updated_at: int = 0  # Unix 时间戳

    def to_milvus_dict(self) -> dict:
        """转换为 Milvus 插入格式"""
        return {
            "object_type": self.object_type.value,
            "object_id": self.object_id,
            "parent_id": self.parent_id,
            "object_desc": self.object_desc,
            "time_col_hint": self.time_col_hint or "",
            "table_category": self.table_category or "",
            "updated_at": self.updated_at
        }

@dataclass
class LoaderOptions:
    """加载器选项配置"""
    batch_size: int = 50
    max_tables: int = 0  # 0 = 不限制
    include_columns: bool = True
    skip_empty_desc: bool = True

    @classmethod
    def from_dict(cls, options: dict) -> 'LoaderOptions':
        """从配置字典创建"""
        return cls(
            batch_size=options.get('batch_size', 50),
            max_tables=options.get('max_tables', 0),
            include_columns=options.get('include_columns', True),
            skip_empty_desc=options.get('skip_empty_desc', True)
        )
```

---

## 6. CLI 命令设计

### 6.1 加载数据命令

**已存在命令：** `load --type table_schema`

```bash
python -m src.metaweave.cli.main load --type table_schema --clean
```

**参数：**
- `--type table_schema`: 指定加载类型为表结构
- `--clean`: 清空 Collection 后重建（可选）
- `--config` / `-c`: 指定 loader_config.yaml 路径（可选）
- `--debug`: 启用调试日志（可选）

**示例：**
```bash
# 增量加载（追加数据）
python -m src.metaweave.cli.main load --type table_schema

# 清空重建（删除旧数据）
python -m src.metaweave.cli.main load --type table_schema --clean

# 使用自定义配置
python -m src.metaweave.cli.main load --type table_schema \
  --config configs/my_loader_config.yaml \
  --debug
```

---

## 7. 错误处理与日志

### 7.1 异常处理

**主要异常类型：**
- `ConfigurationError`: 配置错误（缺少必填项、格式错误）
- `ConnectionError`: 连接失败（Milvus / Embedding）
- `FileNotFoundError`: 文件缺失（MD 或 JSON_LLM 文件）
- `ParseError`: 解析失败（MD 或 JSON 格式错误）
- `EmbeddingError`: 向量化失败（API 限流、超时）

**处理策略：**
- 配置阶段错误：立即终止，输出详细错误信息
- 连接错误：重试 3 次，间隔 2 秒
- 文件缺失：跳过当前表，记录警告日志
- 解析错误：跳过当前对象，记录警告日志
- Embedding 错误：重试 2 次，失败则跳过当前批次

### 7.2 日志设计

**日志级别：**
- `INFO`: 流程关键节点（开始/完成、表切换）
- `WARNING`: 跳过的对象（文件缺失、解析失败）
- `ERROR`: 致命错误（连接失败、配置错误）
- `DEBUG`: 详细执行信息（文件路径、对象内容）

**日志示例：**
```
INFO  | 开始加载表结构到 Milvus
INFO  | 读取配置: md_directory=output/metaweave/metadata/md (13 个文件)
INFO  | 读取配置: json_llm_directory=output/metaweave/metadata/json_llm
INFO  | 连接 Milvus: localhost:19530/nl2sql
INFO  | 确保 Collection 存在: table_schema_embedding
INFO  | [1/13] 加载表: public.dim_company
INFO  |   - 读取 MD 文件: public.dim_company.md
INFO  |   - 读取 JSON_LLM: public.dim_company.json
INFO  |   - 提取 table_category: dim
INFO  |   - 提取时间列: created_at,updated_at
INFO  |   - 构造对象: 1 个 Table + 5 个 Column
INFO  |   - 向量化完成 (6 个对象)
INFO  |   - 插入 Milvus 成功: 6 条
INFO  | [2/13] 加载表: public.fact_store_sales_day
WARN  |   - JSON_LLM 文件不存在，跳过 table_category 和 time_col_hint
INFO  |   - 构造对象: 1 个 Table + 8 个 Column
INFO  |   - 向量化完成 (9 个对象)
INFO  |   - 插入 Milvus 成功: 9 条
INFO  | 加载完成: 总计 13 表 / 156 个对象 / 0 条跳过 / 耗时 35.2s
```

---

## 8. 测试策略

### 8.1 单元测试

**测试文件：** `tests/unit/metaweave/table_schema/`

**测试覆盖：**
- `test_md_parser.py`: Markdown 解析逻辑
- `test_json_extractor.py`: JSON_LLM 信息提取
- `test_table_schema_loader.py`: 加载器核心逻辑
- `test_models.py`: 数据模型解析

**测试用例示例：**
```python
def test_md_parser_get_table_description():
    """测试提取表描述"""
    parser = MDParser(Path("tests/fixtures/md/public.dim_company.md"))
    desc = parser.get_table_description()

    assert "public.dim_company" in desc
    assert "公司维度表" in desc

def test_md_parser_get_column_descriptions():
    """测试提取列描述（标准格式）"""
    parser = MDParser(Path("tests/fixtures/md/public.dim_company.md"))
    columns = parser.get_column_descriptions()

    assert "company_id" in columns
    assert columns["company_id"] == "公司ID（主键）"
    assert "company_name" in columns
    assert columns["company_name"] == "公司名称，唯一"

def test_md_parser_column_descriptions_edge_cases():
    """测试列描述解析（边界情况）"""
    # 测试用例：各种复杂的列注释格式
    test_md = """# public.test_table（测试表）
## 字段列表：
- col1 (integer(32)) - 简单注释 [示例: 1, 2]
- col2 (varchar(100)) - 注释包含括号（说明）和逗号，还有其他符号 [示例: a, b]
- col3 (timestamp) - 时间戳字段
- col4 (numeric(18,2)) - 金额字段（精度18位） [示例: 100.50, 200.75]
## 字段补充说明：
- col4 使用高精度存储
"""
    parser = MDParser.from_string(test_md)
    columns = parser.get_column_descriptions()

    # 验证解析结果
    assert len(columns) == 4
    assert columns["col1"] == "简单注释"
    assert columns["col2"] == "注释包含括号（说明）和逗号，还有其他符号"
    assert columns["col3"] == "时间戳字段"
    assert columns["col4"] == "金额字段（精度18位）"

def test_md_parser_extract_table_name():
    """测试提取表名"""
    parser = MDParser(Path("tests/fixtures/md/public.dim_company.md"))
    table_name = parser.extract_table_name()

    assert table_name == "public.dim_company"

def test_md_parser_malformed_format():
    """测试解析失败场景（格式不符合预期）"""
    test_md = """# 错误格式的标题
- 没有字段列表章节的字段行
"""
    parser = MDParser.from_string(test_md)
    columns = parser.get_column_descriptions()

    # 应该返回空字典（未找到字段列表章节）
    assert len(columns) == 0

def test_json_extractor_get_time_columns():
    """测试提取时间列（标准类型）"""
    extractor = JSONExtractor(Path("tests/fixtures/json_llm/public.dim_company.json"))
    time_cols = extractor.get_time_columns()

    assert "created_at" in time_cols  # data_type: "timestamp"
    assert "updated_at" in time_cols  # data_type: "datetime"

def test_json_extractor_time_columns_variants():
    """测试时间列识别（覆盖各种类型变体）"""
    # 测试数据：包含各种时间类型变体
    test_cases = [
        ("DATE", True),
        ("date", True),
        ("TIMESTAMP WITHOUT TIME ZONE", True),
        ("timestamp with time zone", True),
        ("TIMESTAMPTZ", True),
        ("DATETIME", True),
        ("DATETIME2", True),
        ("SMALLDATETIME", True),
        ("TIME", True),
        ("TIME WITHOUT TIME ZONE", True),
        ("INTERVAL", True),
        ("YEAR", True),
        ("VARCHAR(50)", False),  # 非时间类型
        ("INTEGER", False),
        ("NUMERIC(12,2)", False),
    ]

    for data_type, expected_match in test_cases:
        # Mock JSON 数据
        json_data = {
            "column_profiles": {
                "test_col": {"data_type": data_type}
            }
        }
        extractor = JSONExtractor.from_dict(json_data)
        time_cols = extractor.get_time_columns()

        if expected_match:
            assert "test_col" in time_cols, f"应识别为时间列: {data_type}"
        else:
            assert "test_col" not in time_cols, f"不应识别为时间列: {data_type}"

def test_table_schema_loader_clean_mode():
    """测试清空重建模式"""
    loader = TableSchemaLoader(mock_config)
    result = loader.load(clean=True)

    assert result["success"] is True
    assert result["objects_loaded"] > 0
```

### 8.2 集成测试

**测试文件：** `tests/integration/metaweave/test_table_schema_loader.py`

**测试场景：**
- 端到端加载流程（MD + JSON_LLM -> Milvus）
- 清空重建模式
- 文件缺失处理
- 错误恢复（连接失败、向量化失败）

**测试环境准备：**
- 使用 Docker Compose 启动 Milvus Standalone
- 使用测试数据（独立于生产环境）
- Mock Embedding 服务（避免 API 费用）

---

## 9. 与 57 号需求的对比

| 维度 | 57 号（dim_value） | 58 号（table_schema） |
|------|-------------------|---------------------|
| **数据来源** | PostgreSQL 表数据 | MD + JSON_LLM 文件 |
| **Collection** | `dim_value_embeddings` | `table_schema_embedding` |
| **对象类型** | 单一类型（维度值） | 两种类型（Table + Column） |
| **主键设计** | auto_id=True（自增） | object_id 作为主键（支持 upsert） |
| **向量化内容** | 维度值文本（如 "上海"） | 表描述或列注释 |
| **索引参数** | HNSW + COSINE，M=16，efConstruction=200 | **相同**（与 57 保持一致） |
| **使用场景** | 值匹配（"上海" → `city_name = '上海'`） | Schema 检索（"销售表" → `fact_store_sales_day`） |
| **配置文件** | `dim_tables.yaml` | 无需额外配置，读取现有目录 |
| **复用模块** | - | 复用 EmbeddingService、MilvusClient（扩展 upsert_batch） |

---

## 10. 实施步骤

**开发流程：** 按照以下步骤一次性完成所有功能开发。

### 步骤 1: 基础框架实现（预计 2-3 小时）

1. **实现 TableSchemaLoader 框架**
   - 实现 validate() 和 load() 框架方法
   - 实现 `_ensure_collection()` - 复用 57 号的实现
   - 注册到 LoaderFactory

2. **实现 MDParser**
   - `get_table_description()` - 读取整个 MD 文件
   - `get_column_descriptions()` - 解析列描述
   - `extract_table_name()` - 从文件名或内容提取表名

3. **实现 JSONExtractor**
   - `get_table_category()` - 提取表分类
   - `get_time_columns()` - 筛选时间列
   - `format_time_col_hint()` - 格式化为逗号分隔

### 步骤 2: 核心逻辑实现（预计 3-4 小时）

1. **实现 TableSchemaLoader 核心方法**
   - `_load_table_objects()` - 遍历 MD 文件并构造对象
   - `_parse_table_from_md()` - 解析 Table 对象
   - `_parse_columns_from_md()` - 解析 Column 对象列表
   - `_batch_embed_and_upsert()` - 批量向量化和插入/更新（根据 clean 参数选择 insert 或 upsert）

2. **实现批量向量化逻辑**
   - 调用 Embedding 服务
   - 错误重试和降级

3. **实现数据清洗逻辑**
   - 跳过空描述
   - 文本长度截断

4. **单元测试**
   - test_md_parser.py
   - test_json_extractor.py
   - test_table_schema_loader.py

### 步骤 3: 集成测试与调试（预计 2 小时）

1. **准备测试环境**
   - 使用 Docker Compose 启动 Milvus
   - 准备测试数据（MD + JSON_LLM 文件）

2. **端到端集成测试**
   - MD 解析 → JSON 提取 → 向量化 → Milvus 插入
   - 测试清空重建模式
   - 测试错误处理

3. **性能优化**
   - 批量大小调优（batch_size）
   - 连接池参数调优

4. **错误处理完善**
   - 完善日志输出
   - 完善错误提示

### 步骤 4: 文档与收尾（预计 1 小时）

1. **更新文档**
   - 更新 README（新增 CLI 命令说明）
   - 编写用户手册（配置指南）

2. **代码 Review**
   - 代码风格检查
   - 安全性检查

3. **完成开发**

**总计：预计 8-10 小时**

---

## 11. 风险与注意事项

### 11.1 文本长度限制

- **问题：** 表描述可能超过 8192 字符限制
- **缓解：**
  - 监控并记录超长描述
  - 提供截断策略（保留前 8000 字符）
  - 记录警告日志

### 11.2 文件不匹配

- **问题：** MD 文件和 JSON_LLM 文件可能不完全匹配
- **缓解：**
  - JSON_LLM 缺失时，跳过 table_category 和 time_col_hint
  - MD 文件缺失时，跳过整个表
  - 记录警告日志，但不中断流程

### 11.3 Markdown 格式变化

- **问题：** MetaWeave 生成的 MD 格式可能调整，导致解析失败
- **当前格式假设：**
  ```markdown
  # schema.table_name（表中文说明）
  ## 字段列表：
  - col_name (data_type) - 列注释 [示例: val1, val2]
  ```
- **解析策略（已明确）：**
  - 表描述：直接读取整个 MD 文件内容
  - 列描述：定位 "## 字段列表：" 章节，使用正则表达式 `r'^-\s+(\w+)\s+\([^)]+\)\s+-\s+(.+?)(?:\s+\[示例:.*)?$'` 解析
  - 表名提取：从第一行标题提取，正则表达式 `r'^#\s+([\w.]+)'`
- **缓解措施：**
  1. **宽松匹配**：正则表达式允许空格变化、可选的示例部分
  2. **容错处理**：解析失败的字段行记录警告但不中断，跳过该字段
  3. **降级方案**：
     - 若列描述解析失败，返回空字典（表对象仍然创建）
     - 若表名提取失败，使用文件名作为表名
  4. **单元测试覆盖**：覆盖标准格式和边界情况（括号、逗号等特殊字符）
  5. **版本监控**：记录解析失败的 MD 文件路径和失败原因，定期人工审查

### 11.4 向量模型依赖

- **问题：** Embedding 服务不可用或限流
- **缓解：**
  - 重试机制（retry_times=2）
  - 降级策略（跳过失败批次）
  - 监控和告警

### 11.5 数据一致性

- **问题：** MD 和 JSON_LLM 可能版本不一致
- **缓解：**
  - 使用 updated_at 时间戳标记
  - 提供数据版本校验机制
  - 支持按表名重新加载

### 11.6 增量模式与 Upsert

- **设计方案：** 使用 `object_id` 作为主键（非 auto_id），支持 Milvus 2.2+ 的 upsert 功能
- **行为说明：**
  - `clean=True`：删除整个 Collection 并重建，适合首次加载或完全重建
  - `clean=False`：使用 upsert 插入数据，同名 object_id 会自动覆盖旧数据
- **实现要求：**
  - MilvusClient 需新增 `upsert_batch()` 方法（类似 `insert_batch()`）
  - TableSchemaLoader 在 clean=False 时调用 `upsert_batch()` 而非 `insert_batch()`
- **注意事项：**
  - 确保 Milvus 版本 >= 2.2（如果版本不支持 upsert，需使用删除后插入的方式模拟）
  - Upsert 性能略低于 Insert，但可避免重复数据问题

### 11.7 时间列识别漏检风险

- **问题：** JSON_LLM 中 `data_type` 为自由文本，可能包含未枚举的时间类型变体，导致漏检
- **影响：** `time_col_hint` 字段不完整，影响 NL2SQL 中的时间过滤功能
- **缓解措施：**
  1. **使用关键词包含匹配而非精确匹配**：
     - 支持 "timestamp without time zone" 等长格式
     - 大小写不敏感（统一转小写比较）
  2. **覆盖主流数据库的所有时间类型**：
     - PostgreSQL: date, time, timestamp, timestamptz, interval
     - MySQL: date, time, datetime, timestamp, year
     - SQL Server: date, time, datetime, datetime2, smalldatetime, datetimeoffset
     - Oracle: date, timestamp, interval
  3. **记录未识别的可疑类型**：
     - 日志警告包含 "date/time" 但未匹配的 data_type
     - 提供人工审查机制
  4. **提供测试覆盖**：
     - 单元测试覆盖 15+ 种常见时间类型变体
     - 确保识别逻辑的健壮性
- **监控指标：**
  - 统计各表识别到的时间列数量
  - 对比 DDL 中的实际时间列（人工抽查）

---

## 12. 后续扩展

### 12.1 增量更新优化

- 新增 `--incremental` 参数（智能增量）
- 基于 `updated_at` 字段判断是否需要更新（仅更新变化的对象）
- 当前 clean=False 已支持 upsert 全量覆盖，此扩展可进一步优化为增量对比

### 12.2 搜索 API

- 新增 `table_schema_search.py` 模块
- 实现语义搜索功能：
  - 根据文本查询相似表
  - 根据文本查询相似字段
- 用于 NL2SQL 的 Schema 理解阶段

### 12.3 混合检索

- 结合 57 号（dim_value）和 58 号（table_schema）
- 实现多阶段检索策略：
  1. Schema 检索（找到相关表和字段）
  2. Value 检索（找到匹配的维度值）
- 提高 NL2SQL 的准确性

### 12.4 Schema 变更检测

- 监控 MD 文件的变化
- 自动触发增量更新
- 提供 Schema 版本管理

---

## 13. 总结

本设计方案完整实现了表结构加载到向量数据库的功能，具备以下特点：

✅ **模块化设计：** 各模块职责清晰，易于测试和维护
✅ **配置复用：** 最大化复用 57 号的配置和服务
✅ **双类型支持：** 同时加载 Table 和 Column 对象
✅ **数据来源解耦：** 支持 MD 和 JSON_LLM 独立缺失
✅ **生产就绪：** 完善的错误处理、日志和测试策略
✅ **性能优化：** 批量处理、可配置参数

**开发实施重点：**
1. 复用 57 号的 EmbeddingService 和 MilvusClient
2. 实现健壮的 MD 解析逻辑，支持格式变体
3. 处理文件缺失和不匹配场景
4. 完整的错误提示和日志输出
5. 按照实施步骤一次性完成所有功能开发

**下一步：** 开始开发，按步骤实施。
