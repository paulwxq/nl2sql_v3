# NL2SQL CLI 快速开始

## 简介

NL2SQL CLI 是一个命令行对话工具，可以将自然语言问题自动转换为 SQL 语句。

## 快速开始

### 1. 单次查询

```bash
python scripts/nl2sql_subgraph_cli.py "请对比一下9月份京东便利和全家这两个公司的销售金额"
```

**输入包装**（自动完成）：
```python
{
    "query": "请对比一下9月份京东便利和全家这两个公司的销售金额",
    "query_id": "q_20251102_143052_a1b2c3d4",
    "dependencies_results": {},
    "user_query": "请对比一下9月份京东便利和全家这两个公司的销售金额"
}
```

**输出示例**：
```
================================================================================
查询ID: q_20251102_143052_a1b2c3d4
================================================================================

✅ SQL生成成功!

生成的SQL:
--------------------------------------------------------------------------------
SELECT 
    ds.store_name,
    SUM(fs.amount) as total_amount
FROM public.fact_sales fs
JOIN public.dim_store ds ON fs.store_id = ds.id
WHERE 
    fs.order_date >= '2024-09-01' 
    AND fs.order_date < '2024-10-01'
    AND ds.store_name IN ('京东便利', '全家')
GROUP BY ds.store_name
ORDER BY total_amount DESC
--------------------------------------------------------------------------------

📊 统计信息:
  - 迭代次数: 1
  - 执行耗时: 3.45秒

================================================================================
```

### 2. 交互模式

```bash
python scripts/nl2sql_subgraph_cli.py
```

进入交互模式后可以连续输入问题：

```
💬 请输入问题: 查询2024年10月的订单总数
🔄 正在生成SQL...
✅ SQL生成成功!
...

💬 请输入问题: 销售额最高的前10个门店
🔄 正在生成SQL...
✅ SQL生成成功!
...

💬 请输入问题: exit
👋 再见!
```

## 工作流程

```
用户输入问题
    ↓
[自动包装输入格式]
    ↓
调用 SQL 生成子图
    ↓
  解析问题
    ↓
  Schema 检索
    ↓
  SQL 生成
    ↓
  三层验证
    ↓
[命令行输出SQL]
```

## 日志记录

所有关键步骤都会记录到日志文件：

**日志文件位置**：`logs/sql_subgraph.log`

**日志内容**：
```
2025-11-02 14:30:52 - nl2sql_subgraph_cli - INFO - [q_xxx] 输入问题: 请对比一下9月份...
2025-11-02 14:30:52 - nl2sql_subgraph_cli - INFO - [q_xxx] 开始执行NL2SQL转换
2025-11-02 14:30:55 - nl2sql_subgraph_cli - INFO - [q_xxx] 子图执行完成，总耗时 3.45秒
2025-11-02 14:30:55 - nl2sql_subgraph_cli - INFO - [q_xxx] SQL生成成功，耗时 3.45秒
2025-11-02 14:30:55 - nl2sql_subgraph_cli - INFO - [q_xxx] 生成的SQL: SELECT ...
```

## 功能特点

✅ **自动包装输入**：无需手动构造复杂的输入格式
✅ **唯一查询ID**：每个查询自动生成时间戳+UUID的ID
✅ **友好输出**：清晰的成功/失败提示和SQL格式化显示
✅ **详细日志**：关键步骤全部记录，便于调试和追踪
✅ **性能统计**：显示迭代次数和执行耗时
✅ **错误追踪**：失败时显示详细的验证历史和错误信息

## 示例问题

```bash
# 时间范围查询
python scripts/nl2sql_subgraph_cli.py "查询2024年10月的订单总金额"

# 对比查询
python scripts/nl2sql_subgraph_cli.py "对比京东便利和全家9月份的销售额"

# TOP-N查询
python scripts/nl2sql_subgraph_cli.py "销售额最高的前10个门店"

# 维度查询
python scripts/nl2sql_subgraph_cli.py "列出所有门店名称"

# 聚合查询
python scripts/nl2sql_subgraph_cli.py "计算9月份的平均订单金额"

# 同比环比
python scripts/nl2sql_subgraph_cli.py "对比今年和去年9月的销售额"
```

## 运行示例脚本

### Windows
```bash
scripts\example_usage.bat
```

### Linux/Mac
```bash
chmod +x scripts/example_usage.sh
./scripts/example_usage.sh
```

## 故障排查

### 问题1：模块导入错误
```
ImportError: No module named 'src'
```

**解决方法**：确保在项目根目录运行
```bash
cd C:\Projects\cursor_2025h2\nl2sql_v3
python scripts/nl2sql_subgraph_cli.py "你的问题"
```

### 问题2：数据库连接失败
```
❌ SQL生成失败!
错误信息: 数据库连接失败
```

**解决方法**：
1. 检查 `.env` 文件中的数据库配置
2. 确保 PostgreSQL 和 Neo4j 正常运行
3. 验证网络连接

### 问题3：API密钥错误
```
❌ SQL生成失败!
错误信息: API调用失败
```

**解决方法**：
1. 检查 `DASHSCOPE_API_KEY` 环境变量
2. 确保密钥有效且有足够额度

## 配置说明

工具使用以下配置文件：
- `src/modules/sql_generation/config/sql_generation_subgraph.yaml`
- `.env` 环境变量文件

关键配置项：
```yaml
# Parser 配置
question_parsing:
  enable_internal_parser: true    # 启用问题解析
  fallback_to_empty: true         # 解析失败时回退

# 验证配置
validation:
  enable_semantic_check: true     # 启用数据库验证
  
# 重试配置
retry:
  max_iterations: 3               # 最多重试3次
```

## 高级用法

### 批量查询

创建问题文件 `questions.txt`：
```
查询2024年10月的订单总数
对比京东便利和全家的销售额
销售额最高的前10个门店
```

批量执行（Windows PowerShell）：
```powershell
Get-Content questions.txt | ForEach-Object {
    python scripts/nl2sql_subgraph_cli.py $_
}
```

### 实时查看日志

```bash
# Windows
Get-Content logs/sql_subgraph.log -Wait -Tail 50

# Linux/Mac
tail -f logs/sql_subgraph.log
```

## 技术架构

```
nl2sql_subgraph_cli.py
    ↓
format_input()          # 包装输入格式
    ↓
run_sql_generation_subgraph()
    ↓
    ├─ question_parsing_node    # 问题解析
    ├─ schema_retrieval_node    # Schema检索
    ├─ sql_generation_node      # SQL生成
    └─ validation_node          # 三层验证
    ↓
print_result()          # 格式化输出
    ↓
logger                  # 记录日志
```

## 相关文档

- [SQL生成子图设计文档](sql_generation_subgraph_design.md)
- [改造实施计划](sql_subgraph_modification_detailed_plan.md)
- [Scripts 使用说明](../scripts/README.md)

