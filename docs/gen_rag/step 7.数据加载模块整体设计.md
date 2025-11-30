# Step 7 数据加载模块整体设计

## 1. 模块概述

### 1.1 功能定位

Step 7 数据加载模块是 MetaWeave 元数据生成流程的最后一步，负责将前序步骤生成的各类元数据文件加载到目标数据库中，为 NL2SQL 系统提供运行时所需的元数据支持。

### 1.2 加载任务概览

根据 readme.txt 的需求，Step 7 包含以下 4 种加载任务：

| 加载类型 | 数据源 | 目标数据库 | 用途 | 实现优先级 |
|---------|--------|-----------|------|-----------|
| **cql** | import_all.cypher | Neo4j (图数据库) | 表结构、字段、JOIN关系 | P0 (优先) |
| **md** | *.md 文件 | PgVector/Milvus | 表定义的文本检索 | P1 |
| **dim** | yaml配置 + 维表数据 | PgVector/Milvus | 维度值的语义匹配 | P1 |
| **sql** | 样例SQL文件 | PgVector/Milvus | 历史SQL的模板匹配 | P1 |

### 1.3 设计依赖

- **输入**：Step 2/3/4/5/6 生成的元数据文件
- **输出**：填充好的 Neo4j 图数据库 + 向量数据库
- **依赖服务**：
  - Neo4j 连接管理器（已有：`src/services/db/neo4j_connection.py`）
  - PostgreSQL 连接管理器（已有：`src/services/db/pg_connection.py`）
  - Embedding 服务（已有：`src/services/embedding/embedding_client.py`）

---

## 2. 设计目标和原则

### 2.1 设计目标

1. **统一接口**：不同加载类型使用统一的抽象接口和调用方式
2. **配置驱动**：通过配置文件控制数据源路径、目标连接等参数
3. **幂等性保证**：多次执行不产生重复数据，支持增量更新
4. **易于扩展**：可方便添加新的加载类型（如未来的 Milvus 支持）
5. **错误处理**：清晰的错误提示和日志记录，便于排查问题

### 2.2 设计原则

- **关注点分离**：加载逻辑与数据库操作分离
- **依赖注入**：通过配置注入数据库连接参数，而非硬编码
- **工厂模式**：使用工厂类动态创建加载器实例
- **模板方法**：抽象基类定义加载流程，子类实现具体步骤

---

## 3. 整体架构设计

### 3.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     CLI 层 (用户接口)                         │
│  python -m src.metaweave.cli.main load --type xxx --config   │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  LoaderFactory (工厂层)                       │
│  根据 --type 参数创建对应的加载器实例                          │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               BaseLoader (抽象接口层)                         │
│  定义统一的加载流程：validate() → load() → 统计                │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┬─────────────┬──────────┐
        ▼                           ▼             ▼          ▼
┌──────────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────┐
│  CQLLoader   │  │   MDLoader   │  │DimLoader │  │ SQLLoader  │
│  (Neo4j)     │  │ (PgVector)   │  │(PgVector)│  │ (PgVector) │
└──────┬───────┘  └──────┬───────┘  └────┬─────┘  └─────┬──────┘
       │                 │                │              │
       ▼                 ▼                ▼              ▼
