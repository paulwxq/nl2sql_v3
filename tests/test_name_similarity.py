"""测试字段名相似度计算

测试使用 metaweave 模块中的 SequenceMatcher 算法计算英文和中文的相似度。
"""

from difflib import SequenceMatcher


def calculate_name_similarity(name1: str, name2: str) -> float:
    """计算列名相似度（与metaweave保持一致）
    
    Args:
        name1: 第一个名称
        name2: 第二个名称
        
    Returns:
        相似度分数 (0-1)，1表示完全相同，0表示完全不同
    """
    if name1.lower() == name2.lower():
        return 1.0
    
    # 使用 SequenceMatcher（Ratcliff/Obershelp 算法）
    return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()


def test_english_similarity():
    """测试英文单词相似度"""
    print("=" * 60)
    print("测试英文单词相似度")
    print("=" * 60)
    
    test_cases = [
        # (word1, word2, 描述)
        ("customer_id", "customer_id", "完全相同"),
        ("customer_id", "Customer_ID", "大小写不同"),
        ("customer_id", "customer_key", "前缀相同，后缀不同"),
        ("customer_id", "cust_id", "缩写形式"),
        ("id", "ID", ""),
        ("customerid", "CustomerID", ""),
        ("customerid", "CustomID", ""),
        ("user_id", "userid", ""),
        ("user_id", "USERID", ""),
        ("user_id", "user_key", ""),
        ("user_id", "userkey", ""),
        ("user_id", "use_id", ""),
        ("user_id", "USER_ID", ""),
        ("customer", "CUSTOMER", ""),
        ("order_date", "order_dt", "日期字段的不同写法"),
        ("product_name", "product_description", "同类字段不同属性"),
        ("user_id", "userid", "有无下划线"),
        ("first_name", "last_name", "相似结构不同含义"),
        ("email", "phone", "完全不同的字段"),
        ("sales_amount", "sales_quantity", "同主题不同指标"),
        ("created_at", "updated_at", "审计字段"),
        ("id", "pk", "完全不同的主键命名"),
    ]
    
    results = []
    for word1, word2, description in test_cases:
        similarity = calculate_name_similarity(word1, word2)
        results.append((word1, word2, similarity, description))
        print(f"\n{description}:")
        print(f"  '{word1}' vs '{word2}'")
        print(f"  相似度: {similarity:.4f}")
    
    return results


def test_chinese_similarity():
    """测试中文字段名相似度"""
    print("\n" + "=" * 60)
    print("测试中文字段名相似度")
    print("=" * 60)
    
    test_cases = [
        # (word1, word2, 描述)
        ("客户编号", "客户编号", "完全相同"),
        ("客户编号", "客户ID", "同义不同表达"),
        ("客户编号", "客户姓名", "同主体不同属性"),
        ("订单日期", "订单金额", "同主体不同属性"),
        ("产品名称", "产品描述", "同主体不同属性"),
        ("创建时间", "更新时间", "时间戳字段"),
        ("用户", "客户", "近义词"),
        ("数量", "金额", "不同的度量"),
        ("省份", "城市", "地理层级"),
        ("商品编码", "商品代码", "同义词"),
    ]
    
    results = []
    for word1, word2, description in test_cases:
        similarity = calculate_name_similarity(word1, word2)
        results.append((word1, word2, similarity, description))
        print(f"\n{description}:")
        print(f"  '{word1}' vs '{word2}'")
        print(f"  相似度: {similarity:.4f}")
    
    return results


def test_mixed_language():
    """测试混合语言（拼音、英文、中文）"""
    print("\n" + "=" * 60)
    print("测试混合语言相似度")
    print("=" * 60)
    
    test_cases = [
        # (word1, word2, 描述)
        ("kehu_id", "customer_id", "拼音 vs 英文"),
        ("订单编号", "order_id", "中文 vs 英文"),
        ("yonghu_name", "用户名称", "拼音 vs 中文"),
        ("product_mc", "product_name", "混合缩写"),
    ]
    
    results = []
    for word1, word2, description in test_cases:
        similarity = calculate_name_similarity(word1, word2)
        results.append((word1, word2, similarity, description))
        print(f"\n{description}:")
        print(f"  '{word1}' vs '{word2}'")
        print(f"  相似度: {similarity:.4f}")
    
    return results


