import os
import re

def update_config_yaml():
    path = "src/configs/config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove sql_generation block
    content = re.sub(
        r"# -{78}\n# SQL 生成子图配置\n# -{78}\nsql_generation:.*?# ------------------------------------------------------------------------------",
        "# ------------------------------------------------------------------------------",
        content,
        flags=re.DOTALL
    )

    # Remove nl2sql_father block
    content = re.sub(
        r"# -{78}\n# NL2SQL 父图配置.*?\n# -{78}\nnl2sql_father:.*?# ------------------------------------------------------------------------------",
        "# ------------------------------------------------------------------------------",
        content,
        flags=re.DOTALL
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated config.yaml")

def update_father_yaml():
    path = "src/modules/nl2sql_father/config/nl2sql_father_graph.yaml"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    new_block = """# ==============================================================================
# NL2SQL 父图配置文件（Phase 1 + Phase 2）
# ==============================================================================

# ------------------------------------------------------------------------------
# 整体图调度控制
# ------------------------------------------------------------------------------
graph_control:
  enabled: true                      # 是否启用 NL2SQL 父图
  total_timeout: 120                 # 父图总超时（秒）
  fast_path_enabled: true            # 是否启用 Fast Path
  complex_path_enabled: false        # 是否启用 Complex Path（Phase 2）
"""
    content = content.replace(
        "# ==============================================================================\n# NL2SQL 父图配置文件（Phase 1 + Phase 2）\n# ==============================================================================",
        new_block
    )

    # Also remove save_checkpoints while we are here, as requested in previous analysis
    content = re.sub(
        r"\s*# \[已弃用\].*?save_checkpoints: false.*?\n",
        "\n",
        content,
        flags=re.DOTALL
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated nl2sql_father_graph.yaml")

def update_subgraph_yaml():
    path = "src/modules/sql_generation/config/sql_generation_subgraph.yaml"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    new_block = """# ==============================================================================
# SQL 生成子图配置文件
# ==============================================================================
#
# 说明：
# - 本文件定义 SQL 生成子图的所有参数
# - 基于 docs/sql_generation_subgraph_design.md v1.2
# - 所有参数都可以通过环境变量覆盖
#
# ==============================================================================

# ------------------------------------------------------------------------------
# 整体图调度控制
# ------------------------------------------------------------------------------
graph_control:
  enabled: true                      # 是否启用 SQL 生成子图
  total_timeout: 60                  # 子图总超时（秒）
"""
    header_pattern = r"# ==============================================================================\n# SQL 生成子图配置文件.*?# =============================================================================="
    content = re.sub(header_pattern, new_block, content, flags=re.DOTALL)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Updated sql_generation_subgraph.yaml")

if __name__ == "__main__":
    update_config_yaml()
    update_father_yaml()
    update_subgraph_yaml()
