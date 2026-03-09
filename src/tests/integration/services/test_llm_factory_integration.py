"""LLM 工厂集成测试 — 真实 API 调用验证

测试目标：
1. DeepSeek deepseek-chat：普通对话，验证 temperature 生效、响应正常
2. DeepSeek deepseek-reasoner：思考模式，验证响应含 content（reasoning_content 为附加字段）
3. DashScope qwen_turbo：验证原有 DashScope 功能未被破坏

运行方式：
    # 全部集成测试
    uv run pytest src/tests/integration/services/test_llm_factory_integration.py -v -s

    # 只跑 DeepSeek
    uv run pytest src/tests/integration/services/test_llm_factory_integration.py -v -s -k deepseek

    # 只跑 DashScope 回归
    uv run pytest src/tests/integration/services/test_llm_factory_integration.py -v -s -k dashscope

前置条件：
    .env 中需配置 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URI 和 DASHSCOPE_API_KEY
"""

import os

import pytest
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from src.services.config_loader import ConfigLoader
from src.services.llm_factory import get_llm

# 预加载 .env
_PROJECT_ROOT = ConfigLoader._get_project_root()
load_dotenv(_PROJECT_ROOT / ".env", override=False)

_HAS_DEEPSEEK = bool(os.getenv("DEEPSEEK_API_KEY"))
_HAS_DASHSCOPE = bool(os.getenv("DASHSCOPE_API_KEY"))

pytestmark = pytest.mark.integration

_SKIP_DEEPSEEK = pytest.mark.skipif(
    not _HAS_DEEPSEEK, reason="缺少 DEEPSEEK_API_KEY，跳过 DeepSeek 集成测试"
)
_SKIP_DASHSCOPE = pytest.mark.skipif(
    not _HAS_DASHSCOPE, reason="缺少 DASHSCOPE_API_KEY，跳过 DashScope 集成测试"
)

_SIMPLE_MESSAGES = [
    SystemMessage(content="你是一个简洁的助手，回答时只输出结果，不要解释。"),
    HumanMessage(content="1+1等于几？只回答数字。"),
]


# ---------------------------------------------------------------------------
# DeepSeek deepseek-chat（普通对话模式）
# ---------------------------------------------------------------------------

@_SKIP_DEEPSEEK
def test_deepseek_chat_basic_invoke():
    """deepseek-chat 基本调用：能返回非空 content"""
    llm_meta = get_llm("deepseek_chat")
    assert llm_meta.provider == "deepseek"
    assert llm_meta.model == "deepseek-chat"

    response = llm_meta.llm.invoke(_SIMPLE_MESSAGES)
    assert response.content
    assert "2" in response.content
    print(f"\n[deepseek-chat] response.content = {response.content!r}")


@_SKIP_DEEPSEEK
def test_deepseek_chat_temperature_override():
    """deepseek-chat 支持 temperature 节点级 override"""
    llm_meta = get_llm("deepseek_chat", temperature=0)
    response = llm_meta.llm.invoke(_SIMPLE_MESSAGES)
    assert response.content
    print(f"\n[deepseek-chat temperature=0] response.content = {response.content!r}")


@_SKIP_DEEPSEEK
def test_deepseek_chat_max_tokens_override():
    """deepseek-chat max_tokens 节点级 override 不报错"""
    llm_meta = get_llm("deepseek_chat", max_tokens=128)
    response = llm_meta.llm.invoke(_SIMPLE_MESSAGES)
    assert response.content
    print(f"\n[deepseek-chat max_tokens=128] response.content = {response.content!r}")


@_SKIP_DEEPSEEK
def test_deepseek_chat_provider_meta():
    """LLMWithMeta 元信息字段正确"""
    llm_meta = get_llm("deepseek_chat")
    assert llm_meta.provider == "deepseek"
    assert llm_meta.model == "deepseek-chat"


# ---------------------------------------------------------------------------
# DeepSeek deepseek-reasoner（思考模式）
# ---------------------------------------------------------------------------

@_SKIP_DEEPSEEK
def test_deepseek_reasoner_basic_invoke():
    """deepseek-reasoner 基本调用：能返回非空 content"""
    llm_meta = get_llm("deepseek_reasoner")
    assert llm_meta.provider == "deepseek"
    assert llm_meta.model == "deepseek-reasoner"

    response = llm_meta.llm.invoke(_SIMPLE_MESSAGES)
    assert response.content
    print(f"\n[deepseek-reasoner] response.content = {response.content!r}")
    # reasoning_content 是 DeepSeek 扩展字段，ChatOpenAI 可能不解析，但不应报错
    reasoning = getattr(response, "reasoning_content", None)
    print(f"[deepseek-reasoner] reasoning_content = {str(reasoning)[:200]!r}")


@_SKIP_DEEPSEEK
def test_deepseek_reasoner_provider_meta():
    """deepseek-reasoner LLMWithMeta 元信息字段正确"""
    llm_meta = get_llm("deepseek_reasoner")
    assert llm_meta.provider == "deepseek"
    assert llm_meta.model == "deepseek-reasoner"


# ---------------------------------------------------------------------------
# DashScope 回归测试（验证原有功能未被破坏）
# ---------------------------------------------------------------------------

@_SKIP_DASHSCOPE
def test_dashscope_qwen_turbo_basic_invoke():
    """qwen_turbo 基本调用：验证 DashScope 功能未被 DeepSeek 改动破坏"""
    llm_meta = get_llm("qwen_turbo")
    assert llm_meta.provider == "dashscope"
    assert llm_meta.model == "qwen-turbo"

    response = llm_meta.llm.invoke(_SIMPLE_MESSAGES)
    assert response.content
    assert "2" in response.content
    print(f"\n[qwen_turbo] response.content = {response.content!r}")


@_SKIP_DASHSCOPE
def test_dashscope_temperature_in_model_kwargs():
    """DashScope temperature 通过 model_kwargs 传入，调用不报错"""
    llm_meta = get_llm("qwen_turbo", temperature=0)
    response = llm_meta.llm.invoke(_SIMPLE_MESSAGES)
    assert response.content
    print(f"\n[qwen_turbo temperature=0] response.content = {response.content!r}")


@_SKIP_DASHSCOPE
def test_dashscope_provider_meta():
    """DashScope LLMWithMeta 元信息字段正确"""
    llm_meta = get_llm("qwen_turbo")
    assert llm_meta.provider == "dashscope"
    assert llm_meta.model == "qwen-turbo"
