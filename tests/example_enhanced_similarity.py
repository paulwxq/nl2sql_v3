"""增强型字段名相似度实现示例

演示如何在 metaweave 中集成更好的相似度算法。
包含三种实现方案供参考。
"""

from difflib import SequenceMatcher
from typing import Optional, Dict, List, Set
import logging

# ============================================================================
# 方案1: 增强型规则方法（推荐 - 无需额外依赖）
# ============================================================================

class EnhancedSequenceMatcher:
    """增强型字符串匹配器
    
    在 SequenceMatcher 基础上增加：
    1. 同义词词典
    2. 缩写词典
    3. 领域特定规则
    """
    
    # 数据库字段常见同义词
    SYNONYMS = {
        'customer': {'client', 'cust', 'consumer'},
        'user': {'person', 'usr', 'member'},
        'product': {'item', 'prod', 'goods'},
        'order': {'purchase', 'transaction'},
        'quantity': {'qty', 'amount', 'count'},
        'description': {'desc', 'descr'},
        'identifier': {'id', 'key', 'pk', 'fk'},
        'name': {'title', 'label'},
        'date': {'dt', 'time', 'timestamp'},
        'number': {'num', 'no', 'nbr'},
        'address': {'addr', 'location'},
        'email': {'mail', 'e_mail'},
        'phone': {'tel', 'telephone', 'mobile'},
        'price': {'cost', 'amount'},
        'status': {'state', 'flag'},
    }
    
    # 构建反向索引
    _synonym_map = {}
    for base, variants in SYNONYMS.items():
        _synonym_map[base] = base
        for variant in variants:
            _synonym_map[variant] = base
    
    def __init__(self, min_boost: float = 0.8):
        """初始化
        
        Args:
            min_boost: 检测到同义词时的最小相似度提升值
        """
        self.min_boost = min_boost
    
    def similarity(self, name1: str, name2: str) -> float:
        """计算增强型相似度
        
        Args:
            name1: 字段名1
            name2: 字段名2
            
        Returns:
            相似度 (0-1)
        """
        if name1.lower() == name2.lower():
            return 1.0
        
        # 1. 基础字符串相似度
        base_sim = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
        
        # 2. 检查同义词
        synonym_boost = self._check_synonyms(name1, name2)
        
        # 3. 检查常见模式
        pattern_boost = self._check_patterns(name1, name2)
        
        # 取最大值
        final_sim = max(base_sim, synonym_boost, pattern_boost)
        
        return final_sim
    
    def _check_synonyms(self, name1: str, name2: str) -> float:
        """检查同义词关系
        
        Args:
            name1: 字段名1
            name2: 字段名2
            
        Returns:
            同义词相似度
        """
        # 提取单词（按 _ 分割）
        words1 = set(name1.lower().split('_'))
        words2 = set(name2.lower().split('_'))
        
        # 标准化为基础词
        normalized1 = {self._synonym_map.get(w, w) for w in words1}
        normalized2 = {self._synonym_map.get(w, w) for w in words2}
        
        # 计算交集
        common = normalized1 & normalized2
        
        if not common:
            return 0.0
        
        # 如果有公共的标准化词，给予较高的相似度
        jaccard = len(common) / len(normalized1 | normalized2)
        
        # 如果所有词都匹配，返回高分
        if normalized1 == normalized2:
            return self.min_boost
        
        # 部分匹配，按 Jaccard 相似度计算
        return jaccard * self.min_boost
    
    def _check_patterns(self, name1: str, name2: str) -> float:
        """检查常见模式
        
        Args:
            name1: 字段名1
            name2: 字段名2
            
        Returns:
            模式相似度
        """
        n1_lower = name1.lower()
        n2_lower = name2.lower()
        
        # 主键/外键模式
        pk_fk_patterns = [
            ('_id', '_key'),
            ('_id', '_pk'),
            ('_id', '_fk'),
            ('_key', '_pk'),
            ('id', 'pk'),
            ('id', 'key'),
        ]
        
        for pattern1, pattern2 in pk_fk_patterns:
            if ((pattern1 in n1_lower and pattern2 in n2_lower) or
                (pattern2 in n1_lower and pattern1 in n2_lower)):
                # 检查前缀是否相同
                prefix1 = n1_lower.replace(pattern1, '')
                prefix2 = n2_lower.replace(pattern2, '')
                if prefix1 == prefix2:
                    return 0.85  # 高相似度
        
        return 0.0


