"""Qwen Embedding 客户端 - 文本向量化服务"""

import time
from typing import List, Optional, Union

import dashscope
from dashscope import TextEmbedding

from src.services.config_loader import get_config


class EmbeddingClient:
    """Qwen Embedding 客户端"""

    def __init__(self, config: Optional[dict] = None):
        """
        初始化 Embedding 客户端

        Args:
            config: Embedding 配置，如果为 None 则从全局配置加载
        """
        if config is None:
            main_config = get_config()
            config = main_config["embedding"]

        self.config = config

        # 设置 API Key
        dashscope.api_key = self.config["api_key"]

        # 模型配置
        self.model = self.config.get("model", "text-embedding-v3")
        self.dimensions = self.config.get("dimensions", 1024)
        self.timeout = self.config.get("timeout", 30)
        self.max_retries = self.config.get("max_retries", 3)
        self.batch_size = self.config.get("batch_size", 20)

        print(f"✅ Embedding 客户端已初始化: model={self.model}, dimensions={self.dimensions}")

    def embed_query(self, text: str) -> List[float]:
        """
        对单个文本进行向量化

        Args:
            text: 要向量化的文本

        Returns:
            向量（浮点数列表）

        Raises:
            Exception: 向量化失败
        """
        if not text or not text.strip():
            raise ValueError("文本不能为空")

        embeddings = self.embed_documents([text])
        return embeddings[0]

    def embed_documents(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
    ) -> List[List[float]]:
        """
        对多个文本进行批量向量化

        Args:
            texts: 文本列表
            batch_size: 批处理大小，如果为 None 则使用配置中的值

        Returns:
            向量列表

        Raises:
            Exception: 向量化失败
        """
        if not texts:
            return []

        if batch_size is None:
            batch_size = self.batch_size

        all_embeddings = []

        # 分批处理
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = self._embed_batch(batch_texts)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        对一批文本进行向量化（带重试）

        Args:
            texts: 文本列表

        Returns:
            向量列表

        Raises:
            Exception: 向量化失败
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                # 调用 Dashscope API
                response = TextEmbedding.call(
                    model=self.model,
                    input=texts,
                    dimension=self.dimensions,
                )

                # 检查响应
                if response.status_code == 200:
                    embeddings = []
                    for item in response.output["embeddings"]:
                        embeddings.append(item["embedding"])
                    return embeddings
                else:
                    raise Exception(
                        f"Embedding API 返回错误: "
                        f"status_code={response.status_code}, "
                        f"message={response.message}"
                    )

            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    retry_delay = 2 ** attempt  # 指数退避
                    print(f"⚠️ Embedding 失败（尝试 {attempt + 1}/{self.max_retries}），{retry_delay}秒后重试: {e}")
                    time.sleep(retry_delay)
                else:
                    print(f"❌ Embedding 失败（已重试 {self.max_retries} 次）: {e}")

        raise last_exception

    def test_api(self) -> bool:
        """
        测试 Embedding API

        Returns:
            测试成功返回 True，失败返回 False
        """
        try:
            test_text = "这是一个测试文本"
            embedding = self.embed_query(test_text)

            # 验证向量维度
            if len(embedding) != self.dimensions:
                print(f"❌ 向量维度不匹配: 期望 {self.dimensions}，实际 {len(embedding)}")
                return False

            # 验证向量值
            if not all(isinstance(v, (int, float)) for v in embedding):
                print("❌ 向量包含非数值元素")
                return False

            print(f"✅ Embedding API 测试成功: 向量维度={len(embedding)}")
            return True

        except Exception as e:
            print(f"❌ Embedding API 测试失败: {e}")
            return False

    def get_embedding_info(self) -> dict:
        """
        获取 Embedding 配置信息

        Returns:
            配置信息字典
        """
        return {
            "model": self.model,
            "dimensions": self.dimensions,
            "batch_size": self.batch_size,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }


# 全局 Embedding 客户端实例（单例）
_global_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    """
    获取全局 Embedding 客户端（单例）

    Returns:
        EmbeddingClient 实例
    """
    global _global_embedding_client

    if _global_embedding_client is None:
        _global_embedding_client = EmbeddingClient()

    return _global_embedding_client
