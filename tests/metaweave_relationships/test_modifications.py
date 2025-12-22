#!/usr/bin/env python3
"""验证复合键语义角色过滤优化方案的修改"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from src.services.config_loader import ConfigLoader
from src.metaweave.core.metadata.logical_key_detector import LogicalKeyDetector
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator


def test_config_loading():
    """测试配置加载"""
    print("=" * 80)
    print("测试 1: 配置加载")
    print("=" * 80)

    config_path = "configs/metaweave/metadata_config.yaml"
    config_loader = ConfigLoader(config_path)
    config = config_loader.load()

    # 检查 composite.exclude_semantic_roles
    composite_config = config.get("composite", {})
    exclude_roles = composite_config.get("exclude_semantic_roles", [])

    print(f"✅ 配置加载成功")
    print(f"   composite.exclude_semantic_roles = {exclude_roles}")

    # 默认值应该只是 ["metric"]（保守策略）
    assert exclude_roles == ["metric"], f"配置值不正确: {exclude_roles}（应该是 ['metric']）"
    print(f"✅ 配置值正确（默认只排除 metric）")

    return config


def test_logical_key_detector(config):
    """测试逻辑主键检测器"""
    print("\n" + "=" * 80)
    print("测试 2: LogicalKeyDetector 配置读取")
    print("=" * 80)

    # 模拟 generator.py 的配置传递
    logical_key_config = config.get("logical_key_detection", {})

    # 传递 single_column 配置
    single_column_config = config.get("single_column", {})
    single_column_exclude_roles = single_column_config.get("exclude_semantic_roles", ["audit", "metric"])
    logical_key_config["single_column_exclude_roles"] = single_column_exclude_roles

    # 传递 composite 配置
    composite_config = config.get("composite", {})
    # 默认值保守策略：只排除明确不适合的 metric（与 generator.py:114 保持一致）
    composite_exclude_roles = composite_config.get("exclude_semantic_roles", ["metric"])
    logical_key_config["composite_exclude_roles"] = composite_exclude_roles

    # 创建检测器
    detector = LogicalKeyDetector(logical_key_config)

    print(f"✅ LogicalKeyDetector 创建成功")
    print(f"   单列排除角色: {detector.single_column_exclude_roles}")
    print(f"   复合键排除角色: {detector.composite_exclude_roles}")

    # 默认值应该只是 {"metric"}（保守策略）
    assert detector.composite_exclude_roles == {"metric"}, \
        f"复合键排除角色不正确: {detector.composite_exclude_roles}（应该是 {{'metric'}}）"
    print(f"✅ 复合键排除角色正确（默认只排除 metric）")


def test_candidate_generator(config):
    """测试候选生成器"""
    print("\n" + "=" * 80)
    print("测试 3: CandidateGenerator 配置读取")
    print("=" * 80)

    # 创建候选生成器
    fk_signature_set = set()
    generator = CandidateGenerator(config, fk_signature_set)

    print(f"✅ CandidateGenerator 创建成功")
    print(f"   复合键排除角色: {generator.composite_exclude_semantic_roles}")

    # 默认值应该只是 {"metric"}（保守策略）
    assert generator.composite_exclude_semantic_roles == {"metric"}, \
        f"复合键排除角色不正确: {generator.composite_exclude_semantic_roles}（应该是 {{'metric'}}）"
    print(f"✅ 复合键排除角色正确（默认只排除 metric）")


def test_method_signatures():
    """测试方法签名是否正确"""
    print("\n" + "=" * 80)
    print("测试 4: 方法签名验证")
    print("=" * 80)

    from inspect import signature

    # 测试 _match_columns_as_set 方法签名
    sig = signature(CandidateGenerator._match_columns_as_set)
    params = list(sig.parameters.keys())

    print(f"   _match_columns_as_set 参数: {params}")

    assert "source_is_physical" in params, "缺少 source_is_physical 参数"
    assert "target_is_physical" in params, "缺少 target_is_physical 参数"
    print(f"✅ _match_columns_as_set 方法签名正确")

    # 测试 _find_dynamic_same_name 方法签名
    sig = signature(CandidateGenerator._find_dynamic_same_name)
    params = list(sig.parameters.keys())

    print(f"   _find_dynamic_same_name 参数: {params}")

    assert "is_physical" in params, "缺少 is_physical 参数"
    print(f"✅ _find_dynamic_same_name 方法签名正确")


def main():
    """主测试函数"""
    print("\n" + "=" * 80)
    print("复合键语义角色过滤优化方案 - 修改验证")
    print("=" * 80 + "\n")

    try:
        # 测试 1: 配置加载
        config = test_config_loading()

        # 测试 2: LogicalKeyDetector
        test_logical_key_detector(config)

        # 测试 3: CandidateGenerator
        test_candidate_generator(config)

        # 测试 4: 方法签名
        test_method_signatures()

        print("\n" + "=" * 80)
        print("✅ 所有测试通过！修改验证成功！")
        print("=" * 80)

        return 0

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"❌ 测试失败: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
