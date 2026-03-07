"""FastAPI 应用入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- 启动阶段 ----
    from src.api.core.logging import init_api_logging

    logger = init_api_logging()

    from src.modules.nl2sql_father.graph import get_compiled_father_graph

    get_compiled_father_graph()
    logger.info("LangGraph 父图预编译完成")
    yield
    # ---- 关闭阶段 ----
    from src.services.langgraph_persistence.chat_history_reader import (
        shutdown_read_executor,
    )
    from src.services.langgraph_persistence.chat_history_writer import (
        shutdown_write_executor,
    )
    from src.services.langgraph_persistence.postgres import close_persistence

    shutdown_read_executor()
    shutdown_write_executor()
    close_persistence()
    logger.info("资源已释放（读写线程池 + 持久化连接）")


app = FastAPI(title="NL2SQL API", version="0.1.0", lifespan=lifespan)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
from src.api.routers import history, query

app.include_router(query.router, prefix="/api/v1")
app.include_router(history.router, prefix="/api/v1")
