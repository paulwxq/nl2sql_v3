"""NL2SQL 查询路由"""

from typing import Dict

from fastapi import APIRouter

from src.api.schemas.common import BaseResponse
from src.api.schemas.query import QueryRequest, QueryResponseData
from src.utils.logger import get_module_logger, with_query_id

logger = get_module_logger("api")

router = APIRouter()


@router.get("/health")
def health_check() -> Dict[str, str]:
    """健康检查（例外接口，不走 BaseResponse）"""
    return {"status": "ok"}


@router.post("/query")
def submit_query(req: QueryRequest) -> BaseResponse[QueryResponseData]:
    """提交 NL2SQL 查询"""
    from src.modules.nl2sql_father.graph import run_nl2sql_query

    logger.info(f"收到查询请求: user_id={req.user_id}, thread_id={req.thread_id}, query={req.query[:50]}...")

    try:
        result = run_nl2sql_query(
            query=req.query,
            user_id=req.user_id,
            thread_id=req.thread_id,
        )

        query_id = result.get("query_id")
        qlog = with_query_id(logger, query_id) if query_id else logger
        qlog.info(
            f"查询请求完成: complexity={result.get('complexity')}, "
            f"total_time={result.get('metadata', {}).get('total_execution_time_ms', 0):.0f}ms"
        )

        return BaseResponse(
            code=200,
            message="success",
            data=QueryResponseData(**result),
            trace_id=query_id,
        )
    except Exception as e:
        logger.error(f"查询执行异常: {e}", exc_info=True)
        return BaseResponse(
            code=500,
            message=f"系统异常: {str(e)}",
            data=None,
            trace_id=None,
        )
