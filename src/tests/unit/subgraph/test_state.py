"""SQL 生成子图 State 辅助函数测试"""

from src.modules.sql_generation.subgraph.state import extract_output


def test_extract_output_includes_rewritten_query():
    state = {
        "validated_sql": "SELECT 1",
        "rewritten_query": "查询服务区 abc123 的编码",
        "error": "old error",
        "error_type": "old_type",
        "failed_step": "old_step",
        "iteration_count": 2,
        "execution_time": 1.5,
        "schema_context": {"tables": []},
        "validation_history": [],
    }

    result = extract_output(state)

    assert result["validated_sql"] == "SELECT 1"
    assert result["rewritten_query"] == "查询服务区 abc123 的编码"
    assert result["error"] is None
    assert result["error_type"] is None
    assert result["failed_step"] is None
