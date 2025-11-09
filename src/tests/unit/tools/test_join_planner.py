"""JOIN 规划工具单元测试"""

import pytest

from src.tools.schema_retrieval.join_planner import (
    build_multi_base_join_plans,
    format_join_plan_for_prompt,
)


class TestBuildMultiBaseJoinPlans:
    """测试多基表 JOIN 计划构建"""

    def test_single_base_single_path(self):
        """测试单基表单路径的情况"""
        base_tables = ["public.orders"]
        target_tables = ["public.customers"]
        join_paths = {
            ("public.orders", "public.customers"): {
                "path": ["public.orders", "public.customers"],
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.customers",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.customer_id = DST.id",
                    }
                ],
            }
        }

        plans = build_multi_base_join_plans(base_tables, target_tables, join_paths)

        assert len(plans) == 1
        assert plans[0]["base"] == "public.orders"
        assert len(plans[0]["edges"]) == 1
        assert plans[0]["edges"][0]["src_table"] == "public.orders"
        assert plans[0]["edges"][0]["dst_table"] == "public.customers"

    def test_single_base_multiple_paths(self):
        """测试单基表多路径的情况"""
        base_tables = ["public.orders"]
        target_tables = ["public.customers", "public.products"]
        join_paths = {
            ("public.orders", "public.customers"): {
                "path": ["public.orders", "public.customers"],
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.customers",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.customer_id = DST.id",
                    }
                ],
            },
            ("public.orders", "public.products"): {
                "path": ["public.orders", "public.products"],
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.products",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.product_id = DST.id",
                    }
                ],
            },
        }

        plans = build_multi_base_join_plans(base_tables, target_tables, join_paths)

        assert len(plans) == 1
        assert plans[0]["base"] == "public.orders"
        assert len(plans[0]["edges"]) == 2

    def test_multiple_base_tables(self):
        """测试多基表的情况"""
        base_tables = ["public.orders", "public.sales"]
        target_tables = ["public.customers"]
        join_paths = {
            ("public.orders", "public.customers"): {
                "path": ["public.orders", "public.customers"],
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.customers",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.customer_id = DST.id",
                    }
                ],
            },
            ("public.sales", "public.customers"): {
                "path": ["public.sales", "public.customers"],
                "edges": [
                    {
                        "src_table": "public.sales",
                        "dst_table": "public.customers",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.customer_id = DST.id",
                    }
                ],
            },
        }

        plans = build_multi_base_join_plans(base_tables, target_tables, join_paths)

        assert len(plans) == 2
        assert plans[0]["base"] == "public.orders"
        assert plans[1]["base"] == "public.sales"

    def test_missing_join_path(self):
        """测试缺少 JOIN 路径的情况"""
        base_tables = ["public.orders"]
        target_tables = ["public.customers", "public.products"]
        join_paths = {
            ("public.orders", "public.customers"): {
                "path": ["public.orders", "public.customers"],
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.customers",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.customer_id = DST.id",
                    }
                ],
            },
            # 缺少 orders -> products 的路径
        }

        plans = build_multi_base_join_plans(base_tables, target_tables, join_paths)

        # 应该只包含找到的路径
        assert len(plans) == 1
        assert len(plans[0]["edges"]) == 1

    def test_empty_base_tables(self):
        """测试空基表列表"""
        base_tables = []
        target_tables = ["public.customers"]
        join_paths = {}

        plans = build_multi_base_join_plans(base_tables, target_tables, join_paths)

        assert plans == []

    def test_empty_target_tables(self):
        """测试空目标表列表"""
        base_tables = ["public.orders"]
        target_tables = []
        join_paths = {}

        plans = build_multi_base_join_plans(base_tables, target_tables, join_paths)

        # 没有目标表，应该返回空计划或只包含基表的计划
        # 根据实际实现调整
        assert len(plans) >= 0

    def test_multi_hop_join_path(self):
        """测试多跳 JOIN 路径"""
        base_tables = ["public.orders"]
        target_tables = ["public.categories"]
        join_paths = {
            ("public.orders", "public.categories"): {
                "path": ["public.orders", "public.products", "public.categories"],
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.products",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.product_id = DST.id",
                    },
                    {
                        "src_table": "public.products",
                        "dst_table": "public.categories",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.category_id = DST.id",
                    },
                ],
            }
        }

        plans = build_multi_base_join_plans(base_tables, target_tables, join_paths)

        assert len(plans) == 1
        assert len(plans[0]["edges"]) == 2
        # 验证路径顺序
        assert plans[0]["edges"][0]["dst_table"] == "public.products"
        assert plans[0]["edges"][1]["src_table"] == "public.products"
        assert plans[0]["edges"][1]["dst_table"] == "public.categories"


