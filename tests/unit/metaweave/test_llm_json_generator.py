import json
from typing import Dict

import pandas as pd
import pytest

from src.metaweave.core.metadata.llm_json_generator import LLMJsonGenerator
from src.metaweave.core.metadata.models import ColumnInfo, PrimaryKey, TableMetadata


class _FakeLLMService:
    def __init__(self, *_args, **_kwargs):
        pass

    def _call_llm(self, _prompt):
        return "{}"

    async def batch_call_llm_async(self, prompts, on_progress=None):
        if on_progress:
            on_progress(len(prompts), len(prompts))
        return ["{}" for _ in prompts]


class _DummyConnector:
    """占位连接器，避免实际数据库依赖"""

    def __init__(self):
        pass


def _make_generator(tmp_path, overrides=None):
    cfg = {
        "output": {"json_llm_directory": str(tmp_path)},
        "sampling": {"sample_size": 10, "column_statistics": {"value_distribution_threshold": 10}},
        "llm": {
            "langchain_config": {"use_async": False, "batch_size": 10},
            "comment_generation": {
                "enabled": True,
                "generate_table_comment": True,
                "generate_column_comment": True,
                "language": "zh",
                "max_columns_per_call": 120,
                "max_sample_rows": 3,
                "max_sample_cols": 20,
                "enable_batch_processing": True,
                "overwrite_existing": False,
                "fallback_on_parse_error": True,
                "log_failed_responses": True,
            },
        },
    }
    if overrides:
        cfg["llm"]["comment_generation"].update(overrides.get("comment_generation", {}))
    return LLMJsonGenerator(cfg, connector=_DummyConnector())


def _basic_metadata():
    meta = TableMetadata(schema_name="public", table_name="employee", comment="已有表注释")
    meta.columns = [
        ColumnInfo("id", 1, "integer", is_nullable=False, comment="主键", comment_source="db"),
        ColumnInfo("name", 2, "text", is_nullable=True, comment="", comment_source=""),
    ]
    return meta


@pytest.fixture(autouse=True)
def patch_llm_service(monkeypatch):
    monkeypatch.setattr(
        "src.metaweave.core.metadata.llm_json_generator.LLMService", _FakeLLMService
    )


def test_merge_skips_existing_comments(tmp_path):
    gen = _make_generator(tmp_path)
    meta = _basic_metadata()
    table_json = gen._build_simplified_json(meta, sample_df=None)

    profile = {
        "table_category": "dim",
        "table_comment": "新表注释",
        "column_comments": {"id": "应跳过", "name": "姓名注释"},
    }

    gen._merge_and_save(table_json, profile)

    output_path = tmp_path / "public.employee.json"
    saved = json.loads(output_path.read_text(encoding="utf-8"))

    # 表注释不应被覆盖
    assert saved["table_info"]["comment"] == "已有表注释"
    assert saved["table_info"]["comment_source"] == "db"

    # 已有字段注释不覆盖，缺失字段被填充
    assert saved["column_profiles"]["id"]["comment"] == "主键"
    assert saved["column_profiles"]["id"]["comment_source"] == "db"
    assert saved["column_profiles"]["name"]["comment"] == "姓名注释"
    assert saved["column_profiles"]["name"]["comment_source"] == "llm_generated"

    # 分类写入
    assert saved["table_profile"]["table_category"] == "dim"


def test_token_optimization_truncates_rows_cols(tmp_path):
    gen = _make_generator(tmp_path)
    gen.max_sample_rows = 2
    gen.max_sample_cols = 2
    meta = TableMetadata(schema_name="public", table_name="dept")
    meta.columns = [
        ColumnInfo("id", 1, "int", is_nullable=False, comment="主键", comment_source="db"),
        ColumnInfo("name", 2, "text", is_nullable=True, comment="", comment_source=""),
        ColumnInfo("desc", 3, "text", is_nullable=True, comment="", comment_source=""),
        ColumnInfo("extra1", 4, "text", is_nullable=True, comment="", comment_source=""),
        ColumnInfo("extra2", 5, "text", is_nullable=True, comment="", comment_source=""),
    ]
    df = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "name": ["a", "b", "c"],
            "desc": ["x", "y", "z"],
            "extra1": ["e1", "e2", "e3"],
            "extra2": ["f1", "f2", "f3"],
        }
    )

    meta.primary_keys = [PrimaryKey(constraint_name="pk_dept", columns=["id"])]

    base_json = gen._build_simplified_json(meta, sample_df=df)
    missing_cols = base_json["_metadata"]["missing_column_comments"]
    optimized = gen._build_simplified_json_for_llm(base_json, missing_cols)

    # 行截断到 2 行
    assert len(optimized["sample_records"]["records"]) == 2
    assert optimized["sample_records"]["_truncated_rows"] is True

    # 列截断到 2 列（优先保留主键 + 缺失字段）
    for rec in optimized["sample_records"]["records"]:
        assert len(rec.keys()) == 2
        assert "id" in rec
    assert optimized["sample_records"]["_truncated_cols"] is True

    # 已有注释字段统计被简化
    id_stats = optimized["column_profiles"]["id"]["statistics"]
    assert set(id_stats.keys()) == {"sample_count", "unique_count", "_simplified"}


def test_batching_splits_missing_columns(tmp_path):
    gen = _make_generator(tmp_path)
    gen.max_columns_per_call = 2
    meta = TableMetadata(schema_name="public", table_name="big_table")
    meta.columns = [
        ColumnInfo(f"c{i}", i, "text", is_nullable=True, comment="", comment_source="") for i in range(1, 6)
    ]
    table_json = gen._build_simplified_json(meta, sample_df=None)

    batch_calls = []

    def fake_infer(table_json_arg: Dict) -> Dict:
        batch_cols = table_json_arg["_metadata"]["missing_column_comments"]
        batch_calls.append(batch_cols)
        return {
            "table_category": "dim",
            "table_comment": "表注释",
            "column_comments": {c: f"注释_{c}" for c in batch_cols},
        }

    gen._infer_table_profile_sync = fake_infer  # type: ignore

    profile = gen._generate_single_table_with_batching(table_json)

    # 批次数应为 3（2,2,1）
    assert batch_calls == [["c1", "c2"], ["c3", "c4"], ["c5"]]
    assert len(profile["column_comments"]) == 5
    assert profile["column_comments"]["c5"] == "注释_c5"
    assert profile["table_category"] == "dim"

