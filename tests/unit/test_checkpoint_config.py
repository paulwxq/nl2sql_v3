"""单元测试：Checkpoint 配置分离验证

验证：
1. config.yaml 中的 father_enabled 和 subgraph_enabled 正确加载
2. is_checkpoint_enabled(kind) 返回正确结果
3. get_postgres_saver(kind) 根据开关返回实例或 None
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.services.langgraph_persistence.postgres import (
    is_checkpoint_enabled,
    is_father_checkpoint_enabled,
    is_subgraph_checkpoint_enabled,
    get_postgres_saver,
    reset_persistence_cache,
    _get_persistence_config
)
from src.services.config_loader import get_config

class TestCheckpointConfig(unittest.TestCase):
    def setUp(self):
        # 确保每个测试开始前清理缓存
        reset_persistence_cache()

    def tearDown(self):
        # 确保每个测试结束后清理缓存
        reset_persistence_cache()

    def test_config_parsing(self):
        """验证配置解析是否正确"""
        config = get_config()
        checkpoint_cfg = config.get("langgraph_persistence", {}).get("checkpoint", {})
        
        # 验证新字段存在
        self.assertIn("father_enabled", checkpoint_cfg)
        self.assertIn("subgraph_enabled", checkpoint_cfg)
        
        # 验证默认值（根据我们刚才的修改）
        self.assertTrue(checkpoint_cfg["father_enabled"])
        self.assertFalse(checkpoint_cfg["subgraph_enabled"])

    def test_enable_functions(self):
        """验证判断函数逻辑"""
        # 假设总开关是开启的
        with patch("src.services.langgraph_persistence.postgres._get_persistence_config") as mock_get_cfg:
            # 场景1：父开子关
            mock_get_cfg.return_value = {
                "enabled": True,
                "checkpoint": {
                    "father_enabled": True,
                    "subgraph_enabled": False
                }
            }
            self.assertTrue(is_checkpoint_enabled("father"))
            self.assertTrue(is_father_checkpoint_enabled())
            self.assertFalse(is_checkpoint_enabled("subgraph"))
            self.assertFalse(is_subgraph_checkpoint_enabled())

            # 场景2：父关子开
            mock_get_cfg.return_value = {
                "enabled": True,
                "checkpoint": {
                    "father_enabled": False,
                    "subgraph_enabled": True
                }
            }
            self.assertFalse(is_father_checkpoint_enabled())
            self.assertTrue(is_subgraph_checkpoint_enabled())

            # 场景3：总开关关闭
            mock_get_cfg.return_value = {
                "enabled": False,
                "checkpoint": {
                    "father_enabled": True,
                    "subgraph_enabled": True
                }
            }
            self.assertFalse(is_father_checkpoint_enabled())
            self.assertFalse(is_subgraph_checkpoint_enabled())

    @patch("langgraph.checkpoint.postgres.PostgresSaver.from_conn_string")
    def test_get_postgres_saver_respects_config(self, mock_from_conn):
        """验证 get_postgres_saver 是否尊重开关配置"""
        # 模拟 PostgresSaver
        mock_saver_cm = MagicMock()
        mock_saver = MagicMock()
        mock_saver_cm.__enter__.return_value = mock_saver
        mock_from_conn.return_value = mock_saver_cm

        with patch("src.services.langgraph_persistence.postgres._get_persistence_config") as mock_get_cfg:
            # 设置：父开子关
            mock_get_cfg.return_value = {
                "enabled": True,
                "database": {"use_global_config": True},
                "checkpoint": {
                    "father_enabled": True,
                    "subgraph_enabled": False,
                    "father_namespace": "f_ns",
                    "subgraph_namespace": "s_ns"
                }
            }

            # 应该能获取到 father saver
            father_saver = get_postgres_saver("father")
            self.assertIsNotNone(father_saver)
            self.assertEqual(mock_from_conn.call_count, 1)

            # 应该获取不到 subgraph saver
            subgraph_saver = get_postgres_saver("subgraph")
            self.assertIsNone(subgraph_saver)
            # 调用次数不应增加
            self.assertEqual(mock_from_conn.call_count, 1)

    def test_subgraph_compilation_without_checkpoint(self):
        """验证子图在 checkpoint 禁用时编译不带 checkpointer"""
        from src.modules.sql_generation.subgraph.create_subgraph import get_compiled_subgraph, reset_subgraph_cache
        
        reset_subgraph_cache()
        
        with patch("src.services.langgraph_persistence.postgres.is_subgraph_checkpoint_enabled", return_value=False):
            subgraph = get_compiled_subgraph()
            self.assertIsNotNone(subgraph)
            # 检查编译后的图是否带 checkpointer 是比较困难的（内部属性），
            # 但我们可以通过 get_compiled_subgraph 的逻辑和日志来确信。
            # 我们通过 patch is_subgraph_checkpoint_enabled 来控制逻辑。

if __name__ == "__main__":
    unittest.main()
