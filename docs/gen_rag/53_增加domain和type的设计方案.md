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
  # ⚠️ _未分类_ 是系统预置的特殊 domain，请勿删除
  # 当 LLM 无法为表分配合适的业务主题时，会自动归入此 domain
  - name: "_未分类_"
    description: "无法归入其他业务主题的表"
    
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

**实现位置：** `src/metaweave/cli/metadata_cli.py` 的 `metadata()` 函数中，在执行业务逻辑前进行校验。

**参数互斥检查代码：**

```python
# metadata_cli.py - metadata() 函数开头

# 参数互斥检查
if generate_domains and domain:
    click.echo("❌ 错误：--generate-domains 和 --domain 不能同时使用，请分两步执行", err=True)
    raise click.Abort()
```

> **详细校验逻辑见 6.3.3 节。**

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

### 3.3 --generate-domains 功能设计

#### 3.3.1 功能说明

`--generate-domains` 用于根据 `db_domains.yaml` 中的 `database.description` 自动生成 `domains` 列表。

#### 3.3.2 实现位置

新增文件：`src/metaweave/core/metadata/domain_generator.py`

> **设计说明：** `--generate-domains` 是一个独立功能（输入：yaml 的 description → 输出：更新的 yaml），与 JSON 生成逻辑无关，因此单独创建模块。

#### 3.3.3 处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│                --generate-domains 处理流程                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 读取 db_domains.yaml                                        │
│     └─ 提取 database.description                               │
│                                                                 │
│  2. 校验 description                                            │
│     └─ 若为空 → ERROR 退出                                     │
│                                                                 │
│  3. 调用 LLM 生成 domains 列表                                  │
│     └─ 使用 Prompt 模板（附录 9.3）                            │
│                                                                 │
│  4. 解析 LLM 返回结果                                           │
│     ├─ 期望格式：JSON（便于解析）                              │
│     └─ 解析失败 → ERROR 退出                                   │
│                                                                 │
│  5. 写入 db_domains.yaml                                        │
│     └─ 合并到 domains 节点（覆盖现有）                         │
│                                                                 │
│  6. 输出成功信息                                                │
│     └─ "✅ 已生成 N 个 domain 并写入 xxx.yaml"                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 3.3.4 代码实现

**CLI 入口（metadata_cli.py）：**

```python
# 在 json_llm 步骤处理前检查
if step == "json_llm" and generate_domains:
    from src.metaweave.core.metadata.domain_generator import DomainGenerator
    
    # 注意：config 是 CLI 参数（字符串路径），需要先加载为字典
    with open(config, 'r', encoding='utf-8') as f:
        main_config = yaml.safe_load(f)
    
    # domains_config 是 CLI 的 --domains-config 参数
    generator = DomainGenerator(main_config, domains_config)
    domains = generator.generate_from_description()
    generator.write_to_yaml(domains)
    
    click.echo(f"✅ 已生成 {len(domains)} 个 domain 并写入 {domains_config}")
    return  # 生成后退出，不执行 json_llm 主流程
```

**DomainGenerator 类：**

```python
# src/metaweave/core/metadata/domain_generator.py

import json
import yaml
import logging
from typing import Dict, List
from src.metaweave.services.llm_service import LLMService

logger = logging.getLogger("metaweave.domain_generator")


class DomainGenerator:
    """Domain 列表生成器"""
    
    def __init__(self, config: Dict, yaml_path: str):
        self.config = config
        self.yaml_path = yaml_path
        self.llm_service = LLMService(config.get("llm", {}))
        self.db_config = self._load_yaml()
    
    def _load_yaml(self) -> Dict:
        """加载 db_domains.yaml"""
        try:
            with open(self.yaml_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            raise FileNotFoundError(
                f"错误：{self.yaml_path} 文件不存在，"
                "请先创建并填写 database.description"
            )
    
    def generate_from_description(self) -> List[Dict]:
        """根据 description 生成 domains 列表"""
        # 1. 获取 description
        description = self.db_config.get("database", {}).get("description", "")
        if not description or not description.strip():
            raise ValueError(
                "错误：database.description 为空，无法生成 domains 列表"
            )
        
        # 2. 构建 Prompt
        prompt = self._build_prompt(description)
        
        # 3. 调用 LLM
        logger.info("正在调用 LLM 生成 domains 列表...")
        response = self.llm_service._call_llm(prompt)
        
        # 4. 解析返回结果
        domains = self._parse_response(response)
        logger.info(f"成功生成 {len(domains)} 个 domain")
        
        return domains
    
    def _build_prompt(self, description: str) -> str:
        """构建生成 domains 的 Prompt"""
        return f'''
你是一个数据库业务分析专家。请根据以下数据库描述，生成合理的业务主题分类列表。

## 数据库描述
{description}

## 任务
1. 分析数据库的业务范围
2. 划分合理的业务主题（建议 3-8 个）
3. 每个主题提供名称和描述

## 输出格式（JSON）
```json
{{
  "domains": [
    {{"name": "主题名称", "description": "主题描述"}},
    ...
  ]
}}
```

请只返回 JSON，不要包含其他内容。
'''
    
    def _parse_response(self, response: str) -> List[Dict]:
        """解析 LLM 返回的 JSON"""
        try:
            # 清理可能的 markdown 代码块标记
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            response = response.strip()
            
            data = json.loads(response)
            domains = data.get("domains", [])
            
            if not domains:
                raise ValueError("LLM 返回的 domains 列表为空")
            
            # 校验格式
            for d in domains:
                if "name" not in d:
                    raise ValueError(f"domain 缺少 name 字段: {d}")
            
            return domains
        except json.JSONDecodeError as e:
            logger.error(f"LLM 返回格式错误，无法解析 JSON: {e}")
            logger.error(f"原始返回: {response}")
            raise ValueError(
                "错误：LLM 返回格式错误，无法解析为 JSON，请重试"
            )
    
    # 系统预置的特殊 domain（不可删除）
    UNCLASSIFIED_DOMAIN = "_未分类_"
    
    def write_to_yaml(self, domains: List[Dict]) -> None:
        """将 domains 写入 yaml 文件（保留 _未分类_）"""
        # 1. 确保 _未分类_ domain 存在（系统预置，不可删除）
        unclassified = {
            "name": self.UNCLASSIFIED_DOMAIN, 
            "description": "无法归入其他业务主题的表"
        }
        
        # 2. 过滤掉 LLM 返回中可能包含的 _未分类_（避免重复）
        filtered_domains = [
            d for d in domains 
            if d.get("name") != self.UNCLASSIFIED_DOMAIN
        ]
        
        # 3. 将 _未分类_ 放在列表最前面
        final_domains = [unclassified] + filtered_domains
        
        # 4. 更新 domains 节点
        self.db_config["domains"] = final_domains
        
        with open(self.yaml_path, 'w', encoding='utf-8') as f:
            yaml.dump(
                self.db_config, 
                f, 
                default_flow_style=False, 
                allow_unicode=True,
                sort_keys=False
            )
        
        logger.info(f"domains 已写入 {self.yaml_path}（共 {len(final_domains)} 个，含 _未分类_）")
```

