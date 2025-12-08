# 53 增加 Domain 和 Type 属性设计方案

## 1. 需求概述

### 1.1 背景

在 MetaWeave 元数据生成流程中，需要为表添加**业务主题分类（domain）**和**业务类型（category）**属性，以便：
1. 更好地组织和管理元数据
2. 支持按业务主题分组进行关系发现
3. 在 Neo4j 知识图谱中提供更丰富的表属性信息

### 1.2 核心需求

| 序号 | 需求描述 | 涉及步骤 |
|------|----------|----------|
| 1 | 新增 `db_domains.yaml` 配置文件 | 配置 |
| 2 | 通过 LLM 生成 `table_category` 和 `table_domains` | `--step json_llm` |
| 3 | 支持按 domain 分组进行关系发现（含跨域） | `--step rel_llm` |
| 4 | 将新属性写入 Neo4j Table 节点 | `--step cql_llm` |

### 1.3 术语说明

| 属性路径 | 含义 | 类型 | 取值 | 生成方式 | 本次改造 |
|----------|------|------|------|----------|----------|
| `table_info.table_type` | 数据库对象类型 | `string` | `"table"` / `"view"` / `"partitioned_table"` | 数据库元数据提取（`--step ddl`） | ❌ 不涉及 |
| `table_profile.table_category` | 业务类型 | `string` | `"fact"` / `"dim"` / `"bridge"` / `"unknown"` | `--step json`: 规则算法<br>`--step json_llm`: **LLM 推断** | ✅ 本次重点 |
| `table_profile.table_domains` | 业务主题分类 | `list<string>` | `["学生基本信息"]` | `--step json_llm --domain`: LLM 推断 | ✅ 本次重点 |

**关键区分（避免混淆）：**

| 属性 | 层面 | 含义 | 本次改造 |
|------|------|------|----------|
| `table_info.table_type` | **数据库层面** | 数据库对象类型（table/view/partitioned_table） | ❌ 不涉及，由 `--step ddl` 从数据库元数据提取 |
| `table_profile.table_category` | **业务层面** | 业务类型（dim/fact/bridge/unknown） | ✅ 本次重点，由 LLM 推断 |
| `table_profile.table_type` | — | **⚠️ 该属性本次不处理** | — |

> **重要说明：** 
> - `table_profile.table_type` **本次不处理**，请勿与 `table_info.table_type` 或 `table_profile.table_category` 混淆
> - `table_info.table_type`（数据库对象类型）与 `table_profile.table_category`（业务类型）是两个**完全不同**的概念
> - 本次改造仅涉及 `table_profile` 下的 `table_category` 和 `table_domains`，不涉及 `table_info.table_type`

---

## 2. 配置文件设计

### 2.1 db_domains.yaml 文件结构

**文件路径：** `configs/metaweave/db_domains.yaml`

**文件结构：**

- **第一部分（必填）：** `database.description` - 数据库范围描述
- **第二部分（可选）：** `domains` - 业务主题列表，可通过 `--generate-domains` 自动生成

```yaml
# db_domains.yaml
# 数据库业务主题配置

# ===================================================================
# 第一部分：数据库范围描述（必填）
# ===================================================================
database:
  name: "教学管理系统数据库"
  description: |
    这是一个学校的教学管理数据库系统，主要包含以下业务数据：
    - 学生基本信息：学籍、班级、专业等
    - 教师基本信息：职工、职称、部门等
    - 课程管理：课程设置、排课、选课等
    - 成绩管理：考试成绩、学分绩点等

# ===================================================================
# 第二部分：业务主题列表（可选，可自动生成）
# ===================================================================
domains:
  - name: "学生基本信息"
    description: "学生的基础档案信息，包括学籍、班级、专业、联系方式等"
    
  - name: "教师基本信息"
    description: "教师的基础档案信息，包括职工、职称、部门、联系方式等"
    
  - name: "成绩管理"
    description: "考试成绩、学分绩点、成绩统计等数据"

# ===================================================================
# 第三部分：LLM 推断配置（可选）
# ===================================================================
llm_inference:
  max_domains_per_table: 3  # 单个表最多属于几个 domain
```

