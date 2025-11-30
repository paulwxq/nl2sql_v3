# Step 7.1 CQL 数据加载模块设计

## 1. 模块概述

### 1.1 功能定位

CQLLoader 负责将 Step 4 生成的 Neo4j Cypher 文件（`import_all.cypher`）加载到 Neo4j 图数据库中，为 NL2SQL 系统提供表结构、字段信息和 JOIN 关系的图谱查询能力。

### 1.2 输入输出

- **输入**：`output/metaweave/metadata/cql/import_all.cypher`
- **输出**：填充好的 Neo4j 图数据库，包含：
  - Table 节点（带 pk/uk/fk/logic_pk/logic_fk/logic_uk/indexes 等属性）
    - **注意**：嵌套数组属性（uk/fk/logic_pk/logic_fk/logic_uk/indexes）会被自动转换为 JSON 字符串存储（详见 2.4 节）
    - `pk` 字段保持为一维数组（Neo4j 原生支持）
  - Column 节点（带 is_pk/is_uk/is_fk 等标志）
  - HAS_COLUMN 关系（表→列）
  - JOIN_ON 关系（表→表）

### 1.3 依赖服务

- **Neo4j 连接管理器**：`src/services/db/neo4j_connection.py`（已有）
- **配置服务**：`src/services/config_loader.py`（已有）

---

## 2. 功能需求详细说明

### 2.1 核心功能

| 功能 | 说明 | 优先级 |
|-----|------|--------|
| 读取 CQL 文件 | 从配置指定的路径读取 import_all.cypher | P0 |
| 解析 CQL 文件 | 按章节拆分 CQL 语句（约束/表/列/关系） | P0 |
| 连接 Neo4j | 使用全局配置或自定义配置连接数据库 | P0 |
| 执行 CQL 语句 | 按顺序执行 CQL 语句（支持事务） | P0 |
| 验证加载结果 | 对比预期节点数/关系数 | P1 |
| 错误处理 | 记录详细错误日志，支持重试 | P1 |

### 2.2 幂等性保证

- **约束创建**：使用 `CREATE CONSTRAINT ... IF NOT EXISTS`
- **节点创建**：使用 `MERGE` 而非 `CREATE`
- **关系创建**：使用 `MERGE` 而非 `CREATE`

多次执行不会产生重复数据，支持增量更新。

### 2.3 性能要求

- **小规模数据**（< 100 张表）：加载时间 < 10 秒
- **中等规模数据**（100-1000 张表）：加载时间 < 1 分钟
- **大规模数据**（> 1000 张表）：使用批量提交优化

### 2.4 Neo4j 嵌套数组限制与处理

#### 2.4.1 技术限制

Neo4j **不支持**在属性中存储嵌套集合（collection of collections）。如果尝试直接存储嵌套数组，会报错：

```
Neo.ClientError.Statement.TypeError: Collections containing collections can not be stored in properties.
```

这影响以下字段（来自 Step 4 生成的 CQL 文件）：
- `uk`：物理唯一键，格式 `[["code"], ["name"]]`（可能有多个）
- `fk`：物理外键，格式 `[["parent_id"], ["company_id"]]`（可能有多个）
- `logic_pk`：逻辑主键，格式 `[["id"], ["code"]]`（可能有多个候选）
- `logic_fk`：逻辑外键（来自 Step 3 关系发现）
- `logic_uk`：逻辑唯一键（来自 Step 2 画像推断）
- `indexes`：索引信息

**不受影响的字段：**
- `pk`：物理主键，格式 `[]` 或 `["id"]` 或 `["id", "code"]`
  - 这是一维数组（一个表只能有一个主键）
  - Neo4j 原生支持，**不需要转换**

#### 2.4.2 处理方式

CQLLoader 会自动将这些嵌套数组字段转换为 **JSON 字符串**：

**转换示例：**
```python
# 原始格式（Step 4 生成）
logic_pk: [["company_id"], ["code", "type"]]

# 转换后格式（存储到 Neo4j）
logic_pk: '[["company_id"], ["code", "type"]]'
```

**优点：**
- ✅ 准确保留原始数据结构（嵌套层级）
- ✅ 直观表达语义（能看出有几组复合键）
- ✅ 符合 Neo4j 技术限制

**缺点：**
- ⚠️ 后续模块查询时需要解析 JSON 字符串

#### 2.4.3 后续模块使用方法

