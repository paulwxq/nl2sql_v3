# 关系ID盐值统一修复（v3.2规范）

## 问题背景

在 Step 3 关系发现模块的实现中，**外键直通** 和 **推断关系** 的 ID 生成逻辑不一致：

### 原实现问题

#### 1. Repository (外键直通 - 支持盐值)

在 `src/metaweave/core/relationships/repository.py:157-194`：

```python
class MetadataRepository:
    def __init__(self, json_dir: Path, rel_id_salt: str = ""):
        self.rel_id_salt = rel_id_salt  # ✅ 接受盐值参数

    def _generate_relation_id(self, ...):
        signature = (
            f"{source_schema}.{source_table}.[{','.join(src_cols)}]->"
            f"{target_schema}.{target_table}.[{','.join(tgt_cols)}]"
            f"{self.rel_id_salt}"  # ✅ 使用盐值
        )
        hash_digest = hashlib.md5(signature.encode("utf-8")).hexdigest()
        return f"rel_{hash_digest[:12]}"
```

#### 2. DecisionEngine (推断关系 - 未支持盐值)

在 `src/metaweave/core/relationships/decision_engine.py:22-36, 194-210`：

```python
class DecisionEngine:
    def __init__(self, config: dict):
        # ❌ 没有读取 rel_id_salt 配置
        pass

    def _candidate_to_relation(self, candidate):
        signature = (
            f"{source_schema}.{source_table}.[{','.join(src_cols)}]->"
            f"{target_schema}.{target_table}.[{','.join(tgt_cols)}]"
            # ❌ 缺少盐值
        )
        hash_digest = hashlib.md5(signature.encode("utf-8")).hexdigest()
        relationship_id = f"rel_{hash_digest[:12]}"
```

### 问题影响

**同一关系生成不同ID**：

```python
# 场景：fact_sales.store_id -> dim_store.store_id
# 如果既有外键又被推断系统发现

外键关系ID（带盐值 "myproject"）:
  rel_abc123def456  # MD5("public.fact_sales.[store_id]->public.dim_store.[store_id]myproject")

推断关系ID（无盐值）:
  rel_xyz789ghi012  # MD5("public.fact_sales.[store_id]->public.dim_store.[store_id]")

结果：同一关系生成两个不同的ID ❌
```

---

## 修复方案

按照文档要求和最佳实践，实现以下修复：

### 核心变更

#### 1. DecisionEngine 读取盐值配置

```python
class DecisionEngine:
    def __init__(self, config: dict):
        """初始化决策引擎"""
        decision_config = config.get("decision", {})
        output_config = config.get("output", {})  # ← 新增

        # ... 其他配置

        # ✅ 读取 rel_id_salt 配置（与 Repository 保持一致）
        self.rel_id_salt = output_config.get("rel_id_salt", "")
```

#### 2. 推断关系ID生成加入盐值

```python
def _candidate_to_relation(self, candidate):
    """将候选转换为Relation对象"""
    # ... 提取表和列信息

    # ✅ 使用 Repository 的静态方法生成 relationship_id（统一逻辑）
    relationship_id = MetadataRepository.compute_relationship_id(
        source_schema=source_schema,
        source_table=source_table,
        source_columns=source_columns,
        target_schema=target_schema,
        target_table=target_table,
        target_columns=target_columns,
        rel_id_salt=self.rel_id_salt  # ← 使用盐值
    )
```

#### 3. Repository 添加静态方法（集中封装）

```python
class MetadataRepository:
    @staticmethod
    def compute_relationship_id(
            source_schema: str,
            source_table: str,
            source_columns: List[str],
            target_schema: str,
            target_table: str,
            target_columns: List[str],
            rel_id_salt: str = ""
    ) -> str:
        """生成确定性relationship_id（静态方法，可复用）

        格式: rel_ + MD5[:12]

        Args:
            source_schema: 源schema
            source_table: 源表
            source_columns: 源列列表
            target_schema: 目标schema
            target_table: 目标表
            target_columns: 目标列列表
            rel_id_salt: 哈希盐（用于命名空间隔离）

        Returns:
            relationship_id（格式: rel_abc123def456）
        """
        # 列名排序确保一致性
        src_cols = sorted(source_columns)
        tgt_cols = sorted(target_columns)

        # 构建签名字符串（包含盐值）
        signature = (
            f"{source_schema}.{source_table}.[{','.join(src_cols)}]->"
            f"{target_schema}.{target_table}.[{','.join(tgt_cols)}]"
            f"{rel_id_salt}"
        )

        # MD5哈希
        hash_digest = hashlib.md5(signature.encode("utf-8")).hexdigest()
        return f"rel_{hash_digest[:12]}"

    def _generate_relation_id(self, ...):
        """实例方法，调用静态方法"""
        return self.compute_relationship_id(
            source_schema=source_schema,
            source_table=source_table,
            source_columns=source_columns,
            target_schema=target_schema,
            target_table=target_table,
            target_columns=target_columns,
            rel_id_salt=self.rel_id_salt
        )
```

