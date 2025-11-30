"""加载器基类定义"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class BaseLoader(ABC):
    """加载器基类

    所有具体加载器都应继承此类并实现 validate() 和 load() 方法。
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化加载器

        Args:
            config: 配置字典，包含加载器所需的所有配置项
        """
        self.config = config
        self._validate_config()

    def _validate_config(self):
        """验证配置字典的基本结构

        子类可以重写此方法来添加特定的配置验证逻辑。
        """
        if not isinstance(self.config, dict):
            raise ValueError("配置必须是字典类型")

    @abstractmethod
    def validate(self) -> bool:
        """验证配置和数据源

        在执行 load() 之前调用，检查：
        - 配置项是否完整
        - 数据源文件是否存在
        - 目标数据库是否可连接

        Returns:
            bool: 验证是否通过
        """
        pass

    @abstractmethod
    def load(self) -> Dict[str, Any]:
        """执行加载操作

        Returns:
            Dict[str, Any]: 加载结果字典，至少包含：
                - success (bool): 加载是否成功
                - message (str): 结果消息
                - 其他统计信息（如节点数、关系数等）
        """
        pass

    def execute(self) -> Dict[str, Any]:
        """执行完整的加载流程（验证 + 加载）

        Returns:
            Dict[str, Any]: 加载结果
        """
        logger.info(f"开始执行 {self.__class__.__name__} 加载流程...")

        # 验证
        if not self.validate():
            return {
                "success": False,
                "message": "验证失败",
            }

        # 加载
        result = self.load()

        if result.get("success"):
            logger.info(f"{self.__class__.__name__} 加载成功")
        else:
            logger.error(f"{self.__class__.__name__} 加载失败: {result.get('message')}")

        return result
