# 全局 LLM 配置与工厂模式重构建议书

## 1. 重构背景与目的

在当前项目中，涉及大模型调用的配置（如模型名称、API Key、Timeout 等）直接散落在多个子图和父图的配置文件中。
例如在 `nl2sql_father_graph.yaml` 和 `sql_generation_subgraph.yaml` 的各个节点（Router, Planner, Summarizer, SQL_Generation 等）中，反复硬编码了 `api_key: ${DASHSCOPE_API_KEY}` 和 `model`。

**当前架构的痛点：**

1. **配置冗余（满天飞的 API_KEY）**：同样的鉴权和底层连接参数被重复编写 5 次，违反了 DRY（Don't Repeat Yourself）原则。
2. **缺乏灵活性（厂商强绑定）**：Python 业务代码（如 `router.py`）中直接 `from langchain_community.chat_models import ChatTongyi`，导致未来如果希望为某个复杂节点（如 Planner）单独切换到 `OpenAI` 或 `Claude` 时，必须修改底层 Python 代码才能实现。
3. **管理成本高**：缺乏全局大模型视角的管控，无法统一配置和管理所有可用的大模型资源。
4. **实现不一致**：
   - **模型字段命名混乱**：父图用 `model`，子图分别用 `llm_model` 和 `parser_model`，三种命名共存。
   - **API Key 配置与代码脱节**：父图 YAML 显式配置了 `api_key: ${DASHSCOPE_API_KEY}`（见 `nl2sql_father_graph.yaml` 的 router/planner/summarizer 段），但对应的 Python 代码（`router.py`、`planner.py`、`summarizer.py`）在读取配置时**完全忽略了 `api_key` 字段**，只读取了 `model`/`temperature`/`timeout`（其中 `temperature` 和 `timeout` 最终也被 `ChatTongyi` 的 `extra='ignore'` 静默丢弃），依赖 `ChatTongyi` 自动从环境变量获取 API Key。而子图节点（`question_parsing.py`/`sql_generation.py`）则显式传递了 `dashscope_api_key=config.get("api_key")`。两种风格并存，增加了理解和维护成本。
   - **已有 Bug（严重）**：当前 `ChatTongyi` 的 Pydantic 配置为 `extra='ignore'`，会**静默丢弃**所有非声明字段。经实际验证，`ChatTongyi` 没有 `temperature`、`max_tokens` 这两个直接字段——它们必须通过 `model_kwargs` 字典传入才能生效。但当前所有 5 个节点都以直接 kwargs 方式传入（如 `ChatTongyi(model=..., temperature=0)`），这些参数全部被静默丢弃，系统实际上一直在用 DashScope 的默认参数运行。此外，`timeout` 参数更是 `ChatTongyi` 完全不支持的概念（DashScope SDK 自行管理超时），但多个节点配置中仍存在 `timeout` 字段，属于无效配置。`sql_generation.py` 的 `timeout: 30` 配置更是连代码都没读取。
   - **可观测性代码中的硬编码**：`sql_generation.py` 的 `generate()` 方法中硬编码了 `provider = "DashScope"` 和 `model_name = self.config.get("llm_model", "qwen-plus")`，并在日志和异常信息中使用。即使替换了 LLM 构造器，这些观测性代码仍然与特定 provider 绑定。

**重构目的：**

实现**"大模型驱动器（Provider）"与"业务节点（Node）"的彻底解耦**。允许在全局统一注册和管理所有模型资源，业务节点只需通过"引用名称"来调用指定的模型，同时能在节点内保留（覆盖）特定的运行参数（如 `temperature`）。同时修复上述实现不一致和已有 Bug。

> **范围说明**：本次重构仅涉及 Chat LLM（对话模型）。Embedding 模型已在 `config.yaml` 的 `embedding` 段独立配置，由 `EmbeddingClient` 直接调用 DashScope SDK（非 LangChain 体系），不在本次重构范围内。

## 2. 重构方式（核心设计）

