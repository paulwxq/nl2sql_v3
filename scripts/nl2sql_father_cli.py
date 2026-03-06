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

    # 纯文本输出（禁用 Rich 渲染）
    python scripts/nl2sql_father_cli.py --no-rich "查询销售额"
"""

import sys
import argparse
import logging
import readline  # noqa: F401 — 启用 input() 行编辑和历史记录
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.modules.nl2sql_father.graph import run_nl2sql_query
from src.utils.logger import setup_logging_from_yaml

# 加载 YAML 日志配置
setup_logging_from_yaml(str(project_root / "src" / "configs" / "logging.yaml"))

# CLI 使用独立的 logger
logger = logging.getLogger("nl2sql.father_cli")

# Rich imports（模块级导入，--no-rich 时仅不渲染，不影响导入）
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.text import Text
from rich.prompt import Prompt

# 全局 Console 实例（默认构造，自动检测 TTY）
console = Console()


# ============================================================
# Spinner 与日志冲突处理（§3.3）
# ============================================================

def _collect_stdout_handlers():
    """收集所有写到 stdout 的 StreamHandler（跨 nl2sql 和 root logger，按 id 去重）

    nl2sql 和 root logger 可能引用同一个 console handler 实例，
    用 dict 按 id(handler) 去重，避免重复 set/restore 级别。

    若后续新增其他 propagate=false 且直挂 stdout handler 的 logger，
    需将其名称加入下方遍历列表。
    """
    seen = {}  # id(handler) -> handler
    for logger_name in ("nl2sql", None):  # None = root logger
        lgr = logging.getLogger(logger_name)
        for h in lgr.handlers:
            if (
                isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.FileHandler)
                and getattr(h, "stream", None) is sys.stdout
                and id(h) not in seen
            ):
                seen[id(h)] = h
    return list(seen.values())


def _run_with_spinner(query_func, *args, **kwargs):
    """在 spinner 运行期间临时屏蔽 INFO 日志到终端"""
    stdout_handlers = _collect_stdout_handlers()

    original_levels = {}
    for h in stdout_handlers:
        original_levels[h] = h.level
        h.setLevel(logging.WARNING)

    try:
        with console.status(
            "[bold yellow]🔄 正在执行 NL2SQL 分析与查询...[/bold yellow]",
            spinner="dots",
        ):
            result = query_func(*args, **kwargs)
        return result
    finally:
        for h, level in original_levels.items():
            h.setLevel(level)


# ============================================================
# Legacy 纯文本输出（--no-rich / 非 TTY 降级路径）
# ============================================================

def _print_separator_legacy(char="=", length=80):
    """打印分隔线"""
    print(char * length)


def _print_result_legacy(result: Dict[str, Any]):
    """打印父图执行结果（纯文本 legacy 路径）"""
    _print_separator_legacy()
    print("📊 查询结果")
    _print_separator_legacy()

    # 基本信息
    print(f"\n🆔 Query ID: {result['query_id']}")
    if result.get('thread_id'):
        print(f"🔗 Thread ID: {result['thread_id']}")
    if result.get('user_id'):
        print(f"👤 User ID: {result['user_id']}")
    print(f"❓ 用户问题: {result['user_query']}")
    print(f"🏷️  复杂度: {result.get('complexity', 'N/A')}")
    print(f"🛤️  执行路径: {result.get('path_taken', 'N/A')}")

    # 总结
    print(f"\n💬 总结:")
    print("-" * 80)
    summary = result.get('summary') or '（无总结信息）'
    print(summary)
    print("-" * 80)

    # SQL
    sql = result.get('sql')
    if sql:
        print(f"\n📝 生成的SQL:")
        print("-" * 80)
        print(sql)
        print("-" * 80)
    else:
        # Complex Path：遍历子查询
        sub_queries = result.get('sub_queries', [])
        for sq in sub_queries:
            if sq.get('validated_sql'):
                print(f"\n📝 SQL ({sq['sub_query_id']}):")
                print("-" * 80)
                print(sq['validated_sql'])
                print("-" * 80)

    # 错误信息
    error = result.get('error')
    if error and not result.get('execution_results'):
        print(f"\n❌ 错误信息: {error}")

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
                if exec_result.get('rows'):
                    rows = exec_result['rows']
                    columns = exec_result.get('columns', [])
                    print(f"      数据预览:")
                    if columns:
                        print(f"        列名: {', '.join(columns)}")
                    for row_idx, row in enumerate(rows[:5], 1):
                        print(f"        第{row_idx}行: {row}")
                    if len(rows) > 5:
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
    # Phase 2 指标
    planner_time = metadata.get('planner_latency_ms')
    if planner_time:
        print(f"   Planner 延迟: {planner_time:.0f}ms")
    sub_query_count = metadata.get('sub_query_count', 0)
    if sub_query_count > 1:
        parallel_count = metadata.get('parallel_execution_count', 0)
        print(f"   子查询数: {sub_query_count}")
        print(f"   并发执行数: {parallel_count}")
    print()


def _print_error_legacy(error: Exception):
    """打印异常错误（纯文本 legacy 路径）"""
    _print_separator_legacy()
    print("❌ 执行失败")
    _print_separator_legacy()
    print(f"\n错误: {str(error)}")
    print(f"\n💡 请查看日志了解详情")
    print()


# ============================================================
# Rich 渲染输出（模块 A~E）
# ============================================================

def _render_metadata(result: Dict[str, Any]) -> Table:
    """模块 A：查询元数据"""
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("value")

    table.add_row("🆔 Query ID", result['query_id'])
    if result.get('thread_id'):
        table.add_row("🔗 Thread ID", result['thread_id'])
    if result.get('user_id'):
        table.add_row("👤 User ID", result['user_id'])
    table.add_row("🏷️  复杂度", result.get('complexity') or 'N/A')
    table.add_row("🛤️  执行路径", result.get('path_taken') or 'N/A')
    return table


def _render_summary(result: Dict[str, Any]) -> Panel:
    """模块 B：总结信息（始终渲染，空值显示默认文案）"""
    summary = result.get('summary') or '（无总结信息）'
    return Panel(
        summary,
        title="[bold green]💬 最终总结[/bold green]",
        border_style="green",
        expand=True,
    )


def _render_sql(result: Dict[str, Any]):
    """模块 C：生成的 SQL（返回渲染对象列表，空值返回空列表）"""
    panels = []
    sql = result.get('sql')

    if sql:
        # Fast Path：单子查询
        syntax = Syntax(sql, "sql", theme="monokai", line_numbers=True)
        panels.append(Panel(
            syntax,
            title="[bold blue]📝 执行的 SQL[/bold blue]",
            border_style="blue",
        ))
    else:
        # Complex Path：遍历子查询
        sub_queries = result.get('sub_queries', [])
        for sq in sub_queries:
            validated_sql = sq.get('validated_sql')
            if validated_sql:
                syntax = Syntax(validated_sql, "sql", theme="monokai", line_numbers=True)
                panels.append(Panel(
                    syntax,
                    title=f"[bold blue]📝 SQL ({sq['sub_query_id']})[/bold blue]",
                    border_style="blue",
                ))

    return panels


def _render_execution_results(result: Dict[str, Any]):
    """模块 D：执行结果数据（返回渲染对象列表）"""
    renderables = []
    execution_results = result.get('execution_results', [])
    if not execution_results:
        return renderables

    for exec_result in execution_results:
        sub_query_id = exec_result['sub_query_id']

        if not exec_result['success']:
            # 失败：红色错误面板
            renderables.append(Panel(
                f"[red]{exec_result.get('error', '未知错误')}[/red]",
                title=f"[bold red]❌ 执行失败 ({sub_query_id})[/bold red]",
                border_style="red",
            ))
            continue

        columns = exec_result.get('columns', [])
        rows = exec_result.get('rows', [])
        if not columns and not rows:
            continue

        # 构建数据表格
        table = Table(
            title=f"📊 执行结果 ({sub_query_id})",
            show_lines=False,
            row_styles=["", "dim"],
        )
        for col in columns:
            table.add_column(col, style="bold")

        max_display = 5
        for row in rows[:max_display]:
            table.add_row(*[str(v) for v in row])

        renderables.append(table)

        if len(rows) > max_display:
            renderables.append(Text(
                f"  ... (共 {len(rows)} 行数据，仅展示前 {max_display} 行)",
                style="dim",
            ))

        renderables.append(Text(
            f"  行数: {exec_result['row_count']}  |  "
            f"耗时: {exec_result['execution_time_ms']:.1f}ms",
            style="dim",
        ))

    return renderables


def _render_top_level_error(result: Dict[str, Any]):
    """模块 D'：顶层错误面板（仅在有错误且无执行结果时渲染）"""
    error = result.get('error')
    if error and not result.get('execution_results'):
        return Panel(
            f"[red]{error}[/red]",
            title="[bold red]❌ 错误信息[/bold red]",
            border_style="red",
        )
    return None


