"""缓存服务

使用 JSON 文件存储缓存数据，避免重复调用 LLM 接口。
"""

import logging
from pathlib import Path
from typing import Any, Optional, Dict
import json
from datetime import datetime

from src.metaweave.utils.file_utils import ensure_dir, load_json, save_json

logger = logging.getLogger("metaweave.cache")


class CacheService:
    """缓存服务
    
    使用 JSON 文件存储键值对数据，支持 TTL（可选）。
    """
    
    def __init__(self, cache_file: str | Path):
        """初始化缓存服务
        
        Args:
            cache_file: 缓存文件路径
        """
        self.cache_file = Path(cache_file)
        ensure_dir(self.cache_file.parent)
        
        # 加载现有缓存
        self._cache: Dict[str, Any] = {}
        self._load()
        
        logger.info(f"缓存服务已初始化: {self.cache_file}")
    
    def _load(self):
        """从文件加载缓存"""
        if self.cache_file.exists():
            data = load_json(self.cache_file)
            if data:
                self._cache = data
                logger.info(f"加载缓存: {len(self._cache)} 条记录")
        else:
            self._cache = {}
            logger.info("缓存文件不存在，创建新缓存")
    
    def _save(self):
        """保存缓存到文件"""
        try:
            save_json(self._cache, self.cache_file)
            logger.debug(f"保存缓存: {len(self._cache)} 条记录")
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取缓存值
        
        Args:
            key: 缓存键
            default: 默认值
            
        Returns:
            缓存值，如果不存在返回默认值
        """
        value = self._cache.get(key)
        if value is None:
            logger.debug(f"缓存未命中: {key}")
            return default
        
        # 检查是否是带 TTL 的缓存项
        if isinstance(value, dict) and "_cached_at" in value and "_ttl" in value:
            cached_at = datetime.fromisoformat(value["_cached_at"])
            ttl = value["_ttl"]
            
            # 检查是否过期
            elapsed = (datetime.now() - cached_at).total_seconds()
            if elapsed > ttl:
                logger.debug(f"缓存已过期: {key}")
                del self._cache[key]
                self._save()
                return default
            
            # 返回实际值（不包含元数据）
            return value.get("_value")
        
        logger.debug(f"缓存命中: {key}")
        return value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 表示永不过期
        """
        if ttl:
            # 带 TTL 的缓存项
            cached_value = {
                "_value": value,
                "_cached_at": datetime.now().isoformat(),
                "_ttl": ttl,
            }
            self._cache[key] = cached_value
        else:
            # 永久缓存
            self._cache[key] = value
        
        self._save()
        logger.debug(f"设置缓存: {key}")
    
    def has(self, key: str) -> bool:
        """检查缓存键是否存在
        
        Args:
            key: 缓存键
            
        Returns:
            是否存在
        """
        value = self.get(key)
        return value is not None
    
    def delete(self, key: str):
        """删除缓存项
        
        Args:
            key: 缓存键
        """
        if key in self._cache:
            del self._cache[key]
            self._save()
            logger.debug(f"删除缓存: {key}")
    
    def clear(self):
        """清空所有缓存"""
        self._cache = {}
        self._save()
        logger.info("清空所有缓存")
    
    def size(self) -> int:
        """获取缓存项数量
        
        Returns:
            缓存项数量
        """
        return len(self._cache)
    
    def keys(self) -> list:
        """获取所有缓存键
        
        Returns:
            缓存键列表
        """
        return list(self._cache.keys())
    
    def cleanup_expired(self):
        """清理过期的缓存项"""
        expired_keys = []
        now = datetime.now()
        
        for key, value in self._cache.items():
            if isinstance(value, dict) and "_cached_at" in value and "_ttl" in value:
                cached_at = datetime.fromisoformat(value["_cached_at"])
                ttl = value["_ttl"]
                elapsed = (now - cached_at).total_seconds()
                
                if elapsed > ttl:
                    expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            self._save()
            logger.info(f"清理过期缓存: {len(expired_keys)} 条")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        total_count = len(self._cache)
        permanent_count = 0
        ttl_count = 0
        
        for value in self._cache.values():
            if isinstance(value, dict) and "_cached_at" in value:
                ttl_count += 1
            else:
                permanent_count += 1
        
        return {
            "total": total_count,
            "permanent": permanent_count,
            "with_ttl": ttl_count,
            "cache_file": str(self.cache_file),
        }

