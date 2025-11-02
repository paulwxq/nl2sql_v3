"""日志工具模块"""

import logging
import logging.config
import os
from typing import Optional
import yaml
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(
    name: str,
    level: int = logging.DEBUG,  # 改为 DEBUG 级别，记录更详细
    log_file: str = None,
    console: bool = True,
) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        level: 日志级别
        log_file: 日志文件路径（可选）
        console: 是否输出到控制台
        
    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 清除已有的处理器（避免重复）
    logger.handlers.clear()
    
    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # 控制台处理器
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # 文件处理器
    if log_file:
        # 确保日志目录存在
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        日志记录器
    """
    return logging.getLogger(name)


def setup_module_logger(
    module_name: str,
    *,
    log_file: str | None = None,
    level: int = logging.INFO,
    console: bool = True,
    rotate: bool = True,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    为大模块设置独立日志器（名称形如 nl2sql.<module>）。

    Args:
        module_name: 模块名（如 "sql_subgraph"）
        log_file: 日志文件路径（如 "logs/sql_subgraph.log"）。未提供则默认到 logs/<module_name>.log
        level: 日志级别
        console: 是否输出到控制台
        rotate: 是否使用滚动日志（RotatingFileHandler）
        max_bytes: 单文件最大大小（bytes）
        backup_count: 保留历史文件数

    Returns:
        配置完成的模块日志器
    """
    logger_name = f"nl2sql.{module_name}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    # 避免重复添加 handler
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件处理器
    resolved_log_file = log_file or str(Path("logs") / f"{module_name}.log")
    log_path = Path(resolved_log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if rotate:
        file_handler = RotatingFileHandler(
            resolved_log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
    else:
        file_handler = logging.FileHandler(resolved_log_file, encoding="utf-8")

    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_module_logger(module_name: str) -> logging.Logger:
    """
    获取模块日志器（名称形如 nl2sql.<module>）。
    如未先显式 setup，该函数将返回同名 Logger，但不会自动添加处理器。
    """
    return logging.getLogger(f"nl2sql.{module_name}")


class QueryLoggerAdapter(logging.LoggerAdapter):
    """简单的查询上下文适配器：将 [query_id] 前缀加入消息。"""

    def process(self, msg, kwargs):
        query_id = self.extra.get("query_id")
        if query_id:
            msg = f"[{query_id}] {msg}"
        return msg, kwargs


def with_query_id(logger: logging.Logger, query_id: str) -> logging.LoggerAdapter:
    """基于给定 logger 创建带 query_id 前缀的适配器。"""
    return QueryLoggerAdapter(logger, {"query_id": query_id})


def setup_logging_from_yaml(yaml_path: str) -> None:
    """
    从 YAML 文件加载 logging 配置（dictConfig）。
    支持同时输出到控制台与文件，并允许通过 YAML 设置日志级别。
    """
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"Logging config YAML 不存在: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # 确保文件型 handler 的目录存在
    for handler_name, handler_cfg in (cfg.get("handlers", {}) or {}).items():
        filename: Optional[str] = handler_cfg.get("filename")
        if filename:
            log_path = Path(filename)
            log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.config.dictConfig(cfg)

