"""测试语义相似度算法对比

对比不同的相似度计算方法：
1. SequenceMatcher (当前 metaweave 使用)
2. Sentence-BERT (推荐)
3. FastText (轻量级词向量)
4. 混合方法

所有方法都可以在本地运行，无需在线API。
"""

from difflib import SequenceMatcher
from typing import List, Tuple
import time


# ==================== 方法1: SequenceMatcher (当前方法) ====================
def similarity_sequencematcher(name1: str, name2: str) -> float:
    """基于字符串匹配的相似度（当前 metaweave 使用）"""
    if name1.lower() == name2.lower():
        return 1.0
    return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()


# ==================== 方法2: Sentence-BERT (推荐) ====================
def similarity_sbert(name1: str, name2: str, model=None) -> float:
    """基于 Sentence-BERT 的语义相似度
    
    优点：
    - 理解语义，能识别同义词
    - 效果好，准确度高
    - 本地运行，无需在线API
    - 支持多种预训练模型
    
    缺点：
    - 需要安装 sentence-transformers
    - 首次加载模型较慢（~100MB）
    - 比 SequenceMatcher 慢
    
    安装: pip install sentence-transformers
    """
    try:
        from sentence_transformers import SentenceTransformer, util
        
        if model is None:
            # 使用轻量级模型，适合字段名匹配
            # 可选模型：
            # - 'all-MiniLM-L6-v2' (推荐，轻量级，22MB)
            # - 'paraphrase-MiniLM-L3-v2' (更轻量，61MB)
            # - 'all-mpnet-base-v2' (最好但较大，420MB)
            model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # 对字段名进行预处理：下划线转空格
        text1 = name1.replace('_', ' ')
        text2 = name2.replace('_', ' ')
        
        embeddings1 = model.encode([text1], convert_to_tensor=True)
        embeddings2 = model.encode([text2], convert_to_tensor=True)
        
        # 计算余弦相似度
        similarity = util.cos_sim(embeddings1, embeddings2).item()
        return max(0.0, min(1.0, similarity))  # 确保在 [0, 1] 范围
        
    except ImportError:
        print("⚠️  需要安装 sentence-transformers: pip install sentence-transformers")
        return 0.0


# ==================== 方法3: FastText (词向量) ====================
def similarity_fasttext(name1: str, name2: str, model=None) -> float:
    """基于 FastText 的词向量相似度
    
    优点：
    - 轻量级，速度快
    - 可以处理未见过的词（子词信息）
    - 本地运行
    
    缺点：
    - 对短词效果一般
    - 需要预训练模型或自己训练
    
    安装: pip install fasttext
    模型下载: https://fasttext.cc/docs/en/english-vectors.html
    """
    try:
        import fasttext
        import numpy as np
        
        # 注意：需要下载预训练模型
        # wget https://dl.fbaipublicfiles.com/fasttext/vectors-english/crawl-300d-2M.vec.zip
        # 这里假设模型已下载
        if model is None:
            print("⚠️  需要加载 FastText 预训练模型")
            return 0.0
        
        # 获取词向量
        vec1 = model.get_word_vector(name1.lower().replace('_', ' '))
        vec2 = model.get_word_vector(name2.lower().replace('_', ' '))
        
        # 计算余弦相似度
        similarity = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
        return max(0.0, min(1.0, float(similarity)))
        
    except ImportError:
        print("⚠️  需要安装 fasttext: pip install fasttext")
        return 0.0
    except Exception as e:
        print(f"⚠️  FastText 错误: {e}")
        return 0.0


# ==================== 方法4: 混合方法 ====================
def similarity_hybrid(name1: str, name2: str, sbert_model=None) -> float:
    """混合方法：结合字符串匹配和语义相似度
    
    策略：
    - 如果字符串高度相似 (>0.8)，直接返回字符串相似度
    - 否则使用语义相似度
    - 取两者的加权平均
    
    优点：
    - 兼顾拼写相似和语义相似
    - 对缩写和同义词都有效
    
    权重可调：
    - 字符串匹配: 0.3
    - 语义匹配: 0.7
    """
    # 计算字符串相似度
    char_sim = similarity_sequencematcher(name1, name2)
    
    # 如果字符串已经很相似，直接返回
    if char_sim > 0.95:
        return char_sim
    
    # 计算语义相似度
    semantic_sim = similarity_sbert(name1, name2, sbert_model)
    
    # 加权平均
    # 如果字符串相似度很高，给它更大权重
    if char_sim > 0.8:
        weight_char = 0.6
        weight_semantic = 0.4
    else:
        weight_char = 0.3
        weight_semantic = 0.7
    
    return char_sim * weight_char + semantic_sim * weight_semantic


