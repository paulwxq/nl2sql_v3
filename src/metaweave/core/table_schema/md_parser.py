from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List


COLUMN_PATTERN = re.compile(
    r"^-\s+([\w.-]+)\s+\([^)]+\)\s+-\s+(.+?)(?:\s+\[示例:.*)?$"
)
TABLE_NAME_PATTERN = re.compile(r"^#\s+([\w.]+)")


class MDParser:
    """Markdown 文件解析器，用于提取表描述与字段注释。"""

    def __init__(self, md_file: Path):
        self.md_file = md_file
        self._lines: List[str] = self.md_file.read_text(encoding="utf-8").splitlines()

    @classmethod
    def from_string(cls, content: str) -> "MDParser":
        parser = cls.__new__(cls)
        parser.md_file = Path("<string>")
        parser._lines = content.splitlines()
        return parser

    def get_table_description(self) -> str:
        """返回整份 Markdown 内容（保留原格式）。"""
        return "\n".join(self._lines)

    def get_column_descriptions(self) -> Dict[str, str]:
        """解析“## 字段列表”章节的字段注释。"""
        column_descriptions: Dict[str, str] = {}
        in_field_section = False

        for line in self._lines:
            stripped = line.strip()

            if stripped.startswith("## 字段列表"):
                in_field_section = True
                continue

            # 遇到下一个章节退出
            if in_field_section and stripped.startswith("##"):
                break

            if in_field_section and stripped.startswith("-"):
                match = COLUMN_PATTERN.match(stripped)
                if match:
                    col_name = match.group(1)
                    col_desc = match.group(2).strip()
                    column_descriptions[col_name] = col_desc
                else:
                    # 宽松降级解析："- col (type) - desc [示例: ...]"
                    main_part = stripped.split("[示例", 1)[0].strip()
                    if main_part.startswith("-"):
                        main_part = main_part[1:].strip()
                    if ") - " in main_part:
                        left, desc = main_part.split(") - ", 1)
                        col_name = left.split(" ", 1)[0].strip()
                        if col_name and desc:
                            column_descriptions[col_name] = desc.strip()
                    # 无法解析的行直接跳过

        return column_descriptions

    def extract_table_name(self) -> str:
        """从第一行标题提取 schema.table 名。"""
        if not self._lines:
            raise ValueError(f"文件为空，无法提取表名: {self.md_file}")

        first_line = self._lines[0].strip()
        match = TABLE_NAME_PATTERN.match(first_line)
        if not match:
            raise ValueError(f"无法从 MD 第一行提取表名: {first_line}")
        return match.group(1)


__all__ = ["MDParser", "COLUMN_PATTERN", "TABLE_NAME_PATTERN"]

