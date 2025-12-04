# rel_llm 外键基数推断问题分析与解决方案

## 1. 问题描述

### 1.1 问题现象

在 `rel_llm` 流程中，`_extract_foreign_keys()` 方法直接从 JSON 构造外键关系字典，**没有填充 `cardinality` 字段**。

**文档位置**：`docs/gen_rag/LLM辅助关联关系发现设计方案.md` 第 907-949 行

```python
def _extract_foreign_keys(self, tables: Dict[str, Dict]) -> Tuple[List[Dict], Set[str]]:
    """提取物理外键"""
    for fk in foreign_keys:
        relation = {
            "type": "composite" if len(fk["source_columns"]) > 1 else "single_column",
            "from_table": {"schema": source_schema, "table": source_table},
            "to_table": {"schema": fk["target_schema"], "table": fk["target_table"]},
            "discovery_method": "physical_foreign_key",
            "constraint_name": fk.get("constraint_name")
            # ❌ 缺少 "cardinality" 字段
        }
        fk_relations.append(relation)
```

### 1.2 对比：传统流程的处理

传统 `--step rel` 流程通过 `MetadataRepository.collect_foreign_keys()` 处理外键，会自动调用 `_infer_cardinality()` 推断基数：

```python
# src/metaweave/core/relationships/repository.py:132-143
relation = Relation(
    relationship_id=rel_id,
    source_schema=source_schema,
    source_table=source_table,
    source_columns=source_columns,
    target_schema=target_schema,
    target_table=target_table,
    target_columns=target_columns,
    relationship_type="foreign_key",
    cardinality=self._infer_cardinality(fk, tables, full_name, target_schema, target_table)  # ✅ 自动推断
)
```

## 2. 影响分析

### 2.1 标准外键场景（~95%）

**定义**：外键列无唯一约束，引用主键列

```sql
ALTER TABLE fact_store_sales 
ADD CONSTRAINT fk_store 
FOREIGN KEY (store_id)           -- 可重复
REFERENCES dim_store(store_id);  -- 主键（唯一）
```

- **实际基数**：N:1
- **默认值**：N:1（Relation 模型的默认值）
- **影响**：✅ **无影响**（默认值正确）

### 2.2 唯一外键场景（~4%）

**定义**：外键列有唯一约束，引用主键列（1:1 关系）

```sql
ALTER TABLE user_profile
ADD CONSTRAINT fk_user UNIQUE
FOREIGN KEY (user_id)            -- 唯一
REFERENCES users(user_id);       -- 主键（唯一）
```

- **实际基数**：1:1
- **默认值**：N:1
- **影响**：❌ **基数错误** → CQL 箭头方向错误

### 2.3 反向外键场景（~1%，不规范）

**定义**：外键列为主键，引用非主键列（反向引用）

```sql
-- 不规范设计，但理论上可能存在
ALTER TABLE parent_table
ADD CONSTRAINT fk_child
FOREIGN KEY (parent_id)          -- 主键（唯一）
REFERENCES child_table(child_id);-- 非主键（可重复）
```

- **实际基数**：1:N
- **默认值**：N:1
- **影响**：❌ **基数错误且方向完全相反** → CQL 箭头方向完全错误

### 2.4 总结

| 场景 | 占比 | 默认 N:1 是否正确 | 影响 |
|------|------|------------------|------|
| 标准外键（FK → PK） | ~95% | ✅ 正确 | 无 |
| 唯一外键（1:1） | ~4% | ❌ 错误 | 中等 |
| 反向外键（1:N） | ~1% | ❌ 错误 | 高 |

**问题严重程度**：**中等**（影响约 5% 的非标准外键场景）

## 3. 解决方案

### 3.1 推荐方案：基于唯一性检查的轻量级推断

在 `_extract_foreign_keys()` 中添加基于唯一约束的基数判断逻辑：

