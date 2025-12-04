"""完整测试复合键候选生成流程"""
import json
import yaml
import sys
from pathlib import Path

print("=" * 80)
print("完整测试复合键候选生成流程")
print("=" * 80)

# 1. 加载配置
with open('configs/metaweave/metadata_config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

composite_config = config.get('composite', {})
max_columns = composite_config.get('max_columns', 3)
logical_key_min_confidence = composite_config.get('logical_key_min_confidence', 0.8)

print(f"\n配置:")
print(f"  max_columns: {max_columns}")
print(f"  logical_key_min_confidence: {logical_key_min_confidence}")

# 2. 加载所有表的元数据
json_dir = Path('output/metaweave/metadata/json')
tables = {}

for json_file in json_dir.glob('*.json'):
    if json_file.name.startswith('_'):
        continue

    with open(json_file, 'r', encoding='utf-8') as f:
        table_data = json.load(f)
        table_info = table_data.get('table_info', {})
        schema = table_info.get('schema_name')
        table_name = table_info.get('table_name')
        if schema and table_name:
            full_name = f"{schema}.{table_name}"
            tables[full_name] = table_data

print(f"\n加载的表数量: {len(tables)}")
print(f"表列表: {list(tables.keys())}")

# 3. 模拟 _collect_source_combinations
def collect_source_combinations(table, max_columns, logical_key_min_confidence):
    combinations = []
    table_profile = table.get("table_profile", {})

    # 逻辑主键
    logical_keys = table_profile.get("logical_keys", {})
    for lk in logical_keys.get("candidate_primary_keys", []):
        lk_cols = lk.get("columns", [])
        lk_conf = lk.get("confidence_score", 0)
        if 2 <= len(lk_cols) <= max_columns and lk_conf >= logical_key_min_confidence:
            combinations.append({"columns": lk_cols, "type": "logical"})

    return combinations

# 4. 对 fault_catalog 进行测试
fault_catalog = tables.get('public.fault_catalog')

if not fault_catalog:
    print("\n❌ 错误: 未找到 public.fault_catalog")
    sys.exit(1)

print(f"\n\n{'=' * 80}")
print(f"测试 fault_catalog 的复合键收集")
print(f"{'=' * 80}")

source_combinations = collect_source_combinations(
    fault_catalog, max_columns, logical_key_min_confidence
)

print(f"\nfault_catalog 收集到的复合键组合: {len(source_combinations)}")
for combo in source_combinations:
    print(f"  - {combo['columns']} (type={combo['type']})")

if len(source_combinations) == 0:
    print("\n❌ 问题: fault_catalog 没有收集到任何复合键组合!")
    print("   这就是为什么 '生成复合键候选: 0 个'")

    # 检查逻辑主键候选
    logical_keys = fault_catalog.get("table_profile", {}).get("logical_keys", {})
    candidate_pks = logical_keys.get("candidate_primary_keys", [])

    print(f"\n调试信息:")
    print(f"  逻辑主键候选数量: {len(candidate_pks)}")
    for pk in candidate_pks:
        print(f"    - {pk}")

else:
    print("\n✅ 成功收集到复合键组合")

    # 5. 测试是否能在 maintenance_work_order 中找到匹配
    maintenance = tables.get('public.maintenance_work_order')

    if maintenance:
        print(f"\n\n{'=' * 80}")
        print(f"测试在 maintenance_work_order 中查找匹配")
        print(f"{'=' * 80}")

        maintenance_columns = list(maintenance.get('column_profiles', {}).keys())
        print(f"\nmaintenance_work_order 的列: {maintenance_columns}")

        for combo in source_combinations:
            source_cols = combo['columns']
            print(f"\n源列组合: {source_cols}")

            # 检查是否所有列都存在
            missing = [col for col in source_cols if col not in maintenance_columns]

            if missing:
                print(f"  ❌ 缺少列: {missing}")
            else:
                print(f"  ✅ 所有列都存在")

                # 检查 Stage 1: 目标表是否有这个逻辑主键候选
                target_logical_keys = maintenance.get("table_profile", {}).get("logical_keys", {})
                target_pks = target_logical_keys.get("candidate_primary_keys", [])

                found = False
                for target_pk in target_pks:
                    if set(target_pk['columns']) == set(source_cols):
                        print(f"  ✅ Stage 1: 目标表也有这个逻辑主键候选")
                        found = True
                        break

                if not found:
                    print(f"  ❌ Stage 1: 目标表没有这个逻辑主键候选")
                    print(f"      （需要 Stage 2 动态同名匹配，但 logical 类型会跳过 Stage 2）")

print("\n" + "=" * 80)
