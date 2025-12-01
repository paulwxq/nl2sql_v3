# PostgreSQL 类型兼容性评分标准

## 1. 概述

本文档定义了 MetaWeave 关系发现模块中 PostgreSQL 数据类型的 JOIN 兼容性评分标准。该评分用于候选关系生成阶段，帮助判断两个字段是否适合作为关联字段。

### 1.1 评分等级

| 分数 | 含义 | JOIN 结果 | 使用建议 |
|------|------|----------|---------|
| **1.0** | 类型完全相同 | 完美匹配 | 放心使用 |
| **0.9** | 同类型族，完全互换，零损失 | 完美匹配 | 放心使用 |
| **0.85** | 同大类，高度兼容，实际使用无影响 | 实际无影响 | 放心使用 |
| **0.8** | 同大族，兼容但有细微差异 | 基本可用 | **关键阈值：≥0.8 可放心JOIN** |
| **0.6** | 可以JOIN但有精度问题 | 有精度损失 | 谨慎使用，注意精度 |
| **0.5** | 可以JOIN但精度损失明显 | 损失明显 | **最低阈值：<0.5 不建议JOIN** |
| **0.0** | JOIN会报错，完全不兼容 | 报错 | 拒绝 |

### 1.2 关键阈值

```python
# 在候选筛选代码中的使用：
if type_compatibility >= 0.8:
    # ✅ 可以安心JOIN，基本无问题
    pass

if type_compatibility >= 0.5:
    # ⚠️ 可以JOIN，但要注意精度损失
    pass
else:
    # ❌ 不兼容，直接排除
    pass
```

---

## 2. 详细评分规则

### 2.1 整数类型族（0.9）

**原则**：整数类型之间可以完全互换，无损失

```sql
-- 所有这些JOIN都是完美的
SELECT * FROM t1 JOIN t2 ON t1.id::SMALLINT = t2.id::INTEGER;
SELECT * FROM t1 JOIN t2 ON t1.id::INTEGER = t2.id::BIGINT;
SELECT * FROM t1 JOIN t2 ON t1.id::SERIAL = t2.id::INT;
```

**类型列表**：
- `SMALLINT`, `INT2`, `SMALLSERIAL`
- `INTEGER`, `INT`, `INT4`, `SERIAL`
- `BIGINT`, `INT8`, `BIGSERIAL`

**评分**：
- 整数族内部任意组合 → **0.9**

**示例**：
- `INTEGER` ↔ `BIGINT` → **0.9** ✅
- `SMALLINT` ↔ `SERIAL` → **0.9** ✅

---

### 2.2 字符串类型族（0.85 / 0.8）

**原则**：
1. `VARCHAR`/`TEXT` 之间安全 → **0.85**
2. `CHAR` 参与时有 padding 陷阱 → **0.8**

```sql
-- ✅ 0.85 - 安全
SELECT * FROM t1 JOIN t2 ON t1.name::VARCHAR(10) = t2.name::TEXT;

-- ⚠️ 0.8 - CHAR 有 padding 问题
SELECT 'abc'::CHAR(10) = 'abc'::VARCHAR(10);  -- FALSE！
-- CHAR(10) 存储为 'abc       ' (补7个空格)
```

**类型分组**：

| 组别 | 类型 | 评分 |
|------|------|------|
| **VARCHAR组** | `VARCHAR`, `CHARACTER VARYING`, `TEXT` | 内部 **0.85** |
| **CHAR组** | `CHAR`, `CHARACTER`, `BPCHAR` | 与任意字符串 **0.8** |

**评分规则**：
- `VARCHAR` ↔ `TEXT` → **0.85** ✅
- `VARCHAR` ↔ `CHAR` → **0.8** ⚠️
- `CHAR` ↔ `CHAR` → **0.8** ⚠️

---

### 2.3 精确数值类型（NUMERIC/DECIMAL）

#### 2.3.1 NUMERIC 与 NUMERIC（0.8）

```sql
-- 精度不同时可能有截断
SELECT 123.456::NUMERIC(5,2) = 123.456::NUMERIC(10,4);  -- 123.46 vs 123.4560
```

**评分**：
- `NUMERIC` ↔ `NUMERIC` → **0.8**
- `NUMERIC` ↔ `DECIMAL` → **0.8**

#### 2.3.2 INTEGER 与 NUMERIC（0.9）⭐

**重要**：整数转 NUMERIC 是完全无损的！

```sql
-- 完全相等，无任何损失
SELECT 123::INTEGER = 123::NUMERIC;  -- TRUE
SELECT 9999999999::BIGINT = 9999999999::NUMERIC(20,0);  -- TRUE
```

