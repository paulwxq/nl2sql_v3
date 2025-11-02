"""三层验证节点 - 子图的第三个节点"""

from typing import Any, Dict

from src.modules.sql_generation.subgraph.state import SQLGenerationState
from src.services.config_loader import load_subgraph_config
from src.tools.validation.sql_validation import SQLValidationTool


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
    validation_tool = SQLValidationTool(config)

    # 获取生成的 SQL
    generated_sql = state.get("generated_sql")

    if not generated_sql:
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
        print(f"[{state['query_id']}] {summary}")

        # 准备更新的字段
        updates = {
            "validation_result": validation_result,
            "validation_history": [validation_history_entry],  # add reducer 会自动追加
        }

        # 如果验证通过，设置 validated_sql
        if validation_result["valid"]:
            updates["validated_sql"] = generated_sql
            print(f"[{state['query_id']}] ✅ SQL验证通过")
        else:
            # 验证失败
            print(
                f"[{state['query_id']}] ❌ SQL验证失败（{validation_result['layer']}）："
                f"{', '.join(validation_result['errors'])}"
            )

        return updates

    except Exception as e:
        print(f"[{state['query_id']}] ❌ 验证过程异常: {e}")

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
