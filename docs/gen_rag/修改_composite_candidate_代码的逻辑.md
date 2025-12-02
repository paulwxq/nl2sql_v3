---

## 文档更新日志

**最新更新时间：** 2025-12-01

**主要更新内容：**
1. ✅ 补充了集合匹配算法（`_match_columns_as_set`）的详细实现（**改用穷举排列算法**，避免贪心误判）
2. ✅ 补充了辅助方法的实现细节（已删除，改为保留原有方法）
3. ✅ **明确 `dynamic_same_name` 为默认行为**：总是执行阶段二，不需要在配置中出现，简化配置
4. ✅ 补充了配置文件修改方案（metadata_config.yaml）
5. ✅ 明确了边界条件和实现要点（索引收集策略、阶段二触发条件等）
6. ✅ 增加了总结对比和改造收益说明
7. ✅ **修正了所有伪代码的实现细节**（变量来源、函数调用、逻辑判断等）
8. ✅ **修正目标3描述**：从"严格全表搜索"改为"保留dynamic_same_name作为默认兜底"
9. ✅ **修正组合收集逻辑**：源表组合收集**不依赖**`target_sources`配置，总是收集PK/UK/Logical
10. ✅ **删除语义角色过滤**：复合键不过滤包含 audit/metric 的主键/唯一约束，尊重数据库设计
11. ✅ **简化索引策略**：删除"unique_only"策略，改为布尔值（False/True），符合PostgreSQL特性（UK自动创建索引）
12. ✅ **明确参数对应关系**：在文档中详细说明 `_match_columns_as_set` 方法的参数与YAML配置的对应关系
13. ✅ **保留现有配置格式**：使用 `min_type_compatibility` 参数名，保持与现有配置兼容；`name_similarity_normal_target` 注释但保留
14. ✅ **统一类型兼容性检查**：阶段一和阶段二都使用 `_get_type_compatibility_score` + `min_type_compatibility` 阈值，保持一致性
15. ✅ **简化 target_sources 配置**：只保留 `composite_indexes` 选项，其他选项（PK/UK/Logical/dynamic_same_name）总是启用，不需要配置
16. ✅ **明确配置与布尔参数的关联**：`"composite_indexes" in self.target_sources` → `include_indexes=True/False`

---

### 一、改造目标（复合键候选）

**目标：**
优化 `CandidateGenerator` 中的复合键（多列）匹配逻辑，解决以下问题：
1.  源表不应将普通索引作为外键发起的依据（只保留 PK/UK/逻辑主键）。
2.  目标表应充分利用索引信息来降低匹配门槛（特权模式：允许乱序 + 低阈值）。
3.  保留精确同名匹配作为默认兜底方案（dynamic_same_name 总是执行）。
4.  尊重数据库约束设计，不过滤包含 audit/metric 的主键/唯一约束。

---

### 二、核心函数修改建议

#### 1. `_collect_source_combinations`

**功能变更：**
*   增加参数 `include_indexes: bool = False`：
    - `False`: 不收集索引（默认，用于源表）
    - `True`: 收集所有索引（用于目标表）

**重要说明：**
- **UK = Unique Constraints（唯一约束）**
- PostgreSQL 中，唯一约束会自动创建支持索引，DDL 中显示的是唯一约束
- 源表只需收集 `unique_constraints`，不需要从 `indexes` 中查找"唯一索引"
- **不过滤语义角色**：如果主键/唯一约束包含 audit/metric 字段，说明这是数据库设计的一部分，应该保留

**完整实现逻辑：**

