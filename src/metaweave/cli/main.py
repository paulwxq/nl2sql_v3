"""MetaWeave CLI 主入口

提供命令行接口访问 MetaWeave 各个功能模块。
"""

import click
import logging
from pathlib import Path
from typing import Optional

from src.metaweave.cli.metadata_cli import metadata_command
from src.metaweave.cli.loader_cli import load_command
from src.metaweave.cli.dim_config_cli import dim_config_command
from src.metaweave.utils.logger import setup_metaweave_logging


@click.group()
@click.option(
    "--debug",
    is_flag=True,
    help="启用调试模式"
)
@click.option(
    "--log-config",
    type=click.Path(exists=True),
    help="日志配置文件路径"
)
def cli(debug: bool, log_config: Optional[str]):
    """MetaWeave - 数据库元数据自动生成和增强平台
    
    使用子命令访问不同的功能模块。
    """
    # 初始化日志系统（MetaWeave 专用配置）
    try:
        setup_metaweave_logging(log_config)
    except FileNotFoundError as exc:
        # 回退到最简单的配置，至少不会阻塞 CLI
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        click.echo(f"⚠️  日志配置文件不存在: {exc}", err=True)
    else:
        # 根据 --debug 动态提升控制台输出等级
        if debug:
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.DEBUG)
            for handler in root_logger.handlers:
                handler.setLevel(logging.DEBUG)



# 注册子命令
cli.add_command(metadata_command)
cli.add_command(load_command)
cli.add_command(dim_config_command)


if __name__ == "__main__":
    cli()