**查询示例（Python）：**
```python
import json
from src.services.db.neo4j_connection import Neo4jConnectionManager

# 1. 查询表节点
query = "MATCH (t:Table {full_name: 'public.dim_company'}) RETURN t.logic_pk AS logic_pk"
result = neo4j_manager.execute_query(query)

# 2. 解析 JSON 字符串
logic_pk_str = result[0]["logic_pk"]  # '[["company_id"]]'
logic_pk = json.loads(logic_pk_str)   # [["company_id"]]

# 3. 使用数据
for key_columns in logic_pk:
    print(f"复合键包含列: {', '.join(key_columns)}")
    # 输出: 复合键包含列: company_id
```

**辅助函数（推荐）：**
```python
# src/metaweave/utils/neo4j_helpers.py

import json
from typing import List, Optional

def parse_nested_array_field(field_value: Optional[str]) -> List[List[str]]:
    """解析 Neo4j 中的嵌套数组字段（JSON 字符串格式）

    Args:
        field_value: JSON 字符串，如 '[["col1"], ["col2", "col3"]]'

    Returns:
        解析后的嵌套列表，如 [["col1"], ["col2", "col3"]]
        如果为空或解析失败，返回空列表

    Example:
        >>> parse_nested_array_field('[["company_id"]]')
        [['company_id']]

        >>> parse_nested_array_field('[["code", "type"], ["id"]]')
        [['code', 'type'], ['id']]
    """
    if not field_value:
        return []

    try:
        return json.loads(field_value)
    except (json.JSONDecodeError, TypeError):
        return []
```

#### 2.4.4 替代方案（不推荐）

**方案：平铺格式**
将 `[["col1", "col2"], ["col3"]]` 改为 `["col1,col2", "col3"]`

**缺点：**
- ❌ 不能直观看出有几组复合键（看起来像 2 个字符串）
- ❌ 需要约定分隔符，列名不能包含该分隔符
- ❌ 需要同时修改 Step 4 生成逻辑

**结论：** 当前的 JSON 字符串方案是最佳选择。

---

## 3. Neo4j 配置获取方式

### 3.1 配置优先级

CQLLoader 支持两种配置方式，按以下优先级读取：

1. **加载器配置文件**（`loader_config.yaml` 中的自定义配置）
2. **全局配置文件**（`src/configs/config.yaml` 中的 `neo4j` 配置）

### 3.2 配置结构

#### 方式1：使用全局配置（推荐）

```yaml
# configs/metaweave/loader_config.yaml
cql_loader:
  input_file: "output/metaweave/metadata/cql/import_all.cypher"
  neo4j:
    use_global_config: true  # 复用全局 Neo4j 配置
  options:
    transaction_mode: "by_section"
    validate_after_load: true
```

此时从 `src/configs/config.yaml` 读取 Neo4j 连接信息：

```yaml
# src/configs/config.yaml
neo4j:
  uri: "bolt://localhost:7687"
  user: "neo4j"
  password: "your_password"
  database: "neo4j"
```

#### 方式2：使用自定义配置

```yaml
# configs/metaweave/loader_config.yaml
cql_loader:
  input_file: "output/metaweave/metadata/cql/import_all.cypher"
  neo4j:
    use_global_config: false
    uri: "bolt://192.168.1.100:7687"
    user: "admin"
    password: "custom_password"
    database: "metaweave"
  options:
    transaction_mode: "by_section"
```

### 3.3 配置读取逻辑（伪代码）

```python
class CQLLoader(BaseLoader):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.neo4j_config = self._get_neo4j_config()

    def _get_neo4j_config(self) -> Dict[str, Any]:
        """获取 Neo4j 配置"""
        neo4j_section = self.config.get("cql_loader", {}).get("neo4j", {})

        if neo4j_section.get("use_global_config", True):
            # 从全局配置读取
            from src.services.config_loader import get_config
            global_config = get_config()
            return global_config["neo4j"]
        else:
            # 使用自定义配置
            return {
                "uri": neo4j_section["uri"],
                "user": neo4j_section["user"],
                "password": neo4j_section["password"],
                "database": neo4j_section.get("database", "neo4j"),
            }
```

---

## 4. CQL 文件解析策略

### 4.1 文件结构分析

根据实际生成的 `import_all.cypher` 文件，结构如下：