```python
def _collect_source_combinations(self, table: dict, include_indexes: bool = False) -> List[Dict[str, Any]]:
    """收集表的复合键组合
    
    Args:
        table: 表元数据
        include_indexes: 是否收集索引
            - False: 不收集索引（默认，用于源表）
            - True: 收集所有索引（用于目标表）
    
    Returns:
        组合列表，每个组合: {"columns": [...], "type": "physical|logical"}
    """
    combinations = []
    table_profile = table.get("table_profile", {})
    column_profiles = table.get("column_profiles", {})
    
    # 1. 收集物理约束（PK/UK/Index）
    # ⚠️ 重要：不检查 target_sources 配置，总是收集 PK/UK
    physical = table_profile.get("physical_constraints", {})
    
    # 1.1 收集 PK（Primary Key 主键）- 无条件
    pk = physical.get("primary_key")
    if pk and pk.get("columns"):
        pk_cols = pk["columns"]
        if 2 <= len(pk_cols) <= self.max_columns:
            combinations.append({"columns": pk_cols, "type": "physical"})
    
    # 1.2 收集 UK（Unique Constraints 唯一约束）- 无条件
    for uk in physical.get("unique_constraints", []):
        uk_cols = uk.get("columns", [])
        if 2 <= len(uk_cols) <= self.max_columns:
            combinations.append({"columns": uk_cols, "type": "physical"})
    
    # 1.3 收集 Index（索引）- 根据 include_indexes 参数
    if include_indexes:
        for idx in physical.get("indexes", []):
            idx_cols = idx.get("columns", [])
            if 2 <= len(idx_cols) <= self.max_columns:
                combinations.append({"columns": idx_cols, "type": "physical"})
    
    # 2. 收集逻辑主键
    # ⚠️ 重要：不检查 target_sources 配置，总是收集
    logical_keys = table_profile.get("logical_keys", {})
    for lk in logical_keys.get("candidate_primary_keys", []):
        lk_cols = lk.get("columns", [])
        lk_conf = lk.get("confidence_score", 0)
        if 2 <= len(lk_cols) <= self.max_columns and lk_conf >= self.logical_key_min_confidence:
            combinations.append({"columns": lk_cols, "type": "logical"})
    
    return combinations
```

**关键点说明：**
1. **索引策略简化为布尔值**：
   - 源表：`include_indexes=False`，不收集索引（只收集PK/UK）
   - 目标表：`include_indexes=True`，收集所有索引
2. **UK = Unique Constraints（唯一约束）**：PostgreSQL中唯一约束会自动创建索引，DDL中显示的是唯一约束，不需要从索引中查找"唯一索引"
3. **⚠️ 重要：收集逻辑不依赖配置**：无论 `target_sources` 配置如何，都会收集 PK/UK/逻辑主键。`target_sources` 只控制目标表的**匹配策略**，不影响源表的组合收集。
4. **不过滤语义角色**：不对 audit/metric 字段进行过滤，尊重数据库约束设计

#### 2. `_generate_composite_candidates` (主循环)

**功能变更：**
*   调用 `_collect_source_combinations` 时，源表使用 `include_indexes=False`（不收集索引）。

**调用点修改：**

```python
# 源表收集：PK + UK + Logical（不收集索引）
source_combinations = self._collect_source_combinations(source_table, include_indexes=False)
```

**设计说明：**
- **源表只收集强约束**：PK（主键）、UK（唯一约束）、Logical（逻辑主键）
- **不收集索引**：普通索引不是强约束，不应作为外键源头
- **UK已足够**：PostgreSQL中的唯一约束（UK）会自动创建支持索引，不需要从 `indexes` 中再查找

#### 3. `_find_target_columns` (核心匹配逻辑重写)

**功能变更：**
*   废弃原有的 `_is_compatible_combination` 方法（平均分匹配）。
*   实现 **两阶段匹配策略**：
    - 阶段一：特权模式（基于目标表约束，低阈值）
    - 阶段二：精确同名匹配（dynamic_same_name，**总是执行**）

**完整实现逻辑：**

```python
def _find_target_columns(self, source_columns, source_table, target_table, combo_type) -> List[str]:
    """在目标表中查找匹配的列组合
    
    两阶段匹配策略：
    1. 阶段一：特权模式 - 基于目标表约束（低阈值，允许乱序）
    2. 阶段二：精确同名匹配 - dynamic_same_name（总是执行，作为兜底）
    
    Args:
        source_columns: 源列列表
        source_table: 源表元数据
        target_table: 目标表元数据
        combo_type: 组合类型（physical|logical）
    
    Returns:
        目标列列表（保持源列顺序），未找到返回None
    """
    
    # --- 阶段一：特权模式 (基于目标表约束) ---
    # 根据配置决定是否收集索引
    include_indexes = "composite_indexes" in self.target_sources
    
    # 获取目标表的所有组合（PK/UK/Logical 总是收集，索引根据配置）
    target_combinations = self._collect_source_combinations(target_table, include_indexes=include_indexes)
    
    for target_combo in target_combinations:
        target_cols = target_combo["columns"]
        
        # A. 数量检查
        if len(target_cols) != len(source_columns):
            continue
            
        # B. 集合匹配 (允许乱序) + 低阈值
        # 使用特权模式阈值：name_similarity_important_target, min_type_compatibility
        matched_ordered_target = self._match_columns_as_set(
            source_columns, target_cols, 
            source_table, target_table,
            name_threshold=self.name_similarity_important_target,  # 0.6（来自配置）
            type_threshold=self.min_type_compatibility  # 0.8（来自配置）
        )
        
        if matched_ordered_target:
            return matched_ordered_target  # 找到特权匹配，直接返回

    # --- 阶段二：精确同名匹配（总是执行，作为兜底）---
    matched = self._find_dynamic_same_name(source_columns, source_table, target_table)
    if matched:
        return matched
    
    # 未找到匹配
    return None
```

