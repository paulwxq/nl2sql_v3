"""SQL 验证工具 - 三层验证：语法 + 安全 + 语义"""

import re
from typing import Any, Dict, List, Tuple

import sqlparse

from src.services.db.pg_client import get_pg_client


class SQLValidationTool:
    """SQL 三层验证工具"""

    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化验证工具

        Args:
            config: 验证配置（来自子图配置文件）
        """
        self.config = config or {}
        self.pg_client = get_pg_client()

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

        # 第1层：语法检查
        syntax_result = self._check_syntax(sql)
        if syntax_result["errors"]:
            return {
                "valid": False,
                "errors": syntax_result["errors"],
                "warnings": syntax_result["warnings"],
                "layer": "syntax",
                "explain_plan": None,
            }
        all_warnings.extend(syntax_result["warnings"])

        # 第2层：安全检查
        security_errors = self._check_security(sql)
        if security_errors:
            return {
                "valid": False,
                "errors": security_errors,
                "warnings": all_warnings,
                "layer": "security",
                "explain_plan": None,
            }

        # 第3层：语义检查（EXPLAIN）
        semantic_result = self._check_semantics(sql)
        if not semantic_result["valid"]:
            combined_warnings = all_warnings + semantic_result.get("warnings", [])
            return {
                "valid": False,
                "errors": semantic_result["errors"],
                "warnings": combined_warnings,
                "layer": "semantic",
                "explain_plan": semantic_result.get("explain_plan"),
            }

        # 全部通过
        combined_warnings = all_warnings + semantic_result.get("warnings", [])
        return {
            "valid": True,
            "errors": [],
            "warnings": combined_warnings,
            "layer": "all_passed",
            "explain_plan": semantic_result.get("explain_plan"),
        }

    # ==================== 第1层：语法检查 ====================

    def _check_syntax(self, sql: str) -> Dict[str, Any]:
        """
        第1层：语法检查（使用 sqlparse）

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

            if not parsed:
                errors.append("SQL解析失败：无法识别的SQL语句")
                return {"errors": errors, "warnings": warnings}

            if len(parsed) > 1:
                errors.append("不允许执行多条SQL语句")
                return {"errors": errors, "warnings": warnings}

            stmt = parsed[0]

            # 允许的语句类型
            allowed_types = {"SELECT", "WITH", "UNKNOWN"}
            stmt_type = stmt.get_type()

            if stmt_type not in allowed_types:
                # 额外检查：确保没有修改操作
                sql_upper = sql.upper()
                write_keywords = [
                    "INSERT", "UPDATE", "DELETE", "DROP",
                    "CREATE", "ALTER", "TRUNCATE"
                ]
                found_write = [kw for kw in write_keywords if f" {kw} " in f" {sql_upper} "]

                if found_write:
                    errors.append(
                        f"只允许只读查询，检测到修改操作：{', '.join(found_write)}"
                    )
                else:
                    # 类型不在允许列表，但没检测到修改操作，给出警告
                    warnings.append(
                        f"SQL类型为 {stmt_type}，请确保是只读查询"
                    )

        except Exception as e:
            errors.append(f"语法解析错误：{str(e)}")

        return {"errors": errors, "warnings": warnings}

    # ==================== 第2层：安全检查 ====================

    def _check_security(self, sql: str) -> List[str]:
        """
        第2层：安全检查（防止危险操作）

        Returns:
            错误列表
        """
        errors = []
        sql_upper = sql.upper()

        # 禁止的关键字 - 使用词边界匹配避免误杀（如 created_at 中的 CREATE）
        dangerous_patterns = [
            r"\bDROP\b", r"\bDELETE\b", r"\bTRUNCATE\b",
            r"\bALTER\b", r"\bCREATE\b", r"\bINSERT\b",
            r"\bUPDATE\b", r"\bGRANT\b", r"\bREVOKE\b",
            r"\bEXEC\b", r"\bEXECUTE\b",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, sql_upper):
                keyword = pattern.strip(r"\b")
                errors.append(f"禁止使用关键字：{keyword}")

        # 检查注释注入
        if "--" in sql or "/*" in sql:
            errors.append("SQL中不允许包含注释（防止注入）")

        # 检查分号（防止多语句）
        if sql.count(";") > 1:
            errors.append("不允许执行多条SQL语句")

        # 注意：不再强制要求 WHERE/LIMIT
        # 原因：会误杀合法的维度枚举查询、TOP-N查询等
        # 全表扫描问题由后续的 EXPLAIN 检查处理

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
            # 执行 EXPLAIN（不实际执行查询）
            success, plan, explain_errors = self.pg_client.explain_query(
                sql=sql,
                analyze=False,
                timeout=self.config.get("validation", {}).get("semantic", {}).get("explain_timeout", 5),
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

            # 性能警告（不影响 valid 状态）
            if "SEQ SCAN" in plan_upper:
                warnings.append("检测到顺序扫描（Seq Scan），可能影响性能")

            if "NESTED LOOP" in plan_upper and "JOIN" not in sql.upper():
                warnings.append("可能存在笛卡尔积，请检查JOIN条件")

            # 检查预估行数（如果配置了阈值）
            threshold = self.config.get("validation", {}).get("semantic", {}).get("warnings", {}).get("estimated_rows_threshold", 100000)
            if threshold:
                rows_match = re.search(r"rows=(\d+)", plan)
                if rows_match:
                    estimated_rows = int(rows_match.group(1))
                    if estimated_rows > threshold:
                        warnings.append(
                            f"预估返回行数过多：{estimated_rows} 行（阈值：{threshold}）"
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
