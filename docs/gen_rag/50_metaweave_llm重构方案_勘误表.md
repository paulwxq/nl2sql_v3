# MetaWeave LLM 重构方案 - 勘误表

## 文档版本
- **原版本**: v1.1
- **勘误版本**: v1.2
- **勘误日期**: 2025-12-05

---

## 勘误 #1: `.env.example` 中 DASHSCOPE_MODEL 状态错误

### 📍 影响文档
- `50_metaweave_llm重构方案.md`
  - 第一章：改造背景
  - 2.1 节：现有配置结构
  - Step 1：更新 .env.example 文件

### ❌ 错误描述
文档声称 `.env.example` 当前包含 `DASHSCOPE_MODEL` 并需要删除。

### ✅ 实际情况
经检查 `.env.example` 文件，**该变量已不存在**。

```bash
# 验证命令
$ grep "DASHSCOPE_MODEL" .env.example
# (无输出，证明不存在)
```

### 🔧 修正内容

#### 修正前
```markdown
#### .env 文件（当前）
```bash
DASHSCOPE_MODEL=            # ❌ 问题1：模型名不应在环境变量中
```

**改造背景第1点**：
> 环境变量职责不清：模型名称 `DASHSCOPE_MODEL` 配置在 `.env` 中...

**Step 1**：
- [ ] 删除 `DASHSCOPE_MODEL` 配置项
```

#### 修正后
```markdown
#### .env 文件（当前）
```bash
# (已无 DASHSCOPE_MODEL)
```

**说明**：`.env.example` 模板文件中已经没有 `DASHSCOPE_MODEL`，但如果您的个人 `.env` 文件中还有该配置项，建议删除。

**改造背景第1点**：
> 环境变量职责不清：历史版本中模型名称曾配置在 `.env` 的 `DASHSCOPE_MODEL` 中，现已移除模板但部分用户的 `.env` 可能仍有残留

**Step 1**：
- [ ] ✅ `.env.example` 已无 `DASHSCOPE_MODEL`（无需操作）
- [ ] **⚠️ 提醒用户**：如个人 `.env` 文件中还有 `DASHSCOPE_MODEL`，建议删除
```

### 💡 最佳实践
如果您的个人 `.env` 文件中确实还有 `DASHSCOPE_MODEL`：

1. **检查**：
   ```bash
   grep "DASHSCOPE_MODEL" .env
   ```

2. **删除**（如存在）：
   ```bash
   # 手动编辑 .env 文件，删除该行
   # DASHSCOPE_MODEL=qwen-plus  ← 删除这一行
   ```

3. **迁移到 YAML**：
   ```yaml
   # configs/metaweave/metadata_config.yaml
   llm:
     providers:
       qwen:
         model: qwen-plus  # 在这里配置
   ```

---

## 勘误 #2: CLI 命令格式错误

### 📍 影响文档
- `50_metaweave_llm重构方案_实施清单.md`
  - 测试 1：注释生成功能
  - 测试 2：LLM 关系发现功能

### ❌ 错误描述
文档中的测试命令有两处错误：

1. **错误的模块路径**：`python -m src.metaweave.cli.metadata_cli`
2. **错误的选项名**：`--table`（单数）

### ✅ 实际情况

#### 正确的 CLI 结构
```python
# src/metaweave/cli/main.py
@click.group()
def cli():
    """MetaWeave CLI 主入口"""
    pass

# 注册子命令
cli.add_command(metadata_command)  # 子命令名: metadata
```

#### 正确的选项名
```python
# src/metaweave/cli/metadata_cli.py
@click.option(
    "--tables",     # ← 复数
    "-t",
    type=str,
    help="要处理的表名列表（逗号分隔）"
)
```

### 🔧 修正内容

#### 修正前
```bash
# ❌ 错误命令
python -m src.metaweave.cli.metadata_cli \
    --config configs/metaweave/metadata_config.yaml \
    --step json_llm \
    --table public.dim_product
```

**问题**：
1. `metadata_cli` 不是可执行模块（没有 `if __name__ == "__main__"`）
2. `--table` 会报错：`Error: no such option: --table`