---

## 修复效果

### ✅ 完全统一ID生成逻辑

#### 1. 外键关系与推断关系生成相同ID

```python
# 配置
config = {
    "output": {
        "rel_id_salt": "myproject"
    }
}

# 外键关系（Repository）
fk_relation_id = repository._generate_relation_id(
    "public", "fact_sales", ["store_id"],
    "public", "dim_store", ["store_id"]
)
# 结果: rel_abc123def456

# 推断关系（DecisionEngine）
inferred_relation = decision_engine._candidate_to_relation(candidate)
# 结果: rel_abc123def456

# ✅ 相同的关系生成相同的ID
assert fk_relation_id == inferred_relation.relationship_id
```

#### 2. 支持命名空间隔离

```python
# 项目A（使用盐值 "projectA"）
rel_id_A = MetadataRepository.compute_relationship_id(
    "public", "fact_sales", ["store_id"],
    "public", "dim_store", ["store_id"],
    rel_id_salt="projectA"
)
# 结果: rel_abc123def456

# 项目B（使用盐值 "projectB"）
rel_id_B = MetadataRepository.compute_relationship_id(
    "public", "fact_sales", ["store_id"],
    "public", "dim_store", ["store_id"],
    rel_id_salt="projectB"
)
# 结果: rel_xyz789ghi012

# ✅ 不同项目生成不同的ID，避免命名冲突
assert rel_id_A != rel_id_B
```

#### 3. 集中封装，易于维护

```python
# ✅ 其他模块可以直接使用静态方法
from src.metaweave.core.relationships.repository import MetadataRepository

rel_id = MetadataRepository.compute_relationship_id(
    source_schema="public",
    source_table="fact_sales",
    source_columns=["store_id"],
    target_schema="public",
    target_table="dim_store",
    target_columns=["store_id"],
    rel_id_salt="myproject"
)
```

### ✅ 向后兼容

- ✅ 默认盐值为空字符串 `""`，与原实现行为一致
- ✅ 实例方法 `_generate_relation_id` 保持不变，仍可使用
- ✅ 不影响其他模块

### ✅ 测试验证

- **所有 43 个单元测试通过**（从 40 个增加到 43 个）
- 新增测试覆盖：
  - `test_compute_relationship_id_static_method`：验证静态方法功能
    - 无盐值和有盐值生成不同ID
    - 相同盐值生成相同ID
  - `test_relation_id_salt_consistency`：验证实例方法与静态方法一致性
  - `test_relation_id_with_salt`：验证 DecisionEngine 推断关系ID支持盐值
    - 有盐值和无盐值生成不同ID
    - 与 Repository 生成的ID一致

---

## 使用场景

### 场景1：多项目共享数据库

```
公司有多个项目共享同一个数据仓库

项目A（CRM系统）:
  - rel_id_salt: "crm"
  - 关系: fact_sales.customer_id -> dim_customer.customer_id
  - ID: rel_abc123def456

项目B（BI分析）:
  - rel_id_salt: "bi"
  - 关系: fact_sales.customer_id -> dim_customer.customer_id
  - ID: rel_xyz789ghi012

结果：两个项目的关系ID不冲突 ✅
```

### 场景2：开发/测试/生产环境隔离

```
开发环境:
  - rel_id_salt: "dev"
  - ID: rel_dev123abc456

测试环境:
  - rel_id_salt: "test"
  - ID: rel_test789def012

生产环境:
  - rel_id_salt: "prod"
  - ID: rel_prod345ghi678

结果：不同环境的关系ID独立 ✅
```

### 场景3：版本管理