**设计说明：**
1. **dynamic_same_name 总是执行**：作为默认兜底方案，不需要配置控制
2. **两阶段策略**：先尝试特权模式（灵活），再尝试精确同名（严格）
3. **特权模式使用配置阈值**：
   - 名称相似度：从 `self.name_similarity_important_target` 读取（默认0.6）
   - 类型兼容性：从 `self.min_type_compatibility` 读取（默认0.8）

#### 4. `_match_columns_as_set` (新增辅助方法 - 集合匹配算法)

**功能：** 实现阶段一的集合匹配（允许乱序），使用**穷举排列算法**找到最优匹配。

**完整实现逻辑：**

```python
from itertools import permutations

def _match_columns_as_set(
    self,
    source_columns: List[str],
    target_columns: List[str],
    source_table: dict,
    target_table: dict,
    name_threshold: float,
    type_threshold: float
) -> Optional[List[str]]:
    """集合匹配（允许乱序）- 穷举排列算法
    
    算法步骤：
    1. 穷举目标列的所有排列（2列=2种，3列=6种）
    2. 对每个排列，检查所有源列-目标列配对是否满足阈值
    3. 选择综合分数最高的排列
    4. 返回匹配结果（保持源列顺序）
    
    Args:
        source_columns: 源列列表（顺序固定）
        target_columns: 目标列列表（待排列）
        source_table: 源表元数据
        target_table: 目标表元数据
        name_threshold: 名称相似度阈值
        type_threshold: 类型兼容性阈值
    
    Returns:
        匹配成功返回目标列顺序列表（保持源列顺序），否则返回None
        例如：source_columns = ["id", "type"]
             返回 ["store_id", "store_type"] 表示 id->store_id, type->store_type
    """
    if len(source_columns) != len(target_columns):
        return None
    
    source_profiles = source_table.get("column_profiles", {})
    target_profiles = target_table.get("column_profiles", {})
    
    best_match = None
    best_score = -1
    
    # 穷举目标列的所有排列
    for target_perm in permutations(target_columns):
        all_pass = True
        total_score = 0
        
        # 检查这个排列下，所有配对是否满足阈值
        for src_col, tgt_col in zip(source_columns, target_perm):
            # 计算名称相似度和类型兼容性
            name_sim = self._calculate_name_similarity(src_col, tgt_col)
            
            src_type = source_profiles.get(src_col, {}).get("data_type", "")
            tgt_type = target_profiles.get(tgt_col, {}).get("data_type", "")
            type_compat = self._get_type_compatibility_score(src_type, tgt_type)
            
            # 检查是否满足阈值
            if name_sim < name_threshold or type_compat < type_threshold:
                all_pass = False
                break
            
            # 累加综合分数（名称和类型各占50%权重）
            total_score += name_sim * 0.5 + type_compat * 0.5
        
        # 如果这个排列所有配对都满足阈值，且分数更高
        if all_pass and total_score > best_score:
            best_score = total_score
            best_match = list(target_perm)
    
    return best_match
```

**算法复杂度：** O(n! × n)，对于 max_columns=3，最多 3! × 3 = 18 次计算，完全可接受。

**设计说明：**
- **为什么不用贪心？** 贪心算法可能因局部最优陷入死胡同，即使换个顺序就能全部匹配。对于 2-3 列场景，穷举只需 2-6 次尝试，代价很小。
- **返回值保持源列顺序**：`matched_result[i]` 对应 `source_columns[i]` 的匹配列。
- **选择最优排列**：如果多个排列都满足阈值，选择综合分数最高的。
- **阈值硬性要求**：任一配对不满足阈值，该排列立即被排除。

**参数来源说明：**

调用时传入的阈值参数来自配置文件：

| 参数 | 对应配置 | 默认值 | 说明 |
|:---|:---|:---|:---|
| `name_threshold` | `composite.name_similarity_important_target` | 0.6 | 目标列是关键字段（PK/UK/索引）时的名称相似度阈值 |
| `type_threshold` | `composite.min_type_compatibility` | 0.8 | 类型兼容性阈值 |

**示例调用：**
```python
# 在 _find_target_columns 中调用
matched = self._match_columns_as_set(
    source_columns, target_cols,
    source_table, target_table,
    name_threshold=self.name_similarity_important_target,  # 从配置读取
    type_threshold=self.min_type_compatibility  # 从配置读取
)
```

