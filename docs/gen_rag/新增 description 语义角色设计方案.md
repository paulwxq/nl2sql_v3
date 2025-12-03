# 新增 `description` 语义角色设计方案

> **⚠️ 配置一致性提醒**
> 
> 本方案涉及配置文件、配置类、代码实现三处的映射关系，实施时请严格遵循 **8.1 节《配置一致性检查清单》**，确保：
> 1. YAML 配置路径：`sampling.description_detection.min_avg_length`
> 2. Config 字段名：`description_min_avg_length`
> 3. 读取代码：`desc_cfg.get("min_avg_length", 50.0)`
> 4. 使用代码：`self.config.description_min_avg_length`
> 
> 不一致会导致 `AttributeError` 或读取不到配置值。

---

## 一、背景与目标

### 1.1 需求背景

在现有的语义角色体系中，包含 6 种角色：`audit`、`datetime`、`identifier`、`enum`、`metric`、`attribute`。但缺少对**长文本说明字段**的专门识别，例如：
- 备注字段（`notes`、`remark`）
- 描述字段（`description`、`detail`）
- 说明字段（`comment`、`explanation`）

这类字段的特征：
- ✅ 数据类型通常为 `text` 或 `varchar(>=256)`
- ✅ 内容长度较长且变化较大
- ✅ 唯一性较高（每条记录的描述通常不同）
- ✅ 不参与关联关系（不应作为关联键）

### 1.2 主要挑战

**与 identifier 的冲突问题**：部分系统使用 `text` 类型的字符串作为主键（如 `order_code`、`uuid`），容易与 description 混淆。

**核心区分点**：
- **identifier**：长度稳定、格式固定、有物理约束或索引
- **description**：长度波动大、内容自由、无物理约束

### 1.3 设计目标

1. 准确识别长文本说明字段
2. 与 identifier 有效区分，避免误判
3. 支持配置化，可根据业务调整阈值
4. 性能可接受，不增加显著开销

---

## 二、角色定义

### 2.1 角色名称

**`description`** （描述/说明字段）

### 2.2 典型示例

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `product_description` | text | 产品详细描述 |
| `notes` | text | 备注信息 |
| `remark` | varchar(500) | 备注说明 |
| `fault_detail` | text | 故障详情 |
| `explanation` | text | 解释说明 |
| `comment` | text | 评论内容 |

### 2.3 角色特征

| 特征维度 | 特征值 |
|----------|--------|
| **数据类型** | text 或 varchar(>=256) |
| **平均长度** | >= 50 字符 |
| **长度离散度** | 标准差 > 20（或长度范围 > 100） |
| **唯一性** | >= 0.7 |
| **物理约束** | 无主键、外键、索引 |
| **命名模式** | 包含 description/desc/note/remark/comment 等关键词 |

---

## 三、判断规则详解

### 3.1 优先级位置

在语义角色判断链中的位置：

```
audit > datetime > identifier > description > enum > metric > attribute
                                    ↑
                              插入在此位置
```

**理由**：
- 在 `identifier` **之后**：确保有物理约束的字段优先被识别为 identifier
- 在 `enum` **之前**：description 字段通常唯一性高，避免被误判为 enum

### 3.2 完整判断规则

#### 规则 1：排除条件（前置过滤）

必须**不满足**以下任一条件，否则直接排除：

```python
# 1. 有物理约束
if struct_flags.is_primary_key or struct_flags.is_foreign_key:
    return False

# 2. 被索引
if struct_flags.is_indexed:
    return False
```

**原因**：有约束或索引的字段通常是 identifier，不会是 description。

#### 规则 2：数据类型白名单

必须满足以下**之一**：

```python
# 1. text 类型
data_type == "text"

# 2. 长 varchar/char
data_type in ("varchar", "character varying", "char") 
AND character_maximum_length >= 256
```

**阈值说明**：
- `256` 是合理的分界点，小于此值的通常是普通属性字段
- 可配置：`min_varchar_length`

#### 规则 3：平均长度阈值

```python
stats["avg_length"] >= 50
```

**核心判断依据**，用于区分：
- **< 50**：可能是短编码（identifier）或普通属性（attribute）
- **>= 50**：更可能是长文本说明（description）

**示例**：
```
order_code (identifier):  avg_length = 15
store_name (attribute):   avg_length = 25
description (description): avg_length = 120
```

#### 规则 4：长度稳定性检查（关键区分）

用于区分**固定格式编码** vs **自由文本**：

```python
# 场景 1：长度非常稳定（标准差小）
# 注：此时 avg_length 已经 >= 50（前面已检查）
if length_std < 5:
    # 检查命名：包含 exclude_keywords 中的关键词 → 排除
    if any(kw in column_name for kw in exclude_keywords):
        return False  # 排除，让 identifier 规则处理

# 场景 2：长度波动大（高离散度）
if length_std > 20 or (max_length - min_length) > 100:
    # 强判定为 description（高置信度）
    return True
```

**说明**：`exclude_keywords` 来自配置文件，默认值为 `["code", "_id", "_key", "_no", "number", "uuid", "token"]`。

**示例对比**：