┌──────────────┐  ┌─────────────────────────────────────────┐
│ Neo4jManager │  │      PgConnectionManager + Embedding    │
└──────────────┘  └─────────────────────────────────────────┘
```

### 3.2 核心组件说明

#### 3.2.1 CLI 层
- 位置：`src/metaweave/cli/loader_cli.py`
- 职责：解析命令行参数，调用 LoaderFactory 创建加载器，执行加载流程
- 接口：`load` 子命令

#### 3.2.2 工厂层
- 位置：`src/metaweave/core/loaders/factory.py`
- 职责：根据 `--type` 参数创建对应的加载器实例
- 设计模式：工厂模式

#### 3.2.3 抽象接口层
- 位置：`src/metaweave/core/loaders/base.py`
- 职责：定义统一的加载流程和接口规范
- 设计模式：模板方法模式

#### 3.2.4 具体加载器层
- 位置：`src/metaweave/core/loaders/cql_loader.py` 等
- 职责：实现具体的加载逻辑
- 每个加载器处理一种数据类型

---

## 4. 目录结构设计

```
src/metaweave/
├── core/
│   └── loaders/                        # 加载器模块（新增）
│       ├── __init__.py                 # 导出 BaseLoader, LoaderFactory 等
│       ├── base.py                     # BaseLoader 抽象基类
│       ├── factory.py                  # LoaderFactory 工厂类
│       ├── cql_loader.py               # CQLLoader 实现 (Step 7.1)
│       ├── md_loader.py                # MDLoader 实现 (Step 7.2) - 未来
│       ├── dim_loader.py               # DimLoader 实现 (Step 7.3) - 未来
│       └── sql_loader.py               # SQLLoader 实现 (Step 7.4) - 未来
│
├── cli/
│   ├── main.py                         # CLI 主入口（已有）
│   ├── metadata_cli.py                 # metadata 子命令（已有）
│   └── loader_cli.py                   # load 子命令（新增）
│
└── services/                           # 服务层（已有，复用）
    ├── db/
    │   ├── neo4j_connection.py         # Neo4j 连接管理器
    │   └── pg_connection.py            # PostgreSQL 连接管理器
    └── embedding/
        └── embedding_client.py         # Embedding 服务

configs/metaweave/
└── loader_config.yaml                  # 加载器配置文件（新增）

docs/gen_rag/
├── step 7.数据加载模块整体设计.md      # 本文档
└── step 7.1.cql数据加载模块设计.md     # CQL 加载器详细设计
```

---

## 5. 统一接口设计 (BaseLoader)

### 5.1 抽象基类定义

```python
# src/metaweave/core/loaders/base.py

from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseLoader(ABC):
    """加载器基类

    所有具体加载器都应继承此类并实现 validate() 和 load() 方法。
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化加载器

        Args:
            config: 配置字典，包含加载器所需的所有配置项
        """
        self.config = config
        self._validate_config()

    def _validate_config(self):
        """验证配置字典的基本结构（可被子类重写）"""
        pass

    @abstractmethod
    def validate(self) -> bool:
        """验证配置和数据源

        在执行 load() 之前调用，检查：
        - 配置项是否完整
        - 数据源文件是否存在
        - 目标数据库是否可连接

        Returns:
            bool: 验证是否通过
        """
        pass

    @abstractmethod
    def load(self) -> Dict[str, Any]:
        """执行加载操作

        Returns:
            Dict[str, Any]: 加载结果字典，至少包含：
                - success (bool): 加载是否成功
                - message (str): 结果消息
                - 其他统计信息（如节点数、关系数等）
        """
        pass

    def execute(self) -> Dict[str, Any]:
        """执行完整的加载流程（验证 + 加载）

        Returns:
            Dict[str, Any]: 加载结果
        """
        # 验证
        if not self.validate():
            return {
                "success": False,
                "message": "验证失败",
            }

        # 加载
        result = self.load()
        return result
```

### 5.2 接口规范

所有具体加载器必须实现以下方法：

| 方法 | 说明 | 返回值 |
|-----|------|--------|
| `__init__(config)` | 初始化加载器，接收配置字典 | - |
| `validate()` | 验证配置和数据源 | bool |
| `load()` | 执行加载操作 | Dict[str, Any] |
| `execute()` | 执行完整流程（已在基类实现） | Dict[str, Any] |

### 5.3 返回值规范

`load()` 方法必须返回包含以下字段的字典：

```python
{
    "success": True/False,           # 必需：是否成功
    "message": "加载成功",            # 必需：结果消息

    # 以下为可选的统计信息（根据加载类型不同）
    "nodes_created": 28,             # CQL: 创建的节点数
    "relationships_created": 28,     # CQL: 创建的关系数
    "documents_loaded": 6,           # MD: 加载的文档数
    "vectors_created": 6,            # MD/Dim/SQL: 创建的向量数
}
```

---

## 6. 工厂模式设计 (LoaderFactory)

### 6.1 工厂类定义

```python
# src/metaweave/core/loaders/factory.py

from typing import Dict, Any
from src.metaweave.core.loaders.base import BaseLoader
from src.metaweave.core.loaders.cql_loader import CQLLoader
# 未来导入其他加载器
# from src.metaweave.core.loaders.md_loader import MDLoader
# from src.metaweave.core.loaders.dim_loader import DimLoader
# from src.metaweave.core.loaders.sql_loader import SQLLoader

