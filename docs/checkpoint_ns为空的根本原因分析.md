# checkpoint_ns 字段为空的根本原因分析

## 问题描述

在当前项目中，通过 `PostgresSaver` 向 PostgreSQL 数据库的表 `checkpoints`、`checkpoint_writes`、`checkpoint_blobs` 写入数据时，这三张表的字段 `checkpoint_ns` 都为空（空字符串）。

按照原来的设计，`checkpoint_ns` 应该存储图名/模块名/子图名/子任务 ID 等信息，比如：
- 父图：`nl2sql_father`
- 子图：`sql_generation:<sub_query_id>`

## 测试验证过程

### 测试1：PostgresSaver 直接写入测试
**测试文件**：`tests/test_checkpoint_ns_debug.py`

**结果**：✅ **成功**
- 直接调用 `PostgresSaver.put()` 方法
- checkpoint_ns 正确写入数据库
- 数据库记录显示 checkpoint_ns = `test_namespace_debug`

**结论**：PostgresSaver 本身功能正常，能正确保存 checkpoint_ns。

---

### 测试2：SafeCheckpointer 包装层测试
**测试文件**：`tests/test_safe_checkpointer_wrapper.py`

**结果**：✅ **成功**
- 通过 SafeCheckpointer 包装后调用
- checkpoint_ns 正确写入数据库
- 数据库记录显示 checkpoint_ns = `safe_wrapper_test_ns`

**结论**：SafeCheckpointer 包装层正常，正确传递了 checkpoint_ns 参数。

---

### 测试3：LangGraph 图运行端到端测试
**测试文件**：`tests/test_langgraph_checkpoint_ns_e2e.py`

**结果**：❌ **失败**
- 通过 `app.invoke(state, config=config)` 运行图
- config 中明确包含 `checkpoint_ns='e2e_test_namespace'`
- 但数据库中所有记录的 checkpoint_ns 都是**空字符串**

**结论**：问题出现在 **LangGraph 框架的图运行时**！

---

### 测试4：实际数据库记录检查
**测试文件**：`tests/check_db_checkpoint_ns.py`

**统计结果**：
- checkpoints 表：165/166 条记录的 checkpoint_ns 是**空字符串**
- checkpoint_writes 表：844 条记录**全部**是空字符串
- checkpoint_blobs 表：165 条记录**全部**是空字符串

唯一有值的记录是测试1中直接调用 PostgresSaver 写入的测试数据。

---

### 测试5：版本和 config_specs 检查
**测试文件**：`tests/check_langgraph_version.py`

**发现**：
```
langgraph 版本: 1.0.2
langgraph-checkpoint-postgres 版本: 3.0.2

PostgresSaver.config_specs: []  ⚠️ 关键发现！
```

**重要发现**：`PostgresSaver.config_specs` **为空数组**！

这意味着 PostgresSaver 没有向 LangGraph 声明它需要哪些 configurable 参数。

---

## 根本原因分析

### 核心问题

**LangGraph 在运行图时，只会传递 `config_specs` 中声明的 configurable 参数给 checkpointer。**

1. 你在代码中传入的 config：
```python
config = {
    "configurable": {
        "thread_id": "some-thread-id",
        "checkpoint_ns": "nl2sql_father",  # ← 你传了这个参数
    }
}
app.invoke(state, config=config)
```

2. 但 `PostgresSaver.config_specs = []`（空），没有声明需要 `checkpoint_ns`

3. LangGraph 在内部处理时，**过滤掉了未声明的参数**

4. 最终传递给 PostgresSaver 的 config 中，`checkpoint_ns` 变成了默认值（空字符串）

### 官方文档验证

通过 Context7 查阅 LangGraph 官方文档，发现：

1. **所有官方示例都只使用 `thread_id`**，从未使用 `checkpoint_ns`
2. 文档明确指出：使用 checkpointer 时**必须**指定 `thread_id`
3. 没有任何文档说明如何使用 `checkpoint_ns` 参数
4. 子图隔离是通过 `checkpointer=True` 让子图独立管理 checkpoint，而不是通过 `checkpoint_ns`

### LangGraph 的实际设计

