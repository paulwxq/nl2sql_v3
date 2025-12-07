# 52. MetaWeave Embedding 名称相似度改造方案

## 1. 背景
- 关系候选的列名相似度目前仅依赖字符串比对：`SequenceMatcher` 分别实现在 `src/metaweave/core/relationships/scorer.py:504` 和 `src/metaweave/core/relationships/candidate_generator.py:1061`，无法识别语义相近但字符串差异较大的字段。
- 项目已有全局 embedding 客户端，但 MetaWeave 模块未来可能独立交付，因此不能依赖 `src/services/embedding/embedding_client.py`；需要在 MetaWeave 内部实现可替换的 embedding 方案。
- 需求：读取 `.env` 中的模型参数，由 `configs/metaweave/metadata_config.yaml` 控制开关，支持 Embedding/字符串 两种策略，并在调用处透明切换。

## 2. 目标与范围
1. **统一的列名相似度函数**：向关系评分器与候选生成器提供一致的接口，内部根据配置选择算法。
2. **Embedding 支持**：当开关开启时，调用 MetaWeave 私有的 embedding 客户端，并使用 `numpy` 计算余弦相似度。
3. **配置粒度**：仅通过 `configs/metaweave/metadata_config.yaml` 提供所有相关配置；`.env` 只承载敏感信息。
4. **隔离性**：@metaweave 模块内部完成 embedding 客户端实现，避免依赖仓库其它子系统。

## 3. 约束与默认策略
- Embedding 服务必须单独实现，建议落在 `src/metaweave/services/embedding_service.py`，并仅暴露 MetaWeave 所需的最小接口。
- 由于列配对数量可能很大，必须缓存每个字段名的向量；使用容量受限的 LRU 缓存（参见 5.1 的 OrderedDict 实现）。
- 请求失败时需按配置（默认 3 次）进行重试；重试后仍无法连接或获取向量则直接报错退出，并在日志中明确说明“无法连接 embedding 模型”，不做字符串降级，保证结果一致性。
- 所有可调参数（开关、provider、模型、timeouts、batch_size 等）放在 `metadata_config.yaml`；敏感信息（API Key）放 `.env`，可通过 `${ENV_VAR:default}` 在 YAML 中引用。`embedding` 节保持与 `llm` 平级（顶层），不要放到 `relationships` 下面。

## 4. 配置改造方案
### 4.1 metadata_config.yaml（新增 `relationships.name_similarity` 节）
```yaml
relationships:
  sampling:
    sample_size: 1000
  weights:
    inclusion_rate: 0.55
    name_similarity: 0.20
    type_compatibility: 0.15
    jaccard_index: 0.10

  name_similarity:
    enabled: true                  # 全局开关；false 则退回 SequenceMatcher
    method: embedding              # 预留: embedding | string
    cache_size: 5000               # 可选，控制 LRU 缓存容量
    # provider 选择统一使用顶层 embedding.active（不在此处重复配置）
```
> 若 `enabled=false` 或 `method=string`，直接使用原来的 SequenceMatcher，不触发 embedding。

### 4.2 配置位置与兼容性
- 现状：`metadata_config.yaml` 中 `single_column`、`composite`、`weights`、`decision` 等是顶层节点；`LLMRelationshipDiscovery` 则读取 `config["relationships"]`。
- 统一入口：在进入候选生成/评分/决策前构造 `rel_config`，避免两条路径读取不一致；当前建议的兼容逻辑为：
  ```python
  rel_config = config.get("relationships", {}).copy()
  for key in ["single_column", "composite", "decision", "weights"]:
      if key in config and key not in rel_config:
          rel_config[key] = config[key]
  ```
  这样即便顶层尚未迁移到 `relationships`，也不会丢失 `single_column` 等必需配置。
- 目标：消除顶层/relationships 双路径导致的配置缺失，确保两条链路（pipeline 与 LLMRelationshipDiscovery）读取一致；当前仍以现有顶层结构为主，`rel_config` 只是为兼容 `LLMRelationshipDiscovery` 的读取方式。
- 注意：`embedding` 节保持顶层与 `llm` 平级，不放入 `relationships`，provider 选择统一使用顶层 `embedding.active`，`name_similarity` 不再单独声明 provider。
- 原因说明：`metadata_config.yaml` 已存在 `relationships` 节点（含 sampling/weights），而 `single_column`/`composite` 等仍在顶层；若直接用 `config.get("relationships")` 传递，下游会缺失顶层配置导致初始化失败，合并逻辑用于兼容两种读取路径并防止缺漏。

