# 77_CLI界面Rich优化设计

## 文档信息
- **创建日期**: 2026-03-05
- **状态**: 待实施
- **目标**: 引入 `rich` 库对 `scripts/nl2sql_father_cli.py` 进行终端界面的现代化改造，提升视觉美感、信息层级和交互体验。

---

## 1. 背景与目标

当前 `nl2sql_father_cli.py` 使用原生的 `print()` 和 `input()` 进行交互，输出信息虽然全面，但在复杂查询（包含长 SQL、多列数据结果、长总结）时，终端文本容易混杂在一起，难以快速提取关键信息。

**优化目标**：
1. **美观性**：使用颜色、边框、表格和代码高亮。
2. **结构化**：将元数据、SQL、数据结果和总结等不同性质的信息进行视觉隔离。
3. **交互体验**：增加加载动画（Spinner），缓解等待时的焦虑感。
4. **非侵入式**：仅修改 CLI 的展示层，不触碰核心业务逻辑（`run_nl2sql_query` 等）。

### 1.1 改造约束

- **删除 `--json` 参数**：当前 CLI 的 `--json` 参数将 `run_nl2sql_query()` 返回的 Python dict 用 `json.dumps` 序列化后打印到 stdout。该参数没有实际消费方（无脚本、CI 或其他代码使用其输出），且未来 FastAPI 的 JSON 响应格式会独立设计，与 CLI 的输出格式无关。本次改造中删除该参数及其相关代码分支。
- **非 TTY 环境自动降级**：当 stdout 被重定向到管道或文件时（CI、`> output.txt`），Rich 的 spinner、颜色、边框等均不适合输出。实现策略：
  - 使用 `Console()` 默认构造（不传 `force_terminal`），并通过统一判断 `use_rich = console.is_terminal and not no_rich` 决定渲染路径：`use_rich=True` 走 Rich 渲染，`use_rich=False` 走 legacy `print()` 分支。这意味着非 TTY 环境（`console.is_terminal == False`）会**自动**回退到 legacy 路径，与 `--no-rich` 等效。
  - 额外提供 `--no-rich` 命令行参数，允许用户在 TTY 环境下也强制使用纯文本输出。`--no-rich` 表示**完全不走 Rich 渲染**，回退到改造前的 legacy `print()` 分支（即保留原有的 `print_result`、`print_separator` 等函数作为降级路径）。不使用 `Console(no_color=True)` 这种"半 Rich"方案，因为它仍然会输出 Panel/Table 的 ASCII 边框字符。

---

## 2. 界面布局与颜色设计

### 2.1 颜色与风格定义
借助 Rich 的标记语法，设定统一的主题色：
- **用户输入与提示**：绿色 `[bold green]`
- **系统加载状态**：黄色 `[bold yellow]` + Spinner 动画
- **成功与重要结论**：亮绿色 `[bold bright_green]`
- **错误与警告**：红色 `[bold red]`
- **面板边框与标题**：蓝色 `[bold blue]` 或 青色 `[cyan]`
- **次要信息（如耗时）**：暗色 `[dim]`

### 2.2 核心展示模块设计

根据返回的 `result` 字典（由 `extract_final_result()` 生成），将输出界面划分为以下几个结构化模块：

> **空值兜底规则**：各模块渲染前应检查数据是否为空（`None`、空字符串、空列表）。数据为空时**跳过该模块**，不渲染空 Panel/Table。唯一例外是模块 B（Summary），若 `summary` 为空则显示默认文案 `"（无总结信息）"`。

#### 模块 A：查询元数据 (Metadata)
- **组件**: `rich.table.Table` (无边框 `box=None` 或 极简边框 `box.SIMPLE`)
- **内容**:
  - Query ID, Thread ID, User ID
  - 复杂度 (Complexity) & 实际执行路径 (Path Taken)
- **视觉**: 使用青色作为 Key，白色作为 Value，两列对齐显示。

#### 模块 B：总结信息 (Summary)
- **组件**: `rich.panel.Panel`
- **内容**: `result['summary']`
- **视觉**: `border_style="green"`, 标题为 `"[bold green]💬 最终总结[/bold green]"`。若总结中包含简单的 Markdown 格式（如粗体），可以使用 `rich.markdown.Markdown` 进行渲染。

