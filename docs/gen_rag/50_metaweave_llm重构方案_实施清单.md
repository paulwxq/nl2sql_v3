# MetaWeave LLM 重构实施清单

## 📋 改造文件清单

### 文件 1: `.env.example`
**操作**: 更新注释，说明模型配置位置

**当前状态**: ✅ `.env.example` 模板中已无 `DASHSCOPE_MODEL`

**修改内容**:
```bash
# ------------------------------------------------------------------------------
# 通义千问（Qwen/Dashscope）API 配置
# ------------------------------------------------------------------------------
# ⚠️ 必须填写：Qwen API 密钥
# 获取地址：https://dashscope.console.aliyun.com/apiKey
DASHSCOPE_API_KEY=          # ✅ 必填：Dashscope API Key
DASHSCOPE_BASE_URI=         # 可选：自定义 API Base URI

# 🔧 注意：模型名称（qwen-plus/qwen-turbo/qwen-max）在 metadata_config.yaml 中配置
# 🔧 提醒：如果您的个人 .env 文件中还有 DASHSCOPE_MODEL，建议删除

# ------------------------------------------------------------------------------
# DeepSeek API 配置
# ------------------------------------------------------------------------------
# ⚠️ 必须填写：DeepSeek API 密钥
DEEPSEEK_API_KEY=           # ✅ 必填：DeepSeek API Key
DEEPSEEK_BASE_URI=          # 可选：默认为 https://api.deepseek.com/v1

# 🔧 注意：模型名称（deepseek-chat）在 metadata_config.yaml 中配置
```

---

### 文件 2: `configs/metaweave/metadata_config.yaml`
**操作**: 重写 `llm` 配置段 (line 134-159)

**完整配置**:
```yaml
# LLM 配置
llm:
  # 当前激活的 LLM 提供商
  active: qwen                    # 可选值: qwen | deepseek
  
  # 批量处理配置
  batch_size: 10                  # 批量处理大小
  retry_times: 3                  # 重试次数
  
  # 各 LLM 提供商配置
  providers:
    # Qwen 配置
    qwen:
      model: qwen-plus            # 模型名称：qwen-turbo, qwen-plus, qwen-max, qwen-long
      api_key: ${DASHSCOPE_API_KEY}
      api_base: ${DASHSCOPE_BASE_URI:}  # 可选，默认使用 Dashscope 默认地址
      
      # 基础参数
      temperature: 0.3
      max_tokens: 500
      timeout: 30
      
      # Qwen 特定参数（可选，空值不传递）
      extra_params:
        enable_thinking: true     # 启用思考模式（Qwen 特有）
        stream: false             # 是否流式输出
        top_p: 0.8                # Top-P 采样
    
    # DeepSeek 配置
    deepseek:
      model: deepseek-chat        # 模型名称
      api_key: ${DEEPSEEK_API_KEY}
      api_base: ${DEEPSEEK_BASE_URI:https://api.deepseek.com/v1}
      
      # 基础参数
      temperature: 0.3
      max_tokens: 500
      timeout: 30
      
      # DeepSeek 特定参数（可选，空值不传递）
      extra_params:
        top_p: 0.95
        frequency_penalty: 0.0
        presence_penalty: 0.0
```

**⚠️ 关键修改**:
- Line 150: `${DEEPSEEK_API_BASE:...}` → `${DEEPSEEK_BASE_URI:...}`
- 删除原有的 `provider` 和 `model` 字段
- 新增 `active` 和 `providers` 结构

---

### 文件 3: `src/metaweave/services/llm_service.py`
**操作**: 完全重写 `LLMService` 类

**实施步骤**:

#### Step 3.1: 修改 `__init__()` 方法