```cypher
// import_all.cypher
// Neo4j 元数据导入脚本（global 模式，包含所有表和关系）
// 生成时间: 2025-11-28T01:07:16.122611
// 统计: 6 张表, 22 个列, 6 个关系

// =====================================================================
// 1. 创建唯一约束
// =====================================================================

CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:Table) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT table_full_name IF NOT EXISTS FOR (t:Table) REQUIRE t.full_name IS UNIQUE;
CREATE CONSTRAINT column_full_name IF NOT EXISTS FOR (c:Column) REQUIRE c.full_name IS UNIQUE;

// =====================================================================
// 2. 创建 Table 节点
// =====================================================================

UNWIND [
  { "full_name": "public.dim_company", ... },
  { "full_name": "public.dim_store", ... }
] AS t
MERGE (n:Table {full_name: t.full_name})
SET n.id = t.full_name, n.schema = t.schema, ...;

// =====================================================================
// 3. 创建 Column 节点
// =====================================================================

UNWIND [...] AS c
MERGE (n:Column {full_name: c.full_name})
SET n.schema = c.schema, ...;

// =====================================================================
// 4. 建立 HAS_COLUMN 关系
// =====================================================================

UNWIND [...] AS hc
MATCH (t:Table {full_name: hc.table_full_name})
MATCH (c:Column {full_name: hc.column_full_name})
MERGE (t)-[:HAS_COLUMN]->(c);

// =====================================================================
// 5. 建立 JOIN_ON 关系
// =====================================================================

UNWIND [...] AS j
MATCH (src:Table {full_name: j.src_full_name})
MATCH (dst:Table {full_name: j.dst_full_name})
MERGE (src)-[r:JOIN_ON]->(dst)
SET r.cardinality = j.cardinality, ...;
```

### 4.2 解析策略

#### 策略1：按章节分段解析（推荐）

**优点**：
- 支持按章节执行事务，便于错误定位
- 可以分别统计每个章节的执行结果
- 符合文件的逻辑结构

**实现思路**：
1. 读取整个文件内容
2. 按章节分隔符（`// ========...`）拆分为 5 个章节
3. 每个章节作为一个独立的 Cypher 语句块
4. 按顺序执行 5 个语句块

**伪代码**：

```python
def parse_cql_file(file_path: Path) -> List[Dict[str, Any]]:
    """解析 CQL 文件，按章节拆分

    Returns:
        List[Dict]: 章节列表，每个元素包含：
            - section_name: 章节名称
            - cypher: Cypher 语句
            - order: 执行顺序
    """
    content = file_path.read_text(encoding="utf-8")

    # 章节分隔符正则
    section_pattern = r"// ={50,}\n// (\d+)\. (.+?)\n// ={50,}\n"

    # 拆分章节
    sections = []
    matches = list(re.finditer(section_pattern, content))

    for i, match in enumerate(matches):
        section_number = match.group(1)
        section_title = match.group(2)

        # 提取章节内容（从当前分隔符到下一个分隔符）
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_content = content[start:end].strip()

        # 移除注释行
        cypher = "\n".join(
            line for line in section_content.split("\n")
            if not line.strip().startswith("//")
        ).strip()

        if cypher:
            sections.append({
                "order": int(section_number),
                "section_name": section_title,
                "cypher": cypher,
            })

    return sections
```

#### 策略2：按语句分隔符解析（备选）

**适用场景**：如果文件格式变化，没有明确的章节分隔符

**实现思路**：
1. 按 `;` 分隔所有语句
2. 跳过注释行
3. 逐条执行

**缺点**：无法按章节统计，错误定位困难

---

## 5. 事务管理策略

### 5.1 事务模式对比

| 模式 | 说明 | 优点 | 缺点 | 推荐场景 |
|-----|------|------|------|---------|
| **single** | 整个文件作为一个事务 | 原子性强，全成功或全失败 | 失败后全部回滚，重试代价大 | 小规模数据（< 50 张表） |
| **by_section** | 按章节分段执行 | 错误定位准确，部分成功可保留 | 需要手动处理依赖顺序 | 中大规模数据（推荐） |

### 5.2 推荐配置

```yaml
# configs/metaweave/loader_config.yaml
cql_loader:
  options:
    transaction_mode: "by_section"  # 推荐按章节分段执行
```

### 5.3 执行逻辑（伪代码）

