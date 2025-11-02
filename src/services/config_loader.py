"""配置加载器 - 加载和解析 YAML 配置文件，支持环境变量替换"""

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv


class ConfigLoader:
    """配置加载器 - 加载 YAML 配置并支持环境变量替换"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器

        Args:
            config_path: 配置文件路径，如果为 None 则使用默认路径
        """
        if config_path is None:
            # 使用默认配置路径
            project_root = self._get_project_root()
            config_path = project_root / "src" / "configs" / "config.yaml"
        else:
            config_path = Path(config_path)

        self.config_path = config_path
        self._config: Optional[Dict[str, Any]] = None

    @staticmethod
    def _get_project_root() -> Path:
        """获取项目根目录"""
        current_file = Path(__file__).resolve()
        # src/services/config_loader.py -> src -> project_root
        return current_file.parents[2]

    def load(self) -> Dict[str, Any]:
        """
        加载配置文件

        Returns:
            配置字典

        Raises:
            FileNotFoundError: 配置文件不存在
            yaml.YAMLError: YAML 解析错误
        """
        # 加载 .env 文件（如果存在）
        project_root = self._get_project_root()
        dotenv_path = project_root / ".env"
        if dotenv_path.exists():
            load_dotenv(dotenv_path)
            print(f"✅ 已加载环境变量文件: {dotenv_path}")
        else:
            print(f"⚠️  未找到 .env 文件: {dotenv_path}")
        
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 递归替换环境变量
        self._config = self._replace_env_vars(config)

        return self._config

    def _replace_env_vars(self, obj: Any) -> Any:
        """
        递归替换配置中的环境变量

        支持的格式：
        - ${VAR_NAME}: 引用环境变量，如果不存在则报错
        - ${VAR_NAME:default}: 引用环境变量，如果不存在使用默认值

        Args:
            obj: 要处理的对象（可以是字典、列表、字符串等）

        Returns:
            替换后的对象
        """
        if isinstance(obj, dict):
            return {key: self._replace_env_vars(value) for key, value in obj.items()}

        elif isinstance(obj, list):
            return [self._replace_env_vars(item) for item in obj]

        elif isinstance(obj, str):
            return self._replace_env_var_in_string(obj)

        else:
            return obj

    def _replace_env_var_in_string(self, text: str) -> Any:
        """
        替换字符串中的环境变量

        Args:
            text: 原始字符串

        Returns:
            替换后的值（可能是字符串、数字、布尔值等）
        """
        # 匹配 ${VAR_NAME} 或 ${VAR_NAME:default}
        pattern = r'\$\{([A-Za-z_][A-Za-z0-9_]*?)(?::([^}]*))?\}'

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            default_value = match.group(2)  # 可能为 None

            # 从环境变量获取值
            value = os.getenv(var_name)

            if value is None:
                if default_value is not None:
                    return default_value
                else:
                    raise ValueError(
                        f"环境变量 '{var_name}' 未设置，且没有提供默认值。"
                        f"请在 .env 文件中配置或在配置文件中提供默认值。"
                    )

            return value

        result = re.sub(pattern, replacer, text)

        # 尝试转换类型
        return self._convert_type(result)

    @staticmethod
    def _convert_type(value: str) -> Any:
        """
        尝试将字符串转换为合适的类型

        Args:
            value: 字符串值

        Returns:
            转换后的值（可能是 int、float、bool 或保持 str）
        """
        # 布尔值
        if value.lower() in ("true", "yes", "on", "1"):
            return True
        if value.lower() in ("false", "no", "off", "0"):
            return False

        # 整数
        try:
            return int(value)
        except ValueError:
            pass

        # 浮点数
        try:
            return float(value)
        except ValueError:
            pass

        # 保持字符串
        return value

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        使用点号路径获取配置值

        Args:
            key_path: 配置路径，如 "database.host"
            default: 默认值

        Returns:
            配置值，如果不存在返回默认值

        Example:
            >>> config = ConfigLoader().load()
            >>> host = config.get("database.host")
            >>> pool_size = config.get("database.pool_max_size", 10)
        """
        if self._config is None:
            self.load()

        keys = key_path.split(".")
        value = self._config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def reload(self) -> Dict[str, Any]:
        """
        重新加载配置文件

        Returns:
            新的配置字典
        """
        return self.load()

    def __getitem__(self, key: str) -> Any:
        """支持字典式访问"""
        if self._config is None:
            self.load()
        return self._config[key]

    def __contains__(self, key: str) -> bool:
        """支持 in 操作符"""
        if self._config is None:
            self.load()
        return key in self._config


# 全局配置实例（单例模式）
_global_config: Optional[ConfigLoader] = None


def get_config() -> ConfigLoader:
    """
    获取全局配置实例（单例）

    Returns:
        ConfigLoader 实例
    """
    global _global_config

    if _global_config is None:
        _global_config = ConfigLoader()
        _global_config.load()

    return _global_config


def load_subgraph_config(subgraph_name: str = "sql_generation") -> Dict[str, Any]:
    """
    加载子图配置文件

    Args:
        subgraph_name: 子图名称（默认 "sql_generation"）

    Returns:
        子图配置字典
    """
    main_config = get_config()

    # 从主配置获取子图配置路径
    subgraph_config_path = main_config.get(
        f"{subgraph_name}.subgraph_config_path",
        f"src/modules/{subgraph_name}/config/{subgraph_name}_subgraph.yaml"
    )

    # 解析为绝对路径
    project_root = ConfigLoader._get_project_root()
    absolute_path = project_root / subgraph_config_path

    # 加载子图配置
    subgraph_loader = ConfigLoader(str(absolute_path))
    return subgraph_loader.load()