| 字段 | avg | std | min | max | 判断 |
|------|-----|-----|-----|-----|------|
| `order_code` | 15 | 2 | 12 | 18 | identifier（长度稳定）|
| `uuid` | 36 | 0 | 36 | 36 | identifier（固定长度）|
| `notes` | 85 | 45 | 10 | 300 | description（长度波动）|

#### 规则 5：唯一性检查

```python
stats["uniqueness"] >= 0.7
```

**说明**：
- description 字段通常每条记录内容不同，唯一性较高
- 阈值 `0.7` 可配置

#### 规则 6：命名模式检查

```python
# 强匹配关键词（包含即判定为 description）
description_keywords = [
    "description", "desc", 
    "note", "notes", 
    "remark", "remarks", 
    "comment", "comments",
    "memo", 
    "explain", "explanation", 
    "detail", "details",
    "content", "text", "message"
]

# 排除关键词（包含即排除）
exclude_keywords = [
    "code", "_id", "_key", "_no", 
    "number", "uuid", "token"
]

# 判断逻辑
if any(kw in lower_name for kw in description_keywords):
    return True  # 强判定

if any(kw in lower_name for kw in exclude_keywords):
    return False  # 排除
```

### 3.3 决策流程图

```
┌─────────────────────────────────┐
│ 开始判断 description             │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│ 有 PK/FK/INDEX？                 │
└────────────┬────────────────────┘
             │
        ┌────┴────┐
        │Yes      │No
        ▼         ▼
    [排除]   ┌───────────────────┐
             │ text 或 varchar   │
             │ (>=256)？         │
             └────┬──────────────┘
                  │
             ┌────┴────┐
             │Yes      │No
             ▼         ▼
        ┌───────┐  [排除]
        │avg >= │
        │  50?  │
        └───┬───┘
            │
       ┌────┴────┐
       │Yes      │No
       ▼         ▼
  ┌─────────┐ [排除]
  │length   │
  │std < 5? │
  └────┬────┘
       │
  ┌────┴────┐
  │Yes      │No
  ▼         ▼
┌────────┐ ┌──────────┐
│包含    │ │std > 20  │
│exclude │ │or        │
│keywords│ │range>100?│
│?       │ │          │
└──┬─────┘ └────┬─────┘
   │            │
 Yes│No      Yes│No
   ▼  ▼         ▼  ▼
[排除] │    [description]
       │            │
       ▼            │
  ┌────────┐       │
  │包含desc│       │
  │关键词？│       │
  └───┬────┘       │
      │            │
   Yes│No          │
      ▼  ▼         │
      │[排除]      │
      │            │
      └────────────┴──→ [description]
```

**说明**：`exclude_keywords` 默认值为 `["code", "_id", "_key", "_no", "number", "uuid", "token"]`，可在配置文件中修改。

---

## 四、字符串长度统计实现

### 4.1 采样策略

**当前采样量**：1000 条记录（已有配置）

**采样方法**：随机采样（`TABLESAMPLE` 或 `ORDER BY RANDOM()`）

**是否足够**：
- ✅ 1000 条对于长度统计已足够可靠
- ✅ 性能开销可接受
- ⚠️ 如需更精确，可增加到 2000 条

### 4.2 统计指标

在 `src/metaweave/utils/data_utils.py` 的 `get_column_statistics` 函数中添加：

```python
# 对于字符串类型字段，计算以下指标
if pd.api.types.is_string_dtype(col_data) or col_data.dtype == object:
    non_null_data = col_data.dropna()
    
    if len(non_null_data) > 0:
        lengths = non_null_data.astype(str).str.len()
        
        stats.update({
            "avg_length": float(lengths.mean()),        # 平均长度
            "min_length": int(lengths.min()),           # 最短长度
            "max_length": int(lengths.max()),           # 最长长度
            "median_length": float(lengths.median()),   # 中位数长度
            "length_std": float(lengths.std()),         # 标准差（离散度）
        })
```

### 4.3 为什么需要 min/max？

| 指标 | 作用 | 示例 |
|------|------|------|
| **avg_length** | 判断是否为长文本 | >= 50 → 可能是 description |
| **length_std** | 判断长度稳定性 | < 5 → 固定编码；> 20 → 自由文本 |
| **min/max** | 计算长度范围 | max - min > 100 → 高离散度 |
| **median** | 辅助判断分布 | 与 avg 差异大 → 有异常值 |

**关键区分案例**：

```python
# 案例 1：字符串主键
order_code: avg=15, std=2, min=12, max=18
→ 长度稳定 → identifier

# 案例 2：备注字段
notes: avg=120, std=80, min=5, max=500
→ 长度波动大 → description

# 案例 3：UUID
uuid: avg=36, std=0, min=36, max=36
→ 固定长度 → identifier
```

---

## 五、技术实现方案

### 5.1 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `src/metaweave/utils/data_utils.py` | 在 `get_column_statistics` 中添加字符串长度统计 |
| `src/metaweave/core/metadata/models.py` | 新增 `DescriptionInfo` 数据类 |
| `src/metaweave/core/metadata/profiler.py` | 在 `_classify_semantics` 中添加 description 判断逻辑 |
| `src/metaweave/core/relationships/candidate_generator.py` | 更新排除角色列表，新增 `description` |
| `configs/metaweave/metadata_config.yaml` | 添加 description 检测配置项 + 更新 `single_column.exclude_semantic_roles` |
| `docs/gen_rag/3.1.数据画像模块改造说明.md` | 更新语义角色说明（6→7种） |
| `tests/unit/metaweave/metadata/test_profiler.py` | 更新测试用例（适配返回值变更） |