**示例：**
```python
source_columns = ["company_id", "type_id"]
target_columns = ["type_code", "company_code"]

# 尝试排列1: ["type_code", "company_code"]
#   company_id vs type_code: name_sim=0.3 < 0.6 ❌ 失败

# 尝试排列2: ["company_code", "type_code"]
#   company_id vs company_code: name_sim=0.8, type_compat=0.9 ✅
#   type_id vs type_code: name_sim=0.7, type_compat=1.0 ✅
#   综合分数 = (0.8*0.5+0.9*0.5) + (0.7*0.5+1.0*0.5) = 1.7 ✅ 成功

# 返回: ["company_code", "type_code"]
```

#### 5. 修改 `_find_dynamic_same_name` 方法（类型兼容性检查）

**说明：** 保留原有的 `_find_dynamic_same_name` 方法（大小写不敏感的精确同名匹配），作为默认的阶段二。

**功能变更：** 修改类型兼容性检查逻辑，使用评分方式而非布尔判断。

**修改前（旧逻辑）：**
```python
# 使用 _is_type_compatible 方法（返回布尔值）
if not self._is_type_compatible(src_type, tgt_type):
    return None  # 类型不兼容，匹配失败
```

**修改后（新逻辑）：**
```python
def _find_dynamic_same_name(
    self,
    source_columns: List[str],
    source_table: dict,
    target_table: dict
) -> List[str]:
    """动态同名匹配（大小写不敏感 + 类型兼容性评分）
    
    步骤：
    1. 大小写不敏感的同名检查
    2. 类型兼容性评分检查（使用 min_type_compatibility 阈值）
    """
    source_profiles = source_table.get("column_profiles", {})
    target_profiles = target_table.get("column_profiles", {})
    
    # 构建大小写不敏感的映射（小写列名 -> 原始列名）
    target_column_map = {col_name.lower(): col_name for col_name in target_profiles.keys()}
    
    matched = []
    
    for src_col in source_columns:
        src_col_lower = src_col.lower()
        
        # 1. 大小写不敏感的同名检查
        if src_col_lower not in target_column_map:
            return None
        
        # 获取目标列的原始名称
        tgt_col = target_column_map[src_col_lower]
        
        # 2. 类型兼容性评分检查（关键修改！）
        src_profile = source_profiles.get(src_col, {})
        tgt_profile = target_profiles.get(tgt_col, {})
        
        src_type = src_profile.get("data_type", "")
        tgt_type = tgt_profile.get("data_type", "")
        
        # 使用类型兼容性评分，而非布尔判断
        type_compat_score = self._get_type_compatibility_score(src_type, tgt_type)
        
        # 检查是否达到阈值
        if type_compat_score < self.min_type_compatibility:  # 默认 0.8
            return None  # 类型兼容性不足，匹配失败
        
        matched.append(tgt_col)
    
    return matched if len(matched) == len(source_columns) else None
```

**设计理由：**

1. **一致性**：阶段一和阶段二使用相同的类型兼容性评分逻辑
2. **灵活性**：使用评分 + 阈值方式比布尔判断更精细，可以接受部分兼容的类型
3. **可配置性**：使用 `min_type_compatibility` 参数（默认0.8），用户可以调整阈值
4. **与阶段一保持一致**：两个阶段都使用 `_get_type_compatibility_score` + `min_type_compatibility`

**关键修改点：**
- **修改前**：`self._is_type_compatible(src_type, tgt_type)` （返回布尔值，阈值硬编码）
- **修改后**：`self._get_type_compatibility_score(src_type, tgt_type) >= self.min_type_compatibility` （返回评分，阈值可配置）

**两阶段类型兼容性检查对比：**

| 阶段 | 名称匹配方式 | 类型兼容性检查方式 | 阈值来源 |
|:---|:---|:---|:---|
| **阶段一（特权模式）** | 穷举排列匹配 | `_get_type_compatibility_score` | `min_type_compatibility` (0.8) |
| **阶段二（精确同名）** | 精确同名（不区分大小写） | `_get_type_compatibility_score` | `min_type_compatibility` (0.8) |

**示例：**
```python
# INTEGER vs BIGINT
# _is_type_compatible: True (布尔)
# _get_type_compatibility_score: 0.9 (评分)
# 0.9 >= 0.8: True ✅ 通过

# INTEGER vs VARCHAR
# _is_type_compatible: False (布尔)
# _get_type_compatibility_score: 0.0 (评分)
# 0.0 >= 0.8: False ❌ 不通过

# DATE vs TIMESTAMP
# _is_type_compatible: True (布尔，可能过于宽松)
# _get_type_compatibility_score: 0.5 (评分，更精确)
# 0.5 >= 0.8: False ❌ 不通过（更严格）
```

