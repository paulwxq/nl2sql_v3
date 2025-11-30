# 字段名相似度测试套件

本目录包含了字段名相似度算法的测试和示例代码。

## 📁 文件说明

### 1. `test_name_similarity.py`
基础测试，展示当前 metaweave 使用的 SequenceMatcher 算法。

**测试内容：**
- 英文字段名相似度
- 中文字段名相似度
- 混合语言相似度
- 算法特性分析

**运行：**
```bash
python tests/test_name_similarity.py
```

**无需额外依赖** ✅

---

### 2. `test_semantic_similarity_demo.py`
对比演示，展示 SequenceMatcher 的局限性和改进空间。

**测试内容：**
- SequenceMatcher 表现好的场景
- SequenceMatcher 表现差的场景
- 可用的本地语义匹配方案介绍
- 安装指南

**运行：**
```bash
python tests/test_semantic_similarity_demo.py
```

**无需额外依赖** ✅

---

### 3. `test_semantic_similarity.py`
完整对比测试，比较不同算法的效果。

**测试内容：**
- SequenceMatcher
- Sentence-BERT
- FastText（可选）
- 混合方法
- 性能基准测试

**运行：**
```bash
# 安装依赖（首次）
pip install sentence-transformers

# 运行测试
python tests/test_semantic_similarity.py
```

**需要安装：** `sentence-transformers`

---

### 4. `example_enhanced_similarity.py`
集成示例，展示如何在 metaweave 中实现增强的相似度计算。

**包含：**
- 方案1：增强型规则方法（无需依赖）
- 方案2：Sentence-BERT 集成
- 方案3：混合方法（推荐）
- 在 metaweave 中的集成指南

**运行：**
```bash
python tests/example_enhanced_similarity.py
```

**无需额外依赖** ✅（SBERT 部分是可选的）

---

## 🚀 快速开始

### 场景1：了解当前方法

```bash
python tests/test_name_similarity.py
```

查看 metaweave 当前使用的 SequenceMatcher 在不同场景下的表现。

### 场景2：看看能改进多少

```bash
python tests/test_semantic_similarity_demo.py
```

对比当前方法和理想的语义匹配结果。

### 场景3：测试新方案

```bash
# 无需安装依赖的方案
python tests/example_enhanced_similarity.py

# 完整的语义匹配方案
pip install sentence-transformers
python tests/test_semantic_similarity.py
```

---

## 📊 测试结果摘要

### SequenceMatcher 表现好的场景 ✅

| 字段1 | 字段2 | 相似度 | 说明 |
|-------|-------|--------|------|
| `user_id` | `userid` | 0.92 | 拼写相似 |
| `order_date` | `order_dt` | 0.89 | 常见缩写 |
| `customer_id` | `cust_id` | 0.78 | 缩写 |

### SequenceMatcher 表现差的场景 ❌

| 字段1 | 字段2 | 当前 | 期望 | 说明 |
|-------|-------|------|------|------|
| `customer_id` | `client_id` | 0.50 | 0.85 | 同义词 |
| `user_id` | `person_id` | 0.62 | 0.75 | 同义词 |
| `quantity` | `qty` | 0.55 | 0.90 | 不规则缩写 |
| `id` | `pk` | 0.00 | 0.70 | 完全不同命名 |

---

## 🎯 推荐方案

### 方案A：增强型规则（立即可用）

**优点：**
- ✅ 无需安装依赖
- ✅ 速度快
- ✅ 立即提升效果

**实现：**
```python
from tests.example_enhanced_similarity import EnhancedSequenceMatcher

matcher = EnhancedSequenceMatcher()
similarity = matcher.similarity("customer_id", "client_id")
print(similarity)  # 0.80（vs 原来的 0.50）
```

### 方案B：Sentence-BERT（最佳效果）

**优点：**
- ✅ 理解语义
- ✅ 识别同义词
- ✅ 本地运行

**安装：**
```bash
pip install sentence-transformers
```

