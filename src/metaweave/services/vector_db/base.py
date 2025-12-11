"""向量数据库客户端基类。"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseVectorClient(ABC):
    """向量数据库客户端接口定义。"""

    @abstractmethod
    def connect(self) -> None:
        """建立连接。"""

    @abstractmethod
    def test_connection(self) -> bool:
        """测试连接是否正常。"""

    @abstractmethod
    def ensure_collection(self, collection_name: str, schema: Any, index_params: Dict[str, Any], clean: bool = False) -> Any:
        """确保集合存在并创建索引。"""

    @abstractmethod
    def insert_batch(self, collection_name: str, data: List[Dict[str, Any]]) -> int:
        """批量插入数据。"""

    @abstractmethod
    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """获取集合统计信息。"""

    @abstractmethod
    def close(self) -> None:
        """关闭连接。"""

