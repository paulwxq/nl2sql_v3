"""完整测试关系发现流程

测试从候选生成 → 评分 → 决策的完整流程
"""

import json
from pathlib import Path
from src.metaweave.core.relationships.candidate_generator import CandidateGenerator
from src.metaweave.core.relationships.scorer import RelationshipScorer
from src.metaweave.core.relationships.decision_engine import DecisionEngine

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
    
    return {
        'single_column': full_config['single_column'],
        'composite': full_config['composite'],
        'decision': full_config['decision'],
        'weights': full_config['weights']
    }

def main():
    print("=" * 80)
    print("完整测试：fault_catalog → maintenance_work_order 关系发现流程")
    print("=" * 80)
    
    # 1. 加载表元数据
    print("\n[1] 加载表元数据...")
    fault_catalog = load_table_metadata("fault_catalog")
    maintenance_work_order = load_table_metadata("maintenance_work_order")
    
    tables = {
        "public.fault_catalog": fault_catalog,
        "public.maintenance_work_order": maintenance_work_order
    }
    
    # 2. 加载配置
    print("\n[2] 加载配置...")
    config = load_config()
    
    # 3. 生成候选
    print("\n[3] 生成候选...")
    generator = CandidateGenerator(config, set())
    candidates = generator._generate_composite_candidates(tables)
    
    print(f"   总候选数: {len(candidates)}")
    
    # 找到目标候选
    target_candidate = None
    for candidate in candidates:
        source_table = candidate["source"].get("table_info", {}).get("table_name")
        target_table = candidate["target"].get("table_info", {}).get("table_name")
        source_cols = candidate["source_columns"]
        
        if (source_table == "fault_catalog" and 
            target_table == "maintenance_work_order"):
            target_candidate = candidate
            print(f"   ✓ 找到目标候选: {source_table}{source_cols} → {target_table}")
            break
    
    if not target_candidate:
        print("   ✗ 未找到目标候选！")
        return
    
    # 4. 评分
    print("\n[4] 对候选进行评分...")
    scorer = RelationshipScorer(config)
    
    # 只对目标候选评分
    scored = scorer.score_candidates([target_candidate])
    
    if not scored:
        print("   ✗ 评分失败！")
        return
    
    scored_candidate = scored[0]
    print(f"   ✓ 评分完成:")
    print(f"      综合得分: {scored_candidate['composite_score']:.3f}")
    print(f"      得分明细:")
    for key, value in scored_candidate['score_details'].items():
        print(f"        - {key}: {value:.3f}")
    
    # 5. 决策
    print("\n[5] 决策引擎过滤...")
    decision_engine = DecisionEngine(config)
    
    accept_threshold = config['decision']['accept_threshold']
    print(f"   接受阈值: {accept_threshold}")
    print(f"   候选得分: {scored_candidate['composite_score']:.3f}")
    
    if scored_candidate['composite_score'] >= accept_threshold:
        print(f"   ✓ 候选得分超过阈值，应该被接受")
    else:
        print(f"   ✗ 候选得分低于阈值，会被拒绝")
        print(f"\n   【关键问题】得分过低的原因分析：")
        details = scored_candidate['score_details']
        for metric, score in details.items():
            status = "✓" if score >= 0.8 else "✗"
            print(f"      {status} {metric}: {score:.3f}")
    
    # 应用决策
    accepted_relations, suppressed = decision_engine.filter_and_suppress([scored_candidate])
    
    print(f"\n[6] 决策结果...")
    print(f"   接受的关系数: {len(accepted_relations)}")
    print(f"   抑制的关系数: {len(suppressed)}")
    
    if accepted_relations:
        print(f"   ✅ 目标关系被接受！")
        rel = accepted_relations[0]
        print(f"      关系ID: {rel.relationship_id}")
        print(f"      源表: {rel.source_schema}.{rel.source_table}")
        print(f"      目标表: {rel.target_schema}.{rel.target_table}")
        print(f"      源列: {rel.source_columns}")
        print(f"      目标列: {rel.target_columns}")
        print(f"      基数: {rel.cardinality}")
        print(f"      得分: {rel.composite_score:.3f}")
    else:
        print(f"   ❌ 目标关系被拒绝或抑制！")
        if suppressed:
            print(f"\n   被抑制的原因:")
            print(f"      可能存在更好的复合关系，导致该关系被抑制")
    
    print("\n" + "=" * 80)
    success = len(accepted_relations) > 0
    print(f"最终结果: {'✅ 关系被发现并接受' if success else '❌ 关系未通过决策'}")
    print("=" * 80)

if __name__ == "__main__":
    main()

