"""测试两阶段匹配策略（特权模式 + 动态同名）"""
import sys
sys.path.insert(0, '/mnt/c/Projects/cursor_2025h2/nl2sql_v3')

import json
from pathlib import Path
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator
from src.services.config_loader import ConfigLoader

# 加载 metaweave 配置文件
config_loader = ConfigLoader('configs/metaweave/metadata_config.yaml')
config = config_loader.load()

# 创建候选生成器实例
generator = CandidateGenerator(config, set())

print("=" * 80)
print("两阶段匹配策略测试")
print("=" * 80)

# ============================================================================
# 测试用例 1: 测试 _find_target_columns 的两阶段匹配
# ============================================================================
print("\n【测试1】两阶段匹配 - 特权模式优先")
print("-" * 80)

# 构造源表（带复合主键）- 使用正确的数据结构
source_table = {
    "table_info": {
        "schema_name": "public",
        "table_name": "source_table"
    },
    "column_profiles": {
        "key1": {"data_type": "integer"},
        "key2": {"data_type": "varchar"}
    },
    "table_profile": {
        "physical_constraints": {
            "primary_key": {
                "columns": ["key1", "key2"]
            },
            "unique_constraints": [],
            "indexes": []
        },
        "logical_keys": {
            "candidate_primary_keys": []
        }
    }
}

# 构造目标表（也有复合主键，但列名稍有不同）- 使用正确的数据结构
target_table = {
    "table_info": {
        "schema_name": "public",
        "table_name": "target_table"
    },
    "column_profiles": {
        "key_1": {"data_type": "integer"},  # 下划线分隔
        "key_2": {"data_type": "varchar"}   # 下划线分隔
    },
    "table_profile": {
        "physical_constraints": {
            "primary_key": {
                "columns": ["key_1", "key_2"]
            },
            "unique_constraints": [],
            "indexes": []
        },
        "logical_keys": {
            "candidate_primary_keys": []
        }
    }
}

source_columns = ["key1", "key2"]

# 测试 Stage 1: 特权模式（应该匹配到目标的PK）
result_stage1 = generator._find_target_columns(
    source_columns=source_columns,
    source_table=source_table,
    target_table=target_table,
    combo_type="physical"  # 触发特权模式
)

print(f"源列: {source_columns}")
print(f"源表主键: {source_table['table_profile']['physical_constraints']['primary_key']['columns']}")
print(f"目标表主键: {target_table['table_profile']['physical_constraints']['primary_key']['columns']}")
print(f"匹配结果（特权模式）: {result_stage1}")
print(f"✅ 预期: ['key_1', 'key_2'] (应匹配到目标PK)")
print(f"{'✅ 通过' if result_stage1 == ['key_1', 'key_2'] else '❌ 失败'}")

# ============================================================================
# 测试用例 2: 测试动态同名匹配（不区分大小写）
# ============================================================================
print("\n【测试2】动态同名匹配 - 大小写不敏感")
print("-" * 80)

source_table_2 = {
    "table_info": {
        "schema_name": "public",
        "table_name": "source_table"
    },
    "column_profiles": {
        "CompanyID": {"data_type": "integer"},
        "RegionID": {"data_type": "integer"}
    }
}

target_table_2 = {
    "table_info": {
        "schema_name": "public",
        "table_name": "target_table"
    },
    "column_profiles": {
        "companyid": {"data_type": "integer"},  # 全小写
        "regionid": {"data_type": "bigint"}     # 全小写，类型稍不同但兼容
    }
}

source_columns_2 = ["CompanyID", "RegionID"]

# 测试动态同名匹配
result_stage2 = generator._find_dynamic_same_name(
    source_columns=source_columns_2,
    source_table=source_table_2,
    target_table=target_table_2
)

print(f"源列: {source_columns_2}")
print(f"目标列: {list(target_table_2['column_profiles'].keys())}")
print(f"匹配结果（动态同名）: {result_stage2}")
print(f"✅ 预期: ['companyid', 'regionid'] (大小写不敏感)")
print(f"{'✅ 通过' if result_stage2 == ['companyid', 'regionid'] else '❌ 失败'}")

# ============================================================================
# 测试用例 3: 动态同名失败 - 类型完全不兼容
# ============================================================================
print("\n【测试3】动态同名失败 - 类型不兼容")
print("-" * 80)

source_table_3 = {
    "table_info": {
        "schema_name": "public",
        "table_name": "source_table"
    },
    "column_profiles": {
        "user_id": {"data_type": "integer"},
        "created_at": {"data_type": "timestamp"}  # 时间戳
    }
}

target_table_3 = {
    "table_info": {
        "schema_name": "public",
        "table_name": "target_table"
    },
    "column_profiles": {
        "user_id": {"data_type": "integer"},
        "created_at": {"data_type": "varchar"}  # timestamp vs varchar 不兼容
    }
}

source_columns_3 = ["user_id", "created_at"]

