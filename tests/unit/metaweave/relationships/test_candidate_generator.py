"""测试CandidateGenerator模块"""

import pytest
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator


class TestCandidateGenerator:
    """CandidateGenerator单元测试"""

    def test_composite_key_generation_physical(self):
        """测试从物理约束生成复合键候选"""
        # 使用 top-level 配置结构
        config = {
            "composite": {
                "max_columns": 3,
                "target_sources": ["physical_constraints"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            },
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 创建测试表数据（包含table_profile）
        tables = {
            "public.fact_sales": {
                "table_info": {"schema_name": "public", "table_name": "fact_sales"},
                "column_profiles": {
                    "store_id": {"data_type": "integer"},
                    "date_day": {"data_type": "date"}
                },
                "table_profile": {
                    "physical_constraints": {
                        "indexes": [
                            {
                                "columns": ["store_id", "date_day"],
                                "is_unique": True
                            }
                        ]
                    }
                }
            },
            "public.dim_store": {
                "table_info": {"schema_name": "public", "table_name": "dim_store"},
                "column_profiles": {
                    "store_id": {"data_type": "integer"},
                    "date_day": {"data_type": "date"}
                },
                "table_profile": {
                    "physical_constraints": {
                        "primary_key": {
                            "columns": ["store_id", "date_day"]
                        }
                    }
                }
            }
        }

        candidates = generator._generate_composite_candidates(tables)

        # 应该生成复合键候选
        assert len(candidates) > 0
        composite_candidates = [c for c in candidates if len(c["source_columns"]) > 1]
        assert len(composite_candidates) > 0

    def test_single_column_active_search(self):
        """测试主动同名搜索"""
        config = {
            "single_column": {
                "active_search_same_name": True,
                "important_constraints": ["single_field_primary_key", "single_field_index"],
                "exclude_semantic_roles": ["audit"],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": [],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 创建测试表数据
        tables = {
            "public.fact_sales": {
                "table_info": {"schema_name": "public", "table_name": "fact_sales"},
                "column_profiles": {
                    "store_id": {
                        "data_type": "integer",
                        "structure_flags": {
                            "is_primary_key": False,
                            "is_unique": False,
                            "is_indexed": True
                        }
                    }
                },
                "table_profile": {}
            },
            "public.dim_store": {
                "table_info": {"schema_name": "public", "table_name": "dim_store"},
                "column_profiles": {
                    "store_id": {
                        "data_type": "integer",
                        "structure_flags": {
                            "is_primary_key": True,
                            "is_unique": True,
                            "is_indexed": True
                        }
                    }
                },
                "table_profile": {}
            }
        }

        candidates = generator._generate_single_column_candidates(tables)

        # 应该找到同名列的候选
        assert len(candidates) > 0
        store_id_candidates = [
            c for c in candidates
            if c["source_columns"] == ["store_id"] and c["target_columns"] == ["store_id"]
        ]
        assert len(store_id_candidates) > 0

    def test_fk_signature_deduplication(self):
        """测试FK签名去重"""
        config = {
            "single_column": {
                "active_search_same_name": True,
                "important_constraints": ["single_field_primary_key"],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": [],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }

        # FK签名集合包含已存在的关系
        fk_sigs = {"public.fact_sales.[store_id]->public.dim_store.[store_id]"}
        generator = CandidateGenerator(config, fk_sigs)

        tables = {
            "public.fact_sales": {
                "table_info": {"schema_name": "public", "table_name": "fact_sales"},
                "column_profiles": {
                    "store_id": {
                        "data_type": "integer",
                        "structure_flags": {"is_indexed": True, "is_primary_key": True}
                    }
                },
                "table_profile": {}
            },
            "public.dim_store": {
                "table_info": {"schema_name": "public", "table_name": "dim_store"},
                "column_profiles": {
                    "store_id": {
                        "data_type": "integer",
                        "structure_flags": {"is_primary_key": True}
                    }
                },
                "table_profile": {}
            }
        }

        candidates = generator._generate_single_column_candidates(tables)

        # 已存在的FK关系不应该生成候选
        source_info_candidates = [
            c for c in candidates
            if c["source"].get("table_info", {}).get("table_name") == "fact_sales"
            and c["target"].get("table_info", {}).get("table_name") == "dim_store"
            and c["source_columns"] == ["store_id"]
        ]
        assert len(source_info_candidates) == 0

    def test_semantic_role_exclusion(self):
        """测试语义角色排除"""
        config = {
            "single_column": {
                "active_search_same_name": True,
                "important_constraints": [],
                "exclude_semantic_roles": ["audit"],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": [],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        tables = {
            "public.fact_sales": {
                "table_info": {"schema_name": "public", "table_name": "fact_sales"},
                "column_profiles": {
                    "created_at": {
                        "data_type": "timestamp",
                        "semantic_analysis": {"semantic_role": "audit"},
                        "structure_flags": {"is_indexed": False}
                    }
                },
                "table_profile": {}
            },
            "public.dim_store": {
                "table_info": {"schema_name": "public", "table_name": "dim_store"},
                "column_profiles": {
                    "created_at": {
                        "data_type": "timestamp",
                        "semantic_analysis": {"semantic_role": "audit"},
                        "structure_flags": {"is_indexed": False}
                    }
                },
                "table_profile": {}
            }
        }

        candidates = generator._generate_single_column_candidates(tables)

        # audit角色的字段应该被排除
        created_at_candidates = [
            c for c in candidates
            if c["source_columns"] == ["created_at"]
        ]
        assert len(created_at_candidates) == 0

    def test_has_important_constraint(self):
        """测试重要约束检测"""
        config = {
            "single_column": {
                "important_constraints": [
                    "single_field_primary_key",
                    "single_field_unique_constraint",
                    "single_field_index"
                ],
                "active_search_same_name": True,
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": [],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 有主键约束的列
        col_profile_pk = {
            "structure_flags": {
                "is_primary_key": True,
                "is_unique": False,
                "is_indexed": False
            }
        }
        assert generator._has_important_constraint(col_profile_pk) is True

        # 有索引约束的列
        col_profile_idx = {
            "structure_flags": {
                "is_primary_key": False,
                "is_unique": False,
                "is_indexed": True
            }
        }
        assert generator._has_important_constraint(col_profile_idx) is True

        # 没有约束的列
        col_profile_none = {
            "structure_flags": {
                "is_primary_key": False,
                "is_unique": False,
                "is_indexed": False
            }
        }
        assert generator._has_important_constraint(col_profile_none) is False

    def test_dynamic_same_name_case_insensitive(self):
        """测试动态同名匹配的大小写不敏感"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["dynamic_same_name"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 源表：大写列名
        source_table = {
            "table_info": {"schema_name": "public", "table_name": "fact_sales"},
            "column_profiles": {
                "Store_ID": {"data_type": "integer"},
                "Date_Day": {"data_type": "date"}
            },
            "table_profile": {}
        }

        # 目标表：小写列名
        target_table = {
            "table_info": {"schema_name": "public", "table_name": "fact_summary"},
            "column_profiles": {
                "store_id": {"data_type": "integer"},
                "date_day": {"data_type": "date"}
            },
            "table_profile": {}
        }

        # 调用动态同名匹配
        matched = generator._find_dynamic_same_name(
            ["Store_ID", "Date_Day"], source_table, target_table
        )

        # 应该匹配成功，返回目标表的原始列名（小写）
        assert matched is not None
        assert matched == ["store_id", "date_day"]

    def test_dynamic_same_name_type_incompatible(self):
        """测试动态同名匹配的类型不兼容情况"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["dynamic_same_name"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 源表
        source_table = {
            "table_info": {"schema_name": "public", "table_name": "fact_sales"},
            "column_profiles": {
                "store_id": {"data_type": "integer"},
                "date_day": {"data_type": "date"}
            },
            "table_profile": {}
        }

        # 目标表：date_day 类型不兼容（date vs text）
        target_table = {
            "table_info": {"schema_name": "public", "table_name": "fact_summary"},
            "column_profiles": {
                "store_id": {"data_type": "integer"},
                "date_day": {"data_type": "text"}  # 类型不兼容
            },
            "table_profile": {}
        }

        # 调用动态同名匹配
        matched = generator._find_dynamic_same_name(
            ["store_id", "date_day"], source_table, target_table
        )

        # 应该因为类型不兼容而返回 None
        assert matched is None

    def test_dynamic_same_name_missing_column(self):
        """测试动态同名匹配的列缺失情况"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["dynamic_same_name"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 源表
        source_table = {
            "table_info": {"schema_name": "public", "table_name": "fact_sales"},
            "column_profiles": {
                "store_id": {"data_type": "integer"},
                "date_day": {"data_type": "date"},
                "product_id": {"data_type": "integer"}
            },
            "table_profile": {}
        }

        # 目标表：缺少 product_id 列
        target_table = {
            "table_info": {"schema_name": "public", "table_name": "fact_summary"},
            "column_profiles": {
                "store_id": {"data_type": "integer"},
                "date_day": {"data_type": "date"}
            },
            "table_profile": {}
        }

        # 调用动态同名匹配
        matched = generator._find_dynamic_same_name(
            ["store_id", "date_day", "product_id"], source_table, target_table
        )

        # 应该因为缺少列而返回 None
        assert matched is None

    def test_compatible_combination_with_type_check(self):
        """测试物理/逻辑约束匹配的类型兼容性检查"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["physical_constraints"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 源列画像
        source_profiles = {
            "store_id": {"data_type": "integer"},
            "date_day": {"data_type": "date"}
        }

        # 目标列画像（类型兼容）
        target_profiles_compatible = {
            "store_id": {"data_type": "bigint"},  # integer -> bigint 兼容
            "date_day": {"data_type": "date"}
        }

        # 目标列画像（类型不兼容）
        target_profiles_incompatible = {
            "store_id": {"data_type": "integer"},
            "date_day": {"data_type": "text"}  # date -> text 不兼容
        }

        # 测试类型兼容的情况
        compatible = generator._is_compatible_combination(
            ["store_id", "date_day"],
            ["store_id", "date_day"],
            source_profiles,
            target_profiles_compatible
        )
        assert compatible is True

        # 测试类型不兼容的情况
        incompatible = generator._is_compatible_combination(
            ["store_id", "date_day"],
            ["store_id", "date_day"],
            source_profiles,
            target_profiles_incompatible
        )
        assert incompatible is False

    def test_compatible_combination_name_similarity_threshold(self):
        """测试物理/逻辑约束匹配的名称相似度阈值"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["physical_constraints"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 源列画像
        source_profiles = {
            "store_id": {"data_type": "integer"},
            "product_id": {"data_type": "integer"}
        }

        # 目标列画像
        target_profiles = {
            "store_id": {"data_type": "integer"},
            "product_id": {"data_type": "integer"}
        }

        # 测试名称相似度高的情况（完全相同）
        high_similarity = generator._is_compatible_combination(
            ["store_id", "product_id"],
            ["store_id", "product_id"],
            source_profiles,
            target_profiles
        )
        assert high_similarity is True

        # 测试名称相似度低的情况（完全不同）
        low_similarity = generator._is_compatible_combination(
            ["store_id", "product_id"],
            ["xxx", "yyy"],  # 完全不同的列名
            source_profiles,
            target_profiles
        )
        assert low_similarity is False

    def test_qualified_target_column_with_primary_key(self):
        """测试目标列约束检查：物理主键"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["physical_constraints"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 目标列：有物理主键
        col_profile_pk = {
            "structure_flags": {
                "is_primary_key": True
            }
        }
        table = {}

        assert generator._is_qualified_target_column("customer_id", col_profile_pk, table) is True

    def test_qualified_target_column_with_unique(self):
        """测试目标列约束检查：唯一约束"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["physical_constraints"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 目标列：有唯一约束
        col_profile_unique = {
            "structure_flags": {
                "is_unique": True
            }
        }
        table = {}

        assert generator._is_qualified_target_column("email", col_profile_unique, table) is True

    def test_qualified_target_column_with_index(self):
        """测试目标列约束检查：索引"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["physical_constraints"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 目标列：有索引
        col_profile_indexed = {
            "structure_flags": {
                "is_indexed": True
            }
        }
        table = {}

        assert generator._is_qualified_target_column("product_id", col_profile_indexed, table) is True

    def test_qualified_target_column_with_logical_key(self):
        """测试目标列约束检查：单列逻辑主键"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["physical_constraints"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 目标列：单列逻辑主键（confidence >= 0.8）
        col_profile = {
            "structure_flags": {}
        }
        table = {
            "table_profile": {
                "logical_keys": {
                    "candidate_primary_keys": [
                        {
                            "columns": ["order_id"],
                            "confidence_score": 0.9
                        }
                    ]
                }
            }
        }

        assert generator._is_qualified_target_column("order_id", col_profile, table) is True

    def test_qualified_target_column_identifier_only_rejected(self):
        """测试目标列约束检查：只有identifier角色但无约束应被拒绝"""
        config = {
            "single_column": {
                "active_search_same_name": False,
                "important_constraints": [],
                "exclude_semantic_roles": [],
                "logical_key_min_confidence": 0.8
            },
            "composite": {
                "max_columns": 3,
                "target_sources": ["physical_constraints"],
                "min_name_similarity": 0.7,
                "min_type_compatibility": 0.8
            }
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 目标列：只有identifier角色，但无物理约束或逻辑主键
        col_profile = {
            "structure_flags": {
                "is_primary_key": False,
                "is_unique": False,
                "is_indexed": False
            },
            "semantic_analysis": {
                "semantic_role": "identifier"
            }
        }
        table = {
            "table_profile": {
                "logical_keys": {
                    "candidate_primary_keys": []
                }
            }
        }

        # 应该被拒绝（不满足约束条件）
        assert generator._is_qualified_target_column("customer_name", col_profile, table) is False

    def test_active_search_case_insensitive(self):
        """测试主动搜索支持大小写不敏感"""
        config = {
            "single_column": {
                "active_search_same_name": True
            },
            "composite": {}
        }
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 源表：Store_ID（大写）有主键约束
        source_table = {
            "table_info": {"schema_name": "public", "table_name": "fact_sales"},
            "column_profiles": {
                "Store_ID": {
                    "data_type": "INTEGER",
                    "structure_flags": {"is_primary_key": True},
                    "semantic_analysis": {"semantic_role": "identifier"}
                }
            }
        }

        # 目标表：store_id（小写）
        target_table = {
            "table_info": {"schema_name": "public", "table_name": "dim_store"},
            "column_profiles": {
                "store_id": {
                    "data_type": "INTEGER",
                    "structure_flags": {"is_primary_key": True}
                }
            }
        }

        tables = {
            "public.fact_sales": source_table,
            "public.dim_store": target_table
        }

        candidates = generator._generate_single_column_candidates(tables)

        # 应该匹配成功（大小写不敏感）
        matching_candidates = [
            c for c in candidates
            if c["source_columns"] == ["Store_ID"] and c["target_columns"] == ["store_id"]
        ]
        assert len(matching_candidates) == 1

    def test_name_similarity_case_insensitive(self):
        """测试名称相似度计算支持大小写不敏感"""
        config = {"single_column": {}, "composite": {}}
        fk_sigs = set()
        generator = CandidateGenerator(config, fk_sigs)

        # 精确匹配（大小写不同）
        assert generator._calculate_name_similarity("Store_ID", "store_id") == 1.0
        assert generator._calculate_name_similarity("DATE_DAY", "date_day") == 1.0
        assert generator._calculate_name_similarity("CompanyName", "companyname") == 1.0

        # 完全相同
        assert generator._calculate_name_similarity("store_id", "store_id") == 1.0
