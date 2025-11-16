# Scripts 使用说明

## nl2sql_subgraph_cli.py - NL2SQL 命令行对话工具

### 功能
将自然语言问题转换为 SQL 语句的命令行工具。

### 使用方法

#### 1. 单次查询模式
直接在命令行传入问题：

```bash
# 基本用法
python scripts/nl2sql_subgraph_cli.py "请对比一下9月份京东便利和全家这两个公司的销售金额"

# Windows (PowerShell)
python scripts/nl2sql_subgraph_cli.py "查询2024年10月的订单总数"

# Linux/Mac
python scripts/nl2sql_subgraph_cli.py "查询销售额最高的前10个门店"
```

#### 2. 交互模式
不传参数直接运行，进入交互模式：

```bash
python scripts/nl2sql_subgraph_cli.py
```

进入交互模式后，可以持续输入问题：

```
NL2SQL 命令行对话工具 (交互模式)
================================================================================

输入自然语言问题，系统将自动生成SQL
输入 'exit' 或 'quit' 退出

💬 请输入问题: 请对比一下9月份京东便利和全家这两个公司的销售金额

🔄 正在生成SQL...

================================================================================
查询ID: q_20251102_143052_a1b2c3d4
================================================================================

✅ SQL生成成功!

生成的SQL:
--------------------------------------------------------------------------------
SELECT 
    store_name,
    SUM(amount) as total_amount
FROM public.fact_sales fs
JOIN public.dim_store ds ON fs.store_id = ds.id
WHERE 
    fs.order_date >= '2024-09-01' 
    AND fs.order_date < '2024-10-01'
    AND ds.store_name IN ('京东便利', '全家')
GROUP BY store_name
--------------------------------------------------------------------------------

📊 统计信息:
  - 迭代次数: 1
  - 执行耗时: 3.25秒

================================================================================

💬 请输入问题: 
```

### 输出说明

#### 成功输出
```
✅ SQL生成成功!

生成的SQL:
--------------------------------------------------------------------------------
[SQL语句]
--------------------------------------------------------------------------------

📊 统计信息:
  - 迭代次数: 1
  - 执行耗时: 3.25秒

⚠️  性能警告:（如果有）
  - 检测到顺序扫描（Seq Scan），可能影响性能
```

#### 失败输出
```
❌ SQL生成失败!

错误类型: validation_failed
错误信息: [错误详情]

📝 验证历史 (3次尝试):
  第1次尝试失败:
    - relation "public.nonexistent_table" does not exist
```

### 日志文件

所有执行日志会保存到：
```
logs/sql_subgraph.log
```

日志包含：
- 用户输入的问题
- 子图执行过程
- 生成的SQL
- 错误信息（如果有）
- 执行耗时

### 退出交互模式

在交互模式中，可以使用以下命令退出：
- `exit`
- `quit`
- `q`
- `退出`
- `Ctrl+C`

### 示例问题

```bash
# 时间范围查询
python scripts/nl2sql_subgraph_cli.py "查询2024年10月的订单总金额"

# 对比查询
python scripts/nl2sql_subgraph_cli.py "对比京东便利和全家的销售额"

# TOP-N查询
python scripts/nl2sql_subgraph_cli.py "销售额最高的前10个门店"

# 维度查询
python scripts/nl2sql_subgraph_cli.py "列出所有门店名称"

# 聚合查询
python scripts/nl2sql_subgraph_cli.py "计算9月份的平均订单金额"
```

### 依赖要求

确保以下服务正常运行：
- PostgreSQL 数据库
- Neo4j 图数据库
- Embedding 服务
- 通义千问 API (DASHSCOPE_API_KEY)

### 配置文件

工具使用以下配置：
- `src/modules/sql_generation/config/sql_generation_subgraph.yaml`
- `.env` 文件中的环境变量

### 故障排查

1. **数据库连接失败**
   ```
   检查 .env 文件中的数据库配置
   确保 PostgreSQL 和 Neo4j 正常运行
   ```

2. **API密钥错误**
   ```
   检查 DASHSCOPE_API_KEY 环境变量
   确保密钥有效且有足够额度
   ```

3. **模块导入错误**
   ```
   确保在项目根目录运行
   检查 Python 环境是否正确
   ```

### 高级用法

#### 查看详细日志
```bash
# 实时查看日志
tail -f logs/sql_subgraph.log

# Windows
Get-Content logs/sql_subgraph.log -Wait
```

#### 批量查询
创建问题文件 `questions.txt`：
```
查询2024年10月的订单总数
对比京东便利和全家的销售额
销售额最高的前10个门店
```

然后批量执行：
```bash
# Linux/Mac
while read question; do
    python scripts/nl2sql_subgraph_cli.py "$question"
done < questions.txt

# Windows (PowerShell)
Get-Content questions.txt | ForEach-Object {
    python scripts/nl2sql_subgraph_cli.py $_
}
```