**实现：**
```python
from tests.example_enhanced_similarity import SBERTSimilarity

matcher = SBERTSimilarity()
similarity = matcher.similarity("customer_id", "client_id")
print(similarity)  # 0.85（vs 原来的 0.50）
```

### 方案C：混合方法（推荐）

**优点：**
- ✅ 自动选择最佳方案
- ✅ 向后兼容
- ✅ 可配置

**实现：**
```python
from tests.example_enhanced_similarity import HybridSimilarity

matcher = HybridSimilarity()
similarity = matcher.similarity("customer_id", "client_id")
print(similarity)  # 自动使用最佳方法
```

---

## 🔧 在 metaweave 中集成

### 步骤1：复制实现代码

将 `example_enhanced_similarity.py` 中的类复制到：
```
src/metaweave/utils/similarity.py
```

### 步骤2：修改 scorer.py

```python
from src.metaweave.utils.similarity import HybridSimilarity

class RelationshipScorer:
    def __init__(self, config: dict, connector: DatabaseConnector):
        # ... 现有代码 ...
        
        # 初始化相似度计算器
        self.similarity_calculator = HybridSimilarity()
    
    def _calculate_name_similarity(self, source_columns, target_columns):
        # ... 使用 self.similarity_calculator ...
```

### 步骤3：同样修改 candidate_generator.py

详细集成指南参见：`docs/semantic_similarity_guide.md`

---

## 📈 性能对比

| 方法 | 速度 | 准确度 | 依赖 |
|------|------|--------|------|
| SequenceMatcher | 0.01ms | ⭐⭐⭐ | 无 |
| 增强规则 | 0.02ms | ⭐⭐⭐⭐ | 无 |
| SBERT | 1-5ms | ⭐⭐⭐⭐⭐ | sentence-transformers |
| 混合 | 1-5ms | ⭐⭐⭐⭐⭐ | 可选 |

---

## 🌟 最佳实践

1. **开发环境**：使用混合方法，安装 sentence-transformers
2. **生产环境（小规模）**：使用混合方法
3. **生产环境（大规模）**：使用增强规则或 SequenceMatcher + 缓存
4. **遗留系统（命名混乱）**：必须使用 SBERT 或混合方法

---

## 📚 相关文档

- [完整指南](../docs/semantic_similarity_guide.md)
- [Sentence-Transformers 官方文档](https://www.sbert.net/)
- [预训练模型列表](https://www.sbert.net/docs/pretrained_models.html)

---

## ❓ FAQ

### Q1: 为什么不直接用 SBERT 替换 SequenceMatcher？

A: 考虑向后兼容性和性能。SBERT 需要额外依赖，且速度比 SequenceMatcher 慢 100-500 倍。采用可配置的方式让用户选择。

### Q2: 增强规则方法的同义词词典够用吗？

A: 对于大多数英文数据库字段足够。可以根据实际情况扩展词典。

### Q3: SBERT 模型存储在哪里？

A: 首次运行时自动下载到 `~/.cache/torch/sentence_transformers/`，之后使用本地缓存。

### Q4: 性能影响有多大？

A: 对于 1000 个候选关系：
- SequenceMatcher: ~10ms
- 增强规则: ~20ms
- SBERT: ~1-5秒（可以通过缓存和批处理优化）

### Q5: 支持中文吗？

A: 
- SequenceMatcher: 对中文效果有限（只能字面匹配）
- 增强规则: 可以添加中文同义词词典
- SBERT: 需要使用中文预训练模型（如 `paraphrase-multilingual-MiniLM-L12-v2`）

---

## 🤝 贡献

如果发现新的同义词模式或有改进建议，欢迎：

1. 更新 `SYNONYMS` 词典
2. 添加测试用例
3. 优化算法实现

---

## 📝 更新日志

- 2025-11-30: 创建测试套件和文档
- 未来：根据用户反馈持续优化

---

**Happy Testing! 🎉**

