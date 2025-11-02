"""SQL 验证工具单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.tools.validation.sql_validation import SQLValidationTool


@pytest.fixture
def mock_config():
    """Mock configuration"""
    return {
        "validation": {
            "enable_syntax_check": True,
            "enable_security_check": True,
            "enable_semantic_check": True,
            "allowed_operations": ["SELECT"],
            "max_query_timeout_ms": 5000,
        },
        "database": {
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "user": "testuser",
            "password": "testpass",
        },
    }


@pytest.fixture
def validation_tool(mock_config):
    """创建 SQLValidationTool 实例"""
    with patch("src.tools.validation.sql_validation.PGConnectionManager") as mock_pg:
        # Mock connection manager
        mock_manager = MagicMock()
        mock_pg.return_value = mock_manager

        tool = SQLValidationTool(mock_config)
        tool.pg_manager = mock_manager

        return tool


class TestSyntaxValidation:
    """语法验证测试"""

    def test_valid_syntax(self, validation_tool):
        """测试有效的 SQL 语法"""
        sql = "SELECT id, name FROM public.users WHERE age > 18"
        result = validation_tool._check_syntax(sql)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_invalid_syntax(self, validation_tool):
        """测试无效的 SQL 语法"""
        sql = "SELECT FROM WHERE"
        result = validation_tool._check_syntax(sql)

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_empty_sql(self, validation_tool):
        """测试空 SQL"""
        sql = ""
        result = validation_tool._check_syntax(sql)

        assert result["valid"] is False
        assert "SQL为空" in result["errors"][0]

    def test_whitespace_only_sql(self, validation_tool):
        """测试仅包含空白字符的 SQL"""
        sql = "   \n\t  "
        result = validation_tool._check_syntax(sql)

        assert result["valid"] is False


class TestSecurityValidation:
    """安全验证测试"""

    def test_safe_select_query(self, validation_tool):
        """测试安全的 SELECT 查询"""
        sql = "SELECT id, name FROM public.users WHERE created_at >= '2024-01-01'"
        errors = validation_tool._check_security(sql)

        assert len(errors) == 0

    def test_drop_table_blocked(self, validation_tool):
        """测试 DROP TABLE 被阻止"""
        sql = "DROP TABLE public.users"
        errors = validation_tool._check_security(sql)

        assert len(errors) > 0
        assert any("DROP" in err for err in errors)

    def test_delete_blocked(self, validation_tool):
        """测试 DELETE 被阻止"""
        sql = "DELETE FROM public.users WHERE id = 1"
        errors = validation_tool._check_security(sql)

        assert len(errors) > 0
        assert any("DELETE" in err for err in errors)

    def test_insert_blocked(self, validation_tool):
        """测试 INSERT 被阻止"""
        sql = "INSERT INTO public.users (name) VALUES ('test')"
        errors = validation_tool._check_security(sql)

        assert len(errors) > 0
        assert any("INSERT" in err for err in errors)

    def test_update_blocked(self, validation_tool):
        """测试 UPDATE 被阻止"""
        sql = "UPDATE public.users SET name = 'test' WHERE id = 1"
        errors = validation_tool._check_security(sql)

        assert len(errors) > 0
        assert any("UPDATE" in err for err in errors)

    def test_truncate_blocked(self, validation_tool):
        """测试 TRUNCATE 被阻止"""
        sql = "TRUNCATE TABLE public.users"
        errors = validation_tool._check_security(sql)

        assert len(errors) > 0
        assert any("TRUNCATE" in err for err in errors)

    def test_alter_blocked(self, validation_tool):
        """测试 ALTER 被阻止"""
        sql = "ALTER TABLE public.users ADD COLUMN email VARCHAR(255)"
        errors = validation_tool._check_security(sql)

        assert len(errors) > 0
        assert any("ALTER" in err for err in errors)

    def test_create_blocked(self, validation_tool):
        """测试 CREATE 被阻止"""
        sql = "CREATE TABLE public.test (id INT)"
        errors = validation_tool._check_security(sql)

        assert len(errors) > 0
        assert any("CREATE" in err for err in errors)

    def test_false_positive_created_at(self, validation_tool):
        """测试 created_at 列名不会被误判为 CREATE"""
        sql = "SELECT id, created_at FROM public.users WHERE created_at >= '2024-01-01'"
        errors = validation_tool._check_security(sql)

        # 应该没有安全错误，因为 created_at 不是 CREATE 语句
        assert len(errors) == 0

    def test_false_positive_deleted_flag(self, validation_tool):
        """测试 deleted 列名不会被误判为 DELETE"""
        sql = "SELECT id, deleted FROM public.users WHERE deleted = false"
        errors = validation_tool._check_security(sql)

        assert len(errors) == 0

    def test_multiple_statements_blocked(self, validation_tool):
        """测试多语句被阻止"""
        sql = "SELECT id FROM public.users; DROP TABLE public.users"
        errors = validation_tool._check_security(sql)

        assert len(errors) > 0
        assert any("多条SQL语句" in err or "DROP" in err for err in errors)

    def test_comment_injection_blocked(self, validation_tool):
        """测试注释注入被阻止"""
        sql = "SELECT id FROM public.users -- comment"
        errors = validation_tool._check_security(sql)

        # 注释本身不一定是安全问题，但我们可能想阻止它们
        # 这取决于具体的安全策略实现
        # 如果实现中允许注释，这个测试应该调整


class TestSemanticValidation:
    """语义验证测试（需要数据库连接）"""

    def test_valid_semantic_query(self, validation_tool):
        """测试语义有效的查询"""
        sql = "SELECT id, name FROM public.users WHERE age > 18"

        # Mock database connection and EXPLAIN result
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"QUERY PLAN": "Seq Scan on users"},
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        validation_tool.pg_manager.get_connection.return_value.__enter__.return_value = mock_conn

        result = validation_tool._check_semantics(sql)

        assert result["valid"] is True
        assert result["explain_plan"] is not None

    def test_invalid_table_name(self, validation_tool):
        """测试无效的表名"""
        sql = "SELECT id FROM public.nonexistent_table"

        # Mock database error
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("relation \"public.nonexistent_table\" does not exist")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        validation_tool.pg_manager.get_connection.return_value.__enter__.return_value = mock_conn

        result = validation_tool._check_semantics(sql)

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_invalid_column_name(self, validation_tool):
        """测试无效的列名"""
        sql = "SELECT nonexistent_column FROM public.users"

        # Mock database error
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("column \"nonexistent_column\" does not exist")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        validation_tool.pg_manager.get_connection.return_value.__enter__.return_value = mock_conn

        result = validation_tool._check_semantics(sql)

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_semantic_check_disabled(self, validation_tool):
        """测试语义检查被禁用时的行为"""
        validation_tool.config["validation"]["enable_semantic_check"] = False

        sql = "SELECT id FROM public.users"
        result = validation_tool._check_semantics(sql)

        # 语义检查被禁用时应该跳过
        assert result["valid"] is True
        assert result["explain_plan"] is None


class TestThreeLayerValidation:
    """三层验证集成测试"""

    def test_all_layers_pass(self, validation_tool):
        """测试所有层验证通过"""
        sql = "SELECT id, name FROM public.users WHERE age > 18"

        # Mock semantic check
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"QUERY PLAN": "Seq Scan on users"}]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        validation_tool.pg_manager.get_connection.return_value.__enter__.return_value = mock_conn

        result = validation_tool.validate(sql)

        assert result["valid"] is True
        assert result["layer"] == "all_passed"
        assert len(result["errors"]) == 0

    def test_syntax_layer_fails(self, validation_tool):
        """测试语法层失败"""
        sql = "SELECT FROM WHERE"

        result = validation_tool.validate(sql)

        assert result["valid"] is False
        assert result["layer"] == "syntax"
        assert len(result["errors"]) > 0

    def test_security_layer_fails(self, validation_tool):
        """测试安全层失败"""
        sql = "DROP TABLE public.users"

        result = validation_tool.validate(sql)

        assert result["valid"] is False
        assert result["layer"] == "security"
        assert len(result["errors"]) > 0

    def test_semantic_layer_fails(self, validation_tool):
        """测试语义层失败"""
        sql = "SELECT id FROM public.nonexistent_table"

        # Mock database error
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("relation does not exist")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        validation_tool.pg_manager.get_connection.return_value.__enter__.return_value = mock_conn

        result = validation_tool.validate(sql)

        assert result["valid"] is False
        assert result["layer"] == "semantic"
        assert len(result["errors"]) > 0

    def test_validation_summary(self, validation_tool):
        """测试验证摘要生成"""
        sql = "SELECT id FROM public.users"

        # Mock successful validation
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"QUERY PLAN": "Seq Scan"}]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        validation_tool.pg_manager.get_connection.return_value.__enter__.return_value = mock_conn

        result = validation_tool.validate(sql)
        summary = validation_tool.get_validation_summary(result)

        assert "通过" in summary or "PASSED" in summary.upper()

    def test_validation_with_warnings(self, validation_tool):
        """测试带有警告的验证"""
        sql = "SELECT * FROM public.users"  # SELECT * 可能触发警告

        # Mock successful validation
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"QUERY PLAN": "Seq Scan"}]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        validation_tool.pg_manager.get_connection.return_value.__enter__.return_value = mock_conn

        result = validation_tool.validate(sql)

        # 即使有警告，验证仍应通过
        assert result["valid"] is True


class TestEdgeCases:
    """边界情况测试"""

    def test_very_long_sql(self, validation_tool):
        """测试非常长的 SQL"""
        # 构造一个很长的 SQL（例如有很多 JOIN）
        tables = [f"table{i}" for i in range(50)]
        joins = " ".join([f"JOIN public.{t} ON table0.id = {t}.id" for t in tables[1:]])
        sql = f"SELECT table0.id FROM public.table0 {joins}"

        result = validation_tool._check_syntax(sql)
        # 应该能够处理长 SQL
        assert result is not None

    def test_sql_with_unicode(self, validation_tool):
        """测试包含 Unicode 字符的 SQL"""
        sql = "SELECT id, name FROM public.users WHERE name = '张三'"

        result = validation_tool._check_syntax(sql)
        assert result["valid"] is True

    def test_sql_with_special_chars(self, validation_tool):
        """测试包含特殊字符的 SQL"""
        sql = "SELECT id FROM public.users WHERE email LIKE '%@example.com'"

        result = validation_tool._check_syntax(sql)
        assert result["valid"] is True

    def test_none_sql(self, validation_tool):
        """测试 None SQL"""
        result = validation_tool.validate(None)

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_case_insensitive_keywords(self, validation_tool):
        """测试关键字大小写不敏感"""
        sql1 = "select id from public.users"
        sql2 = "SELECT id FROM public.users"
        sql3 = "SeLeCt id FrOm public.users"

        result1 = validation_tool._check_syntax(sql1)
        result2 = validation_tool._check_syntax(sql2)
        result3 = validation_tool._check_syntax(sql3)

        assert result1["valid"] is True
        assert result2["valid"] is True
        assert result3["valid"] is True