### 5.1.1 `_classify_semantics` 返回值变更影响

> ⚠️ **破坏性变更警告**
>
> `_classify_semantics` 方法的返回值从 **8 个元素**增加到 **9 个元素**（新增 `Optional[DescriptionInfo]`）。
> 所有调用该方法的代码都需要同步修改，否则会导致解包错误。

**受影响的调用位置**：

| 文件 | 方法 | 修改说明 |
|------|------|---------|
| `src/metaweave/core/metadata/profiler.py` | `_profile_column()` | 更新返回值解包，添加 `description_info` 变量 |
| `tests/unit/metaweave/metadata/test_profiler.py` | 相关测试方法 | 更新 mock 和断言 |

**修改示例**（`_profile_column` 方法）：

```python
# 修改前（8 个返回值）
(
    semantic_role,
    semantic_confidence,
    identifier_info,
    metric_info,
    datetime_info,
    enum_info,
    audit_info,
    inference_basis,
) = self._classify_semantics(column, stats, struct_flags)

# 修改后（9 个返回值）
(
    semantic_role,
    semantic_confidence,
    identifier_info,
    metric_info,
    datetime_info,
    enum_info,
    audit_info,
    description_info,  # 新增
    inference_basis,
) = self._classify_semantics(column, stats, struct_flags)
```

### 5.2 代码实现

#### 5.2.1 新增数据模型

在 `src/metaweave/core/metadata/models.py` 中：

```python
@dataclass
class DescriptionInfo:
    """描述字段信息"""
    avg_length: float           # 平均长度
    max_length: int             # 最大长度
    length_variance: float      # 长度方差
    is_rich_text: bool = False  # 是否包含富文本（HTML/Markdown）
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ColumnProfile:
    # ... 现有字段 ...
    description_info: Optional[DescriptionInfo] = None  # 新增
```

#### 5.2.2 添加默认值函数

在 `src/metaweave/core/metadata/profiler.py` 的配置辅助函数区域添加：

```python
def _default_description_keywords() -> List[str]:
    return [
        "description", "desc",
        "note", "notes",
        "remark", "remarks",
        "comment", "comments",
        "memo",
        "explain", "explanation",
        "detail", "details",
        "content", "text", "message"
    ]


def _default_description_exclude_keywords() -> List[str]:
    return ["code", "_id", "_key", "_no", "number", "uuid", "token"]
```

### 5.2.3 扩展 `ProfilingConfig` 类

在 `ProfilingConfig` 类中添加 description 相关字段：

```python
@dataclass
class ProfilingConfig:
    enum_threshold: int = 10
    metric_patterns: List[str] = field(default_factory=_default_metric_patterns)
    identifier_patterns: List[str] = field(default_factory=_default_identifier_patterns)
    audit_patterns: List[str] = field(default_factory=_default_audit_patterns)
    datetime_types: List[str] = field(default_factory=_default_datetime_types)
    allowed_identifier_types: List[str] = field(default_factory=_default_allowed_identifier_types)
    
    # === 新增：description 检测配置（扁平字段） ===
    description_enabled: bool = True
    description_min_varchar_length: int = 256
    description_min_avg_length: float = 50.0
    description_max_stable_std: float = 5.0
    description_min_variance_std: float = 20.0
    description_min_uniqueness: float = 0.7
    description_keywords: List[str] = field(default_factory=_default_description_keywords)
    description_exclude_keywords: List[str] = field(default_factory=_default_description_exclude_keywords)
    
    fact_rules: FactTableRules = field(default_factory=FactTableRules)
    dim_rules: DimTableRules = field(default_factory=DimTableRules)
    bridge_rules: BridgeTableRules = field(default_factory=BridgeTableRules)

    @classmethod
    def from_dict(cls, config: Optional[Dict]) -> "ProfilingConfig":
        """从嵌套配置字典创建扁平化的配置对象"""
        if not config:
            return cls()
        
        # ... 现有配置读取 ...
        enum_threshold = config.get("column_profiling", {}).get("enum_threshold", cls.enum_threshold)
        # ... 其他现有配置 ...
        
        # === 新增：读取 description 配置（从嵌套路径） ===
        desc_cfg = config.get("sampling", {}).get("description_detection", {})
        description_enabled = desc_cfg.get("enabled", True)
        description_min_varchar_length = desc_cfg.get("min_varchar_length", 256)
        description_min_avg_length = desc_cfg.get("min_avg_length", 50.0)
        description_max_stable_std = desc_cfg.get("max_stable_std", 5.0)
        description_min_variance_std = desc_cfg.get("min_variance_std", 20.0)
        description_min_uniqueness = desc_cfg.get("min_uniqueness", 0.7)
        description_keywords = desc_cfg.get("include_keywords", _default_description_keywords())
        description_exclude_keywords = desc_cfg.get("exclude_keywords", _default_description_exclude_keywords())
        
        return cls(
            enum_threshold=enum_threshold,
            # ... 其他现有字段 ...
            # === 新增字段 ===
            description_enabled=description_enabled,
            description_min_varchar_length=description_min_varchar_length,
            description_min_avg_length=description_min_avg_length,
            description_max_stable_std=description_max_stable_std,
            description_min_variance_std=description_min_variance_std,
            description_min_uniqueness=description_min_uniqueness,
            description_keywords=description_keywords,
            description_exclude_keywords=description_exclude_keywords,
            # ... 其他现有字段 ...
        )
```

