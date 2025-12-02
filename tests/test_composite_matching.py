"""测试复合键匹配的穷举排列算法"""
import sys
sys.path.insert(0, '/mnt/c/Projects/cursor_2025h2/nl2sql_v3')

import json
from pathlib import Path
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator
from src.services.config_loader import ConfigLoader

# 加载 metaweave 配置文件（包含关系发现配置）
config_loader = ConfigLoader('configs/metaweave/metadata_config.yaml')
config = config_loader.load()

# 创建候选生成器实例
generator = CandidateGenerator(config, set())

print("=" * 80)
print("复合键匹配穷举排列算法测试")
print("=" * 80)

# ============================================================================
# 测试用例 1: 完美匹配（列名和类型完全一致）
# ============================================================================
print("\n【测试1】完美匹配 - 列名和类型完全一致")
print("-" * 80)

source_columns_1 = ["store_id", "product_type_id"]
target_columns_1 = ["store_id", "product_type_id"]

source_profiles_1 = {
    "store_id": {"data_type": "integer"},
    "product_type_id": {"data_type": "integer"}
}
target_profiles_1 = {
    "store_id": {"data_type": "integer"},
    "product_type_id": {"data_type": "integer"}
}

result_1 = generator._match_columns_as_set(
    source_columns=source_columns_1,
    target_columns=target_columns_1,
    source_profiles=source_profiles_1,
    target_profiles=target_profiles_1,
    min_name_similarity=0.6,
    min_type_compatibility=0.8
)

print(f"源列: {source_columns_1}")
print(f"目标列池: {target_columns_1}")
print(f"匹配结果: {result_1}")
print(f"✅ 预期: {target_columns_1}")
print(f"{'✅ 通过' if result_1 == target_columns_1 else '❌ 失败'}")

# ============================================================================
# 测试用例 2: 需要排列 - 列名相似但顺序不同
# ============================================================================
print("\n【测试2】需要排列 - 列名相似但顺序不同")
print("-" * 80)

source_columns_2 = ["company_id", "region_id"]
target_columns_2 = ["region_id", "company_id"]  # 顺序相反

source_profiles_2 = {
    "company_id": {"data_type": "integer"},
    "region_id": {"data_type": "integer"}
}
target_profiles_2 = {
    "region_id": {"data_type": "integer"},
    "company_id": {"data_type": "integer"}
}

result_2 = generator._match_columns_as_set(
    source_columns=source_columns_2,
    target_columns=target_columns_2,
    source_profiles=source_profiles_2,
    target_profiles=target_profiles_2,
    min_name_similarity=0.6,
    min_type_compatibility=0.8
)

print(f"源列: {source_columns_2}")
print(f"目标列池: {target_columns_2}")
print(f"匹配结果: {result_2}")
# 应该找到正确的排列 [company_id, region_id]
expected_2 = ["company_id", "region_id"]
print(f"✅ 预期: {expected_2}")
print(f"{'✅ 通过' if result_2 == expected_2 else '❌ 失败'}")

# ============================================================================
# 测试用例 3: 三列排列 - 测试 O(n! × n) 复杂度
# ============================================================================
print("\n【测试3】三列排列 - 测试穷举所有6种排列")
print("-" * 80)

source_columns_3 = ["col_a", "col_b", "col_c"]
# 目标列顺序完全打乱
target_columns_3 = ["col_c", "col_a", "col_b"]

source_profiles_3 = {
    "col_a": {"data_type": "integer"},
    "col_b": {"data_type": "varchar"},
    "col_c": {"data_type": "bigint"}
}
target_profiles_3 = {
    "col_c": {"data_type": "bigint"},
    "col_a": {"data_type": "integer"},
    "col_b": {"data_type": "varchar"}
}

result_3 = generator._match_columns_as_set(
    source_columns=source_columns_3,
    target_columns=target_columns_3,
    source_profiles=source_profiles_3,
    target_profiles=target_profiles_3,
    min_name_similarity=0.6,
    min_type_compatibility=0.8
)

print(f"源列: {source_columns_3}")
print(f"目标列池: {target_columns_3}")
print(f"匹配结果: {result_3}")
# 应该找到正确的排列 [col_a, col_b, col_c]
expected_3 = ["col_a", "col_b", "col_c"]
print(f"✅ 预期: {expected_3}")
print(f"{'✅ 通过' if result_3 == expected_3 else '❌ 失败'}")

# ============================================================================
# 测试用例 4: 单列低于阈值 - 应该拒绝整个排列
# ============================================================================
print("\n【测试4】单列低于阈值 - 任一配对失败应拒绝整个排列")
print("-" * 80)

source_columns_4 = ["id_field", "name_field"]
target_columns_4 = ["id_field", "description_field"]  # name vs description 相似度很低

source_profiles_4 = {
    "id_field": {"data_type": "integer"},
    "name_field": {"data_type": "varchar"}
}
target_profiles_4 = {
    "id_field": {"data_type": "integer"},
    "description_field": {"data_type": "varchar"}
}

result_4 = generator._match_columns_as_set(
    source_columns=source_columns_4,
    target_columns=target_columns_4,
    source_profiles=source_profiles_4,
    target_profiles=target_profiles_4,
    min_name_similarity=0.6,  # name_field vs description_field 相似度应该 < 0.6
    min_type_compatibility=0.8
)

print(f"源列: {source_columns_4}")
print(f"目标列池: {target_columns_4}")
print(f"匹配结果: {result_4}")
print(f"✅ 预期: None (因为 name_field vs description_field 相似度低)")
print(f"{'✅ 通过' if result_4 is None else '❌ 失败'}")