### 2.2 创建与使用流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    json_llm 功能使用流程                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  【基础用法】--step json_llm                                    │
│  ────────────────────────────────────────────────               │
│  - 默认通过 LLM 为每个表生成 table_category 属性                │
│  - 不需要 db_domains.yaml 文件                                  │
│  - 输出：json_llm/*.json（含 table_category）                   │
│                                                                 │
│  【进阶用法】使用 domain 功能                                   │
│  ────────────────────────────────────────────────               │
│                                                                 │
│  Step 1: 手动创建 db_domains.yaml                               │
│    - 创建文件：configs/metaweave/db_domains.yaml                │
│    - 填写 database.description（必填）                          │
│    - domains 列表可留空                                         │
│                                                                 │
│  Step 2: 自动生成 domains 列表（可选）                          │
│    - 执行 --step json_llm --generate-domains                    │
│    - LLM 根据 description 生成 domains 列表                     │
│    - 自动写入 db_domains.yaml                                   │
│                                                                 │
│  Step 3: 使用 --domain 参数                                     │
│    - --step json_llm --domain：同时生成 table_category          │
│      和 table_domains                                           │
│    - --step rel_llm --domain：按 domain 分组发现关系            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 错误处理

| 场景 | 错误信息 |
|------|----------|
| `--generate-domains` 和 `--domain` 同时使用 | "错误：--generate-domains 和 --domain 不能同时使用，请分两步执行" |
| `db_domains.yaml` 文件不存在 + 使用 `--domain` 参数 | "错误：db_domains.yaml 文件不存在，无法使用 --domain 参数" |
| `db_domains.yaml` 中 `domains` 列表为空 + 使用 `--domain` 参数 | "错误：db_domains.yaml 中 domains 列表为空，请先执行 --generate-domains" |
| `database.description` 为空 + 使用 `--generate-domains` | "错误：database.description 为空，无法生成 domains 列表" |

---

## 3. 改造一：--step json_llm（LLM 生成表属性）

### 3.1 功能概述

**改造目标：** 在 `--step json_llm` 步骤中，通过 LLM 为每个表生成业务属性。

| 功能 | 当前行为 | 改造后行为 |
|------|----------|------------|
| `table_category` | 不生成 | **默认生成**（LLM 推断 dim/fact/bridge/unknown） |
| `table_domains` | 不生成 | 需要 `--domain` 参数触发生成 |

**输出位置：** `output/metaweave/metadata/json_llm/` 目录

### 3.2 命令行参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--domain` | String（可选） | 无 | 启用 table_domains 生成。不传值或传 `all` 表示使用所有 domain；传 `"A,B"` 表示只使用指定 domain |
| `--domains-config` | Path | `configs/metaweave/db_domains.yaml` | 业务主题配置文件路径（不传则使用默认路径） |
| `--generate-domains` | Flag | False | 根据数据库描述自动生成 domain 列表并写入 yaml |

**`--domain` 参数语义（统一定义）：**

| 传参方式 | 含义 |
|----------|------|
| 不传 `--domain` | 不启用 domain 功能，只生成 `table_category` |
| `--domain` 或 `--domain all` | 启用，使用 db_domains.yaml 中**所有** domain |
| `--domain "学生基本信息,成绩管理"` | 启用，只使用**指定**的 domain |

**说明：**
- `--step json_llm` 不加 `--domain` 参数时，默认只生成 `table_category`
- `--domain` 参数需要 `db_domains.yaml` 文件存在且 `domains` 列表不为空
- `--domains-config` 参数可选，不传递时自动使用默认路径

**⚠️ 参数互斥说明：**

| 参数组合 | 是否允许 | 说明 |
|----------|----------|------|
| `--generate-domains` 单独使用 | ✅ 允许 | 生成 domain 列表写入 yaml |
| `--domain` 单独使用 | ✅ 允许 | 使用 yaml 中的 domain 列表 |
| `--generate-domains` + `--domain` 同时使用 | ❌ **不允许** | 程序报错退出 |

> **重要：** `--generate-domains` 和 `--domain` **不能同时使用**。必须分两步执行：
> 1. **第一步**：执行 `--generate-domains` 生成 domain 列表到 yaml 文件
> 2. **第二步**：执行 `--domain` 读取 yaml 中的 domain 列表，为表生成 `table_domains`

**📋 `domains` 列表为空时的行为：**

| 场景 | `db_domains.yaml` 中 `domains` 状态 | 行为 |
|------|-------------------------------------|------|
| 不传 `--domain` | 可以为空或不存在 | ✅ 正常执行，只生成 `table_category` |
| 传 `--domain` | 为空 `[]` 或不存在 | ❌ **报错退出**："db_domains.yaml 中 domains 列表为空，请先执行 --generate-domains" |
| 传 `--domain` | 有内容 | ✅ 正常执行，生成 `table_category` + `table_domains` |

> **说明：** 如果只需要生成 `table_category`，无需创建 `db_domains.yaml` 文件，直接执行 `--step json_llm` 即可。

**命令示例：**

```bash
# ========================================
# 基础用法：只生成 table_category（不需要 yaml）
# ========================================
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json_llm

# ========================================
# 进阶用法：使用 domain 功能（需要分两步执行）
# ========================================

# 【第一步】自动生成 domain 列表（写入 db_domains.yaml）
# 前提：db_domains.yaml 中已填写 database.description
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json_llm --generate-domains

# 【第二步】生成 table_category + table_domains（使用所有 domain）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json_llm --domain
# 或等价于
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json_llm --domain all

# 【第二步】生成 table_category + table_domains（只使用指定 domain）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json_llm --domain "学生基本信息,成绩管理"

# ========================================
# ❌ 错误用法：--generate-domains 和 --domain 不能同时使用
# ========================================
# 以下命令会报错退出：
# python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step json_llm --generate-domains --domain
```

### 3.3 LLM 调用策略

#### 3.3.1 调用粒度与合并

| 项目 | 说明 |
|------|------|
| **调用粒度** | 每次调用处理**单个表**的 JSON |
| **调用合并** | `table_category` 和 `table_domains` 在**同一次 LLM 调用**中完成 |
| **动态 Prompt** | 根据是否有 `--domain` 参数，动态构建不同的 Prompt |

#### 3.3.2 动态 Prompt 构建

| 参数组合 | Prompt 内容 | LLM 返回格式 |
|----------|-------------|--------------|
| 无 `--domain` | 只包含 category 推断任务 | `{"table_category": "fact", "reason": "..."}` |
| 有 `--domain` | 包含 category + domains 推断任务 | `{"table_category": "fact", "table_domains": [...], "reason": "..."}` |

**动态构建代码示例：**

```python
def build_prompt(
    table_json: Dict, 
    include_domains: bool,
    db_config: Dict = None  # 从 db_domains.yaml 读取
) -> str:
    """动态构建 LLM Prompt"""
    
    # 基础提示词（仅 category）
    base_prompt = f'''
你是一名数据仓库建模专家，请根据我提供的"表结构"和"样例数据"判断该表的类型。

## 表结构与样例数据
{json.dumps(table_json, ensure_ascii=False, indent=2)}

## 类型说明
1) fact：事实类表，特征：有度量值、随业务增长、含多维度外键
2) dim：维度类表，特征：描述性字段多、较稳定、以ID标识实体
3) bridge：桥接表，特征：用于多对多关系，通常只包含外键
4) unknown：无法判断时选择，不要强行猜测
'''
    
    # 如果需要 domain 推断，动态添加
    if include_domains and db_config:
        # 读取数据库描述
        db_description = db_config.get("database", {}).get("description", "")
        
        # 读取 domain 列表并格式化
        domains = db_config.get("domains", [])
        domain_list_text = "\n".join(
            f"{i}) {d['name']}：{d.get('description', '')}"
            for i, d in enumerate(domains, 1)
        )
        
        # 重新构建包含 domain 的提示词
        base_prompt = f'''
你是一名数据仓库建模专家，请根据我提供的"表结构"和"样例数据"完成任务。

## 数据库背景
{db_description}

## 表结构与样例数据
{json.dumps(table_json, ensure_ascii=False, indent=2)}

## 任务一：判断表的类型（table_category）
1) fact：事实类表，特征：有度量值、随业务增长、含多维度外键
2) dim：维度类表，特征：描述性字段多、较稳定、以ID标识实体
3) bridge：桥接表，特征：用于多对多关系，通常只包含外键
4) unknown：无法判断时选择，不要强行猜测

## 任务二：判断表的业务主题（table_domains）
从以下主题列表中选择（可单选或多选）：
{domain_list_text}

如果不属于任何主题，返回空数组。
'''
    
    # 动态构建输出格式
    if include_domains:
        output_format = '''
## 输出格式（JSON）
{"table_category": "<fact|dim|bridge|unknown>", "table_domains": [...], "reason": "..."}
'''
    else:
        output_format = '''
## 输出格式（JSON）
{"table_category": "<fact|dim|bridge|unknown>", "reason": "..."}
'''
    
    return base_prompt + output_format + "\n请只返回 JSON，不要包含其他内容。"
```

#### 3.3.3 复用 LLMService

**复用方式：** 直接使用现有的 `src/metaweave/services/llm_service.py`

| 方法 | 说明 | 适用场景 |
|------|------|----------|
| `_call_llm(prompt)` | 同步调用 | 调试、少量表 |
| `batch_call_llm_async(prompts)` | 批量异步调用 | 生产环境、大量表 |

**调用示例：**

```python
class LLMJsonGenerator:
    def __init__(self, config: Dict, connector: DatabaseConnector):
        # 初始化 LLM 服务（复用现有配置）
        llm_config = config.get("llm", {})
        self.llm_service = LLMService(llm_config)
    
    def _infer_table_profile(self, table_json: Dict) -> Dict:
        """推断表的 category 和 domains"""
        prompt = build_prompt(table_json, self.include_domains, self.db_config)
        response = self.llm_service._call_llm(prompt)
        return self._parse_response(response)
```

### 3.4 table_category 类型定义

| 类型 | 说明 | 特征 |
|------|------|------|
| `fact` | 事实类表（含明细事实、汇总事实、快照表、流水表等） | 有度量值、随业务增长、含多维度外键、粒度明确 |
| `dim` | 维度类表（含实体维、枚举维等） | 描述性字段多、较稳定、以ID标识实体、极少有可汇总指标 |
| `bridge` | 桥接表 | 用于多对多关系，通常只包含外键，缺少描述性字段 |
| `unknown` | 无法判断 | 不符合以上任何特征时使用，避免强行猜测 |

### 3.5 输出格式

**JSON 文件变更（table_profile 节点）：**

```json
{
  "table_profile": {
    "table_category": "fact",
    "table_domains": ["成绩管理"],
    "physical_constraints": { ... }
  }
}
```

**LLM 返回格式：**

```json
// 无 --domain 参数
{
  "table_category": "fact",
  "reason": "该表包含订单记录，有时间戳和金额字段，符合事实表特征"
}

// 有 --domain 参数
{
  "table_category": "fact",
  "table_domains": ["成绩管理"],
  "reason": "该表存储学生成绩记录，属于事实表，归属成绩管理主题"
}

// 无法判断
{
  "table_category": "unknown",
  "table_domains": [],
  "reason": "该表结构不符合典型特征，无法准确判断"
}
```

### 3.6 流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    --step json_llm 流程                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────────────────────────────┐  │
│  │ 读取 DDL 目录 │───▶│ 遍历每个 DDL 文件                     │  │
│  └──────────────┘    └──────────────────────────────────────┘  │
│                                    │                            │
│                                    ▼                            │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ 1. 生成基础 JSON（现有逻辑）                             │    │
│  │    - table_info、column_profiles、sample_records        │    │
│  └────────────────────────────────────────────────────────┘    │
│                                    │                            │
│                                    ▼                            │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ 2. LLM 推断 table_category（默认执行）                   │    │
│  │    → 调用 LLM，返回 dim/fact/bridge/unknown             │    │
│  └────────────────────────────────────────────────────────┘    │
│                                    │                            │
│                          ┌────────┴────────┐                   │
│                          │ 有 --domain 参数?│                   │
│                          └────────┬────────┘                   │
│                       No          │          Yes               │
│                       │           ▼           │                │
│                       │  ┌────────────────────────────────┐   │
│                       │  │ 3. LLM 推断 table_domains       │   │
│                       │  │    - 读取 db_domains.yaml       │   │
│                       │  │    - 匹配业务主题               │   │
│                       │  └────────────────────────────────┘   │
│                       │                   │                    │
│                       └───────────┬───────┘                    │
│                                   │                            │
│                                   ▼                            │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ 4. 写入 table_profile.table_category                    │    │
│  │    写入 table_profile.table_domains（如果有）           │    │
│  └────────────────────────────────────────────────────────┘    │
│                                   │                            │
│                                   ▼                            │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ 5. 输出 JSON 文件到 json_llm/ 目录                      │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 改造二：--step rel_llm（按 domain 分组发现关系）

### 4.1 功能概述

**改造目标：** 在 `--step rel_llm` 步骤中，支持按 domain 分组进行关系发现。

| 功能 | 当前行为 | 改造后行为 |
|------|----------|------------|
| 表对组合 | 所有表两两配对 | 支持按 domain 过滤/分组 |
| 跨域关系 | 不支持 | 支持 `--cross-domain` 参数 |
| 关系发现逻辑 | LLM 判断 + 评分 | **保持不变**，复用现有逻辑 |

**输入位置：** `output/metaweave/metadata/json_llm/` 目录（读取 table_domains）
**输出位置：** `output/metaweave/metadata/rel/` 目录

**前置条件校验：** 使用 `--domain` 参数时，所有表的 JSON 必须包含 `table_profile.table_domains` 属性

### 4.2 命令行参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--domain` | String（可选） | 无 | 指定要处理的 domain。不传值或传 `all` 表示使用所有 domain；传 `"A,B"` 表示只使用指定 domain |
| `--cross-domain` | Flag | False | 是否包含跨域关系 |
| `--domains-config` | Path | `configs/metaweave/db_domains.yaml` | 业务主题配置文件路径（不传则使用默认路径） |

**`--domain` 参数语义（与 json_llm 统一）：**

| 传参方式 | 含义 |
|----------|------|
| 不传 `--domain` | 不启用 domain 功能，所有表两两配对（**现有行为**） |
| `--domain` 或 `--domain all` | 启用，使用 db_domains.yaml 中**所有** domain |
| `--domain "A,B"` | 启用，只使用**指定**的 domain |

**参数组合与行为：**

| 参数组合 | 行为描述 |
|----------|----------|
| 无 `--domain` | 不分 domain，所有表两两配对（**现有行为**） |
| `--domain` 或 `--domain all` | 逐个 domain 内部寻找关系，**不跨域** |
| `--domain "A,B"` | 只在 A 内部 + B 内部寻找关系，**不跨域** |
| `--domain "A,B" --cross-domain` | A 内部 + B 内部 + **A与B之间的跨域关系** |
| `--domain all --cross-domain` | 所有 domain 内部 + **所有 domain 之间的跨域关系** |

**错误处理（使用 `--domain` 参数时）：**

| 场景 | 处理方式 | 错误信息 |
|------|----------|----------|
| JSON 文件缺少 `table_profile.table_domains` 属性 | **ERROR 退出** | `ERROR: 表 {table_name} 的 JSON 文件缺少 table_domains 属性，请先执行 --step json_llm --domain` |
| `table_profile.table_domains` 为空数组 `[]` | 正常处理 | 该表不参与任何 domain 的关系发现（被排除） |
| 表不属于任何指定的 domain | 正常处理 | 该表被过滤，不参与关系发现 |

> **重要说明：** 使用 `--domain` 参数时，必须确保所有 JSON 文件已通过 `--step json_llm --domain` 生成。如果发现任何表缺少 `table_domains` 属性，程序将立即报错退出，避免关系发现静默失效。

**命令示例：**

```bash
# 不分 domain，所有表两两配对（现有行为）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm

# 按所有 domain 分组处理，不跨域（以下两种写法等价）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain all

# 只处理指定 domain 内部，不跨域
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain "学生基本信息,成绩管理"

# 指定 domain 内部 + 跨域关系
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain "学生基本信息,成绩管理" --cross-domain

# 所有 domain 内部 + 所有跨域关系（以下两种写法等价）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain --cross-domain
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain all --cross-domain
```

### 4.3 表对组合逻辑

#### 4.3.1 场景示例

**假设：**
- Domain **A** 包含表：T1, T2
- Domain **B** 包含表：T3, T4
- Domain **C** 包含表：T5

**各模式计算：**

```
┌─────────────────────────────────────────────────────────────────┐
│ 无 --domain 参数（现有行为）                                    │
├─────────────────────────────────────────────────────────────────┤
│ 表集合: {T1, T2, T3, T4, T5}                                    │
│ 表对:   所有两两配对 = C(5,2) = 10 个                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ --domain 或 --domain all（无 --cross-domain）                   │
├─────────────────────────────────────────────────────────────────┤
│ 表对:                                                           │
│   - Domain A 内部: (T1, T2)                   → 1 个            │
│   - Domain B 内部: (T3, T4)                   → 1 个            │
│   - Domain C 内部: (T5) 单表无配对            → 0 个            │
│ 总数:   2 个                                                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ --domain "A,B"（无 --cross-domain）                             │
├─────────────────────────────────────────────────────────────────┤
│ 表对:                                                           │
│   - Domain A 内部: (T1, T2)                   → 1 个            │
│   - Domain B 内部: (T3, T4)                   → 1 个            │
│ 总数:   2 个                                                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ --domain "A,B" --cross-domain                                   │
├─────────────────────────────────────────────────────────────────┤
│ 表对:                                                           │
│   - Domain A 内部: (T1, T2)                   → 1 个            │
│   - Domain B 内部: (T3, T4)                   → 1 个            │
│   - A↔B 跨域: (T1,T3), (T1,T4), (T2,T3), (T2,T4) → 4 个        │
│ 总数:   6 个                                                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ --domain --cross-domain 或 --domain all --cross-domain          │
├─────────────────────────────────────────────────────────────────┤
│ 表对:                                                           │
│   - Domain A 内部: (T1, T2)                   → 1 个            │
│   - Domain B 内部: (T3, T4)                   → 1 个            │
│   - Domain C 内部: (T5)                       → 0 个            │
│   - A↔B 跨域: (T1,T3), (T1,T4), (T2,T3), (T2,T4) → 4 个        │
│   - A↔C 跨域: (T1,T5), (T2,T5)               → 2 个            │
│   - B↔C 跨域: (T3,T5), (T4,T5)               → 2 个            │
│ 总数:   10 个（等同于全量扫描，但分阶段处理）                   │
└─────────────────────────────────────────────────────────────────┘
```

#### 4.3.2 跨域与表集合交集处理

**核心概念：** 跨域关系是找"不同 domain 中的表之间的关联"，不只是找"共享的表"。

**情况1：两个 domain 表集合没有交集（常见情况）**

```
Domain A: [T1, T2]
Domain B: [T3, T4]
A ∩ B = ∅

跨域表对 = A × B = (T1,T3), (T1,T4), (T2,T3), (T2,T4) → 4 个
```

**情况2：两个 domain 表集合有交集（一个表属于多个 domain）**

```
Domain A: [T1, T2, T3]
Domain B: [T3, T4]       ← T3 同时属于 A 和 B
A ∩ B = {T3}

域内关系：
  - A 内部: (T1,T2), (T1,T3), (T2,T3) → 3 个
  - B 内部: (T3,T4)                   → 1 个
```

**跨域候选分析（A × B）：**

| 配对 | 是否已在域内处理 | 跨域处理？ |
|------|------------------|------------|
| (T1, T3) | ✅ A 内部已处理 | ❌ 跳过 |
| (T1, T4) | ❌ 未处理 | ✅ **需要处理** |
| (T2, T3) | ✅ A 内部已处理 | ❌ 跳过 |
| (T2, T4) | ❌ 未处理 | ✅ **需要处理** |
| (T3, T4) | ✅ B 内部已处理 | ❌ 跳过 |

**最终跨域表对：(T1, T4), (T2, T4) → 2 个**

> **重要说明：** T1, T2 不在交集中，但 (T1, T4) 和 (T2, T4) 仍然会被跨域处理。去重逻辑只是避免重复处理已在域内处理过的表对，不会遗漏交集外的表。

#### 4.3.3 表对组合代码

```python
def generate_table_pairs(
    tables: Dict[str, Dict],
    domain_filter: List[str],
    cross_domain: bool,
    all_domains: List[str]
) -> List[Tuple[str, str]]:
    """生成表对组合
    
    Args:
        tables: 所有表的 JSON 数据 {full_name: json_data}
        domain_filter: 指定的 domain 列表，["all"] 表示全部
        cross_domain: 是否包含跨域关系
        all_domains: yaml 中配置的完整 domain 列表
    """
    # 1. 确定要处理的 domain 列表
    if not domain_filter or "all" in domain_filter:
        target_domains = all_domains
    else:
        target_domains = domain_filter
    
    # 2. 按 domain 分组表
    domain_tables = {}  # {domain_name: [table_full_names]}
    for full_name, data in tables.items():
        table_domains = data.get("table_profile", {}).get("table_domains", [])
        for d in table_domains:
            if d in target_domains:
                domain_tables.setdefault(d, []).append(full_name)
    
    # 3. 生成域内表对
    pairs = []
    for domain, table_list in domain_tables.items():
        pairs.extend(combinations(table_list, 2))
    
    # 4. 如果需要跨域，生成跨域表对
    if cross_domain:
        processed_pairs = set(pairs)  # 用于去重
        
        domain_list = list(domain_tables.keys())
        for i, d1 in enumerate(domain_list):
            for d2 in domain_list[i+1:]:
                for t1 in domain_tables[d1]:
                    for t2 in domain_tables[d2]:
                        pair = tuple(sorted([t1, t2]))
                        if pair not in processed_pairs:
                            pairs.append(pair)
                            processed_pairs.add(pair)
    
    return pairs
```

### 4.4 与现有 LLMRelationshipDiscovery 的集成

**关键点：** `--domain` 参数只影响"哪些表参与关系发现"，"如何发现关系"的逻辑保持不变。

**代码变更位置：**

```python
# src/metaweave/core/relationships/llm_relationship_discovery.py

class LLMRelationshipDiscovery:
    def __init__(self, config: Dict, connector: DatabaseConnector):
        # ... 现有初始化代码 ...
        
        # 新增：domain 过滤参数
        self.domain_filter = None      # --domain 参数值
        self.cross_domain = False      # --cross-domain 参数
        self.domains_config = None     # db_domains.yaml 内容
    
    def discover(self) -> Dict:
        """发现关联关系"""
        # 1. 加载表（现有逻辑）
        tables = self._load_all_tables()
        
        # 2. 【新增】生成表对组合
        if self.domain_filter:
            # 2.1 【新增】校验所有表是否包含 table_domains 属性
            self._validate_table_domains(tables)
            
            # 2.2 从 json_llm 中读取 table_domains，按 domain 过滤
            table_pairs = self._generate_table_pairs_by_domain(tables)
        else:
            # 现有行为：所有表两两配对
            table_pairs = list(combinations(tables.keys(), 2))
        
        # 3. 两两调用 LLM 判断关联（现有逻辑，复用）
        llm_candidates = self._discover_llm_candidates(tables, table_pairs)
        
        # 4. 对候选关联进行评分（现有逻辑，复用）
        scored_relations = self._score_candidates(llm_candidates, tables)
        
        # 5. 输出结果（现有逻辑，复用）
        return self._build_output(scored_relations)
    
    def _validate_table_domains(self, tables: Dict) -> None:
        """【新增】校验所有表是否包含 table_domains 属性
        
        如果任何表缺少 table_domains 属性，立即报错退出
        """
        missing_tables = []
        for full_name, data in tables.items():
            table_profile = data.get("table_profile", {})
            if "table_domains" not in table_profile:
                missing_tables.append(full_name)
        
        if missing_tables:
            logger.error(
                "以下表的 JSON 文件缺少 table_domains 属性，"
                "请先执行 --step json_llm --domain 生成："
            )
            for table in missing_tables:
                logger.error(f"  - {table}")
            raise ValueError(
                f"发现 {len(missing_tables)} 个表缺少 table_domains 属性，"
                "无法按 domain 进行关系发现"
            )
    
    def _generate_table_pairs_by_domain(self, tables: Dict) -> List[Tuple]:
        """【新增】按 domain 生成表对组合"""
        all_domains = [d["name"] for d in self.domains_config.get("domains", [])]
        
        return generate_table_pairs(
            tables=tables,
            domain_filter=self.domain_filter,
            cross_domain=self.cross_domain,
            all_domains=all_domains
        )
```

### 4.5 流程图

```
┌─────────────────────────────────────────────────────────────────┐
│          --step rel_llm [--domain] [--cross-domain] 流程        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐    ┌─────────────────────────────────┐   │
│  │ 读取 json_llm/*   │───▶│ 加载所有表的 JSON                │   │
│  │                  │    │ （包含 table_domains）           │   │
│  └──────────────────┘    └─────────────────────────────────┘   │
│                                    │                            │
│                                    ▼                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 判断是否有 --domain 参数                                  │   │
│  │                                                          │   │
│  │  无 --domain       → 所有表两两配对（现有行为）          │   │
│  │  有 --domain       → 按 domain 分组生成表对              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                    │                            │
│                          ┌────────┴────────┐                   │
│                          │ 有 --domain?    │                   │
│                          └────────┬────────┘                   │
│                    No             │           Yes              │
│                    │              │            │               │
│                    ▼              │            ▼               │
│  ┌────────────────────────┐      │   ┌────────────────────┐   │
│  │ 所有表两两配对          │      │   │ 按 domain 分组表   │   │
│  │ C(n,2) 个表对          │      │   │ 生成域内表对       │   │
│  └────────────────────────┘      │   └────────────────────┘   │
│                    │              │            │               │
│                    │              │   ┌────────┴────────┐      │
│                    │              │   │--cross-domain?  │      │
│                    │              │   └────────┬────────┘      │
│                    │              │     No     │    Yes        │
│                    │              │     │      │     │         │
│                    │              │     │      ▼     │         │
│                    │              │     │  ┌────────────────┐  │
│                    │              │     │  │ 添加跨域表对   │  │
│                    │              │     │  │ (笛卡尔积-去重)│  │
│                    │              │     │  └────────────────┘  │
│                    │              │     │      │               │
│                    └──────────────┴─────┴──────┘               │
│                                    │                            │
│  ══════════════════════════════════════════════════════════    │
│  │         以下复用现有 LLMRelationshipDiscovery 逻辑      │    │
│  ══════════════════════════════════════════════════════════    │
│                                    │                            │
│                                    ▼                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 两两调用 LLM 判断关联关系                                │   │
│  │ （复用 RELATIONSHIP_DISCOVERY_PROMPT）                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                    │                            │
│                                    ▼                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 对候选关联进行评分计算                                    │   │
│  │ （复用 RelationshipScorer）                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                    │                            │
│                                    ▼                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 输出结果到 rel/ 目录                                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. 改造三：--step cql_llm（写入新属性）

### 5.1 本次改造范围

**写入 Neo4j 的新属性：**
- `table_profile.table_category` ✅ 本次改造
- `table_profile.table_domains` ✅ 本次改造

**不在本次改造范围：**
- `table_info.table_type` ❌ **不在本次改造范围**（该属性为数据库对象类型 table/view，由现有元数据提取逻辑生成，非 LLM 推断，已在现有 CQL 中处理）

> **说明：** `table_info.table_type` 是数据库层面的对象类型（table/view/partitioned_table），与本次新增的业务属性（table_category/table_domains）无关，不需要在本次改造中处理。

### 5.2 读取新属性

从 `json_llm/` 目录读取表的 JSON，提取：
- `table_profile.table_category`
- `table_profile.table_domains`

### 5.2 TableNode 模型变更

```python
@dataclass
class TableNode:
    # ... 现有属性 ...
    
    # 新增属性
    table_domains: List[str] = field(default_factory=list)
    table_category: Optional[str] = None
```

### 5.3 CQL 变更

```cypher
UNWIND $tables AS t
MERGE (n:Table {full_name: t.full_name})
SET n.id           = t.full_name,
    n.schema       = t.schema,
    n.name         = t.name,
    n.comment      = t.comment,
    // ... 现有属性 ...
    // 新增属性（兼容旧 JSON）
    n.table_domains  = CASE WHEN t.table_domains IS NOT NULL AND size(t.table_domains) > 0 
                            THEN t.table_domains 
                            ELSE n.table_domains END,
    n.table_category = CASE WHEN t.table_category IS NOT NULL 
                            THEN t.table_category 
                            ELSE n.table_category END;
```

### 5.4 兼容性处理

- 若 JSON 中 `table_domains` 为空数组或不存在，保留 Neo4j 中原有值
- 若 JSON 中 `table_category` 为 null 或不存在，保留 Neo4j 中原有值
- 兼容不使用 LLM 生成的旧 JSON 文件

---

## 6. 代码变更清单

### 6.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `configs/metaweave/db_domains.yaml` | 业务主题配置模板 |
| `src/metaweave/core/metadata/table_profile_llm.py` | LLM 表属性推断器 |

### 6.2 修改文件

| 文件路径 | 变更说明 |
|----------|----------|
| `src/metaweave/cli/metadata_cli.py` | 新增 `--domain`、`--cross-domain`、`--generate-domains` 参数 |
| `src/metaweave/core/metadata/llm_json_generator.py` | 集成 LLM 推断，生成 table_category 和 table_domains |
| `src/metaweave/core/relationships/llm_relationship_discovery.py` | 支持按 domain 过滤表对，支持 --cross-domain |
| `src/metaweave/core/cql_generator/reader.py` | 读取 `table_domains` 和 `table_category` |
| `src/metaweave/core/cql_generator/writer.py` | 写入新属性到 CQL |
| `src/metaweave/core/cql_generator/models.py` | TableNode 新增属性 |

---

## 7. 测试计划

### 7.1 单元测试

| 测试项 | 测试内容 |
|--------|----------|
| `test_domain_config_loading` | 验证 db_domains.yaml 配置文件加载 |
| `test_llm_category_inference` | 验证 LLM 推断 table_category |
| `test_llm_domain_inference` | 验证 LLM 推断 table_domains |
| `test_json_llm_default` | 验证 --step json_llm 默认生成 table_category |
| `test_json_llm_with_domain` | 验证 --step json_llm --domain 同时生成 |
| `test_generate_domains` | 验证 --generate-domains 自动生成 |
| `test_domain_param_without_config` | 验证无 db_domains.yaml 时报错 |
| `test_rel_llm_no_domain_param` | 验证 rel_llm 无 --domain 时全量扫描 |
| `test_rel_llm_domain_filter` | 验证 rel_llm --domain 按 domain 分组 |
| `test_rel_llm_cross_domain` | 验证 --cross-domain 包含跨域关系 |
| `test_cql_new_attributes` | 验证 CQL 包含新属性 |
| `test_backward_compatibility` | 验证旧 JSON 兼容性 |

### 7.2 集成测试

| 测试项 | 测试内容 |
|--------|----------|
| `test_json_llm_full_flow` | 完整执行 json_llm 步骤 |
| `test_rel_llm_domain_flow` | 按 domain 过滤的 rel_llm 完整流程 |
| `test_cql_llm_with_new_attrs` | cql_llm 写入新属性 |
| `test_full_pipeline` | 完整流程 json_llm → rel_llm → cql_llm |

---

## 8. 实施计划

### 阶段一：基础功能（优先级 P0）

1. 创建 `db_domains.yaml` 配置模板
2. 实现 `--step json_llm` 中 LLM 推断 table_category（默认）
3. 实现 `--step json_llm --domain` 推断 table_domains
4. 修改 CQL 模块，读取和写入新属性

### 阶段二：按 domain 发现关系（优先级 P1）

1. 实现 `--step rel_llm --domain` 过滤逻辑
2. 实现 `--cross-domain` 跨域表对生成
3. 集成测试

### 阶段三：LLM 增强（优先级 P1）

1. 实现 `--generate-domains` 自动生成功能
2. 完善 Prompt 模板

### 阶段四：收尾（优先级 P2）

1. 编写完整测试用例
2. 更新文档和 README

---

## 9. 附录

### 9.1 Prompt 模板：仅 table_category

```
你是一名数据仓库建模专家，请根据我提供的"表结构"和"样例数据"判断该表的类型。

## 表结构与样例数据
```json
{table_json}
```

## 类型说明
1) fact：事实类表（含明细事实、汇总事实、快照表、流水表等）
   特征：有度量值、随业务增长、含多维度外键、粒度明确。

2) dim：维度类表（含实体维、枚举维等）
   特征：描述性字段多、较稳定、以ID标识实体、极少有可汇总指标。

3) bridge：桥接表
   特征：用于多对多关系，通常只包含外键，缺少描述性字段。

4) unknown：无法判断时请选择 unknown，不要强行猜测。

## 输出格式（JSON）
```json
{
  "table_category": "<fact | dim | bridge | unknown>",
  "reason": "基于字段和样例数据的简要判断依据"
}
```

请只返回 JSON，不要包含其他内容。
```

### 9.2 Prompt 模板：table_category + table_domains

```
你是一名数据仓库建模专家，请根据我提供的"表结构"和"样例数据"完成以下两个任务。

## 数据库背景
{database_description}

## 表结构与样例数据
```json
{table_json}
```

## 任务一：判断表的类型（table_category）
1) fact：事实类表，特征：有度量值、随业务增长、含多维度外键
2) dim：维度类表，特征：描述性字段多、较稳定、以ID标识实体
3) bridge：桥接表，特征：用于多对多关系，通常只包含外键
4) unknown：无法判断时选择，不要强行猜测

## 任务二：判断表的业务主题（table_domains）
从以下主题列表中选择（可单选或多选）：

{domain_list}

如果该表不属于任何主题，请返回空数组。

## 输出格式（JSON）
```json
{
  "table_category": "<fact | dim | bridge | unknown>",
  "table_domains": ["主题名称1", "主题名称2"],
  "reason": "基于字段和样例数据的简要判断依据"
}
```

请只返回 JSON，不要包含其他内容。
```

### 9.3 Prompt 模板：生成 domain 列表

```
你是一个数据库业务分析专家。请根据以下数据库描述，生成合理的业务主题分类列表。

## 数据库描述
{database_description}

## 任务
1. 分析数据库的业务范围
2. 划分合理的业务主题（建议 3-8 个）
3. 每个主题提供名称和描述

## 输出格式（YAML）
```yaml
domains:
  - name: "主题名称"
    description: "主题描述"
```
```

---

## 10. 参考资料

- 原始需求：`docs/gen_rag/53_增加domain和type的需求.txt`
- 现有配置：`configs/metaweave/metadata_config.yaml`
- json_llm 实现：`src/metaweave/core/metadata/llm_json_generator.py`
- rel_llm 实现：`src/metaweave/core/relationships/llm_relationship_discovery.py`
- CQL 生成器：`src/metaweave/core/cql_generator/`
- LLM 服务：`src/metaweave/services/llm_service.py`