#### 修正后
```bash
# ✅ 正确命令
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step json_llm \
    --tables public.dim_product
```

**说明**：
- ✅ 使用 `main` 作为入口模块
- ✅ `metadata` 是子命令
- ✅ `--tables`（复数）是正确选项

### 💡 CLI 使用指南

#### 查看帮助
```bash
# 主帮助
python -m src.metaweave.cli.main --help

# metadata 子命令帮助
python -m src.metaweave.cli.main metadata --help
```

#### 常用命令示例

```bash
# 1. 生成单表的 JSON+LLM 注释
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step json_llm \
    --tables public.dim_product

# 2. 生成多表（逗号分隔）
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step json_llm \
    --tables public.dim_product,public.dim_store

# 3. 处理指定 schema 的所有表
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step json_llm \
    --schemas public

# 4. 运行 LLM 关系发现
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step rel_llm

# 5. 启用调试模式
python -m src.metaweave.cli.main --debug metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step json_llm \
    --tables public.dim_product
```

#### 选项说明
| 选项 | 简写 | 类型 | 说明 |
|------|------|------|------|
| `--config` | `-c` | 路径 | 配置文件路径（必需） |
| `--step` | - | 枚举 | 执行步骤：`json`, `json_llm`, `rel`, `rel_llm`, `cql`, `cql_llm` |
| `--schemas` | `-s` | 字符串 | schema 列表（逗号分隔） |
| `--tables` | `-t` | 字符串 | 表名列表（逗号分隔） |
| `--incremental` | `-i` | 标志 | 增量更新模式 |
| `--debug` | - | 标志 | 启用调试模式（主命令选项） |

---

## 勘误 #3: 测试步骤选择错误

### 📍 影响文档
- `50_metaweave_llm重构方案_实施清单.md`
  - 测试 1：注释生成功能

### ❌ 错误描述
文档声称使用 `--step json_llm` 可以测试 `MetadataGenerator → CommentGenerator → LLMService` 路径。

### ✅ 实际情况

#### `json_llm` 步骤的实际行为
```python
# src/metaweave/cli/metadata_cli.py:83-123
if step == "json_llm":
    generator = LLMJsonGenerator(config, connector)
    count = generator.generate_all_from_ddl(ddl_dir)
```

- ❌ **不实例化** `MetadataGenerator`
- ❌ **不实例化** `CommentGenerator`  
- ❌ **不调用** `LLMService`（仅从 DDL 读取）
- ❌ **忽略** `--tables` 参数（处理所有 DDL 文件）

#### 真正触发注释生成的步骤

```python
# src/metaweave/core/metadata/generator.py:310-344
if self.active_step == "json":
    self._process_table_from_ddl(...)  # ← 不调用 CommentGenerator
else:
    self._process_table_from_db(...)   # ← 这里才调用 CommentGenerator (line 344)
```

**结论**：
- ❌ `--step json`：从 DDL 读取，**不调用** `CommentGenerator`
- ❌ `--step json_llm`：使用独立的 `LLMJsonGenerator`，**不经过** `MetadataGenerator`
- ✅ `--step ddl`：从数据库提取，**调用** `CommentGenerator` ✅
- ✅ `--step all`：完整流程，**调用** `CommentGenerator` ✅
- ✅ `--step md`：生成 Markdown，**调用** `CommentGenerator` ✅

### 🔧 修正内容

#### 修正前
```bash
# ❌ 错误：这个命令不会触发 CommentGenerator
python -m src.metaweave.cli.main metadata \
    --step json_llm \
    --tables public.dim_product
```

#### 修正后
```bash
# ✅ 方法 1：使用 ddl 步骤（推荐）
python -m src.metaweave.cli.main metadata \
    --step ddl \
    --tables public.dim_product

# ✅ 方法 2：使用 all 步骤
python -m src.metaweave.cli.main metadata \
    --step all \
    --tables public.dim_product

# ✅ 方法 3：使用 md 步骤
python -m src.metaweave.cli.main metadata \
    --step md \
    --tables public.dim_product
```

### 💡 步骤选择指南

