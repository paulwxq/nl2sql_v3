import re

with open("src/modules/sql_generation/config/sql_generation_subgraph.yaml", "r", encoding="utf-8") as f:
    content = f.read()

# Pattern to remove cache, logging, monitoring, debug blocks
# We'll remove everything from '# 缓存配置（可选）' down to '# 问题解析配置', but keep '# 问题解析配置'
pattern = r"# -{78}\n# 缓存配置（可选）.*?# -{78}\n# 问题解析配置"
new_content = re.sub(pattern, "# ------------------------------------------------------------------------------\n# 问题解析配置", content, flags=re.DOTALL)

with open("src/modules/sql_generation/config/sql_generation_subgraph.yaml", "w", encoding="utf-8") as f:
    f.write(new_content)
print("Removed dead configs.")
