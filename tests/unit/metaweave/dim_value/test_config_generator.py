import json
from pathlib import Path

from src.metaweave.core.dim_value.config_generator import DimTableConfigGenerator
from src.metaweave.core.dim_value.models import DimTablesConfig


def test_generate_dim_tables(tmp_path: Path):
    json_dir = tmp_path / "json_llm"
    json_dir.mkdir()

    # dim 表
    (json_dir / "dim_company.json").write_text(
        json.dumps(
            {
                "table_profile": {"table_category": "dim", "schema_name": "public", "table_name": "dim_company"}
            }
        ),
        encoding="utf-8",
    )
    # 非 dim 表
    (json_dir / "fact_sales.json").write_text(
        json.dumps(
            {
                "table_profile": {"table_category": "fact", "schema_name": "public", "table_name": "fact_sales"}
            }
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "dim_tables.yaml"
    generator = DimTableConfigGenerator(json_llm_dir=json_dir, output_path=output_path)

    config = generator.generate()
    assert "public.dim_company" in config["tables"]
    assert "public.dim_sales" not in config["tables"]
    assert output_path.exists()

    parsed = DimTablesConfig.from_yaml(config)
    assert "public.dim_company" in parsed.tables
    assert parsed.tables["public.dim_company"].embedding_col is None

