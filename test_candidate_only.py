"""只测试候选生成阶段

不涉及数据库连接，只验证候选是否能被生成
"""

import json
from pathlib import Path
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator

def load_all_tables() -> dict:
    """加载所有表的元数据"""
    json_dir = Path("output/metaweave/metadata/json")
    tables = {}
    
    for json_file in json_dir.glob("public.*.json"):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            table_info = data.get("table_info", {})
            schema = table_info.get("schema_name")
            table_name = table_info.get("table_name")
            if schema and table_name:
                full_name = f"{schema}.{table_name}"
                tables[full_name] = data
    
    return tables

def load_config() -> dict:
    """加载配置"""
    import yaml
    config_path = Path("configs/metaweave/metadata_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        full_config = yaml.safe_load(f)
    
    return {
        'single_column': full_config['single_column'],
        'composite': full_config['composite'],
        'decision': full_config['decision'],
        'weights': full_config['weights']
    }

def main():
    print("=" * 80)
    print("测试：所有表的复合键候选生成")
    print("=" * 80)
    
    # 1. 加载所有表
    print("\n[1] 加载所有表的元数据...")
    tables = load_all_tables()
    print(f"   加载了 {len(tables)} 个表")
    for table_name in sorted(tables.keys()):
        print(f"      - {table_name}")
    
    # 2. 加载配置
    print("\n[2] 加载配置...")
    config = load_config()
    composite_config = config['composite']
    print(f"   max_columns: {composite_config['max_columns']}")
    print(f"   logical_key_min_confidence: {composite_config['logical_key_min_confidence']}")
    print(f"   exclude_semantic_roles: {composite_config.get('exclude_semantic_roles', [])}")
    
    # 3. 生成所有复合键候选
    print("\n[3] 生成所有复合键候选...")
    generator = CandidateGenerator(config, set())
    all_candidates = generator._generate_composite_candidates(tables)
    
    print(f"   总候选数: {len(all_candidates)}")
    
    # 4. 统计和分析
    print("\n[4] 候选统计...")
    
    # 按源表统计
    source_stats = {}
    for candidate in all_candidates:
        source_table = candidate["source"].get("table_info", {}).get("table_name")
        if source_table not in source_stats:
            source_stats[source_table] = []
        target_table = candidate["target"].get("table_info", {}).get("table_name")
        source_cols = candidate["source_columns"]
        source_stats[source_table].append((target_table, source_cols))
    
    for source, targets in sorted(source_stats.items()):
        print(f"\n   源表: {source}")
        for target, cols in targets:
            print(f"      → {target}: {cols}")
    
    # 5. 检查目标关系
    print("\n" + "=" * 80)
    print("[5] 检查目标关系...")
    print("=" * 80)
    
    target_relations = [
        ("fault_catalog", "maintenance_work_order", 
         ["product_line_code", "subsystem_code", "fault_code"]),
        ("equipment_config", "maintenance_work_order",
         ["equipment_id", "config_version"])
    ]
    
    for source_table, target_table, expected_cols in target_relations:
        found = False
        for candidate in all_candidates:
            src = candidate["source"].get("table_info", {}).get("table_name")
            tgt = candidate["target"].get("table_info", {}).get("table_name")
            cols = candidate["source_columns"]
            
            if (src == source_table and tgt == target_table and 
                set(cols) == set(expected_cols)):
                found = True
                print(f"\n✅ {source_table} → {target_table}")
                print(f"   列: {cols}")
                print(f"   候选类型: {candidate.get('candidate_type')}")
                break
        
        if not found:
            print(f"\n❌ {source_table} → {target_table}")
            print(f"   预期列: {expected_cols}")
            print(f"   状态: 未找到")
            
            # 检查是否有该源表的其他候选
            other_candidates = []
            for candidate in all_candidates:
                src = candidate["source"].get("table_info", {}).get("table_name")
                if src == source_table:
                    tgt = candidate["target"].get("table_info", {}).get("table_name")
                    cols = candidate["source_columns"]
                    other_candidates.append((tgt, cols))
            
            if other_candidates:
                print(f"   该源表的其他候选:")
                for tgt, cols in other_candidates:
                    print(f"      → {tgt}: {cols}")
            else:
                print(f"   该源表没有任何复合键候选")
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)

if __name__ == "__main__":
    main()

