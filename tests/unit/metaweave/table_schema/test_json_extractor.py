from src.metaweave.core.table_schema.json_extractor import JSONExtractor


def test_table_category_and_time_columns():
    json_data = {
        "table_profile": {"table_category": "dim"},
        "column_profiles": {
            "created_at": {"data_type": "TIMESTAMP WITHOUT TIME ZONE"},
            "updated_at": {"data_type": "datetime"},
            "name": {"data_type": "varchar"},
        },
    }
    extractor = JSONExtractor.from_dict(json_data)
    assert extractor.get_table_category() == "dim"
    time_cols = extractor.get_time_columns()
    assert set(time_cols) == {"created_at", "updated_at"}
    assert extractor.format_time_col_hint() == "created_at,updated_at"


def test_time_columns_variants():
    cases = [
        ("DATE", True),
        ("time", True),
        ("datetime2", True),
        ("smalldatetime", True),
        ("timestamp with time zone", True),
        ("varchar(20)", False),
    ]
    for data_type, expect_match in cases:
        extractor = JSONExtractor.from_dict(
            {"column_profiles": {"c": {"data_type": data_type}}}
        )
        cols = extractor.get_time_columns()
        assert ("c" in cols) == expect_match

