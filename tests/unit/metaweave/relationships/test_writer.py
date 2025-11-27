"""测试RelationshipWriter模块"""

import json
import pytest
from pathlib import Path
from src.metaweave.core.relationships.writer import RelationshipWriter
from src.metaweave.core.relationships.models import Relation


class TestRelationshipWriter:
    """RelationshipWriter单元测试"""

    @pytest.fixture
    def temp_output_dir(self, tmp_path):
        """创建临时输出目录"""
        return tmp_path / "output" / "metaweave" / "metadata" / "rel"

    @pytest.fixture
    def config(self, temp_output_dir):
        """创建测试配置"""
        return {
            "output": {
                "rel_directory": str(temp_output_dir),
                "rel_granularity": "global"
            },
            "decision": {
                "accept_threshold": 0.80,
                "high_confidence_threshold": 0.90,
                "medium_confidence_threshold": 0.80
            },
            "weights": {
                "inclusion_rate": 0.30,
                "jaccard_index": 0.15,
                "uniqueness": 0.10,
                "name_similarity": 0.20,
                "type_compatibility": 0.20,
                "semantic_role_bonus": 0.05
            },
            "composite": {
                "max_columns": 3
            }
        }

    @pytest.fixture
    def writer(self, config):
        """创建Writer实例"""
        return RelationshipWriter(config)

    @pytest.fixture
    def sample_relations(self):
        """创建示例关系数据"""
        return [
            Relation(
                relationship_id="rel_abc123456789",
                source_schema="public",
                source_table="fact_sales",
                source_columns=["store_id"],
                target_schema="public",
                target_table="dim_store",
                target_columns=["store_id"],
                relationship_type="foreign_key",
                cardinality="N:1"
            ),
            Relation(
                relationship_id="rel_def123456789",
                source_schema="public",
                source_table="fact_sales",
                source_columns=["company_id"],
                target_schema="public",
                target_table="dim_company",
                target_columns=["company_id"],
                relationship_type="inferred",
                cardinality="N:1",
                composite_score=0.85,
                score_details={
                    "inclusion_rate": 0.8,
                    "jaccard_index": 0.6,
                    "name_similarity": 1.0,
                    "type_compatibility": 1.0,
                    "uniqueness": 0.9,
                    "semantic_role_bonus": 1.0
                },
                inference_method="single_active_search"
            )
        ]

    def test_write_json_output(self, writer, sample_relations, temp_output_dir, config):
        """测试JSON输出（v3.2格式）"""
        output_files = writer.write_results(sample_relations, [], config)

        # 检查文件是否生成
        json_file = temp_output_dir / "relationships_global.json"
        assert json_file.exists()

        # 验证JSON内容（v3.2格式）
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 顶层字段验证
        assert data["json_metadata_version"] == "2.0"
        assert data["metadata_source"] == "json_files"
        assert "analysis_timestamp" in data
        assert "statistics" in data
        assert "relationships" in data  # 不是 relations

        # 统计字段验证（v3.2格式，按开发指南 2.10 节要求）
        stats = data["statistics"]
        assert "total_relationships_found" in stats
        assert "foreign_key_relationships" in stats  # ← 新增验证
        assert "composite_key_relationships" in stats
        assert "single_column_relationships" in stats
        assert "total_suppressed_single_relations" in stats
        assert "active_search_discoveries" in stats
        assert "dynamic_composite_discoveries" in stats

        # 验证关系数据
        assert len(data["relationships"]) == 2
        assert data["relationships"][0]["relationship_id"] == "rel_abc123456789"
        assert data["relationships"][1]["composite_score"] == 0.85

        # 验证v3.2格式字段
        rel1 = data["relationships"][0]
        assert "type" in rel1
        assert "from_table" in rel1
        assert "to_table" in rel1
        assert isinstance(rel1["from_table"], dict)

    def test_write_markdown_output(self, writer, sample_relations, temp_output_dir, config):
        """测试Markdown输出"""
        output_files = writer.write_results(sample_relations, [], config)

        # 检查文件是否生成
        md_file = temp_output_dir / "relationships_global.md"
        assert md_file.exists()

        # 验证Markdown内容
        with open(md_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "# 表间关系发现报告" in content or "表间关系" in content or "关系" in content
        assert "统计" in content
        assert "fact_sales" in content
        assert "dim_store" in content

    def test_suppressed_embedded_in_composite(self, writer, temp_output_dir, config):
        """测试被抑制关系嵌入复合键（v3.2格式）"""
        # 创建复合键关系
        composite_relation = Relation(
            relationship_id="rel_composite_001",
            source_schema="public",
            source_table="fact_sales",
            source_columns=["store_id", "date_day"],
            target_schema="public",
            target_table="dim_store",
            target_columns=["store_id", "date_day"],
            relationship_type="inferred",
            cardinality="N:1",
            composite_score=0.90,
            score_details={},
            inference_method="composite_physical"
        )

        # 被抑制的单列关系
        suppressed = [
            {
                "source": {
                    "table_info": {"schema_name": "public", "table_name": "fact_sales"}
                },
                "target": {
                    "table_info": {"schema_name": "public", "table_name": "dim_store"}
                },
                "source_columns": ["store_id"],
                "target_columns": ["store_id"],
                "candidate_type": "single_active_search",
                "composite_score": 0.82,
                "score_details": {}
            }
        ]

        output_files = writer.write_results([composite_relation], suppressed, config)

        # 验证被抑制关系嵌入到复合键对象中
        json_file = temp_output_dir / "relationships_global.json"
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 找到复合键关系
        composite_rels = [r for r in data["relationships"] if r["type"] == "composite"]
        assert len(composite_rels) == 1

        # 验证嵌入的被抑制关系
        assert "suppressed_single_relations" in composite_rels[0]
        suppressed_list = composite_rels[0]["suppressed_single_relations"]
        assert len(suppressed_list) == 1
        assert suppressed_list[0]["from_column"] == "store_id"
        assert suppressed_list[0]["to_column"] == "store_id"
        assert "original_score" in suppressed_list[0]
        assert "suppression_reason" in suppressed_list[0]

    def test_output_files_list(self, writer, sample_relations, config):
        """测试输出文件列表"""
        output_files = writer.write_results(sample_relations, [], config)

        # 应该至少有JSON和Markdown两个文件
        assert len(output_files) >= 2

        # 检查文件路径格式
        for file_path in output_files:
            assert "relationships_global" in file_path

    def test_statistics_in_json(self, writer, sample_relations, config):
        """测试JSON中的统计数据（v3.2格式，按开发指南 2.10 节要求）"""
        output_files = writer.write_results(sample_relations, [], config)

        json_file = Path(output_files[0])
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        stats = data["statistics"]
        # v3.2格式统计字段（完整7个字段）
        assert stats["total_relationships_found"] == 2
        assert stats["foreign_key_relationships"] == 1  # ← 新增验证
        assert stats["composite_key_relationships"] == 0
        assert stats["single_column_relationships"] == 2
        assert stats["total_suppressed_single_relations"] == 0
        assert "active_search_discoveries" in stats
        assert "dynamic_composite_discoveries" in stats

    def test_output_directory_creation(self, sample_relations, tmp_path, config):
        """测试输出目录自动创建"""
        # 使用一个新的、不存在的目录
        new_output_dir = tmp_path / "new_test_dir" / "rel"

        # 确保目录不存在
        assert not new_output_dir.exists()

        # 创建新的config和writer
        new_config = config.copy()
        new_config["output"] = {
            "rel_directory": str(new_output_dir),
            "rel_granularity": "global"
        }

        # 初始化writer时会创建目录
        new_writer = RelationshipWriter(new_config)

        # 目录应该在初始化时被创建
        assert new_output_dir.exists()

        # 写入结果
        new_writer.write_results(sample_relations, [], new_config)

        # 文件应该被创建
        assert (new_output_dir / "relationships_global.json").exists()

    def test_discovery_method_mapping(self, writer, temp_output_dir, config):
        """测试 discovery_method, source_type, source_constraint 字段映射"""
        # 创建不同类型的推断关系
        relations = [
            # 单列主动搜索
            Relation(
                relationship_id="rel_001",
                source_schema="public",
                source_table="fact_sales",
                source_columns=["store_id"],
                target_schema="public",
                target_table="dim_store",
                target_columns=["store_id"],
                relationship_type="inferred",
                cardinality="N:1",
                composite_score=0.88,
                score_details={},
                inference_method="single_active_search"
            ),
            # 复合键物理约束
            Relation(
                relationship_id="rel_002",
                source_schema="public",
                source_table="fact_sales",
                source_columns=["store_id", "date_day"],
                target_schema="public",
                target_table="dim_store",
                target_columns=["store_id", "date_day"],
                relationship_type="inferred",
                cardinality="N:1",
                composite_score=0.92,
                score_details={},
                inference_method="composite_physical"
            ),
            # 复合键逻辑主键
            Relation(
                relationship_id="rel_003",
                source_schema="public",
                source_table="fact_sales",
                source_columns=["order_id", "product_id"],
                target_schema="public",
                target_table="fact_summary",
                target_columns=["order_id", "product_id"],
                relationship_type="inferred",
                cardinality="N:1",
                composite_score=0.85,
                score_details={},
                inference_method="composite_logical"
            ),
            # 复合键动态同名
            Relation(
                relationship_id="rel_004",
                source_schema="public",
                source_table="fact_sales",
                source_columns=["order_id", "line_id"],
                target_schema="public",
                target_table="fact_detail",
                target_columns=["order_id", "line_id"],
                relationship_type="inferred",
                cardinality="N:1",
                composite_score=0.90,
                score_details={},
                inference_method="composite_dynamic_same_name"
            )
        ]

        output_files = writer.write_results(relations, [], config)

        # 验证JSON输出
        json_file = temp_output_dir / "relationships_global.json"
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 验证单列主动搜索
        rel1 = [r for r in data["relationships"] if r["relationship_id"] == "rel_001"][0]
        assert rel1["discovery_method"] == "active_search"
        assert rel1.get("source_type") is None
        assert rel1["source_constraint"] == "single_field_index"

        # 验证复合键物理约束
        rel2 = [r for r in data["relationships"] if r["relationship_id"] == "rel_002"][0]
        assert rel2["discovery_method"] == "physical_constraint_matching"
        assert rel2["source_type"] == "physical_constraints"
        assert rel2.get("source_constraint") is None

        # 验证复合键逻辑主键
        rel3 = [r for r in data["relationships"] if r["relationship_id"] == "rel_003"][0]
        assert rel3["discovery_method"] == "logical_key_matching"
        assert rel3["source_type"] == "candidate_logical_key"
        assert rel3.get("source_constraint") is None

        # 验证复合键动态同名
        rel4 = [r for r in data["relationships"] if r["relationship_id"] == "rel_004"][0]
        assert rel4["discovery_method"] == "dynamic_same_name"
        assert rel4["source_type"] == "candidate_logical_key"
        assert rel4.get("source_constraint") is None

    def test_schema_granularity_warning(self, sample_relations, tmp_path, config, caplog):
        """测试配置 schema 粒度时给出警告并强制使用 global"""
        import logging

        # 配置 schema 粒度
        schema_config = config.copy()
        schema_config["output"] = {
            "rel_directory": str(tmp_path / "rel"),
            "rel_granularity": "schema"  # ← 配置 schema
        }

        # 创建 writer（应该触发警告）
        with caplog.at_level(logging.WARNING):
            writer = RelationshipWriter(schema_config)

        # 验证警告信息
        assert any("仅支持 rel_granularity='global'" in record.message for record in caplog.records)
        assert any("schema" in record.message for record in caplog.records)

        # 验证强制使用 global
        assert writer.rel_granularity == "global"

        # 验证输出文件名仍然是 global
        writer.write_results(sample_relations, [], schema_config)
        assert (tmp_path / "rel" / "relationships_global.json").exists()
        assert (tmp_path / "rel" / "relationships_global.md").exists()

    def test_global_granularity_no_warning(self, sample_relations, tmp_path, config, caplog):
        """测试配置 global 粒度时不给出警告"""
        import logging

        # 配置 global 粒度（默认值）
        global_config = config.copy()
        global_config["output"] = {
            "rel_directory": str(tmp_path / "rel"),
            "rel_granularity": "global"
        }

        # 创建 writer（不应该触发警告）
        with caplog.at_level(logging.WARNING):
            writer = RelationshipWriter(global_config)

        # 验证没有警告
        assert not any("仅支持 rel_granularity='global'" in record.message for record in caplog.records)

        # 验证使用 global
        assert writer.rel_granularity == "global"