def _render_performance(result: Dict[str, Any]) -> Text:
    """模块 E：性能指标"""
    metadata = result.get('metadata', {})
    total_time = metadata.get('total_execution_time_ms', 0)
    router_time = metadata.get('router_latency_ms', 0)

    parts = [f"⏱️  总耗时: {total_time:.0f}ms"]
    if router_time:
        parts.append(f"Router 延迟: {router_time:.0f}ms")

    # Phase 2 指标
    planner_time = metadata.get('planner_latency_ms')
    if planner_time:
        parts.append(f"Planner 延迟: {planner_time:.0f}ms")
    sub_query_count = metadata.get('sub_query_count', 0)
    if sub_query_count > 1:
        parallel_count = metadata.get('parallel_execution_count', 0)
        parts.append(f"子查询数: {sub_query_count}")
        parts.append(f"并发执行数: {parallel_count}")

    return Text(" | ".join(parts), style="dim")


def _print_result_rich(result: Dict[str, Any]):
    """使用 Rich 渲染完整的查询结果"""
    console.print()

    # 模块 A：元数据
    console.print(_render_metadata(result))
    console.print()

    # 模块 B：总结（始终渲染）
    console.print(_render_summary(result))

    # 模块 C：SQL
    for panel in _render_sql(result):
        console.print(panel)

    # 模块 D'：顶层错误
    error_panel = _render_top_level_error(result)
    if error_panel:
        console.print(error_panel)

    # 模块 D：执行结果
    for renderable in _render_execution_results(result):
        console.print(renderable)

    # 模块 E：性能指标
    console.print()
    console.print(_render_performance(result))
    console.print()