#### 模块 C：生成的 SQL (SQL Generation)
- **组件**: `rich.panel.Panel` 包裹 `rich.syntax.Syntax`
- **内容**:
  - **Fast Path（单子查询）**：展示 `result['sql']`（快捷字段，仅单子查询时有值）。
  - **Complex Path（多子查询）**：`result['sql']` 为 `None`，需遍历 `result['sub_queries']`，逐个展示每个子查询的 `sq['validated_sql']`，标题附带 `sq['sub_query_id']`。
- **视觉**:
  - `Syntax` 开启 SQL 语法高亮，`theme="monokai"`，显示行号 `line_numbers=True`。
  - `Panel` 标题为 `"[bold blue]📝 执行的 SQL[/bold blue]"`, `border_style="blue"`。
  - 多子查询时，每个子查询使用独立的 Panel，标题包含子查询 ID。

#### 模块 D：执行结果数据 (Execution Results)
- **组件**: `rich.table.Table`
- **内容**: 针对成功的 SQL 查询，展示返回的列名和前 N 行数据。
- **数据来源**: `result['execution_results']` 列表，每个元素包含 `sub_query_id`、`success`、`columns`、`rows`、`row_count`、`error` 等字段。
- **视觉**:
  - 表头加粗并带有颜色。
  - 行数据交替颜色（可选）以提升可读性。
  - 如果某个 `exec_result['rows']` 行数较多，仅展示前 5 行，在表格下方用文本提示 `... (共 N 行数据，仅展示前 5 行)`。
  - 若执行失败（`exec_result['success'] == False`），使用红色的 `Panel` 显示 `exec_result['error']`。
  - 多个执行结果时，逐个渲染，标题附带 `sub_query_id`。

#### 模块 D'：顶层错误面板 (Top-level Error)
- **触发条件**: `result['error']` 非空 **且** `result['execution_results']` 为空列表。
  - 典型场景：SQL 生成失败（未进入执行阶段）、Router 异常、Planner 异常等。
  - 此时模块 C 和模块 D 均无内容可渲染，需要一个独立的错误展示。
- **组件**: `rich.panel.Panel`
- **视觉**: `border_style="red"`, 标题为 `"[bold red]❌ 错误信息[/bold red]"`，内容为 `result['error']`。
- **与模块 B 的关系**: 模块 B（Summary）侧重自然语言总结，可能包含友好的错误说明；模块 D' 展示原始技术错误信息，两者互补，不替代。

#### 模块 E：性能指标 (Performance Metrics)
- **组件**: 简单的 `rich.text.Text`
- **内容**:
  - 通用指标：总耗时 (`metadata['total_execution_time_ms']`)、Router 延迟 (`metadata['router_latency_ms']`)。
  - Phase 2 指标（Complex Path 时额外展示）：Planner 延迟 (`metadata['planner_latency_ms']`)、并发执行数 (`metadata['parallel_execution_count']`)、子查询总数 (`metadata['sub_query_count']`)。
- **视觉**: 右对齐或左对齐，颜色使用 `[dim]` 或 `[italic]` 降低视觉权重，不喧宾夺主。

---

## 3. 交互流程优化 (Interactive Mode)

### 3.1 启动与欢迎界面
使用一个大型的 Panel 作为欢迎横幅。
```python
from rich.panel import Panel
console.print(Panel(
    "欢迎使用！我可以帮您执行完整的 NL2SQL 流程：\n"
    "Router → Simple Planner → SQL Gen → SQL Exec → Summarizer\n\n"
    "💡 [bold]提示[/bold]:\n"
    "  - 直接输入问题，按回车提交\n"
    "  - 输入 'exit' 或 'quit' 退出",
    title="🤖 [bold blue]NL2SQL 交互式测试终端[/bold blue]",
    border_style="blue",
    expand=False
))
```

### 3.2 输入与等待
- **用户输入**：使用 `console.input()` 配合 Rich 标记渲染提示文本。

  > **技术说明**：`Console.input()` 内部调用 Python 内置 `input()`（源码：`rich/console.py`），因此完全兼容 `readline` 模块的行编辑和历史记录功能（上箭头回溯）。当前 CLI 已 `import readline`，改造后此行为保持不变。`Prompt.ask()` 最终也走 `Console.input()`，两者等价。

  ```python
  # 方式 1：直接使用 console.input()
  console.print("[bold green]👤 您的问题[/bold green]", end="")
  question = console.input(": ")

  # 方式 2：使用 Prompt.ask（封装更完整，支持 default/choices）
  from rich.prompt import Prompt
  question = Prompt.ask("\n[bold green]👤 您的问题[/bold green]")
  ```