#### 3.3.5 错误处理

| 场景 | 处理方式 | 错误信息 |
|------|----------|----------|
| `db_domains.yaml` 不存在 | ERROR 退出 | "错误：xxx.yaml 文件不存在，请先创建并填写 database.description" |
| `database.description` 为空 | ERROR 退出 | "错误：database.description 为空，无法生成 domains 列表" |
| LLM 返回格式错误 | ERROR 退出 | "错误：LLM 返回格式错误，无法解析为 JSON，请重试" |
| LLM 返回的 domains 为空 | ERROR 退出 | "LLM 返回的 domains 列表为空" |

---

### 3.4 LLM 调用策略（table_category / table_domains）

#### 3.4.1 调用粒度与合并

| 项目 | 说明 |
|------|------|
| **调用粒度** | 每次调用处理**单个表**的 JSON |
| **调用合并** | `table_category` 和 `table_domains` 在**同一次 LLM 调用**中完成 |
| **动态 Prompt** | 根据是否有 `--domain` 参数，动态构建不同的 Prompt |

#### 3.4.2 动态 Prompt 构建

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

如果不属于任何主题，返回 ["_未分类_"]（注意：必须是数组格式）。
'''
    
    # 动态构建输出格式
    if include_domains:
        output_format = '''
## 输出格式（JSON）
{"table_category": "<fact|dim|bridge|unknown>", "table_domains": ["主题1", "主题2"], "reason": "..."}
'''
    else:
        output_format = '''
