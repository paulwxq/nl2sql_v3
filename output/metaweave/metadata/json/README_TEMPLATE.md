# 表元数据 JSON 格式说明

## 版本信息
- **当前版本**: 2.0
- **更新日期**: 2025-11-22

## 模板文件说明

本目录提供了三个模板文件，适用于不同场景：

### 1. `_template.json`
**完整模板文件**
- 包含所有可能的字段和示例值
- 适合作为开发参考和字段查询
- 展示了各种数据类型的示例

### 2. `_template_with_comments.jsonc`
**带详细注释的模板文件**
- JSONC 格式（支持注释）
- 每个字段都有详细的中文说明
- 适合学习和理解字段含义
- 包含使用建议和最佳实践

### 3. `_template_minimal.json`
**精简模板文件**
- 只包含必填字段
- 可选字段设为 null 或空值
- 适合快速创建新的元数据文件
- 可以作为生成代码的基础模板

## JSON 格式结构

### 顶层结构
```
{
  "metadata_version": "2.0",           # 元数据格式版本
  "generated_at": "...",               # 生成时间
  "table_info": {...},                 # 表基本信息
  "column_profiles": {...},            # 列画像
  "table_profile": {...},              # 表画像
  "sample_records": {...}              # 样例数据
}
```

### 核心设计思想

#### 1. table_info - 表基本信息
- **目的**: 集中管理表的元数据和约束信息
- **新增**: `column_count` 字段，方便快速获取列数
- **整合**: 将 `constraints` 作为子对象，包含主键、外键、唯一约束、索引

#### 2. column_profiles - 列画像
- **结构化**: 将相关字段分组
  - `statistics`: 统计信息
  - `semantic_analysis`: 语义分析结果
  - `structure_flags`: 结构标志位
  - `role_specific_info`: 角色特定信息
- **灵活性**: `role_specific_info` 根据列的语义角色动态包含不同子对象

#### 3. table_profile - 表画像
- **智能分析**: 表级别的自动推断结果
- **分类信息**: 区分事实表、维度表、桥接表的特定信息
- **候选键**: 自动推断的逻辑主键

#### 4. sample_records - 样例数据
- **元信息完整**: 包含采样方法、时间等上下文信息
- **类型保真**: 数据保持原始类型（数值、字符串等）
- **易于使用**: 直接可用的记录数组

## 字段说明

### 语义角色 (semantic_role)
| 角色 | 说明 | 示例 |
|------|------|------|
| identifier | 标识符 | ID、主键、唯一键 |
| metric | 度量值 | 销售额、数量、金额 |
| datetime | 时间字段 | 创建时间、日期 |
| enum | 枚举类型 | 状态、类型、类别 |
| attribute | 属性字段 | 名称、描述、地址 |
| audit | 审计字段 | 创建人、更新时间 |

### 表分类 (table_category)
| 分类 | 说明 | 特征 |
|------|------|------|
| dimension | 维度表 | 有主键、无度量、描述性属性 |
| fact | 事实表 | 有粒度列、有度量列、多外键 |
| bridge | 桥接表 | 多对多关系、双向外键 |
| unknown | 未知 | 无法明确分类 |

### 置信度说明
- **1.0**: 确定（基于物理约束）
- **0.8-0.9**: 高置信度（多个证据支持）
- **0.6-0.7**: 中等置信度（部分证据）
- **0.5**: 低置信度（猜测或回退）

## 使用场景

### 场景 1: 数据目录
- 作为数据目录系统的元数据存储格式
- 支持搜索、浏览、血缘分析

### 场景 2: RAG 增强
- 为 NL2SQL 提供丰富的上下文信息
- 包含统计分布和样例数据辅助理解

### 场景 3: 数据质量监控
- 基于统计信息进行数据质量检查
- 监控数据分布变化

### 场景 4: 自动化文档生成
- 自动生成数据字典
- 生成表关系图和 ER 图

## 重新生成 JSON 文件

如果你修改了模板或代码，需要重新生成 JSON 文件，请运行：

```bash
# 生成 JSON 格式的元数据（从 DDL）
python -m src.metaweave.cli.metadata_cli generate --config configs/metaweave/metadata_config.yaml --step json

# 或使用脚本
python scripts/metaweave/run_metadata_generation.py --step json
```

这将：
1. 从 `output/metaweave/metadata/ddl/*.sql` 读取 DDL 文件
2. 解析表结构和注释
3. 连接数据库采样计算统计信息
4. 从 DDL 的 `SAMPLE_RECORDS` 注释块提取样例数据
5. 生成符合 v2.0 模板格式的 JSON 文件到 `output/metaweave/metadata/json/`

## 版本变更记录

### v2.0 (2025-11-22)
- ✨ 新增: 样例数据 (`sample_records`)
- ✨ 新增: `table_info.total_columns` 字段（原 `column_count`）
- ✨ 新增: `table_info.total_rows` 字段（原 `row_count`）
- 🔄 变更: 将 `table_constraints` 整合到 `table_info.constraints`
- 🔄 优化: 列画像字段分组（`semantic_analysis`, `role_specific_info`）
- 🔄 优化: `candidate_logical_primary_keys` 移到 `table_profile` 内
- 📝 改进: 样例数据保持原始类型
- 🔧 代码: 修改 `TableMetadata.to_dict()` 和 `ColumnProfile.to_dict()` 输出格式
- 🔧 代码: 添加从 DDL 提取样例数据的功能
- 🔧 字段: 重命名 `row_count` → `total_rows`, `column_count` → `total_columns`

### v1.0
- 初始版本
- 基本的表和列元数据

## 最佳实践

1. **必填字段**: 至少填充 `table_info` 和基本的 `column_profiles`
2. **统计信息**: 定期更新统计信息以保持准确性
3. **样例数据**: 建议包含 5-10 条代表性样例
4. **注释信息**: 优先从 DDL 获取，其次是数据库注释
5. **语义推断**: 结合多个证据提高置信度

## 工具支持

可以使用以下工具处理这些 JSON 文件：
- `jq`: 命令行 JSON 处理工具
- Python `json` 模块: 编程处理
- 任何支持 JSON Schema 验证的工具

## 相关文件

- 源数据: `output/metaweave/metadata/ddl/*.sql`
- Markdown 文档: `output/metaweave/metadata/markdown/*.md`

---

**维护者**: NL2SQL v3 Team  
**联系方式**: 见项目主 README

