"""SafeCheckpointer - Fail-open 适配层

包装真实 checkpointer，捕获异常，失败时记录日志并返回空结果。
实现"checkpoint best-effort，不影响主流程返回"的策略。
"""

from typing import Any, Iterator, Optional, Sequence, Tuple

from langgraph.checkpoint.base import BaseCheckpointSaver

from src.utils.logger import get_module_logger

logger = get_module_logger("persistence.checkpointer")


class SafeCheckpointer(BaseCheckpointSaver):
    """Fail-open 适配层：捕获异常，失败时记录日志并返回空结果

    用法：
        real_checkpointer = get_postgres_saver("father")
        safe_checkpointer = SafeCheckpointer(real_checkpointer)
        app = graph.compile(checkpointer=safe_checkpointer)

    接口签名：
        基于 langgraph-checkpoint-postgres==3.0.2 的 PostgresSaver 验证：
        - put(config, checkpoint, metadata, new_versions) -> RunnableConfig
        - put_writes(config, writes, task_id, task_path='') -> None
        - get(config) -> Checkpoint | None
        - get_tuple(config) -> CheckpointTuple | None
        - list(config, *, filter, before, limit) -> Iterator[CheckpointTuple]
        - get_next_version(current, channel) -> str
        - config_specs: Sequence[ConfigurableFieldSpec]
        - serde: SerializerProtocol
    """

    def __init__(
        self,
        real_checkpointer: Any,
        timeout_seconds: float = 5.0,
        enabled: bool = True,
    ):
        """
        Args:
            real_checkpointer: 真实的 checkpointer（如 PostgresSaver）
            timeout_seconds: 超时时间（秒），预留，当前未实现
            enabled: 是否启用，False 时所有操作均为 no-op
        """
        self._real = real_checkpointer
        self._timeout = timeout_seconds
        self._enabled = enabled

    @property
    def config_specs(self) -> Sequence[Any]:
        """返回配置规格（LangGraph 要求的接口）"""
        if self._real is None:
            return []
        try:
            return self._real.config_specs
        except Exception:
            return []

    def put(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        """写入 checkpoint，失败时记录 warning 并跳过

        Args:
            config: RunnableConfig（包含 thread_id 等）
            checkpoint: Checkpoint 数据
            metadata: CheckpointMetadata
            new_versions: ChannelVersions

        Returns:
            写入结果配置（RunnableConfig），失败时返回原 config
        """
        if not self._enabled or self._real is None:
            return config

        try:
            return self._real.put(config, checkpoint, metadata, new_versions)
        except Exception as e:
            logger.warning(f"Checkpoint 写入失败（已跳过）: {e}")
            return config

    def put_writes(
        self,
        config: Any,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """写入增量数据，失败时记录 warning 并跳过

        Args:
            config: RunnableConfig
            writes: 写入列表
            task_id: 任务 ID
            task_path: 任务路径（默认空字符串）
        """
        if not self._enabled or self._real is None:
            return

        try:
            self._real.put_writes(config, writes, task_id, task_path)
        except Exception as e:
            logger.warning(f"Checkpoint put_writes 失败（已跳过）: {e}")

    def get(self, config: dict) -> Optional[dict]:
        """读取 checkpoint，失败时返回 None

        Args:
            config: 配置字典

        Returns:
            checkpoint 数据，或 None 如果失败
        """
        if not self._enabled or self._real is None:
            return None

        try:
            return self._real.get(config)
        except Exception as e:
            logger.warning(f"Checkpoint 读取失败（返回 None）: {e}")
            return None

    def get_tuple(self, config: dict) -> Optional[Any]:
        """读取 checkpoint tuple，失败时返回 None

        Args:
            config: 配置字典

        Returns:
            checkpoint tuple，或 None 如果失败
        """
        if not self._enabled or self._real is None:
            return None

        try:
            return self._real.get_tuple(config)
        except Exception as e:
            logger.warning(f"Checkpoint get_tuple 失败（返回 None）: {e}")
            return None

    def list(
        self,
        config: Optional[dict] = None,
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Any]:
        """列出 checkpoints，失败时返回空迭代器

        Args:
            config: 配置字典
            filter: 过滤条件
            before: 时间戳之前
            limit: 数量限制

        Yields:
            checkpoint 记录
        """
        if not self._enabled or self._real is None:
            return iter([])

        try:
            return self._real.list(config, filter=filter, before=before, limit=limit)
        except Exception as e:
            logger.warning(f"Checkpoint list 失败（返回空）: {e}")
            return iter([])

    def get_next_version(self, current: Optional[str], channel: Any) -> str:
        """获取下一个版本号（LangGraph 要求的接口）

        Args:
            current: 当前版本（str 或 None）
            channel: 通道信息

        Returns:
            下一个版本号（str）
        """
        if self._real is None:
            return "1"
        try:
            return self._real.get_next_version(current, channel)
        except Exception as e:
            logger.warning(f"get_next_version 失败: {e}")
            return "1"

    @property
    def serde(self) -> Any:
        """返回序列化器（LangGraph 要求的接口）"""
        if self._real is None:
            return None
        try:
            return self._real.serde
        except Exception:
            return None

    def setup(self) -> None:
        """初始化表结构（透传到真实 checkpointer）"""
        if self._real is not None and hasattr(self._real, "setup"):
            self._real.setup()

    def delete_thread(self, thread_id: str) -> None:
        """删除线程的所有 checkpoint（透传）"""
        if self._real is not None and hasattr(self._real, "delete_thread"):
            try:
                self._real.delete_thread(thread_id)
            except Exception as e:
                logger.warning(f"delete_thread 失败: {e}")

    def __enter__(self):
        """上下文管理器入口"""
        if self._real is not None and hasattr(self._real, "__enter__"):
            self._real.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if self._real is not None and hasattr(self._real, "__exit__"):
            self._real.__exit__(exc_type, exc_val, exc_tb)
        return False

