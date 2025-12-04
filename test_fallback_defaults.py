#!/usr/bin/env python3
"""验证 fallback 默认值是否正确（当 YAML 配置缺失时）"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.metaweave.core.metadata.logical_key_detector import LogicalKeyDetector
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator


def test_logical_key_detector_fallback():
    """测试 LogicalKeyDetector 的 fallback 默认值"""
    print("=" * 80)
    print("测试 1: LogicalKeyDetector fallback 默认值")
    print("=" * 80)

    # 创建一个空配置（模拟 YAML 中没有 composite_exclude_roles）
    config = {
        "min_confidence": 0.8,
        "max_combinations": 3,
        "name_patterns": ["id", "code"],
        # 注意：故意不包含 composite_exclude_roles
    }

    detector = LogicalKeyDetector(config)

    print(f"✅ LogicalKeyDetector 创建成功（使用 fallback）")
    print(f"   复合键排除角色（fallback）: {detector.composite_exclude_roles}")

    # 验证 fallback 是否正确
    assert detector.composite_exclude_roles == {"metric"}, \
        f"❌ Fallback 不正确: {detector.composite_exclude_roles}（应该是 {{'metric'}}）"

    print(f"✅ Fallback 正确：只排除 metric")


def test_candidate_generator_fallback():
    """测试 CandidateGenerator 的 fallback 默认值"""
    print("\n" + "=" * 80)
    print("测试 2: CandidateGenerator fallback 默认值")
    print("=" * 80)

    # 创建一个配置，composite 节点中故意不包含 exclude_semantic_roles
    config = {
        "single_column": {
            "important_constraints": ["single_field_primary_key"],
            "exclude_semantic_roles": ["audit", "metric"],
            "logical_key_min_confidence": 0.8,
            "min_type_compatibility": 0.8,
            "name_similarity_important_target": 0.6,
            "name_similarity_normal_target": 0.9
        },
        "composite": {
            "max_columns": 3,
            "target_sources": [],
            "min_type_compatibility": 0.8,
            "logical_key_min_confidence": 0.8,
            "name_similarity_important_target": 0.6,
            # 注意：故意不包含 exclude_semantic_roles
        }
    }

    fk_signature_set = set()
    generator = CandidateGenerator(config, fk_signature_set)

    print(f"✅ CandidateGenerator 创建成功（使用 fallback）")
    print(f"   复合键排除角色（fallback）: {generator.composite_exclude_semantic_roles}")

    # 验证 fallback 是否正确
    assert generator.composite_exclude_semantic_roles == {"metric"}, \
        f"❌ Fallback 不正确: {generator.composite_exclude_semantic_roles}（应该是 {{'metric'}}）"

    print(f"✅ Fallback 正确：只排除 metric")


def test_test_script_fallback():
    """测试 test_modifications.py 的 fallback 逻辑"""
    print("\n" + "=" * 80)
    print("测试 3: test_modifications.py fallback 逻辑")
    print("=" * 80)

    # 模拟 test_modifications.py 中的逻辑
    config = {
        "composite": {
            # 故意不包含 exclude_semantic_roles
        }
    }

    # 模拟 test_modifications.py:54-56 的逻辑
    composite_config = config.get("composite", {})
    composite_exclude_roles = composite_config.get("exclude_semantic_roles", ["metric"])

    print(f"✅ test_modifications.py fallback 逻辑")
    print(f"   复合键排除角色（fallback）: {composite_exclude_roles}")

    # 验证 fallback 是否正确
    assert composite_exclude_roles == ["metric"], \
        f"❌ Fallback 不正确: {composite_exclude_roles}（应该是 ['metric']）"

    print(f"✅ Fallback 正确：只排除 metric")


def main():
    """主测试函数"""
    print("\n" + "=" * 80)
    print("Fallback 默认值验证测试")
    print("目的：验证当 YAML 配置缺失时，fallback 是否为 ['metric']")
    print("=" * 80 + "\n")

    try:
        # 测试 1: LogicalKeyDetector
        test_logical_key_detector_fallback()

        # 测试 2: CandidateGenerator
        test_candidate_generator_fallback()

        # 测试 3: test_modifications.py 逻辑
        test_test_script_fallback()

        print("\n" + "=" * 80)
        print("✅ 所有 fallback 测试通过！")
        print("   当 YAML 配置缺失时，默认值正确为 ['metric']")
        print("=" * 80)

        return 0

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"❌ Fallback 测试失败: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