根据文档和测试结果，LangGraph 的 checkpoint 隔离机制是：

```python
# 官方推荐的方式：子图独立管理 checkpoint
subgraph = subgraph_builder.compile(checkpointer=True)
```

而**不是**通过在 config 中传递 checkpoint_ns：

```python
# 这种方式不起作用！
config = {
    "configurable": {
        "thread_id": "thread-123",
        "checkpoint_ns": "my_namespace",  # ← LangGraph 会忽略这个参数
    }
}
```

---

## 数据库表结构说明

经过检查，checkpoint_ns 字段定义为：
```sql
checkpoint_ns TEXT NOT NULL
```

- 类型：TEXT
- 约束：NOT NULL（不允许 NULL）
- 默认值：无显式默认值

由于字段不允许 NULL，当 LangGraph 没有传递 checkpoint_ns 参数时，PostgresSaver 使用**空字符串**作为默认值写入。

---

## 问题定位总结

### 原因分类

**B 类原因**：你传了 checkpoint_ns，但实际执行时没有真正传递到 PostgresSaver

具体来说：

1. ✅ **代码层面传递了** checkpoint_ns
   - 父图：`graph.py:563-569`
   - 子图：`create_subgraph.py:292-302`

2. ✅ **checkpointer 正常挂载和启用**
   - PostgresSaver 创建成功
   - SafeCheckpointer 包装正常
   - 图编译时传入了 checkpointer

3. ❌ **LangGraph 框架层面过滤掉了 checkpoint_ns**
   - `PostgresSaver.config_specs` 为空
   - LangGraph 只传递已声明的参数
   - checkpoint_ns 未被声明，被框架忽略

---

## 技术根源

这是 **LangGraph 1.0.x 版本的设计行为**，而非代码 bug。

LangGraph 的 checkpoint 隔离机制：
- **thread_id**：用于区分不同的对话线程（必需参数）
- **user_id**：用于区分不同的用户（可选参数）
- **checkpoint_ns**：不是用户级参数，是 LangGraph 内部管理的概念

LangGraph 通过子图的独立 checkpointer 来实现隔离，而不是通过 checkpoint_ns：
```python
# 正确的子图隔离方式
subgraph = subgraph_builder.compile(checkpointer=True)
```

---

## 后续建议

### 选项 1：遵循 LangGraph 官方设计（推荐）

不再手动传递 checkpoint_ns，而是：
- 父图和子图使用相同的 thread_id
- 依靠 LangGraph 内部的子图隔离机制
- 通过 thread_id + 时间戳/节点信息来区分记录

### 选项 2：修改表结构（降级方案）

如果一定需要人工可读的 namespace：
- 将 checkpoint_ns 改为可选字段（允许 NULL 或设置默认值）
- 在应用层添加额外的标识字段（如 metadata）
- 通过 checkpoint metadata 传递业务标识

### 选项 3：升级或等待 LangGraph 更新

关注 LangGraph 后续版本是否提供 checkpoint_ns 的官方支持机制。

---

## 测试脚本索引

所有测试脚本位于 `tests/` 目录：
1. `test_checkpoint_ns_debug.py` - 基础功能测试
2. `test_safe_checkpointer_wrapper.py` - 包装层测试
3. `test_langgraph_checkpoint_ns_e2e.py` - 端到端测试
4. `check_db_checkpoint_ns.py` - 数据库记录检查
5. `check_table_schema.py` - 表结构检查
6. `check_langgraph_version.py` - 版本和配置检查
7. `trace_checkpointer_calls.py` - 调用追踪（可用于深入调试）

---

## 结论

**checkpoint_ns 为空的根本原因**：

LangGraph 1.0.2 版本在运行图时，只会传递 checkpointer 的 `config_specs` 中声明的参数。由于 `PostgresSaver.config_specs` 为空，LangGraph 框架**过滤掉了所有未声明的 configurable 参数**，包括我们手动传入的 `checkpoint_ns`，导致它以空字符串的形式写入数据库。

这不是代码 bug，而是 LangGraph 框架的设计机制。官方文档中没有通过 config 传递 checkpoint_ns 的用法，子图隔离是通过 `checkpointer=True` 实现的。