### 4.3 顶层 `embedding` 配置示例
```yaml
# Embedding 配置（与 llm 平级）
embedding:
  # 当前激活的 Embedding 提供商
  active: qwen                    # 可选值: qwen（预留扩展其他 provider）

  # 批量处理和重试配置
  batch_size: 16                  # 预留：批量请求大小
  max_retries: 3                  # API 调用失败时的最大重试次数
  timeout: 30                     # 请求超时（秒）

  # 各 Embedding 提供商配置
  providers:
    # Qwen Embedding 配置
    qwen:
      model: text-embedding-v3
      api_key: ${DASHSCOPE_API_KEY}
      api_base: ${DASHSCOPE_BASE_URI}   # 复用系统已有 DashScope 地址
      dimensions: 1024                  # 模型输出维度（用于预分配与校验）
```

### 4.4 `.env` 说明
- 不新增 `METAWEAVE_EMBED_MODEL` / `METAWEAVE_EMBED_BASE`，直接复用现有 `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URI`。
- 若未来需要自定义其他 provider，再按需增加对应的 API Key 环境变量；模型名/地址仍建议放在 YAML。

## 5. 模块设计
### 5.1 `NameSimilarityService`
- **位置**：`src/metaweave/core/relationships/name_similarity.py`（新文件）。
- **职责**：
  - 读取 `relationships.name_similarity` 配置。
  - 对外提供 `compare_columns(source_cols, target_cols)` 与 `compare_pair(name_a, name_b)`；
    `compare_columns` 负责 scorer 场景的多列配对平均，`compare_pair` 负责候选生成的单字段比较。
  - 内部根据配置决定使用 `EmbeddingService` 或 `SequenceMatcher`。
  - 维护一个容量受限的 LRU 缓存（基于 `collections.OrderedDict`），键为规范化列名 `lower().strip()`，值为向量；超过 `cache_size` 时淘汰最旧项，避免无界内存占用。
    缓存粒度以「列名」为单位，这样 `compare_columns` 和 `compare_pair` 会共享同一份向量结果（即使调用路径不同）。
    示例实现：
    ```python
    from collections import OrderedDict

    class LRUCache:
        def __init__(self, capacity: int):
            self.cache = OrderedDict()
            self.capacity = max(1, capacity)

        def get(self, key):
            if key not in self.cache:
                return None
            self.cache.move_to_end(key)
            return self.cache[key]

        def put(self, key, value):
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
    ```
  - 提供监控日志：命中缓存、API 重试、失败退出等。

### 5.2 `EmbeddingService`
- **位置**：`src/metaweave/services/embedding_service.py`（新文件）。
- **功能**：
  - 封装具体 provider（初版仅 DashScope TextEmbedding）。
  - 提供 `get_embedding(text: str) -> np.ndarray` 和批量 `get_embeddings(list[str]) -> Dict[str, np.ndarray]` 接口。
  - 负责重试、超时及 API 结构解析。DashScope 可直接复用 `dashscope.TextEmbedding.call`，但参数、日志、错误需按 MetaWeave 风格处理。
  - 允许通过 `provider` 扩展结构，预留占位符（例如 future: `openai`）。

### 5.3 与现有流程的集成
1. **管道注入**：`RelationshipDiscoveryPipeline` 在初始化时创建 `NameSimilarityService`，传入拆分后的 `name_similarity_config` 与顶层 `embedding_config`。
2. **候选生成**：`CandidateGenerator` 的构造函数需新增 `name_similarity_service` 参数（默认可为 None），由 `RelationshipDiscoveryPipeline`、`LLMRelationshipDiscovery` 等调用方显式注入；内部 `_calculate_name_similarity` 改为调用 service 的 `compare_pair`。
3. **关系评分器**：`RelationshipScorer` 也需要新增相同依赖，统一使用 service 的 `compare_columns`；这样 LLM 流程与常规 pipeline 都会复用同一份缓存与算法。
4. **日志**：在 DEBUG 级别输出 embedding 命中/重试/失败信息，便于排查开关行为。

## 6. 主要实现步骤
1. **配置解析**：更新 `metadata_config.yaml`。在 `RelationshipDiscoveryPipeline` 初始化时，按 4.2 的合并逻辑构造 `self.rel_config`（先拷贝 `config.get("relationships", {})`，再补顶层的 `single_column`/`composite`/`decision`/`weights`），取 `name_sim_config = self.rel_config.get("name_similarity", {})`，`embedding_config = config.get("embedding", {})`，并据此创建 `NameSimilarityService`。
2. **实现 `EmbeddingService`**：
   - 处理 provider 选择、API key 校验、调用 dashscope SDK。
   - 加上 numpy 依赖（项目已有），根据 `np.dot` / `np.linalg.norm` 计算余弦相似度。
   - 支持批量请求与指数退避重试，必要时拆分文本长度。