def _print_error_rich(error: Exception):
    """使用 Rich 渲染异常错误"""
    console.print()
    console.print(Panel(
        f"[red]{str(error)}[/red]\n\n[dim]💡 请查看日志了解详情[/dim]",
        title="[bold red]❌ 执行失败[/bold red]",
        border_style="red",
    ))
    console.print()


# ============================================================
# 会话选择菜单
# ============================================================

def _render_session_menu(sessions: List[Dict[str, Any]]) -> Panel:
    """渲染会话选择菜单（Rich Panel）。

    Args:
        sessions: list_recent_sessions() 返回的会话列表（新->旧）

    Returns:
        Rich Panel 对象（仅包含选项列表，不含输入提示）
    """
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column("idx", style="bold cyan", no_wrap=True, width=4)
    table.add_column("info")

    # 第一行：新建会话
    table.add_row("[0]", "[bold green]新建会话[/bold green]")

    # 历史会话
    for i, session in enumerate(sessions, 1):
        created_at = session["created_at"]
        # UTC -> 本地时区显示
        local_time = created_at.astimezone()
        time_str = local_time.strftime("%Y-%m-%d %H:%M")

        # 首问展示（兜底空值）
        question = session.get("first_question") or "（无对话内容）"
        max_q_len = 36
        if len(question) > max_q_len:
            question = question[:max_q_len] + "..."

        table.add_row(f"[{i}]", f"{time_str}  {question}")

    return Panel(
        table,
        title="[bold blue]NL2SQL 交互式终端[/bold blue]",
        border_style="blue",
        expand=False,
        padding=(1, 2),
    )