class LoaderFactory:
    """加载器工厂类

    根据加载类型创建对应的加载器实例。
    """

    # 注册表：加载类型 -> 加载器类
    _loaders = {
        "cql": CQLLoader,
        # 未来扩展
        # "md": MDLoader,
        # "dim": DimLoader,
        # "sql": SQLLoader,
    }

    @classmethod
    def create(cls, load_type: str, config: Dict[str, Any]) -> BaseLoader:
        """创建加载器实例

        Args:
            load_type: 加载类型（"cql"/"md"/"dim"/"sql"）
            config: 配置字典

        Returns:
            BaseLoader: 加载器实例

        Raises:
            ValueError: 未知的加载类型
        """
        loader_class = cls._loaders.get(load_type)
        if not loader_class:
            raise ValueError(f"未知的加载类型: {load_type}")

        return loader_class(config)

    @classmethod
    def register(cls, load_type: str, loader_class: type):
        """注册新的加载器类型（用于扩展）

        Args:
            load_type: 加载类型标识
            loader_class: 加载器类
        """
        cls._loaders[load_type] = loader_class
```

### 6.2 使用示例

```python
# 在 CLI 中使用工厂创建加载器
from src.metaweave.core.loaders.factory import LoaderFactory

config = load_yaml_config("configs/metaweave/loader_config.yaml")
loader = LoaderFactory.create("cql", config)
result = loader.execute()

if result["success"]:
    print(f"✅ 加载成功: {result}")
else:
    print(f"❌ 加载失败: {result}")
```

---

## 7. 配置文件设计

### 7.1 配置文件路径

```
configs/metaweave/loader_config.yaml
```

### 7.2 配置文件结构

```yaml
# =====================================================================
# Step 7 数据加载器配置文件
# =====================================================================

# CQL 加载器配置 (Step 7.1)
cql_loader:
  input_file: "output/metaweave/metadata/cql/import_all.cypher"
  neo4j:
    use_global_config: true  # 使用全局 Neo4j 配置（src/configs/config.yaml）
    # 如果 use_global_config=false，则需要提供以下配置：
    # uri: "bolt://localhost:7687"
    # user: "neo4j"
    # password: "password"
    # database: "neo4j"
  options:
    transaction_mode: "by_section"  # 事务模式：single(单事务) / by_section(按章节分段)
    validate_after_load: true       # 加载后验证节点/关系数量

# MD 加载器配置 (Step 7.2) - 未来实现
md_loader:
  input_dir: "output/metaweave/metadata/md"
  vector_db:
    type: "pgvector"  # 或 "milvus"
    use_global_config: true
  options:
    chunk_size: 512         # 文本分块大小
    chunk_overlap: 50       # 分块重叠大小
    embedding_model: "text-embedding-ada-002"

# Dim 加载器配置 (Step 7.3) - 未来实现
dim_loader:
  config_file: "configs/metaweave/dim_tables.yaml"  # 维表列表配置
  vector_db:
    type: "pgvector"
    use_global_config: true
  options:
    batch_size: 100

# SQL 加载器配置 (Step 7.4) - 未来实现
sql_loader:
  input_dir: "output/metaweave/metadata/sql"
  vector_db:
    type: "pgvector"
    use_global_config: true
  options:
    embedding_model: "text-embedding-ada-002"
```

### 7.3 配置复用说明

- **Neo4j 配置**：默认复用 `src/configs/config.yaml` 中的 `neo4j` 配置
- **PostgreSQL 配置**：默认复用 `src/configs/config.yaml` 中的 `database` 配置
- **Embedding 配置**：复用现有 `embedding_client.py` 的配置

---

## 8. CLI 接口设计

### 8.1 命令格式

```bash
python -m src.metaweave.cli.main load --type <TYPE> [--config <CONFIG_FILE>] [--debug]
```

### 8.2 参数说明

| 参数 | 类型 | 必需 | 说明 | 默认值 |
|-----|------|------|------|--------|
| `--type` | str | 是 | 加载类型：cql/md/dim/sql | - |
| `--config` | str | 否 | 配置文件路径 | configs/metaweave/loader_config.yaml |
| `--debug` | flag | 否 | 启用调试模式 | False |

### 8.3 使用示例

```bash
# 加载 CQL 到 Neo4j（使用默认配置）
python -m src.metaweave.cli.main load --type cql

