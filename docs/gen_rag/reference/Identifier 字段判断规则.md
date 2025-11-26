# Identifier 字段判断规则（完整版）

## 一、整体逻辑

```
semantic_role = 'identifier' ⇔ 满足以下任一条件：

1. 有物理约束（PK/FK/UNIQUE）
2. 统计特征明显（高唯一性）
3. 命名特征明显（包含标识关键词）
```

---

## 二、完整判断规则

### 规则 0：前置过滤 - 数据类型白名单

**必须满足**（否则直接排除）

#### ✅ 允许的类型

**整数类型**

- `integer`, `int`, `int4` - 标准整数
- `bigint`, `int8` - 长整数
- `smallint`, `int2` - 短整数
- `serial` - 自增整数
- `bigserial` - 自增长整数
- `smallserial` - 自增短整数

**字符串类型**

- `varchar`, `character varying` - 可变长度字符串
- `char`, `character` - 固定长度字符串
- `bpchar` - blank-padded char（内部类型名）

**UUID类型**

- `uuid` - 通用唯一标识符

**数值类型（有条件）**

- `numeric`, `decimal` - 仅当 `scale = 0`（无小数位）
  - ✓ 示例：`numeric(10,0)` 
  - ✗ 示例：`numeric(10,2)`

#### ❌ 明确排除的类型

**逻辑类型**

- `boolean` - 二值枚举，不是标识符

**文本类型**

- `text` - 无限长度，通常存储内容而非标识

**浮点数类型**

- `real`, `float4` - 单精度浮点数
- `double precision`, `float8` - 双精度浮点数
- `float` - 浮点数（精度问题）

**日期时间类型**

- `date` - 日期
- `time` - 时间
- `timestamp` - 时间戳
- `timestamptz`, `timestamp with time zone`
- `timestamp without time zone`
- `interval` - 时间间隔

**复杂类型**

- `json`, `jsonb` - JSON类型
- `array`, `[]` - 数组类型（如 `integer[]`）
- `bytea` - 二进制数据
- `hstore` - 键值对存储

**几何/网络类型**

- `point`, `line`, `polygon` - 几何类型
- `geometry`, `geography` - PostGIS类型
- `inet`, `cidr` - IP地址
- `macaddr`, `macaddr8` - MAC地址

**范围/特殊类型**

- `int4range`, `int8range`, `numrange`, `tsrange`, `daterange` - 范围类型
- `xml` - XML
- `money` - 货币（有精度问题）
- `bit`, `bit varying` - 位串
- `tsvector`, `tsquery` - 全文搜索
- `oid` - 对象标识符（已过时）

---

### 规则 1：物理约束检查

**直接判定为 identifier**（100% 确定）

字段有以下任一物理约束：

- ✓ `PRIMARY KEY` - 主键
- ✓ `FOREIGN KEY` - 外键
- ✓ `UNIQUE` - 唯一约束

→ 无需进一步判断，直接标记为 identifier

**查询方式：**

从 \output\metaweave\metadata\ddl 目录下的 *.sql中解析sql中的主键、外键和唯一约束。

```sql
-- 方式1：
CREATE TABLE students (
    id INT PRIMARY KEY,
    name VARCHAR(50)
);

-- 方式2：
-- 单字段主键
CREATE TABLE students (
    id INT,
    name VARCHAR(50),
    PRIMARY KEY (id)
);
-- 复合主键
CREATE TABLE orders (
    order_id INT,
    product_id INT,
    quantity INT,
    PRIMARY KEY (order_id, product_id)
);

-- 方式3：建表后添加主键
-- 先创建表
CREATE TABLE students (
    id INT,
    name VARCHAR(50)
);
-- 后添加主键
ALTER TABLE students ADD PRIMARY KEY (id);


```



### 规则 2：逻辑推断 - 条件A（统计特征）

**目标**：识别逻辑主键、唯一约束候选

**判断条件**（同时满足）：

- 唯一性 > 0.95
- 非空率 > 0.80

其中：

- 唯一性 = `distinct_count` / `non_null_count`
- 非空率 = `non_null_count` / `total_count`

**捕获的字段类型**：

- 逻辑主键（命名规范或不规范）
- 唯一约束（业务编号、唯一标识）
- 命名不规范但确实唯一的字段（email, phone, mobile等）

**典型示例**：

- `user_id`: 唯一性=1.0, 非空率=1.0
- `email`: 唯一性=0.96, 非空率=0.95
- `order_no`: 唯一性=0.98, 非空率=0.99
- `pk`: 唯一性=1.0, 非空率=1.0（老系统主键）
- `phone`: 唯一性=0.97, 非空率=0.90

---

### 规则 3：逻辑推断 - 条件B（命名特征）

**目标**：识别逻辑外键、以及命名规范的主键/唯一约束

**判断条件**（同时满足）：

