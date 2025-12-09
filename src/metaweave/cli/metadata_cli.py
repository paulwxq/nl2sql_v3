"""元数据生成 CLI 命令"""

import click
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
import yaml

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
    type=click.Choice(["ddl", "json", "json_llm", "cql", "cql_llm", "md", "rel", "rel_llm", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="指定要执行的步骤：ddl/json/json_llm/cql/cql_llm/md/rel/rel_llm 或 all"
)
@click.option(
    "--domain",
    type=str,
    default=None,
    flag_value="all",
    help="启用 domain 功能。不传值或传 'all' 表示使用所有 domain；传 'A,B' 表示只使用指定 domain"
)
@click.option(
    "--domains-config",
    type=click.Path(exists=False),
    default="configs/metaweave/db_domains.yaml",
    help="业务主题配置文件路径（默认：configs/metaweave/db_domains.yaml）"
)
@click.option(
    "--generate-domains",
    is_flag=True,
    default=False,
    help="根据 db_domains.yaml 中的 database.description 自动生成 domains 列表"
)
@click.option(
    "--cross-domain",
    is_flag=True,
    default=False,
    help="是否包含跨域关系。可与 --domain 一起使用，也可单独使用（只生成跨域关系）"
)
@click.option(
    "--md-context",
    is_flag=True,
    default=False,
    help="生成 domains 时附加 md 目录摘要"
)
@click.option(
    "--md-context-dir",
    type=click.Path(exists=False),
    default="output/metaweave/metadata/md",
    help="md 摘要目录（默认：output/metaweave/metadata/md）"
)
@click.option(
    "--md-context-mode",
    type=click.Choice(["name", "name_comment", "full"], case_sensitive=False),
    default="name_comment",
    show_default=True,
    help="md 摘要模式：name 仅表名；name_comment 表名+首行；full 全文"
)
@click.option(
    "--md-context-limit",
    type=int,
    default=100,
    show_default=True,
    help="md 文件数量上限，超出截断"
)
def metadata_command(
    config: str,
    schemas: str,
    tables: str,
    incremental: bool,
    max_workers: int,
    step: str,
    domain: Optional[str],
    domains_config: str,
    generate_domains: bool,
    cross_domain: bool,
    md_context: bool,
    md_context_dir: str,
    md_context_mode: str,
    md_context_limit: int,
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
        def _load_yaml(path: Path) -> Dict:
            if not path.exists():
                return {}
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

        def _parse_domain_filter(domain_value: Optional[str]) -> Optional[List[str]]:
            if not domain_value:
                return None
            lower = domain_value.lower()
            if lower == "all":
                return ["all"]
            return [d.strip() for d in domain_value.split(",") if d.strip()]

        # 解析配置文件路径
        config_path = Path(config)
        if not config_path.is_absolute():
            config_path = get_project_root() / config_path

        click.echo(f"📋 加载配置: {config_path}")

        # 参数校验
        if generate_domains and domain:
            raise click.UsageError("--generate-domains 和 --domain 不能同时使用，请分两步执行")

        domains_config_path = Path(domains_config)
        if not domains_config_path.is_absolute():
            domains_config_path = get_project_root() / domains_config_path
        db_domains_config: Optional[Dict] = None

        if domain or cross_domain:
            if not domains_config_path.exists():
                raise click.UsageError(f"错误：{domains_config} 文件不存在，无法使用 --domain/--cross-domain")
            db_domains_config = _load_yaml(domains_config_path)
            domains_list = db_domains_config.get("domains", [])
            if not domains_list:
                raise click.UsageError(f"错误：{domains_config} 中 domains 列表为空，请先执行 --generate-domains")

        if generate_domains:
            if not domains_config_path.exists():
                raise click.UsageError(f"错误：{domains_config} 文件不存在，请先创建并填写 database.description")
            db_domains_config = _load_yaml(domains_config_path)
            description = db_domains_config.get("database", {}).get("description", "")
            if not description or not description.strip():
                raise click.UsageError("错误：database.description 为空，无法生成 domains 列表")

        # generate-domains 可独立执行（不依赖 step）
        if generate_domains and step != "json_llm":
            from src.metaweave.core.metadata.domain_generator import DomainGenerator
            from src.services.config_loader import load_config

            config = load_config(config_path)
            md_dir = Path(md_context_dir)
            if not md_dir.is_absolute():
                md_dir = get_project_root() / md_dir

            generator = DomainGenerator(
                config=config,
                yaml_path=str(domains_config_path),
                md_context=md_context,
                md_context_dir=str(md_dir),
                md_context_mode=md_context_mode,
                md_context_limit=md_context_limit,
            )
            domains = generator.generate_from_description()
            generator.write_to_yaml(domains)
            click.echo(f"✅ 已生成 {len(domains)} 个 domain 并写入 {domains_config_path}")
            return

        domain_filter = _parse_domain_filter(domain)

        # Step: json_llm - 简化版 JSON 生成
        if step == "json_llm":
            from src.metaweave.core.metadata.llm_json_generator import LLMJsonGenerator
            from src.metaweave.core.metadata.connector import DatabaseConnector
            from src.services.config_loader import load_config
            from src.metaweave.core.metadata.domain_generator import DomainGenerator

            click.echo("📦 开始生成简化版 JSON（json_llm）...")
            click.echo("")

            # 加载配置
            config = load_config(config_path)

            # generate-domains 单独执行
            if generate_domains:
                md_dir = Path(md_context_dir)
                if not md_dir.is_absolute():
                    md_dir = get_project_root() / md_dir
                generator = DomainGenerator(
                    config=config,
                    yaml_path=str(domains_config_path),
                    md_context=md_context,
                    md_context_dir=str(md_dir),
                    md_context_mode=md_context_mode,
                    md_context_limit=md_context_limit,
                )
                domains = generator.generate_from_description()
                generator.write_to_yaml(domains)
                click.echo(f"✅ 已生成 {len(domains)} 个 domain 并写入 {domains_config_path}")
                return
            
            # 初始化连接器和生成器
            connector = DatabaseConnector(config.get("database", {}))
            generator = LLMJsonGenerator(
                config=config,
                connector=connector,
                include_domains=bool(domain),
                domain_filter=domain_filter,
                db_domains_config=db_domains_config
            )
            
            # DDL 目录
            output_config = config.get("output", {})
            output_dir = output_config.get("output_dir", "output/metaweave/metadata")
            ddl_dir = get_project_root() / output_dir / "ddl"
            
            if not ddl_dir.exists():
                raise FileNotFoundError(
                    f"DDL 目录不存在: {ddl_dir}\n"
                    f"请先执行 --step ddl 生成 DDL 文件"
                )
            
            # 生成简化版 JSON
            count = generator.generate_all_from_ddl(ddl_dir)
            
            # 显示结果
            click.echo("")
            click.echo("=" * 60)
            click.echo("📊 简化版 JSON 生成结果")
            click.echo("=" * 60)
            click.echo(f"✅ 生成文件: {count} 个")
            click.echo(f"📁 输出目录: {generator.output_dir}")
            click.echo("=" * 60)
            click.echo("✨ 简化版 JSON 生成完成！")
            
            return

        # Step: rel_llm - LLM 辅助关系发现
        if step == "rel_llm":
            from src.metaweave.core.relationships.llm_relationship_discovery import LLMRelationshipDiscovery
            from src.metaweave.core.metadata.connector import DatabaseConnector
            from src.services.config_loader import load_config

            click.echo("🤖 开始 LLM 辅助关系发现（rel_llm）...")
            click.echo("")

            # 加载配置
            config = load_config(config_path)
            
            # 初始化连接器
            connector = DatabaseConnector(config.get("database", {}))
            
            # 初始化发现器
            discovery = LLMRelationshipDiscovery(
                config=config,
                connector=connector,
                domain_filter=domain,
                cross_domain=cross_domain,
                db_domains_config=db_domains_config
            )
            
            # 检查 json_llm 目录
            if not discovery.json_llm_dir.exists():
                raise FileNotFoundError(
                    f"json_llm 目录不存在: {discovery.json_llm_dir}\n"
                    f"请先执行 --step json_llm 生成简化版 JSON"
                )
            
            # 发现关系
            result = discovery.discover()
            
            # 输出结果文件
            output_config = config.get("output", {})
            rel_dir = get_project_root() / output_config.get("rel_directory", "output/metaweave/metadata/rel")
            rel_dir.mkdir(parents=True, exist_ok=True)
            
            output_file = rel_dir / "relationships_global.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            # 显示结果
            click.echo("")
            click.echo("=" * 60)
            click.echo("📊 LLM 辅助关系发现结果")
            click.echo("=" * 60)
            stats = result.get("statistics", {})
            click.echo(f"✅ 总关系数: {stats.get('total_relationships_found', 0)} 个")
            click.echo(f"  - 物理外键: {stats.get('foreign_key_relationships', 0)}")
            click.echo(f"  - LLM 推断: {stats.get('llm_assisted_relationships', 0)}")
            click.echo(f"📁 输出文件: {output_file}")
            click.echo("=" * 60)
            click.echo("✨ LLM 辅助关系发现完成！")
            
            return

        # Step: cql_llm - CQL 生成（LLM 流程）
        if step == "cql_llm":
            from src.metaweave.core.cql_generator.generator import CQLGenerator

            click.echo("🔧 开始生成 Neo4j CQL（LLM 流程）...")
            click.echo("")

            generator = CQLGenerator(config_path)
            
            # 覆盖 json_dir 为 json_llm 目录
            json_llm_dir = generator._resolve_path(
                generator.config.get("output", {}).get("json_llm_directory", "output/metaweave/metadata/json_llm")
            )
            
            # 检查 json_llm 目录是否存在
            if not json_llm_dir.exists():
                raise FileNotFoundError(
                    f"json_llm 目录不存在: {json_llm_dir}\n"
                    f"请先执行 --step json_llm 生成简化版 JSON"
                )
            
            generator.json_dir = json_llm_dir
            logger.info(f"cql_llm: 使用 json_llm 目录: {json_llm_dir}")
            
            result = generator.generate()

            # 显示结果统计
            click.echo("")
            click.echo("=" * 60)
            click.echo("📊 CQL 生成结果统计（LLM 流程）")
            click.echo("=" * 60)
            click.echo(f"✅ 表节点: {result.tables_count} 个")
            click.echo(f"✅ 列节点: {result.columns_count} 个")
            click.echo(f"✅ 关系: {result.relationships_count} 个")
            click.echo(f"📁 输出文件: {len(result.output_files)} 个")

            for file_path in result.output_files:
                click.echo(f"  - {Path(file_path).name}")

            if result.errors:
                click.echo(f"\n⚠️  错误列表:")
                for error in result.errors[:5]:
                    click.echo(f"  - {error}", err=True)
                if len(result.errors) > 5:
                    click.echo(f"  ... 还有 {len(result.errors) - 5} 个错误", err=True)

            click.echo("=" * 60)

            if result.success:
                click.echo("✨ CQL 生成完成（LLM 流程）！")
            else:
                click.echo("⚠️  CQL 生成完成，但存在错误", err=True)
                raise click.Abort()

            return

        # Step 4: CQL 生成
        if step == "cql":
            from src.metaweave.core.cql_generator.generator import CQLGenerator

            click.echo("🔧 开始生成 Neo4j CQL...")
            click.echo("")

            generator = CQLGenerator(config_path)
            result = generator.generate()

            # 显示结果统计
            click.echo("")
            click.echo("=" * 60)
            click.echo("📊 CQL 生成结果统计")
            click.echo("=" * 60)
            click.echo(f"✅ 表节点: {result.tables_count} 个")
            click.echo(f"✅ 列节点: {result.columns_count} 个")
            click.echo(f"✅ 关系: {result.relationships_count} 个")
            click.echo(f"📁 输出文件: {len(result.output_files)} 个")

            for file_path in result.output_files:
                click.echo(f"  - {Path(file_path).name}")

            if result.errors:
                click.echo(f"\n⚠️  错误列表:")
                for error in result.errors[:5]:
                    click.echo(f"  - {error}", err=True)
                if len(result.errors) > 5:
                    click.echo(f"  ... 还有 {len(result.errors) - 5} 个错误", err=True)

            click.echo("=" * 60)

            if result.success:
                click.echo("✨ CQL 生成完成！")
            else:
                click.echo("⚠️  CQL 生成完成，但存在错误", err=True)
                raise click.Abort()

            return

        # Step 3: 关系发现
        if step == "rel":
            from src.metaweave.core.relationships.pipeline import RelationshipDiscoveryPipeline

            click.echo("🔗 开始关系发现...")
            click.echo("")

            pipeline = RelationshipDiscoveryPipeline(config_path)
            result = pipeline.discover()

            # 显示结果统计
            click.echo("")
            click.echo("=" * 60)
            click.echo("📊 关系发现结果统计")
            click.echo("=" * 60)
            click.echo(f"✅ 发现关系: {result.total_relations} 个")
            click.echo(f"  - 外键直通: {result.foreign_key_relations}")
            click.echo(f"  - 推断关系: {result.inferred_relations}")
            click.echo(f"  - 高置信度: {result.high_confidence_count}")
            click.echo(f"  - 中置信度: {result.medium_confidence_count}")
            click.echo(f"  - 抑制数量: {result.suppressed_count}")
            click.echo(f"📁 输出文件: {len(result.output_files)} 个")

            if result.errors:
                click.echo(f"\n⚠️  错误列表:")
                for error in result.errors[:5]:
                    click.echo(f"  - {error}", err=True)
                if len(result.errors) > 5:
                    click.echo(f"  ... 还有 {len(result.errors) - 5} 个错误", err=True)

            click.echo("=" * 60)

            if result.success:
                click.echo("✨ 关系发现完成！")
            else:
                click.echo("⚠️  关系发现完成，但存在错误", err=True)
                raise click.Abort()

            return

        # 初始化生成器（Step 2）
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