```
元数据版本 v1.0:
  - rel_id_salt: "v1.0"
  - ID: rel_v10abc123def

元数据版本 v2.0:
  - rel_id_salt: "v2.0"
  - ID: rel_v20xyz789ghi

结果：支持元数据版本演进 ✅
```

---

## 相关文件

### 修改的代码文件

1. **src/metaweave/core/relationships/repository.py**
   - 添加 `compute_relationship_id()` 静态方法
   - 修改 `_generate_relation_id()` 实例方法（调用静态方法）

2. **src/metaweave/core/relationships/decision_engine.py**
   - 修改 `__init__()` 方法，读取 `rel_id_salt` 配置
   - 修改 `_candidate_to_relation()` 方法，使用静态方法生成ID
   - 添加 `MetadataRepository` 导入

### 修改的测试文件

1. **tests/unit/metaweave/relationships/test_repository.py**
   - 新增 `test_compute_relationship_id_static_method`
   - 新增 `test_relation_id_salt_consistency`

2. **tests/unit/metaweave/relationships/test_decision_engine.py**
   - 新增 `test_relation_id_with_salt`

### 配置文件

**docs/gen_rag/metadata_config.step3.yaml.template** (已存在)：

```yaml
output:
  output_dir: output/metaweave/metadata
  rel_directory: output/metaweave/metadata/rel
  rel_granularity: global
  rel_id_salt: ""  # 可选：用于命名空间隔离（默认为空）
```

---

## 配置示例

### 使用盐值

```yaml
output:
  output_dir: output/metaweave/metadata
  rel_directory: output/metaweave/metadata/rel
  rel_granularity: global
  rel_id_salt: "myproject"  # 项目特定的盐值
```

### 不使用盐值（默认）

```yaml
output:
  output_dir: output/metaweave/metadata
  rel_directory: output/metaweave/metadata/rel
  rel_granularity: global
  rel_id_salt: ""  # 空字符串（默认）
```

---

## 完整示例

### 代码示例

```python
from src.metaweave.core.relationships.repository import MetadataRepository
from src.metaweave.core.relationships.decision_engine import DecisionEngine

# 配置
config = {
    "decision": {
        "accept_threshold": 0.80
    },
    "output": {
        "rel_id_salt": "myproject"
    }
}

# Repository（外键直通）
repository = MetadataRepository(
    json_dir=Path("output/metaweave/metadata/json"),
    rel_id_salt="myproject"
)

fk_id = repository._generate_relation_id(
    "public", "fact_sales", ["store_id"],
    "public", "dim_store", ["store_id"]
)
# 结果: rel_abc123def456

# DecisionEngine（推断关系）
decision_engine = DecisionEngine(config)

candidate = {
    "source": {"table_info": {"schema_name": "public", "table_name": "fact_sales"}},
    "target": {"table_info": {"schema_name": "public", "table_name": "dim_store"}},
    "source_columns": ["store_id"],
    "target_columns": ["store_id"],
    "composite_score": 0.85,
    "score_details": {},
    "candidate_type": "single_active_search"
}

inferred_relation = decision_engine._candidate_to_relation(candidate)
# 结果: rel_abc123def456

# ✅ 外键和推断关系生成相同ID
assert fk_id == inferred_relation.relationship_id
```

### 静态方法使用示例

```python
from src.metaweave.core.relationships.repository import MetadataRepository

# 直接使用静态方法（无需实例化）
rel_id = MetadataRepository.compute_relationship_id(
    source_schema="public",
    source_table="fact_sales",
    source_columns=["store_id"],
    target_schema="public",
    target_table="dim_store",
    target_columns=["store_id"],
    rel_id_salt="myproject"
)
# 结果: rel_abc123def456
```

---

## 版本信息

- 修复时间：2025-11-26
- 影响模块：Step 3 关系发现（Repository, DecisionEngine）
- 修复优先级：低（但重要）
- 测试覆盖：43/43 单元测试通过

---

## 后续优化

1. **性能优化**：
   - 考虑缓存相同参数的ID生成结果
   - 对于大量关系，优化哈希计算

2. **扩展功能**：
   - 支持自定义哈希算法（SHA256, SHA512等）
   - 支持自定义ID长度

3. **监控和诊断**：
   - 记录ID生成统计（冲突检测）
   - 在日志中输出盐值配置（脱敏）