# ==================== 测试用例 ====================
def get_test_cases() -> List[Tuple[str, str, str]]:
    """返回测试用例
    
    Returns:
        List[(word1, word2, 描述)]
    """
    return [
        # 字符串相似的情况
        ("customer_id", "customer_key", "字符串相似但语义不同"),
        ("user_id", "userid", "有无下划线"),
        ("order_date", "order_dt", "常见缩写"),
        
        # 语义相似但字符串不同
        ("customer_id", "client_id", "同义词：customer vs client"),
        ("user_id", "person_id", "同义词：user vs person"),
        ("product_name", "item_name", "同义词：product vs item"),
        ("order_id", "purchase_id", "同义词：order vs purchase"),
        
        # 语义相关但不完全相同
        ("customer_name", "customer_email", "同实体不同属性"),
        ("order_date", "order_amount", "同实体不同属性"),
        
        # 语义完全不同
        ("customer_id", "order_date", "完全不同"),
        ("email", "quantity", "完全不同"),
        
        # 缩写形式
        ("customer_id", "cust_id", "缩写：customer -> cust"),
        ("quantity", "qty", "缩写：quantity -> qty"),
        ("description", "desc", "缩写：description -> desc"),
        
        # 主键/外键常见模式
        ("id", "pk", "主键不同命名"),
        ("id", "key", "主键不同命名"),
        ("user_id", "user_fk", "id vs fk"),
    ]


# ==================== 对比测试 ====================
def compare_all_methods():
    """对比所有方法的效果"""
    print("=" * 100)
    print("语义相似度算法对比测试")
    print("=" * 100)
    
    # 尝试加载 SBERT 模型
    sbert_model = None
    try:
        from sentence_transformers import SentenceTransformer
        print("\n正在加载 Sentence-BERT 模型...")
        sbert_model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✅ 模型加载成功\n")
    except ImportError:
        print("\n⚠️  未安装 sentence-transformers，将跳过 SBERT 和混合方法测试")
        print("   安装命令: pip install sentence-transformers\n")
    except Exception as e:
        print(f"\n⚠️  模型加载失败: {e}\n")
    
    test_cases = get_test_cases()
    
    # 表头
    print(f"{'字段1':<20} {'字段2':<20} {'SequenceMatcher':<15} {'SBERT':<15} {'混合方法':<15} {'描述':<30}")
    print("-" * 120)
    
    results = []
    for word1, word2, description in test_cases:
        # 方法1: SequenceMatcher
        sim_seq = similarity_sequencematcher(word1, word2)
        
        # 方法2: SBERT
        sim_sbert = 0.0
        if sbert_model is not None:
            sim_sbert = similarity_sbert(word1, word2, sbert_model)
        
        # 方法3: 混合
        sim_hybrid = 0.0
        if sbert_model is not None:
            sim_hybrid = similarity_hybrid(word1, word2, sbert_model)
        
        results.append((word1, word2, sim_seq, sim_sbert, sim_hybrid, description))
        
        # 高亮显示差异最大的情况
        diff = abs(sim_seq - sim_sbert) if sbert_model else 0
        marker = "🔥" if diff > 0.3 else "  "
        
        print(f"{marker} {word1:<20} {word2:<20} {sim_seq:<15.4f} {sim_sbert:<15.4f} {sim_hybrid:<15.4f} {description:<30}")
    
    return results