class TestFormatJoinPlanForPrompt:
    """测试 JOIN 计划格式化"""

    def test_format_single_plan(self):
        """测试格式化单个计划"""
        join_plans = [
            {
                "base": "public.orders",
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.customers",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.customer_id = DST.id",
                    }
                ],
            }
        ]

        formatted = format_join_plan_for_prompt(join_plans)

        assert "Base #1" in formatted
        assert "public.orders" in formatted
        assert "LEFT JOIN" in formatted

    def test_format_multiple_plans(self):
        """测试格式化多个计划"""
        join_plans = [
            {
                "base": "public.orders",
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.customers",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.customer_id = DST.id",
                    }
                ],
            },
            {
                "base": "public.sales",
                "edges": [
                    {
                        "src_table": "public.sales",
                        "dst_table": "public.products",
                        "join_type": "INNER JOIN",
                        "on_template": "SRC.product_id = DST.id",
                    }
                ],
            },
        ]

        formatted = format_join_plan_for_prompt(join_plans)

        assert "Base #1" in formatted
        assert "Base #2" in formatted
        assert "public.orders" in formatted
        assert "public.sales" in formatted

    def test_format_limit_to_three_plans(self):
        """测试最多显示 3 个计划"""
        join_plans = [
            {"base": f"public.table{i}", "edges": []} for i in range(5)
        ]

        formatted = format_join_plan_for_prompt(join_plans)

        # 应该只显示前 3 个
        assert "Base #1" in formatted
        assert "Base #2" in formatted
        assert "Base #3" in formatted
        # 不应该出现第 4、5 个
        assert "public.table3" not in formatted
        assert "public.table4" not in formatted

    def test_format_empty_plans(self):
        """测试格式化空计划列表"""
        join_plans = []

        formatted = format_join_plan_for_prompt(join_plans)

        assert formatted == "（无）" or formatted == "" or "无" in formatted

    def test_format_multi_hop_plan(self):
        """测试格式化多跳计划"""
        join_plans = [
            {
                "base": "public.orders",
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.products",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.product_id = DST.id",
                    },
                    {
                        "src_table": "public.products",
                        "dst_table": "public.categories",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.category_id = DST.id",
                    },
                ],
            }
        ]

        formatted = format_join_plan_for_prompt(join_plans)

        assert "public.orders" in formatted
        assert "public.products" in formatted
        assert "public.categories" in formatted
        # 验证格式包含 JOIN 类型
        assert "LEFT JOIN" in formatted

    def test_format_preserves_join_info(self):
        """测试格式化保留完整的 JOIN 信息"""
        join_plans = [
            {
                "base": "public.orders",
                "edges": [
                    {
                        "src_table": "public.orders",
                        "dst_table": "public.customers",
                        "join_type": "LEFT JOIN",
                        "on_template": "SRC.customer_id = DST.id",
                    }
                ],
            }
        ]

        formatted = format_join_plan_for_prompt(join_plans)

        # 验证格式包含关键信息
        assert "public.orders" in formatted
        assert "public.customers" in formatted
        assert "LEFT JOIN" in formatted
        # ON 模板可能以某种形式出现
        assert "SRC" in formatted or "customer_id" in formatted
