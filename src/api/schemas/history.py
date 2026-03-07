"""历史相关的响应模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SessionInfo(BaseModel):
    """历史会话信息"""

    thread_id: str
    created_at: Optional[datetime] = None
    first_question: Optional[str] = None


class TurnInfo(BaseModel):
    """对话轮次信息"""

    question: str
    answer: str