**关键映射关系**：
| YAML 配置路径 | ProfilingConfig 字段 |
|---------------|---------------------|
| `sampling.description_detection.enabled` | `description_enabled` |
| `sampling.description_detection.min_avg_length` | `description_min_avg_length` |
| `sampling.description_detection.max_stable_std` | `description_max_stable_std` |
| `sampling.description_detection.include_keywords` | `description_keywords` |
| ... | ... |

### 5.2.4 修改 `_classify_semantics` 方法

在 `src/metaweave/core/metadata/profiler.py` 中：

```python
def _classify_semantics(
    self,
    column: ColumnInfo,
    stats: Optional[Dict],
    struct_flags: StructureFlags,
) -> Tuple[
    str,
    float,
    Optional[IdentifierInfo],
    Optional[MetricInfo],
    Optional[DateTimeInfo],
    Optional[EnumInfo],
    Optional[AuditInfo],
    Optional[DescriptionInfo],  # 新增
    List[str],
]:
    # ... 现有代码 ...
    
    # identifier detection (保持不变)
    is_id, id_confidence, matched_pattern, id_basis = self._is_identifier(...)
    if is_id:
        return ("identifier", id_confidence, ..., None, inference_basis)  # 最后一个 None 是 DescriptionInfo
    
    # === 新增：description detection ===
    if self.config.description_enabled and self._is_description(column, stats, struct_flags):
        inference_basis.append("description_text_pattern")
        avg_len = stats.get("avg_length", 0) if stats else 0
        max_len = stats.get("max_length", 0) if stats else 0
        length_var = stats.get("length_std", 0) if stats else 0
        
        return (
            "description",
            0.85,
            None, None, None, None, None,  # id/metric/datetime/enum/audit 都是 None
            DescriptionInfo(
                avg_length=avg_len,
                max_length=max_len,
                length_variance=length_var,
                is_rich_text=False
            ),
            inference_basis,
        )
    
    # enum detection (继续)
    # ...
```

#### 5.2.5 新增 `_is_description` 方法

```python
def _is_description(
    self,
    column: ColumnInfo,
    stats: Optional[Dict],
    struct_flags: StructureFlags
) -> bool:
    """判断是否为 description 角色
    
    通过 self.config 访问配置项，配置来自 metadata_config.yaml:
    - sampling.description_detection.min_varchar_length
    - sampling.description_detection.min_avg_length
    - 等等
    """
    
    # 1. 排除：有物理约束或被索引的字段
    if (struct_flags.is_primary_key or 
        struct_flags.is_foreign_key or 
        struct_flags.is_indexed):
        return False
    
    data_type = column.data_type.lower()
    lower_name = column.column_name.lower()
    
    # 2. 数据类型检查
    is_text_type = data_type == "text"
    is_long_varchar = (
        data_type in ("varchar", "character varying", "char") 
        and column.character_maximum_length 
        and column.character_maximum_length >= self.config.description_min_varchar_length  # 从配置读取
    )
    
    if not (is_text_type or is_long_varchar):
        return False
    
    if not stats:
        return False
    
    # 3. 平均长度检查（核心指标）
    avg_length = stats.get("avg_length", 0)
    if avg_length < self.config.description_min_avg_length:  # 从配置读取
        return False
    
    # 4. 长度稳定性检查
    length_std = stats.get("length_std", 0)
    max_length = stats.get("max_length", 0)
    min_length = stats.get("min_length", 0)
    
    # 如果长度非常稳定，可能是固定格式的编码
    # 注：此时 avg_length 已经 >= min_avg_length（默认50），无需再检查 avg_length > 20
    if length_std < self.config.description_max_stable_std:  # 从配置读取
        # 使用配置中的排除关键词
        if any(kw in lower_name for kw in self.config.description_exclude_keywords):
            return False  # 很可能是 identifier
    
    # 5. 唯一性检查
    uniqueness = stats.get("uniqueness", 0)
    if uniqueness < self.config.description_min_uniqueness:  # 从配置读取
        return False
    
    # 6. 命名模式检查（使用配置中的关键词列表）
    description_keywords = self.config.description_keywords
    exclude_keywords = self.config.description_exclude_keywords
    
    # 强匹配：包含 description 关键词
    if any(kw in lower_name for kw in description_keywords):
        return True
    
    # 排除：包含 identifier 关键词
    if any(kw in lower_name for kw in exclude_keywords):
        return False
    
    # 7. 如果长度离散度高，判定为 description
    length_range = max_length - min_length
    if length_std > self.config.description_min_variance_std or length_range > 100:  # 从配置读取
        return True
    
    return False
```

### 5.3 配置加载机制说明

**配置加载流程**：

