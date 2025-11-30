"""加载器工厂类"""

from typing import Dict, Any

from src.metaweave.core.loaders.base import BaseLoader


class LoaderFactory:
    """加载器工厂类

    根据加载类型创建对应的加载器实例。
    """

    # 注册表：加载类型 -> 加载器类
    _loaders: Dict[str, type] = {}

    @classmethod
    def create(cls, load_type: str, config: Dict[str, Any]) -> BaseLoader:
        """创建加载器实例

        Args:
            load_type: 加载类型（"cql"/"md"/"dim"/"sql"）
            config: 配置字典

        Returns:
            BaseLoader: 加载器实例

        Raises:
            ValueError: 未知的加载类型
        """
        loader_class = cls._loaders.get(load_type)
        if not loader_class:
            raise ValueError(
                f"未知的加载类型: {load_type}，"
                f"支持的类型: {list(cls._loaders.keys())}"
            )

        return loader_class(config)

    @classmethod
    def register(cls, load_type: str, loader_class: type):
        """注册新的加载器类型（用于扩展）

        Args:
            load_type: 加载类型标识
            loader_class: 加载器类

        Example:
            >>> LoaderFactory.register("cql", CQLLoader)
        """
        cls._loaders[load_type] = loader_class

    @classmethod
    def get_supported_types(cls) -> list:
        """获取支持的加载类型列表

        Returns:
            list: 支持的加载类型
        """
        return list(cls._loaders.keys())


# 注册内置加载器
def _register_builtin_loaders():
    """注册内置的加载器类型"""
    # 延迟导入，避免循环依赖
    from src.metaweave.core.loaders.cql_loader import CQLLoader

    LoaderFactory.register("cql", CQLLoader)

    # 未来扩展
    # from src.metaweave.core.loaders.md_loader import MDLoader
    # LoaderFactory.register("md", MDLoader)
    #
    # from src.metaweave.core.loaders.dim_loader import DimLoader
    # LoaderFactory.register("dim", DimLoader)
    #
    # from src.metaweave.core.loaders.sql_loader import SQLLoader
    # LoaderFactory.register("sql", SQLLoader)


# 自动注册内置加载器
_register_builtin_loaders()
