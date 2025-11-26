"""测试RelationshipScorer模块"""

import pytest
from unittest.mock import Mock
from src.metaweave.core.relationships.scorer import RelationshipScorer


class TestRelationshipScorer:
    """RelationshipScorer单元测试"""

    @pytest.fixture
    def mock_connector(self):
        """创建Mock数据库连接器"""
        connector = Mock()
        # Mock execute_query返回字典格式的示例数据
        connector.execute_query.return_value = [
            {"col1": "value1"},
            {"col1": "value2"},
            {"col1": "value3"}
        ]
        return connector

    @pytest.fixture
    def scorer(self, mock_connector):
        """创建Scorer实例"""
        config = {
            "weights": {
                "inclusion_rate": 0.30,
                "jaccard_index": 0.15,
                "uniqueness": 0.10,
                "name_similarity": 0.20,
                "type_compatibility": 0.20,
                "semantic_role_bonus": 0.05
            }
        }
        return RelationshipScorer(config, mock_connector)

    def test_calculate_name_similarity(self, scorer):
        """测试列名相似度计算"""
        # 完全相同
        score = scorer._calculate_name_similarity(["store_id"], ["store_id"])
        assert score == 1.0

        # 不同的列名
        score = scorer._calculate_name_similarity(["user_id"], ["company_id"])
        assert 0.0 <= score < 1.0

        # 复合键
        score = scorer._calculate_name_similarity(
            ["store_id", "date_day"],
            ["store_id", "date_day"]
        )
        assert score == 1.0

    def test_calculate_type_compatibility(self, scorer):
        """测试类型兼容性计算"""
        source_columns = ["store_id"]
        target_columns = ["store_id"]

        source_profiles = {
            "store_id": {"data_type": "integer"}
        }

        target_profiles = {
            "store_id": {"data_type": "integer"}
        }

        score = scorer._calculate_type_compatibility(
            source_columns, source_profiles,
            target_columns, target_profiles
        )
        assert score == 1.0  # 完全相同类型

    def test_calculate_avg_uniqueness(self, scorer):
        """测试平均唯一性计算"""
        columns = ["store_id"]
        profiles = {
            "store_id": {
                "statistics": {
                    "uniqueness": 0.1
                }
            }
        }

        score = scorer._calculate_avg_uniqueness(columns, profiles)
        assert abs(score - 0.1) < 0.01

    def test_semantic_role_bonus(self, scorer):
        """测试语义角色加分"""
        columns = ["store_id"]

        # identifier角色应该有加分
        profiles = {
            "store_id": {
                "semantic_analysis": {
                    "semantic_role": "identifier"
                }
            }
        }

        bonus = scorer._calculate_semantic_role_bonus(columns, profiles)
        assert bonus == 1.0  # 全部是identifier

        # 非identifier角色
        profiles["store_id"]["semantic_analysis"]["semantic_role"] = "metric"
        bonus = scorer._calculate_semantic_role_bonus(columns, profiles)
        assert bonus == 0.0

    def test_extract_value_set_single_column(self, scorer):
        """测试单列值集合提取"""
        rows = [
            {"col1": "value1"},
            {"col1": "value2"},
            {"col1": "value1"},  # 重复
            {"col1": None}        # NULL值
        ]
        columns = ["col1"]

        value_set = scorer._extract_value_set(rows, columns)

        # 应该去重且排除None
        assert len(value_set) == 2
        assert ("value1",) in value_set
        assert ("value2",) in value_set

    def test_extract_value_set_composite_columns(self, scorer):
        """测试复合列值集合提取"""
        rows = [
            {"col1": "val1", "col2": "val2"},
            {"col1": "val3", "col2": "val4"},
            {"col1": "val1", "col2": "val2"},  # 重复
            {"col1": None, "col2": "val5"},    # 包含None
        ]
        columns = ["col1", "col2"]

        value_set = scorer._extract_value_set(rows, columns)

        # 应该去重且排除包含None的行
        assert len(value_set) == 2
        assert ("val1", "val2") in value_set
        assert ("val3", "val4") in value_set

    def test_get_type_compatibility_integer_types(self, scorer):
        """测试整数类型族兼容性"""
        # 整数类型互相兼容
        compat = scorer._get_type_compatibility("integer", "bigint")
        assert compat == 1.0

        # 整数与数值类型部分兼容
        compat = scorer._get_type_compatibility("integer", "numeric")
        assert compat == 0.6

    def test_normalize_type(self, scorer):
        """测试类型标准化"""
        # 去除precision
        normalized = scorer._normalize_type("numeric(10,2)")
        assert normalized == "numeric"

        # 转小写
        normalized = scorer._normalize_type("VARCHAR")
        assert normalized == "varchar"
