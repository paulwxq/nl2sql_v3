"""LLM 工厂模块 — 根据全局配置的 llm_profiles 创建 LLM 实例

设计参考：src/services/vector_adapter/factory.py（已有的工厂模式先例）

使用方式：
    from src.services.llm_factory import get_llm

    llm_meta = get_llm("qwen_max", temperature=0, max_tokens=2000)
    response = llm_meta.llm.invoke(prompt)
    logger.info("provider=%s, model=%s", llm_meta.provider, llm_meta.model)
"""

import importlib
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel

from src.services.config_loader import get_config

logger = logging.getLogger(__name__)

_PROVIDER_MAP: dict[str, tuple[str, str]] = {
    "dashscope": ("langchain_community.chat_models", "ChatTongyi"),
    "openai": ("langchain_openai", "ChatOpenAI"),
    "openrouter": ("langchain_openai", "ChatOpenAI"),
}

_OPENAI_COMPATIBLE = frozenset({"openai", "openrouter"})

_ALLOWED_OVERRIDES = frozenset({"temperature", "timeout", "max_tokens"})


@dataclass
class LLMWithMeta:
    """LLM 实例及其元信息（用于日志 / 异常 / 可观测性）"""

    llm: BaseChatModel
    provider: str
    model: str


def extract_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """从节点配置中提取允许传给 get_llm 的 override 参数。

    自动取 ``config`` 与 ``_ALLOWED_OVERRIDES`` 的交集，
    节点无需手动罗列参数名。新增 override 只需修改 ``_ALLOWED_OVERRIDES``。
    """
    return {k: config[k] for k in _ALLOWED_OVERRIDES if k in config}


def get_llm(profile_name: str, **overrides: Any) -> LLMWithMeta:
    """根据画像名称创建 LLM 实例。

    Args:
        profile_name: 全局注册表中的画像名称，如 ``"qwen_max"``。
        **overrides: 节点级覆盖参数（``temperature``, ``max_tokens``）。
            ``timeout`` 仅限支持的 provider，DashScope 传入会报错。

    Returns:
        ``LLMWithMeta``，包含 LLM 实例和 provider/model 元信息。

    Raises:
        ValueError: 配置缺失、profile 不存在、provider 不支持等。
    """
    config = get_config()

    # ---- llm_profiles 校验 ----
    profiles = config.get("llm_profiles")
    if not profiles:
        raise ValueError("全局配置缺少 llm_profiles 段，请检查 config.yaml")

    if profile_name not in profiles:
        raise ValueError(
            f"LLM profile '{profile_name}' 不存在，"
            f"可用的 profile: {sorted(profiles.keys())}"
        )
    profile = profiles[profile_name]

    if "provider" not in profile:
        raise ValueError(
            f"profile '{profile_name}' 缺少必需字段 'provider'，请检查 config.yaml"
        )
    if "model" not in profile:
        raise ValueError(
            f"profile '{profile_name}' 缺少必需字段 'model'，请检查 config.yaml"
        )

    provider_name: str = profile["provider"]
    model_name: str = profile["model"]

    # ---- llm_providers 校验 ----
    providers = config.get("llm_providers")
    if not providers:
        raise ValueError("全局配置缺少 llm_providers 段，请检查 config.yaml")

    if provider_name not in providers:
        raise ValueError(
            f"profile '{profile_name}' 引用了不存在的 provider '{provider_name}'，"
            f"已注册的 provider: {sorted(providers.keys())}"
        )
    provider_config: dict = providers[provider_name]

    if not provider_config.get("api_key"):
        raise ValueError(
            f"provider '{provider_name}' 缺少必需字段 'api_key' 或其值为空，"
            "请检查 config.yaml 和 .env"
        )

    # ---- provider 类型校验 ----
    if provider_name not in _PROVIDER_MAP:
        raise ValueError(
            f"不支持的 provider 类型: '{provider_name}'，"
            f"当前支持: {sorted(_PROVIDER_MAP.keys())}"
        )

    # ---- 动态导入 LangChain 类 ----
    module_path, class_name = _PROVIDER_MAP[provider_name]
    try:
        cls = _import_class(module_path, class_name)
    except (ImportError, AttributeError) as e:
        raise ValueError(
            f"无法导入 provider '{provider_name}' 对应的 LangChain 类 "
            f"'{module_path}.{class_name}'，请确认相关依赖包已安装: {e}"
        ) from e

    # ---- 构建参数并实例化 ----
    params = _build_params(provider_name, provider_config, model_name, overrides)
    llm = cls(**params)

    logger.debug(
        "LLM 实例已创建: provider=%s, model=%s, profile=%s",
        provider_name,
        model_name,
        profile_name,
    )

    return LLMWithMeta(llm=llm, provider=provider_name, model=model_name)


def _build_params(
    provider_name: str,
    provider_config: dict,
    model_name: str,
    overrides: dict,
) -> dict:
    """根据 provider 类型构建 LangChain 构造参数。

    ChatTongyi (DashScope):
        - ``temperature`` / ``max_tokens`` 必须通过 ``model_kwargs`` 传入
          （Pydantic ``extra='ignore'`` 会静默丢弃顶层未知字段）。
        - ``timeout`` 不支持，传入即报错。

    ChatOpenAI (OpenAI / OpenRouter 等兼容 API):
        - ``temperature`` / ``max_tokens`` 是直接字段。
        - ``timeout`` 映射为 ``request_timeout``。
    """
    # 白名单校验
    invalid_keys = set(overrides) - _ALLOWED_OVERRIDES
    if invalid_keys:
        raise ValueError(
            f"不允许通过 override 覆盖的 LLM 参数: {sorted(invalid_keys)}，"
            f"仅允许: {sorted(_ALLOWED_OVERRIDES)}"
        )

    if provider_name == "dashscope":
        if "timeout" in overrides:
            raise ValueError(
                "DashScope provider 不支持 per-request timeout 参数"
                "（DashScope SDK 自行管理超时），请从节点配置中移除 timeout"
            )

        model_kwargs: dict[str, Any] = {}
        if "temperature" in overrides:
            model_kwargs["temperature"] = overrides["temperature"]
        if "max_tokens" in overrides:
            model_kwargs["max_tokens"] = overrides["max_tokens"]

        params: dict[str, Any] = {
            "model": model_name,
            "dashscope_api_key": provider_config["api_key"],
        }
        if model_kwargs:
            params["model_kwargs"] = model_kwargs

    elif provider_name in _OPENAI_COMPATIBLE:
        params = {
            "model": model_name,
            "api_key": provider_config["api_key"],
        }
        if "base_url" in provider_config:
            params["base_url"] = provider_config["base_url"]
        if "temperature" in overrides:
            params["temperature"] = overrides["temperature"]
        if "max_tokens" in overrides:
            params["max_tokens"] = overrides["max_tokens"]
        if "timeout" in overrides:
            params["request_timeout"] = overrides["timeout"]

    else:
        raise ValueError(f"不支持的 provider: {provider_name}")

    return params


def _import_class(module_path: str, class_name: str) -> type:
    """动态导入指定模块中的类。"""
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