```python
def __init__(self, config: Dict[str, Any]):
    """初始化 LLM 服务
    
    Args:
        config: LLM 配置字典，支持新旧两种格式
            新格式:
                - active: 当前激活的提供商名称
                - providers: 各提供商配置字典
                - batch_size: 批量大小
                - retry_times: 重试次数
            旧格式（自动迁移）:
                - provider: "qwen-plus" | "deepseek"
                - model: 模型名称
                - api_key: API Key
                - ...
    """
    # 自动检测并迁移旧配置格式
    if "provider" in config and "providers" not in config:
        logger.warning("检测到旧版 LLM 配置格式，自动迁移到新格式")
        config = self._migrate_old_config(config)
    
    # 1. 读取激活的 LLM 配置名称
    self.provider_type = config.get("active", "qwen")
    
    # 2. 获取对应的配置段
    providers = config.get("providers", {})
    if self.provider_type not in providers:
        raise ValueError(
            f"找不到 LLM 配置: '{self.provider_type}'\n"
            f"可用配置: {list(providers.keys())}\n"
            f"请检查 metadata_config.yaml 中的 llm.active 和 llm.providers 配置"
        )
    
    provider_config = providers[self.provider_type]
    
    # 3. 提取通用参数
    self.model = provider_config.get("model")
    self.api_key = provider_config.get("api_key")
    self.api_base = provider_config.get("api_base")
    self.temperature = provider_config.get("temperature", 0.3)
    self.max_tokens = provider_config.get("max_tokens", 500)
    self.timeout = provider_config.get("timeout", 30)
    
    # ✅ 早期校验：API Key 必须存在
    if not self.api_key:
        raise ValueError(
            f"LLM API Key 未配置: {self.provider_type}\n"
            f"请在 .env 文件中设置相应的 API Key 环境变量"
        )
    
    # ✅ 早期校验：model 必须存在
    if not self.model:
        raise ValueError(
            f"LLM 模型未配置: {self.provider_type}\n"
            f"请在 metadata_config.yaml 中设置 llm.providers.{self.provider_type}.model"
        )
    
    # 4. 提取特定参数
    self.extra_params = provider_config.get("extra_params", {})
    
    # 5. 提取批量配置
    self.batch_size = config.get("batch_size", 10)
    self.retry_times = config.get("retry_times", 3)
    
    # 6. 初始化 LLM 客户端
    self.llm: BaseChatModel = self._init_llm()
    
    logger.info(f"LLM 服务已初始化: {self.provider_type} ({self.model})")
```

#### Step 3.2: 修改 `_init_llm()` 方法

```python
def _init_llm(self) -> BaseChatModel:
    """初始化 LLM 客户端（根据 provider_type 判断）"""
    if self.provider_type == "qwen":
        return self._init_qwen()
    elif self.provider_type == "deepseek":
        return self._init_deepseek()
    else:
        raise ValueError(
            f"不支持的 LLM 提供商: '{self.provider_type}'\n"
            f"当前支持: qwen, deepseek"
        )
```

#### Step 3.3: 修改 `_init_qwen()` 方法

```python
def _init_qwen(self) -> BaseChatModel:
    """初始化通义千问（qwen-plus）"""
    try:
        from langchain_community.chat_models.tongyi import ChatTongyi
        
        # 基础参数
        init_params = {
            "model": self.model,
            "dashscope_api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }
        
        # 可选：api_base
        if self.api_base:
            init_params["dashscope_api_base"] = self.api_base
        
        # ✅ 添加特定参数（过滤 None 值）
        for key, value in self.extra_params.items():
            if value is not None:
                init_params[key] = value
                logger.debug(f"Qwen 额外参数: {key}={value}")
        
        logger.info(f"初始化 Qwen LLM: {self.model}")
        logger.debug(f"Qwen 初始化参数: {init_params}")
        
        return ChatTongyi(**init_params)
    except ImportError as e:
        logger.error(f"导入 ChatTongyi 失败: {e}")
        raise
    except Exception as e:
        logger.error(f"初始化通义千问失败: {e}")
        raise
```

#### Step 3.4: 修改 `_init_deepseek()` 方法

```python
def _init_deepseek(self) -> BaseChatModel:
    """初始化 DeepSeek"""
    try:
        from langchain_openai import ChatOpenAI
        
        # 基础参数
        init_params = {
            "model": self.model,
            "openai_api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }
        
        # 可选：api_base（默认值）
        api_base = self.api_base or "https://api.deepseek.com/v1"
        init_params["openai_api_base"] = api_base
        
        # ✅ 添加特定参数（过滤 None 值）
        for key, value in self.extra_params.items():
            if value is not None:
                init_params[key] = value
                logger.debug(f"DeepSeek 额外参数: {key}={value}")
        
        logger.info(f"初始化 DeepSeek LLM: {self.model}")
        logger.debug(f"DeepSeek 初始化参数: {init_params}")
        
        return ChatOpenAI(**init_params)
    except ImportError as e:
        logger.error(f"导入 ChatOpenAI 失败: {e}")
        raise
    except Exception as e:
        logger.error(f"初始化 DeepSeek 失败: {e}")
        raise
```

