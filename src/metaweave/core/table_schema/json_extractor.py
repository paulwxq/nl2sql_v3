from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

TIME_TYPE_KEYWORDS = [
    "date",
    "time",
    "datetime",
    "timestamp",
    "timestamptz",
    "interval",
    "year",
]


class JSONExtractor:
    """JSON_LLM 信息提取器。"""

    def __init__(self, json_file: Path):
        self.json_file = json_file
        self.json_data: Dict = {}
        if self.json_file.exists():
            self.json_data = json.loads(self.json_file.read_text(encoding="utf-8"))
        else:
            logger.warning("JSON_LLM 文件不存在: %s", json_file)

    @classmethod
    def from_dict(cls, data: Dict) -> "JSONExtractor":
        extractor = cls.__new__(cls)
        extractor.json_file = Path("<dict>")
        extractor.json_data = data or {}
        return extractor

    def get_table_category(self) -> Optional[str]:
        table_profile = self.json_data.get("table_profile") or {}
        return table_profile.get("table_category")

    def get_time_columns(self) -> List[str]:
        column_profiles: Dict[str, Dict] = self.json_data.get("column_profiles") or {}
        time_cols: List[str] = []

        for col_name, col_profile in column_profiles.items():
            data_type = (col_profile.get("data_type") or "").lower().strip()
            if any(keyword in data_type for keyword in TIME_TYPE_KEYWORDS):
                time_cols.append(col_name)
            elif any(suspicious in data_type for suspicious in ["date", "time"]):
                logger.warning("可疑的未识别时间类型: 列=%s, data_type=%s", col_name, data_type)

        return time_cols

    def format_time_col_hint(self) -> Optional[str]:
        cols = self.get_time_columns()
        return ",".join(cols) if cols else None


__all__ = ["JSONExtractor", "TIME_TYPE_KEYWORDS"]