```python
def load(self) -> Dict[str, Any]:
    """执行 CQL 加载"""
    sections = self.parse_cql_file(self.input_file)
    transaction_mode = self.config.get("cql_loader", {}).get("options", {}).get("transaction_mode", "by_section")

    if transaction_mode == "single":
        return self._load_single_transaction(sections)
    else:
        return self._load_by_section(sections)

def _load_by_section(self, sections: List[Dict]) -> Dict[str, Any]:
    """按章节分段执行（推荐）"""
    stats = {
        "success": True,
        "message": "",
        "sections": [],
    }

    for section in sections:
        logger.info(f"[{section['order']}/5] {section['section_name']}...")

        try:
            result = self.neo4j_manager.execute_write_transaction(
                section["cypher"]
            )

            stats["sections"].append({
                "name": section["section_name"],
                "success": True,
            })

        except Exception as e:
            logger.error(f"章节 {section['section_name']} 执行失败: {e}")
            stats["success"] = False
            stats["message"] = f"章节 {section['section_name']} 失败"
            stats["sections"].append({
                "name": section["section_name"],
                "success": False,
                "error": str(e),
            })
            break  # 中断后续章节

    return stats
```

---

## 6. 执行流程设计

### 6.1 完整执行流程图

```
┌─────────────────────────────────────────────┐
│ 1. validate() - 验证阶段                     │
├─────────────────────────────────────────────┤
│ 1.1 检查配置是否完整                          │
│ 1.2 检查 CQL 文件是否存在                     │
│ 1.3 测试 Neo4j 连接                          │
│ 1.4 可选：检查 Neo4j 数据库是否为空           │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ 2. load() - 加载阶段                         │
├─────────────────────────────────────────────┤
│ 2.1 读取 CQL 文件                            │
│ 2.2 解析 CQL 文件（按章节拆分）               │
│ 2.3 执行章节 1: 创建约束                     │
│ 2.4 执行章节 2: 创建 Table 节点              │
│ 2.5 执行章节 3: 创建 Column 节点             │
│ 2.6 执行章节 4: 创建 HAS_COLUMN 关系         │
│ 2.7 执行章节 5: 创建 JOIN_ON 关系            │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ 3. validate_result() - 验证结果（可选）       │
├─────────────────────────────────────────────┤
│ 3.1 查询 Table 节点数量                      │
│ 3.2 查询 Column 节点数量                     │
│ 3.3 查询 JOIN_ON 关系数量                    │
│ 3.4 对比 CQL 文件头部的统计信息               │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ 4. 返回加载结果                              │
├─────────────────────────────────────────────┤
│ {                                            │
│   "success": True,                           │
│   "message": "加载成功",                      │
│   "nodes_created": 28,                       │
│   "relationships_created": 35,               │
│   "execution_time": 2.5                      │
│ }                                            │
└─────────────────────────────────────────────┘
```

### 6.2 各阶段详细说明

#### 阶段1：validate() - 验证阶段

```python
def validate(self) -> bool:
    """验证配置和数据源"""
    # 1. 检查配置是否完整
    if "cql_loader" not in self.config:
        logger.error("配置文件缺少 cql_loader 字段")
        return False

    # 2. 检查 CQL 文件是否存在
    input_file = Path(self.config["cql_loader"]["input_file"])
    if not input_file.exists():
        logger.error(f"CQL 文件不存在: {input_file}")
        return False

    # 3. 测试 Neo4j 连接
    try:
        self.neo4j_manager = Neo4jConnectionManager(self.neo4j_config)
        self.neo4j_manager.initialize()
        if not self.neo4j_manager.test_connection():
            logger.error("Neo4j 连接测试失败")
            return False
    except Exception as e:
        logger.error(f"Neo4j 连接失败: {e}")
        return False

    logger.info("✅ 配置验证通过")
    return True
```

#### 阶段2：load() - 加载阶段

（见第 5.3 节的伪代码）

#### 阶段3：validate_result() - 验证结果

