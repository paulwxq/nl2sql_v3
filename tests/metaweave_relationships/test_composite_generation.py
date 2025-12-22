"""测试复合键候选生成逻辑"""
import json
import sys

print("=" * 80)
print("测试复合键候选生成逻辑")
print("=" * 80)

# 读取配置
import yaml
with open('configs/metaweave/metadata_config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

composite_config = config.get('composite', {})
max_columns = composite_config.get('max_columns', 3)
logical_key_min_confidence = composite_config.get('logical_key_min_confidence', 0.8)

print(f"\n配置:")
print(f"  max_columns: {max_columns}")
print(f"  logical_key_min_confidence: {logical_key_min_confidence}")

# 读取 fault_catalog
with open('output/metaweave/metadata/json/public.fault_catalog.json', 'r', encoding='utf-8') as f:
    fault_catalog = json.load(f)

table_profile = fault_catalog.get("table_profile", {})
logical_keys = table_profile.get("logical_keys", {})
candidate_primary_keys = logical_keys.get("candidate_primary_keys", [])

print(f"\nfault_catalog 逻辑主键候选数量: {len(candidate_primary_keys)}")

combinations = []
for lk in candidate_primary_keys:
    lk_cols = lk.get("columns", [])
    lk_conf = lk.get("confidence_score", 0)

    print(f"\n  候选: {lk_cols}")
    print(f"    confidence_score: {lk_conf}")
    print(f"    列数: {len(lk_cols)}")

    # 检查条件
    print(f"\n  检查条件:")
    print(f"    列数检查: 2 <= {len(lk_cols)} <= {max_columns} = {2 <= len(lk_cols) <= max_columns}")
    print(f"    置信度检查: {lk_conf} >= {logical_key_min_confidence} = {lk_conf >= logical_key_min_confidence}")

    if 2 <= len(lk_cols) <= max_columns and lk_conf >= logical_key_min_confidence:
        combinations.append({"columns": lk_cols, "type": "logical"})
        print(f"    ✅ 通过！添加到候选")
    else:
        print(f"    ❌ 未通过！")
        if not (2 <= len(lk_cols) <= max_columns):
            print(f"       原因: 列数 {len(lk_cols)} 不在 [2, {max_columns}] 范围内")
        if not (lk_conf >= logical_key_min_confidence):
            print(f"       原因: 置信度 {lk_conf} < {logical_key_min_confidence}")

print(f"\n最终收集到的复合键组合数: {len(combinations)}")

if len(combinations) == 0:
    print("\n❌ 问题: 没有收集到任何复合键组合！")
    print("   这就是为什么 '生成复合键候选: 0 个'")
else:
    print("\n✅ 成功收集到复合键组合:")
    for combo in combinations:
        print(f"   - {combo['columns']} (type={combo['type']})")

print("\n" + "=" * 80)
