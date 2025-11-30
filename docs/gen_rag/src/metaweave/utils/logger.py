"""MetaWeave 日志工具模块

提供独立的日志配置和获取函数，支持将来模块独立提取。
"""

import logging
import logging.config
from pathlib import Path
from typing import Optional
import yaml


def setup_metaweave_logging(config_path: Optional[str] = None) -> None:
    """初始化 MetaWeave 日志系统

    从 YAML 配置文件加载日志配置。如果未提供配置文件路径，
    使用默认配置 configs/metaweave/logging.yaml。

    Args:
        config_path: 日志配置文件路径（可选）

    Raises:
        FileNotFoundError: 配置文件不存在
    """
    if config_path is None:
        config_path = "configs/metaweave/logging.yaml"

    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"日志配置文件不存在: {config_path}")

    with open(config_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # 确保所有日志文件的目录存在
    for handler_name, handler_cfg in (cfg.get("handlers", {}) or {}).items():
        filename = handler_cfg.get("filename")
        if filename:
            log_path = Path(filename)
            log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.config.dictConfig(cfg)


def get_metaweave_logger(module_name: str) -> logging.Logger:
    """获取 MetaWeave 模块日志器

    Args:
        module_name: 模块名（如 "metadata", "relationships"）

    Returns:
        logging.Logger: 日志器实例（命名: metaweave.<module_name>）

    Examples:
        >>> logger = get_metaweave_logger("metadata")
        >>> logger.info("开始生成元数据")

        >>> logger = get_metaweave_logger("relationships.scorer")
        >>> logger.debug("计算候选评分")
    """
    logger_name = f"metaweave.{module_name}"
    return logging.getLogger(logger_name)
