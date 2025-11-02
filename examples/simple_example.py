"""
SQL 生成子图简单示例

演示如何使用 SQL 生成子图生成 SQL 语句
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

# 加载环境变量
load_dotenv(project_root / ".env")

from src.modules.sql_generation.subgraph.create_subgraph import run_sql_generation_subgraph


def main():
    """运行示例"""

    print("=" * 80)
    print("SQL 生成子图示例")
    print("=" * 80)
    print()

    # 示例1：简单单表查询
    print("示例1：简单单表查询")
    print("-" * 80)

    result1 = run_sql_generation_subgraph(
        query="查询2024年总销售额",
        query_id="example_1",
        user_query="查询2024年总销售额",
        parse_hints={
            "time": {"start": "2024-01-01", "end": "2025-01-01"},
            "metric": {"text": "销售额", "type": "sum"}
        }
    )

    print()
    print("结果：")
    if result1.get("validated_sql"):
        print(f"✅ 成功生成 SQL：")
        print(result1["validated_sql"])
    else:
        print(f"❌ 生成失败：{result1.get('error')}")

    print()
    print(f"迭代次数：{result1['iteration_count']}")
    print(f"执行耗时：{result1['execution_time']:.2f}秒")
    print()

    # 示例2：多表 JOIN 查询
    print()
    print("示例2：多表 JOIN 查询")
    print("-" * 80)

    result2 = run_sql_generation_subgraph(
        query="查询各店铺2024年第一季度的销售额，按金额降序",
        query_id="example_2",
        user_query="查询各店铺2024年第一季度的销售额，按金额降序",
        parse_hints={
            "time": {"start": "2024-01-01", "end": "2024-04-01"},
            "dimensions": [
                {"text": "店铺", "role": "column"}
            ],
            "metric": {"text": "销售额", "type": "sum"}
        }
    )

    print()
    print("结果：")
    if result2.get("validated_sql"):
        print(f"✅ 成功生成 SQL：")
        print(result2["validated_sql"])
    else:
        print(f"❌ 生成失败：{result2.get('error')}")

    print()
    print(f"迭代次数：{result2['iteration_count']}")
    print(f"执行耗时：{result2['execution_time']:.2f}秒")
    print()

    # 示例3：带维度值过滤的查询
    print()
    print("示例3：带维度值过滤的查询")
    print("-" * 80)

    result3 = run_sql_generation_subgraph(
        query="查询京东便利店2024年的销售额",
        query_id="example_3",
        user_query="查询京东便利店2024年的销售额",
        parse_hints={
            "time": {"start": "2024-01-01", "end": "2025-01-01"},
            "dimensions": [
                {"text": "京东便利店", "role": "value"}
            ],
            "metric": {"text": "销售额", "type": "sum"}
        }
    )

    print()
    print("结果：")
    if result3.get("validated_sql"):
        print(f"✅ 成功生成 SQL：")
        print(result3["validated_sql"])
    else:
        print(f"❌ 生成失败：{result3.get('error')}")

    print()
    print(f"迭代次数：{result3['iteration_count']}")
    print(f"执行耗时：{result3['execution_time']:.2f}秒")

    print()
    print("=" * 80)
    print("示例完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