3. **实现 `NameSimilarityService`**：
   - 初始化 embedding service（如启用）。
   - 实现缓存：使用 5.1 所示的基于 `collections.OrderedDict` 的 LRU，按 `cache_size` 控制容量。
   - 对外方法在多列场景下按索引配对求平均，与当前实现保持行为一致。
   - 若列数不一致，立即返回 0.0，和旧逻辑兼容。
4. **接入 Pipeline / LLM 流程**：
   - 常规 pipeline (`pipeline.py`)：`CandidateGenerator` 和 `RelationshipScorer` 都改为依赖注入同一个 `NameSimilarityService`，复用缓存。
   - LLM 流程 (`LLMRelationshipDiscovery`)：不走 `CandidateGenerator`，只需在 `RelationshipScorer` 中注入 `NameSimilarityService`。
   - 在日志中标记当前策略（embedding 或 string）。
   - 统一配置入口：在管道/LLM 调用处按 4.2 的"合并"逻辑构造 `rel_config`（先拷贝 `config["relationships"]`，再补顶层的 `single_column`/`composite`/`decision`/`weights` 等缺失字段），然后传给候选生成/评分/决策，避免混合结构导致缺失。

   **具体代码修改**：

   **(a) 修改构造函数签名**

   `src/metaweave/core/relationships/candidate_generator.py:23`：
   ```python
   # 当前
   def __init__(self, config: dict, fk_signature_set: Set[str]):
   
   # 修改后
   def __init__(self, config: dict, fk_signature_set: Set[str],
                name_similarity_service: Optional['NameSimilarityService'] = None):
       # ... 现有代码 ...
       self.name_similarity_service = name_similarity_service
   ```

   `src/metaweave/core/relationships/scorer.py:37`：
   ```python
   # 当前
   def __init__(self, config: dict, connector: DatabaseConnector):
   
   # 修改后
   def __init__(self, config: dict, connector: DatabaseConnector,
                name_similarity_service: Optional['NameSimilarityService'] = None):
       # ... 现有代码 ...
       self.name_similarity_service = name_similarity_service
   ```

   **(b) 修改 `pipeline.py`**（约第 60-75 行，`__init__` 方法内）

   ```python
   from src.metaweave.core.relationships.name_similarity import NameSimilarityService

   # 构造并保存 rel_config（合并顶层配置）
   self.rel_config = self.config.get("relationships", {}).copy()
   for key in ["single_column", "composite", "decision", "weights"]:
       if key in self.config and key not in self.rel_config:
           self.rel_config[key] = self.config[key]

   # 获取 embedding 配置（顶层）
   self.embedding_config = self.config.get("embedding", {})

   # 创建 NameSimilarityService
   name_sim_config = self.rel_config.get("name_similarity", {})
   self.name_similarity_service = NameSimilarityService(name_sim_config, self.embedding_config)

   # 修改 scorer 创建（__init__ 中创建 scorer 的位置）
   self.scorer = RelationshipScorer(self.rel_config, self.connector, self.name_similarity_service)
   ```

   并在 `run()` 方法中修改 `CandidateGenerator` 创建（`generate_candidates` 前的创建位置）：
   ```python
   self.candidate_generator = CandidateGenerator(self.rel_config, fk_sigs, self.name_similarity_service)
   ```

   **(c) 修改 `llm_relationship_discovery.py`**（约第 100-110 行，`__init__` 方法内）

   ```python
   from src.metaweave.core.relationships.name_similarity import NameSimilarityService

   # 构造并保存 rel_config（合并顶层配置）
   self.rel_config = config.get("relationships", {}).copy()
   for key in ["single_column", "composite", "decision", "weights"]:
       if key in config and key not in self.rel_config:
           self.rel_config[key] = config[key]

   # 获取 embedding 配置
   self.embedding_config = config.get("embedding", {})

   # 创建 NameSimilarityService
   name_sim_config = self.rel_config.get("name_similarity", {})
   self.name_similarity_service = NameSimilarityService(name_sim_config, self.embedding_config)

   # 修改 scorer 创建（__init__ 中创建 scorer 的位置）
   self.scorer = RelationshipScorer(self.rel_config, connector, self.name_similarity_service)
   ```

   **(d) 修改 `_calculate_name_similarity` 调用**

`candidate_generator.py`（`_calculate_name_similarity` 方法）：
   ```python
   def _calculate_name_similarity(self, name1: str, name2: str) -> float:
       if self.name_similarity_service:
           return self.name_similarity_service.compare_pair(name1, name2)
       # Fallback: 原有逻辑
       if name1.lower() == name2.lower():
           return 1.0
       return SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
   ```

