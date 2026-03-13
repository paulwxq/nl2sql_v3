"""历史会话路由"""

from typing import List, Optional

from fastapi import APIRouter, Query

from src.api.schemas.common import BaseResponse
from src.api.schemas.history import SessionInfo, TurnInfo
from src.utils.logger import get_module_logger
from src.services.config_loader import get_config

logger = get_module_logger("api")

router = APIRouter()


@router.get("/sessions")
def list_sessions(
    user_id: str = Query(default="guest"),
    limit: Optional[int] = Query(default=None, ge=1, le=50),
) -> BaseResponse[List[SessionInfo]]:
    """获取历史会话列表"""
    from src.services.langgraph_persistence.chat_history_reader import (
        list_recent_sessions,
    )

    try:
        # 如果没有传 limit，则从配置文件中读取 max_recent_sessions，默认值为 5
        if limit is None:
            config = get_config()
            limit = config.get("api", {}).get("max_recent_sessions", 5)

        sessions = list_recent_sessions(
            user_id=user_id,
            max_sessions=limit,
        )
        data = [SessionInfo(**s) for s in sessions]
        return BaseResponse(code=200, data=data)
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}", exc_info=True)
        return BaseResponse(code=500, message=f"获取会话列表失败: {str(e)}")


@router.get("/sessions/turns")
def get_turns(
    thread_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
) -> BaseResponse[List[TurnInfo]]:
    """恢复历史会话的对话上下文"""
    from src.services.langgraph_persistence.chat_history_reader import (
        get_recent_turns,
    )

    try:
        turns = get_recent_turns(
            thread_id=thread_id,
            history_max_turns=limit,
            max_history_content_length=10000,
        )
        data = [TurnInfo(**t) for t in turns]
        return BaseResponse(code=200, data=data)
    except Exception as e:
        logger.error(f"获取对话明细失败: {e}", exc_info=True)
        return BaseResponse(code=500, message=f"获取对话明细失败: {str(e)}")