def _select_session(
    user_id: str,
    use_rich: bool,
) -> Optional[str]:
    """展示会话列表并等待用户选择，返回 thread_id。

    Args:
        user_id: 用户标识（已经过 sanitize_user_id 处理）
        use_rich: 是否使用 Rich 渲染

    Returns:
        - 选中的历史 thread_id（继续对话）
        - None（新建会话，由调用方生成 thread_id）
    """
    from src.services.langgraph_persistence.chat_history_reader import (
        list_recent_sessions,
    )

    # 查询最近会话
    sessions = list_recent_sessions(user_id=user_id, max_sessions=3)

    if not sessions:
        # 无历史会话，直接新建
        return None

    # 渲染菜单
    if use_rich:
        panel = _render_session_menu(sessions)
        console.print(panel)
    else:
        # 纯文本降级
        print("=" * 50)
        print("  [0] 新建会话")
        for i, s in enumerate(sessions, 1):
            local_time = s["created_at"].astimezone()
            time_str = local_time.strftime("%Y-%m-%d %H:%M")
            q = s.get("first_question") or "（无对话内容）"
            if len(q) > 36:
                q = q[:36] + "..."
            print(f"  [{i}] {time_str}  {q}")
        print("=" * 50)

    # 等待用户输入（输入提示在 Panel 外部）
    max_idx = len(sessions)
    while True:
        if use_rich:
            choice = console.input(
                f"[bold]请输入选项编号 (0-{max_idx}): [/bold]"
            ).strip()
        else:
            choice = input(f"请输入选项编号 (0-{max_idx}): ").strip()

        if choice == "0" or choice == "":
            return None  # 新建会话

        try:
            idx = int(choice)
            if 1 <= idx <= max_idx:
                return sessions[idx - 1]["thread_id"]
        except ValueError:
            pass

        # 输入无效，提示重试
        if use_rich:
            console.print(f"[red]请输入 0 到 {max_idx} 之间的数字[/red]")
        else:
            print(f"请输入 0 到 {max_idx} 之间的数字")


# ============================================================
# 核心业务函数
# ============================================================

def run_single_query(
    question: str,
    query_id: str = None,
    thread_id: str = None,
    user_id: str = None,
    use_rich: bool = True,
    interactive: bool = False,
):
    """运行单个查询

    Args:
        question: 用户问题
        query_id: 查询ID（可选）
        thread_id: 会话ID（可选，多轮对话时复用）
        user_id: 用户标识（可选，默认 guest）
        use_rich: 是否使用 Rich 渲染
        interactive: 是否在交互模式中调用
    """
    logger.info(f"开始执行查询: {question}")

    try:
        # 执行查询（带 spinner 或静态提示）
        use_spinner = use_rich and console.is_terminal

        if use_spinner:
            result = _run_with_spinner(
                run_nl2sql_query,
                query=question,
                query_id=query_id,
                thread_id=thread_id,
                user_id=user_id,
            )
        else:
            if interactive:
                print("🔄 正在执行 NL2SQL 分析与查询...")
            result = run_nl2sql_query(
                query=question,
                query_id=query_id,
                thread_id=thread_id,
                user_id=user_id,
            )

        logger.info(f"查询完成: query_id={result['query_id']}, complexity={result.get('complexity')}")

        # 渲染结果
        if use_rich:
            _print_result_rich(result)
        else:
            _print_result_legacy(result)

        return result

    except Exception as e:
        logger.error(f"查询执行异常: {e}", exc_info=True)

        if use_rich:
            _print_error_rich(e)
        else:
            _print_error_legacy(e)

        return None


