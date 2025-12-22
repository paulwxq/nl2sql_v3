# Metaweave 关系发现测试脚本

本目录包含用于测试 Metaweave 关系发现、复合键匹配等功能的脚本。

## 测试脚本分类

### 候选生成测试
- `test_candidate_only.py` - 仅测试候选生成阶段，不涉及数据库连接
- `test_composite_candidates.py` - 测试复合键候选生成逻辑

### 复合键匹配测试
- `test_composite_generation.py` - 测试复合键关系生成
- `test_composite_logical_key_matching.py` - 测试复合逻辑主键匹配
- `test_full_composite_generation.py` - 完整的复合键生成测试

### 关系管道测试
- `test_full_relationship_pipeline.py` - 完整的关系发现管道测试

### 数据结构测试
- `test_structure_flags.py` - 测试 StructureFlags 的字段互斥性
- `test_modifications.py` - 测试元数据修改功能
- `test_fallback_defaults.py` - 测试回退默认值

### 数据验证
- `verify_milvus_data.py` - 验证 Milvus 中的 dim_value_embeddings 数据

## 使用方法

这些脚本通常直接运行，不需要额外参数：

```bash
python tests\metaweave_relationships\test_candidate_only.py
python tests\metaweave_relationships\test_structure_flags.py
python tests\metaweave_relationships\verify_milvus_data.py
```

## 注意事项

- 部分脚本需要已生成的元数据文件（`output/metaweave/metadata/json/`）
- 部分脚本需要数据库连接（PostgreSQL/Neo4j）
- 部分脚本需要 Milvus 连接
- 运行前请确保相关依赖服务已启动