```
metadata_config.yaml 
    ↓ (YAML 解析)
嵌套字典 config = {
    "sampling": {
        "description_detection": {
            "min_avg_length": 50,
            ...
        }
    }
}
    ↓ (ProfilingConfig.from_dict)
扁平化配置对象:
    self.config.description_min_avg_length = 50
    ↓ (在代码中访问)
if avg_length < self.config.description_min_avg_length:
    return False
```

**关键点**：
1. **YAML 配置**：嵌套结构 `sampling.description_detection.min_avg_length`
2. **加载代码**：在 `ProfilingConfig.from_dict()` 中读取嵌套路径
3. **使用代码**：通过扁平字段 `self.config.description_min_avg_length` 访问

这种设计的好处：
- ✅ YAML 中分组清晰（按模块组织）
- ✅ 代码中访问简洁（无需多层嵌套）
- ✅ 默认值集中管理（在 dataclass 定义中）

### 5.4 配置文件修改

在 `configs/metaweave/metadata_config.yaml` 中的 `sampling` 节点下添加：

```yaml
# 数据采样配置
sampling:
  enabled: true
  sample_size: 1000
  sample_method: limit
  
  # ... 现有的 column_statistics、enum_detection、identifier_detection 等 ...
  
  # === 新增：Description 检测配置 ===
  description_detection:
    enabled: true
    
    # 类型阈值
    min_varchar_length: 256       # varchar 最小长度（小于此值不考虑）
    
    # 长度统计阈值
    min_avg_length: 50            # 平均长度阈值（核心指标）
    max_stable_std: 5             # 稳定编码的最大标准差（用于排除固定格式编码）
    min_variance_std: 20          # 离散文本的最小标准差（高离散度强判定）
    
    # 其他阈值
    min_uniqueness: 0.7           # 最小唯一性
    
    # 命名模式（包含这些关键词倾向于识别为 description）
    include_keywords:
      - "description"
      - "desc"
      - "note"
      - "notes"
      - "remark"
      - "remarks"
      - "comment"
      - "comments"
      - "memo"
      - "explain"
      - "explanation"
      - "detail"
      - "details"
      - "content"
      - "text"
      - "message"
    
    # 排除关键词（包含这些关键词排除 description，倾向于 identifier）
    exclude_keywords:
      - "code"
      - "_id"
      - "_key"
      - "_no"
      - "number"
      - "uuid"
      - "token"
```

**配置路径说明**：
- 配置在 YAML 中的路径：`sampling.description_detection.*`
- 在代码中通过 `self.config.description_min_avg_length` 等扁平字段访问
- `ProfilingConfig.from_dict()` 方法负责从嵌套配置读取并映射到扁平字段

---

## 六、测试用例

### 6.1 正确识别为 description

| 字段名 | 类型 | avg | std | min | max | 约束 | 预期 |
|--------|------|-----|-----|-----|-----|------|------|
| `product_description` | text | 120 | 45 | 50 | 300 | - | ✅ description |
| `notes` | text | 85 | 60 | 5 | 400 | - | ✅ description |
| `remark` | varchar(500) | 65 | 35 | 10 | 200 | - | ✅ description |
| `fault_detail` | text | 150 | 80 | 20 | 500 | - | ✅ description |
| `explanation` | text | 200 | 100 | 30 | 800 | - | ✅ description |
| `recommended_action` | text | 60+ | 高 | - | - | - | ✅ description |

> **说明**：`fault_catalog.recommended_action` 字段虽然 `uniqueness=1.0`，但它是 `text` 类型、长度较长且离散度高，应该被正确识别为 `description` 而非逻辑主键候选。这是预期行为，因为"建议处理措施"字段不适合作为关联键。

### 6.2 正确识别为 identifier（避免误判）

| 字段名 | 类型 | avg | std | min | max | 约束 | 预期 |
|--------|------|-----|-----|-----|-----|------|------|
| `order_code` | text | 15 | 2 | 12 | 18 | PK | ✅ identifier |
| `product_id` | varchar(50) | 10 | 1 | 10 | 10 | FK | ✅ identifier |
| `serial_no` | text | 20 | 3 | 18 | 24 | UNIQUE | ✅ identifier |
| `uuid` | text | 36 | 0 | 36 | 36 | INDEX | ✅ identifier |
| `company_code` | text | 8 | 1 | 8 | 8 | - | ✅ identifier |

### 6.3 边界情况

| 字段名 | 类型 | avg | std | min | max | 约束 | 预期 | 原因 |
|--------|------|-----|-----|-----|-----|------|------|------|
| `short_desc` | varchar(100) | 25 | 10 | 10 | 50 | - | ❌ attribute | 平均长度 < 50 |
| `long_code` | text | 200 | 2 | 198 | 202 | - | ⚠️ identifier | 长度稳定 + 包含 code |
| `status_desc` | varchar(50) | 15 | 5 | 10 | 20 | - | ❌ attribute | varchar < 256 |
| `json_content` | text | 300 | 150 | 50 | 1000 | - | ✅ description | 长度波动大 |

---

## 七、与现有角色的关系

### 7.1 更新后的角色体系