本次重构引入 **"Provider 注册 + LLM 画像注册表 (LLM Profiles Registry)" + "工厂模式 (Factory Pattern)"** 的三层设计。

> **设计参考**：项目中已有成熟的工厂模式先例——`src/services/vector_adapter/factory.py`，它通过 `get_config()` 读取全局配置，根据 `active` 字段动态选择 Milvus 或 PgVector 实现。本次 `LLMFactory` 的设计将参照这一范式，保持架构一致性。

### 2.1 全局配置：两层注册结构

在 `src/configs/config.yaml` 中新增两个段落：

- **`llm_providers`**：Provider 级别的连接参数（`api_key`、`base_url` 等），每个 provider 只注册一次，消除 API Key 重复。
- **`llm_profiles`**：模型画像，引用 provider 并指定具体模型名称，作为业务节点的调用入口。

**YAML Schema 示例：**

```yaml
# ---- Provider 连接参数（每个 provider 只写一次） ----
llm_providers:
  dashscope:
    api_key: ${DASHSCOPE_API_KEY}
    # base_url: ...              # dashscope 不需要

  # 未来接入时取消注释并配置对应环境变量：
  # openai:
  #   api_key: ${OPENAI_API_KEY}
  #   base_url: https://api.openai.com/v1

# ---- Chat LLM 画像注册表 ----
llm_profiles:
  qwen_turbo:
    provider: dashscope          # 引用上面的 provider 键名
    model: qwen-turbo

  qwen_plus:
    provider: dashscope
    model: qwen-plus

  qwen_max:
    provider: dashscope
    model: qwen-max
```

> **关于环境变量安全**：当前 `ConfigLoader`（`src/services/config_loader.py` 的 `_replace_env_var_in_string` 方法）在加载时会递归替换整个 YAML 中的 `${VAR}`，未设置且无默认值的变量会直接抛出 `ValueError` 导致启动失败。因此 **`llm_providers` 中只注册当前实际使用的 provider**，未启用的 provider 保持注释状态，不要以 `${OPENAI_API_KEY}` 等未设置的变量形式存在于配置中。

### 2.2 节点配置：引用画像名称

在各个模块配置（如 `nl2sql_father_graph.yaml`）中，移除 `model`/`llm_model`/`parser_model`/`api_key` 等底层声明，统一改用 `llm_profile` 字段指向全局注册表中的键名。同时保留 `temperature`、`max_tokens` 作为节点级覆盖项（override）。`timeout` 仅供支持该参数的 provider 使用（当前 DashScope 不支持，详见下方说明）。

**节点配置示例：**

```yaml
# nl2sql_father_graph.yaml
router:
  llm_profile: qwen_turbo       # 引用全局注册表
  temperature: 0                 # 节点级覆盖
  default_on_error: complex
  log_decision: true

planner:
  llm_profile: qwen_max
  temperature: 0
  # ...
```

```yaml
# sql_generation_subgraph.yaml
sql_generation:
  llm_profile: qwen_max
  temperature: 0
  max_tokens: 2000               # 节点级覆盖
  # ...

question_parsing:
  llm_profile: qwen_plus
  temperature: 0
  max_tokens: 1500
  # ...
```

> **关于 timeout**：经验证，当前使用的 `ChatTongyi` 不支持 per-request timeout 参数（DashScope SDK 自行管理超时）。因此当前所有 DashScope/Qwen 节点**不配置 `timeout`**。原有 YAML 中的 `timeout` 字段属于无效配置，本次重构一并移除。`timeout` 仍保留在工厂白名单中，仅供未来支持 timeout 的 provider（如 OpenAI 的 `request_timeout`）使用；若在 DashScope 节点下误传 `timeout`，工厂将直接报错提示不支持。