# 加载 CQL（指定配置文件）
python -m src.metaweave.cli.main load --type cql --config my_loader_config.yaml

# 加载 MD 到向量数据库（未来实现后可用）
python -m src.metaweave.cli.main load --type md --debug

# 注意：--type 仅支持 cql/md/dim/sql（单个类型）
# 批量加载 --type all 尚未实现，参见第 9.4 节未来扩展点
```

### 8.4 输出示例

```
开始执行 CQLLoader 加载流程...
✅ 配置验证通过
✅ CQL 文件存在: output/metaweave/metadata/cql/import_all.cypher
✅ Neo4j 连接成功: bolt://localhost:7687

正在加载 CQL 文件...
  [1/5] 创建约束... ✅ (3个约束)
  [2/5] 创建 Table 节点... ✅ (6个节点)
  [3/5] 创建 Column 节点... ✅ (28个节点)
  [4/5] 创建 HAS_COLUMN 关系... ✅ (28个关系)
  [5/5] 创建 JOIN_ON 关系... ✅ (7个关系)

✅ 加载成功！
统计信息:
  - 节点总数: 34
  - 关系总数: 35
  - 执行时间: 2.5s
```

---

## 9. 未来扩展点

### 9.1 支持更多向量数据库

当前优先支持 **PgVector**，未来可扩展：
- **Milvus**：高性能向量检索
- **Qdrant**：云原生向量数据库
- **Weaviate**：语义搜索引擎

扩展方式：
1. 在 `vector_db.type` 配置中添加新类型
2. 在加载器中添加对应的数据库客户端逻辑
3. 无需修改 BaseLoader 接口

### 9.2 支持增量更新

当前设计支持全量加载，未来可扩展增量更新：
- **CQL**：通过 MERGE 语句天然支持增量（已实现）
- **向量库**：
  - 方案1：基于文档 ID 去重（UPSERT）
  - 方案2：维护版本号，只加载新增/修改的文档

### 9.3 支持数据清理

在 `load` 命令中添加 `--clean` 参数，清空目标数据库后再加载：

```bash
# 清空 Neo4j 后重新加载
python -m src.metaweave.cli.main load --type cql --clean
```

实现方式：
- 在 `validate()` 方法中检查 `--clean` 参数
- 如果为 True，执行清空操作（如 `MATCH (n) DETACH DELETE n`）

### 9.4 支持批量加载

未来可能需要一次性加载所有类型：

```bash
# 加载所有类型
python -m src.metaweave.cli.main load --type all
```

实现方式：
- 在 CLI 中检测 `--type all`
- 依次调用所有已注册的加载器

---

## 10. 与现有模块的集成

### 10.1 复用现有服务

- **Neo4j 连接**：复用 `src/services/db/neo4j_connection.py`
- **PostgreSQL 连接**：复用 `src/services/db/pg_connection.py`
- **Embedding 服务**：复用 `src/services/embedding/embedding_client.py`

### 10.2 配置文件整合

可选方案1：独立配置文件
- 优点：职责清晰，不影响现有配置
- 缺点：配置分散

可选方案2：合并到现有配置
- 在 `configs/metaweave/metadata_config.yaml` 中添加 `loaders` 字段
- 优点：配置集中
- 缺点：文件变大

**推荐方案1**（独立配置文件），因为 Step 7 是独立的运行时步骤。

---

## 11. 总结

### 11.1 核心设计

- **统一接口**：BaseLoader 抽象基类定义统一的加载流程
- **工厂模式**：LoaderFactory 动态创建加载器实例
- **配置驱动**：所有参数通过配置文件管理
- **易于扩展**：添加新加载类型只需实现 BaseLoader 接口

### 11.2 实现路径

1. ✅ **Step 7.1**：实现 CQLLoader（优先级 P0）
2. Step 7.2：实现 MDLoader（优先级 P1）
3. Step 7.3：实现 DimLoader（优先级 P1）
4. Step 7.4：实现 SQLLoader（优先级 P1）

### 11.3 下一步

请参阅 **Step 7.1.cql数据加载模块设计.md**，了解 CQL 加载器的详细实现设计。