```python
def validate_result(self, expected_stats: Dict[str, int]) -> bool:
    """验证加载结果

    Args:
        expected_stats: 期望的统计信息（从 CQL 文件头部提取）
            - table_count: 期望的表数量
            - column_count: 期望的列数量
            - relationship_count: 期望的关系数量

    Returns:
        bool: 验证是否通过
    """
    # 查询实际节点/关系数量
    actual_stats = self._get_graph_stats()

    # 对比
    if actual_stats["table_count"] != expected_stats["table_count"]:
        logger.warning(
            f"表数量不匹配: 期望 {expected_stats['table_count']}, "
            f"实际 {actual_stats['table_count']}"
        )
        return False

    if actual_stats["column_count"] != expected_stats["column_count"]:
        logger.warning(
            f"列数量不匹配: 期望 {expected_stats['column_count']}, "
            f"实际 {actual_stats['column_count']}"
        )
        return False

    logger.info("✅ 加载结果验证通过")
    return True

def _get_graph_stats(self) -> Dict[str, int]:
    """查询 Neo4j 中的统计信息"""
    query = """
        MATCH (t:Table)
        WITH count(t) AS table_count
        MATCH (c:Column)
        WITH table_count, count(c) AS column_count
        MATCH ()-[r:JOIN_ON]->()
        RETURN table_count, column_count, count(r) AS relationship_count
    """
    result = self.neo4j_manager.execute_query(query)
    record = result[0]

    return {
        "table_count": record["table_count"],
        "column_count": record["column_count"],
        "relationship_count": record["relationship_count"],
    }
```

---

## 7. 错误处理

### 7.1 常见错误类型

| 错误类型 | 原因 | 处理策略 |
|---------|------|---------|
| **文件不存在** | CQL 文件路径错误 | 在 validate() 中提前检测，返回 False |
| **Neo4j 连接失败** | 网络问题、配置错误 | 在 validate() 中提前检测，返回详细错误信息 |
| **语法错误** | CQL 文件格式错误 | 捕获异常，记录错误语句，返回 success=False |
| **约束冲突** | 重复执行导致约束已存在 | 使用 IF NOT EXISTS 避免（已在 Step 4 保证） |
| **节点不存在** | 关系创建时引用的节点不存在 | 按顺序执行（约束→表→列→关系），避免依赖问题 |

### 7.2 错误处理逻辑

```python
def _load_by_section(self, sections: List[Dict]) -> Dict[str, Any]:
    """按章节分段执行（带错误处理）"""
    stats = {
        "success": True,
        "message": "加载成功",
        "sections": [],
        "errors": [],
    }

    for section in sections:
        try:
            logger.info(f"[{section['order']}/5] {section['section_name']}...")

            # 执行 Cypher
            result = self.neo4j_manager.execute_write_transaction(
                section["cypher"]
            )

            stats["sections"].append({
                "name": section["section_name"],
                "success": True,
            })
            logger.info(f"  ✅ {section['section_name']} 完成")

        except Neo4jError as e:
            # Neo4j 特定错误（语法错误、约束冲突等）
            error_msg = f"{section['section_name']} 失败: {e.message}"
            logger.error(f"  ❌ {error_msg}")

            stats["success"] = False
            stats["message"] = error_msg
            stats["errors"].append({
                "section": section["section_name"],
                "error_type": "Neo4jError",
                "error_message": e.message,
                "error_code": e.code,
            })
            break  # 中断后续章节

        except Exception as e:
            # 其他未知错误
            error_msg = f"{section['section_name']} 失败: {str(e)}"
            logger.error(f"  ❌ {error_msg}")

            stats["success"] = False
            stats["message"] = error_msg
            stats["errors"].append({
                "section": section["section_name"],
                "error_type": "UnknownError",
                "error_message": str(e),
            })
            break

    return stats
```

### 7.3 日志记录

使用分级日志记录：

- **INFO**：正常执行流程（开始加载、章节完成等）
- **WARNING**：非致命问题（验证结果不匹配等）
- **ERROR**：致命错误（文件不存在、连接失败、执行失败等）
- **DEBUG**：详细的 Cypher 语句内容（仅在 --debug 模式下）

---

## 8. 验证策略

### 8.1 验证时机

- **加载前验证**：在 `validate()` 中执行
  - 配置完整性
  - 文件存在性
  - 数据库连接

- **加载后验证**：在 `load()` 完成后执行（可选）
  - 节点/关系数量对比
  - 数据完整性检查

### 8.2 统计信息提取

从 CQL 文件头部注释提取期望统计：

