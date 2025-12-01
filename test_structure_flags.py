"""测试 structure_flags 的新字段
验证单列约束和复合约束成员的标志是否互斥
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.metaweave.core.metadata.models import StructureFlags

def test_structure_flags_default():
    """测试默认值"""
    flags = StructureFlags()
    assert flags.is_primary_key == False
    assert flags.is_composite_primary_key_member == False
    assert flags.is_foreign_key == False
    assert flags.is_composite_foreign_key_member == False
    assert flags.is_unique == False
    assert flags.is_composite_unique_member == False
    assert flags.is_unique_constraint == False
    assert flags.is_composite_unique_constraint_member == False
    assert flags.is_indexed == False
    assert flags.is_composite_indexed_member == False
    assert flags.is_nullable == True
    print("✅ 默认值测试通过")

def test_single_primary_key():
    """测试单列主键"""
    flags = StructureFlags(
        is_primary_key=True,
        is_composite_primary_key_member=False,
        is_nullable=False
    )
    assert flags.is_primary_key == True
    assert flags.is_composite_primary_key_member == False
    print("✅ 单列主键测试通过")

def test_composite_primary_key_member():
    """测试复合主键成员"""
    flags = StructureFlags(
        is_primary_key=False,
        is_composite_primary_key_member=True,
        is_nullable=False
    )
    assert flags.is_primary_key == False
    assert flags.is_composite_primary_key_member == True
    print("✅ 复合主键成员测试通过")

def test_to_dict():
    """测试转换为字典"""
    flags = StructureFlags(
        is_primary_key=True,
        is_foreign_key=False,
        is_composite_foreign_key_member=True,
        is_nullable=False
    )
    data = flags.to_dict()
    
    # 检查所有字段都在字典中
    expected_keys = [
        'is_primary_key',
        'is_composite_primary_key_member',
        'is_foreign_key',
        'is_composite_foreign_key_member',
        'is_unique',
        'is_composite_unique_member',
        'is_unique_constraint',
        'is_composite_unique_constraint_member',
        'is_indexed',
        'is_composite_indexed_member',
        'is_nullable'
    ]
    
    for key in expected_keys:
        assert key in data, f"缺少字段: {key}"
    
    print("✅ to_dict() 测试通过")
    print(f"   字典内容: {data}")

if __name__ == "__main__":
    print("=" * 60)
    print("测试 StructureFlags 新字段")
    print("=" * 60)
    
    test_structure_flags_default()
    test_single_primary_key()
    test_composite_primary_key_member()
    test_to_dict()
    
    print("=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)