**参数归属原则：**
- **Provider 层**（`llm_providers`）：`api_key`、`base_url` 等连接/身份参数，按 provider 聚合，只写一次。
- **Profile 层**（`llm_profiles`）：`provider`（引用键）、`model`（真实模型名）。
- **节点层**（override）：当前仅允许 `temperature`、`timeout`、`max_tokens` 三个运行时参数通过白名单校验。但 **`timeout` 仅对支持该参数的 provider 有效**（如 OpenAI），DashScope 节点不应配置 `timeout`，否则工厂将报错。如需新增白名单参数（如 `top_p`），须同时修改工厂中的 `_ALLOWED_OVERRIDES` 和对应测试用例。
- **不纳入工厂**：`llm_retry`（重试策略）属于调用层逻辑，保留在节点配置中，由业务代码自行处理。

### 2.3 核心代码：LLMFactory 工厂

在 `src/services/llm_factory.py` 创建工厂模块，负责：
1. 通过 `get_config()` 单例读取全局 `llm_providers` 和 `llm_profiles` 注册表
2. 根据 `provider` 字段映射到对应的 LangChain `BaseChatModel` 实现类
3. 合并 provider 层连接参数 + profile 层模型参数 + 节点层 override 参数，实例化并返回 LLM
4. 同时返回 provider/model 元信息，供调用方用于日志和异常信息（解决可观测性硬编码问题）

**接口签名与伪代码：**

```python
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from src.services.config_loader import get_config

# provider → LangChain class 映射
_PROVIDER_MAP = {
    "dashscope": ("langchain_community.chat_models", "ChatTongyi"),
    "openai": ("langchain_openai", "ChatOpenAI"),
}


@dataclass
class LLMWithMeta:
    """LLM 实例及其元信息（用于日志/异常）"""
    llm: BaseChatModel
    provider: str    # e.g. "dashscope"
    model: str       # e.g. "qwen-max"


def get_llm(profile_name: str, **overrides: Any) -> LLMWithMeta:
    """根据画像名称创建 LLM 实例。

    Args:
        profile_name: 全局注册表中的画像名称，如 "qwen_max"
        **overrides: 节点级覆盖参数，如 temperature=0, max_tokens=2000
                     （timeout 仅限支持的 provider，DashScope 传入会报错）

    Returns:
        LLMWithMeta，包含 LLM 实例和 provider/model 元信息

    Raises:
        ValueError: 配置缺失、profile 不存在、provider 不支持等
    """
    config = get_config()

    # ---- 配置完整性校验（清晰失败，不依赖裸 KeyError） ----
    profiles = config.get("llm_profiles")
    if not profiles:
        raise ValueError(
            "全局配置缺少 llm_profiles 段，请检查 config.yaml"
        )

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

    provider_name = profile["provider"]
    model_name = profile["model"]

    providers = config.get("llm_providers")
    if not providers:
        raise ValueError(
            "全局配置缺少 llm_providers 段，请检查 config.yaml"
        )

    if provider_name not in providers:
        raise ValueError(
            f"profile '{profile_name}' 引用了不存在的 provider '{provider_name}'，"
            f"已注册的 provider: {sorted(providers.keys())}"
        )
    provider_config = providers[provider_name]

    if not provider_config.get("api_key"):
        raise ValueError(
            f"provider '{provider_name}' 缺少必需字段 'api_key' 或其值为空，请检查 config.yaml"
        )

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

    # 合并参数：provider 连接参数 + profile 模型 + 节点 override
    params = _build_params(provider_name, provider_config, model_name, overrides)
    return LLMWithMeta(
        llm=cls(**params),
        provider=provider_name,
        model=model_name,
    )


def _build_params(
    provider_name: str,
    provider_config: dict,
    model_name: str,
    overrides: dict,
) -> dict:
    """根据 provider 类型构建 LangChain 构造参数。

    不同 provider 的 LangChain 类接受不同的参数名和传参方式，
    工厂在此处完成通用字段 → provider 专属字段的转换。

    关键差异：
    - ChatTongyi: temperature/max_tokens 不是直接字段，必须通过 model_kwargs 传入；
      extra='ignore' 会静默丢弃未知的顶层 kwargs。
    - ChatOpenAI: temperature/max_tokens 是直接字段；timeout 对应 request_timeout。
    """
    # 白名单校验：节点只能覆盖运行时参数，禁止覆盖连接/身份参数
    _ALLOWED_OVERRIDES = {"temperature", "timeout", "max_tokens"}
    invalid_keys = set(overrides) - _ALLOWED_OVERRIDES
    if invalid_keys:
        raise ValueError(
            f"不允许通过 override 覆盖的 LLM 参数: {sorted(invalid_keys)}，"
            f"仅允许: {sorted(_ALLOWED_OVERRIDES)}"
        )

    # 各 provider 的参数构建规则
    if provider_name == "dashscope":
        # ChatTongyi 没有 temperature/max_tokens 顶层字段，
        # 必须通过 model_kwargs 传入，否则会被 Pydantic extra='ignore' 静默丢弃
        if "timeout" in overrides:
            raise ValueError(
                "DashScope provider 不支持 per-request timeout 参数"
                "（DashScope SDK 自行管理超时），请从节点配置中移除 timeout"
            )

        model_kwargs = {}
        if "temperature" in overrides:
            model_kwargs["temperature"] = overrides["temperature"]
        if "max_tokens" in overrides:
            model_kwargs["max_tokens"] = overrides["max_tokens"]

        params = {
            "model": model_name,
            "dashscope_api_key": provider_config["api_key"],
        }
        if model_kwargs:
            params["model_kwargs"] = model_kwargs

    elif provider_name == "openai":
        # ChatOpenAI 有原生的 temperature/max_tokens 字段，可直接传入
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
        # ChatOpenAI 的超时字段名为 request_timeout
        if "timeout" in overrides:
            params["request_timeout"] = overrides["timeout"]

    else:
        raise ValueError(f"不支持的 provider: {provider_name}")

    return params
```