```python
def _extract_expected_stats(self, file_path: Path) -> Dict[str, int]:
    """从 CQL 文件头部提取期望的统计信息

    文件头部格式：
    // 统计: 6 张表, 22 个列, 6 个关系
    """
    content = file_path.read_text(encoding="utf-8")

    # 正则提取统计信息
    match = re.search(
        r"// 统计:\s*(\d+)\s*张表,\s*(\d+)\s*个列,\s*(\d+)\s*个关系",
        content
    )

    if match:
        return {
            "table_count": int(match.group(1)),
            "column_count": int(match.group(2)),
            "relationship_count": int(match.group(3)),
        }
    else:
        logger.warning("无法从 CQL 文件提取统计信息，跳过验证")
        return {}
```

### 8.3 验证查询

```cypher
-- 查询统计信息（使用 WITH 分段统计，避免笛卡尔积）
MATCH (t:Table)
WITH count(t) AS table_count
MATCH (c:Column)
WITH table_count, count(c) AS column_count
MATCH ()-[r:JOIN_ON]->()
RETURN table_count, column_count, count(r) AS relationship_count
```

---

## 9. 实现细节（伪代码）

### 9.1 CQLLoader 完整实现

```python
# src/metaweave/core/loaders/cql_loader.py

from pathlib import Path
from typing import Dict, Any, List
import re
import time
import logging

from src.metaweave.core.loaders.base import BaseLoader
from src.services.db.neo4j_connection import Neo4jConnectionManager
from src.services.config_loader import get_config
from neo4j.exceptions import Neo4jError

logger = logging.getLogger(__name__)


class CQLLoader(BaseLoader):
    """Neo4j CQL 加载器

    加载 Step 4 生成的 import_all.cypher 文件到 Neo4j 图数据库。
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.neo4j_config = self._get_neo4j_config()
        self.neo4j_manager = None
        self.input_file = Path(self.config["cql_loader"]["input_file"])

    def _get_neo4j_config(self) -> Dict[str, Any]:
        """获取 Neo4j 配置（全局配置或自定义配置）"""
        neo4j_section = self.config.get("cql_loader", {}).get("neo4j", {})

        if neo4j_section.get("use_global_config", True):
            # 使用全局配置
            global_config = get_config()
            return global_config["neo4j"]
        else:
            # 使用自定义配置
            return {
                "uri": neo4j_section["uri"],
                "user": neo4j_section["user"],
                "password": neo4j_section["password"],
                "database": neo4j_section.get("database", "neo4j"),
            }

    def validate(self) -> bool:
        """验证配置和数据源"""
        # 1. 检查配置
        if "cql_loader" not in self.config:
            logger.error("配置缺少 cql_loader 字段")
            return False

        # 2. 检查文件
        if not self.input_file.exists():
            logger.error(f"CQL 文件不存在: {self.input_file}")
            return False

        # 3. 测试连接
        try:
            self.neo4j_manager = Neo4jConnectionManager(self.neo4j_config)
            self.neo4j_manager.initialize()
            if not self.neo4j_manager.test_connection():
                logger.error("Neo4j 连接测试失败")
                return False
        except Exception as e:
            logger.error(f"Neo4j 连接失败: {e}")
            return False

        logger.info("✅ 配置验证通过")
        logger.info(f"✅ CQL 文件存在: {self.input_file}")
        logger.info(f"✅ Neo4j 连接成功: {self.neo4j_config['uri']}")

        return True

    def load(self) -> Dict[str, Any]:
        """执行 CQL 加载"""
        start_time = time.time()

        # 1. 解析 CQL 文件
        logger.info("正在解析 CQL 文件...")
        sections = self._parse_cql_file(self.input_file)
        logger.info(f"解析完成，共 {len(sections)} 个章节")

        # 2. 执行加载
        transaction_mode = self.config.get("cql_loader", {}).get("options", {}).get("transaction_mode", "by_section")
        logger.info(f"开始加载（事务模式: {transaction_mode}）...")

        if transaction_mode == "single":
            result = self._load_single_transaction(sections)
        else:
            result = self._load_by_section(sections)

        # 3. 验证结果（可选）
        validate_after_load = self.config.get("cql_loader", {}).get("options", {}).get("validate_after_load", True)
        if validate_after_load and result["success"]:
            expected_stats = self._extract_expected_stats(self.input_file)
            if expected_stats:
                self._validate_result(expected_stats)

        # 4. 统计执行时间
        execution_time = time.time() - start_time
        result["execution_time"] = round(execution_time, 2)

        return result

    def _parse_cql_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """解析 CQL 文件，按章节拆分"""
        content = file_path.read_text(encoding="utf-8")
        section_pattern = r"// ={50,}\n// (\d+)\. (.+?)\n// ={50,}\n"

        sections = []
        matches = list(re.finditer(section_pattern, content))

        for i, match in enumerate(matches):
            section_number = match.group(1)
            section_title = match.group(2)

            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_content = content[start:end].strip()

            # 移除注释行
            cypher = "\n".join(
                line for line in section_content.split("\n")
                if not line.strip().startswith("//")
            ).strip()

            if cypher:
                sections.append({
                    "order": int(section_number),
                    "section_name": section_title,
                    "cypher": cypher,
                })

        return sections

    def _load_by_section(self, sections: List[Dict]) -> Dict[str, Any]:
        """按章节分段执行（推荐）"""
        stats = {
            "success": True,
            "message": "加载成功",
            "sections": [],
            "errors": [],
        }

        for section in sections:
            try:
                logger.info(f"  [{section['order']}/5] {section['section_name']}...")

                result = self.neo4j_manager.execute_write_transaction(
                    section["cypher"]
                )

                stats["sections"].append({
                    "name": section["section_name"],
                    "success": True,
                })
                logger.info(f"    ✅ {section['section_name']} 完成")

            except Neo4jError as e:
                error_msg = f"{section['section_name']} 失败: {e.message}"
                logger.error(f"    ❌ {error_msg}")

                stats["success"] = False
                stats["message"] = error_msg
                stats["errors"].append({
                    "section": section["section_name"],
                    "error_type": "Neo4jError",
                    "error_message": e.message,
                })
                break

            except Exception as e:
                error_msg = f"{section['section_name']} 失败: {str(e)}"
                logger.error(f"    ❌ {error_msg}")

                stats["success"] = False
                stats["message"] = error_msg
                stats["errors"].append({
                    "section": section["section_name"],
                    "error_type": "UnknownError",
                    "error_message": str(e),
                })
                break

        return stats

    def _extract_expected_stats(self, file_path: Path) -> Dict[str, int]:
        """从 CQL 文件头部提取期望的统计信息"""
        content = file_path.read_text(encoding="utf-8")
        match = re.search(
            r"// 统计:\s*(\d+)\s*张表,\s*(\d+)\s*个列,\s*(\d+)\s*个关系",
            content
        )

        if match:
            return {
                "table_count": int(match.group(1)),
                "column_count": int(match.group(2)),
                "relationship_count": int(match.group(3)),
            }
        else:
            logger.warning("无法从 CQL 文件提取统计信息")
            return {}

    def _validate_result(self, expected_stats: Dict[str, int]):
        """验证加载结果"""
        actual_stats = self._get_graph_stats()

        if actual_stats["table_count"] != expected_stats["table_count"]:
            logger.warning(
                f"表数量不匹配: 期望 {expected_stats['table_count']}, "
                f"实际 {actual_stats['table_count']}"
            )
        else:
            logger.info(f"✅ 表数量正确: {actual_stats['table_count']}")

        if actual_stats["column_count"] != expected_stats["column_count"]:
            logger.warning(
                f"列数量不匹配: 期望 {expected_stats['column_count']}, "
                f"实际 {actual_stats['column_count']}"
            )
        else:
            logger.info(f"✅ 列数量正确: {actual_stats['column_count']}")

    def _get_graph_stats(self) -> Dict[str, int]:
        """查询 Neo4j 中的统计信息"""
        query = """
            MATCH (t:Table)
            WITH count(t) AS table_count
            MATCH (c:Column)
            WITH table_count, count(c) AS column_count
            MATCH ()-[r:JOIN_ON]->()
            RETURN table_count, column_count, count(r) AS relationship_count
        """
        result = self.neo4j_manager.execute_query(query)
        record = result[0]

        return {
            "table_count": record["table_count"],
            "column_count": record["column_count"],
            "relationship_count": record["relationship_count"],
        }
```

