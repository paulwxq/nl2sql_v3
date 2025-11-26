"""元数据生成 CLI 命令"""

import click
import logging
from pathlib import Path

from src.metaweave.core.metadata.generator import MetadataGenerator
from src.metaweave.utils.file_utils import get_project_root

logger = logging.getLogger("metaweave.cli")


@click.command(name="metadata")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    required=True,
    help="配置文件路径"
)
@click.option(
    "--schemas",
    "-s",
    type=str,
    help="要处理的 schema 列表（逗号分隔）"
)
@click.option(
    "--tables",
    "-t",
    type=str,
    help="要处理的表名列表（逗号分隔）"
)
@click.option(
    "--incremental",
    "-i",
    is_flag=True,
    help="增量更新模式（仅处理变更的表）"
)
@click.option(
    "--max-workers",
    "-w",
    type=int,
    default=4,
    help="最大并发数（默认: 4）"
)
@click.option(
    "--step",
    type=click.Choice(["ddl", "json", "cql", "md", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="指定要执行的步骤：ddl/json/cql/md 或 all"
)
def metadata_command(
    config: str,
    schemas: str,
    tables: str,
    incremental: bool,
    max_workers: int,
    step: str
):
    """生成数据库元数据
    
    从 PostgreSQL 数据库中提取元数据、生成注释、识别逻辑主键，
    并输出为 DDL、Markdown、JSON 格式。
    
    示例:
    
        metaweave metadata --config configs/metaweave/metadata_config.yaml
        
        metaweave metadata -c config.yaml --schemas public,myschema
        
        metaweave metadata -c config.yaml --tables users,orders --max-workers 8
    """
    try:
        # 解析配置文件路径
        config_path = Path(config)
        if not config_path.is_absolute():
            config_path = get_project_root() / config_path
        
        click.echo(f"📋 加载配置: {config_path}")
        
        # 初始化生成器
        generator = MetadataGenerator(config_path)
        
        # 解析 schemas 和 tables
        schema_list = None
        if schemas:
            schema_list = [s.strip() for s in schemas.split(",")]
            click.echo(f"🎯 指定 Schema: {schema_list}")
        
        table_list = None
        if tables:
            table_list = [t.strip() for t in tables.split(",")]
            click.echo(f"🎯 指定表: {table_list}")
        
        if incremental:
            click.echo("🔄 增量更新模式")
        
        click.echo(f"⚙️  并发数: {max_workers}")
        click.echo(f"🧱 执行步骤: {step.lower()}")
        click.echo("")
        
        # 执行生成
        click.echo("🚀 开始生成元数据...")
        result = generator.generate(
            schemas=schema_list,
            tables=table_list,
            incremental=incremental,
            max_workers=max_workers,
            step=step
        )
        
        # 显示结果
        click.echo("")
        click.echo("=" * 60)
        click.echo("📊 生成结果统计")
        click.echo("=" * 60)
        click.echo(f"✅ 成功处理: {result.processed_tables} 张表")
        
        if result.failed_tables > 0:
            click.echo(f"❌ 处理失败: {result.failed_tables} 张表", err=True)
        
        click.echo(f"💬 生成注释: {result.generated_comments} 个")
        click.echo(f"🔑 识别逻辑主键: {result.logical_keys_found} 个")
        click.echo(f"📁 输出文件: {len(result.output_files)} 个")
        
        if result.errors:
            click.echo(f"\n⚠️  错误列表:")
            for error in result.errors[:5]:
                click.echo(f"  - {error}", err=True)
            if len(result.errors) > 5:
                click.echo(f"  ... 还有 {len(result.errors) - 5} 个错误", err=True)
        
        click.echo("=" * 60)
        
        if result.success:
            click.echo("✨ 元数据生成完成！")
        else:
            click.echo("⚠️  元数据生成完成，但存在错误", err=True)
            raise click.Abort()
    
    except Exception as e:
        logger.error(f"元数据生成失败: {e}")
        click.echo(f"❌ 错误: {e}", err=True)
        raise click.Abort()