**Provider 参数映射规则（关键）：**

各 LangChain 类的参数名和传参方式不同，工厂负责统一翻译：

| 通用字段 | DashScope (`ChatTongyi`) | OpenAI (`ChatOpenAI`) |
|----------|--------------------------|----------------------|
| `api_key` | `dashscope_api_key` | `api_key` |
| `base_url` | 不需要 | `base_url` |
| `model` | `model`（alias of `model_name`） | `model`（alias of `model_name`） |
| `temperature` | 必须通过 `model_kwargs` 传入 | 直接字段 |
| `max_tokens` | 必须通过 `model_kwargs` 传入 | 直接字段 |
| `timeout` | 不支持，传入即报错 | `request_timeout` |

> **重要提醒**：`ChatTongyi` 的 Pydantic 配置为 `extra='ignore'`，任何以顶层 kwargs 传入的非声明字段（如 `temperature`、`max_tokens`）都会被**静默丢弃**而不是报错。这是当前代码中参数全部失效的根因，工厂必须通过 `model_kwargs` 字典传入才能使这些参数真正生效。

> **备选方案说明**：LangChain 提供了 `langchain.chat_models.init_chat_model()` 作为 provider-agnostic 的模型初始化 API，可天然支持 provider 切换而无需自行维护映射表。但该 API 目前对 DashScope/通义千问的支持有限，因此本方案采用自建映射的方式，待 LangChain 生态完善后可考虑迁移。

## 3. 修改涉及的文件与细节清单

### 3.1 YAML 配置文件改造

1. **`src/configs/config.yaml`** (修改现有文件)
   - 在现有配置（database、neo4j、embedding、vector_database 等）基础上，新增 `llm_providers` 段和 `llm_profiles` 段。
   - 仅注册当前使用的 `dashscope` provider，未使用的 provider 以注释形式保留示例。

2. **`src/modules/nl2sql_father/config/nl2sql_father_graph.yaml`** (修改)
   - **Router**: 移除 `model`、`api_key`、`timeout`，改为 `llm_profile: qwen_turbo`，保留 `temperature`。
   - **Planner**: 移除 `model`、`api_key`、`timeout`，改为 `llm_profile: qwen_max`，保留 `temperature`。
   - **Summarizer**: 移除 `model`、`api_key`、`timeout`，改为 `llm_profile: qwen_plus`，保留 `temperature`。