---

### 三、配置文件修改（metadata_config.yaml）

#### 修改 `composite` 配置节：

```yaml
# 复合键候选配置
composite:
  max_columns: 3  # 最多考虑3列的复合键
  
  target_sources:
    - composite_indexes  # 是否在目标表匹配时收集索引（唯一有实际作用的配置）
    # 注意：
    # - PK/UK/Logical 总是收集，不需要在这里配置
    # - dynamic_same_name 总是执行，不需要在这里配置
    # - 如果不想收集索引，删除 composite_indexes 即可
  
  logical_key_min_confidence: 0.8  # 逻辑主键最低置信度阈值
  min_type_compatibility: 0.8  # 最低类型兼容性阈值（用于阶段一和阶段二）
  name_similarity_important_target: 0.6  # 目标列是关键字段时的名称相似度阈值（用于阶段一特权模式）
  # name_similarity_normal_target: 0.9     # 目标列是普通字段时的名称相似度阈值（已废弃，新设计中不再使用）
```

> **说明**：`single_column` 配置中原有的 `logical_key_min_confidence` / `min_type_compatibility` / `name_similarity_important_target` 字段仍会保留，继续供单列候选读取；此处仅是在 `composite` 下增加同名字段，让复合候选拥有独立配置，两套逻辑互不干扰。

**重要说明：**

1. **`target_sources` 只有一个有效选项**：
   - `composite_indexes`：控制目标表匹配时是否收集索引
   - PK/UK/Logical 总是收集，不受此配置影响
   - dynamic_same_name 总是执行，不受此配置影响

2. **原有配置已废弃**：`min_name_similarity` 已被 `name_similarity_important_target` 替代。

3. **保留的配置**：`min_type_compatibility` 保持不变，用于类型兼容性阈值（阶段一和阶段二都使用）。

4. **废弃但保留的配置**：`name_similarity_normal_target` 在新设计中不再使用（已注释），但保留在配置文件中以便将来扩展。

5. **不再需要语义角色过滤配置**：复合键不过滤包含 audit/metric 的主键/唯一约束，尊重数据库设计。

#### 代码中加载配置的修改：

```python
# 在 CandidateGenerator.__init__ 中
composite_config = config.get("composite", {})

# 复合键基本配置
self.max_columns = composite_config.get("max_columns", 3)
self.target_sources = composite_config.get("target_sources", [])
# 注意：target_sources 只用于检查 "composite_indexes" 是否存在
# - 如果包含 "composite_indexes"，目标表匹配时收集索引
# - PK/UK/Logical 总是收集，不检查 target_sources
# - dynamic_same_name 总是执行，不检查 target_sources

# 特权模式阈值（阶段一使用）
self.name_similarity_important_target = composite_config.get("name_similarity_important_target", 0.6)
self.min_type_compatibility = composite_config.get("min_type_compatibility", 0.8)

# 注意：
# - name_similarity_normal_target 在新设计中不再使用，但保留在配置文件中
# - 复合键不需要 exclude_semantic_roles 配置，不过滤语义角色
```

#### 配置说明：

| 配置项 | 用途 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `max_columns` | 复合键最大列数 | 3 | 最多考虑几列的复合键 |
| `target_sources` | 索引收集控制 | `[]` | **仅用于控制是否收集索引**<br>- 包含 `composite_indexes`：目标表匹配时收集索引<br>- 不包含或为空：目标表匹配时不收集索引<br>- PK/UK/Logical 总是收集，不受影响<br>- dynamic_same_name 总是执行，不受影响 |
| `logical_key_min_confidence` | 逻辑主键最低置信度 | 0.8 | 收集逻辑主键时的最低置信度阈值 |
| `name_similarity_important_target` | 特权模式名称阈值 | 0.6 | **用于阶段一**：目标列是关键字段（PK/UK/索引）时的名称相似度阈值 |
| `min_type_compatibility` | 类型兼容性阈值 | 0.8 | **用于阶段一和阶段二**：类型兼容性阈值 |
| `name_similarity_normal_target` | （已废弃） | 0.9 | 已注释，新设计中不再使用，但保留在配置中 |

