import pytest

from src.metaweave.core.table_schema.md_parser import MDParser


MD_SAMPLE = """# public.dim_company（公司维表）
## 字段列表：
- company_id (integer(32)) - 公司ID（主键） [示例: 1, 2]
- company_name (character varying(200)) - 公司名称，唯一 [示例: 京东便利, 喜士多]
## 字段补充说明：
- company_id 为主键
"""


def test_extract_table_name():
    parser = MDParser.from_string(MD_SAMPLE)
    assert parser.extract_table_name() == "public.dim_company"


def test_get_column_descriptions_standard():
    parser = MDParser.from_string(MD_SAMPLE)
    cols = parser.get_column_descriptions()
    assert cols["company_id"] == "公司ID（主键）"
    assert cols["company_name"] == "公司名称，唯一"
    # 确认遇到下一个章节后停止解析
    assert len(cols) == 2


def test_get_table_description_returns_full_content():
    parser = MDParser.from_string(MD_SAMPLE)
    desc = parser.get_table_description()
    assert "# public.dim_company" in desc
    assert "公司名称，唯一" in desc


def test_extract_table_name_invalid_title_raises():
    bad_md = "- no title\n- row"
    parser = MDParser.from_string(bad_md)
    with pytest.raises(ValueError):
        parser.extract_table_name()