# ============================================================================
# 方案2: Sentence-BERT 集成（可选依赖）
# ============================================================================

class SBERTSimilarity:
    """基于 Sentence-BERT 的语义相似度
    
    需要安装: pip install sentence-transformers
    """
    
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        """初始化
        
        Args:
            model_name: SBERT 模型名称
        """
        try:
            from sentence_transformers import SentenceTransformer, util
            self.model = SentenceTransformer(model_name)
            self.util = util
            self.available = True
        except ImportError:
            logging.warning("sentence-transformers 未安装，无法使用 SBERT 语义匹配")
            self.available = False
    
    def similarity(self, name1: str, name2: str) -> float:
        """计算语义相似度
        
        Args:
            name1: 字段名1
            name2: 字段名2
            
        Returns:
            相似度 (0-1)
        """
        if not self.available:
            return 0.0
        
        if name1.lower() == name2.lower():
            return 1.0
        
        # 预处理：下划线转空格
        text1 = name1.replace('_', ' ')
        text2 = name2.replace('_', ' ')
        
        # 编码
        embeddings1 = self.model.encode([text1], convert_to_tensor=True)
        embeddings2 = self.model.encode([text2], convert_to_tensor=True)
        
        # 计算余弦相似度
        similarity = self.util.cos_sim(embeddings1, embeddings2).item()
        
        return max(0.0, min(1.0, similarity))


# ============================================================================
# 方案3: 混合方法（推荐用于生产环境）
# ============================================================================

class HybridSimilarity:
    """混合相似度计算器
    
    自动选择最佳方法：
    - 如果安装了 sentence-transformers，使用 SBERT
    - 否则使用增强型 SequenceMatcher
    """
    
    def __init__(
        self,
        use_sbert: bool = True,
        sbert_weight: float = 0.7,
        char_weight: float = 0.3
    ):
        """初始化
        
        Args:
            use_sbert: 是否尝试使用 SBERT
            sbert_weight: SBERT 权重
            char_weight: 字符匹配权重
        """
        self.enhanced_matcher = EnhancedSequenceMatcher()
        self.sbert = None
        self.sbert_weight = sbert_weight
        self.char_weight = char_weight
        
        if use_sbert:
            try:
                self.sbert = SBERTSimilarity()
                if self.sbert.available:
                    logging.info("✅ SBERT 语义匹配已启用")
                else:
                    logging.info("⚠️  SBERT 不可用，使用增强型字符匹配")
            except Exception as e:
                logging.warning(f"无法加载 SBERT: {e}")
    
    def similarity(self, name1: str, name2: str) -> float:
        """计算混合相似度
        
        Args:
            name1: 字段名1
            name2: 字段名2
            
        Returns:
            相似度 (0-1)
        """
        if name1.lower() == name2.lower():
            return 1.0
        
        # 增强型字符匹配
        char_sim = self.enhanced_matcher.similarity(name1, name2)
        
        # 如果字符相似度已经很高，直接返回
        if char_sim > 0.95:
            return char_sim
        
        # 如果有 SBERT，计算语义相似度
        if self.sbert and self.sbert.available:
            semantic_sim = self.sbert.similarity(name1, name2)
            
            # 动态权重：字符相似度越高，字符匹配权重越大
            if char_sim > 0.8:
                w_char = 0.6
                w_semantic = 0.4
            else:
                w_char = self.char_weight
                w_semantic = self.sbert_weight
            
            return char_sim * w_char + semantic_sim * w_semantic
        
        # 否则只用增强型字符匹配
        return char_sim


# ============================================================================
# 在 metaweave 中的集成示例
# ============================================================================

