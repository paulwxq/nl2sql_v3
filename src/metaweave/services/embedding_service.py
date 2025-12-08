"""Embedding 服务（MetaWeave 专用）"""

import asyncio
import time
from typing import Dict, List, Optional

import numpy as np
import dashscope
from dashscope import TextEmbedding

from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("services.embedding_service")


class EmbeddingService:
    """封装 DashScope Embedding，提供同步与异步接口。"""

    def __init__(self, embedding_config: dict, name_similarity_config: Optional[dict] = None):
        self.config = embedding_config or {}
        self.name_similarity_config = name_similarity_config or {}

        self.provider = self.config.get("active")
        providers = self.config.get("providers", {})
        provider_cfg = providers.get(self.provider, {}) if self.provider else {}

        if not self.provider or not provider_cfg:
            raise ValueError("Embedding 配置缺失：active 或 providers")

        self.model = provider_cfg.get("model")
        self.api_key = provider_cfg.get("api_key")
        self.api_base = provider_cfg.get("api_base")
        self.dimensions = provider_cfg.get("dimensions")
        self.batch_size = self.config.get("batch_size", 16)
        self.max_retries = self.config.get("max_retries", 3)
        self.timeout = self.config.get("timeout", 30)
        self.async_concurrency = self.config.get("async_concurrency", self.name_similarity_config.get("async_concurrency", 10))

        if not self.model or not self.api_key:
            raise ValueError("Embedding 配置缺少 model 或 api_key")

        # 配置 dashscope
        dashscope.api_key = self.api_key
        if self.api_base:
            # dashscope SDK 支持 api_base 参数，缺省则用默认
            try:
                dashscope.base_url = self.api_base  # type: ignore[attr-defined]
            except Exception:
                pass

        self._semaphore = asyncio.Semaphore(max(1, int(self.async_concurrency)))

        logger.info(
            "EmbeddingService 初始化: provider=%s, model=%s, dimensions=%s, batch_size=%s, max_retries=%s, timeout=%s",
            self.provider,
            self.model,
            self.dimensions,
            self.batch_size,
            self.max_retries,
            self.timeout,
        )

    # === 同步接口 ===
    def get_embedding(self, text: str) -> np.ndarray:
        if not text or not text.strip():
            raise ValueError("待向量化文本不能为空")
        embeddings = self.get_embeddings([text])
        return embeddings[text]

    def get_embeddings(self, texts: List[str]) -> Dict[str, np.ndarray]:
        if not texts:
            return {}

        results: Dict[str, np.ndarray] = {}
        # 去重保持顺序
        unique_texts = list(dict.fromkeys(texts))
        for i in range(0, len(unique_texts), self.batch_size):
            batch = unique_texts[i:i + self.batch_size]
            batch_result = self._embed_batch(batch)
            results.update(batch_result)

        return results

    def _embed_batch(self, texts: List[str]) -> Dict[str, np.ndarray]:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = TextEmbedding.call(
                    model=self.model,
                    input=texts,
                    dimension=self.dimensions,
                    timeout=self.timeout,
                    api_key=self.api_key,
                )

                if response.status_code != 200:
                    raise RuntimeError(
                        f"Embedding API 返回错误: status_code={response.status_code}, message={response.message}"
                    )

                embeddings: Dict[str, np.ndarray] = {}
                for item, text in zip(response.output["embeddings"], texts):
                    embeddings[text] = np.array(item["embedding"], dtype=float)
                return embeddings
            except Exception as exc:  # noqa: PERF203
                last_error = exc
                if attempt < self.max_retries:
                    delay = 2 ** (attempt - 1)
                    logger.warning(
                        "Embedding 调用失败（第 %s/%s 次），%s 秒后重试: %s",
                        attempt,
                        self.max_retries,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                else:
                    logger.error("Embedding 调用失败（已重试 %s 次）: %s", self.max_retries, exc)

        raise last_error or RuntimeError("Embedding 调用失败，原因未知")

    # === 异步接口 ===
    async def aget_embedding(self, text: str) -> np.ndarray:
        embeddings = await self.aget_embeddings([text])
        return embeddings[text]

    async def aget_embeddings(self, texts: List[str]) -> Dict[str, np.ndarray]:
        if not texts:
            return {}

        loop = asyncio.get_running_loop()
        results: Dict[str, np.ndarray] = {}
        unique_texts = list(dict.fromkeys(texts))

        async def _task(t: str) -> None:
            async with self._semaphore:
                vec = await loop.run_in_executor(None, self.get_embedding, t)
                results[t] = vec

        await asyncio.gather(*[_task(t) for t in unique_texts])
        return results
