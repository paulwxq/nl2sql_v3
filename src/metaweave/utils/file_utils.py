"""文件操作工具函数"""

import json
import logging
from pathlib import Path
from typing import Any, Dict
import yaml

logger = logging.getLogger("metaweave.file_utils")


def ensure_dir(directory: str | Path) -> Path:
    """确保目录存在，如果不存在则创建
    
    Args:
        directory: 目录路径
        
    Returns:
        目录的 Path 对象
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"创建目录: {dir_path}")
    return dir_path


def save_json(data: Any, file_path: str | Path, indent: int = 2) -> bool:
    """保存数据为 JSON 文件
    
    Args:
        data: 要保存的数据
        file_path: 文件路径
        indent: 缩进空格数
        
    Returns:
        是否保存成功
    """
    try:
        file_path = Path(file_path)
        ensure_dir(file_path.parent)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        
        logger.debug(f"保存 JSON 文件: {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存 JSON 文件失败 ({file_path}): {e}")
        return False


def load_json(file_path: str | Path) -> Any:
    """加载 JSON 文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        加载的数据，如果失败返回 None
    """
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            logger.warning(f"JSON 文件不存在: {file_path}")
            return None
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        logger.debug(f"加载 JSON 文件: {file_path}")
        return data
    except Exception as e:
        logger.error(f"加载 JSON 文件失败 ({file_path}): {e}")
        return None


def save_text(text: str, file_path: str | Path) -> bool:
    """保存文本到文件
    
    Args:
        text: 文本内容
        file_path: 文件路径
        
    Returns:
        是否保存成功
    """
    try:
        file_path = Path(file_path)
        ensure_dir(file_path.parent)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)
        
        logger.debug(f"保存文本文件: {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存文本文件失败 ({file_path}): {e}")
        return False


def load_text(file_path: str | Path) -> str:
    """加载文本文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        文本内容，如果失败返回空字符串
    """
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            logger.warning(f"文本文件不存在: {file_path}")
            return ""
        
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        
        logger.debug(f"加载文本文件: {file_path}")
        return text
    except Exception as e:
        logger.error(f"加载文本文件失败 ({file_path}): {e}")
        return ""


def load_yaml(file_path: str | Path) -> Dict[str, Any]:
    """加载 YAML 配置文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        配置字典，如果失败返回空字典
    """
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"YAML 文件不存在: {file_path}")
            return {}
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        logger.debug(f"加载 YAML 文件: {file_path}")
        return data if data else {}
    except Exception as e:
        logger.error(f"加载 YAML 文件失败 ({file_path}): {e}")
        return {}


def save_yaml(data: Dict[str, Any], file_path: str | Path) -> bool:
    """保存数据为 YAML 文件
    
    Args:
        data: 要保存的数据
        file_path: 文件路径
        
    Returns:
        是否保存成功
    """
    try:
        file_path = Path(file_path)
        ensure_dir(file_path.parent)
        
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        
        logger.debug(f"保存 YAML 文件: {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存 YAML 文件失败 ({file_path}): {e}")
        return False


def get_project_root() -> Path:
    """获取项目根目录
    
    Returns:
        项目根目录的 Path 对象
    """
    # 从当前文件向上查找，直到找到包含 pyproject.toml 的目录
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    
    # 如果找不到，返回当前文件的上三级目录（src/metaweave/utils -> project_root）
    return current.parents[3]