| 步骤 | 用途 | 是否调用 CommentGenerator | 性能 |
|------|------|---------------------------|------|
| `ddl` | 生成 DDL 文件 | ✅ 是 | 快 |
| `json` | 从 DDL 生成 JSON | ❌ 否 | 快 |
| `json_llm` | 简化版 JSON（LLM 格式） | ❌ 否 | 快 |
| `md` | 生成 Markdown | ✅ 是 | 中 |
| `cql` | 生成 Cypher（从 json） | ❌ 否 | 快 |
| `cql_llm` | 生成 Cypher（从 json_llm） | ❌ 否 | 快 |
| `rel` | 关系发现（非 LLM） | ❌ 否 | 慢 |
| `rel_llm` | LLM 辅助关系发现 | ❌ 否 | 慢 |
| `all` | 完整流程 | ✅ 是 | 最慢 |

**测试建议**：
- 🎯 **测试 LLM 注释生成**：使用 `--step ddl`（最快）
- 🎯 **完整功能验证**：使用 `--step all`
- ❌ **避免使用 `json_llm`**：它不会触发注释生成

### 🔍 验证方法

运行命令后检查日志：

```bash
# 成功触发注释生成的日志标志
✅ "LLM 服务已初始化: qwen (qwen-plus)"
✅ "生成表注释成功: public.dim_product"
✅ "生成字段注释成功: public.dim_product, 5 个字段"
```

如果看不到以上日志，说明步骤选择错误。

---

## 修正汇总

### 已修正文件
1. ✅ `docs/gen_rag/50_metaweave_llm重构方案.md` (v1.2)
   - 修正 `.env.example` 状态描述
   - 更新改造背景说明
   - 更新 Step 1 清单

2. ✅ `docs/gen_rag/50_metaweave_llm重构方案_实施清单.md` (v1.3)
   - 修正文件 1 的操作说明
   - 修正测试 1 的命令格式（CLI 入口和选项）
   - 修正测试 1 的步骤选择（`json_llm` → `ddl`/`all`/`md`）
   - 修正测试 2 的命令格式
   - 添加 CLI 使用说明
   - 添加步骤选择指南

### 验证清单
- [x] 确认 `.env.example` 不包含 `DASHSCOPE_MODEL`
- [x] 确认 CLI 入口是 `src.metaweave.cli.main`
- [x] 确认选项是 `--tables`（复数）
- [x] 确认 `--step json_llm` 不调用 `CommentGenerator`
- [x] 确认 `--step ddl` 调用 `CommentGenerator`
- [x] 测试命令格式和步骤选择正确性

---

## 相关问题预防

### Q1: 如何判断使用哪个 CLI 入口？
**A**: 检查文件是否有 `if __name__ == "__main__":`：
```bash
# 检查方法
grep -n "if __name__" src/metaweave/cli/*.py

# 结果
main.py:57:if __name__ == "__main__":
# ↑ 只有 main.py 有，所以它是入口
```

### Q2: 如何查看所有可用选项？
**A**: 使用 `--help`：
```bash
python -m src.metaweave.cli.main metadata --help
```

### Q3: 为什么是 `--tables` 复数？
**A**: 因为支持多表批量处理：
```bash
# 单表
--tables public.dim_product

# 多表
--tables public.dim_product,public.dim_store,public.fact_sales
```

---

## 版本历史

| 版本 | 日期 | 修正内容 | 影响等级 |
|------|------|---------|---------|
| v1.0 | 2025-12-05 | 初始版本 | - |
| v1.1 | 2025-12-05 | 修正环境变量命名、name 字段冗余等 4 个问题 | 🔴 高 |
| v1.2 | 2025-12-05 | 修正 `.env.example` 状态描述和 CLI 命令格式 | 🔴 高 |
| v1.3 | 2025-12-05 | 修正测试步骤选择错误（`json_llm` 不调用 `CommentGenerator`） | 🔴 高 |

---

**勘误负责人**: AI Assistant  
**审核状态**: 已验证  
**累计勘误数**: 3 个关键问题  
**影响等级**: 🔴 高（测试步骤错误会导致测试失败，无法验证改造效果）