def analyze_results():
    """分析测试结果并给出建议"""
    print("\n" + "=" * 60)
    print("算法特性分析")
    print("=" * 60)
    
    analysis = """
    SequenceMatcher (Ratcliff/Obershelp) 算法特性：
    
    1. 【工作原理】
       - 基于最长公共子序列（LCS）
       - 计算公式: 2 * M / T
         其中 M = 匹配字符数, T = 两个字符串的总字符数
    
    2. 【对英文的效果】✅ 优秀
       - 适合字母拼写相似的单词
       - 能识别缩写、拼写变体
       - 对字符插入、删除、替换敏感度适中
       - 示例:
         * "customer_id" vs "cust_id" → 0.70+ (能识别缩写)
         * "order_date" vs "order_dt" → 0.80+ (能识别常见缩写)
    
    3. 【对中文的效果】⚠️ 有限
       - 基于字符匹配，不理解语义
       - 对同义词无法识别 (如"客户" vs "用户")
       - 只能识别字面上的相似 (如"客户编号" vs "客户ID" → 0.50)
       - 不如专门的中文语义相似度模型
       
    4. 【在 metaweave 场景下的适用性】
       - ✅ 数据库字段名通常是英文或拼音，效果较好
       - ✅ 轻量级，无需外部依赖，速度快
       - ✅ 对命名规范一致的系统效果很好
       - ⚠️ 无法识别语义相似但拼写不同的字段
       - ⚠️ 需要配合其他维度（类型、数据采样）综合判断
    
    5. 【改进建议】
       如果需要更好的语义识别能力：
       - 可以考虑集成词嵌入模型 (Word2Vec, FastText)
       - 使用预训练的句子编码器 (Sentence-BERT)
       - 对于中文，可以使用专门的中文语义模型
       - 但这些方法会增加复杂度和计算成本
    
    6. 【metaweave 的设计理念】
       - 使用多维度评分系统（6个维度）
       - name_similarity 只占权重 0.20 (20%)
       - 更依赖数据采样的实际匹配率 (inclusion_rate 30%)
       - 这种设计弥补了单纯名称相似度的不足
    """
    
    print(analysis)


def main():
    """运行所有测试"""
    print("\n" + "🔬 字段名相似度算法测试")
    print("使用 metaweave 的 SequenceMatcher 方法\n")
    
    # 运行测试
    english_results = test_english_similarity()
    # chinese_results = test_chinese_similarity()
    # mixed_results = test_mixed_language()
    
    # 分析结果
    analyze_results()
    
    # 总结统计
    print("\n" + "=" * 60)
    print("测试统计")
    print("=" * 60)
    print(f"英文测试用例数: {len(english_results)}")
    # print(f"中文测试用例数: {len(chinese_results)}")
    # print(f"混合语言测试用例数: {len(mixed_results)}")
    
    # 找出高相似度和低相似度的案例
    # all_results = english_results + chinese_results + mixed_results
    # high_sim = [r for r in all_results if r[2] > 0.7 and r[2] < 1.0]
    # low_sim = [r for r in all_results if r[2] < 0.3]
    
    # print(f"\n高相似度案例 (>0.7): {len(high_sim)}")
    # for word1, word2, sim, desc in high_sim[:3]:
    #     print(f"  - {word1} vs {word2}: {sim:.4f}")
    
    # print(f"\n低相似度案例 (<0.3): {len(low_sim)}")
    # for word1, word2, sim, desc in low_sim[:3]:
    #     print(f"  - {word1} vs {word2}: {sim:.4f}")
    
    print("\n✅ 测试完成！")


if __name__ == "__main__":
    main()