**废弃配置：**
- ~~`min_name_similarity`~~：被 `name_similarity_important_target` 替代
- ~~`name_similarity_normal_target`~~：新设计中不再使用（阶段三已删除），但保留在配置文件中
- ~~`exclude_semantic_roles`~~：复合键不再需要此配置，不过滤语义角色
- ~~`physical_constraints`~~（在 target_sources 中）：PK/UK 总是收集，不需要配置
- ~~`candidate_logical_keys`~~（在 target_sources 中）：Logical Key 总是收集，不需要配置
- ~~`dynamic_same_name`~~（在 target_sources 中）：总是执行，不需要配置

---

### 四、实现要点与边界条件

#### 4.1 索引收集策略

**PostgreSQL 特性说明：**
- 在PostgreSQL中，创建唯一约束（UNIQUE CONSTRAINT）时会自动创建一个支持索引
- DDL中显示的是唯一约束，而不是"唯一索引"
- 元数据中的 `unique_constraints` 数组已经包含了所有唯一约束
- **不需要从 `indexes` 数组中查找"唯一索引"**

**收集策略：**

| 场景 | include_indexes 参数 | 收集内容 | 说明 |
|:---|:---|:---|:---|
| **源表** | `False` | PK + UK + Logical | 只收集强约束，不收集索引 |
| **目标表（阶段一）** | `True` | PK + UK + **所有索引** + Logical | 作为特权依据，降低匹配门槛 |
| **目标表（阶段二）** | N/A | 使用 `_find_dynamic_same_name` | 精确同名匹配 |

**术语说明：**
- **PK**：Primary Key（主键）
- **UK**：Unique Constraints（唯一约束）
- **Logical**：Logical Key（逻辑主键，由算法推断）
- **索引**：普通索引（非唯一），仅目标表作为特权依据

#### 4.2 `target_sources` 配置的作用域

**⚠️ 关键澄清：** `target_sources` **只控制目标表匹配时是否收集索引**，不影响其他任何逻辑。

**正确理解：**

| 配置项 | 作用域 | 影响 |
|:---|:---|:---|
| `target_sources: ["composite_indexes"]` | **目标表索引收集** | 只控制阶段一是否收集索引 |
| PK/UK 收集 | **总是执行** | 不检查 `target_sources`，总是收集 |
| Logical Key 收集 | **总是执行** | 不检查 `target_sources`，总是收集 |
| 源表组合收集 | **无条件执行** | 总是收集 PK/UK/Logical（不收集索引），不受配置影响 |
| dynamic_same_name | **总是执行** | 总是执行阶段二，不检查 `target_sources` |

**错误示例（现有代码的问题）：**
```python
# ❌ 错误！不应该根据 target_sources 决定是否收集 PK/UK/Logical
if "physical_constraints" in self.target_sources:
    收集 PK/UK

if "candidate_logical_keys" in self.target_sources:
    收集 Logical

if "dynamic_same_name" in self.target_sources:
    执行动态同名匹配
```

**正确示例（新设计）：**
```python
# ✅ 正确！_collect_source_combinations 不检查 target_sources
def _collect_source_combinations(self, table, include_indexes=False):
    # 总是收集 PK/UK（不检查配置）
    收集 PK
    收集 UK
    
    # 根据参数决定是否收集索引
    if include_indexes:
        收集索引
    
    # 总是收集 Logical（不检查配置）
    收集 Logical
    
    return combinations

# ✅ 正确！_find_target_columns 只用 target_sources 控制索引收集
def _find_target_columns(self, ...):
    # 根据配置决定是否收集索引
    include_indexes = "composite_indexes" in self.target_sources
    
    # 阶段一：特权模式
    target_combinations = self._collect_source_combinations(
        target_table, 
        include_indexes=include_indexes  # ← 与配置关联
    )
    # ... 穷举排列匹配 ...
    
    # 阶段二：动态同名（总是执行，不检查配置）
    matched = self._find_dynamic_same_name(...)
    if matched:
        return matched
```

#### 4.3 `composite_indexes` 配置的作用

**配置含义：** 控制目标表匹配（阶段一）时是否收集索引。

**使用场景：**

| 配置 | 目标表收集内容 | 适用场景 |
|:---|:---|:---|
| `target_sources: ["composite_indexes"]` | PK + UK + **索引** + Logical | 数据质量高，索引设计合理，希望降低匹配门槛 |
| `target_sources: []` 或不包含 `composite_indexes` | PK + UK + Logical | 数据质量未知，希望只匹配强约束 |

**代码实现：**

```python
# 在 _find_target_columns 中
def _find_target_columns(self, source_columns, source_table, target_table, combo_type):
    # 阶段一：特权模式
    include_indexes = "composite_indexes" in self.target_sources  # ← 检查配置
    
    target_combinations = self._collect_source_combinations(
        target_table, 
        include_indexes=include_indexes  # ← 传递给方法
    )
    
    # 如果 include_indexes=True，target_combinations 包含索引
    # 如果 include_indexes=False，target_combinations 不包含索引
    for target_combo in target_combinations:
        # ... 穷举排列匹配 ...
```

