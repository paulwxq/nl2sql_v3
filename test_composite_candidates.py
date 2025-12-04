"""测试复合键候选生成逻辑"""
import json
import sys

# 读取 fault_catalog 的元数据
print("=" * 80)
print("测试复合键候选生成")
print("=" * 80)

with open('output/metaweave/metadata/json/public.fault_catalog.json', 'r', encoding='utf-8') as f:
    fault_catalog = json.load(f)

print("\n1. fault_catalog 的逻辑主键候选:")
logical_keys = fault_catalog['table_profile']['logical_keys']['candidate_primary_keys']
print(f"   数量: {len(logical_keys)}")
for key in logical_keys:
    print(f"   - {key['columns']} (confidence={key['confidence_score']}, uniqueness={key['uniqueness']})")

# 读取 maintenance_work_order 的元数据
with open('output/metaweave/metadata/json/public.maintenance_work_order.json', 'r', encoding='utf-8') as f:
    maintenance = json.load(f)

print("\n2. maintenance_work_order 的列:")
columns = list(maintenance['column_profiles'].keys())
print(f"   数量: {len(columns)}")
for col in columns:
    print(f"   - {col}")

# 检查匹配
print("\n3. fault_catalog 的逻辑主键能否在 maintenance_work_order 中找到匹配:")
for key in logical_keys:
    key_columns = key['columns']
    print(f"\n   逻辑主键: {key_columns}")

    # 检查每一列是否在目标表中存在
    missing_columns = []
    for col in key_columns:
        if col not in columns:
            missing_columns.append(col)

    if missing_columns:
        print(f"   ❌ 无法匹配 - 缺少列: {missing_columns}")
    else:
        print(f"   ✅ 所有列都存在于目标表")

        # 检查目标表是否有这个组合的逻辑主键候选
        target_logical_keys = maintenance['table_profile']['logical_keys']['candidate_primary_keys']
        found = False
        for target_key in target_logical_keys:
            if set(target_key['columns']) == set(key_columns):
                print(f"   ✅ 目标表也有这个逻辑主键候选")
                found = True
                break

        if not found:
            print(f"   ❌ 目标表没有这个组合的逻辑主键候选")
            print(f"      （这就是为什么 Stage 1 匹配失败的原因）")

print("\n4. 真实的业务关系（3列）:")
business_key = ['product_line_code', 'subsystem_code', 'fault_code']
print(f"   业务键: {business_key}")

missing_in_target = []
for col in business_key:
    if col not in columns:
        missing_in_target.append(col)

if missing_in_target:
    print(f"   ❌ 目标表缺少列: {missing_in_target}")
else:
    print(f"   ✅ 目标表有所有 3 列")

    # 检查源表是否有这个 3 列组合的逻辑主键候选
    has_in_source = False
    for key in logical_keys:
        if set(key['columns']) == set(business_key):
            print(f"   ✅ 源表有这个 3 列逻辑主键候选")
            has_in_source = True
            break

    if not has_in_source:
        print(f"   ❌ 源表没有这个 3 列逻辑主键候选")
        print(f"      （这就是根本问题：逻辑主键检测器没有生成正确的候选）")

print("\n" + "=" * 80)
print("结论:")
print("=" * 80)
print("1. fault_catalog 的逻辑主键检测结果是 [product_line_code, fault_name]")
print("2. maintenance_work_order 没有 fault_name 列，所以无法匹配")
print("3. 真实业务键 [product_line_code, subsystem_code, fault_code] 没有被检测为逻辑主键")
print("4. 即使有同名的 3 列，也无法通过 Stage 1 匹配（因为不是逻辑主键候选）")
print("5. Stage 2 动态同名匹配被跳过（因为源表是 logical 类型，不是 physical）")
print("=" * 80)