| 序号 | 角色 | 优先级 | 典型示例 | 判断依据 |
|------|------|--------|----------|----------|
| 1 | `audit` | 最高 | `created_at`, `updated_by` | 命名模式（审计关键词）|
| 2 | `datetime` | 高 | `order_date`, `created_time` | 时间类型或命名 |
| 3 | `identifier` | 高 | `store_id`, `order_code` | 物理约束 + 类型 + 命名 |
| 4 | **`description`** | **中** | **`notes`, `remark`** | **长文本 + 长度离散** |
| 5 | `enum` | 中低 | `status`, `level` | 低基数 + 值分布 |
| 6 | `metric` | 中低 | `sales_amount`, `count` | 数值型 + 命名 |
| 7 | `attribute` | 最低 | `store_name`, `address` | 兜底分类 |

### 7.2 角色互斥性

所有语义角色**互斥**，每个字段只能属于一个角色。判断顺序按上表优先级。

### 7.3 在关联分析中的使用

在 `src/metaweave/core/relationships/candidate_generator.py` 中，需要更新排除规则：

#### 7.3.1 单列候选键

**从 YAML 配置读取**（`single_column.exclude_semantic_roles`）：

```yaml
# configs/metaweave/metadata_config.yaml
single_column:
  exclude_semantic_roles:
    - audit
    - metric
    - description  # 新增
```

```python
# 代码中读取配置
exclude_roles = config.get("single_column", {}).get("exclude_semantic_roles", ["audit", "metric", "description"])

if column_profile.semantic_role in exclude_roles:
    continue  # 跳过该字段
```

#### 7.3.2 复合键候选

**硬编码在代码中**（`composite_exclude_semantic_roles`）：

```python
# 在 candidate_generator.py 中
composite_exclude_semantic_roles = {"metric", "description"}  # 新增 description

if column_profile.semantic_role in composite_exclude_semantic_roles:
    continue  # 跳过该字段
```

#### 7.3.3 排除规则对比

| 候选类型 | 排除角色 | 配置方式 |
|---------|---------|---------|
| 单列候选 | `[audit, metric, description]` | YAML 配置（可修改） |
| 复合键候选 | `[metric, description]` | 硬编码 |

**设计说明**：
- **单列候选**：排除更严格，因为单列关联更容易误判
- **复合键候选**：只排除 `metric` 和 `description`，允许 `audit` 参与（如 `created_by` 可能与用户表关联）

**原因**：description 字段内容自由、长度大，不适合作为关联键。

---

## 八、实施建议

### 8.1 配置一致性检查清单

在实施前，请确保以下三处保持一致：

**✅ 第 1 处：YAML 配置文件路径**
```yaml
# configs/metaweave/metadata_config.yaml
sampling:
  description_detection:
    min_avg_length: 50  # ← 配置名
```

**✅ 第 2 处：ProfilingConfig 字段定义**
```python
@dataclass
class ProfilingConfig:
    description_min_avg_length: float = 50.0  # ← 扁平字段名
```

**✅ 第 3 处：ProfilingConfig.from_dict 读取**
```python
desc_cfg = config.get("sampling", {}).get("description_detection", {})
description_min_avg_length = desc_cfg.get("min_avg_length", 50.0)  # ← 读取路径
```

**✅ 第 4 处：代码中使用**
```python
if avg_length < self.config.description_min_avg_length:  # ← 访问方式
    return False
```

**命名规则**：
- YAML 中：`min_avg_length`（下划线分隔，简短）
- Config 中：`description_min_avg_length`（加前缀，避免冲突）

### 8.2 实施步骤

1. **阶段 1：基础实现**（1-2 小时）
   - 修改 `data_utils.py` 添加字符串长度统计
   - 新增 `DescriptionInfo` 数据模型
   - 添加默认值函数（`_default_description_keywords` 等）

2. **阶段 2：配置扩展**（1 小时）
   - 在 `ProfilingConfig` 类中添加 8 个 description 字段
   - 在 `from_dict` 方法中添加配置读取逻辑（**严格按照映射关系**）
   - 在 `metadata_config.yaml` 中添加 `sampling.description_detection` 配置

3. **阶段 3：核心逻辑**（2-3 小时）
   - 实现 `_is_description` 方法（使用 `self.config.description_*` 访问配置）
   - 修改 `_classify_semantics` 集成 description 判断
   - 更新返回值类型签名（添加 `DescriptionInfo`）

4. **阶段 4：测试验证**（1-2 小时）
   - 使用现有测试数据验证
   - 检查是否有误判（特别是 text 类型的主键）
   - 调整阈值

5. **阶段 5：文档更新**（30 分钟）
   - 更新数据画像文档
   - 更新 README 和 JSON 模板说明

### 8.3 回归测试重点

测试以下表是否受影响：

```bash
# 重新生成元数据
python -m src.metaweave.cli.main metadata \
  --config configs/metaweave/metadata_config.yaml \
  --step json

# 检查以下字段的语义角色是否正确
- maintenance_work_order.fault_description  # 应为 description
- equipment_config.notes                    # 应为 description
- fault_catalog.recommended_action          # 应为 description
- dim_store.store_code                      # 应为 identifier（不误判）
```

### 8.3.1 单元测试修改清单

由于 `_classify_semantics` 返回值变更，需要修改以下测试文件：

| 测试文件 | 修改内容 |
|---------|---------|
| `tests/unit/metaweave/metadata/test_profiler.py` | 更新返回值解包（8→9） |

**测试修改示例**：