**设计说明：**

1. **源表永远不收集索引**：`_generate_composite_candidates` 调用时传 `include_indexes=False`
2. **目标表根据配置决定**：`_find_target_columns` 中根据 `target_sources` 决定
3. **默认建议启用**：索引通常反映了表的查询模式，包含索引可以提高匹配成功率

#### 4.4 阶段二的执行逻辑

**执行逻辑：** 阶段二（dynamic_same_name）**总是执行**，作为兜底方案。

```python
# 阶段一失败后，总是尝试阶段二
matched = self._find_dynamic_same_name(source_columns, source_table, target_table)
if matched:
    return matched

# 未找到匹配
return None
```

**设计说明：**
- **无需配置**：dynamic_same_name 是默认行为，不在 `target_sources` 中配置
- **总是作为兜底**：阶段一失败后自动尝试，确保不遗漏精确同名的匹配
- **类型兼容性检查**：使用 `_get_type_compatibility_score` + `min_type_compatibility` 阈值（与阶段一一致）
- **风险可控**：虽然不要求目标列有约束，但精确同名（大小写不敏感）+ 类型兼容性评分（≥0.8）的要求已经足够严格

**类型兼容性检查细节：**

| 检查项 | 方法 | 阈值 | 说明 |
|:---|:---|:---|:---|
| 名称匹配 | 精确同名（大小写不敏感） | 100% | 必须完全相同 |
| 类型兼容性 | `_get_type_compatibility_score` | `min_type_compatibility` (0.8) | 使用评分方式，与阶段一一致 |

#### 4.5 保持不变的参数

以下参数保持原有配置和逻辑，不做修改：
- `logical_key_min_confidence: 0.8`：逻辑主键的最低置信度阈值
- `max_columns: 3`：复合键最多列数
- `_calculate_name_similarity` 方法：名称相似度计算逻辑
- `_get_type_compatibility_score` 方法：类型兼容性评分逻辑
- `_normalize_type` 方法：类型标准化逻辑

---

### 五、总结对比

| 特性 | 旧逻辑 | **新逻辑** |
| :--- | :--- | :--- |
| **源表组合** | 包含普通索引 | **排除所有索引** (只收集 PK/UK/Logical) |
| **目标表组合** | 不明确索引处理 | **明确包含所有索引** (作为特权依据) |
| **UK说明** | 无明确说明 | **UK = Unique Constraints（唯一约束）**，自动包含支持索引 |
| **匹配方式** | 顺序敏感 + 平均分达标 | **阶段一：** 基于约束，穷举排列(乱序) + 低阈值(0.6/0.8)<br>**阶段二：** 精确同名匹配（**总是执行**） |
| **匹配算法** | 固定顺序配对 | **穷举排列算法**（2-3列，最多6种排列） |
| **语义角色过滤** | 单列有过滤 | **复合键不过滤**，尊重数据库约束设计 |
| **dynamic_same_name** | 需要配置才执行 | **默认行为**（总是执行，不需要配置） |
| **target_sources 作用** | 控制多个来源 | **只控制是否收集索引**（`composite_indexes`） |
| **配置命名** | `min_name_similarity` | **改名为** `name_similarity_important_target` |
| **类型兼容性检查** | 阶段一用评分，阶段二用布尔 | **统一为评分** + `min_type_compatibility` 阈值 |

---

### 六、修改的功能

#### 修改的方法：

| 方法 | 状态 | 变更说明 |
|:---|:---|:---|
| `_collect_source_combinations` | 🔧 修改 | 增加 `include_indexes` 参数 |
| `_find_target_columns` | 🔧 重写 | 改为两阶段匹配（特权模式 + 动态同名） |
| `_is_compatible_combination` | ❌ 废弃 | 被 `_match_columns_as_set` 替代 |
| `_find_dynamic_same_name` | 🔧 修改 | 修改类型兼容性检查：从布尔判断改为评分+阈值 |

#### 新增方法：

| 方法 | 功能 | 使用场景 |
|:---|:---|:---|
| `_match_columns_as_set` | 穷举排列集合匹配 | 阶段一（特权模式） |

#### 废弃配置：

| 旧配置 | 新配置 | 说明 |
|:---|:---|:---|
| `min_name_similarity` | `name_similarity_important_target` | 改名，语义更明确 |
| `target_sources` 中的其他选项 | 只保留 `composite_indexes` | PK/UK/Logical 总是收集，不需要配置 |