- 字段名包含关键词（见下方详细列表）
- 唯一性 > 0.05（排除枚举）

#### 命名匹配规则（大小写不敏感）

**核心关键词**（优先级从高到低）

**1. ID相关**（最常见）

- `id` → user_id, userId, USER_ID, Id, ID
- `_id` → dept_id, order_id, product_id
- `id_` → id_user, id_order（少见但存在）

**2. Code相关**（业务编码）

- `code` → product_code, dept_code, area_code
- `_code` → user_code, order_code
- `code_` → code_product（少见）

**3. Key相关**（键值）

- `key` → user_key, order_key, warehouse_key
- `_key` → product_key, customer_key
- `pk` → pk_id, user_pk（主键简写）
- `fk` → fk_user, fk_dept（外键简写，少见）

**4. Number/No相关**（编号）

- `no` → order_no, invoice_no, contract_no
- `_no` → ticket_no, serial_no
- `num` → order_num, product_num
- `number` → order_number, invoice_number, contract_number
- `_number` → serial_number, reference_number

**5. 序列号相关**

- `sn` → device_sn, product_sn, serial_sn
- `serial` → serial_number, serial_id, product_serial
- `seq` → sequence_no, seq_id, seq_num

**6. UUID/GUID相关**

- `uuid` → request_uuid, trace_uuid, user_uuid
- `guid` → request_guid, session_guid

**7. 标识符相关**（完整单词）

- `identifier` → user_identifier, unique_identifier
- `uid` → user_uid, device_uid（Unix风格）

**8. 引用相关**

- `ref` → ref_id, reference_id, ref_code
- `reference` → reference_no, reference_number

#### 匹配方式

字段名转小写后，检查是否包含上述任一关键词

**示例**：

- `UserID` → 'userid' 包含 'id' ✓
- `DEPT_CODE` → 'dept_code' 包含 'code' ✓
- `order_no` → 'order_no' 包含 'no' ✓
- `productKey` → 'productkey' 包含 'key' ✓
- `SerialNumber` → 'serialnumber' 包含 'serial' 和 'number' ✓
- `ref_user` → 'ref_user' 包含 'ref' ✓

#### 特殊模式（可选，提高准确率）

**前缀模式**

- `id_*` → id_user, id_order
- `pk_*` → pk_user, pk_order
- `fk_*` → fk_user, fk_department
- `ref_*` → ref_customer, ref_product

**后缀模式**

- `*_id` → user_id, order_id
- `*_code` → product_code, dept_code
- `*_key` → user_key, warehouse_key
- `*_no` → order_no, invoice_no
- `*_num` → order_num, product_num
- `*_sn` → device_sn, product_sn
- `*_uuid` → request_uuid, trace_uuid
- `*_guid` → session_guid, request_guid
- `*_ref` → user_ref, order_ref

#### 中文/拼音环境（可选）

如果系统存在中文拼音命名：

- `bianhao` → 编号（拼音）
- `bianma` → 编码（拼音）
- `daima` → 代码（拼音）

**捕获的字段类型**：

- 逻辑外键（唯一性低，但命名明确）
- 命名规范的主键（也会被条件A捕获，重叠部分）
- 命名规范的唯一约束（也会被条件A捕获，重叠部分）

**典型示例**：

- `dept_id`: 唯一性=0.05（外键，10个部门）
- `category_code`: 唯一性=0.02（外键，5个分类）
- `warehouse_key`: 唯一性=0.01（外键，3个仓库）
- `order_number`: 唯一性=0.98（唯一编号）
- `device_sn`: 唯一性=0.99（设备序列号）
- `ref_user`: 唯一性=0.10（外键引用）

---

### 规则 4：最终判定

**组合逻辑**（满足任一即可）：

```
is_identifier = 
    规则0（类型白名单）通过
    AND
    (
        规则1（物理约束：PK/FK/UNIQUE）
        OR
        规则2（条件A：唯一性>0.95 AND 非空率>0.80）
        OR  
        规则3（条件B：命名包含关键词 AND 唯一性>0.05）
    )
```

---

## 三、完整决策树

```
字段输入
    ↓
┌─────────────────────────────┐
│ 规则0：类型检查              │
│ 类型在白名单？               │
│ - int/bigint/varchar/uuid   │
│ - serial/numeric(scale=0)   │
└─────────────────────────────┘
    ↓ No → ❌ 不是 identifier
    ↓ Yes
┌─────────────────────────────┐
│ 规则1：物理约束检查          │
│ 有PK/FK/UNIQUE约束？        │
└─────────────────────────────┘
    ↓ Yes → ✅ identifier
    ↓ No
┌─────────────────────────────┐
│ 规则2：统计特征检查          │
│ 唯一性 > 0.95               │
│ AND 非空率 > 0.80？         │
└─────────────────────────────┘
    ↓ Yes → ✅ identifier
    ↓ No
┌─────────────────────────────┐
│ 规则3：命名特征检查          │
│ 命名包含关键词：             │
│ id/code/key/no/num/sn/      │
│ uuid/serial/ref             │
│ AND 唯一性 > 0.05？         │
└─────────────────────────────┘
    ↓ Yes → ✅ identifier
    ↓ No
    ↓
❌ 不是 identifier
```