#### Step 3.5: 添加 `_migrate_old_config()` 方法

```python
def _migrate_old_config(self, old_config: Dict[str, Any]) -> Dict[str, Any]:
    """将旧配置格式转换为新格式（向后兼容）
    
    Args:
        old_config: 旧配置格式
            - provider: "qwen-plus" | "deepseek" 等
            - model: 模型名称
            - api_key: API Key
            - ...
    
    Returns:
        新配置格式字典
    """
    provider = old_config.get("provider", "qwen-plus")
    
    # 根据 provider 值判断类型
    if "qwen" in provider.lower():
        provider_type = "qwen"
        default_model = "qwen-plus"
    elif "deepseek" in provider.lower():
        provider_type = "deepseek"
        default_model = "deepseek-chat"
    else:
        # 默认使用 qwen
        logger.warning(f"未知的 provider: {provider}，默认使用 qwen")
        provider_type = "qwen"
        default_model = "qwen-plus"
    
    # 构建新配置
    new_config = {
        "active": provider_type,
        "providers": {
            provider_type: {
                "model": old_config.get("model", default_model),
                "api_key": old_config.get("api_key"),
                "api_base": old_config.get("api_base"),
                "temperature": old_config.get("temperature", 0.3),
                "max_tokens": old_config.get("max_tokens", 500),
                "timeout": old_config.get("timeout", 30),
                "extra_params": {}
            }
        },
        "batch_size": old_config.get("batch_size", 10),
        "retry_times": old_config.get("retry_times", 3)
    }
    
    logger.info(f"已将旧配置格式迁移为新格式: {provider} -> {provider_type}")
    return new_config
```

---

## 🧪 验证测试清单

### 测试 1: 注释生成功能
**测试目标**: `MetadataGenerator` → `CommentGenerator` → `LLMService`

```bash
# ⚠️ 重要：必须使用 --step ddl 或 --step all 才能触发注释生成
# --step json_llm 不会经过 MetadataGenerator 或 CommentGenerator！

# 方法 1：使用 ddl 步骤（推荐，最快）
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step ddl \
    --tables public.dim_product

# 方法 2：使用 all 步骤（完整流程）
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step all \
    --tables public.dim_product

# 方法 3：使用 md 步骤（生成 Markdown）
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step md \
    --tables public.dim_product
```

**⚠️ 关键说明**：
- **入口**：`src.metaweave.cli.main`（不是 `metadata_cli`）
- **子命令**：`metadata`
- **选项**：`--tables`（复数，支持多表逗号分隔）
- **步骤选择**：
  - ✅ `--step ddl`：从数据库提取并生成注释（**推荐用于测试**）
  - ✅ `--step all`：完整流程（包含注释生成）
  - ✅ `--step md`：生成 Markdown（也会调用注释生成）
  - ❌ `--step json_llm`：使用 `LLMJsonGenerator`，**不经过** `CommentGenerator`
  - ❌ `--step json`：从 DDL 读取，**不调用** `CommentGenerator`

**验证点**:
- [ ] LLM 服务正确初始化（检查日志输出 "LLM 服务已初始化"）
- [ ] 表注释生成成功（日志显示 "生成表注释成功"）
- [ ] 列注释生成成功（日志显示 "生成字段注释成功"）
- [ ] 缓存机制正常工作（二次运行时从缓存获取）

---

### 测试 2: LLM 关系发现功能
**测试目标**: `LLMRelationshipDiscovery` → `LLMService`

```bash
# 运行 LLM 关系发现
python -m src.metaweave.cli.main metadata \
    --config configs/metaweave/metadata_config.yaml \
    --step rel_llm
```

**验证点**:
- [ ] LLM 服务正确初始化
- [ ] 关系发现调用成功
- [ ] 输出的关系 JSON 格式正确

---

### 测试 3: 配置切换测试
**测试场景**: 验证 `active` 字段切换功能

```yaml
# 修改 metadata_config.yaml
llm:
  active: deepseek  # 从 qwen 切换到 deepseek
```

**验证点**:
- [ ] 切换到 deepseek 后服务正常
- [ ] 日志显示正确的提供商和模型

---

### 测试 4: DeepSeek Base URI 默认值测试
**测试场景**: `.env` 中不配置 `DEEPSEEK_BASE_URI`