```python
# 修改前
def test_classify_semantics_identifier(self):
    result = profiler._classify_semantics(column, stats, flags)
    assert len(result) == 8
    role, confidence, id_info, metric_info, dt_info, enum_info, audit_info, basis = result

# 修改后
def test_classify_semantics_identifier(self):
    result = profiler._classify_semantics(column, stats, flags)
    assert len(result) == 9  # 新增 DescriptionInfo
    role, confidence, id_info, metric_info, dt_info, enum_info, audit_info, desc_info, basis = result
```

**新增测试用例**：

```python
def test_classify_semantics_description(self):
    """测试 description 角色识别"""
    column = ColumnInfo(
        column_name="notes",
        data_type="text",
        # ...
    )
    stats = {
        "avg_length": 120,
        "length_std": 45,
        "min_length": 10,
        "max_length": 300,
        "uniqueness": 0.85,
    }
    struct_flags = StructureFlags()  # 无约束
    
    result = profiler._classify_semantics(column, stats, struct_flags)
    role, confidence, _, _, _, _, _, desc_info, _ = result
    
    assert role == "description"
    assert confidence == 0.85
    assert desc_info is not None
    assert desc_info.avg_length == 120

def test_classify_semantics_not_description_stable_length(self):
    """测试：长度稳定的 text 字段不应被识别为 description"""
    column = ColumnInfo(
        column_name="order_code",
        data_type="text",
        # ...
    )
    stats = {
        "avg_length": 15,
        "length_std": 2,  # 稳定
        "min_length": 12,
        "max_length": 18,
        "uniqueness": 0.99,
    }
    struct_flags = StructureFlags()
    
    result = profiler._classify_semantics(column, stats, struct_flags)
    role, _, _, _, _, _, _, desc_info, _ = result
    
    assert role != "description"
    assert desc_info is None
```

### 8.4 阈值调优建议

**初始值**（保守）：
```yaml
sampling:
  description_detection:
    min_avg_length: 50
    max_stable_std: 5
    min_variance_std: 20
    min_uniqueness: 0.7
```

**如果出现漏判**（description 未识别）：
- 降低 `min_avg_length` → 40
- 降低 `min_variance_std` → 15

**如果出现误判**（identifier 被误判为 description）：
- 提高 `min_avg_length` → 60
- 降低 `max_stable_std` → 3

**调整方法**：直接修改 `configs/metaweave/metadata_config.yaml` 中的对应值，无需改代码。

### 8.5 性能影响评估

**计算开销**：
- ✅ 字符串长度统计：O(n)，n = 采样数量（1000）
- ✅ 每个字符串字段额外计算：5 个统计指标（mean/std/min/max/median）
- ✅ 预计增加时间：< 10ms / 表

**内存开销**：
- ✅ 每个字段增加：5 个浮点数（~40 bytes）
- ✅ 预计增加内存：< 1KB / 表

**结论**：性能影响可忽略不计。

---

## 九、后续优化方向

### 9.1 富文本检测

未来可扩展检测 HTML/Markdown 格式的富文本：

```python
def _is_rich_text(value: str) -> bool:
    """检测是否为富文本"""
    html_tags = ["<p>", "<div>", "<br>", "<a>", "<img>"]
    markdown_patterns = ["##", "**", "- ", "1. ", "[", "]("]
    
    return any(tag in value for tag in html_tags) or \
           any(pattern in value for pattern in markdown_patterns)
```

### 9.2 多语言支持

不同语言的文本长度特征不同：
- 中文：平均长度较短（1 个字 = 1 个字符）
- 英文：平均长度较长（1 个词 ≈ 5-7 个字符）

可根据数据库字符集调整阈值。

### 9.3 机器学习方法

如果规则难以覆盖所有情况，可考虑：
- 使用 LLM 辅助判断（基于字段名 + 样例数据）
- 训练简单的分类模型（特征：长度统计 + 命名模式）

---

## 十、总结

### 10.1 核心要点

1. **description** 是第 **7** 种语义角色，专门识别长文本说明字段
2. **关键区分**：与 identifier 的区分依赖**长度离散度**（标准差）
3. **实施注意**：`_classify_semantics` 返回值变更为 **9 个元素**（新增 `DescriptionInfo`），需同步更新调用点
4. **关联分析**：单列排除 `[audit, metric, description]`（可配置），复合键排除 `[metric, description]`（硬编码）
5. **性能无忧**：额外开销 < 10ms/表

### 10.2 预期效果

- ✅ 准确识别 notes、remark、description 等字段
- ✅ 避免误判 text 类型的主键
- ✅ 在关联分析中自动排除 description 字段
- ✅ 为 NL2SQL 提供更精准的字段语义信息

### 10.3 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| **配置路径不一致** | 中 | **高** | **遵循配置一致性检查清单（8.1 节）** |
| **返回值解包错误** | 中 | **高** | **参照 5.1.1 节更新所有调用点** |
| 误判 text 主键为 description | 低 | 中 | 优先判断 identifier + 长度稳定性检查 |
| 漏判短 description 字段 | 中 | 低 | 可调整阈值（min_avg_length） |
| 性能下降 | 极低 | 低 | 统计计算开销 < 10ms |
| 配置复杂度增加 | 低 | 低 | 提供合理默认值 |