**从 `target_sources` 中移除的选项：**
- ~~`physical_constraints`~~：PK/UK 总是收集，不需要配置
- ~~`candidate_logical_keys`~~：Logical Key 总是收集，不需要配置
- ~~`dynamic_same_name`~~：总是执行，不需要配置

#### 保留配置：

- `target_sources`：只保留 `["composite_indexes"]`（可选），用于控制是否收集索引
- `min_type_compatibility`：保持不变，用于阶段一和阶段二的类型兼容性阈值

---

### 七、改造收益

1. **更精准的源表筛选**：排除所有索引，只收集强约束（PK/UK/Logical），避免弱约束作为外键源头
2. **更灵活的目标表匹配**：特权模式利用所有索引（包括普通索引）降低门槛
3. **更智能的乱序匹配**：穷举排列算法，不再要求列顺序一致，避免贪心算法的漏报
4. **尊重数据库设计**：不过滤包含 audit/metric 的主键/唯一约束，如果数据库设计中包含这些字段，说明有其合理性
5. **简化配置**：
   - dynamic_same_name 作为默认行为总是执行，不需要配置控制
   - PK/UK/Logical 总是收集，不需要配置控制
   - `target_sources` 简化为只控制索引收集（`composite_indexes`）
6. **算法优化**：从 O(n²) 贪心算法改为 O(n! × n) 穷举算法，对于 2-3 列场景性能完全可接受且准确性更高
7. **符合PostgreSQL特性**：理解UK自动创建索引的机制，不需要从indexes中查找"唯一索引"
8. **类型兼容性检查一致性**：阶段一和阶段二都使用 `_get_type_compatibility_score` + `min_type_compatibility` 阈值，逻辑统一，更易维护
9. **配置语义明确**：`target_sources` 不再控制多个来源，只控制"是否收集索引"这一个选项，避免混淆

---

### 八、潜在风险与缓解措施

#### 风险1：唯一约束识别不全

**风险：** 如果元数据中 `unique_constraints` 数据不完整，可能丢失候选。

**缓解：** 
- 源表收集逻辑已明确：只收集 PK/UK/Logical，不依赖索引
- PostgreSQL 的唯一约束会自动出现在 `unique_constraints` 数组中
- 如果仍有问题，可以检查元数据提取逻辑是否正确

#### 风险2：dynamic_same_name 执行失败

**风险：** dynamic_same_name 虽然总是执行，但如果实现有误，可能导致匹配失败。

**缓解：**
- 保持原有 `_find_dynamic_same_name` 方法逻辑不变，经过验证
- 在代码中增加日志，记录阶段二是否找到匹配
- 确保阶段二的逻辑简单可靠（精确同名 + 类型兼容）

#### 风险3：穷举排列性能问题

**风险：** 如果将来 `max_columns` 增加到 4 或 5，穷举算法可能变慢。

**缓解：**
- 当前限制 `max_columns=3`，最多 6 种排列，性能无忧
- 如果将来需要支持更大的 `max_columns`，可以考虑匈牙利算法或启发式搜索

#### 风险4：误解 target_sources 的作用域

**风险：** 现有代码中，`target_sources` 被错误地用于控制 PK/UK/Logical 的收集，导致配置不当会丢失候选。

**缓解：**
- **修正实现**：从 `_collect_source_combinations` 中删除所有 `if ... in self.target_sources` 判断
- **文档明确标注**：`target_sources` **只控制是否收集索引**（`composite_indexes`）
- **代码注释**：在 `_collect_source_combinations` 中明确注释"总是收集 PK/UK/Logical，不检查配置"
- **Code Review 检查点**：确保 PK/UK/Logical 收集代码不包含 `if ... in self.target_sources` 判断

**现有代码的问题示例：**
```python
# ❌ 现有代码的错误（需要修正）
if "physical_constraints" in self.target_sources:  # 第163行
    收集 PK/UK

if "candidate_logical_keys" in self.target_sources:  # 第186行
    收集 Logical
```

这会导致：如果用户删除配置中的 `physical_constraints`，PK/UK 就不会被收集，候选数量大幅下降。

#### 风险5：索引收集配置不明确

**风险：** 用户可能不理解 `composite_indexes` 的作用，误删或误添。

**缓解：**
- **配置注释**：在 YAML 中明确说明该选项的作用
- **文档详细说明**：增加 4.3 小节专门说明 `composite_indexes` 的作用和使用场景
- **默认建议**：建议默认启用 `composite_indexes`，除非数据质量很差