---

## 10. 测试计划

### 10.1 单元测试

测试文件：`tests/unit/metaweave/loaders/test_cql_loader.py`

| 测试用例 | 说明 | 预期结果 |
|---------|------|---------|
| `test_validate_success` | 配置正确、文件存在、连接成功 | validate() 返回 True |
| `test_validate_file_not_found` | CQL 文件不存在 | validate() 返回 False |
| `test_validate_neo4j_connection_failed` | Neo4j 连接失败 | validate() 返回 False |
| `test_parse_cql_file` | 解析 CQL 文件 | 返回 5 个章节 |
| `test_load_by_section_success` | 按章节加载成功 | load() 返回 success=True |
| `test_load_single_transaction` | 单事务加载成功 | load() 返回 success=True |

### 10.2 集成测试

测试文件：`tests/integration/metaweave/loaders/test_cql_loader_integration.py`

| 测试用例 | 说明 | 预期结果 |
|---------|------|---------|
| `test_full_loading_flow` | 完整加载流程（含验证） | 数据正确写入 Neo4j |
| `test_idempotency` | 多次执行幂等性 | 不产生重复数据 |
| `test_error_handling` | 模拟错误场景（文件损坏、连接断开） | 正确捕获并记录错误 |

### 10.3 手动测试步骤

