"""基于日志的 sq2 时序分析测试。

目的：
- 固化 q_777b0b84 这次 Complex Path 运行的关键结论
- 不依赖线上服务，不修改生产代码
- 通过日志确认 sq2 的主要耗时区间
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


LOG_PATH = Path("logs/nl2sql.log")
QUERY_ID = "q_777b0b84"


def _load_all_lines() -> list[str]:
    return LOG_PATH.read_text(encoding="utf-8").splitlines()


def _load_query_lines(query_id: str) -> list[str]:
    return [line for line in _load_all_lines() if f"[{query_id}]" in line]


def _find_line(lines: list[str], needle: str) -> str:
    for line in lines:
        if needle in line:
            return line
    raise AssertionError(f"未找到日志行: {needle}")


def _parse_ts(line: str) -> datetime:
    ts_text = line.split(" - ", 1)[0]
    return datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S")


def test_sq2_log_confirms_main_latency_is_sql_generation_llm_wait():
    lines = _load_query_lines(QUERY_ID)
    all_lines = _load_all_lines()

    assert lines, f"日志中未找到 query_id={QUERY_ID}"

    # sq2 的关键阶段
    parsing_done = _find_line(lines, "rewritten_query=查询高速服务区 ID 为 8eb8ec693642354a62d640c7f1c2365c 的驿购源系统中的服务区编码")
    retrieval_done = _find_line(lines, "Schema 检索完成，耗时 1.04 秒")
    llm_call_start = _find_line(all_lines, "调用 LLM 生成 SQL...")
    llm_done = _find_line(lines, "SQL生成完成（第 1 次）")
    subgraph_done = _find_line(lines, "子图执行完成，耗时 274.88秒")

    parsing_done_ts = _parse_ts(parsing_done)
    retrieval_done_ts = _parse_ts(retrieval_done)
    llm_call_start_ts = _parse_ts(llm_call_start)
    llm_done_ts = _parse_ts(llm_done)
    subgraph_done_ts = _parse_ts(subgraph_done)

    # 解析和检索都很快
    assert (retrieval_done_ts - parsing_done_ts).total_seconds() <= 2

    # 主要时间消耗在 SQL Generation 的 LLM 调用等待
    llm_wait_seconds = (llm_done_ts - llm_call_start_ts).total_seconds()
    assert llm_wait_seconds >= 240, f"预期 LLM 等待明显偏长，实际仅 {llm_wait_seconds}s"

    # 子图总耗时与 LLM 等待接近，说明瓶颈不在验证或 SQL 执行
    total_subgraph_seconds = (subgraph_done_ts - _parse_ts(_find_line(lines, "开始执行 SQL 生成子图"))).total_seconds()
    assert total_subgraph_seconds >= 240


def test_sq2_log_confirms_placeholder_was_resolved_before_summarizer():
    lines = _load_query_lines(QUERY_ID)
    all_lines = _load_all_lines()

    rewritten_line = _find_line(
        lines,
        "rewritten_query=查询高速服务区 ID 为 8eb8ec693642354a62d640c7f1c2365c 的驿购源系统中的服务区编码",
    )
    summarizer_title_line = _find_line(
        all_lines,
        "【查询高速服务区 ID 为 8eb8ec693642354a62d640c7f1c2365c 的驿购源系统中的服务区编码】",
    )

    assert "{{sq1.result}}" not in rewritten_line
    assert "{{sq1.result}}" not in summarizer_title_line


def test_sq2_log_confirms_final_sql_and_result_are_correct():
    lines = _load_query_lines(QUERY_ID)
    all_lines = _load_all_lines()

    sql_line = _find_line(all_lines, "AND mapper.source_system_type = '驿购'")
    result_line = _find_line(lines, "SQL执行成功，返回 1 行，耗时 2ms")
    summary_line = _find_line(lines, "LLM 生成总结成功（attempt=1）")

    assert "驿购" in sql_line
    assert "返回 1 行" in result_line
    assert "attempt=1" in summary_line