## 输出格式（JSON）
{"table_category": "<fact|dim|bridge|unknown>", "reason": "..."}
'''
    
    return base_prompt + output_format + "\n请只返回 JSON，不要包含其他内容。"
```

#### 3.4.3 复用 LLMService（支持异步）

**复用方式：** 直接使用现有的 `src/metaweave/services/llm_service.py`

| 方法 | 说明 | 适用场景 |
|------|------|----------|
| `_call_llm(prompt)` | 同步调用 | 调试、少量表 |
| `batch_call_llm_async(prompts)` | 批量异步调用 | 生产环境、大量表（**推荐**） |

**异步配置（复用现有配置）：**

```yaml
# metadata_config.yaml
llm:
  langchain_config:
    use_async: true           # 启用异步调用
    async_concurrency: 20     # 并发数
    batch_size: 50            # 批量大小
```

**调用示例（支持同步/异步）：**

```python
class LLMJsonGenerator:
    def __init__(self, config: Dict, connector: DatabaseConnector):
        # 初始化 LLM 服务（复用现有配置）
        llm_config = config.get("llm", {})
        self.llm_service = LLMService(llm_config)
        
        # 异步配置（复用 rel_llm 的配置方式）
        langchain_config = llm_config.get("langchain_config", {})
        self.use_async = langchain_config.get("use_async", False)
        self.batch_size = max(1, int(langchain_config.get("batch_size", 50) or 50))
    
    def generate_all_from_ddl(self, ddl_dir: Path) -> int:
        """生成所有表的 JSON（支持同步/异步）"""
        ddl_files = list(ddl_dir.glob("*.sql"))
        
        if self.use_async:
            # 批量异步调用 LLM
            return self._generate_all_async(ddl_files)
        else:
            # 同步逻辑
            return self._generate_all_sync(ddl_files)
    
    def _generate_all_sync(self, ddl_files: List[Path]) -> int:
        """同步生成（逐个处理）"""
        success_count = 0
        for ddl_file in ddl_files:
            table_json = self._generate_base_json(ddl_file)
            profile = self._infer_table_profile_sync(table_json)
            self._merge_and_save(table_json, profile)
            success_count += 1
        return success_count
    
    async def _generate_all_async(self, ddl_files: List[Path]) -> int:
        """异步生成（批量并发）"""
        import asyncio
        
        # 1. 先生成所有基础 JSON
        table_jsons = [self._generate_base_json(f) for f in ddl_files]
        
        # 2. 批量构建 Prompts
        prompts = [
            build_prompt(tj, self.include_domains, self.db_config)
            for tj in table_jsons
        ]
        
        # 3. 批量异步调用 LLM（复用 LLMService 的异步能力）
        results = await self.llm_service.batch_call_llm_async(
            prompts,
            on_progress=lambda done, total: logger.info(f"进度: {done}/{total}")
        )
        
        # 4. 解析结果并保存
        success_count = 0
        for idx, (_, response) in enumerate(results):
            if response:
                profile = self._parse_response(response)
                self._merge_and_save(table_jsons[idx], profile)
                success_count += 1
        
        return success_count
    
    def _infer_table_profile_sync(self, table_json: Dict) -> Dict:
        """同步推断表的 category 和 domains"""
        prompt = build_prompt(table_json, self.include_domains, self.db_config)
        response = self.llm_service._call_llm(prompt)
        return self._parse_response(response)
```

**性能对比：**

| 模式 | 100 张表耗时（估算） | 适用场景 |
|------|---------------------|----------|
| 同步 (`use_async: false`) | ~100 × 2s = 200s | 调试、少量表 |
| 异步 (`use_async: true`, 并发20) | ~100 / 20 × 2s = 10s | 生产环境、大量表 |

> **建议：** 生产环境建议启用异步调用（`use_async: true`），可显著提升处理速度。

### 3.5 table_category 类型定义

| 类型 | 说明 | 特征 |
|------|------|------|
| `fact` | 事实类表（含明细事实、汇总事实、快照表、流水表等） | 有度量值、随业务增长、含多维度外键、粒度明确 |
| `dim` | 维度类表（含实体维、枚举维等） | 描述性字段多、较稳定、以ID标识实体、极少有可汇总指标 |
| `bridge` | 桥接表 | 用于多对多关系，通常只包含外键，缺少描述性字段 |
| `unknown` | 无法判断 | 不符合以上任何特征时使用，避免强行猜测 |

### 3.6 输出格式

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
  "table_domains": ["_未分类_"],
  "reason": "该表结构不符合典型特征，无法准确判断"
}
```

### 3.7 流程图

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
| 无参数 | 不分 domain，所有表两两配对（**现有行为**） |
| `--domain` 或 `--domain all` | 逐个 domain 内部寻找关系，**不跨域** |
| `--domain "A,B"` | 只在 A 内部 + B 内部寻找关系，**不跨域** |
| `--domain "A,B" --cross-domain` | A 内部 + B 内部 + **A与B之间的跨域关系** |
| `--domain all --cross-domain` | 所有 domain 内部 + **所有 domain 之间的跨域关系** |
| `--cross-domain`（**单独使用**） | **只生成跨域关系**，跳过域内关系（使用 yaml 中所有 domain） |

> **新增场景说明：** `--cross-domain` 可单独使用，用于在已有域内关系的基础上，只补充跨域关系。适用于分阶段执行：先 `--domain` 生成域内关系，再 `--cross-domain` 补充跨域关系。

**错误处理（使用 `--domain` 或 `--cross-domain` 参数时）：**

| 场景 | 处理方式 | 错误信息 |
|------|----------|----------|
| `db_domains.yaml` 文件不存在 | **ERROR 退出** | `ERROR: {domains_config} 文件不存在，无法使用 --domain/--cross-domain 参数` |
| `db_domains.yaml` 中 `domains` 列表为空 | **ERROR 退出** | `ERROR: {domains_config} 中 domains 列表为空，请先执行 --generate-domains` |
| JSON 文件缺少 `table_profile.table_domains` 属性 | **ERROR 退出** | `ERROR: 表 {table_name} 的 JSON 文件缺少 table_domains 属性，请先执行 --step json_llm --domain` |
| 表不属于任何指定的 domain | 正常处理 | 该表被过滤，不参与关系发现 |

> **重要说明：**
> - 使用 `--domain` 或 `--cross-domain` 参数时，都需要 `db_domains.yaml` 文件存在且 `domains` 列表不为空
> - `--cross-domain` 单独使用时，会隐式使用 yaml 中的**所有** domain，因此同样需要满足上述前置条件
> - 必须确保所有 JSON 文件已通过 `--step json_llm --domain` 生成。如果发现任何表缺少 `table_domains` 属性，程序将立即报错退出，避免关系发现静默失效

**实现位置：** 参数校验逻辑详见 6.3.3 节。

**"_未分类_" domain 说明：**

> 在 `--step json_llm --domain` 阶段，如果 LLM 无法为表分配合适的业务主题，会自动将其归入 `_未分类_` domain。因此，所有表的 `table_domains` 至少包含一个值，不会出现空数组。`_未分类_` 是一个真实的 domain（预置在 `db_domains.yaml` 中），与其他 domain 同等对待。

**命令示例：**

```bash
# ========================================
# 全量扫描（不使用 domain）
# ========================================
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm

# ========================================
# 只生成域内关系
# ========================================
# 按所有 domain 分组处理，不跨域（以下两种写法等价）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain all

# 只处理指定 domain 内部，不跨域
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain "学生基本信息,成绩管理"

# ========================================
# 域内 + 跨域一起生成
# ========================================
# 指定 domain 内部 + 跨域关系
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain "学生基本信息,成绩管理" --cross-domain

# 所有 domain 内部 + 所有跨域关系
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain all --cross-domain

# ========================================
# 只生成跨域关系（分阶段执行）
# ========================================
# 场景：先执行了 --domain，后续只补充跨域关系
# 第一阶段：只生成域内关系
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --domain

# 第二阶段：只补充跨域关系（跳过域内）
python -m src.metaweave.cli.main metadata --config configs/metaweave/metadata_config.yaml --step rel_llm --cross-domain
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

#### 4.3.3 表对组合代码（函数拆分设计）

**函数调用关系：**

```
┌─────────────────────────────────────────────────────────────────┐
│  调度入口（顶层）                                                │
│  get_table_pairs() → 根据参数组合调度                           │
├─────────────────────────────────────────────────────────────────┤
│                              │                                   │
│     ┌────────────────────────┼────────────────────────┐         │
│     │                        │                        │         │
│     ▼                        ▼                        ▼         │
│  generate_all_pairs()  generate_intra_     generate_cross_      │
│  (全量扫描)            domain_pairs()       domain_pairs()      │
│                        (域内关系)           (跨域关系)          │
│                              │                        │         │
│                              └───────────┬────────────┘         │
│                                          │                      │
│                                          ▼                      │
│                              _group_tables_by_domain()          │
│                              (共享：按 domain 分组表)           │
└─────────────────────────────────────────────────────────────────┘
```

**代码实现：**

```python
from itertools import combinations, product
from typing import Dict, List, Tuple, Optional

# 注意：_未分类_ 现在是 db_domains.yaml 中预置的真实 domain
# 不再需要代码中的 UNCLASSIFIED_DOMAIN 常量
# 所有表的 table_domains 至少包含一个值（由 LLM 保证）


# ============================================================
# 底层：共享函数（核心逻辑只写一次）
# ============================================================

def _group_tables_by_domain(
    tables: Dict[str, Dict],
    domain_filter: Optional[List[str]],
    all_domains: List[str]
) -> Dict[str, List[str]]:
    """按 domain 分组表（被 intra 和 cross 复用）
    
    说明：
    - _未分类_ 是 db_domains.yaml 中预置的真实 domain
    - 所有表的 table_domains 至少包含一个值（由 LLM 保证）
    - 不再需要特殊处理空数组的情况
    """
    # 确定目标 domain 列表
    if not domain_filter or "all" in domain_filter:
        target_domains = all_domains.copy()
    else:
        target_domains = domain_filter.copy()
    
    # 分组
    domain_tables = {}
    for full_name, data in tables.items():
        table_domains = data.get("table_profile", {}).get("table_domains", [])
        
        for d in table_domains:
            if d in target_domains:
                domain_tables.setdefault(d, []).append(full_name)
    
    return domain_tables


# ============================================================
# 中层：业务函数（复用底层）
# ============================================================

def generate_all_pairs(tables: Dict[str, Dict]) -> List[Tuple[str, str]]:
    """全量扫描：所有表两两配对
    
    场景：无 --domain 参数时使用
    """
    return list(combinations(tables.keys(), 2))


def generate_intra_domain_pairs(
    tables: Dict[str, Dict],
    domain_filter: Optional[List[str]],
    all_domains: List[str]
) -> List[Tuple[str, str]]:
    """只生成域内关系
    
    场景：--domain 参数时使用
    """
    domain_tables = _group_tables_by_domain(
        tables, domain_filter, all_domains
    )
    
    pairs = []
    for table_list in domain_tables.values():
        pairs.extend(combinations(table_list, 2))
    return pairs


def generate_cross_domain_pairs(
    tables: Dict[str, Dict],
    domain_filter: Optional[List[str]],
    all_domains: List[str],
    intra_pairs: List[Tuple[str, str]] = None
) -> List[Tuple[str, str]]:
    """只生成跨域关系
    
    场景：
    - --domain --cross-domain 时追加使用
    - --cross-domain 单独使用时
    
    Args:
        intra_pairs: 已有的域内表对，用于去重
    """
    domain_tables = _group_tables_by_domain(
        tables, domain_filter, all_domains
    )
    
    processed = set(intra_pairs or [])
    pairs = []
    domain_list = list(domain_tables.keys())
    
    for i, d1 in enumerate(domain_list):
        for d2 in domain_list[i+1:]:
            for t1, t2 in product(domain_tables[d1], domain_tables[d2]):
                # 跳过自关联（当表同时属于多个 domain 时会出现）
                if t1 == t2:
                    continue
                pair = tuple(sorted([t1, t2]))
                if pair not in processed:
                    pairs.append(pair)
                    processed.add(pair)
    
    return pairs


# ============================================================
# 顶层：调度入口（根据参数组合选择）
# ============================================================

def get_table_pairs(
    tables: Dict[str, Dict],
    domain: Optional[str],
    cross_domain: bool,
    all_domains: List[str]
) -> List[Tuple[str, str]]:
    """根据参数组合选择生成策略
    
    参数组合与行为：
    - 无 domain, 无 cross_domain → 全量扫描
    - 有 domain, 无 cross_domain → 只域内
    - 有 domain, 有 cross_domain → 域内 + 跨域
    - 无 domain, 有 cross_domain → 只跨域（使用所有 domain）
    
    说明：
    - _未分类_ 是 db_domains.yaml 中预置的真实 domain，与其他 domain 同等对待
    - 不再需要 include_unclassified 参数
    """
    domain_filter = _parse_domain_filter(domain)
    
    # 1. 无 --domain, 无 --cross-domain → 全量扫描
    if not domain and not cross_domain:
        return generate_all_pairs(tables)
    
    # 2. 有 --domain, 无 --cross-domain → 只域内
    if domain and not cross_domain:
        return generate_intra_domain_pairs(
            tables, domain_filter, all_domains
        )
    
    # 3. 有 --domain, 有 --cross-domain → 域内 + 跨域
    if domain and cross_domain:
        intra_pairs = generate_intra_domain_pairs(
            tables, domain_filter, all_domains
        )
        cross_pairs = generate_cross_domain_pairs(
            tables, domain_filter, all_domains,
            intra_pairs=intra_pairs
        )
        return intra_pairs + cross_pairs
    
    # 4. 无 --domain, 有 --cross-domain → 只跨域（使用所有 domain）
    if not domain and cross_domain:
        return generate_cross_domain_pairs(
            tables, None, all_domains,
            intra_pairs=[]
        )
    
    return []


def _parse_domain_filter(domain: Optional[str]) -> Optional[List[str]]:
    """解析 --domain 参数值"""
    if not domain:
        return None
    if domain.lower() == "all":
        return ["all"]
    return [d.strip() for d in domain.split(",")]
```

**逻辑复用总结：**

| 逻辑 | 写几次 | 复用关系 |
|------|--------|----------|
| 表分组 | **1 次** | `_group_tables_by_domain()` 被 intra 和 cross 复用 |
| 域内配对 | **1 次** | `generate_intra_domain_pairs()` |
| 跨域配对 | **1 次** | `generate_cross_domain_pairs()` |
| 全量配对 | **1 次** | `generate_all_pairs()` |
| 调度逻辑 | **1 次** | `get_table_pairs()` 组合调用 |

### 4.4 与现有 LLMRelationshipDiscovery 的集成

**关键点：** `--domain` 参数只影响"哪些表参与关系发现"，"如何发现关系"的逻辑保持不变。

**代码变更位置：**

```python
# src/metaweave/core/relationships/llm_relationship_discovery.py

class LLMRelationshipDiscovery:
    def __init__(
        self, 
        config: Dict, 
        connector: DatabaseConnector,
        # 新增参数
        domain_filter: Optional[str] = None,
        cross_domain: bool = False,
        db_domains_config: Optional[Dict] = None
    ):
        # ... 现有初始化代码 ...
        
        # 新增：domain 过滤参数
        self.domain_filter = domain_filter           # --domain 参数值
        self.cross_domain = cross_domain             # --cross-domain 参数
        self.db_domains_config = db_domains_config   # db_domains.yaml 加载后的字典
    
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
        all_domains = [d["name"] for d in self.db_domains_config.get("domains", [])]
        
        # 注意：调用 4.3 节定义的 get_table_pairs 函数
        return get_table_pairs(
            tables=tables,
            domain=self.domain_filter,
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
│  │              get_table_pairs() 调度入口                   │   │
│  │                                                          │   │
│  │  判断参数组合，选择生成策略：                            │   │
│  │  ┌─────────────────────────────────────────────────────┐│   │
│  │  │ 无 --domain, 无 --cross-domain                      ││   │
│  │  │   → generate_all_pairs() 全量扫描                   ││   │
│  │  ├─────────────────────────────────────────────────────┤│   │
│  │  │ 有 --domain, 无 --cross-domain                      ││   │
│  │  │   → generate_intra_domain_pairs() 只域内            ││   │
│  │  ├─────────────────────────────────────────────────────┤│   │
│  │  │ 有 --domain, 有 --cross-domain                      ││   │
│  │  │   → generate_intra_domain_pairs()                   ││   │
│  │  │   + generate_cross_domain_pairs() 域内+跨域         ││   │
│  │  ├─────────────────────────────────────────────────────┤│   │
│  │  │ 无 --domain, 有 --cross-domain（单独使用）          ││   │
│  │  │   → generate_cross_domain_pairs() 只跨域            ││   │
│  │  └─────────────────────────────────────────────────────┘│   │
│  └─────────────────────────────────────────────────────────┘   │
│                                    │                            │
│                                    ▼                            │
│                           ┌────────────────┐                   │
│                           │ 获得表对列表    │                   │
│                           └────────────────┘                   │
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

**分阶段执行示例：**

```
┌─────────────────────────────────────────────────────────────────┐
│                      分阶段执行流程                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  【第一阶段】--domain                                           │
│  ────────────────────────────────────────────────               │
│  → generate_intra_domain_pairs()                               │
│  → 输出：域内关系                                              │
│                                                                 │
│                         ↓ (评估效果，决定是否继续)              │
│                                                                 │
│  【第二阶段】--cross-domain（单独）                             │
│  ────────────────────────────────────────────────               │
│  → generate_cross_domain_pairs()                               │
│  → 输出：跨域关系（补充）                                      │
│                                                                 │
│  最终结果 = 域内关系 + 跨域关系                                │
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

### 5.2 reader.py 修改（读取新属性）

**修改位置：** `src/metaweave/core/cql_generator/reader.py`

**修改内容：** 在读取 JSON 时提取新字段

```python
# reader.py

def read_table_node(json_path: Path) -> TableNode:
    """从 JSON 文件读取 TableNode"""
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    table_info = json_data.get("table_info", {})
    table_profile = json_data.get("table_profile", {})
    
    return TableNode(
        # ... 现有字段 ...
        full_name=table_info.get("full_name"),
        schema=table_info.get("schema"),
        name=table_info.get("name"),
        comment=table_info.get("comment"),
        
        # 新增字段（兼容旧 JSON）
        table_domains=table_profile.get("table_domains", []),      # 默认空列表
        table_category=table_profile.get("table_category", None)   # 默认 None
    )


def read_all_table_nodes(json_dir: Path) -> List[TableNode]:
    """读取目录下所有表的 TableNode"""
    nodes = []
    for json_file in json_dir.glob("*.json"):
        try:
            node = read_table_node(json_file)
            nodes.append(node)
        except Exception as e:
            logger.warning(f"读取 {json_file} 失败: {e}")
    return nodes
```

### 5.3 models.py 修改（TableNode 模型变更）

**修改位置：** `src/metaweave/core/cql_generator/models.py`

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class TableNode:
    """表节点数据模型"""
    # 现有属性
    full_name: str
    schema: str
    name: str
    comment: Optional[str] = None
    # ... 其他现有属性 ...
    
    # 新增属性
    table_domains: List[str] = field(default_factory=list)
    table_category: Optional[str] = None
    
    def to_cypher_dict(self) -> Dict[str, Any]:
        """转换为 Cypher 参数字典"""
        return {
            "full_name": self.full_name,
            "schema": self.schema,
            "name": self.name,
            "comment": self.comment,
            # ... 其他现有属性 ...
            
            # 新增属性
            "table_domains": self.table_domains if self.table_domains else [],
            "table_category": self.table_category
        }
```

### 5.4 writer.py 修改（生成 CQL）

**修改位置：** `src/metaweave/core/cql_generator/writer.py`

**修改内容：** 在 CQL 语句中添加新属性的写入

```python
# writer.py

def generate_table_cypher(tables: List[TableNode]) -> Tuple[str, Dict]:
    """生成表节点的 Cypher 语句和参数"""
    
    # 转换为参数列表
    params = [t.to_cypher_dict() for t in tables]
    
    # CQL 语句（包含新属性）
    cypher = """
    UNWIND $tables AS t
    MERGE (n:Table {full_name: t.full_name})
    SET n.id           = t.full_name,
        n.schema       = t.schema,
        n.name         = t.name,
        n.comment      = t.comment,
        // ... 现有属性 ...
        
        // 新增属性（兼容旧 JSON，空值时保留原有值）
        n.table_domains  = CASE 
            WHEN t.table_domains IS NOT NULL AND size(t.table_domains) > 0 
            THEN t.table_domains 
            ELSE COALESCE(n.table_domains, []) 
        END,
        n.table_category = CASE 
            WHEN t.table_category IS NOT NULL 
            THEN t.table_category 
            ELSE n.table_category 
        END
    """
    
    return cypher, {"tables": params}


def write_table_nodes(session, tables: List[TableNode]) -> int:
    """写入表节点到 Neo4j"""
    cypher, params = generate_table_cypher(tables)
    
    result = session.run(cypher, params)
    summary = result.consume()
    
    logger.info(f"写入 {summary.counters.nodes_created} 个新节点，"
                f"更新 {summary.counters.properties_set} 个属性")
    
    return len(tables)
```

### 5.5 CQL 语句说明

**完整 CQL 示例：**

```cypher
UNWIND $tables AS t
MERGE (n:Table {full_name: t.full_name})
SET n.id           = t.full_name,
    n.schema       = t.schema,
    n.name         = t.name,
    n.comment      = t.comment,
    // ... 现有属性 ...
    
    // 新增属性（兼容旧 JSON）
    n.table_domains  = CASE 
        WHEN t.table_domains IS NOT NULL AND size(t.table_domains) > 0 
        THEN t.table_domains 
        ELSE COALESCE(n.table_domains, []) 
    END,
    n.table_category = CASE 
        WHEN t.table_category IS NOT NULL 
        THEN t.table_category 
        ELSE n.table_category 
    END;
```

**CASE 语句说明：**

| 条件 | 行为 |
|------|------|
| `t.table_domains` 有值且非空数组 | 写入新值 |
| `t.table_domains` 为 null 或空数组 | 保留 Neo4j 中原有值，若无则为空数组 |
| `t.table_category` 有值 | 写入新值 |
| `t.table_category` 为 null | 保留 Neo4j 中原有值 |

### 5.6 兼容性处理

| 场景 | JSON 内容 | Neo4j 写入行为 |
|------|-----------|----------------|
| 新 JSON（json_llm 生成） | 有 `table_domains` 和 `table_category` | 正常写入新值 |
| 旧 JSON（无新属性） | 无 `table_domains` 和 `table_category` | 保留 Neo4j 中原有值（若有） |
| 部分新 JSON | 只有 `table_category`，无 `table_domains` | 写入 category，保留 domains 原值 |

> **兼容性说明：** 使用 `CASE WHEN ... ELSE n.xxx END` 确保旧 JSON 文件不会覆盖 Neo4j 中已有的属性值。

---

## 6. 代码变更清单

### 6.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `configs/metaweave/db_domains.yaml` | 业务主题配置模板 |
| `src/metaweave/core/metadata/domain_generator.py` | Domain 列表生成器（实现 `--generate-domains` 功能） |

### 6.2 修改文件

| 文件路径 | 变更说明 |
|----------|----------|
| `src/metaweave/cli/metadata_cli.py` | 新增 `--domain`、`--cross-domain`、`--generate-domains`、`--domains-config` 参数 |
| `src/metaweave/core/metadata/llm_json_generator.py` | 新增 LLM 推断 table_category 和 table_domains 的方法，**更新模块文档字符串** |
| `src/metaweave/core/relationships/llm_relationship_discovery.py` | 支持按 domain 过滤表对，支持 --cross-domain，新增校验逻辑 |
| `src/metaweave/core/cql_generator/reader.py` | 读取 `table_domains` 和 `table_category` |
| `src/metaweave/core/cql_generator/writer.py` | 写入新属性到 CQL |
| `src/metaweave/core/cql_generator/models.py` | TableNode 新增属性 |

> **设计说明：** LLM 推断 `table_category` 和 `table_domains` 的逻辑直接在 `llm_json_generator.py` 中实现，不单独新增模块。理由：
> 1. 当前 `LLMJsonGenerator` 代码量适中，扩展后不会过大
> 2. LLM 推断逻辑与 JSON 生成高度耦合
> 3. 减少模块间依赖，代码更集中

**📝 文档字符串更新（llm_json_generator.py）：**

```python
# 原文档字符串（需删除）：
"""简化版 JSON 数据画像生成器（供 LLM 使用）

不包含推断内容：
- semantic_analysis（语义角色）
- role_specific_info（角色特定信息）
- table_profile 下的推断字段（table_category, confidence, logical_keys 等）
"""

# 更新后的文档字符串：
"""简化版 JSON 数据画像生成器（供 LLM 使用）

包含 LLM 推断内容：
- table_category（LLM 推断，默认启用）
- table_domains（LLM 推断，--domain 参数启用）

不包含规则推断内容：
- semantic_analysis（语义角色，由 --step json 的规则算法生成）
- role_specific_info（角色特定信息）
- logical_keys、confidence 等（由 --step json 的规则算法生成）

说明：
- 本模块通过 LLM 进行推断，与 --step json 的规则算法互为补充
- table_category 判断表的业务类型（dim/fact/bridge/unknown）
- table_domains 判断表所属的业务主题（需配合 --domain 参数和 db_domains.yaml）
"""
```

### 6.3 CLI 参数定义（metadata_cli.py）

**修改位置：** `src/metaweave/cli/metadata_cli.py`

#### 6.3.1 新增参数定义

```python
# ============================================================
# 新增参数（添加到 @click.command() 装饰器链中）
# ============================================================

# --domain 参数（json_llm 和 rel_llm 共用）
@click.option(
    "--domain",
    type=str,
    default=None,
    help="启用 domain 功能。不传值或传 'all' 表示使用所有 domain；传 'A,B' 表示只使用指定 domain"
)

# --domains-config 参数（json_llm 和 rel_llm 共用）
@click.option(
    "--domains-config",
    type=click.Path(exists=False),
    default="configs/metaweave/db_domains.yaml",
    help="业务主题配置文件路径（默认：configs/metaweave/db_domains.yaml）"
)

# --generate-domains 参数（仅 json_llm）
@click.option(
    "--generate-domains",
    is_flag=True,
    default=False,
    help="根据 db_domains.yaml 中的 database.description 自动生成 domains 列表"
)

# --cross-domain 参数（仅 rel_llm）
@click.option(
    "--cross-domain",
    is_flag=True,
    default=False,
    help="是否包含跨域关系。可与 --domain 一起使用，也可单独使用（只生成跨域关系）"
)

# 注意：--include-unclassified 参数已移除
# 原因：_未分类_ 现在是一个真实的 domain（预置在 db_domains.yaml 中）
# LLM 为表分配 domain 时，无法分配的表会自动归入 _未分类_
```

#### 6.3.2 完整命令函数签名

```python
@click.command()
@click.option("--config", "-c", type=click.Path(exists=True), required=True, help="配置文件路径")
@click.option("--step", type=click.Choice(["ddl", "json", "json_llm", "rel", "rel_llm", "cql", "cql_llm"]), help="执行步骤")
# 新增参数
@click.option("--domain", type=str, default=None, help="启用 domain 功能")
@click.option("--domains-config", type=click.Path(), default="configs/metaweave/db_domains.yaml", help="业务主题配置文件路径")
@click.option("--generate-domains", is_flag=True, default=False, help="自动生成 domains 列表")
@click.option("--cross-domain", is_flag=True, default=False, help="包含跨域关系")
def metadata(
    config: str,
    step: str,
    domain: str,
    domains_config: str,
    generate_domains: bool,
    cross_domain: bool
):
    """元数据生成命令"""
    ...
```

#### 6.3.3 参数校验逻辑

```python
def metadata(...):
    """元数据生成命令"""
    
    # ========================================
    # 参数校验
    # ========================================
    
    # 1. --generate-domains 和 --domain 不能同时使用
    if generate_domains and domain:
        raise click.UsageError(
            "--generate-domains 和 --domain 不能同时使用，请分两步执行"
        )
    
    # 2. --cross-domain 可以单独使用（隐含使用所有 domain）
    # 注意：--include-unclassified 参数已移除
    # _未分类_ 现在是 db_domains.yaml 中预置的真实 domain
    
    # 3. 使用 --domain 时校验 db_domains.yaml
    if domain or cross_domain:
        if not Path(domains_config).exists():
            raise click.UsageError(
                f"错误：{domains_config} 文件不存在，无法使用 --domain 参数"
            )
        
        db_config = load_yaml(domains_config)
        domains_list = db_config.get("domains", [])
        
        if not domains_list:
            raise click.UsageError(
                f"错误：{domains_config} 中 domains 列表为空，"
                "请先执行 --generate-domains"
            )
    
    # 4. 使用 --generate-domains 时校验 description
    if generate_domains:
        if not Path(domains_config).exists():
            raise click.UsageError(
                f"错误：{domains_config} 文件不存在，"
                "请先创建并填写 database.description"
            )
        
        db_config = load_yaml(domains_config)
        description = db_config.get("database", {}).get("description", "")
        
        if not description or not description.strip():
            raise click.UsageError(
                "错误：database.description 为空，无法生成 domains 列表"
            )
    
    # ========================================
    # 加载主配置（config 是 CLI 参数，字符串路径）
    # ========================================
    with open(config, 'r', encoding='utf-8') as f:
        main_config = yaml.safe_load(f)
    
    # ========================================
    # 执行逻辑
    # ========================================
    
    if step == "json_llm":
        if generate_domains:
            # 生成 domains 列表
            from src.metaweave.core.metadata.domain_generator import DomainGenerator
            generator = DomainGenerator(main_config, domains_config)
            domains = generator.generate_from_description()
            generator.write_to_yaml(domains)
            click.echo(f"✅ 已生成 {len(domains)} 个 domain 并写入 {domains_config}")
            return
        
        # 正常执行 json_llm
        # 传递 domain 参数给 LLMJsonGenerator
        ...
    
    elif step == "rel_llm":
        # 传递 domain, cross_domain 参数给 LLMRelationshipDiscovery
        ...
```

#### 6.3.4 参数传递链路

**参数流向图：**

```
┌─────────────────────────────────────────────────────────────────┐
│                         参数传递链路                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  命令行参数                                                     │
│  --domain "A,B"                                                 │
│  --domains-config configs/metaweave/db_domains.yaml             │
│  --cross-domain                                                 │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ CLI 层（metadata_cli.py）                                │   │
│  │                                                          │   │
│  │ 1. 读取 db_domains.yaml → db_config                      │   │
│  │ 2. 解析 --domain → include_domains, domain_filter        │   │
│  │ 3. 构建参数字典 → 传递给业务类                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 业务类（LLMJsonGenerator / LLMRelationshipDiscovery）    │   │
│  │                                                          │   │
│  │ 接收参数，执行业务逻辑                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**1. CLI 层读取配置：**

```python
# metadata_cli.py

import yaml
from pathlib import Path


def _load_db_domains_config(domains_config_path: str) -> Dict:
    """读取 db_domains.yaml 配置文件"""
    path = Path(domains_config_path)
    if not path.exists():
        return {}
    
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def metadata(
    config: str,
    step: str,
    domain: str,
    domains_config: str,
    generate_domains: bool,
    cross_domain: bool
):
    # 加载主配置
    with open(config, 'r', encoding='utf-8') as f:
        main_config = yaml.safe_load(f)
    
    # 加载 db_domains.yaml（如果需要）
    db_domains_config = None
    if domain or cross_domain or generate_domains:
        db_domains_config = _load_db_domains_config(domains_config)
    
    # ... 参数校验 ...
    
    # 构建业务类并传递参数
    ...
```

**2. LLMJsonGenerator 签名修改：**

```python
# src/metaweave/core/metadata/llm_json_generator.py

class LLMJsonGenerator:
    """LLM JSON 生成器（修改后的签名）"""
    
    def __init__(
        self,
        config: Dict,
        connector: DatabaseConnector,
        # 新增参数
        include_domains: bool = False,
        domain_filter: Optional[List[str]] = None,
        db_domains_config: Optional[Dict] = None
    ):
        """初始化
        
        Args:
            config: 主配置（metadata_config.yaml）
            connector: 数据库连接器
            include_domains: 是否生成 table_domains（来自 --domain 参数）
            domain_filter: domain 过滤列表（来自 --domain 参数值）
            db_domains_config: db_domains.yaml 的内容
        """
        # 现有初始化
        self.config = config
        self.connector = connector
        self.llm_service = LLMService(config.get("llm", {}))
        
        # 新增：domain 相关参数
        self.include_domains = include_domains
        self.domain_filter = domain_filter
        self.db_domains_config = db_domains_config
        
        # 新增：异步配置（复用现有配置）
        langchain_config = config.get("llm", {}).get("langchain_config", {})
        self.use_async = langchain_config.get("use_async", False)
        self.batch_size = max(1, int(langchain_config.get("batch_size", 50) or 50))
```

**3. LLMRelationshipDiscovery 签名修改：**

```python
# src/metaweave/core/relationships/llm_relationship_discovery.py

class LLMRelationshipDiscovery:
    """LLM 关系发现器（修改后的签名）"""
    
    def __init__(
        self,
        config: Dict,
        connector: DatabaseConnector,
        # 新增参数
        domain_filter: Optional[str] = None,
        cross_domain: bool = False,
        db_domains_config: Optional[Dict] = None
    ):
        """初始化
        
        Args:
            config: 主配置
            connector: 数据库连接器
            domain_filter: domain 过滤（来自 --domain 参数）
            cross_domain: 是否包含跨域关系（来自 --cross-domain）
            db_domains_config: db_domains.yaml 的内容
        
        说明：
            _未分类_ 是 db_domains.yaml 中预置的真实 domain，与其他 domain 同等对待
        """
        # 现有初始化
        self.config = config
        self.connector = connector
        # ... 其他现有初始化 ...
        
        # 新增：domain 相关参数
        self.domain_filter = domain_filter
        self.cross_domain = cross_domain
        self.db_domains_config = db_domains_config
```

**4. CLI 调用业务类（完整示例）：**

```python
# metadata_cli.py

def metadata(...):
    # ... 配置加载和参数校验 ...
    
    # 解析 domain_filter
    domain_filter = None
    if domain:
        if domain.lower() == "all":
            domain_filter = ["all"]
        else:
            domain_filter = [d.strip() for d in domain.split(",")]
    
    # ========================================
    # json_llm 步骤
    # ========================================
    if step == "json_llm":
        if generate_domains:
            # 生成 domains 列表（不执行 json_llm 主流程）
            generator = DomainGenerator(main_config, domains_config)
            domains = generator.generate_from_description()
            generator.write_to_yaml(domains)
            click.echo(f"✅ 已生成 {len(domains)} 个 domain")
            return
        
        # 正常执行 json_llm
        connector = DatabaseConnector(main_config.get("database", {}))
        generator = LLMJsonGenerator(
            config=main_config,
            connector=connector,
            include_domains=bool(domain),           # 是否生成 table_domains
            domain_filter=domain_filter,            # domain 过滤列表
            db_domains_config=db_domains_config     # db_domains.yaml 内容
        )
        generator.generate_all_from_ddl(ddl_dir)
    
    # ========================================
    # rel_llm 步骤
    # ========================================
    elif step == "rel_llm":
        connector = DatabaseConnector(main_config.get("database", {}))
        discovery = LLMRelationshipDiscovery(
            config=main_config,
            connector=connector,
            domain_filter=domain,                   # --domain 参数原值
            cross_domain=cross_domain,              # --cross-domain 标志
            db_domains_config=db_domains_config     # db_domains.yaml 内容
        )
        discovery.discover()
```

**参数传递总结：**

| 来源 | 参数 | 传递给 | 用途 |
|------|------|--------|------|
| `--domain` | `include_domains=True` | LLMJsonGenerator | 是否生成 table_domains |
| `--domain "A,B"` | `domain_filter=["A","B"]` | LLMJsonGenerator / LLMRelationshipDiscovery | 过滤指定 domain |
| `--domains-config` → 读取文件 | `db_domains_config=Dict` | LLMJsonGenerator / LLMRelationshipDiscovery | 数据库描述和 domain 列表 |
| `--cross-domain` | `cross_domain=True` | LLMRelationshipDiscovery | 是否生成跨域关系 |
| `config.llm.langchain_config.use_async` | `self.use_async` | LLMJsonGenerator | 是否使用异步调用 |

> **说明：** `--include-unclassified` 参数已移除。`_未分类_` 现在是 `db_domains.yaml` 中预置的真实 domain，与其他 domain 同等对待。

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

**重要说明：**
- 如果该表明确属于某个业务主题，请选择对应的主题
- 如果该表无法归入任何其他业务主题，**必须**选择 "_未分类_"
- **不要**返回空数组，每个表至少属于一个主题（包括 "_未分类_"）

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

> **注意：** 此模板与 3.3.4 节 `DomainGenerator._build_prompt()` 保持一致，使用 **JSON 格式**（更容易解析）。

```
你是一个数据库业务分析专家。请根据以下数据库描述，生成合理的业务主题分类列表。

## 数据库描述
{database_description}

## 任务
1. 分析数据库的业务范围
2. 划分合理的业务主题（建议 3-8 个）
3. 每个主题提供名称和描述

## 注意事项
- **不要**生成名为 "_未分类_" 的主题（这是系统预置的特殊主题，会自动添加）
- 只生成有明确业务含义的主题

## 输出格式（JSON）
```json
{
  "domains": [
    {"name": "主题名称", "description": "主题描述"},
    ...
  ]
}
```

请只返回 JSON，不要包含其他内容。
```

---

## 10. 参考资料

- 原始需求：`docs/gen_rag/53_增加domain和type的需求.txt`
- 现有配置：`configs/metaweave/metadata_config.yaml`
- json_llm 实现：`src/metaweave/core/metadata/llm_json_generator.py`
- rel_llm 实现：`src/metaweave/core/relationships/llm_relationship_discovery.py`
- CQL 生成器：`src/metaweave/core/cql_generator/`
- LLM 服务：`src/metaweave/services/llm_service.py`