```python
def _extract_foreign_keys(self, tables: Dict[str, Dict]) -> Tuple[List[Dict], Set[str]]:
    """提取物理外键（带基数推断）"""
    fk_relations = []
    fk_signatures = set()
    
    for full_name, table_data in tables.items():
        table_info = table_data.get("table_info", {})
        source_schema = table_info.get("schema_name")
        source_table = table_info.get("table_name")
        
        physical_constraints = table_data.get("table_profile", {}).get("physical_constraints", {})
        foreign_keys = physical_constraints.get("foreign_keys", [])
        
        for fk in foreign_keys:
            # ========== 基数推断逻辑 ==========
            source_columns = fk["source_columns"]
            target_schema = fk["target_schema"]
            target_table = fk["target_table"]
            target_columns = fk["target_columns"]
            
            # 1. 检查源列唯一性
            source_is_unique = self._check_uniqueness(
                table_data, source_columns
            )
            
            # 2. 检查目标列唯一性
            target_full_name = f"{target_schema}.{target_table}"
            target_table_data = tables.get(target_full_name)
            target_is_unique = self._check_uniqueness(
                target_table_data, target_columns
            ) if target_table_data else True  # 目标表不存在时假设唯一（保守）
            
            # 3. 判断基数
            if source_is_unique and target_is_unique:
                cardinality = "1:1"  # 唯一外键
            elif source_is_unique and not target_is_unique:
                cardinality = "1:N"  # 反向外键（罕见）
            elif not source_is_unique and target_is_unique:
                cardinality = "N:1"  # 标准外键（最常见）
            else:
                cardinality = "M:N"  # 非规范外键（极罕见）
            
            logger.debug(
                f"外键基数: {source_schema}.{source_table}{source_columns} -> "
                f"{target_schema}.{target_table}{target_columns}, "
                f"source_unique={source_is_unique}, target_unique={target_is_unique}, "
                f"cardinality={cardinality}"
            )
            # ====================================
            
            relation = {
                "type": "composite" if len(source_columns) > 1 else "single_column",
                "from_table": {"schema": source_schema, "table": source_table},
                "to_table": {"schema": target_schema, "table": target_table},
                "discovery_method": "physical_foreign_key",
                "constraint_name": fk.get("constraint_name"),
                "cardinality": cardinality  # ✅ 添加推断的基数
            }
            
            if relation["type"] == "single_column":
                relation["from_column"] = source_columns[0]
                relation["to_column"] = target_columns[0]
            else:
                relation["from_columns"] = source_columns
                relation["to_columns"] = target_columns
            
            sig = self._make_signature(
                source_schema, source_table, source_columns,
                target_schema, target_table, target_columns
            )
            fk_signatures.add(sig)
            fk_relations.append(relation)
            
            logger.debug(f"物理外键: {source_schema}.{source_table} -> {target_schema}.{target_table} [{cardinality}]")
    
    return fk_relations, fk_signatures

def _check_uniqueness(self, table_data: Dict, columns: List[str]) -> bool:
    """检查列（组合）是否唯一
    
    优先级：物理约束 > 统计值
    
    Args:
        table_data: 表的 JSON 数据
        columns: 列名列表
        
    Returns:
        True: 列是唯一的
        False: 列不唯一或无法判断
    """
    if not table_data or not columns:
        return False
    
    physical_constraints = table_data.get("table_profile", {}).get("physical_constraints", {})
    column_profiles = table_data.get("column_profiles", {})
    
    # === 1. 检查物理约束（优先） ===
    
    # 单列情况
    if len(columns) == 1:
        col_name = columns[0]
        col_profile = column_profiles.get(col_name, {})
        flags = col_profile.get("structure_flags", {})
        
        # 主键或唯一约束 → 唯一
        if flags.get("is_primary_key") or flags.get("is_unique_constraint"):
            logger.debug(f"列 {col_name}: 物理约束判定为唯一")
            return True
    
    # 复合列情况：检查复合主键/唯一约束
    else:
        # 检查复合主键
        pk = physical_constraints.get("primary_key")
        if pk and isinstance(pk, dict):
            pk_columns = pk.get("columns", [])
        elif pk and isinstance(pk, list):
            pk_columns = pk
        else:
            pk_columns = []
        
        if pk_columns and set(pk_columns) == set(columns):
            logger.debug(f"列组合 {columns}: 复合主键，判定为唯一")
            return True
        
        # 检查复合唯一约束
        for uk in physical_constraints.get("unique_constraints", []):
            if isinstance(uk, dict):
                uk_columns = uk.get("columns", [])
            elif isinstance(uk, list):
                uk_columns = uk
            else:
                continue
            
            if uk_columns and set(uk_columns) == set(columns):
                logger.debug(f"列组合 {columns}: 复合唯一约束，判定为唯一")
                return True
    
    # === 2. Fallback 到统计值 ===
    
    HIGH_UNIQUENESS = 0.95  # 高唯一性阈值
    
    if len(columns) == 1:
        col_name = columns[0]
        col_profile = column_profiles.get(col_name, {})
        stats = col_profile.get("statistics", {})
        uniqueness = stats.get("uniqueness", 0.0)
        
        if uniqueness >= HIGH_UNIQUENESS:
            logger.debug(f"列 {col_name}: 统计值 uniqueness={uniqueness:.3f} >= {HIGH_UNIQUENESS}，判定为唯一")
            return True
    else:
        # 复合列：取最小唯一性（保守估计）
        min_uniqueness = 1.0
        for col_name in columns:
            col_profile = column_profiles.get(col_name, {})
            stats = col_profile.get("statistics", {})
            uniqueness = stats.get("uniqueness", 0.0)
            min_uniqueness = min(min_uniqueness, uniqueness)
        
        if min_uniqueness >= HIGH_UNIQUENESS:
            logger.debug(f"列组合 {columns}: 统计值 min_uniqueness={min_uniqueness:.3f} >= {HIGH_UNIQUENESS}，判定为唯一")
            return True
    
    logger.debug(f"列/列组合 {columns}: 未满足唯一条件")
    return False
```

