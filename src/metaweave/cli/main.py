"""MetaWeave CLI 主入口

提供命令行接口访问 MetaWeave 各个功能模块。
"""

import click
import logging
from pathlib import Path

from src.metaweave.cli.metadata_cli import metadata_command


@click.group()
@click.option(
    "--debug",
    is_flag=True,
    help="启用调试模式"
)
def cli(debug: bool):
    """MetaWeave - 数据库元数据自动生成和增强平台
    
    使用子命令访问不同的功能模块。
    """
    # 设置日志级别
    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )


# 注册子命令
cli.add_command(metadata_command)


if __name__ == "__main__":
    cli()

