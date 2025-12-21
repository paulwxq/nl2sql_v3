"""
分析元数据文件，查看被向量化的文本内容

目标：
1. 读取 MD 文件，提取 object_desc（用于生成 embedding）
2. 对比不同表的描述文本
3. 分析为什么某些表的相似度会更高
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from metaweave.core.table_schema.md_parser import MDParser
from metaweave.core.table_schema.json_extractor import JSONExtractor


def main():
    """主函数。"""
    print("=" * 80)
    print("元数据 Embedding 文本分析")
    print("=" * 80 + "\n")

    # 定义要分析的表
    tables_to_analyze = [
        "public.maintenance_work_order",
        "public.fact_store_sales_day",
        "public.fact_store_sales_month",
        "public.dim_store",
        "public.order_header",
    ]

    # 元数据目录
    md_dir = Path(__file__).parent.parent / "output" / "metaweave" / "metadata" / "md"
    json_llm_dir = Path(__file__).parent.parent / "output" / "metaweave" / "metadata" / "json_llm"

    test_query = "请问广州全家天河店的销售额是多少"
    print(f"📝 测试查询: {test_query}\n")
    print("=" * 80 + "\n")

    # 分析每个表
    for table_name in tables_to_analyze:
        md_file = md_dir / f"{table_name}.md"
        json_file = json_llm_dir / f"{table_name}.json"

        if not md_file.exists():
            print(f"⚠️  文件不存在: {md_file}")
            continue

        print(f"📋 分析表: {table_name}")
        print("-" * 80)

        # 解析 MD 文件
        md_parser = MDParser(md_file)
        table_desc = md_parser.get_table_description().strip()

        # 解析 JSON 文件
        json_extractor = JSONExtractor(json_file)
        table_category = json_extractor.get_table_category()
        time_col_hint = json_extractor.format_time_col_hint()

        # 输出表描述（这就是会被向量化的文本）
        print(f"类型: {table_category}")
        print(f"时间列: {time_col_hint}")
        print(f"\n📄 Object Desc（用于生成 Embedding 的文本）:")
        print(f"{table_desc}")
        print()

        # 分析关键词
        query_keywords = ["销售额", "广州", "全家", "天河", "店铺", "sales", "store"]
        matched_keywords = [kw for kw in query_keywords if kw in table_desc]

        if matched_keywords:
            print(f"✅ 匹配的关键词: {', '.join(matched_keywords)}")
        else:
            print(f"❌ 未匹配任何关键词")

        print("\n" + "=" * 80 + "\n")

    # 总结分析
    print("📊 分析总结:")
    print("-" * 80)
    print("\n从上面的分析可以看出：")
    print("1. object_desc 是 MD 文件第一行的表描述（括号内的文本）")
    print("2. 表描述的质量和相关性直接影响向量相似度")
    print("3. 如果维修工单表的描述包含更多通用词汇，可能导致误匹配")
    print("\n建议：")
    print("- 优化表描述，使其更具区分性")
    print("- 增加表名语义匹配权重")
    print("- 考虑表的连通性作为选择 Base 表的因素")


if __name__ == "__main__":
    main()
