"""SQL 验证工具 - 三层验证：语法 + 安全 + 语义"""

import re
from typing import Any, Dict, List, Optional, Tuple

import sqlparse

from src.services.db.pg_client import get_pg_client
from src.utils.logger import get_module_logger, with_query_id


DEFAULT_FORBIDDEN_KEYWORDS = [
    'DROP',
    'DELETE',
    'TRUNCATE',
    'ALTER',
    'CREATE',
    'INSERT',
    'UPDATE',
    'GRANT',
    'REVOKE',
    'EXEC',
    'EXECUTE',
]


BASE_LOGGER = get_module_logger("sql_subgraph")


class SQLValidationTool:
    """SQL 三层验证工具"""

    def __init__(self, config: Dict[str, Any] = None, query_id: Optional[str] = None):
        """
        初始化验证工具

        Args:
            config: 验证配置（来自子图配置文件）
            query_id: 日志上下文中的查询ID
        """
        self.config = config or {}
        self.pg_client = get_pg_client()
        self.validation_config = self.config.get('validation', {})
        self.security_config = self.validation_config.get('security', {})

        self.logger = with_query_id(BASE_LOGGER, query_id) if query_id else BASE_LOGGER

        # 读取三层验证开关
        self.enable_syntax_check = self.validation_config.get('enable_syntax_check', True)
        self.enable_security_check = self.validation_config.get('enable_security_check', True)
        self.enable_semantic_check = self.validation_config.get('enable_semantic_check', True)
        self.logger.debug(
            '三层验证开关：语法检查=%s，安全检查=%s，语义检查=%s',
            self.enable_syntax_check,
            self.enable_security_check,
            self.enable_semantic_check,
        )

        # 语法检查配置
        self.syntax_config = self.validation_config.get('syntax', {})
        self.allow_multiple_statements = self.syntax_config.get('allow_multiple_statements', False)
        self.logger.debug(
            '语法检查配置：allow_multiple_statements=%s',
            self.allow_multiple_statements,
        )

        # 安全检查配置
        raw_types = self.security_config.get('allowed_statement_types')
        self.allowed_statement_types = [t.upper() for t in (raw_types or ['SELECT', 'WITH', 'UNKNOWN'])]
        
        raw_keywords = self.security_config.get('forbidden_keywords')
        self.security_keywords = [kw.upper() for kw in (raw_keywords or DEFAULT_FORBIDDEN_KEYWORDS)]
        
        self.allow_comments = self.security_config.get('allow_comments', False)
        
        self.logger.debug(
            '安全检查配置：allowed_statement_types=%s，forbidden_keywords=%s，allow_comments=%s',
            self.allowed_statement_types,
            ', '.join(self.security_keywords),
            self.allow_comments,
        )

        # 语义检查配置
        self.semantic_config = self.validation_config.get('semantic', {})
        self.explain_timeout = self.semantic_config.get('explain_timeout', 5)
        self.explain_analyze = self.semantic_config.get('explain_analyze', False)
        
        # 性能警告配置
        self.warnings_config = self.semantic_config.get('warnings', {})
        self.seq_scan_warn = self.warnings_config.get('seq_scan_warn', True)
        self.nested_loop_warn = self.warnings_config.get('nested_loop_warn', True)
        self.estimated_rows_threshold = self.warnings_config.get('estimated_rows_threshold', 100000)
        
        # 验证失败处理配置
        self.validation_failure_config = self.validation_config.get('on_validation_failure', {})
        self.include_explain_plan = self.validation_failure_config.get('include_explain_plan', True)
        
        self.logger.debug(
            '语义检查配置：explain_timeout=%s秒，explain_analyze=%s，estimated_rows_threshold=%s',
            self.explain_timeout,
            self.explain_analyze,
            self.estimated_rows_threshold,
        )
        self.logger.debug(
            '验证失败处理配置：include_explain_plan=%s',
            self.include_explain_plan,
        )

    def validate(self, sql: str) -> Dict[str, Any]:
        """
        三层验证 SQL

        Returns:
            {
                "valid": bool,              # 是否通过验证
                "errors": List[str],        # 硬错误列表
                "warnings": List[str],      # 警告列表（性能警告等）
                "layer": str,               # 失败层："syntax" / "security" / "semantic" / "all_passed"
                "explain_plan": Optional[str]  # EXPLAIN 结果（如果执行了）
            }
        """
        all_errors = []
        all_warnings = []
        explain_plan = None

        # 第1层：语法检查
        if self.enable_syntax_check:
            self.logger.debug('验证1：开始语法检查')
            syntax_result = self._check_syntax(sql)
            if syntax_result["errors"]:
                self.logger.warning('语法检查失败：%s', '; '.join(syntax_result["errors"]))
                return {
                    "valid": False,
                    "errors": syntax_result["errors"],
                    "warnings": syntax_result["warnings"],
                    "layer": "syntax",
                    "explain_plan": None,
                }
            self.logger.debug('验证1：语法检查通过')
            all_warnings.extend(syntax_result["warnings"])
        else:
            self.logger.debug('验证1：语法检查配置为 false，跳过检查')

        # 第2层：安全检查
        if self.enable_security_check:
            self.logger.debug('验证2：开始安全检查')
            security_errors = self._check_security(sql)
            if security_errors:
                self.logger.warning('安全检查失败：%s', '; '.join(security_errors))
                return {
                    "valid": False,
                    "errors": security_errors,
                    "warnings": all_warnings,
                    "layer": "security",
                    "explain_plan": None,
                }
            self.logger.debug('验证2：安全检查通过')
        else:
            self.logger.debug('验证2：安全检查配置为 false，跳过检查')

        # 第3层：语义检查（EXPLAIN）
        if self.enable_semantic_check:
            self.logger.debug('验证3：开始语义检查')
            semantic_result = self._check_semantics(sql)
            if not semantic_result["valid"]:
                combined_warnings = all_warnings + semantic_result.get("warnings", [])
                self.logger.warning('语义检查失败：%s', '; '.join(semantic_result["errors"] or ['未知错误']))
                return {
                    "valid": False,
                    "errors": semantic_result["errors"],
                    "warnings": combined_warnings,
                    "layer": "semantic",
                    "explain_plan": semantic_result.get("explain_plan"),
                }
            self.logger.debug('验证3：语义检查通过')
            all_warnings.extend(semantic_result.get("warnings", []))
            explain_plan = semantic_result.get("explain_plan")
        else:
            self.logger.debug('验证3：语义检查配置为 false，跳过检查')

        # 全部通过
        return {
            "valid": True,
            "errors": [],
            "warnings": all_warnings,
            "layer": "all_passed",
            "explain_plan": explain_plan,
        }

    # ==================== 第1层：语法检查 ====================

    def _check_syntax(self, sql: str) -> Dict[str, Any]:
        """
        第1层：语法检查（判断是否为合法的SQL语句）

        Returns:
            {
                "errors": List[str],    # 硬错误
                "warnings": List[str]   # 警告信息
            }
        """
        errors = []
        warnings = []

        try:
            parsed = sqlparse.parse(sql)

            # 1. 能否被解析
            if not parsed:
                errors.append("SQL解析失败：无法识别的SQL语句")
                return {"errors": errors, "warnings": warnings}

            # 2. 是否多条语句（根据配置决定是否报错）
            if len(parsed) > 1:
                if not self.allow_multiple_statements:
                    errors.append("不允许执行多条SQL语句")
                    return {"errors": errors, "warnings": warnings}
                else:
                    warnings.append("检测到多条SQL语句")

            # 3. 是否被识别为SQL语句（而不是纯文本）
            stmt = parsed[0]
            stmt_type = stmt.get_type()
            if not stmt_type:
                errors.append("无法识别的SQL类型，可能不是合法的SQL语句")

        except Exception as e:
            errors.append(f"语法解析错误：{str(e)}")

        return {"errors": errors, "warnings": warnings}

    # ==================== 第2层：安全检查 ====================

    def _check_security(self, sql: str) -> List[str]:
        """
        第2层：安全检查（检查SQL是否符合安全策略）

        Returns:
            错误列表
        """
        errors = []
        sql_upper = sql.upper()

        # 1. 检查SQL类型是否允许
        try:
            parsed = sqlparse.parse(sql)
            if parsed:
                stmt = parsed[0]
                stmt_type = stmt.get_type()
                self.logger.debug(
                    'SQL类型检查：stmt_type=%s，允许的类型=%s',
                    stmt_type,
                    self.allowed_statement_types,
                )
                
                if stmt_type and stmt_type not in self.allowed_statement_types:
                    errors.append(
                        f"不允许的SQL类型：{stmt_type}，只允许：{', '.join(self.allowed_statement_types)}"
                    )
        except Exception as e:
            self.logger.warning('SQL类型检查失败：%s', e)

        # 2. 检查禁止的关键字（使用词边界匹配避免误杀）
        for keyword in self.security_keywords:
            pattern = rf"\b{re.escape(keyword)}\b"
            if re.search(pattern, sql_upper):
                errors.append(f"禁止使用关键字：{keyword}")

        # 3. 检查注释（根据配置决定是否报错）
        if not self.allow_comments:
            if "--" in sql or "/*" in sql:
                errors.append("SQL中不允许包含注释（防止注入）")

        return errors

    # ==================== 第3层：语义检查 ====================

    def _check_semantics(self, sql: str) -> Dict[str, Any]:
        """
        第3层：语义验证（使用 EXPLAIN 检查）

        Returns:
            {
                "valid": bool,
                "errors": List[str],        # 硬错误：表不存在、列不存在等
                "warnings": List[str],      # 性能警告：Seq Scan、Nested Loop等
                "explain_plan": Optional[str]
            }
        """
        errors = []
        warnings = []
        explain_plan = None

        try:
            # 执行 EXPLAIN（根据配置决定是否实际执行）
            success, plan, explain_errors = self.pg_client.explain_query(
                sql=sql,
                analyze=self.explain_analyze,
                timeout=self.explain_timeout,
            )

            if not success:
                # EXPLAIN 失败，通常是语法错误或表/列不存在
                errors.extend(explain_errors)
                return {
                    "valid": False,
                    "errors": errors,
                    "warnings": warnings,
                    "explain_plan": None,
                }

            explain_plan = plan

            # 分析查询计划，检测潜在问题
            plan_upper = plan.upper()

            # 性能警告（不影响 valid 状态，根据配置决定是否启用）
            if self.seq_scan_warn and "SEQ SCAN" in plan_upper:
                warnings.append("检测到顺序扫描（Seq Scan），可能影响性能")

            if self.nested_loop_warn and "NESTED LOOP" in plan_upper and "JOIN" not in sql.upper():
                warnings.append("可能存在笛卡尔积，请检查JOIN条件")

            # 检查预估行数（如果配置了阈值）
            if self.estimated_rows_threshold:
                rows_match = re.search(r"rows=(\d+)", plan)
                if rows_match:
                    estimated_rows = int(rows_match.group(1))
                    if estimated_rows > self.estimated_rows_threshold:
                        warnings.append(
                            f"预估返回行数过多：{estimated_rows} 行（阈值：{self.estimated_rows_threshold}）"
                        )

        except Exception as e:
            # 捕获未预期的异常
            errors.append(f"语义验证失败：{str(e)}")

        return {
            "valid": len(errors) == 0,  # 只有硬错误才影响 valid
            "errors": errors,
            "warnings": warnings,
            "explain_plan": explain_plan,
        }

    # ==================== 工具方法 ====================

    def extract_tables_from_sql(self, sql: str) -> List[str]:
        """
        从 SQL 中提取表名

        Args:
            sql: SQL 语句

        Returns:
            表名列表
        """
        tables = []

        try:
            parsed = sqlparse.parse(sql)
            if not parsed:
                return tables

            stmt = parsed[0]

            # 遍历所有 tokens
            from_seen = False
            for token in stmt.tokens:
                if from_seen and isinstance(token, sqlparse.sql.Identifier):
                    tables.append(str(token))
                    from_seen = False
                elif from_seen and token.ttype is None:
                    # 可能是 IdentifierList（多个表）
                    if hasattr(token, "get_identifiers"):
                        for identifier in token.get_identifiers():
                            tables.append(str(identifier))
                    from_seen = False
                elif token.ttype is sqlparse.tokens.Keyword and token.value.upper() == "FROM":
                    from_seen = True

        except Exception as e:
            print(f"⚠️ 提取表名失败: {e}")

        return tables

    def get_validation_summary(self, result: Dict[str, Any]) -> str:
        """
        生成验证结果摘要（用于日志）

        Args:
            result: 验证结果字典

        Returns:
            摘要文本
        """
        if result["valid"]:
            summary = f"✅ 验证通过（{result['layer']}）"
            if result["warnings"]:
                summary += f"\n⚠️ 警告 ({len(result['warnings'])}个):\n"
                summary += "\n".join(f"  - {w}" for w in result["warnings"])
        else:
            summary = f"❌ 验证失败（{result['layer']}）"
            if result["errors"]:
                summary += f"\n错误 ({len(result['errors'])}个):\n"
                summary += "\n".join(f"  - {e}" for e in result["errors"])
            
            # 根据配置决定是否在日志中包含 EXPLAIN 结果
            if self.include_explain_plan and result.get("explain_plan"):
                summary += f"\n\n📋 EXPLAIN 结果：\n{result['explain_plan']}"

        return summary


# 便捷函数

def validate_sql(sql: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    验证 SQL（便捷函数）

    Args:
        sql: 要验证的 SQL
        config: 验证配置

    Returns:
        验证结果
    """
    tool = SQLValidationTool(config)
    return tool.validate(sql)


def quick_validate(sql: str) -> bool:
    """
    快速验证 SQL（仅返回是否通过）

    Args:
        sql: 要验证的 SQL

    Returns:
        通过返回 True，否则返回 False
    """
    result = validate_sql(sql)
    return result["valid"]
