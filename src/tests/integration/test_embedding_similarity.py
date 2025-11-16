"""Embedding 相似度探针测试。

通过真实的向量模型计算“京东 ↔ 京东便利”和“深圳 ↔ 深圳市”的余弦相似度，
以便核对 dim_value_index 的文本相似度与向量语义相似度之间的差异。

运行方式：
    pytest -k embedding_similarity -s
"""

import math
import os
from typing import Dict, List, Tuple

import pytest
from dotenv import load_dotenv

from src.services.config_loader import ConfigLoader
from src.services.embedding.embedding_client import EmbeddingClient

# 预加载 .env，确保 DASHSCOPE_API_KEY 可用
PROJECT_ROOT = ConfigLoader._get_project_root()
load_dotenv(PROJECT_ROOT / ".env", override=False)

API_KEY_PRESENT = bool(os.getenv("DASHSCOPE_API_KEY"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not API_KEY_PRESENT,
        reason="缺少 DASHSCOPE_API_KEY，无法调用真实的向量服务",
    ),
]

# 测试用例：[(原始值, 维度库命中值)]
TEST_PAIRS: List[Tuple[str, str]] = [
    ("京东", "京东便利"),
    ("深圳", "深圳市"),
]


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if len(vec_a) != len(vec_b):
        raise ValueError("向量维度不一致")

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        raise ValueError("向量范数为 0，无法计算余弦相似度")

    return dot_product / (norm_a * norm_b)


def test_embedding_similarity_for_dim_values():
    """
    通过 EmbeddingClient 计算两组维度值的向量相似度，并将结果打印出来。
    """
    client = EmbeddingClient()

    # 按顺序去重，避免重复请求
    unique_texts: List[str] = []
    for a, b in TEST_PAIRS:
        if a not in unique_texts:
            unique_texts.append(a)
        if b not in unique_texts:
            unique_texts.append(b)

    embeddings = client.embed_documents(unique_texts)
    assert len(embeddings) == len(unique_texts), "Embedding 数量与文本数量不一致"

    embedding_map: Dict[str, List[float]] = dict(zip(unique_texts, embeddings))

    # 计算并输出相似度
    for source_text, matched_text in TEST_PAIRS:
        similarity = _cosine_similarity(
            embedding_map[source_text],
            embedding_map[matched_text],
        )
        # 结果必须落在 [-1, 1] 范围内
        assert -1.0 <= similarity <= 1.0
        print(f"{source_text} → {matched_text} | cosine_similarity={similarity:.4f}")