---

## 四、阈值参数表

| 参数 | 阈值 | 说明 | 示例 |
|------|------|------|------|
| 唯一性（条件A） | > 0.95 | 95%以上的值不重复 | 10000条允许500个重复 |
| 非空率（条件A） | > 0.80 | 80%以上的记录有值 | 10000条允许2000个NULL |
| 唯一性（条件B） | > 0.05 | 排除极端重复的枚举 | 10000条至少500个不同值 |

### 阈值设计理由

**唯一性 > 0.95（条件A）**

- 几乎完全唯一，适合做主键/唯一索引
- 允许少量重复（如极少数脏数据或软删除场景）
- 计算：0.95 = 10000条记录允许最多500个重复值

**非空率 > 0.80（条件A）**

- 允许少量NULL（如候选键、可选的唯一标识）
- 比主键要求宽松（主键通常要求100%非空）
- 计算：0.80 = 10000条记录允许最多2000个NULL

**唯一性 > 0.05（条件B）**

- 排除枚举字段（枚举通常 < 0.01）
- 允许外键有大量重复（多对一关系）
- 计算：0.05 = 10000条记录至少需要500个不同值

---

## 五、与其他 semantic_role 的区分

| semantic_role | 关键特征 | 与 identifier 的区别 |
|--------------|---------|---------------------|
| enum | distinct ≤ 20, uniqueness < 0.01 | identifier 唯一性要求 > 0.05，且通常有id/code等关键词 |
| attribute | 通常为记录中的属性字段，无标识关键词, uniqueness 0.5-0.9 | identifier 要么唯一性>0.95，要么命名有关键词 |
| audit | 类型是 timestamp，命名含 created_/updated_/deleted_ | identifier 类型必须是 int/varchar/uuid，命名含 id/code/key |
| measure | 类型是 numeric(有小数)/float，表示度量值 | identifier 不允许浮点类型，numeric必须scale=0 |
|               |                                                          |                                                            |

---

## 六、实施建议

### 优先级顺序

1. 先检查物理约束（快速且100%准确）
2. 再检查统计特征（需要计算但准确率高）
3. 最后检查命名特征（补充外键识别）

### 性能优化

1. **类型白名单检查**：只需查询元数据，极快
2. **物理约束检查**：查询 information_schema，较快
3. **统计计算**：需要扫描数据，最慢
   - 可以采样计算（TABLESAMPLE）
   - 可以缓存结果
   - 可以批量并行处理

### 准确率提升

1. 建立人工标注样本
2. 根据实际业务调整阈值
3. 记录误判案例，优化规则
4. 增加业务特有的命名关键词

---

## 七、规则总结卡片

### 快速记忆

```
┌─────────────────────────────────────────┐
│         Identifier 判断规则              │
├─────────────────────────────────────────┤
│ 类型：int/varchar/uuid/serial           │
│ 物理：PK/FK/UNIQUE → 直接确定            │
│ 统计：唯一性>0.95 + 非空率>0.80          │
│ 命名：包含 id/code/key/no + 唯一性>0.05 │
│                                          │
│ 满足任一条件 → identifier                │
└─────────────────────────────────────────┘
```

### 核心口诀

```
类型先过滤（int/varchar/uuid）
物理约束优先（PK/FK/UNIQUE）
统计看唯一（>0.95 高唯一性）
命名看关键（id/code/key/no/num/sn）
唯一性底线（>0.05 排除枚举）
```

### 覆盖范围

- 物理主键、外键、唯一约束
- 逻辑主键候选（唯一性高）
- 逻辑外键候选（命名明确）
- 业务唯一编码（订单号、序列号）
- 唯一联系方式（email、phone）
- UUID/GUID标识符

---

## 八、命名关键词速查表

| 类别 | 关键词 | 示例字段 |
|------|--------|---------|
| ID类 | id, _id, uid | user_id, userId, device_uid |
| 编码类 | code, _code | product_code, dept_code |
| 键值类 | key, _key, pk, fk | user_key, pk_id, fk_user |
| 编号类 | no, num, number, _number | order_no, serial_number |
| 序列类 | sn, serial, seq | device_sn, product_serial, seq_id |
| UUID类 | uuid, guid | request_uuid, session_guid |
| 引用类 | ref, reference | ref_id, reference_no |
| 标识类 | identifier | user_identifier |

**匹配方式**：字段名转小写后，包含任一关键词即可

