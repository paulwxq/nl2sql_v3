"""LLM 工厂模块 — 根据全局配置的 llm_profiles 创建 LLM 实例

设计参考：src/services/vector_adapter/factory.py（已有的工厂模式先例）

使用方式::

    from src.services.llm_factory import get_llm

    llm_meta = get_llm("qwen_max", temperature=0, max_tokens=2000)
    response = llm_meta.llm.invoke(prompt)
    logger.info("provider=%s, model=%s", llm_meta.provider, llm_meta.model)

参数优先级::

    节点 override  >  llm_profiles 中的 profile 默认值  >  LangChain/SDK 自身默认值

DashScope 特有参数（enable_thinking / enable_search / search_options）
仅适用于 dashscope provider，传给其他 provider 会报错。

DeepSeek 特有参数（thinking）
仅适用于 deepseek provider。deepseek-reasoner 模型不支持 temperature/top_p。
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
    "deepseek": ("langchain_openai", "ChatOpenAI"),
}

_OPENAI_COMPATIBLE = frozenset({"openai", "openrouter", "deepseek"})

_ALLOWED_OVERRIDES = frozenset({
    "temperature", "timeout", "max_tokens",
    "top_p", "enable_thinking", "enable_search",
    "search_options", "response_format", "stream",
    "thinking",
})

_DASHSCOPE_ONLY_PARAMS = frozenset({
    "enable_thinking", "enable_search", "search_options",
})

_DEEPSEEK_ONLY_PARAMS = frozenset({
    "thinking",
})

_PROFILE_RESERVED_KEYS = frozenset({"provider", "model"})


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

    Profile 中除 ``provider`` / ``model`` 外的字段作为参数默认值，
    节点传入的 ``overrides`` 优先级更高。

    Args:
        profile_name: 全局注册表中的画像名称，如 ``"qwen_max"``。
        **overrides: 节点级覆盖参数。支持的参数见 ``_ALLOWED_OVERRIDES``。

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

    # ---- profile 级参数默认值 + 节点级 override 合并 ----
    profile_defaults = {
        k: v for k, v in profile.items() if k not in _PROFILE_RESERVED_KEYS
    }
    effective_overrides = {**profile_defaults, **overrides}

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
    if provider_name in _PROVIDER_MAP:
        module_path, class_name = _PROVIDER_MAP[provider_name]
    elif provider_config.get("base_url"):
        # 未注册的 provider 若配置了 base_url，自动走 OpenAI 兼容模式
        module_path, class_name = "langchain_openai", "ChatOpenAI"
        logger.info(
            "provider '%s' 未在 _PROVIDER_MAP 中注册，"
            "检测到 base_url 配置，自动使用 OpenAI 兼容模式 (ChatOpenAI)",
            provider_name,
        )
    else:
        raise ValueError(
            f"不支持的 provider 类型: '{provider_name}'，"
            f"当前支持: {sorted(_PROVIDER_MAP.keys())}。"
            f"如需使用 OpenAI 兼容 API，请在 llm_providers 中为 "
            f"'{provider_name}' 配置 base_url"
        )

    # ---- 动态导入 LangChain 类 ----
    try:
        cls = _import_class(module_path, class_name)
    except (ImportError, AttributeError) as e:
        raise ValueError(
            f"无法导入 provider '{provider_name}' 对应的 LangChain 类 "
            f"'{module_path}.{class_name}'，请确认相关依赖包已安装: {e}"
        ) from e

    # ---- 构建参数并实例化 ----
    params = _build_params(
        provider_name, provider_config, model_name, effective_overrides
    )
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
        - 大部分参数通过 ``model_kwargs`` 传入
          （Pydantic ``extra='ignore'`` 会静默丢弃顶层未知字段）。
        - ``stream`` 映射为构造参数 ``streaming``。
        - ``timeout`` 不支持，传入即报错。
        - DashScope 特有参数（``enable_thinking`` / ``enable_search``
          / ``search_options``）仅此 provider 可用。

    ChatOpenAI (OpenAI / OpenRouter / DeepSeek 等兼容 API):
        - ``temperature`` / ``max_tokens`` / ``top_p`` 等是直接字段。
        - ``timeout`` 映射为 ``request_timeout``。
        - ``stream`` 映射为构造参数 ``streaming``。
        - DashScope 特有参数传入会报错。
        - DeepSeek 专有参数 ``thinking`` 通过 ``extra_body`` 传入
          （`model_kwargs` 会报 TypeError，必须用 `extra_body`）。
          ``deepseek-reasoner`` 模型无需此参数，思考模式已固定开启。
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

        _DS_MODEL_KWARGS_KEYS = frozenset({
            "temperature", "max_tokens", "top_p",
            "enable_thinking", "enable_search", "search_options",
            "response_format",
        })
        model_kwargs: dict[str, Any] = {
            k: overrides[k] for k in _DS_MODEL_KWARGS_KEYS if k in overrides
        }

        params: dict[str, Any] = {
            "model": model_name,
            "dashscope_api_key": provider_config["api_key"],
        }
        if "stream" in overrides:
            params["streaming"] = overrides["stream"]
        if model_kwargs:
            params["model_kwargs"] = model_kwargs

    else:
        # OpenAI 兼容路径（硬编码的 openai/openrouter/deepseek + 自动检测的 provider）
        _is_hardcoded = provider_name in _OPENAI_COMPATIBLE

        if _is_hardcoded:
            # 硬编码的 provider 拒绝 DashScope 专有参数
            ds_only = _DASHSCOPE_ONLY_PARAMS & set(overrides)
            if ds_only:
                raise ValueError(
                    f"参数 {sorted(ds_only)} 仅适用于 DashScope provider，"
                    f"当前 provider 为 '{provider_name}'"
                )

        deepseek_only = _DEEPSEEK_ONLY_PARAMS & set(overrides)
        if deepseek_only and provider_name != "deepseek":
            raise ValueError(
                f"参数 {sorted(deepseek_only)} 仅适用于 DeepSeek provider，"
                f"当前 provider 为 '{provider_name}'"
            )

        params = {
            "model": model_name,
            "api_key": provider_config["api_key"],
        }
        if "base_url" in provider_config:
            params["base_url"] = provider_config["base_url"]

        _OPENAI_DIRECT_FIELDS = ("temperature", "max_tokens", "top_p")
        for key in _OPENAI_DIRECT_FIELDS:
            if key in overrides:
                params[key] = overrides[key]

        if "timeout" in overrides:
            params["request_timeout"] = overrides["timeout"]
        if "stream" in overrides:
            params["streaming"] = overrides["stream"]
        if "response_format" in overrides:
            params["response_format"] = overrides["response_format"]

        # DeepSeek thinking 参数通过 extra_body 传入（非标准字段，不能放 model_kwargs）
        if provider_name == "deepseek" and "thinking" in overrides:
            params["extra_body"] = {"thinking": overrides["thinking"]}

        # 自动检测的 provider：DashScope 专有参数通过 extra_body 透传
        if not _is_hardcoded:
            extra = {
                k: overrides[k] for k in _DASHSCOPE_ONLY_PARAMS if k in overrides
            }
            if extra:
                params.setdefault("extra_body", {}).update(extra)

    return params


def _import_class(module_path: str, class_name: str) -> type:
    """动态导入指定模块中的类。"""
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