### 3.2 备选方案：直接复用 MetadataRepository

如果想完全复用现有逻辑，可以这样：

```python
def _extract_foreign_keys(self, tables: Dict[str, Dict]) -> Tuple[List[Dict], Set[str]]:
    """提取物理外键（复用 MetadataRepository）"""
    from src.metaweave.core.relationships.repository import MetadataRepository
    
    # 创建临时 repository
    repository = MetadataRepository.__new__(MetadataRepository)
    repository.rel_id_salt = self.config.get("output", {}).get("rel_id_salt", "")
    
    # 调用现有的外键收集方法（包含完整的基数推断逻辑）
    fk_relation_objects, fk_signatures = repository.collect_foreign_keys(tables)
    
    # 转换为 rel_llm 需要的字典格式
    fk_relations = []
    for rel in fk_relation_objects:
        relation_dict = {
            "type": "composite" if len(rel.source_columns) > 1 else "single_column",
            "from_table": {"schema": rel.source_schema, "table": rel.source_table},
            "to_table": {"schema": rel.target_schema, "table": rel.target_table},
            "discovery_method": "physical_foreign_key",
            "cardinality": rel.cardinality,  # ✅ 包含推断的基数
            "relationship_id": rel.relationship_id
        }
        
        if relation_dict["type"] == "single_column":
            relation_dict["from_column"] = rel.source_columns[0]
            relation_dict["to_column"] = rel.target_columns[0]
        else:
            relation_dict["from_columns"] = rel.source_columns
            relation_dict["to_columns"] = rel.target_columns
        
        fk_relations.append(relation_dict)
    
    return fk_relations, fk_signatures
```

## 4. 方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **方案 1：轻量级推断** | • 代码清晰<br>• 独立性强<br>• 逻辑透明 | • 需要实现 `_check_uniqueness()`<br>• 代码略多 | ⭐⭐⭐⭐⭐ |
| **方案 2：复用 Repository** | • 代码少<br>• 完全复用现有逻辑<br>• 保证一致性 | • 依赖另一个类<br>• 耦合度高 | ⭐⭐⭐⭐ |
| **保持现状（默认 N:1）** | • 无需修改<br>• 95% 场景正确 | • 5% 场景错误<br>• 不够完善 | ⭐⭐ |

## 5. 实施建议

### 5.1 短期方案（快速上线）

- 📝 **文档说明**：在设计文档中明确声明
  > "rel_llm 流程假设所有物理外键都是标准 N:1 关系（外键列无唯一约束）。如果存在唯一外键（1:1）或反向外键（1:N），基数可能不准确。"

### 5.2 长期优化（推荐实施）

- ✅ **实施方案 1**：添加基于唯一性检查的轻量级基数推断
- ✅ **测试覆盖**：添加单元测试覆盖三种场景
- ✅ **文档更新**：在文档中说明基数推断逻辑

### 5.3 优先级评估

- **严重程度**：中等（影响 ~5% 场景）
- **修复成本**：低（约 50 行代码）
- **优先级**：**P1**（建议实施，非阻塞）

## 6. 测试用例

### 6.1 标准外键测试

```python
def test_standard_foreign_key():
    """测试标准外键（N:1）"""
    fk = {
        "source_columns": ["store_id"],
        "target_schema": "public",
        "target_table": "dim_store",
        "target_columns": ["store_id"]
    }
    
    # 源列：非唯一
    # 目标列：主键（唯一）
    # 预期：N:1
    assert cardinality == "N:1"
```

### 6.2 唯一外键测试

```python
def test_unique_foreign_key():
    """测试唯一外键（1:1）"""
    fk = {
        "source_columns": ["user_id"],
        "target_schema": "public",
        "target_table": "users",
        "target_columns": ["user_id"]
    }
    
    # 源列：唯一约束
    # 目标列：主键（唯一）
    # 预期：1:1
    assert cardinality == "1:1"
```

### 6.3 反向外键测试

```python
def test_reverse_foreign_key():
    """测试反向外键（1:N）"""
    fk = {
        "source_columns": ["parent_id"],
        "target_schema": "public",
        "target_table": "child_table",
        "target_columns": ["child_id"]
    }
    
    # 源列：主键（唯一）
    # 目标列：非唯一
    # 预期：1:N
    assert cardinality == "1:N"
```

## 7. 总结

1. ✅ **问题确实存在**：`rel_llm` 流程缺少外键基数推断逻辑
2. ✅ **影响有限**：仅影响约 5% 的非标准外键场景（唯一外键、反向外键）
3. ✅ **解决方案明确**：基于唯一约束检查实现轻量级基数推断
4. ✅ **建议实施**：虽然不阻塞上线，但建议尽快完善以提升准确性

---

**文档版本**：v1.0  
**创建日期**：2024-12-04  
**最后更新**：2024-12-04

