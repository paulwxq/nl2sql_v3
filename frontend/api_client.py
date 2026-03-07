"""封装对 FastAPI 的 requests 调用"""

import os
from typing import Optional

import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8008/api/v1")
DEFAULT_TIMEOUT = 120


class NL2SQLApiClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url

    def _unwrap(self, resp: requests.Response) -> dict | list | None:
        """统一解包 BaseResponse，返回 data 字段"""
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 200:
            raise RuntimeError(f"API 业务错误: {body.get('message')}")
        return body.get("data")

    def health_check(self) -> bool:
        """检查后端是否可用"""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def submit_query(
        self,
        query: str,
        user_id: str = "guest",
        thread_id: Optional[str] = None,
    ) -> dict:
        """提交 NL2SQL 查询，返回解包后的业务数据"""
        payload = {"query": query, "user_id": user_id}
        if thread_id:
            payload["thread_id"] = thread_id
        resp = requests.post(
            f"{self.base_url}/query",
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )
        return self._unwrap(resp)

    def list_sessions(self, user_id: str = "guest", limit: int = None) -> list:
        """获取历史会话列表"""
        params = {"user_id": user_id}
        if limit is not None:
            params["limit"] = limit
            
        resp = requests.get(
            f"{self.base_url}/sessions",
            params=params,
            timeout=10,
        )
        return self._unwrap(resp)

    def get_turns(self, thread_id: str, limit: int = 50) -> list:
        """获取会话对话明细"""
        resp = requests.get(
            f"{self.base_url}/sessions/turns",
            params={"thread_id": thread_id, "limit": limit},
            timeout=10,
        )
        return self._unwrap(resp)
