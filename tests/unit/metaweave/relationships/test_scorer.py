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
        """创建Scorer实例（4维度评分体系）"""
        config = {
            "weights": {
                "inclusion_rate": 0.55,
                "name_similarity": 0.20,
                "type_compatibility": 0.15,
                "jaccard_index": 0.10
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

    def test_extract_value_set_single_column(self, scorer):
        """测试单列值集合提取"""
        rows = [
            {"col1": "value1"},
            {"col1": "value2"},
            {"col1": "value1"},  # 重复
            {"col1": None}        # NULL值
        ]
        columns = ["col1"]

        value_set, valid_count = scorer._extract_value_set(rows, columns)

        # 应该去重且排除None
        assert len(value_set) == 2
        assert ("value1",) in value_set
        assert ("value2",) in value_set
        # valid_count 应该是排除 None 后的行数（3行有效）
        assert valid_count == 3

    def test_extract_value_set_composite_columns(self, scorer):
        """测试复合列值集合提取"""
        rows = [
            {"col1": "val1", "col2": "val2"},
            {"col1": "val3", "col2": "val4"},
            {"col1": "val1", "col2": "val2"},  # 重复
            {"col1": None, "col2": "val5"},    # 包含None
        ]
        columns = ["col1", "col2"]

        value_set, valid_count = scorer._extract_value_set(rows, columns)

        # 应该去重且排除包含None的行
        assert len(value_set) == 2
        assert ("val1", "val2") in value_set
        assert ("val3", "val4") in value_set
        # valid_count 应该是排除含 None 行后的有效行数（3行有效，含1行重复）
        assert valid_count == 3

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

    def test_calculate_cardinality_one_to_one(self, scorer):
        """测试基数计算 - 1:1（双方高唯一）"""
        cardinality = scorer._calculate_cardinality(
            source_uniqueness=0.98,
            target_uniqueness=0.97,
            join_multiplicity=1.0
        )
        assert cardinality == "1:1"

    def test_calculate_cardinality_one_to_many(self, scorer):
        """测试基数计算 - 1:N（源唯一，目标重复）"""
        cardinality = scorer._calculate_cardinality(
            source_uniqueness=0.99,
            target_uniqueness=0.5,
            join_multiplicity=2.5
        )
        assert cardinality == "1:N"

    def test_calculate_cardinality_many_to_one(self, scorer):
        """测试基数计算 - N:1（源重复，目标唯一）"""
        cardinality = scorer._calculate_cardinality(
            source_uniqueness=0.3,
            target_uniqueness=0.99,
            join_multiplicity=0.8
        )
        assert cardinality == "N:1"

    def test_calculate_cardinality_many_to_many(self, scorer):
        """测试基数计算 - M:N（双方都不唯一，高倍率）"""
        cardinality = scorer._calculate_cardinality(
            source_uniqueness=0.5,
            target_uniqueness=0.5,
            join_multiplicity=3.0
        )
        assert cardinality == "M:N"

    def test_calculate_cardinality_boundary_case(self, scorer):
        """测试基数计算 - 边界情况（唯一性在 [0.8, 0.95) 区间）"""
        # 唯一性在边界区间，倍率接近 1 → 依据唯一性比较判断
        cardinality = scorer._calculate_cardinality(
            source_uniqueness=0.88,
            target_uniqueness=0.85,
            join_multiplicity=1.05
        )
        # source 更唯一，且倍率 ≈ 1 → 1:1
        assert cardinality == "1:1"

        # 唯一性在边界区间，倍率 > 1.5 且源较唯一 → 1:N
        cardinality = scorer._calculate_cardinality(
            source_uniqueness=0.88,
            target_uniqueness=0.60,
            join_multiplicity=1.8
        )
        assert cardinality == "1:N"