def interactive_mode(
    thread_id: str = None,
    user_id: str = None,
    use_rich: bool = True,
):
    """交互对话模式

    Args:
        thread_id: 初始会话ID（可选，不传则自动生成）
        user_id: 用户标识（可选，默认 guest）
        use_rich: 是否使用 Rich 渲染
    """
    from datetime import datetime, timezone
    from src.services.langgraph_persistence.identifiers import sanitize_user_id

    # 用户标识（使用项目已有的 sanitize_user_id）
    actual_user_id = sanitize_user_id(user_id)

    # ====== 会话选择（在欢迎横幅之前） ======
    is_resumed = False
    if thread_id is None:
        # 未通过 --thread-id 指定，展示会话选择菜单
        selected = _select_session(
            user_id=actual_user_id,
            use_rich=use_rich,
        )
        if selected is not None:
            thread_id = selected
            is_resumed = True
        else:
            now = datetime.now(timezone.utc)
            timestamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
            thread_id = f"{actual_user_id}:{timestamp}"

    # ====== 欢迎横幅（在会话选择之后） ======
    if use_rich:
        if is_resumed:
            console.print(f"\n[cyan]已恢复历史会话[/cyan]: {thread_id}")
        console.print(Panel(
            "欢迎使用！我可以帮您执行完整的 NL2SQL 流程：\n"
            "Router → Simple Planner → SQL Gen → SQL Exec → Summarizer\n\n"
            "[bold]💡 提示[/bold]:\n"
            "  - 直接输入问题，按回车提交\n"
            "  - 输入 'exit' 或 'quit' 退出\n"
            "  - 按 Ctrl+C 也可以退出",
            title="[bold blue]🤖 NL2SQL 交互式测试终端[/bold blue]",
            border_style="blue",
            expand=False,
        ))
    else:
        if is_resumed:
            print(f"\n已恢复历史会话: {thread_id}")
        _print_separator_legacy()
        print("🤖 NL2SQL 父图测试工具 - 交互模式")
        _print_separator_legacy()
        print("\n欢迎使用！我可以帮您执行完整的 NL2SQL 流程：")
        print("  Router → Simple Planner → SQL Generation → SQL Execution → Summarizer")
        print("\n💡 提示:")
        print("  - 直接输入问题，按回车提交")
        print("  - 输入 'exit' 或 'quit' 退出")
        print("  - 按 Ctrl+C 也可以退出")

    if use_rich:
        console.print(f"\n[cyan]🆔 会话 ID:[/cyan] {thread_id}")
        console.print(f"[cyan]👤 用户:[/cyan] {actual_user_id}\n")
    else:
        print(f"\n🆔 会话 ID: {thread_id}")
        print(f"👤 用户: {actual_user_id}\n")
        _print_separator_legacy()
        print()

    logger.info(f"进入交互模式: thread_id={thread_id}, user_id={actual_user_id}")

    conversation_count = 0

    while True:
        try:
            # 获取用户输入
            if use_rich:
                console.print("[bold green]👤 您的问题[/bold green]", end="")
                question = console.input(": ").strip()
            else:
                question = input("👤 您的问题: ").strip()

            # 退出命令
            if question.lower() in ["exit", "quit", "q", "bye", "退出", "再见"]:
                if use_rich:
                    console.print("\n[bold]👋 再见！感谢使用~[/bold]")
                else:
                    print("\n👋 再见！感谢使用~")
                logger.info(f"退出交互模式，共执行 {conversation_count} 次查询")
                break

            # 空输入
            if not question:
                if use_rich:
                    console.print("[dim]💭 请输入您的问题~[/dim]\n")
                else:
                    print("💭 请输入您的问题~\n")
                continue

            conversation_count += 1

            # 执行查询
            run_single_query(
                question,
                query_id=None,
                thread_id=thread_id,
                user_id=actual_user_id,
                use_rich=use_rich,
                interactive=True,
            )

            # 继续提示
            if use_rich:
                console.print("[dim]💬 您可以继续提问，或输入 'exit' 退出[/dim]\n")
            else:
                print("💬 您可以继续提问，或输入 'exit' 退出\n")

        except KeyboardInterrupt:
            if use_rich:
                console.print("\n\n[bold]👋 再见！感谢使用~[/bold]")
            else:
                print("\n\n👋 再见！感谢使用~")
            logger.info(f"用户中断，退出交互模式，共执行 {conversation_count} 次查询")
            break
        except Exception as e:
            logger.error(f"交互模式异常: {e}", exc_info=True)
            if use_rich:
                console.print(f"\n[red]❌ 抱歉，出现了一些问题: {e}[/red]")
                console.print("[dim]💬 您可以继续提问，或输入 'exit' 退出[/dim]\n")
            else:
                print(f"\n❌ 抱歉，出现了一些问题: {e}")
                print("💬 您可以继续提问，或输入 'exit' 退出\n")


# ============================================================
# 入口
# ============================================================

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

  # 纯文本输出
  python scripts/nl2sql_father_cli.py --no-rich "查询销售额"

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
        "--no-rich",
        action="store_true",
        help="禁用 Rich 渲染，使用纯文本输出"
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

    # 决定渲染路径：use_rich = console.is_terminal and not no_rich
    use_rich = console.is_terminal and not args.no_rich

    logger.info("=" * 80)
    logger.info("NL2SQL 父图 CLI 启动")
    logger.info("=" * 80)

    # 检查是否提供了问题
    if args.question:
        # 单次查询模式
        question = " ".join(args.question)
        logger.info("单次查询模式")

        run_single_query(
            question,
            query_id=args.query_id,
            thread_id=args.thread_id,
            user_id=args.user_id,
            use_rich=use_rich,
            interactive=False,
        )
    else:
        # 交互模式
        interactive_mode(
            thread_id=args.thread_id,
            user_id=args.user_id,
            use_rich=use_rich,
        )


if __name__ == "__main__":
    main()