def demo_integration():
    """演示如何在 metaweave 中集成"""
    
    print("=" * 80)
    print("集成方案对比")
    print("=" * 80)
    
    test_cases = [
        ("customer_id", "client_id"),
        ("user_id", "person_id"),
        ("product_name", "item_name"),
        ("order_id", "purchase_id"),
        ("quantity", "qty"),
        ("id", "pk"),
        ("user_id", "user_fk"),
    ]
    
    # 初始化各种方法
    original = lambda n1, n2: SequenceMatcher(None, n1.lower(), n2.lower()).ratio()
    enhanced = EnhancedSequenceMatcher()
    hybrid = HybridSimilarity(use_sbert=False)  # 先不用SBERT演示
    
    print(f"\n{'字段1':<20} {'字段2':<20} {'原始':<10} {'增强':<10} {'混合':<10}")
    print("-" * 70)
    
    for name1, name2 in test_cases:
        sim_orig = original(name1, name2)
        sim_enhanced = enhanced.similarity(name1, name2)
        sim_hybrid = hybrid.similarity(name1, name2)
        
        print(f"{name1:<20} {name2:<20} {sim_orig:<10.3f} {sim_enhanced:<10.3f} {sim_hybrid:<10.3f}")
    
    print("\n" + "=" * 80)
    print("集成建议")
    print("=" * 80)
    
    integration_guide = """
    
    🔧 如何在 metaweave 中集成：
    
    1. 修改配置文件支持方法选择
       --------------------------------
       在 config.yaml 中添加：
       
       relationships:
         name_similarity:
           method: "hybrid"  # 可选: "sequence_matcher", "enhanced", "sbert", "hybrid"
           sbert_model: "all-MiniLM-L6-v2"
           weights:
             char: 0.3
             semantic: 0.7
    
    2. 修改 scorer.py
       --------------------------------
       在 RelationshipScorer.__init__ 中：
       
       # 初始化相似度计算器
       sim_config = config.get("name_similarity", {})
       method = sim_config.get("method", "sequence_matcher")
       
       if method == "hybrid":
           self.similarity_calculator = HybridSimilarity(
               use_sbert=sim_config.get("use_sbert", True),
               sbert_weight=sim_config.get("weights", {}).get("semantic", 0.7),
               char_weight=sim_config.get("weights", {}).get("char", 0.3)
           )
       elif method == "enhanced":
           self.similarity_calculator = EnhancedSequenceMatcher()
       elif method == "sbert":
           self.similarity_calculator = SBERTSimilarity(
               model_name=sim_config.get("sbert_model", "all-MiniLM-L6-v2")
           )
       else:  # sequence_matcher
           self.similarity_calculator = None  # 使用原有实现
    
    3. 修改 _calculate_name_similarity 方法
       --------------------------------
       def _calculate_name_similarity(self, source_columns, target_columns):
           if len(source_columns) != len(target_columns):
               return 0.0
           
           total_sim = 0
           for src_col, tgt_col in zip(source_columns, target_columns):
               if self.similarity_calculator:
                   # 使用新的相似度计算器
                   sim = self.similarity_calculator.similarity(src_col, tgt_col)
               else:
                   # 原有实现（向后兼容）
                   if src_col == tgt_col:
                       sim = 1.0
                   else:
                       sim = SequenceMatcher(None, src_col.lower(), tgt_col.lower()).ratio()
               
               total_sim += sim
           
           return total_sim / len(source_columns)
    
    4. 同样修改 candidate_generator.py
       --------------------------------
       在 CandidateGenerator 中也使用相同的相似度计算器
    
    
    ✅ 优势：
    - 向后兼容（默认使用原方法）
    - 可配置（用户可选择方法）
    - 渐进式升级（可以先试用再决定）
    - 性能可控（可以只在关键路径使用）
    
    
    📊 性能建议：
    
    - 小规模数据库（< 100 张表）：使用 hybrid 方法
    - 中等规模（100-500 张表）：使用 enhanced 方法
    - 大规模（> 500 张表）：使用 sequence_matcher + 缓存
    """
    
    print(integration_guide)


# ============================================================================
# 主函数
# ============================================================================

def main():
    """运行演示"""
    print("\n🔬 增强型字段名相似度实现示例\n")
    
    demo_integration()
    
    print("\n✅ 演示完成！")
    print("\n💡 提示：")
    print("  - 方案1（增强型规则）：无需安装依赖，立即可用")
    print("  - 方案2（SBERT）：需要 pip install sentence-transformers")
    print("  - 方案3（混合）：自动选择最佳方案（推荐）")


if __name__ == "__main__":
    main()

