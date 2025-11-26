import pandas as pd

from src.metaweave.core.metadata.models import (
    ColumnInfo,
    ForeignKey,
    PrimaryKey,
    TableMetadata,
)
from src.metaweave.core.metadata.profiler import MetadataProfiler


def _build_metadata():
    metadata = TableMetadata(
        schema_name="public",
        table_name="fact_sales",
        comment="店铺销售日流水事实表",
    )
    metadata.columns = [
        ColumnInfo(column_name="store_id", ordinal_position=1, data_type="integer", is_nullable=False),
        ColumnInfo(column_name="date_day", ordinal_position=2, data_type="date", is_nullable=False),
        ColumnInfo(column_name="amount", ordinal_position=3, data_type="numeric", is_nullable=False),
    ]
    metadata.primary_keys = [PrimaryKey(constraint_name="pk_fact_sales", columns=["store_id", "date_day"])]
    metadata.foreign_keys = [
        ForeignKey(
            constraint_name="fk_sales_store",
            source_columns=["store_id"],
            target_schema="public",
            target_table="dim_store",
            target_columns=["store_id"],
        )
    ]
    return metadata


def test_profiler_generates_column_and_table_profiles():
    metadata = _build_metadata()
    df = pd.DataFrame(
        {
            "store_id": [1, 2, 3, 1],
            "date_day": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-02", "2024-01-01"]),
            "amount": [100, 120, 130, 110],
        }
    )

    profiler = MetadataProfiler()
    result = profiler.profile(metadata, df)

    assert "store_id" in result.column_profiles
    store_profile = result.column_profiles["store_id"]
    assert store_profile.semantic_role == "identifier"
    assert store_profile.structure_flags.is_foreign_key

    amount_profile = result.column_profiles["amount"]
    assert amount_profile.semantic_role == "metric"
    assert amount_profile.metric_info is not None

    assert result.table_profile is not None
    assert result.table_profile.table_category == "fact"

