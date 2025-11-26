"""测试MetadataRepository模块"""

import json
import pytest
from pathlib import Path
from src.metaweave.core.relationships.repository import MetadataRepository


class TestMetadataRepository:
    """MetadataRepository单元测试"""

    def test_generate_relation_id_deterministic(self):
        """测试relationship_id生成的确定性"""
        repo = MetadataRepository(Path("output/metaweave/metadata/json"))

        rel_id1 = repo._generate_relation_id(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"]
        )

        rel_id2 = repo._generate_relation_id(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"]
        )

        # 相同输入应生成相同ID
        assert rel_id1 == rel_id2
        assert rel_id1.startswith("rel_")
        assert len(rel_id1) == 16  # rel_ + 12位哈希

    def test_generate_relation_id_different_tables(self):
        """测试不同表生成不同ID"""
        repo = MetadataRepository(Path("output/metaweave/metadata/json"))

        rel_id1 = repo._generate_relation_id(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"]
        )

        rel_id2 = repo._generate_relation_id(
            "public", "fact_sales", ["company_id"],
            "public", "dim_company", ["company_id"]
        )

        # 不同表对应生成不同ID
        assert rel_id1 != rel_id2

    def test_generate_fk_signature(self):
        """测试FK签名生成"""
        repo = MetadataRepository(Path("output/metaweave/metadata/json"))

        sig = repo._generate_fk_signature(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"]
        )

        expected = "public.fact_sales.[store_id]->public.dim_store.[store_id]"
        assert sig == expected

    def test_generate_fk_signature_composite(self):
        """测试复合键签名生成"""
        repo = MetadataRepository(Path("output/metaweave/metadata/json"))

        sig = repo._generate_fk_signature(
            "public", "fact_sales", ["store_id", "date_day"],
            "public", "dim_store", ["store_id", "date_day"]
        )

        # 列名应该被排序
        assert "date_day" in sig
        assert "store_id" in sig
        assert sig.startswith("public.fact_sales")

    def test_load_all_tables_with_real_data(self):
        """测试加载真实JSON文件"""
        json_dir = Path("output/metaweave/metadata/json")

        if not json_dir.exists():
            pytest.skip("JSON目录不存在，跳过测试")

        repo = MetadataRepository(json_dir)
        tables = repo.load_all_tables()

        # 应该至少加载一些表
        assert len(tables) > 0

        # 检查表名格式
        for full_name in tables.keys():
            assert "." in full_name  # schema.table格式

    def test_collect_foreign_keys_with_real_data(self):
        """测试外键提取（使用真实数据）"""
        json_dir = Path("output/metaweave/metadata/json")

        if not json_dir.exists():
            pytest.skip("JSON目录不存在，跳过测试")

        repo = MetadataRepository(json_dir)
        tables = repo.load_all_tables()

        if not tables:
            pytest.skip("没有加载到表数据")

        fk_relations, fk_sigs = repo.collect_foreign_keys(tables)

        # FK签名集合数量应该等于关系数量
        assert len(fk_sigs) == len(fk_relations)

        # 每个关系应该有完整的字段
        for rel in fk_relations:
            assert rel.relationship_id.startswith("rel_")
            assert rel.relationship_type == "foreign_key"
            assert len(rel.source_columns) > 0
            assert len(rel.target_columns) > 0

    def test_compute_relationship_id_static_method(self):
        """测试静态方法 compute_relationship_id"""
        # 使用静态方法生成 ID（无盐值）
        rel_id1 = MetadataRepository.compute_relationship_id(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"]
        )

        # 使用静态方法生成 ID（有盐值）
        rel_id2 = MetadataRepository.compute_relationship_id(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"],
            rel_id_salt="myproject"
        )

        # 无盐值和有盐值应生成不同ID
        assert rel_id1 != rel_id2

        # 相同盐值应生成相同ID
        rel_id3 = MetadataRepository.compute_relationship_id(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"],
            rel_id_salt="myproject"
        )
        assert rel_id2 == rel_id3

    def test_relation_id_salt_consistency(self):
        """测试实例方法与静态方法的一致性"""
        # 创建带盐值的 repository
        repo = MetadataRepository(
            Path("output/metaweave/metadata/json"),
            rel_id_salt="myproject"
        )

        # 使用实例方法生成 ID
        instance_id = repo._generate_relation_id(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"]
        )

        # 使用静态方法生成 ID（相同盐值）
        static_id = MetadataRepository.compute_relationship_id(
            "public", "fact_sales", ["store_id"],
            "public", "dim_store", ["store_id"],
            rel_id_salt="myproject"
        )

        # 应该生成相同的 ID
        assert instance_id == static_id