```bash
# .env 文件中删除或注释掉
# DEEPSEEK_BASE_URI=
```

**验证点**:
- [ ] `api_base` 正确回落到默认值 `https://api.deepseek.com/v1`
- [ ] DeepSeek LLM 正常工作

---

### 测试 5: 旧配置格式兼容性测试
**测试场景**: 使用旧配置格式

```yaml
# 临时使用旧格式（测试自动迁移）
llm:
  provider: qwen-plus
  model: qwen-plus
  api_key: ${DASHSCOPE_API_KEY}
  temperature: 0.3
  max_tokens: 500
  timeout: 30
```

**验证点**:
- [ ] 日志显示"检测到旧版 LLM 配置格式，自动迁移到新格式"
- [ ] 自动迁移成功
- [ ] LLM 服务正常工作

---

### 测试 6: 错误处理测试

#### 6.1 缺少 API Key
```bash
# .env 中注释掉 API Key
# DASHSCOPE_API_KEY=
```

**预期结果**:
```
ValueError: LLM API Key 未配置: qwen
请在 .env 文件中设置相应的 API Key 环境变量
```

#### 6.2 配置不存在的提供商
```yaml
llm:
  active: unknown_provider
```

**预期结果**:
```
ValueError: 找不到 LLM 配置: 'unknown_provider'
可用配置: ['qwen', 'deepseek']
请检查 metadata_config.yaml 中的 llm.active 和 llm.providers 配置
```

#### 6.3 缺少模型配置
```yaml
providers:
  qwen:
    # model: qwen-plus  # 注释掉
    api_key: ${DASHSCOPE_API_KEY}
```

**预期结果**:
```
ValueError: LLM 模型未配置: qwen
请在 metadata_config.yaml 中设置 llm.providers.qwen.model
```

---

## 📝 实施注意事项

### 1. 分步提交
建议分 3 个 commit 提交：

```bash
# Commit 1: 更新配置文件
git add .env.example configs/metaweave/metadata_config.yaml
git commit -m "refactor(metaweave): update LLM config structure to active+providers"

# Commit 2: 重构 LLMService
git add src/metaweave/services/llm_service.py
git commit -m "refactor(metaweave): refactor LLMService to support multiple providers"

# Commit 3: 更新文档
git add docs/gen_rag/50_metaweave_llm重构方案*.md
git commit -m "docs(metaweave): add LLM refactoring design and implementation guide"
```

### 2. 回滚方案
如果出现问题，保留旧配置格式作为备份：

```bash
# 备份当前配置
cp configs/metaweave/metadata_config.yaml configs/metaweave/metadata_config.yaml.bak

# 如需回滚
git revert <commit-hash>
```

### 3. 日志级别
建议在测试期间临时调整日志级别：

```yaml
# metadata_config.yaml
logging:
  level: DEBUG  # 改为 DEBUG 查看详细日志
```

---

## ✅ 实施完成标志

- [ ] 所有 3 个文件修改完成
- [ ] 通过所有 6 项测试
- [ ] 日志输出正确
- [ ] 无 linter 错误
- [ ] 文档更新完成
- [ ] 代码已提交

---

**文档版本**: v1.3  
**创建日期**: 2025-12-05  
**最后更新**: 2025-12-05  
**关联文档**: `50_metaweave_llm重构方案.md`

**版本历史**：
- **v1.3** (2025-12-05):
  - 🔴 **关键修正**：测试 1 的步骤选择错误
    - `--step json_llm` **不调用** `CommentGenerator`（使用独立的 `LLMJsonGenerator`）
    - 修正为 `--step ddl`/`all`/`md`（才会调用 `CommentGenerator`）
  - ✅ 添加步骤选择详细说明和对比表
  - ✅ 添加日志验证点

- **v1.2** (2025-12-05):
  - ✅ 修正文件 1 的操作说明（`.env.example` 实际已无 `DASHSCOPE_MODEL`）
  - ✅ 修正测试 1、2 的 CLI 命令格式
  - ✅ 修正模块路径：`metadata_cli` → `main`
  - ✅ 修正选项名：`--table` → `--tables`
  - ✅ 添加 CLI 使用说明

- **v1.0** (2025-12-05): 初始版本

**相关文档**：
- 📖 设计方案：`50_metaweave_llm重构方案.md`
- 🔍 勘误表：`50_metaweave_llm重构方案_勘误表.md` (包含详细的步骤对比表)