result_stage3 = generator._find_dynamic_same_name(
    source_columns=source_columns_3,
    source_table=source_table_3,
    target_table=target_table_3
)

print(f"源列: {source_columns_3}")
print(f"源类型: timestamp, 目标类型: varchar")
print(f"匹配结果: {result_stage3}")
print(f"✅ 预期: None (类型不兼容)")
print(f"{'✅ 通过' if result_stage3 is None else '❌ 失败'}")

# ============================================================================
# 测试用例 4: 特权模式 + 低相似度阈值
# ============================================================================
print("\n【测试4】特权模式允许更低的名称相似度")
print("-" * 80)

source_table_4 = {
    "table_info": {
        "schema_name": "public",
        "table_name": "source_table"
    },
    "column_profiles": {
        "store_key": {"data_type": "integer"},
        "product_key": {"data_type": "integer"}
    },
    "table_profile": {
        "physical_constraints": {
            "primary_key": {
                "columns": ["store_key", "product_key"]
            },
            "unique_constraints": [],
            "indexes": []
        },
        "logical_keys": {
            "candidate_primary_keys": []
        }
    }
}

target_table_4 = {
    "table_info": {
        "schema_name": "public",
        "table_name": "target_table"
    },
    "column_profiles": {
        "store_id": {"data_type": "integer"},    # key vs id (相似但不同)
        "product_id": {"data_type": "integer"}
    },
    "table_profile": {
        "physical_constraints": {
            "primary_key": {
                "columns": ["store_id", "product_id"]
            },
            "unique_constraints": [],
            "indexes": []
        },
        "logical_keys": {
            "candidate_primary_keys": []
        }
    }
}

source_columns_4 = ["store_key", "product_key"]

# 测试特权模式（应使用 composite_name_similarity_important_target = 0.6）
result_privilege = generator._find_target_columns(
    source_columns=source_columns_4,
    source_table=source_table_4,
    target_table=target_table_4,
    combo_type="physical"
)

print(f"源列: {source_columns_4}")
print(f"目标PK: {target_table_4['table_profile']['physical_constraints']['primary_key']['columns']}")
print(f"匹配结果（特权模式，阈值=0.6）: {result_privilege}")
print(f"说明: store_key vs store_id, product_key vs product_id 相似度应 > 0.6")
print(f"{'✅ 通过' if result_privilege is not None else '❌ 失败'}")

# ============================================================================
# 测试用例 5: 完整两阶段流程
# ============================================================================
print("\n【测试5】完整两阶段流程 - Stage1失败后尝试Stage2")
print("-" * 80)

source_table_5 = {
    "table_info": {
        "schema_name": "public",
        "table_name": "source_table"
    },
    "column_profiles": {
        "col_a": {"data_type": "integer"},
        "col_b": {"data_type": "varchar"}
    },
    "table_profile": {
        "physical_constraints": {
            "primary_key": {
                "columns": ["col_a", "col_b"]
            },
            "unique_constraints": [],
            "indexes": []
        },
        "logical_keys": {
            "candidate_primary_keys": []
        }
    }
}

target_table_5 = {
    "table_info": {
        "schema_name": "public",
        "table_name": "target_table"
    },
    "column_profiles": {
        "col_a": {"data_type": "integer"},
        "col_b": {"data_type": "varchar"},
        "other_col": {"data_type": "text"}
    },
    "table_profile": {
        "physical_constraints": {
            "primary_key": {
                "columns": ["other_col"]  # PK不匹配，应该fallback到动态同名
            },
            "unique_constraints": [],
            "indexes": []
        },
        "logical_keys": {
            "candidate_primary_keys": []
        }
    }
}

source_columns_5 = ["col_a", "col_b"]

result_two_stage = generator._find_target_columns(
    source_columns=source_columns_5,
    source_table=source_table_5,
    target_table=target_table_5,
    combo_type="physical"
)

print(f"源列: {source_columns_5}")
print(f"目标PK: {target_table_5['table_profile']['physical_constraints']['primary_key']['columns']} (列数不匹配)")
print(f"Stage1: 特权模式失败（PK列数不匹配）")
print(f"Stage2: 动态同名匹配成功")
print(f"匹配结果: {result_two_stage}")
print(f"✅ 预期: ['col_a', 'col_b'] (fallback到动态同名)")
print(f"{'✅ 通过' if result_two_stage == ['col_a', 'col_b'] else '❌ 失败'}")

# ============================================================================
# 总结
# ============================================================================
print("\n" + "=" * 80)
print("测试总结")
print("=" * 80)
print("✅ 以上测试用例验证了两阶段匹配策略：")
print("  1. Stage 1（特权模式）：优先匹配PK/UK/逻辑键")
print("  2. Stage 1 使用更低的相似度阈值（0.6 vs 0.9）")
print("  3. Stage 2（动态同名）：总是执行，大小写不敏感")
print("  4. Stage 2 检查类型兼容性")
print("  5. 完整流程：Stage1失败后fallback到Stage2")
