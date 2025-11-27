"""Step 4 CQL 生成器

主生成器类，协调整个 Cypher 生成流程。
"""

import logging
import yaml
from pathlib import Path
from typing import Dict, Any

from src.metaweave.core.cql_generator.models import CQLGenerationResult
from src.metaweave.core.cql_generator.reader import JSONReader
from src.metaweave.core.cql_generator.writer import CypherWriter

logger = logging.getLogger("metaweave.cql_generator")


class CQLGenerator:
    """CQL 生成器

    负责整体流程：
    1. 加载配置
    2. 读取 Step 2 和 Step 3 的 JSON 文件
    3. 生成 Cypher 脚本文件
    """

    def __init__(self, config_path: Path):
        """初始化生成器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        self.config = self._load_config()
        logger.info(f"加载配置: {self.config_path}")

        # 解析配置路径
        self.json_dir = self._resolve_path(
            self.config.get("output", {}).get("json_directory", "output/metaweave/metadata/json")
        )
        self.rel_dir = self._resolve_path(
            self.config.get("output", {}).get("rel_directory", "output/metaweave/metadata/rel")
        )
        self.cql_dir = self._resolve_path(
            self.config.get("output", {}).get("cql_directory", "output/metaweave/metadata/cql")
        )

        logger.info(f"JSON 目录: {self.json_dir}")
        logger.info(f"关系目录: {self.rel_dir}")
        logger.info(f"CQL 输出目录: {self.cql_dir}")

    def _load_config(self) -> Dict[str, Any]:
        """加载 YAML 配置文件"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            return config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            raise

    def _resolve_path(self, path_str: str) -> Path:
        """解析路径（支持相对路径和绝对路径）"""
        path = Path(path_str)
        if not path.is_absolute():
            # 相对于项目根目录
            project_root = self.config_path.parent.parent.parent
            path = project_root / path
        return path

    def generate(self) -> CQLGenerationResult:
        """执行 CQL 生成

        Returns:
            生成结果
        """
        try:
            logger.info("=" * 60)
            logger.info("开始 Step 4: Neo4j CQL 生成")
            logger.info("=" * 60)

            # 1. 读取 JSON 数据
            logger.info("\n[1/2] 读取 Step 2 和 Step 3 的 JSON 文件...")
            reader = JSONReader(self.json_dir, self.rel_dir)
            tables, columns, has_column_rels, join_on_rels = reader.read_all()

            logger.info(f"  - 表节点: {len(tables)}")
            logger.info(f"  - 列节点: {len(columns)}")
            logger.info(f"  - HAS_COLUMN 关系: {len(has_column_rels)}")
            logger.info(f"  - JOIN_ON 关系: {len(join_on_rels)}")

            # 2. 生成 Cypher 文件
            logger.info("\n[2/2] 生成 Cypher 脚本文件...")
            writer = CypherWriter(self.cql_dir)
            output_files = writer.write_all(
                tables, columns, has_column_rels, join_on_rels
            )

            logger.info(f"  - 生成文件: {len(output_files)} 个")
            for file_path in output_files:
                logger.info(f"    * {file_path}")

            # 构造结果
            result = CQLGenerationResult(
                success=True,
                output_files=output_files,
                tables_count=len(tables),
                columns_count=len(columns),
                relationships_count=len(join_on_rels),
                errors=[]
            )

            logger.info("\n" + "=" * 60)
            logger.info("✅ Step 4 完成")
            logger.info("=" * 60)
            logger.info(str(result))

            return result

        except Exception as e:
            logger.error(f"CQL 生成失败: {e}", exc_info=True)
            return CQLGenerationResult(
                success=False,
                output_files=[],
                tables_count=0,
                columns_count=0,
                relationships_count=0,
                errors=[str(e)]
            )