3. **`src/modules/sql_generation/config/sql_generation_subgraph.yaml`** (修改)
   - **sql_generation**: 移除 `llm_model`、`api_key`、`timeout`，改为 `llm_profile: qwen_max`，保留 `temperature`、`max_tokens`。
   - **question_parsing**: 移除 `parser_model`、`api_key`、`timeout`，改为 `llm_profile: qwen_plus`，保留 `temperature`、`max_tokens`。

### 3.2 Python 核心代码改造

1. **`src/services/llm_factory.py`** (全新创建)
   - 提供 `get_llm(profile_name: str, **overrides) -> LLMWithMeta` 工厂函数。
   - 维护 `_PROVIDER_MAP` 映射表，当前支持 `dashscope`，预留 `openai` 扩展。
   - 通过 `get_config()` 单例访问全局 `llm_providers` + `llm_profiles` 配置。

2. **业务节点代码 (共 5 个文件)**

   将直接 `from langchain_community.chat_models import ChatTongyi` 并实例化的代码，统一替换为调用 `get_llm()`。

   由于 `get_llm()` 返回 `LLMWithMeta`（而非裸 `BaseChatModel`），节点中必须解构后再使用：

   ```python
   # 改造后的标准写法（所有节点统一）
   from src.services.llm_factory import get_llm

   llm_meta = get_llm(config["llm_profile"], temperature=...)
   llm = llm_meta.llm          # BaseChatModel，用于 invoke()
   # llm_meta.provider / llm_meta.model 可用于日志（见下方约束）
   ```

   **涉及文件与改造要点：**

   | 文件 | 当前写法 | 改造后 |
   |------|----------|--------|
   | `router.py` | `llm = ChatTongyi(model=..., temperature=..., timeout=...)` | `llm_meta = get_llm(config["llm_profile"], temperature=...)`<br>`llm = llm_meta.llm` |
   | `planner.py` | `llm = ChatTongyi(model=..., temperature=..., timeout=...)` | 同上 |
   | `summarizer.py` | `llm = ChatTongyi(model=..., temperature=..., timeout=...)` | 同上 |
   | `sql_generation.py` | `self.llm = ChatTongyi(model=..., dashscope_api_key=..., temperature=..., max_tokens=...)` | `llm_meta = get_llm(config["llm_profile"], temperature=..., max_tokens=...)`<br>`self.llm = llm_meta.llm`<br>`self._provider = llm_meta.provider`<br>`self._model_name = llm_meta.model` |
   | `question_parsing.py` | `self._llm = ChatTongyi(model=..., dashscope_api_key=..., temperature=..., max_tokens=..., timeout=...)` | `llm_meta = get_llm(config["llm_profile"], temperature=..., max_tokens=...)`<br>`self._llm = llm_meta.llm` |

   **顺带修复的已有严重 Bug：**
   - **参数静默丢弃**：当前所有节点以顶层 kwargs 传入的 `temperature`、`max_tokens` 被 `ChatTongyi` 的 `extra='ignore'` 静默丢弃，系统一直在用 DashScope 默认参数运行。工厂的 `_build_params` 会将这些参数正确路由到 `model_kwargs` 字典中，确保真正生效。
   - **无效 timeout 配置清理**：当前多个节点配置了 `timeout` 参数，但 `ChatTongyi` 完全不支持 per-request timeout（DashScope SDK 自行管理超时）。本次重构将这些无效配置全部移除，工厂对 DashScope provider 传入 `timeout` 时将直接报错。
   - 所有节点的 API Key 传递方式将由工厂统一处理，消除父图/子图之间的不一致。

