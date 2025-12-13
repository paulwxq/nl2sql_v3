from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from src.metaweave.core.loaders.base import BaseLoader
from src.metaweave.core.table_schema import (
    LoaderOptions,
    MDParser,
    JSONExtractor,
    ObjectType,
    SchemaObject,
)
from src.metaweave.services.embedding_service import EmbeddingService
from src.metaweave.services.vector_db.milvus_client import MilvusClient, _lazy_import_milvus
from src.metaweave.utils.file_utils import get_project_root
from src.metaweave.utils.logger import get_metaweave_logger
from src.services.config_loader import ConfigLoader


logger = get_metaweave_logger("table_schema.loader")


class TableSchemaLoader(BaseLoader):
    """表结构加载器：读取 MD + JSON_LLM，向量化后写入 Milvus。"""

    COLLECTION_NAME = "table_schema_embeddings"

    def __init__(
        self,
        config: Dict[str, Any],
        milvus_client_cls: Type[MilvusClient] = MilvusClient,
        embedding_service_cls: Type[EmbeddingService] = EmbeddingService,
    ):
        super().__init__(config)
        loader_cfg = self.config.get("table_schema_loader", {})

        self.md_directory = self._resolve_path(loader_cfg.get("md_directory", "output/metaweave/metadata/md"))
        self.json_llm_directory = self._resolve_path(
            loader_cfg.get("json_llm_directory", "output/metaweave/metadata/json_llm")
        )
        self.metadata_config_path = self._resolve_path(
            self.config.get("metadata_config_file", "configs/metaweave/metadata_config.yaml")
        )
        self.options = LoaderOptions.from_dict(loader_cfg.get("options", {}))

        self._metadata_config: Dict[str, Any] = {}
        self._vector_db_config: Dict[str, Any] = {}
        self._milvus_client: Optional[MilvusClient] = None
        self._embedding_service: Optional[EmbeddingService] = None

        self.milvus_client_cls = milvus_client_cls
        self.embedding_service_cls = embedding_service_cls

    # ---- helpers ----
    @staticmethod
    def _resolve_path(path_str: str) -> Path:
        path = Path(path_str)
        if not path.is_absolute():
            path = get_project_root() / path
        return path

    def _load_metadata_config(self) -> Dict[str, Any]:
        try:
            loader = ConfigLoader(str(self.metadata_config_path))
            metadata_config = loader.load()
            if not metadata_config:
                raise ValueError(f"无法加载 metadata_config.yaml: {self.metadata_config_path}")
            return metadata_config
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"加载 metadata_config.yaml 失败: {exc}") from exc

    def _get_vector_db_config(self) -> Dict[str, Any]:
        metadata_config = self._metadata_config or self._load_metadata_config()
        vector_db = metadata_config.get("vector_database") or {}
        active = vector_db.get("active")
        if active != "milvus":
            raise ValueError("当前仅支持 Milvus，请设置 vector_database.active = 'milvus'")
        milvus_cfg = (vector_db.get("providers") or {}).get("milvus")
        if not milvus_cfg:
            raise ValueError("缺少 Milvus 配置: vector_database.providers.milvus")
        return milvus_cfg

    def _get_embedding_config(self) -> Dict[str, Any]:
        metadata_config = self._metadata_config or self._load_metadata_config()
        embedding_cfg = metadata_config.get("embedding") or {}
        if not embedding_cfg:
            raise ValueError("metadata_config.yaml 缺少 embedding 配置")
        return embedding_cfg

    def _get_embedding_dimension(self) -> int:
        embedding_cfg = self._get_embedding_config()
        active = embedding_cfg.get("active")
        providers = embedding_cfg.get("providers") or {}
        active_cfg = providers.get(active, {})
        dim = active_cfg.get("dimensions")
        if not dim:
            raise ValueError("未找到 embedding 维度配置 embedding.providers.{active}.dimensions")
        return int(dim)

    # ---- lifecycle ----
    def validate(self) -> bool:
        """验证配置和依赖服务。"""
        if not self.md_directory.exists():
            logger.error("md_directory 不存在: %s", self.md_directory)
            return False

        if not self.json_llm_directory.exists():
            logger.error("json_llm_directory 不存在: %s", self.json_llm_directory)
            return False

        try:
            self._metadata_config = self._load_metadata_config()
            self._vector_db_config = self._get_vector_db_config()
        except Exception as exc:  # noqa: BLE001
            logger.error("配置校验失败: %s", exc)
            return False

        try:
            self._embedding_service = self.embedding_service_cls(self._get_embedding_config())
        except Exception as exc:  # noqa: BLE001
            logger.error("Embedding 服务初始化失败: %s", exc)
            return False

        try:
            self._milvus_client = self.milvus_client_cls(self._vector_db_config)
            if not self._milvus_client.test_connection():
                return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Milvus 连接测试失败: %s", exc)
            return False

        return True

    def load(self, clean: bool = False) -> Dict[str, Any]:
        start_ts = time.time()
        result: Dict[str, Any] = {
            "success": True,
            "message": "加载成功",
            "tables_processed": 0,
            "tables_skipped": 0,
            "objects_loaded": 0,
            "objects_skipped": 0,
        }

        try:
            if not self._metadata_config:
                self._metadata_config = self._load_metadata_config()
            if not self._vector_db_config:
                self._vector_db_config = self._get_vector_db_config()
            if not self._embedding_service:
                self._embedding_service = self.embedding_service_cls(self._get_embedding_config())
            if not self._milvus_client:
                self._milvus_client = self.milvus_client_cls(self._vector_db_config)

            logger.info("初始化依赖服务: Milvus / Embedding")
            self._milvus_client.connect()

            self._ensure_collection(clean=clean)
            logger.info("确保 Collection 存在: %s", self.COLLECTION_NAME)

            md_files = sorted(self.md_directory.glob("*.md"))
            max_tables = self.options.max_tables if self.options.max_tables else len(md_files)
            md_files = md_files[:max_tables]

            for idx, md_file in enumerate(md_files, start=1):
                logger.info("[%d/%d] 处理表 Markdown: %s", idx, len(md_files), md_file.name)

                try:
                    objects = self._load_table_objects(md_file)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("跳过表 %s，原因: %s", md_file.name, exc)
                    result["tables_skipped"] += 1
                    continue

                if not objects:
                    logger.info("  - 未生成对象，跳过")
                    result["tables_skipped"] += 1
                    continue

                batch_stats = self._batch_embed_and_upsert(objects, clean=clean)
                result["objects_loaded"] += batch_stats.get("loaded", 0)
                result["objects_skipped"] += batch_stats.get("skipped", 0)
                result["tables_processed"] += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("加载失败: %s", exc, exc_info=True)
            result["success"] = False
            result["message"] = str(exc)
        finally:
            result["execution_time"] = round(time.time() - start_ts, 2)

        return result

    # ---- core steps ----
    def _ensure_collection(self, clean: bool = False) -> None:
        _, _, FieldSchema, CollectionSchema, _, DataType, _ = _lazy_import_milvus()

        dim = self._get_embedding_dimension()
        fields = [
            FieldSchema(
                name="object_id",
                dtype=DataType.VARCHAR,
                max_length=256,
                is_primary=True,
                auto_id=False,
            ),
            FieldSchema(name="object_type", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="object_desc", dtype=DataType.VARCHAR, max_length=8192),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
            FieldSchema(name="time_col_hint", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="table_category", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="updated_at", dtype=DataType.INT64),
        ]
        schema = CollectionSchema(fields=fields, description="Table and column schema embeddings for NL2SQL")
        index_params = {
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200},
        }

        assert self._milvus_client is not None
        self._milvus_client.ensure_collection(
            collection_name=self.COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
            clean=clean,
        )

    def _load_table_objects(self, md_file: Path) -> List[SchemaObject]:
        md_parser = MDParser(md_file)
        table_name = md_parser.extract_table_name()

        json_file = self.json_llm_directory / f"{table_name}.json"
        json_extractor = JSONExtractor(json_file)

        table_obj = self._parse_table_from_md(md_parser, table_name, json_extractor)
        if table_obj is None:
            return []

        objects: List[SchemaObject] = [table_obj]
        if self.options.include_columns:
            objects.extend(self._parse_columns_from_md(md_parser, table_name))
        return objects

    def _parse_table_from_md(
        self,
        md_parser: MDParser,
        table_name: str,
        json_extractor: JSONExtractor,
    ) -> Optional[SchemaObject]:
        desc = md_parser.get_table_description().strip()
        if self.options.skip_empty_desc and not desc:
            logger.warning("表描述为空，跳过表: %s", table_name)
            return None

        updated_at = int(time.time())
        return SchemaObject(
            object_type=ObjectType.TABLE,
            object_id=table_name,
            parent_id=table_name,
            object_desc=desc,
            time_col_hint=json_extractor.format_time_col_hint(),
            table_category=json_extractor.get_table_category(),
            updated_at=updated_at,
        )

    def _parse_columns_from_md(self, md_parser: MDParser, table_name: str) -> List[SchemaObject]:
        column_descs = md_parser.get_column_descriptions()
        updated_at = int(time.time())
        objects: List[SchemaObject] = []

        for col_name, col_desc in column_descs.items():
            if self.options.skip_empty_desc and not col_desc:
                continue
            objects.append(
                SchemaObject(
                    object_type=ObjectType.COLUMN,
                    object_id=f"{table_name}.{col_name}",
                    parent_id=table_name,
                    object_desc=col_desc,
                    time_col_hint=None,
                    table_category=None,
                    updated_at=updated_at,
                )
            )

        return objects

    def _batch_embed_and_upsert(self, objects: List[SchemaObject], clean: bool = False) -> Dict[str, int]:
        if not objects:
            return {"loaded": 0, "skipped": 0}

        assert self._embedding_service is not None
        assert self._milvus_client is not None

        loaded_total = 0
        skipped_total = 0

        for batch in self._iter_batches(objects, self.options.batch_size):
            texts = [obj.object_desc for obj in batch]
            embeddings = None
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    embeddings = self._embedding_service.get_embeddings(texts)
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt < max_retries:
                        logger.warning("向量化失败（尝试 %d/%d），重试中: %s", attempt + 1, max_retries + 1, exc)
                    else:
                        logger.error("向量化失败（已重试 %d 次），跳过该批次 %d 条记录: %s", max_retries, len(batch), exc)
                        skipped_total += len(batch)
            if embeddings is None:
                continue

            enriched: List[Dict[str, Any]] = []
            for obj in batch:
                vec = embeddings.get(obj.object_desc)
                if vec is None:
                    skipped_total += 1
                    continue

                embedding_list = vec.tolist() if hasattr(vec, "tolist") else vec
                enriched.append(obj.to_milvus_dict(embedding=embedding_list))

            if not enriched:
                continue

            if clean:
                loaded_total += self._milvus_client.insert_batch(self.COLLECTION_NAME, enriched)
            else:
                loaded_total += self._milvus_client.upsert_batch(self.COLLECTION_NAME, enriched)

        return {"loaded": loaded_total, "skipped": skipped_total}

    @staticmethod
    def _iter_batches(items: List[SchemaObject], batch_size: int) -> List[List[SchemaObject]]:
        for i in range(0, len(items), batch_size):
            yield items[i : i + batch_size]


__all__ = ["TableSchemaLoader"]

