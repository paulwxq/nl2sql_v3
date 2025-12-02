---

### 一、改造目标（单列候选）

**目标：**  
在 `CandidateGenerator._generate_single_column_candidates(...)` 中，把原先的两条路径：

- `active_search_same_name`（物理约束 + 同名）
- `logical_key_matching`（逻辑主键 + 目标列满足约束）

统一成一条 **“重要源列 → 统一规则选目标列”** 的逻辑，按名称相似度 + 类型兼容性 + 目标列是否重要来控制阈值。

---

### 二、配置层面的改动（`__init__` 里的单列配置）

在 `__init__` 里，只改 **单列相关配置**：

1. **删除字段**

   - 删除 `self.active_search_enabled` 这一配置和日志使用（不再有 `active_search_same_name` 开关）。

2. **保留字段**

   - `self.important_constraints`
   - `self.exclude_semantic_roles`
   - `self.logical_key_min_confidence`
   - `self.min_type_compatibility`（用于单列类型兼容性的最低分）

3. **新增两个名称相似度阈值（在 `single_column` 配置下）**

   - `self.name_similarity_important_target = single_config.get("name_similarity_important_target", 0.6)`
   - `self.name_similarity_normal_target = single_config.get("name_similarity_normal_target", 0.9)`

   语义：

   - **important_target**：目标列是“关键字段”（PK/UK/Index/逻辑主键）时使用的 name 阈值（默认 0.6）  
   - **normal_target**：目标列不是关键字段时使用的 name 阈值（默认 0.9）

---

### 三、源列判断逻辑（统一入口）

在 `_generate_single_column_candidates` 的源列循环中，原来是：

- `if self.active_search_enabled and self._has_defined_constraint(...)`: active_search 分支
- `if self._is_logical_primary_key(...)`: logical_key 分支

改成统一入口（伪代码）：

1. **保持语义角色过滤不变：**

```text
semantic_role = col_profile["semantic_analysis"]["semantic_role"]
if semantic_role in self.exclude_semantic_roles:
    continue
```

2. **源列“重要性”判定：**

利用现有两个方法，命名明确为：

```text
has_defined_constraint = self._has_defined_constraint(col_profile)
is_logical_pk          = self._is_logical_primary_key(col_name, source_table)
```

3. **只保留“重要源列”：**

```text
if not (has_defined_constraint or is_logical_pk):
    # 源列既没有定义约束，也不是逻辑主键 → 不参与单列候选生成
    continue
```

> 这样，旧的 active_search / logical_key 两个 if 分支整体被一个统一入口替代。

---

### 四、目标列筛选统一逻辑

对每个“重要源列”，遍历所有其他表、所有列作为目标候选列，逻辑如下：

1. **遍历目标表**

```text
for target_name, target_table in tables.items():
    if target_name == source_name:
        continue

    target_info     = target_table.get("table_info", {})
    target_schema   = target_info.get("schema_name")
    target_tbl_name = target_info.get("table_name")
    target_profiles = target_table.get("column_profiles", {})
```

2. **遍历目标列**

```text
for target_col_name, target_col_profile in target_profiles.items():
    ...
```

3. **(a) 语义角色过滤**

沿用现有逻辑：

```text
target_role = target_col_profile.get("semantic_analysis", {}).get("semantic_role")
if target_role in self.exclude_semantic_roles:
    continue
```

4. **(b) 类型兼容性过滤**

统一用 `_get_type_compatibility_score` + `self.min_type_compatibility`：

```text
src_type = col_profile.get("data_type", "")
tgt_type = target_col_profile.get("data_type", "")
type_compat = self._get_type_compatibility_score(src_type, tgt_type)

if type_compat < self.min_type_compatibility:
    continue
```

5. **(c) 判断目标列是否“关键字段”**

直接复用 `_is_qualified_target_column`（现有实现保持不变）：

```text
is_important_target = self._is_qualified_target_column(
    target_col_name, target_col_profile, target_table
)
```

语义：满足 PK / UK / Index / 单列逻辑主键（conf >= 0.8）之一。

6. **(d) 名称相似度 + 阈值选择**

名称相似度继续使用 `_calculate_name_similarity`，它已经：

- 内部对 `name1` / `name2` 调用 `.lower()`  
- 同名时直接返回 1.0

逻辑：

```text
name_sim = self._calculate_name_similarity(col_name, target_col_name)

if is_important_target:
    threshold = self.name_similarity_important_target  # 默认 0.6
else:
    threshold = self.name_similarity_normal_target     # 默认 0.9

if name_sim < threshold:
    continue
```

7. **(e) FK 去重**

沿用 `_make_signature` 和 `fk_signature_set`：

```text
fk_sig = self._make_signature(
    source_schema, source_table_name, [col_name],
    target_schema, target_tbl_name, [target_col_name]
)
if fk_sig in self.fk_signature_set:
    continue
```

8. **(f) 决定 `candidate_type`（方案 B，且不用默认 else）**

我们用三个明确的类型名，并显式覆盖所有可能组合：

- `single_defined`：有定义约束，无逻辑主键
- `single_logical_key`：逻辑主键，无定义约束
- `single_defined_and_logical`：两者皆有

伪代码：

```text
if has_defined_constraint and is_logical_pk:
    candidate_type = "single_defined_constraint_and_logical_pk"
elif has_defined_constraint and not is_logical_pk:
    candidate_type = "single_defined_constraint"
elif is_logical_pk and not has_defined_constraint:
    candidate_type = "single_logical_key"
else:
    # 理论上进不到这里（因为外层已经确保 has_defined_constraint or is_logical_pk）
    # 实现时可以选择 log.warning 然后 continue，避免产生语义不明的候选
    continue
```

9. **(g) 构造并追加候选**

```text
candidate = {
    "source": source_table,
    "target": target_table,
    "source_columns": [col_name],
    "target_columns": [target_col_name],
    "candidate_type": candidate_type,
}
candidates.append(candidate)
```

> 注意：不再使用 `"single_active_search"` 这个 `candidate_type` 名字；单列候选只有上面三种。

---

### 五、保持不变的部分

- 复合键相关逻辑（`_generate_composite_candidates`、`_collect_source_combinations`、`_find_target_columns` 等）保持不变。
- `_has_defined_constraint`、`_is_logical_primary_key`、`_is_qualified_target_column`、`_calculate_name_similarity`、`_get_type_compatibility_score` 的内部实现保持不变，仅在单列逻辑中“如何组合使用它们”发生了变化。
- 不额外增加 bonus 分；“同名优先”通过 `name_sim = 1.0` 自然体现。

---

### 六、整体行为总结

**新逻辑总结成一句话：**

> “只要源列是有显式定义约束的列（PK/UK）或被推断为单列逻辑主键，就在所有其它表的所有非 metric/audit 列中，按类型兼容性 + 名称相似度筛选候选；如果目标列本身也是关键字段，名字可以相似度阈值低一点（0.6），否则要更像（0.9），最后根据源列的‘定义约束/逻辑主键’身份标记候选类型为 `single_defined` / `single_logical_key` / `single_defined_and_logical`。”

