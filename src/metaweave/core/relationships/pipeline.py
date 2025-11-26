"""关系发现管道

主控制器，协调整个关系发现流程的5个阶段。
"""

import logging
from pathlib import Path
from typing import Dict, Any

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.core.relationships.models import RelationshipDiscoveryResult
from src.metaweave.core.relationships.repository import MetadataRepository
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator
from src.metaweave.core.relationships.scorer import RelationshipScorer
from src.metaweave.core.relationships.decision_engine import DecisionEngine
from src.metaweave.core.relationships.writer import RelationshipWriter
from src.metaweave.utils.file_utils import get_project_root
from src.services.config_loader import ConfigLoader

logger = logging.getLogger("metaweave.relationships.pipeline")


class RelationshipDiscoveryPipeline:
    """关系发现管道

    协调5个阶段：
    1. JSON加载 + 外键直通
    2. 候选生成（复合键 + 单列）
    3. 候选评分（6维度 + 数据库采样）
    4. 决策过滤 + 抑制
    5. 结果输出（JSON + Markdown）
    """

    def __init__(self, config_path: Path):
        """初始化关系发现管道

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()

        # 获取JSON目录（支持直接配置 json_directory，或从 output_dir 推导）
        output_config = self.config.get("output", {})
        json_directory = output_config.get("json_directory")
        if json_directory:
            self.json_dir = get_project_root() / json_directory
        else:
            # Fallback: 从 output_dir 推导
            output_dir = output_config.get("output_dir", "output/metaweave/metadata")
            self.json_dir = get_project_root() / output_dir / "json"

        config_source = "显式配置" if json_directory else "自动推导"
        logger.info(f"关系发现管道已初始化: json_dir={self.json_dir} ({config_source})")

        # 初始化数据库连接器（从database节点获取配置）
        db_config = self.config.get("database", {})
        self.connector = DatabaseConnector(db_config)

        # 初始化各模块（传入 top-level config）
        rel_id_salt = output_config.get("rel_id_salt", "")
        self.repository = MetadataRepository(self.json_dir, rel_id_salt=rel_id_salt)

        # candidate_generator需要fk_signature_set，稍后设置
        self.candidate_generator = None

        # scorer需要connector和config（传入top-level config）
        self.scorer = RelationshipScorer(self.config, self.connector)

        # decision_engine（传入top-level config）
        self.decision_engine = DecisionEngine(self.config)

        # writer（传入top-level config）
        self.writer = RelationshipWriter(self.config)

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件（使用ConfigLoader处理环境变量替换）"""
        try:
            config_loader = ConfigLoader(str(self.config_path))
            config = config_loader.load()
            if not config:
                raise ValueError(f"配置文件加载失败: {self.config_path}")
            logger.info(f"配置文件加载成功: {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            raise

    def discover(self) -> RelationshipDiscoveryResult:
        """执行5阶段关系发现

        Returns:
            关系发现结果
        """
        result = RelationshipDiscoveryResult(success=True)

        try:
            logger.info("=" * 60)
            logger.info("开始关系发现")
            logger.info("=" * 60)

            # Stage 1: JSON加载 + 外键直通
            logger.info("阶段1: 加载JSON元数据并提取外键直通关系")
            tables = self.repository.load_all_tables()
            fk_relations, fk_sigs = self.repository.collect_foreign_keys(tables)

            result.foreign_key_relations = len(fk_relations)
            logger.info(f"外键直通关系: {result.foreign_key_relations} 个")

            # Stage 2: 候选生成
            logger.info("阶段2: 生成候选关系（复合键 + 单列）")
            self.candidate_generator = CandidateGenerator(self.config, fk_sigs)
            candidates = self.candidate_generator.generate_candidates(tables)
            logger.info(f"候选关系: {len(candidates)} 个")

            # Stage 3: 候选评分
            logger.info("阶段3: 评分候选关系（6维度 + 数据库采样）")
            scored_candidates = self.scorer.score_candidates(candidates, tables)
            logger.info(f"评分完成: {len(scored_candidates)} 个")

            # Stage 4: 决策过滤 + 抑制
            logger.info("阶段4: 决策过滤和抑制规则")
            inferred_relations, suppressed = self.decision_engine.filter_and_suppress(scored_candidates)

            result.inferred_relations = len(inferred_relations)
            result.suppressed_count = len(suppressed)
            logger.info(f"推断关系: {result.inferred_relations} 个，抑制: {result.suppressed_count} 个")

            # 统计置信度分布
            decision_config = self.config.get("decision", {})
            high_threshold = decision_config.get("high_confidence_threshold", 0.90)
            medium_threshold = decision_config.get("medium_confidence_threshold", 0.80)

            for rel in inferred_relations:
                if rel.composite_score and rel.composite_score >= high_threshold:
                    result.high_confidence_count += 1
                elif rel.composite_score and rel.composite_score >= medium_threshold:
                    result.medium_confidence_count += 1

            # Stage 5: 输出结果
            logger.info("阶段5: 输出结果（JSON + Markdown）")
            all_relations = fk_relations + inferred_relations
            result.total_relations = len(all_relations)

            output_files = self.writer.write_results(all_relations, suppressed, self.config)
            for file_path in output_files:
                result.add_output_file(file_path)

            logger.info("=" * 60)
            logger.info("关系发现完成")
            logger.info(f"总关系数: {result.total_relations}")
            logger.info(f"  - 外键直通: {result.foreign_key_relations}")
            logger.info(f"  - 推断关系: {result.inferred_relations}")
            logger.info(f"  - 高置信度: {result.high_confidence_count}")
            logger.info(f"  - 中置信度: {result.medium_confidence_count}")
            logger.info(f"  - 抑制数量: {result.suppressed_count}")
            logger.info(f"输出文件: {len(result.output_files)} 个")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"关系发现失败: {e}", exc_info=True)
            result.add_error(str(e))

        finally:
            # 关闭数据库连接
            self.connector.close()

        return result
