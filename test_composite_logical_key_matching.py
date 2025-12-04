"""测试复合逻辑主键的动态同名匹配

验证修改后的代码是否能够发现：
fault_catalog[product_line_code, subsystem_code, fault_code] 
→ maintenance_work_order[product_line_code, subsystem_code, fault_code]
"""

import json
from pathlib import Path
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator

def load_table_metadata(table_name: str) -> dict:
    """加载表的元数据"""
    json_path = Path(f"output/metaweave/metadata/json/public.{table_name}.json")
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_config() -> dict:
    """加载配置"""
    import yaml
    config_path = Path("configs/metaweave/metadata_config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        full_config = yaml.safe_load(f)
    
    # 关系发现配置分散在多个顶级键下，需要重组
    return {
        'single_column': full_config['single_column'],
        'composite': full_config['composite'],
        'decision': full_config['decision'],
        'weights': full_config['weights']
    }

def main():
    print("=" * 80)
    print("测试复合逻辑主键的动态同名匹配")
    print("=" * 80)
    
    # 1. 加载表元数据
    print("\n[1] 加载表元数据...")
    fault_catalog = load_table_metadata("fault_catalog")
    maintenance_work_order = load_table_metadata("maintenance_work_order")
    
    tables = {
        "public.fault_catalog": fault_catalog,
        "public.maintenance_work_order": maintenance_work_order
    }
    
    # 2. 检查逻辑主键
    print("\n[2] 检查 fault_catalog 的逻辑主键候选...")
    logical_keys = fault_catalog.get("table_profile", {}).get("logical_keys", {})
    candidates = logical_keys.get("candidate_primary_keys", [])
    
    if not candidates:
        print("❌ 错误：fault_catalog 没有逻辑主键候选！")
        return
    
    for i, candidate in enumerate(candidates, 1):
        columns = candidate.get("columns", [])
        conf = candidate.get("confidence_score", 0)
        print(f"   候选 {i}: {columns}")
        print(f"   置信度: {conf}")
        print(f"   唯一性: {candidate.get('uniqueness', 0)}")
    
    # 3. 检查目标表字段
    print("\n[3] 检查 maintenance_work_order 的字段...")
    target_profiles = maintenance_work_order.get("column_profiles", {})
    
    target_columns = ["product_line_code", "subsystem_code", "fault_code"]
    for col in target_columns:
        if col in target_profiles:
            profile = target_profiles[col]
            role = profile.get("semantic_analysis", {}).get("semantic_role")
            flags = profile.get("structure_flags", {})
            print(f"   ✓ {col}: role={role}, indexed={flags.get('is_indexed', False)}")
        else:
            print(f"   ✗ {col}: 不存在！")
    
    # 4. 加载配置并生成候选
    print("\n[4] 加载配置并生成候选...")
    config = load_config()
    
    # 打印关键配置
    composite_config = config["composite"]
    print(f"   max_columns: {composite_config['max_columns']}")
    print(f"   logical_key_min_confidence: {composite_config['logical_key_min_confidence']}")
    print(f"   exclude_semantic_roles: {composite_config.get('exclude_semantic_roles', [])}")
    
    # 5. 生成候选
    print("\n[5] 生成复合键候选...")
    generator = CandidateGenerator(config, set())
    
    # 只生成复合键候选
    candidates = generator._generate_composite_candidates(tables)
    
    print(f"   生成候选数量: {len(candidates)}")
    
    # 6. 检查是否有 fault_catalog → maintenance_work_order 的候选
    print("\n[6] 检查目标关系...")
    found = False
    
    for candidate in candidates:
        source_table = candidate["source"].get("table_info", {}).get("table_name")
        target_table = candidate["target"].get("table_info", {}).get("table_name")
        source_cols = candidate["source_columns"]
        target_cols = candidate["target_columns"]
        
        if (source_table == "fault_catalog" and 
            target_table == "maintenance_work_order" and
            set(source_cols) == set(target_columns)):
            
            print(f"   ✅ 找到目标关系！")
            print(f"      源表: {source_table}")
            print(f"      目标表: {target_table}")
            print(f"      源列: {source_cols}")
            print(f"      目标列: {target_cols}")
            print(f"      候选类型: {candidate.get('candidate_type')}")
            found = True
            break
    
    if not found:
        print(f"   ❌ 未找到目标关系！")
        print(f"\n   生成的候选关系：")
        for i, candidate in enumerate(candidates, 1):
            source_table = candidate["source"].get("table_info", {}).get("table_name")
            target_table = candidate["target"].get("table_info", {}).get("table_name")
            source_cols = candidate["source_columns"]
            print(f"      {i}. {source_table}{source_cols} → {target_table}")
    
    print("\n" + "=" * 80)
    print(f"测试结果: {'✅ 通过' if found else '❌ 失败'}")
    print("=" * 80)

if __name__ == "__main__":
    main()