**特别注意**：

1. **配置不一致**会导致运行时 `AttributeError`，务必确保：
   - YAML 配置路径正确（`sampling.description_detection.*`）
   - `from_dict` 读取路径正确
   - Config 字段名与读取逻辑匹配
   - 代码中通过 `self.config.description_*` 访问

2. **返回值变更**会导致解包错误，务必确保：
   - 所有调用 `_classify_semantics` 的位置都更新为 9 元素解包
   - 相关单元测试同步更新

---

## 附录

### A. 完整配置映射表

| YAML 配置路径 | Config 字段名 | 类型 | 默认值 | 说明 |
|---------------|--------------|------|--------|------|
| `sampling.description_detection.enabled` | `description_enabled` | bool | `True` | 是否启用 description 检测 |
| `sampling.description_detection.min_varchar_length` | `description_min_varchar_length` | int | `256` | varchar 最小长度阈值 |
| `sampling.description_detection.min_avg_length` | `description_min_avg_length` | float | `50.0` | 平均长度阈值（核心） |
| `sampling.description_detection.max_stable_std` | `description_max_stable_std` | float | `5.0` | 稳定编码最大标准差 |
| `sampling.description_detection.min_variance_std` | `description_min_variance_std` | float | `20.0` | 离散文本最小标准差 |
| `sampling.description_detection.min_uniqueness` | `description_min_uniqueness` | float | `0.7` | 最小唯一性阈值 |
| `sampling.description_detection.include_keywords` | `description_keywords` | List[str] | 见下方 | 强匹配关键词列表 |
| `sampling.description_detection.exclude_keywords` | `description_exclude_keywords` | List[str] | 见下方 | 排除关键词列表 |

**默认关键词列表**：
```python
# include_keywords → description_keywords
["description", "desc", "note", "notes", "remark", "remarks", 
 "comment", "comments", "memo", "explain", "explanation", 
 "detail", "details", "content", "text", "message"]

# exclude_keywords → description_exclude_keywords
["code", "_id", "_key", "_no", "number", "uuid", "token"]
```

### B. 配置模板（完整）

```yaml
# 数据采样配置
sampling:
  enabled: true
  sample_size: 1000
  sample_method: limit
  
  # 列统计配置
  column_statistics:
    enabled: true
    value_distribution_threshold: 10
  
  # 枚举识别配置
  enum_detection:
    enabled: true
    simple_two_value:
      max_null_rate: 0.3
      min_occurrence_per_value: 2
      max_string_length: 20
  
  # 标识符识别配置
  identifier_detection:
    allowed_data_types:
      - integer
      - bigint
      - varchar
      # ... 其他类型
    high_uniqueness_threshold: 0.95
    min_non_null_rate: 0.80
    low_uniqueness_threshold: 0.05
    exclude_keywords:
      - name
      - nm
      # ... 其他关键词
  
  # === 新增：Description 检测配置 ===
  description_detection:
    enabled: true
    min_varchar_length: 256
    min_avg_length: 50
    max_stable_std: 5
    min_variance_std: 20
    min_uniqueness: 0.7
    include_keywords:
      - "description"
      - "desc"
      - "note"
      - "notes"
      - "remark"
      - "remarks"
      - "comment"
      - "comments"
      - "memo"
      - "explain"
      - "explanation"
      - "detail"
      - "details"
      - "content"
      - "text"
      - "message"
    exclude_keywords:
      - "code"
      - "_id"
      - "_key"
      - "_no"
      - "number"
      - "uuid"
      - "token"
```

**注意**：配置在 `sampling.description_detection` 路径下，与 `identifier_detection`、`enum_detection` 同级。

### C. 相关文档

- 《3.1.数据画像模块改造说明.md》- 语义角色设计
- 《step 3.关联字段查找算法详解_v3.2.md》- 候选筛选规则
- 《Identifier 字段判断规则.md》- identifier 规则详解

### D. 实施前自检清单

在开始编码前，请确认以下事项：

- [ ] 已阅读并理解 **8.1 节《配置一致性检查清单》**
- [ ] 已阅读并理解 **5.1.1 节《返回值变更影响》**
- [ ] 已查看附录 A《完整配置映射表》，理解映射关系
- [ ] 已在本地准备好测试数据（包含 text 类型主键和 description 字段）
- [ ] 已备份当前的 `profiler.py` 和 `metadata_config.yaml`
- [ ] 已创建 Git 分支用于开发
- [ ] 已了解现有的配置加载机制（`ProfilingConfig.from_dict`）
- [ ] 已定位所有调用 `_classify_semantics` 的代码位置

### E. 联系方式

如有问题或建议，请联系：[项目负责人]

---

**文档版本**：v1.1  
**创建日期**：2025-12-03  
**最后更新**：2025-12-03

### 版本历史

| 版本 | 日期 | 修改内容 |
|------|------|---------|
| v1.0 | 2025-12-03 | 初始版本 |
| v1.1 | 2025-12-03 | 1. 明确关联分析中单列/复合键的排除规则差异<br>2. 添加返回值变更影响说明<br>3. 添加单元测试修改清单<br>4. 修复流程图与代码不一致问题<br>5. 移除冗余的 `avg_length > 20` 检查 |

