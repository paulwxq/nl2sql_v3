"""dim_tables 配置生成 CLI 命令。"""

from pathlib import Path
from typing import Optional

import click

from src.metaweave.core.dim_value.config_generator import DimTableConfigGenerator
from src.metaweave.utils.file_utils import get_project_root, load_yaml


@click.command(name="dim_config")
@click.option(
    "--generate",
    "-g",
    "generate",
    is_flag=True,
    required=True,
    help="生成 dim_tables.yaml 配置文件",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True),
    default="configs/metaweave/metadata_config.yaml",
    show_default=True,
    help="metadata_config.yaml 路径",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(),
    default="configs/metaweave/dim_tables.yaml",
    show_default=True,
    help="输出 dim_tables.yaml 路径",
)
def dim_config_command(generate: bool, config_path: str, output_path: str) -> None:
    """生成 dim_tables.yaml（识别 table_category='dim' 的表）。"""

    if not generate:
        click.echo("❌ 请提供 --generate 选项")
        raise click.Abort()

    project_root = get_project_root()
    metadata_path = Path(config_path)
    if not metadata_path.is_absolute():
        metadata_path = project_root / metadata_path

    output_path = Path(output_path)
    if not output_path.is_absolute():
        output_path = project_root / output_path

    metadata_config = load_yaml(metadata_path)
    output_cfg = metadata_config.get("output", {}) if metadata_config else {}
    json_llm_dir = output_cfg.get("json_llm_directory")
    if not json_llm_dir:
        click.echo("❌ metadata_config.yaml 缺少 output.json_llm_directory 配置")
        raise click.Abort()

    json_llm_dir = Path(json_llm_dir)
    if not json_llm_dir.is_absolute():
        json_llm_dir = project_root / json_llm_dir

    # 开始扫描前先打印日志
    click.echo("")
    click.echo("🔍 开始扫描维度表...")
    click.echo(f"📂 扫描目录: {json_llm_dir}")
    click.echo("")

    generator = DimTableConfigGenerator(json_llm_dir=json_llm_dir, output_path=output_path)
    config = generator.generate()

    tables = list(config.get("tables", {}).keys())

    click.echo(f"✅ 已生成 {output_path}")
    click.echo(f"📊 识别到 {len(tables)} 个维度表：")
    for name in tables:
        click.echo(f"  - {name}")

    click.echo("")
    click.echo("⚠️  请手工填写 embedding_col 字段（要向量化的列名）")
    click.echo("")
    if tables:
        sample_table = tables[0]
        click.echo("📝 配置示例：")
        click.echo(f"    {sample_table}:")
        click.echo("      embedding_col: your_text_column             # 单列")
        click.echo("")
        click.echo("    # 多列向量化（同一张表的多个列）：")
        click.echo(f"    {sample_table}:")
        click.echo("      embedding_col: [col1, col2, col3]           # YAML列表（推荐）")
        click.echo("      # 或")
        click.echo("      embedding_col: col1, col2, col3             # 逗号分隔（自动拆分）")


__all__ = ["dim_config_command"]