- **加载状态**：使用 `console.status`，但需显式判断是否启用 spinner（非 TTY 或 `--no-rich` 时跳过）：
  ```python
  use_spinner = console.is_terminal and not no_rich

  if use_spinner:
      result = _run_with_spinner(console, run_nl2sql_query, ...)
  else:
      # 非 TTY / --no-rich：直接调用
      # 仅交互模式打印静态提示；单次命令模式省略，避免重定向输出中的噪音
      # interactive: bool 参数，由调用方传入（interactive_mode 传 True，run_single_query 传 False）
      if interactive:
          print("🔄 正在执行 NL2SQL 分析与查询...")
      result = run_nl2sql_query(...)
  ```
  TTY 环境下用户会看到旋转动画；非 TTY 交互模式输出一行静态提示；单次命令模式（含重定向）不输出任何额外状态文本。

### 3.3 Spinner 与日志输出冲突处理

**问题**：当前日志配置（`src/configs/logging.yaml`）的 console handler 输出到 `sys.stdout`。`console.status` 的 spinner 动画也使用 stdout 进行 Live rendering。两者在同一个 stdout 上交错，会导致 spinner 动画被日志文本打断、终端显示混乱。

**解决方案**：在 spinner 运行期间，临时将写到 stdout 的 console handler 级别提升到 `WARNING`，屏蔽 `INFO`/`DEBUG` 日志对终端的干扰。spinner 结束后恢复原级别。

注意：项目的业务日志走 `nl2sql` logger 且 `propagate: false`（`logging.yaml:24-27`），不会冒泡到 root logger。因此必须同时处理 `nl2sql` logger 和 root logger 上挂载的 stdout handler，才能完全压住终端日志输出。若后续新增其他 `propagate: false` 且直挂 stdout handler 的 logger，需将其名称加入 `_collect_stdout_handlers` 的遍历列表。

```python
import logging
import sys

def _collect_stdout_handlers():
    """收集所有写到 stdout 的 StreamHandler（跨 nl2sql 和 root logger，按 id 去重）

    nl2sql 和 root logger 可能引用同一个 console handler 实例，
    用 dict 按 id(handler) 去重，避免重复 set/restore 级别。
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

def _run_with_spinner(console, query_func, *args, **kwargs):
    """在 spinner 运行期间临时屏蔽 INFO 日志到终端"""
    stdout_handlers = _collect_stdout_handlers()

    original_levels = {}
    for h in stdout_handlers:
        original_levels[h] = h.level
        h.setLevel(logging.WARNING)

    try:
        with console.status("[bold yellow]🔄 正在执行 NL2SQL 分析与查询...[/bold yellow]", spinner="dots"):
            result = query_func(*args, **kwargs)
        return result
    finally:
        # 恢复原级别
        for h, level in original_levels.items():
            h.setLevel(level)
```

> **注意**：spinner 期间的 INFO/DEBUG 日志仍然会写入日志文件（`sql_subgraph_file` handler 不受影响），不会丢失，只是不在终端显示。

---

## 4. 实施修改步骤

1. **确认依赖**：`pyproject.toml` 已包含 `rich>=14.3.3`，确认版本满足本方案所需特性（`Console.status`、`Table`、`Panel` 等），无需额外添加。
2. **重构为 Rich 主路径 + legacy 降级路径并存**：
   - 将原有的 `print_result`、`print_separator` 重命名为 `_print_result_legacy`、`_print_separator_legacy`，保留作为 `--no-rich` 的降级路径。
   - 新增 `_print_result_rich(console, result)` 函数，引入 `Console`，按上述模块 (A~E) 逐一构建 Rich 对象并渲染。
   - 注意处理 Fast Path（单子查询）和 Complex Path（多子查询）两种场景。
   - 在调用处根据 `use_rich = console.is_terminal and not no_rich` 选择路径（非 TTY 自动走 legacy）。
3. **重构交互逻辑**：
   - 修改 `interactive_mode` 和 `run_single_query` 中的 `print` 调用，改用 `console.print`。
   - 引入 `console.input()` 或 `Prompt.ask` 替代原生 `input()`。
   - 引入 `console.status` spinner（需配合 3.3 的日志冲突处理）。
   - 增加对异常 (`Exception`) 的优美展示（如使用 `console.print_exception()` 或自定义红色面板）。
