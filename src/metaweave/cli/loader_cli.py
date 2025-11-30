"""数据加载 CLI 命令

提供统一的数据加载接口，支持将各类元数据文件加载到目标数据库。
"""

import click
import logging
from pathlib import Path
import yaml

from src.metaweave.core.loaders.factory import LoaderFactory
from src.metaweave.utils.file_utils import get_project_root

logger = logging.getLogger("metaweave.cli")


@click.command(name="load")
@click.option(
    "--type",
    "-t",
    "load_type",
    type=click.Choice(["cql", "md", "dim", "sql"], case_sensitive=False),
    required=True,
    help="加载类型：cql(Neo4j CQL) / md(Markdown) / dim(维表数据) / sql(样例SQL)"
)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    default="configs/metaweave/loader_config.yaml",
    show_default=True,
    help="配置文件路径"
)
@click.option(
    "--clean",
    is_flag=True,
    help="加载前清空目标数据库（谨慎使用！）"
)
@click.option(
    "--debug",
    is_flag=True,
    help="启用调试模式"
)
def load_command(load_type: str, config: str, clean: bool, debug: bool):
    """加载元数据到目标数据库

    将 MetaWeave 生成的各类元数据文件加载到对应的数据库中：

    \b
    - cql : 加载 Neo4j Cypher 文件到图数据库（Step 4 生成）
    - md  : 加载 Markdown 表定义到向量数据库（Step 5 生成，未来支持）
    - dim : 加载维表数据到向量数据库（未来支持）
    - sql : 加载样例 SQL 到向量数据库（Step 6 生成，未来支持）

    示例:

    \b
        # 加载 CQL 到 Neo4j（使用默认配置）
        python -m src.metaweave.cli.main load --type cql

    \b
        # 加载前清空数据库（谨慎使用）
        python -m src.metaweave.cli.main load --type cql --clean

    \b
        # 使用自定义配置文件
        python -m src.metaweave.cli.main load --type cql --config my_config.yaml

    \b
        # 启用调试模式
        python -m src.metaweave.cli.main load --type cql --debug
    """
    try:
        # 设置日志级别
        if debug:
            logging.getLogger("metaweave").setLevel(logging.DEBUG)

        # 解析配置文件路径
        config_path = Path(config)
        if not config_path.is_absolute():
            config_path = get_project_root() / config_path

        click.echo(f"📋 加载配置: {config_path}")

        # 检查加载类型是否已实现
        supported_types = LoaderFactory.get_supported_types()
        if load_type not in supported_types:
            click.echo(
                f"⚠️  加载类型 '{load_type}' 尚未实现",
                err=True
            )
            click.echo(f"当前支持的类型: {', '.join(supported_types)}")
            raise click.Abort()

        # 加载配置文件
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 显示警告（如果需要清空数据库）
        if clean:
            click.echo("")
            click.echo("⚠️  警告: 您即将清空目标数据库的所有数据！")
            click.echo("⚠️  此操作不可逆，请确认您知道自己在做什么。")
            click.echo("")
            if not click.confirm("是否继续？"):
                click.echo("操作已取消")
                return

        # 创建加载器
        click.echo(f"🔧 创建加载器: {load_type.upper()}Loader")
        loader = LoaderFactory.create(load_type, config)

        # 执行加载（传递 clean 参数）
        click.echo("")
        click.echo("=" * 60)
        click.echo(f"🚀 开始加载 {load_type.upper()} 数据")
        click.echo("=" * 60)
        click.echo("")

        # 特殊处理 CQLLoader（支持 clean 参数）
        if load_type == "cql":
            # 直接调用 load() 方法，而不是 execute()
            if not loader.validate():
                click.echo("❌ 验证失败", err=True)
                raise click.Abort()

            result = loader.load(clean=clean)
        else:
            result = loader.execute()

        # 显示结果
        click.echo("")
        click.echo("=" * 60)
        click.echo("📊 加载结果")
        click.echo("=" * 60)

        if result.get("success"):
            click.echo(f"✅ 状态: 成功")
            click.echo(f"💬 消息: {result.get('message', '加载完成')}")

            # 显示统计信息（根据加载类型不同）
            if load_type == "cql":
                # CQL 加载器的统计信息
                sections = result.get("sections", [])
                if sections:
                    click.echo(f"📦 执行章节: {len(sections)} 个")
                    for i, section in enumerate(sections, 1):
                        status = "✅" if section.get("success") else "❌"
                        click.echo(f"  {status} [{i}] {section.get('name')}")

            # 显示执行时间
            execution_time = result.get("execution_time")
            if execution_time is not None:
                click.echo(f"⏱️  执行时间: {execution_time}s")

        else:
            click.echo(f"❌ 状态: 失败", err=True)
            click.echo(f"💬 消息: {result.get('message', '未知错误')}", err=True)

            # 显示错误列表
            errors = result.get("errors", [])
            if errors:
                click.echo("")
                click.echo("⚠️  错误详情:")
                for i, error in enumerate(errors[:5], 1):
                    click.echo(f"  [{i}] {error.get('section')}: {error.get('error_message')}", err=True)

                if len(errors) > 5:
                    click.echo(f"  ... 还有 {len(errors) - 5} 个错误", err=True)

        click.echo("=" * 60)

        if result.get("success"):
            click.echo("✨ 加载完成！")
        else:
            click.echo("⚠️  加载失败", err=True)
            raise click.Abort()

    except FileNotFoundError as e:
        logger.error(f"文件不存在: {e}")
        click.echo(f"❌ 错误: 文件不存在 - {e}", err=True)
        raise click.Abort()

    except ValueError as e:
        logger.error(f"配置错误: {e}")
        click.echo(f"❌ 错误: {e}", err=True)
        raise click.Abort()

    except Exception as e:
        logger.error(f"加载失败: {e}", exc_info=debug)
        click.echo(f"❌ 错误: {e}", err=True)
        if debug:
            import traceback
            click.echo("\n" + traceback.format_exc(), err=True)
        raise click.Abort()