# ============================================================================
# 测试用例 5: 类型不兼容 - 拒绝类型兼容性低的配对
# ============================================================================
print("\n【测试5】类型不兼容 - 拒绝类型兼容性低的配对")
print("-" * 80)

source_columns_5 = ["id_num", "date_field"]
target_columns_5 = ["id_num", "date_field"]

source_profiles_5 = {
    "id_num": {"data_type": "integer"},
    "date_field": {"data_type": "date"}
}
target_profiles_5 = {
    "id_num": {"data_type": "integer"},
    "date_field": {"data_type": "varchar"}  # date vs varchar 不兼容
}

result_5 = generator._match_columns_as_set(
    source_columns=source_columns_5,
    target_columns=target_columns_5,
    source_profiles=source_profiles_5,
    target_profiles=target_profiles_5,
    min_name_similarity=0.6,
    min_type_compatibility=0.8  # date vs varchar 类型兼容性应该 < 0.8
)

print(f"源列: {source_columns_5}")
print(f"目标列池: {target_columns_5}")
print(f"匹配结果: {result_5}")
print(f"✅ 预期: None (因为 date vs varchar 类型不兼容)")
print(f"{'✅ 通过' if result_5 is None else '❌ 失败'}")

# ============================================================================
# 测试用例 6: 最佳排列选择 - 多个排列都合格，选得分最高的
# ============================================================================
print("\n【测试6】最佳排列选择 - 选择综合得分最高的排列")
print("-" * 80)

source_columns_6 = ["user_id", "item_id"]
# 目标有两列名称相似，但一个更接近
target_columns_6 = ["user_key", "item_code"]

source_profiles_6 = {
    "user_id": {"data_type": "integer"},
    "item_id": {"data_type": "integer"}
}
target_profiles_6 = {
    "user_key": {"data_type": "integer"},  # user_id vs user_key 相似度高
    "item_code": {"data_type": "integer"}  # item_id vs item_code 相似度中等
}

result_6 = generator._match_columns_as_set(
    source_columns=source_columns_6,
    target_columns=target_columns_6,
    source_profiles=source_profiles_6,
    target_profiles=target_profiles_6,
    min_name_similarity=0.3,  # 降低阈值以便测试排列选择
    min_type_compatibility=0.8
)

print(f"源列: {source_columns_6}")
print(f"目标列池: {target_columns_6}")
print(f"匹配结果: {result_6}")
# 应该匹配到最佳排列
expected_6 = ["user_key", "item_code"]
print(f"✅ 预期: {expected_6}")
print(f"{'✅ 通过' if result_6 == expected_6 else '❌ 失败'}")

# ============================================================================
# 测试用例 7: 整数类型族兼容性
# ============================================================================
print("\n【测试7】整数类型族兼容性 - integer vs bigint 应兼容")
print("-" * 80)

source_columns_7 = ["id1", "id2"]
target_columns_7 = ["id1", "id2"]

source_profiles_7 = {
    "id1": {"data_type": "integer"},
    "id2": {"data_type": "smallint"}
}
target_profiles_7 = {
    "id1": {"data_type": "bigint"},
    "id2": {"data_type": "int8"}
}

result_7 = generator._match_columns_as_set(
    source_columns=source_columns_7,
    target_columns=target_columns_7,
    source_profiles=source_profiles_7,
    target_profiles=target_profiles_7,
    min_name_similarity=0.6,
    min_type_compatibility=0.8
)

print(f"源列: {source_columns_7}")
print(f"目标列池: {target_columns_7}")
print(f"匹配结果: {result_7}")
print(f"✅ 预期: {target_columns_7} (整数类型族应该兼容)")
print(f"{'✅ 通过' if result_7 == target_columns_7 else '❌ 失败'}")

# ============================================================================
# 测试用例 8: 列数不匹配 - 应该返回 None
# ============================================================================
print("\n【测试8】列数不匹配 - 源列3个，目标列2个")
print("-" * 80)

source_columns_8 = ["col_a", "col_b", "col_c"]
target_columns_8 = ["col_a", "col_b"]  # 只有2列

source_profiles_8 = {
    "col_a": {"data_type": "integer"},
    "col_b": {"data_type": "integer"},
    "col_c": {"data_type": "integer"}
}
target_profiles_8 = {
    "col_a": {"data_type": "integer"},
    "col_b": {"data_type": "integer"}
}

result_8 = generator._match_columns_as_set(
    source_columns=source_columns_8,
    target_columns=target_columns_8,
    source_profiles=source_profiles_8,
    target_profiles=target_profiles_8,
    min_name_similarity=0.6,
    min_type_compatibility=0.8
)

print(f"源列: {source_columns_8}")
print(f"目标列池: {target_columns_8}")
print(f"匹配结果: {result_8}")
print(f"✅ 预期: None (列数不匹配)")
print(f"{'✅ 通过' if result_8 is None else '❌ 失败'}")

# ============================================================================
# 总结
# ============================================================================
print("\n" + "=" * 80)
print("测试总结")
print("=" * 80)
print("✅ 以上测试用例验证了穷举排列算法的核心功能：")
print("  1. 完美匹配场景")
print("  2. 列顺序打乱的排列搜索")
print("  3. 三列排列的O(n! × n)算法")
print("  4. 任一列低于阈值立即拒绝（关键修复）")
print("  5. 类型不兼容拒绝")
print("  6. 多个合格排列中选最佳")
print("  7. 类型族兼容性")
print("  8. 边界条件处理")