**评分**：
- `INTEGER` ↔ `NUMERIC` → **0.9** ✅（提升到与 INTEGER ↔ BIGINT 同级）

---

### 2.4 浮点类型（0.8）

```sql
-- REAL vs DOUBLE PRECISION 精度不同
SELECT 1.23456789::REAL = 1.23456789::DOUBLE PRECISION;  -- 可能 FALSE
```

**类型列表**：
- `REAL`, `FLOAT4`
- `DOUBLE PRECISION`, `FLOAT8`, `FLOAT`

**评分**：
- 浮点族内部 → **0.8**

---

### 2.5 数值类型交叉

#### 2.5.1 INTEGER ↔ FLOAT（0.6）

```sql
-- 小整数安全，大整数危险
SELECT 123::INTEGER = 123::REAL;           -- TRUE（安全）
SELECT 16777217::INTEGER = 16777217::REAL; -- FALSE（超出REAL精度）
```

**评分**：
- `INTEGER` ↔ `REAL/DOUBLE` → **0.6** ⚠️

#### 2.5.2 NUMERIC ↔ FLOAT（0.5）⚠️

**重要降级**：精确数值 → 近似值，损失更严重

```sql
-- NUMERIC → FLOAT：丢失精确性
SELECT 123.456789012345::NUMERIC = 123.456789012345::REAL;  -- FALSE
-- NUMERIC 能保存所有位数，REAL 只能保存约7位
```

**评分**：
- `NUMERIC` ↔ `REAL/DOUBLE` → **0.5** ⚠️

---

### 2.6 日期时间类型

#### 2.6.1 DATE 类型（1.0）

```sql
SELECT '2025-12-01'::DATE = '2025-12-01'::DATE;  -- TRUE
```

**评分**：
- `DATE` ↔ `DATE` → **1.0**

#### 2.6.2 TIMESTAMP 系列（0.9 / 0.8）

```sql
-- 同义词
SELECT '2025-12-01 10:30:00'::TIMESTAMP 
     = '2025-12-01 10:30:00'::TIMESTAMP WITHOUT TIME ZONE;  -- TRUE (同义词)

-- 时区转换
SELECT '2025-12-01 10:30:00'::TIMESTAMP 
     = '2025-12-01 10:30:00'::TIMESTAMPTZ;  -- 可能 FALSE（取决于时区设置）
```

**评分规则**：

| 类型1 | 类型2 | 分数 | 说明 |
|-------|-------|------|------|
| `TIMESTAMP` | `TIMESTAMP WITHOUT TIME ZONE` | **0.9** | 同义词 |
| `TIMESTAMPTZ` | `TIMESTAMP WITH TIME ZONE` | **0.9** | 同义词 |
| `TIMESTAMP` | `TIMESTAMPTZ` | **0.8** | 有时区转换 |

#### 2.6.3 DATE ↔ TIMESTAMP（0.5）⚠️

**关键限制**：DATE 只能匹配午夜 00:00:00

```sql
-- 只有午夜才匹配
SELECT '2025-12-01'::DATE = '2025-12-01 00:00:00'::TIMESTAMP;  -- TRUE
SELECT '2025-12-01'::DATE = '2025-12-01 10:30:00'::TIMESTAMP;  -- FALSE
```

**评分**：
- `DATE` ↔ `TIMESTAMP` → **0.5** ⚠️

#### 2.6.4 TIME 类型（0.85 / 0.0）

```sql
-- TIME 系列内部
SELECT '10:30:00'::TIME = '10:30:00'::TIME WITH TIME ZONE;  -- 基本可用

-- TIME vs DATE/TIMESTAMP 不能JOIN
SELECT '10:30:00'::TIME = '2025-12-01 10:30:00'::TIMESTAMP;  -- ERROR!
```

**评分**：
- `TIME` 系列内部 → **0.85**
- `TIME` ↔ `DATE/TIMESTAMP` → **0.0** ❌

---

### 2.7 布尔类型（0.9 / 0.6）

#### 2.7.1 布尔族内部（0.9）

```sql
SELECT TRUE::BOOLEAN = TRUE::BOOL;  -- TRUE（同义词）
```

**评分**：
- `BOOLEAN` ↔ `BOOL` → **0.9**

#### 2.7.2 布尔与整数（0.6）⚠️

PostgreSQL 允许布尔与整数隐式转换：

```sql
SELECT TRUE::BOOLEAN = 1::INTEGER;   -- TRUE
SELECT FALSE::BOOLEAN = 0::INTEGER;  -- TRUE
```

