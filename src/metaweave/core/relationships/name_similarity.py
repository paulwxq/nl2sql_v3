"""名称相似度服务"""

import asyncio
import logging
from collections import OrderedDict
from difflib import SequenceMatcher
from typing import Dict, Optional

import numpy as np

from src.metaweave.services.embedding_service import EmbeddingService
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.name_similarity")


class LRUCache:
    """简单 LRU 缓存，容量受限。"""

    def __init__(self, capacity: int):
        self.cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self.capacity = max(1, capacity)

    def get(self, key: str) -> Optional[np.ndarray]:
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: np.ndarray) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)


class NameSimilarityService:
    """统一名称相似度服务，支持 embedding 与字符串算法。"""

    def __init__(self, name_similarity_config: dict, embedding_config: dict):
        self.config = name_similarity_config or {}
        self.embedding_config = embedding_config or {}

        # method 缺省为 string，只有 embedding 时才创建服务
        self.method = (self.config.get("method") or "string").lower()
        cache_size = int(self.config.get("cache_size", 5000) or 5000)
        self.cache = LRUCache(cache_size)

        self.embedding_service: Optional[EmbeddingService] = None
        if self.method == "embedding":
            self.embedding_service = EmbeddingService(self.embedding_config, self.config)
            logger.info("名称相似度将使用 Embedding，缓存容量=%s", cache_size)
        else:
            logger.info("名称相似度使用字符串算法（SequenceMatcher），缓存容量=%s", cache_size)

    @staticmethod
    def _normalize(name: str) -> str:
        return (name or "").strip().lower()

    @staticmethod
    def _string_similarity(name1: str, name2: str) -> float:
        norm1, norm2 = NameSimilarityService._normalize(name1), NameSimilarityService._normalize(name2)
        if norm1 == norm2:
            return 1.0
        return SequenceMatcher(None, norm1, norm2).ratio()

    def _get_embedding(self, norm_name: str) -> np.ndarray:
        cached = self.cache.get(norm_name)
        if cached is not None:
            return cached

        if not self.embedding_service:
            raise RuntimeError("EmbeddingService 未启用但尝试获取向量")

        embedding = self.embedding_service.get_embedding(norm_name)
        self.cache.put(norm_name, embedding)
        return embedding

    def compare_pair(self, name_a: str, name_b: str) -> float:
        """比较单个字段名相似度"""
        if not self.embedding_service:
            return self._string_similarity(name_a, name_b)

        norm_a, norm_b = self._normalize(name_a), self._normalize(name_b)
        if norm_a == norm_b:
            if self.embedding_service and logger.isEnabledFor(logging.DEBUG):
                logger.debug("Embedding name similarity: '%s' vs '%s' -> 1.0000 (exact match)", norm_a, norm_b)
            return 1.0

        vec_a = self._get_embedding(norm_a)
        vec_b = self._get_embedding(norm_b)

        denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
        if denom == 0:
            return 0.0
        sim = float(np.dot(vec_a, vec_b) / denom)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Embedding name similarity: '%s' vs '%s' -> %.4f", norm_a, norm_b, sim)
        return sim

    def compare_columns(self, source_cols: list, target_cols: list) -> float:
        """多列配对平均相似度"""
        if len(source_cols) != len(target_cols):
            return 0.0

        total = 0.0
        for a, b in zip(source_cols, target_cols):
            total += self.compare_pair(a, b)
        return total / len(source_cols) if source_cols else 0.0

    # === 异步接口，复用同一缓存 ===
    async def acompare_pair(self, name_a: str, name_b: str) -> float:
        if not self.embedding_service:
            return self._string_similarity(name_a, name_b)

        norm_a, norm_b = self._normalize(name_a), self._normalize(name_b)
        if norm_a == norm_b:
            if self.embedding_service and logger.isEnabledFor(logging.DEBUG):
                logger.debug("Embedding name similarity (async): '%s' vs '%s' -> 1.0000 (exact match)", norm_a, norm_b)
            return 1.0

        vec_a, vec_b = await asyncio.gather(
            self._aget_embedding(norm_a),
            self._aget_embedding(norm_b),
        )

        denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
        if denom == 0:
            return 0.0
        sim = float(np.dot(vec_a, vec_b) / denom)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Embedding name similarity (async): '%s' vs '%s' -> %.4f", norm_a, norm_b, sim)
        return sim

    async def acompare_columns(self, source_cols: list, target_cols: list) -> float:
        if len(source_cols) != len(target_cols):
            return 0.0
        sims = await asyncio.gather(
            *[self.acompare_pair(a, b) for a, b in zip(source_cols, target_cols)]
        )
        return float(sum(sims) / len(sims)) if sims else 0.0

    async def _aget_embedding(self, norm_name: str) -> np.ndarray:
        cached = self.cache.get(norm_name)
        if cached is not None:
            return cached
        if not self.embedding_service:
            raise RuntimeError("EmbeddingService 未启用但尝试获取向量")
        embedding = await self.embedding_service.aget_embedding(norm_name)
        self.cache.put(norm_name, embedding)
        return embedding
