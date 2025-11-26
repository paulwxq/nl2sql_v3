# 配置结构重构总结

## 问题背景

在 Step 3 关系发现模块的实现中，存在**配置结构不一致**的问题：

- **文档模板**（`metadata_config.step3.yaml.template`）使用 **top-level 配置结构**
- **原实现代码** 期望从 `relationships` 子树读取配置
- **原配置文件**（`metadata_config.yaml`）使用了 `relationships` 包裹

这导致文档与代码不一致，增加了用户配置的复杂度。

## 修复方案

采用**方案A**：调整代码以匹配文档模板（推荐方案）

### 核心变更

#### 1. Pipeline 配置读取（`pipeline.py`）

**修改前**：
```python
# 从 relationships 子树读取配置
self.rel_config = self.config.get("relationships", {})

# 从 output.output_dir 推导 json_dir
output_config = self.config.get("output", {})
output_dir = output_config.get("output_dir", "output/metaweave/metadata")
self.json_dir = get_project_root() / output_dir / "json"

# 传递 rel_config 给各模块
self.scorer = RelationshipScorer(self.rel_config, self.connector)
self.decision_engine = DecisionEngine(self.rel_config)
self.writer = RelationshipWriter(self.rel_config)
```

**修改后**：
```python
# 支持直接配置 json_directory，或从 output_dir 推导（fallback）
output_config = self.config.get("output", {})
json_directory = output_config.get("json_directory")
if json_directory:
    self.json_dir = get_project_root() / json_directory
else:
    # Fallback: 从 output_dir 推导
    output_dir = output_config.get("output_dir", "output/metaweave/metadata")
    self.json_dir = get_project_root() / output_dir / "json"

# 传递 top-level config 给各模块
self.scorer = RelationshipScorer(self.config, self.connector)
self.decision_engine = DecisionEngine(self.config)
self.writer = RelationshipWriter(self.config)
```

#### 2. 配置文件结构（`metadata_config.yaml`）

**修改前**（嵌套结构）：
```yaml
relationships:
  output:
    rel_directory: "output/metaweave/metadata/rel"
    rel_granularity: "global"
    rel_id_salt: ""
  single_column:
    ...
  composite:
    ...
  decision:
    ...
  weights:
    ...
```

**修改后**（扁平结构，与文档模板一致）：
```yaml
output:
  output_dir: output/metaweave/metadata
  # Step 3 配置
  json_directory: output/metaweave/metadata/json
  rel_directory: output/metaweave/metadata/rel
  rel_granularity: global
  rel_id_salt: ""
  # Step 2 配置
  formats: [ddl, markdown, json]
  ...

single_column:
  active_search_same_name: true
  ...

composite:
  max_columns: 3
  ...

decision:
  accept_threshold: 0.80
  ...

weights:
  inclusion_rate: 0.30
  ...
```

## 修复效果

### ✅ 优势

1. **与文档模板一致**：用户可直接参考 `metadata_config.step3.yaml.template`
2. **配置结构更扁平**：减少嵌套层级，更符合 YAML 最佳实践
3. **output 节点统一**：Step 2 和 Step 3 配置合并，避免重复
4. **向后兼容**：支持 `json_directory` 直接配置 + `output_dir` fallback

### ✅ 测试验证

- 所有 29 个单元测试通过
- 配置读取逻辑正确
- 各模块正常工作

## 配置说明

### output 节点（合并 Step 2 和 Step 3）

| 配置项 | 用途 | 默认值 |
|--------|------|--------|
| `output_dir` | Step 2 输出根目录 | `output/metaweave/metadata` |
| `json_directory` | Step 3 输入（JSON元数据） | fallback: `output_dir/json` |
| `rel_directory` | Step 3 输出（关系发现） | `output/metaweave/metadata/rel` |
| `rel_granularity` | 输出粒度 | `global` (Phase 1 仅支持 global) |
| `rel_id_salt` | 关系ID哈希盐值 | `""` (空字符串) |

### 其他 Step 3 配置节点

- `single_column`：单列候选生成配置
- `composite`：复合键候选生成配置
- `decision`：决策和抑制规则配置
- `weights`：6 维度评分权重配置

## 迁移指南

如果之前使用了 `relationships` 包裹的配置，需要：

1. 移除 `relationships:` 顶层节点
2. 将 `relationships.output` 合并到顶层 `output` 节点
3. 将其他配置（`single_column`、`composite` 等）提升到 top-level

**迁移示例**：

```yaml
# 旧配置 ❌
relationships:
  output:
    rel_directory: "xxx"
  single_column:
    ...

# 新配置 ✅
output:
  rel_directory: "xxx"
single_column:
  ...
```

## 相关文件

- 修改的代码文件：
  - `src/metaweave/core/relationships/pipeline.py`

- 修改的配置文件：
  - `configs/metaweave/metadata_config.yaml`

- 参考文档：
  - `docs/gen_rag/metadata_config.step3.yaml.template`

## 版本信息

- 修复时间：2025-11-26
- 影响模块：Step 3 关系发现
- 测试覆盖：29/29 单元测试通过
