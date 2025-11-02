"""环境变量加载和验证模块"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def load_env(env_file: Optional[str] = None) -> None:
    """
    加载环境变量文件

    Args:
        env_file: .env 文件路径，如果为 None，则自动查找项目根目录的 .env
    """
    if env_file is None:
        # 自动查找项目根目录的 .env 文件
        current_file = Path(__file__).resolve()
        project_root = current_file.parents[2]  # src/utils/env.py -> src -> project_root
        env_file = project_root / ".env"
    else:
        env_file = Path(env_file)

    if env_file.exists():
        load_dotenv(env_file)
        print(f"✅ 已加载环境变量: {env_file}")
    else:
        print(f"⚠️ 环境变量文件不存在: {env_file}")
        print("   将使用系统环境变量和配置文件中的默认值")


def get_env(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """
    获取环境变量

    Args:
        key: 环境变量名
        default: 默认值
        required: 是否必需（如果必需且不存在，抛出异常）

    Returns:
        环境变量值，如果不存在返回默认值

    Raises:
        ValueError: 如果 required=True 且环境变量不存在
    """
    value = os.getenv(key, default)

    if required and value is None:
        raise ValueError(
            f"必需的环境变量 '{key}' 未设置。"
            f"请在 .env 文件中配置或设置系统环境变量。"
        )

    return value


def validate_required_env_vars() -> bool:
    """
    验证必需的环境变量是否已设置

    Returns:
        如果所有必需的环境变量都已设置返回 True，否则返回 False
    """
    required_vars = [
        "DB_PASSWORD",           # PostgreSQL 密码
        "NEO4J_PASSWORD",        # Neo4j 密码
        "DASHSCOPE_API_KEY",     # Qwen API 密钥
    ]

    missing_vars = []

    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        print("❌ 以下必需的环境变量未设置:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n请在 .env 文件中配置这些变量。")
        print("参考 .env.example 文件获取配置模板。")
        return False

    print("✅ 所有必需的环境变量已设置")
    return True


def get_project_root() -> Path:
    """
    获取项目根目录路径

    Returns:
        项目根目录的 Path 对象
    """
    current_file = Path(__file__).resolve()
    return current_file.parents[2]  # src/utils/env.py -> src -> project_root


# 自动加载环境变量（模块导入时执行）
load_env()
