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
        # 若上游已经标记为不可恢复错误（例如 generation_failed），不覆盖错误类型，直接返回
        if state.get("error_type") == "generation_failed":
            query_logger.warning("上游生成失败（generation_failed），跳过验证")
            return {}

        # 否则视为异常流程，记录错误并返回防御性结果
        query_logger.error("验证节点收到空SQL，这是一个异常流程")
        return {
            "validation_result": {
                "valid": False,
                "errors": ["系统错误：空SQL进入验证"],
                "warnings": [],
                "layer": "syntax",
                "explain_plan": None,
            },
            "error": "系统错误：空SQL进入验证",
            "error_type": "validation_failed",
            "failed_step": "validation",
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
            # 成功后清理错误字段，避免“成功 + 历史错误”并存
            updates["error"] = None
            updates["error_type"] = None
            updates["failed_step"] = None
        else:
            # 验证失败：写入顶层 error/error_type/failed_step
            error_list = validation_result.get("errors") or ["未知错误"]
            layer = validation_result.get("layer") or "unknown"
            updates["error"] = error_list[0]
            updates["error_type"] = f"validation_{layer}_failed"
            updates["failed_step"] = "validation"
            query_logger.warning(
                "SQL 验证失败（%s）：%s",
                layer,
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
            "failed_step": "validation",
        }
