"""三层验证节点 - 子图的第三个节点"""

from typing import Any, Dict

from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.tools.validation.sql_validation import SQLValidationTool
from src.utils.logger import get_module_logger, with_query_id


logger = get_module_logger("sql_subgraph")


def validation_node(state: SQLGenerationState) -> Dict[str, Any]:
    """
    三层验证节点

    对生成的 SQL 执行三层验证：语法 + 安全 + 语义

    Args:
        state: 当前 state

    Returns:
        更新的 state 字典
    """
    # 加载配置
    config = load_subgraph_config("sql_generation")

    # 初始化验证工具
    validation_tool = SQLValidationTool(config, query_id=state.get("query_id"))

    query_logger = with_query_id(logger, state.get("query_id", ""))

    # 获取生成的 SQL
    generated_sql = state.get("generated_sql")

    if not generated_sql:
        query_logger.warning("验证阶段没有生成的 SQL，跳过验证")
        return {
            "validation_result": {
                "valid": False,
                "errors": ["没有生成SQL"],
                "warnings": [],
                "layer": "syntax",
                "explain_plan": None,
            },
            "error": "没有生成SQL",
            "error_type": "validation_failed",
        }

    try:
        # 执行验证
        validation_result = validation_tool.validate(generated_sql)

        # 记录验证历史
        validation_history_entry = {
            "iteration": state.get("iteration_count", 0),
            "sql": generated_sql,
            "result": validation_result,
        }

        # 获取验证摘要
        summary = validation_tool.get_validation_summary(validation_result)
        query_logger.debug(summary)

        # 准备更新的字段
        updates = {
            "validation_result": validation_result,
            "validation_history": [validation_history_entry],  # add reducer 会自动追加
        }

        # 如果验证通过，设置 validated_sql
        if validation_result["valid"]:
            updates["validated_sql"] = generated_sql
            query_logger.info("SQL 验证通过")
        else:
            # 验证失败
            error_list = validation_result.get("errors") or ["未知错误"]
            query_logger.warning(
                "SQL 验证失败（%s）：%s",
                validation_result.get("layer", "unknown"),
                "; ".join(error_list),
            )

        return updates

    except Exception as e:
        query_logger.error("验证过程出现异常: %s", e, exc_info=True)

        return {
            "validation_result": {
                "valid": False,
                "errors": [f"验证过程异常：{str(e)}"],
                "warnings": [],
                "layer": "error",
                "explain_plan": None,
            },
            "error": f"验证过程异常：{str(e)}",
            "error_type": "validation_failed",
        }