```bash
# 1. 准备测试数据（确保 Step 4 已生成 CQL 文件）
# 注意：--config 参数是必需的
python -m src.metaweave.cli.main metadata \
  --config configs/metaweave/metadata_config.yaml \
  --step cql

# 2. 清空 Neo4j 数据库（可选）
# 在 Neo4j Browser 执行：MATCH (n) DETACH DELETE n

# 3. 执行加载
python -m src.metaweave.cli.main load --type cql --debug

# 4. 验证结果
# 在 Neo4j Browser 执行：
MATCH (t:Table) RETURN count(t) AS table_count;
MATCH (c:Column) RETURN count(c) AS column_count;
MATCH ()-[r:JOIN_ON]->() RETURN count(r) AS join_count;

# 5. 测试幂等性（再次执行）
python -m src.metaweave.cli.main load --type cql

# 6. 验证节点数未增加
MATCH (t:Table) RETURN count(t) AS table_count;
```

---

## 11. 总结

### 11.1 关键设计点

1. **配置灵活性**：支持全局配置和自定义配置两种方式
2. **按章节解析**：符合 CQL 文件的逻辑结构，便于错误定位
3. **分段事务**：默认按章节执行，平衡了原子性和灵活性
4. **幂等性保证**：使用 MERGE 和 IF NOT EXISTS，支持多次执行
5. **结果验证**：可选的加载后验证，确保数据完整性

### 11.2 未来优化方向

1. **批量提交优化**：对于大规模数据（> 1000 张表），使用批量提交减少网络开销
2. **并发执行**：章节 2 和章节 3（Table/Column 节点创建）可以并发执行
3. **增量更新**：只加载新增/修改的表，而非全量加载
4. **断点续传**：记录执行进度，失败后从断点处继续

### 11.3 依赖关系

- **前置步骤**：Step 4（CQL 生成）必须完成
- **后续步骤**：Step 7.2/7.3/7.4（向量数据加载）可独立进行
- **运行时依赖**：NL2SQL 系统需要 Neo4j 图谱支持 JOIN 路径规划

---

## 附录

### 附录A：配置文件完整示例

```yaml
# configs/metaweave/loader_config.yaml

cql_loader:
  input_file: "output/metaweave/metadata/cql/import_all.cypher"

  neo4j:
    use_global_config: true  # 使用 src/configs/config.yaml 中的 neo4j 配置

  options:
    transaction_mode: "by_section"  # single | by_section
    validate_after_load: true       # 加载后验证节点/关系数量
```

### 附录B：CLI 输出示例

```
$ python -m src.metaweave.cli.main load --type cql

开始执行 CQLLoader 加载流程...
✅ 配置验证通过
✅ CQL 文件存在: output/metaweave/metadata/cql/import_all.cypher
✅ Neo4j 连接成功: bolt://localhost:7687

正在解析 CQL 文件...
解析完成，共 5 个章节

开始加载（事务模式: by_section）...
  [1/5] 创建唯一约束...
    ✅ 创建唯一约束 完成
  [2/5] 创建 Table 节点...
    ✅ 创建 Table 节点 完成
  [3/5] 创建 Column 节点...
    ✅ 创建 Column 节点 完成
  [4/5] 建立 HAS_COLUMN 关系...
    ✅ 建立 HAS_COLUMN 关系 完成
  [5/5] 建立 JOIN_ON 关系...
    ✅ 建立 JOIN_ON 关系 完成

验证加载结果...
✅ 表数量正确: 6
✅ 列数量正确: 22

✅ CQLLoader 加载成功

加载结果:
  - 成功: True
  - 消息: 加载成功
  - 执行时间: 2.35s
```
