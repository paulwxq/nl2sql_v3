from pathlib import Path
import yaml

import pytest

from src.metaweave.core.dim_value.models import LoaderOptions
from src.metaweave.core.loaders.dim_value_loader import ConfigurationError, DimValueLoader


class FakeMilvusClient:
    def __init__(self, config):
        self.config = config
        self.inserted = []
        self.collection = None

    def test_connection(self) -> bool:
        return True

    def ensure_collection(self, collection_name, schema, index_params, clean=False):
        self.collection = collection_name

    def insert_batch(self, collection_name, data):
        self.inserted.extend(data)
        return len(data)

    def close(self):
        pass


class FakeEmbeddingService:
    def __init__(self, cfg):
        self.cfg = cfg

    def get_embeddings(self, texts):
        return {t: [0.1, 0.2] for t in texts}


class FakePGManager:
    def __init__(self, cfg=None):
        self.cfg = cfg

    def test_connection(self) -> bool:  # pragma: no cover - 简单返回 True
        return True

    def get_connection(self):  # pragma: no cover - 测试中不会调用
        raise RuntimeError("should be patched")


def _write_metadata_config(path: Path):
    path.write_text(
        yaml.safe_dump(
            {
                "database": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "db",
                    "user": "u",
                    "password": "p",
                },
                "embedding": {
                    "active": "qwen",
                    "providers": {"qwen": {"model": "text-embedding-v3", "api_key": "k", "dimensions": 1024}},
                },
                "vector_database": {
                    "active": "milvus",
                    "providers": {"milvus": {"host": "localhost", "port": 19530, "database": "nl2sql"}},
                },
            }
        ),
        encoding="utf-8",
    )


def test_vector_db_config_missing_raises(tmp_path: Path):
    metadata_path = tmp_path / "metadata_config.yaml"
    metadata_path.write_text("embedding: {}\n", encoding="utf-8")

    dim_tables = tmp_path / "dim_tables.yaml"
    dim_tables.write_text("tables: {}\n", encoding="utf-8")

    loader = DimValueLoader(
        {
            "dim_loader": {"config_file": str(dim_tables)},
            "metadata_config_file": str(metadata_path),
        }
    )

    with pytest.raises(ConfigurationError):
        loader._get_vector_db_config()


def test_loader_loads_and_cleans_duplicate_values(tmp_path: Path):
    metadata_path = tmp_path / "metadata_config.yaml"
    _write_metadata_config(metadata_path)

    dim_tables = tmp_path / "dim_tables.yaml"
    dim_tables.write_text(
        yaml.safe_dump({"tables": {"public.dim_company": {"embedding_col": "company_name"}}}),
        encoding="utf-8",
    )

    loader = DimValueLoader(
        {
            "dim_loader": {
                "config_file": str(dim_tables),
                "options": {"batch_size": 2},
            },
            "metadata_config_file": str(metadata_path),
        },
        milvus_client_cls=FakeMilvusClient,
        pg_manager_cls=FakePGManager,
        embedding_service_cls=FakeEmbeddingService,
    )

    # 避免真实数据库访问
    loader._fetch_table_data = lambda schema, table, col: [
        {"col_value": "Apple"},
        {"col_value": "Banana"},
        {"col_value": "Apple"},  # 重复
    ]
    loader._ensure_collection = lambda clean=False: None

    result = loader.load(clean=False)

    assert result["success"] is True
    assert result["records_loaded"] == 2  # 去重后两条
    assert result["records_skipped"] >= 1

    assert isinstance(loader.options, LoaderOptions)
    assert loader.options.batch_size == 2

    # 确认数据插入被调用
    assert isinstance(loader._milvus_client, FakeMilvusClient)
    assert len(loader._milvus_client.inserted) == 2