**评分**：
- `BOOLEAN` ↔ `INTEGER` → **0.6** ⚠️（可JOIN但语义奇怪，不建议）

---

### 2.8 UUID 类型（1.0 / 0.0）

```sql
-- UUID 只能与 UUID 比较
SELECT 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::UUID 
     = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::UUID;  -- TRUE

-- UUID vs VARCHAR 会报错
SELECT 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::UUID 
     = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::VARCHAR;  -- ERROR!
```

**评分**：
- `UUID` ↔ `UUID` → **1.0**
- `UUID` ↔ 其他 → **0.0** ❌

---

### 2.9 跨大类（0.0）

**完全不兼容的组合**：

| 类型1 | 类型2 | 分数 | 原因 |
|-------|-------|------|------|
| 整数/数值 | 字符串 | **0.0** | 需显式转换 |
| 日期/时间 | 字符串 | **0.0** | 需显式转换 |
| UUID | 非UUID | **0.0** | 严格类型 |
| 布尔 | 非布尔/非整数 | **0.0** | 类型不匹配 |

```sql
-- 这些都会报错
SELECT 123::INTEGER = '123'::VARCHAR;           -- ERROR!
SELECT '2025-12-01'::DATE = '2025-12-01'::TEXT; -- ERROR!
```

---

## 3. 完整评分表

### 3.1 数值类型矩阵

|  | INTEGER | BIGINT | NUMERIC | REAL | DOUBLE |
|---|---------|--------|---------|------|--------|
| **INTEGER** | 1.0 | 0.9 | 0.9 ✨ | 0.6 | 0.6 |
| **BIGINT** | 0.9 | 1.0 | 0.9 ✨ | 0.6 | 0.6 |
| **NUMERIC** | 0.9 ✨ | 0.9 ✨ | 0.8 | 0.5 ⚠️ | 0.5 ⚠️ |
| **REAL** | 0.6 | 0.6 | 0.5 ⚠️ | 1.0 | 0.8 |
| **DOUBLE** | 0.6 | 0.6 | 0.5 ⚠️ | 0.8 | 1.0 |

> ✨ **关键修正**：INTEGER ↔ NUMERIC 提升到 **0.9**（原来是 0.8）

### 3.2 字符串类型矩阵

|  | VARCHAR | TEXT | CHAR |
|---|---------|------|------|
| **VARCHAR** | 1.0 | 0.85 | 0.8 ⚠️ |
| **TEXT** | 0.85 | 1.0 | 0.8 ⚠️ |
| **CHAR** | 0.8 ⚠️ | 0.8 ⚠️ | 0.8 |

> ⚠️ CHAR 有 padding 陷阱，降级到 0.8

### 3.3 日期时间类型矩阵

|  | DATE | TIMESTAMP | TIMESTAMPTZ | TIME |
|---|------|-----------|-------------|------|
| **DATE** | 1.0 | 0.5 ⚠️ | 0.5 ⚠️ | 0.0 ❌ |
| **TIMESTAMP** | 0.5 ⚠️ | 0.9 | 0.8 | 0.0 ❌ |
| **TIMESTAMPTZ** | 0.5 ⚠️ | 0.8 | 0.9 | 0.0 ❌ |
| **TIME** | 0.0 ❌ | 0.0 ❌ | 0.0 ❌ | 0.85 |

---

## 4. 实现说明

### 4.1 类型标准化

在计算兼容性之前，需要先标准化类型：

```python
def _normalize_type(self, type_str: str) -> str:
    """标准化PostgreSQL类型字符串
    
    Args:
        type_str: 原始类型字符串（如 "VARCHAR(100)", "NUMERIC(10,2)"）
        
    Returns:
        str: 标准化后的类型（如 "varchar", "numeric"）
    """
    if not type_str:
        return ""
    
    # 转小写
    normalized = type_str.lower().strip()
    
    # 去除长度/精度限制（VARCHAR(100) → varchar）
    if '(' in normalized:
        normalized = normalized.split('(')[0].strip()
    
    # 去除数组标记（integer[] → integer）
    normalized = normalized.replace('[]', '').strip()
    
    return normalized
```

### 4.2 使用示例

```python
# 在候选生成器中使用
class CandidateGenerator:
    def __init__(self, config: dict):
        # 从配置中读取阈值
        self.min_type_compatibility = config.get("min_type_compatibility", 0.5)
    
    def filter_candidates(self, col1_type: str, col2_type: str) -> bool:
        """判断两列是否类型兼容"""
        score = self._get_type_compatibility_score(col1_type, col2_type)
        
        if score >= 0.8:
            # ✅ 放心使用
            return True
        elif score >= 0.5:
            # ⚠️ 可用但需注意
            return True
        else:
            # ❌ 不兼容
            return False
```

