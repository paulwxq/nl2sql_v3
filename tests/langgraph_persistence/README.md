# LangGraph 持久化测试脚本

本目录包含用于测试和验证 LangGraph 持久化功能的脚本。

## 测试脚本

### 功能测试
- `test_langgraph_persistence.py` - 完整的持久化功能测试（Checkpoint + Store）
- `test_langgraph_multi_turn.py` - 多轮对话持久化测试
- `test_search_path.py` - 验证 PostgreSQL search_path 配置
- `test_no_checkpointer.py` - 验证无 checkpointer 时的 LangGraph 行为
- `test_invalid_thread_id.py` - 验证无效 thread_id 的处理

### 数据检查工具
- `check_all_tables.py` - 检查所有 langgraph 表结构
- `check_checkpoint_data.py` - 检查 checkpoint 表数据
- `check_store_schema.py` - 检查 store 表结构

## 使用方法

```bash
# 运行完整持久化测试
.venv-win\Scripts\python.exe tests\langgraph_persistence\test_langgraph_persistence.py

# 检查表结构
.venv-win\Scripts\python.exe tests\langgraph_persistence\check_all_tables.py
```

## 注意事项

- 这些脚本需要 PostgreSQL 数据库连接配置
- 运行前确保已在 `.env` 或 `config.yaml` 中正确配置数据库连接

