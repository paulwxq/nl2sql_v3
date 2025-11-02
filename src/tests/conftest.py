"""Pytest 配置和共享 fixtures"""

import os
import sys
from pathlib import Path

import pytest

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def project_root_path():
    """返回项目根目录路径"""
    return project_root


@pytest.fixture(scope="session")
def test_config_path(project_root_path):
    """返回测试配置文件路径"""
    return project_root_path / "src" / "configs" / "config.yaml"


@pytest.fixture
def mock_env_vars(monkeypatch):
    """设置模拟环境变量"""
    test_env = {
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "testdb",
        "DB_USER": "testuser",
        "DB_PASSWORD": "testpass",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "testpass",
        "DASHSCOPE_API_KEY": "test-api-key",
    }

    for key, value in test_env.items():
        monkeypatch.setenv(key, value)

    return test_env


@pytest.fixture
def sample_schema_context():
    """返回示例 Schema 上下文"""
    return {
        "tables": ["public.orders", "public.customers", "public.products"],
        "columns": [
            {
                "table": "public.orders",
                "column": "id",
                "data_type": "integer",
            },
            {
                "table": "public.orders",
                "column": "customer_id",
                "data_type": "integer",
            },
            {
                "table": "public.orders",
                "column": "amount",
                "data_type": "numeric",
            },
        ],
        "join_plans": [
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
        ],
        "table_cards": {
            "public.orders": {
                "text_raw": "订单表 id:INTEGER customer_id:INTEGER amount:NUMERIC order_date:DATE",
                "time_col_hint": "order_date",
                "table_category": "fact",
            },
            "public.customers": {
                "text_raw": "客户表 id:INTEGER name:VARCHAR city:VARCHAR",
                "table_category": "dimension",
            },
        },
        "similar_sqls": [
            {
                "question": "查询2024年1月的订单",
                "sql": "SELECT * FROM public.orders WHERE order_date >= '2024-01-01' AND order_date < '2024-02-01'",
                "similarity": 0.85,
            }
        ],
        "dim_value_matches": [],
        "metadata": {
            "retrieval_time": 0.1,
            "total_tables": 3,
            "total_columns": 3,
        },
    }


@pytest.fixture
def sample_parse_hints():
    """返回示例解析提示"""
    return {
        "time": {
            "start": "2024-01-01",
            "end": "2024-02-01",
        },
        "dimensions": [
            {
                "text": "北京",
                "type": "location",
            }
        ],
        "metric": {
            "text": "销售额",
            "aggregation": "sum",
        },
    }


@pytest.fixture
def sample_sql_generation_state():
    """返回示例 SQL 生成状态"""
    from src.modules.sql_generation.subgraph.state import SQLGenerationState

    return SQLGenerationState(
        messages=[],
        query="查询2024年1月的订单",
        query_id="test-001",
        user_query="查询2024年1月的订单",
        dependencies_results={},
        parse_hints={
            "time": {
                "start": "2024-01-01",
                "end": "2024-02-01",
            }
        },
        schema_context=None,
        generated_sql=None,
        iteration_count=0,
        validation_result=None,
        validation_history=[],
        validated_sql=None,
        error=None,
        error_type=None,
        execution_time=0.0,
    )


# 跳过标记的辅助函数
def pytest_configure(config):
    """注册自定义标记"""
    config.addinivalue_line(
        "markers", "unit: 单元测试"
    )
    config.addinivalue_line(
        "markers", "integration: 集成测试"
    )
    config.addinivalue_line(
        "markers", "slow: 慢速测试"
    )
    config.addinivalue_line(
        "markers", "requires_db: 需要数据库连接的测试"
    )
    config.addinivalue_line(
        "markers", "requires_llm: 需要 LLM API 的测试"
    )


# 条件跳过辅助函数
def pytest_collection_modifyitems(config, items):
    """根据环境修改测试收集"""
    skip_db = pytest.mark.skip(reason="需要数据库连接，使用 --run-db 运行")
    skip_llm = pytest.mark.skip(reason="需要 LLM API，使用 --run-llm 运行")

    # 如果没有指定运行数据库测试，跳过
    if not config.getoption("--run-db", default=False):
        for item in items:
            if "requires_db" in item.keywords:
                item.add_marker(skip_db)

    # 如果没有指定运行 LLM 测试，跳过
    if not config.getoption("--run-llm", default=False):
        for item in items:
            if "requires_llm" in item.keywords:
                item.add_marker(skip_llm)


def pytest_addoption(parser):
    """添加命令行选项"""
    parser.addoption(
        "--run-db",
        action="store_true",
        default=False,
        help="运行需要数据库连接的测试",
    )
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="运行需要 LLM API 的测试",
    )
