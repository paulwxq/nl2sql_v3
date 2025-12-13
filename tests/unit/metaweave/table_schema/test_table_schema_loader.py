import json
from pathlib import Path
from typing import Any, Dict, List

from src.metaweave.core.loaders.table_schema_loader import TableSchemaLoader


class FakeEmbeddingService:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def get_embeddings(self, texts: List[str]) -> Dict[str, List[float]]:
        # 简单返回定长向量
        return {t: [0.1, 0.2, 0.3, 0.4] for t in texts}


class FakeMilvusClient:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.insert_calls: int = 0
        self.upsert_calls: int = 0

    def test_connection(self) -> bool:
        return True

    def connect(self) -> None:
        return None

    def ensure_collection(self, **kwargs) -> None:
        return None

    def insert_batch(self, collection_name: str, data: List[Dict[str, Any]]) -> int:
        self.insert_calls += 1
        return len(data)

    def upsert_batch(self, collection_name: str, data: List[Dict[str, Any]]) -> int:
        self.upsert_calls += 1
        return len(data)


def _write_metadata_config(tmp_path: Path) -> Path:
    cfg = {
        "embedding": {
            "active": "qwen",
            "providers": {"qwen": {"dimensions": 4}},
        },
        "vector_database": {
            "active": "milvus",
            "providers": {"milvus": {"host": "localhost", "port": 19530, "database": "nl2sql"}},
        },
    }
    meta_path = tmp_path / "metadata_config.yaml"
    meta_path.write_text(json.dumps(cfg), encoding="utf-8")
    return meta_path


def _write_md_and_json(tmp_path: Path) -> None:
    md_dir = tmp_path / "md"
    json_dir = tmp_path / "json_llm"
    md_dir.mkdir()
    json_dir.mkdir()

    md_content = """# public.dim_company（公司维表）
## 字段列表：
- company_id (integer(32)) - 公司ID（主键） [示例: 1, 2]
- company_name (character varying(200)) - 公司名称，唯一 [示例: 京东便利, 喜士多]
"""
    (md_dir / "public.dim_company.md").write_text(md_content, encoding="utf-8")

    json_content = {
        "table_profile": {"table_category": "dim"},
        "column_profiles": {
            "company_id": {"data_type": "integer"},
            "company_name": {"data_type": "varchar"},
            "created_at": {"data_type": "timestamp"},
        },
    }
    (json_dir / "public.dim_company.json").write_text(
        json.dumps(json_content), encoding="utf-8"
    )


def test_loader_clean_uses_insert(tmp_path):
    meta_cfg = _write_metadata_config(tmp_path)
    _write_md_and_json(tmp_path)

    config = {
        "metadata_config_file": str(meta_cfg),
        "table_schema_loader": {
            "md_directory": str(tmp_path / "md"),
            "json_llm_directory": str(tmp_path / "json_llm"),
            "options": {"batch_size": 2},
        },
    }

    loader = TableSchemaLoader(
        config,
        milvus_client_cls=FakeMilvusClient,
        embedding_service_cls=FakeEmbeddingService,
    )

    assert loader.validate()
    result = loader.load(clean=True)

    assert result["success"] is True
    assert result["objects_loaded"] > 0
    # 确认 clean 模式调用 insert
    assert loader._milvus_client.insert_calls >= 1  # type: ignore[attr-defined]
    assert loader._milvus_client.upsert_calls == 0  # type: ignore[attr-defined]


def test_loader_incremental_uses_upsert(tmp_path):
    meta_cfg = _write_metadata_config(tmp_path)
    _write_md_and_json(tmp_path)

    config = {
        "metadata_config_file": str(meta_cfg),
        "table_schema_loader": {
            "md_directory": str(tmp_path / "md"),
            "json_llm_directory": str(tmp_path / "json_llm"),
            "options": {"batch_size": 2},
        },
    }

    loader = TableSchemaLoader(
        config,
        milvus_client_cls=FakeMilvusClient,
        embedding_service_cls=FakeEmbeddingService,
    )

    assert loader.validate()
    result = loader.load(clean=False)

    assert result["success"] is True
    assert result["objects_loaded"] > 0
    # 确认增量模式调用 upsert
    assert loader._milvus_client.upsert_calls >= 1  # type: ignore[attr-defined]
    assert loader._milvus_client.insert_calls == 0  # type: ignore[attr-defined]