4. **删除 `--json` 参数**：
   - 删除 `argparse` 中的 `--json` 参数定义及其对应的 `json.dumps` + `print` 代码分支。
5. **添加 `--no-rich` 参数**：
   - 在 `argparse` 中添加 `--no-rich` 标志。
   - 启用时完全跳过 Rich 渲染，调用步骤 2 中保留的 `_print_result_legacy` 等降级函数。
6. **处理中文字符排版**：
   - `rich` 的 `Table` 组件在渲染中文字符时有时会有对齐问题。如遇对齐错位，可检查终端字体是否为等宽字体（推荐 Nerd Font 系列），或尝试设置 `Console(width=...)` 手动指定宽度。

---

## 5. 预期视觉效果模拟

```text
╭────────────────── 🤖 NL2SQL 交互式测试终端 ───────────────────╮
│ 欢迎使用！我可以帮您执行完整的 NL2SQL 流程...               │
╰─────────────────────────────────────────────────────────────╯

👤 您的问题: 广州市的京东便利店销售额是多少？

(🔄 正在执行 NL2SQL 分析与查询...) # 带有动态旋转效果

🆔 Query ID    : q_a1b2c3d4
🔗 Thread ID   : guest:20250305T123456000Z
🏷️ 复杂度      : simple
🛤️ 执行路径    : fast

╭──────────────────────── 💬 最终总结 ────────────────────────╮
│ 广州市的京东便利店总销售额为 1,234,567 元。                 │
╰─────────────────────────────────────────────────────────────╯

╭──────────────────────── 📝 执行的 SQL ────────────────────────╮
│ 1 │ SELECT SUM(amount) AS total_sales                       │
│ 2 │ FROM public.fact_store_sales_day fssd                   │
│ 3 │ INNER JOIN public.dim_store ds ON fssd.store_id = ...   │
│ 4 │ WHERE ds.store_type_name = '京东便利'                   │
│ 5 │   AND ds.city_name = '广州市';                          │
╰─────────────────────────────────────────────────────────────╯

📊 执行结果:
┏━━━━━━━━━━━━━━┓
┃ total_sales  ┃
┡━━━━━━━━━━━━━━┩
│ 1234567.00   │
└──────────────┘

⏱️ 总耗时: 1540ms | Router 延迟: 230ms
```

---

## 6. 实施验收清单

以下 6 个场景为最小验收集，实施完成后逐项手动验证：

| # | 场景 | 执行方式 | 预期表现 |
|---|------|----------|----------|
| 1 | TTY + Rich（默认） | `python scripts/nl2sql_father_cli.py "查询销售额"` | Panel/Table/Syntax 高亮、spinner 动画正常 |
| 2 | TTY + `--no-rich` | `python scripts/nl2sql_father_cli.py --no-rich "查询销售额"` | 走 legacy `print()` 路径，无边框/颜色/spinner |
| 3 | 非 TTY 重定向 | `python scripts/nl2sql_father_cli.py "查询销售额" > out.txt` | 输出纯文本（与 `--no-rich` 等效），文件内无 ANSI 转义码 |
| 4 | 交互模式 | `python scripts/nl2sql_father_cli.py`（无参数） | 欢迎面板、`readline` 历史导航正常、spinner 正常、多轮对话正常 |
| 5 | 单次查询模式 | `python scripts/nl2sql_father_cli.py "查询销售额"` | 执行完输出结果后正常退出，无多余提示 |
| 6 | 异常路径 | 断开数据库后执行查询 | 显示红色错误面板（Rich）或错误文本（legacy），不抛未捕获异常 |
| 7 | Complex Path（多子查询） | 输入需要拆分的复杂问题（如"对比广州和深圳的销售额"） | 模块 C 渲染多个 SQL Panel、模块 D 渲染多个结果 Table、模块 E 显示 Phase 2 指标（子查询数、并发数） |
| 8 | `--verbose` + spinner 日志恢复 | `python scripts/nl2sql_father_cli.py -v "查询销售额"` | spinner 期间终端无 INFO 日志干扰；spinner 结束后 DEBUG/INFO 日志恢复正常输出，未被永久抑制 |
