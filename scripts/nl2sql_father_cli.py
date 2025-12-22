#!/usr/bin/env python3
"""
NL2SQL 父图命令行测试工具

用法:
    # 单次查询模式
    python scripts/nl2sql_father_cli.py "查询2024年的销售总额"

    # 交互模式
    python scripts/nl2sql_father_cli.py

    # 带自定义 query_id
    python scripts/nl2sql_father_cli.py --query-id "test-001" "查询销售额"
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, Any

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.modules.nl2sql_father.graph import run_nl2sql_query
from src.utils.logger import setup_logging_from_yaml

# 加载 YAML 日志配置
setup_logging_from_yaml(str(project_root / "src" / "configs" / "logging.yaml"))

# CLI 使用独立的 logger
logger = logging.getLogger("nl2sql.father_cli")


def print_separator(char="=", length=80):
    """打印分隔线"""
    print(char * length)


def print_result(result: Dict[str, Any]):
    """
    打印父图执行结果

    Args:
        result: 父图返回的结果字典
    """
    print_separator()
    print("📊 查询结果")
    print_separator()

    # 基本信息
    print(f"\n🆔 Query ID: {result['query_id']}")
    if result.get('thread_id'):
        print(f"🔗 Thread ID: {result['thread_id']}")
    if result.get('user_id'):
        print(f"👤 User ID: {result['user_id']}")
    print(f"❓ 用户问题: {result['user_query']}")
    print(f"🏷️  复杂度: {result.get('complexity', 'N/A')}")
    print(f"🛤️  执行路径: {result.get('path_taken', 'N/A')}")

    # 总结（最重要的输出）
    print(f"\n💬 总结:")
    print("-" * 80)
    summary = result.get('summary', '无总结')
    print(summary)
    print("-" * 80)

    # SQL（如果有）
    sql = result.get('sql')
    if sql:
        print(f"\n📝 生成的SQL:")
        print("-" * 80)
        print(sql)
        print("-" * 80)

    # 错误信息（如果有）
    error = result.get('error')
    if error:
        print(f"\n❌ 错误信息: {error}")

    # 子查询详情
    sub_queries = result.get('sub_queries', [])
    if sub_queries:
        print(f"\n📋 子查询详情 ({len(sub_queries)} 个):")
        for i, sq in enumerate(sub_queries, 1):
            print(f"\n  [{i}] {sq['sub_query_id']}")
            print(f"      状态: {sq['status']}")
            if sq.get('validated_sql'):
                print(f"      SQL: {sq['validated_sql'][:100]}{'...' if len(sq['validated_sql']) > 100 else ''}")
            if sq.get('error'):
                print(f"      错误: {sq['error']}")
            print(f"      迭代次数: {sq.get('iteration_count', 0)}")

    # 执行结果
    execution_results = result.get('execution_results', [])
    if execution_results:
        print(f"\n📊 执行结果 ({len(execution_results)} 条):")
        for i, exec_result in enumerate(execution_results, 1):
            print(f"\n  [{i}] {exec_result['sub_query_id']}")
            print(f"      成功: {'✅' if exec_result['success'] else '❌'}")
            if exec_result['success']:
                print(f"      行数: {exec_result['row_count']}")
                print(f"      耗时: {exec_result['execution_time_ms']:.1f}ms")

                # 显示前几行数据
                if exec_result.get('rows'):
                    rows = exec_result['rows']
                    columns = exec_result.get('columns', [])
                    print(f"      数据预览:")
                    if columns:
                        print(f"        列名: {', '.join(columns)}")
                    for row_idx, row in enumerate(rows[:3], 1):  # 只显示前3行
                        print(f"        第{row_idx}行: {row}")
                    if len(rows) > 3:
                        print(f"        ... (共 {len(rows)} 行)")
            else:
                print(f"      错误: {exec_result.get('error')}")

    # 性能指标
    metadata = result.get('metadata', {})
    total_time = metadata.get('total_execution_time_ms', 0)
    router_time = metadata.get('router_latency_ms', 0)

    print(f"\n⏱️  性能指标:")
    print(f"   总耗时: {total_time:.0f}ms")
    if router_time:
        print(f"   Router 延迟: {router_time:.0f}ms")

    print()


def run_single_query(
    question: str,
    query_id: str = None,
    thread_id: str = None,
    user_id: str = None,
):
    """
    运行单个查询

    Args:
        question: 用户问题
        query_id: 查询ID（可选）
        thread_id: 会话ID（可选，多轮对话时复用）
        user_id: 用户标识（可选，默认 guest）
    """
    print(f"\n🔄 正在处理您的问题...")
    print(f"问题: {question}")
    if query_id:
        print(f"Query ID: {query_id}")
    if thread_id:
        print(f"Thread ID: {thread_id}")
    if user_id:
        print(f"User ID: {user_id}")
    print()

    logger.info(f"开始执行查询: {question}")

    try:
        result = run_nl2sql_query(
            query=question,
            query_id=query_id,
            thread_id=thread_id,
            user_id=user_id,
        )

        logger.info(f"查询完成: query_id={result['query_id']}, complexity={result.get('complexity')}")

        print_result(result)

        # 返回 result 供交互模式使用（获取 thread_id）
        return result

    except Exception as e:
        logger.error(f"查询执行异常: {e}", exc_info=True)

        print_separator()
        print("❌ 执行失败")
        print_separator()
        print(f"\n错误: {str(e)}")
        print(f"\n💡 请查看日志了解详情")
        print()
        return None


def interactive_mode(thread_id: str = None, user_id: str = None):
    """交互对话模式

    Args:
        thread_id: 初始会话ID（可选，不传则自动生成）
        user_id: 用户标识（可选，默认 guest）
    """
    from datetime import datetime, timezone

    print_separator()
    print("🤖 NL2SQL 父图测试工具 - 交互模式")
    print_separator()
    print("\n欢迎使用！我可以帮您执行完整的 NL2SQL 流程：")
    print("  Router → Simple Planner → SQL Generation → SQL Execution → Summarizer")
    print("\n💡 提示:")
    print("  - 直接输入问题，按回车提交")
    print("  - 输入 'exit' 或 'quit' 退出")
    print("  - 按 Ctrl+C 也可以退出")

    # 用户标识（默认 guest）
    actual_user_id = user_id or "guest"

    # 启动时生成一次 thread_id（固定整个交互会话）
    if thread_id is None:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
        thread_id = f"{actual_user_id}:{timestamp}"

    print(f"\n🆔 会话 ID: {thread_id}")
    print(f"👤 用户: {actual_user_id}\n")
    print_separator()
    print()

    logger.info(f"进入交互模式: thread_id={thread_id}, user_id={actual_user_id}")

    conversation_count = 0

    while True:
        try:
            # 获取用户输入
            question = input("👤 您的问题: ").strip()

            # 退出命令
            if question.lower() in ["exit", "quit", "q", "bye", "退出", "再见"]:
                print("\n👋 再见！感谢使用~")
                logger.info(f"退出交互模式，共执行 {conversation_count} 次查询")
                break

            # 空输入
            if not question:
                print("💭 请输入您的问题~\n")
                continue

            conversation_count += 1

            # 执行查询（每轮使用同一 thread_id，query_id 自动生成）
            run_single_query(
                question,
                query_id=None,  # 每轮自动生成
                thread_id=thread_id,  # 固定（整个交互会话共享）
                user_id=actual_user_id,
            )

            # 询问是否继续
            print("💬 您可以继续提问，或输入 'exit' 退出\n")

        except KeyboardInterrupt:
            print("\n\n👋 再见！感谢使用~")
            logger.info(f"用户中断，退出交互模式，共执行 {conversation_count} 次查询")
            break
        except Exception as e:
            logger.error(f"交互模式异常: {e}", exc_info=True)
            print(f"\n❌ 抱歉，出现了一些问题: {e}")
            print("💬 您可以继续提问，或输入 'exit' 退出\n")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="NL2SQL 父图测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 交互模式
  python scripts/nl2sql_father_cli.py

  # 单次查询
  python scripts/nl2sql_father_cli.py "查询2024年的销售总额"

  # 带自定义 query_id
  python scripts/nl2sql_father_cli.py --query-id "test-001" "查询销售额"

  # 指定用户（多轮对话）
  python scripts/nl2sql_father_cli.py --user-id "alice" "查询销售额"

  # 继续某个会话（多轮对话）
  python scripts/nl2sql_father_cli.py --thread-id "alice:20251221T120000000Z" "追加条件"

  # 查看详细日志
  python scripts/nl2sql_father_cli.py "查询销售额" --verbose
        """
    )

    parser.add_argument(
        "question",
        nargs="*",
        help="用户问题（留空则进入交互模式）"
    )

    parser.add_argument(
        "--query-id",
        "-q",
        help="自定义查询ID"
    )

    parser.add_argument(
        "--thread-id",
        "-t",
        help="会话ID（多轮对话时复用同一 thread_id）"
    )

    parser.add_argument(
        "--user-id",
        "-u",
        help="用户标识（默认 guest）"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="以JSON格式输出结果"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="显示详细日志"
    )

    args = parser.parse_args()

    # 设置日志级别
    if args.verbose:
        logging.getLogger("nl2sql").setLevel(logging.DEBUG)

    logger.info("="*80)
    logger.info("NL2SQL 父图 CLI 启动")
    logger.info("="*80)

    # 检查是否提供了问题
    if args.question:
        # 单次查询模式
        question = " ".join(args.question)
        logger.info("单次查询模式")

        if args.json:
            # JSON 输出模式
            try:
                result = run_nl2sql_query(
                    query=question,
                    query_id=args.query_id,
                    thread_id=args.thread_id,
                    user_id=args.user_id,
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))
            except Exception as e:
                error_result = {
                    "error": str(e),
                    "query": question,
                    "query_id": args.query_id
                }
                print(json.dumps(error_result, indent=2, ensure_ascii=False))
                sys.exit(1)
        else:
            # 友好输出模式
            run_single_query(
                question,
                query_id=args.query_id,
                thread_id=args.thread_id,
                user_id=args.user_id,
            )
    else:
        # 交互模式
        interactive_mode(thread_id=args.thread_id, user_id=args.user_id)


if __name__ == "__main__":
    main()
