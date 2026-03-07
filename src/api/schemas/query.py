"""查询相关的请求/响应模型"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=1000)
    user_id: str = "guest"
    thread_id: Optional[str] = None


class QueryResponseData(BaseModel):
    """POST /query 响应数据，映射自 extract_final_result()"""

    user_query: str
    query_id: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    complexity: Optional[str] = None
    path_taken: Optional[str] = None
    summary: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    failed_step: Optional[str] = None
    sql: Optional[str] = None
    sub_queries: List[Dict[str, Any]] = []
    execution_results: List[Dict[str, Any]] = []
    dependency_graph: Optional[Dict[str, Any]] = None
    current_round: Optional[int] = None
    max_rounds: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
