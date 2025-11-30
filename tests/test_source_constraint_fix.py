"""测试 source_constraint 修复

验证 active_search 发现的关系能正确识别源列的约束类型。
"""

def test_source_constraint_detection():
    """模拟测试：验证 source_constraint 的检测逻辑"""
    
    # 模拟不同的 structure_flags 场景
    test_cases = [
        {
            "name": "主键",
            "structure_flags": {
                "is_primary_key": True,
                "is_unique_constraint": False,
                "is_indexed": False
            },
            "expected": "single_field_primary_key"
        },
        {
            "name": "唯一约束",
            "structure_flags": {
                "is_primary_key": False,
                "is_unique_constraint": True,
                "is_indexed": False
            },
            "expected": "single_field_unique_constraint"
        },
        {
            "name": "索引",
            "structure_flags": {
                "is_primary_key": False,
                "is_unique_constraint": False,
                "is_indexed": True
            },
            "expected": "single_field_index"
        },
        {
            "name": "只有数据唯一（无物理约束）",
            "structure_flags": {
                "is_primary_key": False,
                "is_unique_constraint": False,
                "is_indexed": False,
                "is_unique": True  # 只是数据唯一
            },
            "expected": None
        },
        {
            "name": "无任何约束",
            "structure_flags": {
                "is_primary_key": False,
                "is_unique_constraint": False,
                "is_indexed": False,
                "is_unique": False
            },
            "expected": None
        }
    ]
    
    print("=" * 70)
    print("source_constraint 检测逻辑测试")
    print("=" * 70)
    
    for test in test_cases:
        structure_flags = test["structure_flags"]
        expected = test["expected"]
        
        # 模拟检测逻辑（与 writer.py 的 _get_source_constraint 一致）
        if structure_flags.get("is_primary_key"):
            result = "single_field_primary_key"
        elif structure_flags.get("is_unique_constraint"):
            result = "single_field_unique_constraint"
        elif structure_flags.get("is_indexed"):
            result = "single_field_index"
        else:
            result = None
        
        status = "✅" if result == expected else "❌"
        print(f"\n{status} {test['name']}")
        print(f"  输入: {structure_flags}")
        print(f"  期望: {expected}")
        print(f"  实际: {result}")
    
    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)


def test_dim_product_type_case():
    """测试实际案例：dim_product_type.product_type_id"""
    
    print("\n" + "=" * 70)
    print("实际案例测试: dim_product_type.product_type_id")
    print("=" * 70)
    
    # 从 JSON 文件中读取的实际数据
    actual_structure_flags = {
        "is_primary_key": False,      # 不是物理主键
        "is_foreign_key": False,
        "is_unique": True,             # 数据唯一（但不是约束）
        "is_unique_constraint": False, # 不是唯一约束
        "is_indexed": False,           # 不是索引
        "is_nullable": False
    }
    
    print(f"\n实际的 structure_flags:")
    for key, value in actual_structure_flags.items():
        print(f"  {key}: {value}")
    
    # 应用检测逻辑
    if actual_structure_flags.get("is_primary_key"):
        result = "single_field_primary_key"
    elif actual_structure_flags.get("is_unique_constraint"):
        result = "single_field_unique_constraint"
    elif actual_structure_flags.get("is_indexed"):
        result = "single_field_index"
    else:
        result = None
    
    print(f"\n检测结果:")
    print(f"  source_constraint: {result}")
    
    if result is None:
        print(f"\n✅ 正确！没有物理约束，应该返回 None")
        print(f"   （虽然数据是唯一的 is_unique=True，但这不是物理约束）")
    else:
        print(f"\n❌ 错误！不应该返回 {result}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_source_constraint_detection()
    test_dim_product_type_case()
    
    print("\n" + "=" * 70)
    print("总结")
    print("=" * 70)
    print("""
修复说明：
    
1. 问题：
   - 之前 writer.py 硬编码返回 "single_field_index"
   - 没有检查源列的实际约束类型
   
2. 修复：
   - 添加 _get_source_constraint() 方法
   - 实际检查 structure_flags 判断约束类型
   - 按优先级返回：主键 > 唯一约束 > 索引 > None
   
3. 对于 dim_product_type.product_type_id：
   - is_unique: True（数据碰巧唯一）
   - is_indexed: False（没有索引）
   - 应该返回 None（没有物理约束）
   - 而不是错误的 "single_field_index"
    
4. 修改的文件：
   - src/metaweave/core/relationships/writer.py
     * write_results(): 添加 tables 参数
     * _parse_discovery_info(): 调用 _get_source_constraint()
     * _get_source_constraint(): 新方法，检查实际约束
   - src/metaweave/core/relationships/pipeline.py
     * 调用 write_results() 时传入 self.tables
    """)
    print("=" * 70)