---

## 5. 配置建议

### 5.1 推荐阈值

根据不同场景，建议配置不同的阈值：

| 场景 | 阈值 | 说明 |
|------|------|------|
| **严格模式** | 0.8 | 只接受高度兼容的类型 |
| **标准模式** | 0.5 | 接受有精度损失但能JOIN的类型 |
| **宽松模式** | 0.0 | 只排除完全不兼容的类型 |

### 5.2 配置示例

```yaml
relationships:
  single_column:
    # 单列候选的类型兼容性阈值
    min_type_compatibility: 0.5  # 标准模式
  
  composite:
    # 复合键候选的类型兼容性阈值（建议更严格）
    min_type_compatibility: 0.8
```

---

## 6. 测试用例

### 6.1 基本测试

```python
def test_type_compatibility():
    gen = CandidateGenerator(config={})
    
    # 1.0 - 完全相同
    assert gen._get_type_compatibility_score("INTEGER", "INTEGER") == 1.0
    
    # 0.9 - 整数族
    assert gen._get_type_compatibility_score("INTEGER", "BIGINT") == 0.9
    
    # 0.9 - 整数与NUMERIC ✨
    assert gen._get_type_compatibility_score("INTEGER", "NUMERIC") == 0.9
    
    # 0.85 - VARCHAR/TEXT
    assert gen._get_type_compatibility_score("VARCHAR", "TEXT") == 0.85
    
    # 0.8 - CHAR参与
    assert gen._get_type_compatibility_score("CHAR", "VARCHAR") == 0.8
    
    # 0.8 - NUMERIC精度不同
    assert gen._get_type_compatibility_score("NUMERIC(10,2)", "NUMERIC(15,4)") == 0.8
    
    # 0.6 - INTEGER vs FLOAT
    assert gen._get_type_compatibility_score("INTEGER", "REAL") == 0.6
    
    # 0.5 - NUMERIC vs FLOAT ⚠️
    assert gen._get_type_compatibility_score("NUMERIC", "REAL") == 0.5
    
    # 0.5 - DATE vs TIMESTAMP ⚠️
    assert gen._get_type_compatibility_score("DATE", "TIMESTAMP") == 0.5
    
    # 0.0 - 跨大类
    assert gen._get_type_compatibility_score("INTEGER", "VARCHAR") == 0.0
```

### 6.2 边界测试

```python
def test_edge_cases():
    gen = CandidateGenerator(config={})
    
    # 处理空值
    assert gen._get_type_compatibility_score("", "INTEGER") == 0.0
    assert gen._get_type_compatibility_score(None, None) == 0.0
    
    # 处理大小写
    assert gen._get_type_compatibility_score("INTEGER", "integer") == 1.0
    
    # 处理precision/scale
    assert gen._get_type_compatibility_score("NUMERIC(10,2)", "NUMERIC") == 0.8
    
    # 处理数组类型
    assert gen._get_type_compatibility_score("INTEGER[]", "INTEGER") == 1.0
```

---

## 7. 版本历史

### v3.2 (2025-12-01)

**重要改进**：

1. ✅ **INTEGER ↔ NUMERIC** 提升到 **0.9**（原来是 0.8）
   - 理由：整数转NUMERIC是完全无损的
   
2. ✅ **CHAR 类型降级** 到 **0.8**（原来在字符串族统一 0.85）
   - 理由：CHAR有padding陷阱，需要特殊标记
   
3. ✅ **NUMERIC ↔ FLOAT** 降级到 **0.5**（原来是 0.6）
   - 理由：精确数值→近似值，损失更严重
   
4. ✅ **布尔与整数** 新增 **0.6** 评分
   - 理由：PostgreSQL允许隐式转换，但不推荐

5. ✅ 评分层级优化：
   - 去掉了 0.95（太接近1.0）
   - 去掉了 0.7（简化层级）
   - 最终层级：**1.0, 0.9, 0.85, 0.8, 0.6, 0.5, 0.0**

---

## 8. 参考资料

- [PostgreSQL 数据类型官方文档](https://www.postgresql.org/docs/current/datatype.html)
- [PostgreSQL 类型转换规则](https://www.postgresql.org/docs/current/typeconv.html)
- MetaWeave 项目配置文件：`config/relationships.yaml`
- 实现代码：`src/metaweave/core/relationships/candidate_generator.py`

