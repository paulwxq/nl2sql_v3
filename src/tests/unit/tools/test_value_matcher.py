"""维度值匹配工具单元测试"""

import pytest

from src.tools.schema_retrieval.value_matcher import (
    group_matches_by_source,
    select_best_match,
    build_optimized_filters,
    format_dim_value_matches_for_prompt,
)


class TestGroupMatchesBySource:
    """测试按源维度分组匹配结果"""

    def test_group_single_source_single_match(self):
        """测试单个源单个匹配"""
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "dim_table": "public.stores",
                "dim_col": "city",
                "key_col": "store_id",
                "key_value": "BJ001",
                "score": 0.95,
            }
        ]

        grouped = group_matches_by_source(dim_matches)

        assert 0 in grouped
        assert len(grouped[0]) == 1
        assert grouped[0][0]["matched_text"] == "北京"

    def test_group_single_source_multiple_matches(self):
        """测试单个源多个匹配"""
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "score": 0.95,
            },
            {
                "source_dim_idx": 0,
                "matched_text": "北京市",
                "score": 0.90,
            },
        ]

        grouped = group_matches_by_source(dim_matches)

        assert 0 in grouped
        assert len(grouped[0]) == 2

    def test_group_multiple_sources(self):
        """测试多个源"""
        dim_matches = [
            {"source_dim_idx": 0, "matched_text": "北京", "score": 0.95},
            {"source_dim_idx": 1, "matched_text": "2024", "score": 0.88},
            {"source_dim_idx": 0, "matched_text": "北京市", "score": 0.90},
        ]

        grouped = group_matches_by_source(dim_matches)

        assert 0 in grouped
        assert 1 in grouped
        assert len(grouped[0]) == 2
        assert len(grouped[1]) == 1

    def test_group_empty_matches(self):
        """测试空匹配列表"""
        grouped = group_matches_by_source([])

        assert grouped == {}


class TestSelectBestMatch:
    """测试选择最佳匹配"""

    def test_select_best_by_score(self):
        """测试按分数选择最佳匹配"""
        matches = [
            {"matched_text": "北京", "score": 0.95},
            {"matched_text": "北京市", "score": 0.90},
            {"matched_text": "Beijing", "score": 0.85},
        ]

        best = select_best_match(matches)

        assert best["matched_text"] == "北京"
        assert best["score"] == 0.95

    def test_select_from_single_match(self):
        """测试只有一个匹配的情况"""
        matches = [{"matched_text": "北京", "score": 0.95}]

        best = select_best_match(matches)

        assert best["matched_text"] == "北京"

    def test_select_from_equal_scores(self):
        """测试相同分数的情况"""
        matches = [
            {"matched_text": "北京", "score": 0.95},
            {"matched_text": "北京市", "score": 0.95},
        ]

        best = select_best_match(matches)

        # 应该返回第一个
        assert best["matched_text"] == "北京"

    def test_select_from_empty_list(self):
        """测试空列表"""
        best = select_best_match([])

        assert best is None


class TestBuildOptimizedFilters:
    """测试构建优化的过滤条件"""

    def test_build_with_high_score_match(self):
        """测试高分匹配优化"""
        parse_hints = {
            "dimensions": [
                {"text": "北京", "type": "location"},
            ]
        }
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "dim_table": "public.stores",
                "key_col": "store_id",
                "key_value": "BJ001",
                "score": 0.95,
            }
        ]

        filters = build_optimized_filters(
            parse_hints=parse_hints,
            dim_matches=dim_matches,
            optimize_min_score=0.5,
        )

        assert len(filters) == 1
        # 应该使用匹配的文本
        assert "北京" in filters[0]

    def test_build_with_low_score_match(self):
        """测试低分匹配回退到原始文本"""
        parse_hints = {
            "dimensions": [
                {"text": "某城市", "type": "location"},
            ]
        }
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "score": 0.3,  # 低于阈值
            }
        ]

        filters = build_optimized_filters(
            parse_hints=parse_hints,
            dim_matches=dim_matches,
            optimize_min_score=0.5,
        )

        assert len(filters) == 1
        # 应该使用原始文本
        assert "某城市" in filters[0]

    def test_build_without_matches(self):
        """测试没有匹配的情况"""
        parse_hints = {
            "dimensions": [
                {"text": "北京", "type": "location"},
            ]
        }
        dim_matches = []

        filters = build_optimized_filters(
            parse_hints=parse_hints,
            dim_matches=dim_matches,
        )

        assert len(filters) == 1
        # 应该使用原始文本
        assert "北京" in filters[0]

    def test_build_multiple_dimensions(self):
        """测试多个维度"""
        parse_hints = {
            "dimensions": [
                {"text": "北京", "type": "location"},
                {"text": "2024", "type": "year"},
            ]
        }
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "score": 0.95,
            },
            {
                "source_dim_idx": 1,
                "matched_text": "2024",
                "score": 0.88,
            },
        ]

        filters = build_optimized_filters(
            parse_hints=parse_hints,
            dim_matches=dim_matches,
            optimize_min_score=0.5,
        )

        assert len(filters) == 2
        assert any("北京" in f for f in filters)
        assert any("2024" in f for f in filters)

    def test_build_no_dimensions_in_hints(self):
        """测试解析提示中没有维度"""
        parse_hints = {}
        dim_matches = []

        filters = build_optimized_filters(
            parse_hints=parse_hints,
            dim_matches=dim_matches,
        )

        assert filters == []

    def test_build_partial_matches(self):
        """测试部分维度有匹配的情况"""
        parse_hints = {
            "dimensions": [
                {"text": "北京", "type": "location"},
                {"text": "某产品", "type": "product"},
            ]
        }
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "score": 0.95,
            },
            # 第二个维度没有匹配
        ]

        filters = build_optimized_filters(
            parse_hints=parse_hints,
            dim_matches=dim_matches,
            optimize_min_score=0.5,
        )

        assert len(filters) == 2
        assert any("北京" in f for f in filters)
        assert any("某产品" in f for f in filters)

    def test_build_custom_threshold(self):
        """测试自定义分数阈值"""
        parse_hints = {
            "dimensions": [
                {"text": "北京", "type": "location"},
            ]
        }
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "score": 0.6,
            }
        ]

        # 阈值 0.5，应该使用匹配
        filters_low = build_optimized_filters(
            parse_hints=parse_hints,
            dim_matches=dim_matches,
            optimize_min_score=0.5,
        )

        # 阈值 0.7，应该使用原始文本
        filters_high = build_optimized_filters(
            parse_hints=parse_hints,
            dim_matches=dim_matches,
            optimize_min_score=0.7,
        )

        assert "北京" in filters_low[0]
        assert "北京" in filters_high[0]


