# 调试工具

本目录包含用于调试和辅助开发的脚本工具。

## 搜索工具

- `search_graph_switch.py` - 搜索文档中的图级开关相关内容
- `search_checkpoint_cleanup.py` - 搜索 checkpoint 清理相关代码
- `search_created_at.py` - 搜索 created_at 字段相关代码
- `search_namespace.py` - 搜索 namespace 相关代码

## 通用工具

- `read_lines.py` - 读取文件指定行（通用文件读取工具）
- `embedding_similarity_probe.py` - Embedding 相似度探测工具

## 使用方法

这些脚本主要用于临时调试和快速搜索，直接运行即可：

```bash
python tests\debug_tools\search_graph_switch.py
python tests\debug_tools\embedding_similarity_probe.py
```

## 注意事项

- 这些是临时性调试工具，可能随时修改或删除
- 不应被正式代码依赖

