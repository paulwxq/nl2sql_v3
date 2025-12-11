"""维度值加载器：将维表文本列向量化后写入 Milvus。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Type

from psycopg import sql

from src.metaweave.core.dim_value.models import DimTablesConfig, LoaderOptions
from src.metaweave.core.loaders.base import BaseLoader
from src.metaweave.services.embedding_service import EmbeddingService
from src.metaweave.services.vector_db.milvus_client import MilvusClient, _lazy_import_milvus
from src.metaweave.services.vector_db.pgvector_client import PgVectorClient
from src.metaweave.utils.file_utils import get_project_root, load_yaml
from src.metaweave.utils.logger import get_metaweave_logger
from src.services.db.pg_connection import PGConnectionManager
from src.services.config_loader import ConfigLoader

logger = get_metaweave_logger("dim_value.loader")


class ConfigurationError(Exception):
    """配置错误。"""


class DataValidationError(Exception):
    """数据验证错误。"""


class EmbeddingError(Exception):
    """向量化失败（如 API 限流或超时）。"""


class DimValueLoader(BaseLoader):
    """维度值加载器。

    从 PostgreSQL 读取维表数据，调用 Embedding 模型向量化后，
    加载到向量数据库（当前仅支持 Milvus）的 dim_value_embeddings Collection。
    """

    COLLECTION_NAME = "dim_value_embeddings"

    def __init__(
        self,
        config: Dict[str, Any],
        milvus_client_cls: Type[MilvusClient] = MilvusClient,
        pg_manager_cls: Type[PGConnectionManager] = PGConnectionManager,
        embedding_service_cls: Type[EmbeddingService] = EmbeddingService,
    ):
        super().__init__(config)
        self.milvus_client_cls = milvus_client_cls
        self.pg_manager_cls = pg_manager_cls
        self.embedding_service_cls = embedding_service_cls

        loader_cfg = self.config.get("dim_loader", {})

        self.dim_tables_path = self._resolve_path(
            loader_cfg.get("config_file", "configs/metaweave/dim_tables.yaml")
        )
        self.metadata_config_path = self._resolve_path(
            self.config.get("metadata_config_file", "configs/metaweave/metadata_config.yaml")
        )

        self.options = LoaderOptions.from_dict(loader_cfg.get("options", {}))

        self._metadata_config: Dict[str, Any] = {}
        self._vector_db_config: Dict[str, Any] = {}
        self._milvus_client: MilvusClient | None = None
        self._embedding_service: EmbeddingService | None = None
        self._pg_manager: PGConnectionManager | None = None

    def _retry(
        self,
        func,
        retries: int = 3,
        delay: int = 2,
        desc: str | None = None,
    ) -> Any:
        """简单重试封装，用于连接类操作。"""

        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return func()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < retries:
                    logger.warning(
                        "%s失败（尝试 %d/%d），%d 秒后重试: %s",
                        desc or func.__name__,
                        attempt,
                        retries,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "%s失败（已重试 %d 次）: %s",
                        desc or func.__name__,
                        retries,
                        exc,
                    )
                    raise
        if last_exc:
            raise last_exc

    # ---- helpers ----
    @staticmethod
    def _resolve_path(path_str: str) -> Path:
        path = Path(path_str)
        if not path.is_absolute():
            path = get_project_root() / path
        return path

    def _load_metadata_config(self) -> Dict[str, Any]:
        """加载 metadata_config.yaml，并替换环境变量占位符"""
        try:
            # 使用 ConfigLoader 以支持环境变量替换（如 ${MILVUS_HOST:localhost}）
            config_loader = ConfigLoader(str(self.metadata_config_path))
            metadata_config = config_loader.load()
            if not metadata_config:
                raise ConfigurationError(f"无法加载 metadata_config.yaml: {self.metadata_config_path}")
            return metadata_config
        except Exception as exc:
            raise ConfigurationError(
                f"加载 metadata_config.yaml 失败: {self.metadata_config_path}\n"
                f"原因: {exc}"
            ) from exc

    def _get_vector_db_config(self) -> Dict[str, Any]:
        metadata_config = self._metadata_config or self._load_metadata_config()
        if "vector_database" not in metadata_config:
            raise ConfigurationError("metadata_config.yaml 缺少 'vector_database' 配置段")

        vector_database = metadata_config["vector_database"]
        required_fields = ["active", "providers"]
        for field in required_fields:
            if field not in vector_database:
                raise ConfigurationError(f"vector_database 缺少必填字段: {field}")

        active = vector_database.get("active")
        if active != "milvus":
            raise ConfigurationError(
                f"当前版本仅支持 Milvus，但配置为: {active}；请设置 vector_database.active = 'milvus'"
            )

        providers = vector_database.get("providers", {})
        milvus_cfg = providers.get("milvus")
        if not milvus_cfg:
            raise ConfigurationError("未找到 Milvus 的配置: vector_database.providers.milvus")
        return milvus_cfg

    # ---- lifecycle ----
    def validate(self) -> bool:
        """验证配置与依赖服务。"""

        if not self.dim_tables_path.exists():
            logger.error("dim_tables.yaml 不存在: %s", self.dim_tables_path)
            return False

        try:
            self._metadata_config = self._load_metadata_config()
            self._vector_db_config = self._get_vector_db_config()
        except Exception as exc:  # noqa: BLE001
            logger.error("配置校验失败: %s", exc)
            return False

        try:
            self._embedding_service = self.embedding_service_cls(self._metadata_config.get("embedding", {}))
        except Exception as exc:  # noqa: BLE001
            logger.error("Embedding 服务初始化失败: %s", exc)
            return False

        try:
            self._milvus_client = self.milvus_client_cls(self._vector_db_config)
            if not self._retry(self._milvus_client.test_connection, desc="Milvus 连接测试"):
                return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Milvus 连接测试失败: %s", exc)
            return False

        try:
            self._pg_manager = self.pg_manager_cls(self._metadata_config.get("database"))
            if not self._retry(self._pg_manager.test_connection, desc="PostgreSQL 连接测试"):
                return False
        except Exception as exc:  # noqa: BLE001
            logger.error("PostgreSQL 连接测试失败: %s", exc)
            return False

        return True

    def load(self, clean: bool = False) -> Dict[str, Any]:
        """执行加载操作。"""

        start_ts = time.time()
        total_tables = 0
        result: Dict[str, Any] = {
            "success": True,
            "message": "加载成功",
            "tables_processed": 0,
            "tables_skipped": 0,
            "records_loaded": 0,
            "records_skipped": 0,
        }

        try:
            logger.info("开始加载维度值到 Milvus (collection=%s)", self.COLLECTION_NAME)
            if not self._metadata_config:
                self._metadata_config = self._load_metadata_config()
            if not self._vector_db_config:
                self._vector_db_config = self._get_vector_db_config()
            if not self._embedding_service:
                self._embedding_service = self.embedding_service_cls(self._metadata_config.get("embedding", {}))
            if not self._milvus_client:
                self._milvus_client = self.milvus_client_cls(self._vector_db_config)
            if not self._pg_manager:
                self._pg_manager = self.pg_manager_cls(self._metadata_config.get("database"))

            logger.info("初始化依赖服务: PostgreSQL / Milvus / Embedding")
            self._retry(self._milvus_client.connect, desc="Milvus 连接")
            if hasattr(self._pg_manager, "initialize"):
                try:
                    self._retry(self._pg_manager.initialize, desc="PostgreSQL 初始化")
                except Exception:  # noqa: BLE001
                    logger.warning("PostgreSQL 初始化失败，将在首次访问时重试", exc_info=True)

            dim_tables_config = self._load_dim_tables()
            total_tables = len(dim_tables_config.tables)
            logger.info("读取配置: %s (%d 个维表)", self.dim_tables_path, total_tables)

            db_cfg = self._metadata_config.get("database", {})
            logger.info(
                "连接 PostgreSQL: %s:%s/%s",
                db_cfg.get("host", "-"),
                db_cfg.get("port", "-"),
                db_cfg.get("database", "-"),
            )

            milvus_cfg = self._vector_db_config
            logger.info(
                "连接 Milvus: %s:%s/%s",
                milvus_cfg.get("host", "-"),
                milvus_cfg.get("port", "-"),
                milvus_cfg.get("database", "-"),
            )

            self._ensure_collection(clean=clean)
            logger.info("确保 Collection 存在: %s", self.COLLECTION_NAME)

            for idx, dim_cfg in enumerate(dim_tables_config.tables.values(), start=1):
                # 使用 embedding_cols_list 获取列名列表（支持单列或多列）
                embedding_cols = dim_cfg.embedding_cols_list

                # 验证列名
                if not embedding_cols:
                    logger.warning(
                        "[%d/%d] ⚠️  跳过表 %s：embedding_col 未配置或为空",
                        idx,
                        total_tables,
                        dim_cfg.full_table_name,
                    )
                    result["tables_skipped"] += 1
                    continue

                # 显示表信息和配置的列
                logger.info(
                    "[%d/%d] 加载表: %s.%s",
                    idx,
                    total_tables,
                    dim_cfg.schema,
                    dim_cfg.table,
                )
                logger.info("  - 配置的向量化列: %s", ", ".join(embedding_cols))

                # 对每个列分别加载
                for col_idx, embedding_col in enumerate(embedding_cols, 1):
                    if len(embedding_cols) > 1:
                        logger.info("  - [%d/%d] 处理列: %s", col_idx, len(embedding_cols), embedding_col)

                    table_stats = self._load_table(dim_cfg.schema, dim_cfg.table, embedding_col)
                    result["records_loaded"] += table_stats.get("loaded", 0)
                    result["records_skipped"] += table_stats.get("skipped", 0)

                # 表处理完成，计数+1
                result["tables_processed"] += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("加载失败: %s", exc)
            result["success"] = False
            result["message"] = str(exc)
        finally:
            result["execution_time"] = round(time.time() - start_ts, 2)
            summary_logger = logger.info if result.get("success") else logger.error
            summary_logger(
                "维度值加载完成: 处理 %d/%d 张表，加载 %d 条，跳过 %d 条，耗时 %.2fs",
                result["tables_processed"],
                total_tables or (result["tables_processed"] + result["tables_skipped"]),
                result["records_loaded"],
                result["records_skipped"],
                result["execution_time"],
            )

        return result

    # ---- internal helpers ----
    def _load_dim_tables(self) -> DimTablesConfig:
        dim_tables_yaml = load_yaml(self.dim_tables_path)
        return DimTablesConfig.from_yaml(dim_tables_yaml)

    def _ensure_collection(self, clean: bool = False) -> None:
        _, _, FieldSchema, CollectionSchema, _, DataType, _ = _lazy_import_milvus()

        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="table_name", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="col_name", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="col_value", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024),
            FieldSchema(name="update_ts", dtype=DataType.INT64),
        ]
        schema = CollectionSchema(fields=fields, description="Embedding index for dimension value text fields")
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

    def _load_table(self, schema: str, table: str, embedding_col: str) -> Dict[str, int]:
        table_start = time.time()
        raw_rows = self._fetch_table_data(schema, table, embedding_col)
        logger.info("  - 读取 %d 条记录", len(raw_rows))

        cleaned: List[Dict[str, Any]] = []
        skipped = 0
        seen_values = set()

        for row in raw_rows:
            value = None
            if isinstance(row, dict):
                value = row.get("col_value") or row.get(embedding_col)
            elif isinstance(row, (list, tuple)) and row:
                value = row[0]

            if value is None:
                skipped += 1
                continue

            text = str(value).strip()
            if self.options.skip_empty_values and not text:
                skipped += 1
                continue

            if self.options.truncate_long_text and len(text) > self.options.max_text_length:
                text = text[: self.options.max_text_length]

            if text in seen_values:
                skipped += 1
                continue
            seen_values.add(text)

            cleaned.append(
                {
                    "table_name": f"{schema}.{table}",
                    "col_name": embedding_col,
                    "col_value": text,
                }
            )

            if self.options.max_records_per_table and len(cleaned) >= self.options.max_records_per_table:
                break

        logger.info("  - 清洗后可用: %d 条，跳过 %d 条", len(cleaned), skipped)
        if not cleaned:
            logger.info("  - 无可用记录，跳过向量化与插入 (耗时 %.2fs)", time.time() - table_start)
            return {"loaded": 0, "skipped": skipped}

        batch_result = self._batch_embed_and_insert(cleaned)
        logger.info("  - 向量化完成 (batch_size=%d)", self.options.batch_size)
        total_skipped = skipped + batch_result.get("skipped", 0)
        logger.info(
            "  - 插入 Milvus 成功: %d 条，跳过 %d 条",
            batch_result.get("loaded", 0),
            total_skipped,
        )
        logger.info("  - 表加载耗时: %.2fs", time.time() - table_start)
        return {
            "loaded": batch_result.get("loaded", 0),
            "skipped": total_skipped,
        }

    def _fetch_table_data(self, schema: str, table: str, column: str) -> List[Dict[str, Any]]:
        """从 PostgreSQL 获取维表数据。"""

        assert self._pg_manager is not None
        limit_clause = sql.SQL(" LIMIT %s") if self.options.max_records_per_table else sql.SQL("")

        query = sql.SQL(
            "SELECT DISTINCT CAST({col} AS TEXT) AS col_value "
            "FROM {schema}.{table} "
            "WHERE {col} IS NOT NULL AND LENGTH(BTRIM(CAST({col} AS TEXT))) > 0"
        ).format(
            col=sql.Identifier(column),
            schema=sql.Identifier(schema),
            table=sql.Identifier(table),
        ) + limit_clause

        params: Tuple[Any, ...] | List[Any] = []
        if self.options.max_records_per_table:
            params = [self.options.max_records_per_table]

        with self._pg_manager.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or None)
                rows = cur.fetchall()

        return rows

    def _batch_embed_and_insert(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        if not records:
            return {"loaded": 0, "skipped": 0}

        assert self._embedding_service is not None
        assert self._milvus_client is not None

        loaded_total = 0
        skipped_total = 0

        for batch in self._iter_batches(records, self.options.batch_size):
            texts = [r["col_value"] for r in batch]
            embeddings = None
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    embeddings = self._embedding_service.get_embeddings(texts)
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt < max_retries:
                        logger.warning(
                            "  - 向量化失败（尝试 %d/%d），重试中: %s",
                            attempt + 1,
                            max_retries + 1,
                            exc,
                        )
                    else:
                        logger.error(
                            "  - 向量化失败（已重试 %d 次），跳过该批次 %d 条记录: %s",
                            max_retries,
                            len(batch),
                            exc,
                        )
                        skipped_total += len(batch)
            if embeddings is None:
                continue

            enriched: List[Dict[str, Any]] = []
            ts = int(time.time())
            for rec in batch:
                vec = embeddings.get(rec["col_value"])
                if vec is None:
                    skipped_total += 1
                    continue

                enriched.append(
                    {
                        **rec,
                        "embedding": vec.tolist() if hasattr(vec, "tolist") else vec,
                        "update_ts": ts,
                    }
                )

            loaded_total += self._milvus_client.insert_batch(self.COLLECTION_NAME, enriched)

        return {"loaded": loaded_total, "skipped": skipped_total}

    @staticmethod
    def _iter_batches(items: List[Dict[str, Any]], batch_size: int) -> Iterable[List[Dict[str, Any]]]:
        for i in range(0, len(items), batch_size):
            yield items[i : i + batch_size]


__all__ = ["DimValueLoader", "ConfigurationError", "DataValidationError", "EmbeddingError"]