# ==================== 分析和建议 ====================
def analyze_and_recommend():
    """分析各方法优缺点并给出建议"""
    print("\n" + "=" * 100)
    print("方法对比与建议")
    print("=" * 100)
    
    comparison = """
    
    ┌─────────────────────┬─────────────────────┬──────────────────────┬──────────────────────┐
    │      方法           │      优点            │       缺点            │    适用场景          │
    ├─────────────────────┼─────────────────────┼──────────────────────┼──────────────────────┤
    │ SequenceMatcher     │ • 速度快             │ • 无法理解语义        │ • 命名规范严格       │
    │ (当前方法)          │ • 无依赖             │ • 无法识别同义词      │ • 字段名一致性高     │
    │                     │ • 适合缩写           │ • 对 id/key 无效      │ • 对性能要求高       │
    ├─────────────────────┼─────────────────────┼──────────────────────┼──────────────────────┤
    │ Sentence-BERT       │ • 理解语义           │ • 需要额外依赖        │ • 命名规范不统一     │
    │ (推荐)              │ • 识别同义词         │ • 模型加载耗时        │ • 需要识别同义词     │
    │                     │ • 准确度高           │ • 比字符匹配慢        │ • 数据质量重要       │
    │                     │ • 本地运行           │ • 需要22-100MB内存    │                      │
    ├─────────────────────┼─────────────────────┼──────────────────────┼──────────────────────┤
    │ 混合方法            │ • 综合两者优点       │ • 略复杂             │ • 混合场景           │
    │                     │ • 对拼写和语义都好   │ • 需要调参           │ • 中大型项目         │
    │                     │ • 更鲁棒             │                      │                      │
    └─────────────────────┴─────────────────────┴──────────────────────┴──────────────────────┘
    
    
    🎯 针对 metaweave 的建议：
    
    1. 【短期方案 - 增强型 SequenceMatcher】
       保持当前方法，但添加规则：
       • 添加同义词字典 (customer/client, user/person, order/purchase)
       • 添加缩写字典 (qty->quantity, desc->description)
       • 对常见模式特殊处理 (id/key/pk/fk)
       
       优点：无需额外依赖，易实现
       实现复杂度：⭐⭐
    
    2. 【中期方案 - 可选的 SBERT 支持】
       添加配置项，允许用户选择使用 SBERT：
       • 默认使用 SequenceMatcher（向后兼容）
       • 可选启用 SBERT（需要安装依赖）
       • 首次运行自动下载模型
       
       配置示例：
       ```yaml
       relationships:
         name_similarity:
           method: "sbert"  # 或 "sequence_matcher"
           sbert_model: "all-MiniLM-L6-v2"
       ```
       
       优点：灵活，用户可选
       实现复杂度：⭐⭐⭐
    
    3. 【长期方案 - 智能混合方法】
       实现混合方法，自动选择最佳策略：
       • 首次加载尝试加载 SBERT
       • 如果失败，回退到 SequenceMatcher + 规则
       • 根据字段名特征自动选择方法
       
       优点：最智能，效果最好
       实现复杂度：⭐⭐⭐⭐
    
    
    💡 性能考虑：
    
    • SequenceMatcher: ~0.01ms/次
    • SBERT: ~1-5ms/次 (首次加载 ~2秒)
    • 对于 1000 个候选关系的评分：
      - SequenceMatcher: ~10ms
      - SBERT: ~1-5秒
    
    • 解决方案：
      1. 只在候选生成阶段使用语义匹配
      2. 使用缓存避免重复计算
      3. 批量编码提升性能
    
    
    📦 安装指南（Sentence-BERT）：
    
    ```bash
    pip install sentence-transformers
    ```
    
    模型会自动下载到：~/.cache/torch/sentence_transformers/
    首次运行时下载，之后直接使用本地缓存。
    
    推荐模型：
    • all-MiniLM-L6-v2 (22MB, 速度快, 效果好) ⭐⭐⭐⭐⭐
    • paraphrase-MiniLM-L3-v2 (61MB, 更快)
    • all-mpnet-base-v2 (420MB, 效果最好但较慢)
    """
    
    print(comparison)


# ==================== 性能测试 ====================
def benchmark_performance():
    """性能基准测试"""
    print("\n" + "=" * 100)
    print("性能基准测试")
    print("=" * 100)
    
    test_pairs = [
        ("customer_id", "client_id"),
        ("user_name", "username"),
        ("order_date", "purchase_date"),
    ]
    
    iterations = 1000
    
    # 测试 SequenceMatcher
    start = time.time()
    for _ in range(iterations):
        for word1, word2 in test_pairs:
            similarity_sequencematcher(word1, word2)
    time_seq = (time.time() - start) * 1000  # 转换为毫秒
    
    print(f"\nSequenceMatcher:")
    print(f"  总时间: {time_seq:.2f}ms ({iterations * len(test_pairs)} 次)")
    print(f"  平均: {time_seq / (iterations * len(test_pairs)):.4f}ms/次")
    
    # 测试 SBERT
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
        start = time.time()
        for _ in range(iterations):
            for word1, word2 in test_pairs:
                similarity_sbert(word1, word2, model)
        time_sbert = (time.time() - start) * 1000
        
        print(f"\nSentence-BERT:")
        print(f"  总时间: {time_sbert:.2f}ms ({iterations * len(test_pairs)} 次)")
        print(f"  平均: {time_sbert / (iterations * len(test_pairs)):.4f}ms/次")
        print(f"  相对速度: {time_sbert / time_seq:.1f}x 慢")
        
    except ImportError:
        print("\n⚠️  未安装 sentence-transformers，跳过 SBERT 性能测试")


# ==================== 主函数 ====================
def main():
    """运行所有测试"""
    print("\n🔬 语义相似度算法对比测试")
    print("比较不同算法在字段名匹配中的表现\n")
    
    # 对比测试
    results = compare_all_methods()
    
    # 性能测试
    benchmark_performance()
    
    # 分析和建议
    analyze_and_recommend()
    
    print("\n✅ 测试完成！")
    print("\n💡 提示：观察标记为 🔥 的行，这些是 SBERT 相比 SequenceMatcher 提升最明显的案例")


if __name__ == "__main__":
    main()