`scorer.py`（`_calculate_name_similarity` 方法）：
   ```python
   def _calculate_name_similarity(self, source_columns: List[str], target_columns: List[str]) -> float:
       if self.name_similarity_service:
           return self.name_similarity_service.compare_columns(source_columns, target_columns)
       # Fallback: 原有逻辑
       if len(source_columns) != len(target_columns):
           return 0.0
       total_sim = 0
       for src_col, tgt_col in zip(source_columns, target_columns):
           if src_col == tgt_col:
               sim = 1.0
           else:
               sim = SequenceMatcher(None, src_col.lower(), tgt_col.lower()).ratio()
           total_sim += sim
       return total_sim / len(source_columns)
   ```
5. **单元测试 / 集成测试**：
   - 构造假 embedding service（可注入 mock 向量）验证多列平均值、缓存次数等。
   - 添加配置解析测试，确保 `enabled=false` 时不会实例化 embedding 客户端。
6. **文档 & 示例脚本**：
   - 在 README 或使用指南中补充开关说明。
   - 可复用 `scripts/embedding_similarity_probe.py` 的思路，另建 MetaWeave 专用调试脚本（可选）。

## 7. 测试建议
- **单元测试**：
  - `NameSimilarityService`：字符串模式 vs embedding 模式结果是否符合预期；列数量不等返回 0；缓存命中不重复调用底层客户端。
  - `EmbeddingService`：模拟 dashscope 响应/错误，验证重试与异常处理。
- **集成测试**：在 `tests/test_full_relationship_pipeline.py` 或新增测试里，设置 `name_similarity.enabled=false/true` 比较得分变化，确保 pipeline 可运行。
- **性能测试**：在拥有大量候选的样本库上评估 embedding 开关对耗时的影响，必要时调优批量大小与缓存策略。

## 8. 风险与缓解
| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| Embedding API 异常导致流程中断 | 无法生成关系 | SDK/HTTP 调用层做 3 次可配置重试，仍失败则报错退出并记录错误日志，便于快速排查 |
| 大量字段触发频繁 API 请求 | 成本/时延上升 | 缓存向量；在候选阶段预批量算常见字段名；支持手动关闭 embedding |
| 依赖 numpy/dashscope 版本 | 运行失败 | 在 MetaWeave README 中记录依赖，CI 添加 import/self test |
| 未来切换 provider | 影响代码结构 | 在配置和 service 中保持 provider 抽象，`if provider == "dashscope"` 结构易扩展 |

## 9. 后续可选项
1. 支持局部词向量缓存落盘，在多次运行间复用。
2. 引入简单的字段名“规范化词典”与 embedding 组合。
3. 在决策环节记录名称相似度明细，便于诊断 embedding 开关效果。

## 10. 与 LLM 异步改造的兼容性
- 默认策略：列名数量在几十到几百时，保持同步 embedding + 缓存即可，复杂度最低；若在异步事件循环中直接调用同步接口会阻塞。
- 异步能力：`EmbeddingService` 同时提供 `get_embedding/get_embeddings` 与 `aget_embedding/aget_embeddings`（asyncio），内部用 `asyncio.Semaphore` 控制并发，复用同一份缓存与重试/批量逻辑。
- `NameSimilarityService` 补充 `acompare_pair/acompare_columns`，异步 pipeline（如 `LLMRelationshipDiscovery`）调用 async 接口，同步 pipeline 继续使用同步方法，实例可复用以共享缓存。
- 配置建议：在 `configs/metaweave/metadata_config.yaml` 的 `embedding` 节增加 `use_async`（默认 false）与 `async_concurrency`（默认 10），用于控制是否启用异步及并发度；仍复用现有 DashScope 环境变量 `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URI`。
- 技术实现：异步接口基于 Python 原生 asyncio，而非依赖 LangChain；Embedding 请求直接走 DashScope SDK/HTTP，保持 MetaWeave 模块内聚。
- 失败处理：无论同步/异步，Embedding 请求都会按配置（默认 3 次）重试；仍失败则抛出错误并退出，日志记录“无法连接 embedding 模型”；只有在配置显式 `method=string` 或 `enabled=false` 时才使用字符串算法。

**配置传递约定**
- 入口统一拿两份配置：按 4.2 的合并逻辑构造 `rel_config`（先拷贝 `config.get("relationships", {})`，再补顶层的 `single_column`/`composite`/`decision`/`weights` 等缺失字段），以及顶层 `embedding_config = config.get("embedding", {})`（与 `llm` 平级）。
- `NameSimilarityService` 构造签名建议为 `__init__(self, name_similarity_config: dict, embedding_config: dict)`：前者由 `rel_config.get("name_similarity", {})` 传入，后者直接传 `embedding_config`，避免丢失顶层 embedding 配置。
- provider 选择：优先使用顶层 `embedding.active` 决定具体 provider，`name_similarity` 不再单独声明 provider，避免重复。
