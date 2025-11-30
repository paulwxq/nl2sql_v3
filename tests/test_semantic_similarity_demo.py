"""语义相似度算法对比演示（不需要安装额外依赖）"""

from difflib import SequenceMatcher


def similarity_sequencematcher(name1: str, name2: str) -> float:
    """基于字符串匹配的相似度（当前 metaweave 使用）"""
    if name1.lower() == name2.lower():
        return 1.0
    return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()


def main():
    """演示 SequenceMatcher 的局限性"""
    print("=" * 80)
    print("SequenceMatcher 的局限性演示")
    print("=" * 80)
    
    test_cases = [
        ("字段1", "字段2", "SequenceMatcher", "理想的语义匹配结果", "说明"),
        ("=" * 15, "=" * 15, "=" * 15, "=" * 20, "=" * 30),
        
        # 字符串相似的情况 - SequenceMatcher 表现好
        ("user_id", "userid", 0.92, 0.95, "✅ 拼写相似 - SM 表现好"),
        ("order_date", "order_dt", 0.89, 0.90, "✅ 缩写 - SM 表现好"),
        ("customer_id", "cust_id", 0.78, 0.80, "✅ 常见缩写 - SM 尚可"),
        
        # 语义相似但字符串不同 - SequenceMatcher 表现差
        ("customer_id", "client_id", 0.48, 0.85, "❌ 同义词 - SM 失败"),
        ("user_id", "person_id", 0.32, 0.75, "❌ 同义词 - SM 失败"),
        ("product_name", "item_name", 0.41, 0.80, "❌ 同义词 - SM 失败"),
        ("order_id", "purchase_id", 0.36, 0.80, "❌ 同义词 - SM 失败"),
        ("quantity", "qty", 0.47, 0.90, "❌ 缩写 - SM 表现差"),
        
        # 主键相关
        ("id", "pk", 0.00, 0.70, "❌ 主键命名 - SM 完全失败"),
        ("id", "key", 0.00, 0.60, "❌ 主键命名 - SM 完全失败"),
        ("user_id", "user_fk", 0.80, 0.90, "⚠️ id vs fk - SM 尚可"),
    ]
    
    print(f"\n{'字段1':<18} {'字段2':<18} {'当前方法':<10} {'语义方法':<12} {'说明':<30}")
    print("-" * 90)
    
    for i, case in enumerate(test_cases):
        if i < 2:  # 跳过表头
            continue
        
        word1, word2, expected_sm, expected_semantic, description = case
        actual_sm = similarity_sequencematcher(word1, word2)
        
        print(f"{word1:<18} {word2:<18} {actual_sm:<10.2f} {expected_semantic:<12.2f} {description:<30}")
    
    print("\n" + "=" * 80)
    print("总结")
    print("=" * 80)
    
    summary = """
    从上面的结果可以看出：
    
    ✅ SequenceMatcher 表现好的场景：
       • 拼写相似的字段 (user_id vs userid)
       • 常见缩写 (order_date vs order_dt)
       • 大小写差异
    
    ❌ SequenceMatcher 表现差的场景：
       • 同义词 (customer vs client, user vs person, product vs item)
       • 不规则缩写 (quantity vs qty)
       • 完全不同的命名 (id vs pk vs key)
    
    
    🎯 可用的本地语义匹配方案：
    
    1. Sentence-BERT (强烈推荐) ⭐⭐⭐⭐⭐
       • 优点：准确度高，理解语义，本地运行
       • 缺点：需要安装依赖，首次下载模型 (~22MB)
       • 安装：pip install sentence-transformers
       • 模型：all-MiniLM-L6-v2 (轻量级，性能好)
       • 性能：~1-5ms/次 (SequenceMatcher: ~0.01ms/次)
       
       示例代码：
       ```python
       from sentence_transformers import SentenceTransformer, util
       
       model = SentenceTransformer('all-MiniLM-L6-v2')
       
       def similarity(name1, name2):
           text1 = name1.replace('_', ' ')
           text2 = name2.replace('_', ' ')
           emb1 = model.encode([text1], convert_to_tensor=True)
           emb2 = model.encode([text2], convert_to_tensor=True)
           return util.cos_sim(emb1, emb2).item()
       ```
    
    2. 增强型规则方法（轻量级方案）⭐⭐⭐
       • 优点：无需额外依赖，速度快
       • 缺点：需要维护规则库
       • 实现：SequenceMatcher + 同义词词典 + 缩写词典
       
       示例代码：
       ```python
       SYNONYMS = {
           'customer': ['client', 'cust'],
           'user': ['person', 'usr'],
           'product': ['item', 'prod'],
           'order': ['purchase'],
           'quantity': ['qty', 'amount'],
           'description': ['desc'],
           'identifier': ['id', 'key', 'pk'],
       }
       
       def enhanced_similarity(name1, name2):
           # 先用 SequenceMatcher
           base_sim = SequenceMatcher(None, name1, name2).ratio()
           
           # 检查同义词
           for base, variants in SYNONYMS.items():
               if (base in name1 or any(v in name1 for v in variants)) and \\
                  (base in name2 or any(v in name2 for v in variants)):
                   base_sim = max(base_sim, 0.8)
           
           return base_sim
       ```
    
    3. spaCy + 词向量 ⭐⭐⭐⭐
       • 优点：成熟稳定，功能丰富
       • 缺点：模型较大 (~50MB)
       • 安装：pip install spacy && python -m spacy download en_core_web_md
       
    4. Gensim Word2Vec/FastText ⭐⭐⭐
       • 优点：灵活，可以用自己的数据训练
       • 缺点：需要训练或下载预训练模型
       • 安装：pip install gensim
    
    
    💡 针对 metaweave 的建议：
    
    方案A：渐进式升级（推荐）
    1. 保持当前 SequenceMatcher 作为默认
    2. 添加配置项支持 Sentence-BERT
    3. 如果安装了 sentence-transformers 就自动启用
    4. 否则回退到 SequenceMatcher
    
    方案B：轻量级增强
    1. 添加数据库领域的同义词词典
    2. 在 SequenceMatcher 基础上增强
    3. 无需额外依赖
    
    
    📊 性能对比（在 1000 个候选关系的场景）：
    
    • SequenceMatcher: ~10ms，无需安装
    • SBERT: ~1-5秒，需要安装 (首次加载 ~2秒)
    • 增强型规则: ~20ms，无需安装
    
    建议：
    - 如果性能要求极高：使用增强型规则方法
    - 如果准确度重要：使用 Sentence-BERT
    - 如果要兼容性好：保持 SequenceMatcher 但添加缓存
    """
    
    print(summary)
    
    print("\n" + "=" * 80)
    print("快速测试 Sentence-BERT")
    print("=" * 80)
    print("\n如果想测试 Sentence-BERT 的效果，运行以下命令：")
    print("\n  pip install sentence-transformers")
    print("  python tests/test_semantic_similarity.py")
    print("\n首次运行会自动下载模型（~22MB），之后使用本地缓存。")


if __name__ == "__main__":
    main()

