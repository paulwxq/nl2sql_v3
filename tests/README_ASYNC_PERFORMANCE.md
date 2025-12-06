# LLM 异步性能对比测试

## 概述

该测试程序用于对比两种 LLM 异步调用方式的性能：

1. **LangChain ainvoke**：使用 LangChain 的异步接口（兼容多提供商：Qwen, DeepSeek 等）
2. **DashScope AioGeneration**：使用 DashScope 原生的异步 API（仅支持 Qwen）

## 测试场景

- **数据源**：`output/metaweave/metadata/json_llm` 目录下的 13 张表
- **测试规模**：78 个表对组合 (C(13,2))
- **调用方式**：真实 API 调用（会消耗 API 额度）
- **并发数**：10（可在代码中调整）
- **Prompt**：使用关系发现的标准 prompt 模板

## 测试指标

1. **总耗时**（秒）
2. **成功率**（成功调用数 / 总调用数）
3. **平均耗时**（每次调用的平均时间）
4. **失败详情**（如有失败，显示前 5 个错误）

## 环境要求

### Python 依赖

```bash
pip install langchain-community dashscope python-dotenv pyyaml
```

### 配置文件

确保以下文件存在并正确配置：

1. **`.env`**：包含 `DASHSCOPE_API_KEY`
2. **`configs/metaweave/metadata_config.yaml`**：包含 LLM 配置

## 运行测试

从项目根目录运行：

```bash
# Windows
python -m tests.test_llm_async_performance

# Linux/Mac
python -m tests.test_llm_async_performance
```

或者直接运行：

```bash
python tests/test_llm_async_performance.py
```

## 预期输出示例

```
================================================================================
LLM 异步性能对比测试
================================================================================
加载配置和数据...
配置信息:
  - 模型: qwen-plus
  - 测试表数: 13 张
  - 表对组合: 78 个
  - 并发数: 10
  - Temperature: 0.3

--------------------------------------------------------------------------------
测试 1: LangChain ainvoke (兼容多提供商)
--------------------------------------------------------------------------------
执行中...
  进度: 78/78
✓ 完成
  - 总耗时: 21.35 秒
  - 成功调用: 78 / 78 (100.0%)
  - 平均耗时: 0.27 秒/次
  - 失败: 0

等待 5 秒后开始第二个测试...

--------------------------------------------------------------------------------
测试 2: DashScope AioGeneration (仅 Qwen)
--------------------------------------------------------------------------------
执行中...
  进度: 78/78
✓ 完成
  - 总耗时: 18.92 秒
  - 成功调用: 78 / 78 (100.0%)
  - 平均耗时: 0.24 秒/次
  - 失败: 0

================================================================================
对比结果
================================================================================
性能差异:
  - DashScope AioGeneration 比 LangChain ainvoke 快 2.43 秒 (11.4%)
  - 两者成功率相同: 100.0%

建议:
  - DashScope AioGeneration 性能更优 (11.4%)
  - 如仅使用 Qwen，推荐使用 DashScope 原生 API
  - 如需保持多提供商兼容性，使用 LangChain
================================================================================
```

## 成本估算

- **每次测试**：78 次 API 调用
- **两个测试**：总共 156 次 API 调用
- **Token 消耗**：取决于表结构复杂度，预计每次 1000-2000 tokens
- **预计成本**（qwen-plus）：约 0.1-0.2 元人民币

## 调整测试参数

### 修改并发数

在 `TestConfig.__init__` 中修改：

```python
self.concurrent_limit = 10  # 改为 5, 15, 20 等
```

### 测试部分表对

在 `main()` 函数中添加：

```python
# 只测试前 20 个表对
table_pairs = generate_table_pairs(tables)[:20]
```

### 调整模型参数

在配置文件 `configs/metaweave/metadata_config.yaml` 中修改：

```yaml
llm:
  providers:
    qwen:
      model: qwen-turbo  # 或 qwen-max
      temperature: 0.3
      max_tokens: 500
```

## 测试结果分析

### 预期结果

1. **性能对比**：
   - DashScope 原生 API 通常会快 5-15%
   - 原因：减少了 LangChain 的封装层开销

2. **成功率**：
   - 两者应该都接近 100%
   - 如果成功率低于 95%，检查：
     - API Key 是否有效
     - 网络连接是否稳定
     - 是否触发了 API 限流

3. **失败原因**：
   - 常见：网络超时、API 限流
   - 解决：减少并发数或增加重试逻辑

### 决策建议

**选择 LangChain ainvoke 如果**：
- 需要支持多个 LLM 提供商（Qwen, DeepSeek, OpenAI 等）
- 性能差异可接受（< 15%）
- 希望代码更易于维护和扩展

**选择 DashScope AioGeneration 如果**：
- 只使用 Qwen 模型
- 需要最优性能
- 对性能敏感（大规模调用场景）

## 故障排查

### 问题：`DASHSCOPE_API_KEY not found`

**解决**：在项目根目录的 `.env` 文件中添加：

```
DASHSCOPE_API_KEY=your_api_key_here
```

### 问题：`ModuleNotFoundError: No module named 'langchain_community'`

**解决**：安装缺失的依赖：

```bash
pip install langchain-community dashscope
```

### 问题：API 调用频繁失败

**解决**：
1. 检查 API Key 是否有效
2. 减少并发数（改为 5 或 3）
3. 检查网络连接
4. 查看是否触发 API 限流

### 问题：测试时间过长

**解决**：
1. 减少测试的表对数量（在代码中截取部分表对）
2. 增加并发数（但注意不要触发限流）
3. 使用更快的模型（如 qwen-turbo）

## 相关文件

- 测试程序：[tests/test_llm_async_performance.py](test_llm_async_performance.py)
- 配置文件：[configs/metaweave/metadata_config.yaml](../configs/metaweave/metadata_config.yaml)
- 环境变量：`.env`（项目根目录）
- 测试数据：`output/metaweave/metadata/json_llm/`

## 后续优化

可以考虑的改进：

1. **命令行参数支持**：
   ```bash
   python tests/test_llm_async_performance.py --concurrent 15 --sample 20
   ```

2. **结果保存**：将测试结果保存到 JSON/CSV 文件

3. **可视化**：使用 matplotlib 生成性能对比图表

4. **多次测试取平均值**：减少单次测试的偶然性

5. **内存和 CPU 监控**：对比两种方法的资源消耗

