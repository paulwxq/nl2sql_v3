"""API 日志初始化"""

import logging
from pathlib import Path

from src.utils.logger import setup_logging_from_yaml


def init_api_logging() -> logging.Logger:
    """初始化 API 日志（全局 + API 专属）

    对标 CLI 入口 nl2sql_father_cli.py 的做法：
    - setup_logging_from_yaml() 初始化全局日志体系
    - nl2sql.fastapi logger 已在 logging.yaml 中配置
    """
    project_root = Path(__file__).parent.parent.parent.parent
    yaml_path = str(project_root / "src" / "configs" / "logging.yaml")
    setup_logging_from_yaml(yaml_path)

    return logging.getLogger("nl2sql.fastapi")
