"""Embedding 相似度调试脚本。

用途：
    直接调用当前环境配置的 Embedding 模型，计算两组文本的余弦相似度。

运行：
    python scripts/embedding_similarity_probe.py
"""

import math
from typing import Dict, List, Tuple

from dotenv import load_dotenv

from src.services.config_loader import ConfigLoader
from src.services.embedding.embedding_client import EmbeddingClient

PROJECT_ROOT = ConfigLoader._get_project_root()
load_dotenv(PROJECT_ROOT / ".env", override=False)

PAIRS: List[Tuple[str, str]] = [
    ("京东", "京东便利"),
    ("深圳", "深圳市"),
]


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算余弦相似度。"""
    if len(vec_a) != len(vec_b):
        raise ValueError("向量维度不一致")

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        raise ValueError("向量范数为 0，无法计算相似度")

    return dot_product / (norm_a * norm_b)


def main():
    client = EmbeddingClient()

    unique_texts: List[str] = []
    for a, b in PAIRS:
        if a not in unique_texts:
            unique_texts.append(a)
        if b not in unique_texts:
            unique_texts.append(b)

    embeddings = client.embed_documents(unique_texts)
    mapping: Dict[str, List[float]] = dict(zip(unique_texts, embeddings))

    print("=== Embedding 相似度结果 ===")
    for src, dst in PAIRS:
        score = cosine_similarity(mapping[src], mapping[dst])
        print(f"{src} -> {dst}: cosine_similarity={score:.4f}")


if __name__ == "__main__":
    main()