3. **可观测性代码改造**

   > **通用约束：节点不得自行推导 `provider`/`model` 信息，一律从 `LLMWithMeta` 获取。** 这条规则适用于所有使用 LLM 的节点，而非仅限 `sql_generation.py`。如果未来 router/planner/summarizer 也需要在日志中记录模型信息，同样从 `llm_meta.provider` / `llm_meta.model` 读取，禁止硬编码或从配置中自行推导。

   当前需要立即改造的文件是 `sql_generation.py`，因为它已存在硬编码：

   ```python
   # 当前代码（sql_generation.py 的 generate() 方法开头）
   provider = "DashScope"                              # ← 硬编码 provider
   model_name = self.config.get("llm_model", "qwen-plus")  # ← 引用旧字段

   # 后续在日志 warning 和 raise RuntimeError 中使用了 provider 和 model_name
   ```

   改造方案：在 `__init__` 中从 `LLMWithMeta` 保存元信息，`generate()` 方法中引用实例属性：

   ```python
   # __init__ 中
   llm_meta = get_llm(config["llm_profile"], temperature=..., max_tokens=...)
   self.llm = llm_meta.llm
   self._provider = llm_meta.provider    # "dashscope"
   self._model_name = llm_meta.model     # "qwen-max"

   # generate() 中直接使用 self._provider / self._model_name
   ```

### 3.3 单元测试与集成测试修复

测试改造分为两部分：**现有节点/集成测试的适配** 和 **工厂模块自身的新增测试**。

#### 3.3.1 现有测试适配：Mock 目标变更

重构后节点文件将以 `from src.services.llm_factory import get_llm` 方式导入工厂函数。根据 Python Mock 的工作原理，**patch 必须打在使用方的模块命名空间**（即 `where it's looked up`），而不是定义方。否则 patch 不会生效，测试会穿透 Mock 发起真实 LLM 调用。

**涉及的测试文件完整清单（共 6 个）：**

| 测试文件 | 原 Mock 目标 | 新 Mock 目标（模块本地符号） |
|----------|-------------|-------------|
| `src/tests/unit/nl2sql_father/test_router.py` | `...nodes.router.ChatTongyi` | `src.modules.nl2sql_father.nodes.router.get_llm` |
| `src/tests/unit/nl2sql_father/test_planner.py` | `...nodes.planner.ChatTongyi` | `src.modules.nl2sql_father.nodes.planner.get_llm` |
| `src/tests/unit/nl2sql_father/test_summarizer.py` | `...nodes.summarizer.ChatTongyi` | `src.modules.nl2sql_father.nodes.summarizer.get_llm` |
| `src/tests/unit/subgraph/test_question_parsing.py` | `...nodes.question_parsing.ChatTongyi` | `src.modules.sql_generation.subgraph.nodes.question_parsing.get_llm` |
| `src/tests/integration/sql_generation_subgraph/test_subgraph.py` | `question_parsing.ChatTongyi` + `sql_generation.ChatTongyi` | 对应模块的 `.get_llm` |
| `src/tests/integration/nl2sql_father/test_nl2sql_father_integration.py` | `router.ChatTongyi` + `summarizer.ChatTongyi` | 对应模块的 `.get_llm` |

> **注意**：由于工厂返回 `LLMWithMeta` 而非裸 `BaseChatModel`，Mock 的返回值结构比以前复杂一层。以 `test_router.py` 为例：

```python
# 以前：直接 Mock ChatTongyi 类
mock_llm_class.return_value = MagicMock()
mock_llm_class.return_value.invoke.return_value = mock_response

# 改造后：Mock get_llm，返回 LLMWithMeta 结构
mock_llm_meta = MagicMock()
mock_llm_meta.llm.invoke.return_value = mock_response  # .llm 才是真正的 LLM
mock_llm_meta.provider = "dashscope"
mock_llm_meta.model = "qwen-turbo"

mock_get_llm.return_value = mock_llm_meta
```

#### 3.3.2 现有测试适配：配置 fixture 迁移

当前测试 fixture 中构造的配置字典使用旧字段名，需迁移到 `llm_profile`：