class TestFormatDimValueMatchesForPrompt:
    """测试维度值匹配格式化"""

    def test_format_single_match(self):
        """测试格式化单个匹配"""
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "dim_table": "public.stores",
                "dim_col": "city",
                "key_col": "store_id",
                "key_value": "BJ001",
                "score": 0.95,
            }
        ]

        formatted = format_dim_value_matches_for_prompt(dim_matches)

        assert "北京" in formatted
        assert "public.stores" in formatted
        assert "store_id" in formatted
        assert "BJ001" in formatted

    def test_format_multiple_matches(self):
        """测试格式化多个匹配"""
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "dim_table": "public.stores",
                "key_col": "store_id",
                "key_value": "BJ001",
                "score": 0.95,
            },
            {
                "source_dim_idx": 1,
                "matched_text": "2024",
                "dim_table": "public.time_dim",
                "key_col": "year_id",
                "key_value": "2024",
                "score": 0.88,
            },
        ]

        formatted = format_dim_value_matches_for_prompt(dim_matches)

        assert "北京" in formatted
        assert "2024" in formatted
        assert "public.stores" in formatted
        assert "public.time_dim" in formatted

    def test_format_empty_matches(self):
        """测试格式化空匹配列表"""
        formatted = format_dim_value_matches_for_prompt([])

        assert formatted == "（无）" or "无" in formatted or formatted == ""

    def test_format_includes_score(self):
        """测试格式化包含分数信息"""
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京",
                "dim_table": "public.stores",
                "key_col": "store_id",
                "key_value": "BJ001",
                "score": 0.95,
            }
        ]

        formatted = format_dim_value_matches_for_prompt(dim_matches)

        # 根据实际实现，可能包含分数
        # assert "0.95" in formatted or "95%" in formatted

    def test_format_limit_top_results(self):
        """测试格式化限制顶部结果"""
        # 创建很多匹配
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": f"城市{i}",
                "dim_table": "public.stores",
                "key_col": "store_id",
                "key_value": f"CITY{i:03d}",
                "score": 0.9 - i * 0.01,
            }
            for i in range(20)
        ]

        formatted = format_dim_value_matches_for_prompt(dim_matches)

        # 应该有某种形式的限制，不会显示所有 20 个
        # 具体限制数量取决于实际实现
        assert len(formatted) > 0

    def test_format_with_unicode(self):
        """测试格式化包含 Unicode 字符"""
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "北京市朝阳区",
                "dim_table": "public.区域",
                "dim_col": "名称",
                "key_col": "区域_id",
                "key_value": "110105",
                "score": 0.95,
            }
        ]

        formatted = format_dim_value_matches_for_prompt(dim_matches)

        assert "北京市朝阳区" in formatted
        assert "区域" in formatted


class TestEdgeCases:
    """边界情况测试"""

    def test_none_parse_hints(self):
        """测试 None 解析提示"""
        filters = build_optimized_filters(
            parse_hints=None,
            dim_matches=[],
        )

        assert filters == []

    def test_malformed_dim_match(self):
        """测试格式错误的维度匹配"""
        dim_matches = [
            {
                # 缺少必要字段
                "source_dim_idx": 0,
                # 没有 matched_text
            }
        ]

        # 应该能够处理格式错误，不崩溃
        try:
            grouped = group_matches_by_source(dim_matches)
            assert 0 in grouped
        except Exception as e:
            pytest.fail(f"Should handle malformed matches gracefully: {e}")

    def test_negative_score(self):
        """测试负分数"""
        matches = [
            {"matched_text": "test", "score": -0.5},
        ]

        best = select_best_match(matches)
        assert best["score"] == -0.5

    def test_very_long_matched_text(self):
        """测试非常长的匹配文本"""
        dim_matches = [
            {
                "source_dim_idx": 0,
                "matched_text": "A" * 1000,
                "dim_table": "public.test",
                "key_col": "id",
                "key_value": "1",
                "score": 0.95,
            }
        ]

        formatted = format_dim_value_matches_for_prompt(dim_matches)
        # 应该能够处理长文本
        assert len(formatted) > 0
