# 字段名语义相似度解决方案

## 📋 目录

1. [当前方法](#当前方法)
2. [问题分析](#问题分析)
3. [可用的本地方案](#可用的本地方案)
4. [对比测试](#对比测试)
5. [集成建议](#集成建议)
6. [安装指南](#安装指南)

---

## 当前方法

metaweave 目前使用 **SequenceMatcher** (Python 标准库 `difflib`) 来计算字段名相似度。

### 算法原理

- **名称**: Ratcliff/Obershelp 算法（Gestalt Pattern Matching）
- **原理**: 基于最长公共子序列 (LCS)
- **公式**: `相似度 = 2 * M / T`
  - M = 匹配字符数
  - T = 两个字符串的总字符数

### 代码位置

```python
# src/metaweave/core/relationships/scorer.py
# src/metaweave/core/relationships/candidate_generator.py

from difflib import SequenceMatcher

def _calculate_name_similarity(self, name1: str, name2: str) -> float:
    if name1.lower() == name2.lower():
        return 1.0
    return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
```

### 优点 ✅

- 速度极快 (~0.01ms/次)
- 无需额外依赖
- 对拼写相似的字段效果好
- 能识别常见缩写

### 缺点 ❌

- 无法理解语义
- 不能识别同义词 (`customer` vs `client`)
- 对完全不同的命名无效 (`id` vs `pk` → 0.0)

---

## 问题分析

### SequenceMatcher 失败的典型场景

| 字段1 | 字段2 | 实际相似度 | 期望相似度 | 问题 |
|-------|-------|-----------|-----------|------|
| `customer_id` | `client_id` | 0.50 | 0.85 | 同义词无法识别 |
| `user_id` | `person_id` | 0.62 | 0.75 | 同义词无法识别 |
| `product_name` | `item_name` | 0.57 | 0.80 | 同义词无法识别 |
| `quantity` | `qty` | 0.55 | 0.90 | 不规则缩写 |
| `id` | `pk` | 0.00 | 0.70 | 完全不同的命名 |

### 为什么 metaweave 目前还能工作？

metaweave 使用 **多维度评分系统**：

```python
DEFAULT_WEIGHTS = {
    "inclusion_rate": 0.30,      # 数据采样匹配率（最重要）
    "jaccard_index": 0.15,       # Jaccard 相似度
    "uniqueness": 0.10,          # 唯一性
    "name_similarity": 0.20,     # 名称相似度（只占20%）
    "semantic_role_bonus": 0.05, # 语义角色
}
```

即使字段名不相似，只要数据实际匹配良好 (`inclusion_rate` 高)，也能被识别为关系。

---

## 可用的本地方案

### 方案1: Sentence-BERT（强烈推荐）⭐⭐⭐⭐⭐

**优点：**
- 理解语义，能识别同义词
- 准确度高
- 完全本地运行，无需在线 API
- 模型较小 (22MB - 420MB)

**缺点：**
- 需要安装依赖：`pip install sentence-transformers`
- 首次运行下载模型 (~2秒)
- 比 SequenceMatcher 慢 (~1-5ms/次)

**推荐模型：**
- `all-MiniLM-L6-v2` (22MB, 轻量级，推荐) ⭐⭐⭐⭐⭐
- `paraphrase-MiniLM-L3-v2` (61MB, 更快)
- `all-mpnet-base-v2` (420MB, 效果最好但较慢)

**示例代码：**

```python
from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer('all-MiniLM-L6-v2')

def similarity(name1, name2):
    text1 = name1.replace('_', ' ')
    text2 = name2.replace('_', ' ')
    emb1 = model.encode([text1], convert_to_tensor=True)
    emb2 = model.encode([text2], convert_to_tensor=True)
    return util.cos_sim(emb1, emb2).item()

# 测试
print(similarity("customer_id", "client_id"))  # ~0.85 (vs 0.50)
print(similarity("id", "pk"))                   # ~0.70 (vs 0.00)
```

### 方案2: 增强型规则方法 ⭐⭐⭐

**优点：**
- 无需额外依赖
- 速度快 (~0.02ms/次)
- 立即可用

**缺点：**
- 需要维护规则库
- 只能识别预定义的同义词

**实现：**

```python
# SequenceMatcher + 同义词词典 + 缩写词典
SYNONYMS = {
    'customer': ['client', 'cust'],
    'user': ['person', 'usr'],
    'product': ['item', 'prod'],
    'order': ['purchase'],
    'quantity': ['qty'],
    'identifier': ['id', 'key', 'pk'],
}

def enhanced_similarity(name1, name2):
    base_sim = SequenceMatcher(None, name1, name2).ratio()
    
    # 检查同义词
    for base, variants in SYNONYMS.items():
        if has_synonym(name1, name2, base, variants):
            base_sim = max(base_sim, 0.8)
    
    return base_sim
```

### 方案3: spaCy + 词向量 ⭐⭐⭐⭐

**优点：**
- 成熟稳定
- 功能丰富
- 支持多种语言

**缺点：**
- 模型较大 (~50MB)
- 需要安装：`pip install spacy && python -m spacy download en_core_web_md`

### 方案4: FastText/Word2Vec ⭐⭐⭐

**优点：**
- 灵活，可以用自己的数据训练
- 能处理未见过的词（FastText）

**缺点：**
- 需要预训练模型或自己训练
- 对短词效果一般

---

## 对比测试

运行测试脚本查看对比：

```bash
# 基础测试（无需额外依赖）
python tests/test_name_similarity.py

# 语义相似度对比演示
python tests/test_semantic_similarity_demo.py

# 完整对比（需要 sentence-transformers）
python tests/test_semantic_similarity.py

# 集成示例
python tests/example_enhanced_similarity.py
```

### 测试结果对比

| 测试用例 | SequenceMatcher | 增强规则 | SBERT | 说明 |
|---------|----------------|---------|-------|------|
| `customer_id` vs `client_id` | 0.50 | 0.80 | 0.85 | 同义词 |
| `user_id` vs `person_id` | 0.62 | 0.80 | 0.75 | 同义词 |
| `quantity` vs `qty` | 0.55 | 0.80 | 0.90 | 缩写 |
| `id` vs `pk` | 0.00 | 0.85 | 0.70 | 主键 |
| `order_date` vs `order_dt` | 0.89 | 0.89 | 0.90 | 常见缩写 |

---

## 集成建议

### 推荐方案：混合方法（渐进式升级）

```python
class HybridSimilarity:
    """混合相似度计算器
    
    自动选择最佳方法：
    - 优先尝试加载 SBERT
    - 失败则使用增强型规则
    - 向后兼容原有方法
    """
    
    def __init__(self):
        self.enhanced_matcher = EnhancedSequenceMatcher()
        
        # 尝试加载 SBERT（可选依赖）
        try:
            from sentence_transformers import SentenceTransformer
            self.sbert_model = SentenceTransformer('all-MiniLM-L6-v2')
            self.use_sbert = True
        except ImportError:
            self.use_sbert = False
    
    def similarity(self, name1, name2):
        # 字符相似度
        char_sim = self.enhanced_matcher.similarity(name1, name2)
        
        # 如果字符相似度很高，直接返回
        if char_sim > 0.95:
            return char_sim
        
        # 使用 SBERT 增强
        if self.use_sbert:
            semantic_sim = self._sbert_similarity(name1, name2)
            return char_sim * 0.3 + semantic_sim * 0.7
        
        return char_sim
```

### 配置文件扩展

在 `config.yaml` 中添加：

```yaml
relationships:
  name_similarity:
    method: "hybrid"  # 可选: "sequence_matcher", "enhanced", "sbert", "hybrid"
    sbert_model: "all-MiniLM-L6-v2"
    weights:
      char: 0.3
      semantic: 0.7
```

### 修改 scorer.py

```python
class RelationshipScorer:
    def __init__(self, config: dict, connector: DatabaseConnector):
        # ... 现有代码 ...
        
        # 初始化相似度计算器
        sim_config = config.get("name_similarity", {})
        method = sim_config.get("method", "sequence_matcher")
        
        if method == "hybrid":
            self.similarity_calculator = HybridSimilarity()
        elif method == "enhanced":
            self.similarity_calculator = EnhancedSequenceMatcher()
        else:
            self.similarity_calculator = None  # 使用原有实现
    
    def _calculate_name_similarity(self, source_columns, target_columns):
        if len(source_columns) != len(target_columns):
            return 0.0
        
        total_sim = 0
        for src_col, tgt_col in zip(source_columns, target_columns):
            if self.similarity_calculator:
                sim = self.similarity_calculator.similarity(src_col, tgt_col)
            else:
                # 原有实现（向后兼容）
                if src_col == tgt_col:
                    sim = 1.0
                else:
                    sim = SequenceMatcher(None, src_col.lower(), tgt_col.lower()).ratio()
            
            total_sim += sim
        
        return total_sim / len(source_columns)
```

---

## 安装指南

### 安装 Sentence-BERT

```bash
pip install sentence-transformers
```

首次运行时会自动下载模型到：`~/.cache/torch/sentence_transformers/`

### 验证安装

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
print("✅ SBERT 安装成功！")
```

---

## 性能对比

| 方法 | 速度 | 内存占用 | 准确度 | 依赖 |
|------|------|---------|--------|------|
| SequenceMatcher | 0.01ms/次 | <1MB | ⭐⭐⭐ | 无 |
| 增强规则 | 0.02ms/次 | <1MB | ⭐⭐⭐⭐ | 无 |
| SBERT | 1-5ms/次 | 22-100MB | ⭐⭐⭐⭐⭐ | sentence-transformers |
| 混合方法 | 1-5ms/次 | 22-100MB | ⭐⭐⭐⭐⭐ | 可选 |

### 在实际场景中的影响

**假设：1000 个候选关系需要评分**

- SequenceMatcher: ~10ms
- 增强规则: ~20ms
- SBERT: ~1-5秒 (首次加载 +2秒)
- 混合方法: ~1-5秒

**优化建议：**
1. 使用缓存避免重复计算
2. 批量编码提升性能（SBERT）
3. 只在必要时使用语义匹配

---

## 总结

### 🎯 针对不同场景的建议

1. **小规模数据库 (< 100 张表)**
   - 推荐：**混合方法** 或 **SBERT**
   - 理由：准确度优先，性能影响小

2. **中等规模 (100-500 张表)**
   - 推荐：**增强规则方法**
   - 理由：平衡准确度和性能

3. **大规模 (> 500 张表)**
   - 推荐：**SequenceMatcher + 缓存**
   - 理由：性能优先，配合数据采样维度足够

4. **命名不规范的遗留系统**
   - 推荐：**SBERT** 或 **混合方法**
   - 理由：需要强语义理解能力

### 📝 实施步骤

1. **第一阶段**：添加增强规则方法（无需依赖）
2. **第二阶段**：添加配置支持可选 SBERT
3. **第三阶段**：根据用户反馈优化权重和规则

### 🔗 相关文件

- 测试脚本：
  - `tests/test_name_similarity.py` - 基础测试
  - `tests/test_semantic_similarity_demo.py` - 对比演示
  - `tests/test_semantic_similarity.py` - 完整测试
  - `tests/example_enhanced_similarity.py` - 集成示例

- 核心代码：
  - `src/metaweave/core/relationships/scorer.py`
  - `src/metaweave/core/relationships/candidate_generator.py`

---

## 参考资源

- [Sentence-Transformers 文档](https://www.sbert.net/)
- [Python difflib 文档](https://docs.python.org/3/library/difflib.html)
- [预训练模型列表](https://www.sbert.net/docs/pretrained_models.html)