| 测试文件 | 当前 fixture 中的旧字段 | 迁移为 |
|----------|------------------------|--------|
| `test_router.py` 的 `mock_config` fixture | `"model": "qwen-turbo"` | `"llm_profile": "qwen_turbo"` |
| `test_subgraph.py` 的 `mock_all_dependencies` fixture（question_parsing 段） | `"parser_model": "qwen-plus"`, `"api_key": "test-key"` | `"llm_profile": "qwen_plus"` |
| `test_subgraph.py` 的 `mock_all_dependencies` fixture（sql_generation 段） | `"llm_model": "qwen-plus"`, `"api_key": "test-key"` | `"llm_profile": "qwen_plus"` |
| 其他测试文件 | 类似的旧字段 | 统一迁移 |

> **说明**：上述 6 个节点/集成测试在 patch 了模块本地 `get_llm` 之后，调用链不会进入工厂内部，因此**不需要**额外处理 `get_config()` 单例缓存。单例缓存是工厂自身测试的关注点，见下节。

#### 3.3.3 新增：`llm_factory.py` 自身的单元测试

工厂模块需要新增独立的单元测试文件（如 `src/tests/unit/services/test_llm_factory.py`），覆盖以下场景：

**正常路径：**
- `get_llm()` 能正确根据 profile 名称创建对应 provider 的 LLM 实例
- `_build_params()` 能正确完成 provider 参数名转换（如 `api_key` → `dashscope_api_key`）
- DashScope provider：`temperature`/`max_tokens` 被正确路由到 `model_kwargs` 字典（而非顶层 kwargs）
- DashScope provider：传入 `timeout` override 时抛出 `ValueError`（清晰提示不支持）
- OpenAI provider：`temperature`/`max_tokens` 作为直接字段传入，`timeout` 映射为 `request_timeout`

**配置缺失/引用错误（均应抛出带清晰中文提示的 `ValueError`）：**
- `llm_profiles` 整段缺失
- `llm_providers` 整段缺失
- profile 名称不存在
- profile 缺少必需字段 `provider`
- profile 缺少必需字段 `model`
- profile 引用了不存在的 provider
- provider 缺少必需字段 `api_key`
- provider 的 `api_key` 为空字符串
- provider 类型不在 `_PROVIDER_MAP` 中
- 动态导入失败（依赖包未安装或类名错误）

**Override 白名单校验：**
- 传入 `model` 作为 override → 报错
- 传入 `api_key` 作为 override → 报错
- 传入未知字段如 `foo` 作为 override → 报错

**`get_config()` 单例缓存处理**：工厂通过 `get_config()` 单例读取全局配置。在工厂测试中，不同 test case 可能需要构造不同的 `llm_profiles` / `llm_providers`，此时需要隔离单例状态：

- **推荐方案**：在测试中 patch `src.services.llm_factory.get_config`，返回构造好的 Mock 配置对象。这样每个 test case 独立控制配置内容，不受单例缓存影响。
- 备选方案：在 fixture 的 teardown 中重置全局单例 `_global_config = None`（参考现有 `test_router.py` 中 `test_default_on_error_simple` 对 `_router_config_cache` 的重置做法）。

## 4. 实施步骤

按依赖关系从上游到下游，分 4 步执行：

1. **定义配置结构**：在 `config.yaml` 中新增 `llm_providers` 和 `llm_profiles` 段，确定 YAML Schema。
2. **开发工厂模块**：创建 `src/services/llm_factory.py`，实现 `get_llm()`、`_build_params()`、`LLMWithMeta`。同时新增 `src/tests/unit/services/test_llm_factory.py`，验证参数映射、异常处理等（此处需处理 `get_config()` 单例缓存）。
3. **改造节点配置与业务代码**：修改 2 个 YAML 配置文件 + 5 个节点 Python 文件。注意节点中必须解构 `LLMWithMeta`（`llm_meta.llm` 用于调用，`llm_meta.provider`/`llm_meta.model` 用于日志）。同步移除各节点无效的 `timeout` 配置，修复可观测性硬编码。
4. **适配现有测试**：更新 6 个测试文件的 Mock 目标（打在模块本地 `get_llm` 符号上，Mock 返回值需构造 `LLMWithMeta` 结构）、迁移配置 fixture 中的旧字段（`model`/`llm_model`/`parser_model`/`api_key` → `llm_profile`），运行全部测试确保通过。
