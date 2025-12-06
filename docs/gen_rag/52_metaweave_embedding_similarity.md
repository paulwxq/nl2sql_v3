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
- 由于列配对数量可能很大，必须缓存每个字段名的向量；可考虑在名称相似度服务层做 LRU 或简单字典缓存。
- 当 embedding 服务返回异常或 API 不可用时，自动回退到字符串算法，保证流程可继续执行。
- 所有可调参数（开关、provider、模型、timeouts、batch_size 等）只能放在 `metadata_config.yaml`，并允许 `${ENV_VAR:default}` 引用。

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

    embedding:
      provider: dashscope          # 先支持一个 provider，后续可扩展
      model: ${METAWEAVE_EMBED_MODEL:text-embedding-v3}
      api_base: ${METAWEAVE_EMBED_BASE:https://dashscope.aliyuncs.com/api/v1}
      api_key: ${METAWEAVE_EMBED_API_KEY}
      dimensions: 1024
      timeout: 30
      max_retries: 3
      batch_size: 16
```
> 若 `enabled=false` 或 `method=string`，直接使用原来的 SequenceMatcher，不触发 embedding。

### 4.2 `.env` 示例
```
METAWEAVE_EMBED_API_KEY=sk-xxx
METAWEAVE_EMBED_MODEL=text-embedding-v3
METAWEAVE_EMBED_BASE=https://dashscope.aliyuncs.com/api/v1
```

## 5. 模块设计
### 5.1 `NameSimilarityService`
- **位置**：`src/metaweave/core/relationships/name_similarity.py`（新文件）。
- **职责**：
  - 读取 `relationships.name_similarity` 配置。
  - 对外提供 `compare_columns(source_cols, target_cols)` 与 `compare_pair(name_a, name_b)`。
  - 内部根据配置决定使用 `EmbeddingSimilarityCalculator` 或 `SequenceMatcher`。
  - 维护一个 `Dict[str, np.ndarray]` 的缓存，并对字段名做 `lower().strip()` 规范化。
  - 提供监控日志：命中缓存、API 失败、回退等。

### 5.2 `EmbeddingSimilarityCalculator`
- **位置**：`src/metaweave/services/embedding_service.py`（新文件）。
- **功能**：
  - 封装具体 provider（初版仅 DashScope TextEmbedding）。
  - 提供 `get_embedding(text: str) -> np.ndarray` 和批量 `get_embeddings(list[str]) -> Dict[str, np.ndarray]` 接口。
  - 负责重试、超时及 API 结构解析。DashScope 可直接复用 `dashscope.TextEmbedding.call`，但参数、日志、错误需按 MetaWeave 风格处理。
  - 允许通过 `provider` 扩展结构，预留占位符（例如 future: `openai`）。

### 5.3 与现有流程的集成
1. **管道注入**：`RelationshipDiscoveryPipeline` 在初始化时创建 `NameSimilarityService`，传入 `self.config`。
2. **候选生成**：`CandidateGenerator` 接收该服务实例，通过依赖注入替换 `_calculate_name_similarity`；原方法可移至 service 或保留为 fallback。
3. **关系评分器**：`RelationshipScorer` 调用同一服务的 `compare_columns`，确保两个阶段的算法与缓存一致。
4. **日志**：在 DEBUG 级别输出 embedding 命中/回退信息，便于排查开关行为。

## 6. 主要实现步骤
1. **配置解析**：更新 `metadata_config.yaml`，并在 `RelationshipDiscoveryPipeline` 初始化时读取 `relationships.get("name_similarity", {})`，将该 dict 传给新服务。
2. **实现 `EmbeddingService`**：
   - 处理 provider 选择、API key 校验、调用 dashscope SDK。
   - 加上 numpy 依赖（项目已有），根据 `np.dot` / `np.linalg.norm` 计算余弦相似度。
   - 支持批量请求与指数退避重试，必要时拆分文本长度。
3. **实现 `NameSimilarityService`**：
   - 初始化 embedding service（如启用）。
   - 实现缓存：dict + max size（超过时可简单 FIFO 或 `functools.lru_cache`）。
   - 对外方法在多列场景下按索引配对求平均，与当前实现保持行为一致。
   - 若列数不一致，立即返回 0.0，和旧逻辑兼容。
4. **接入 Pipeline**：
   - `CandidateGenerator` 和 `RelationshipScorer` 改为依赖注入 service，移除重复代码。
   - 在日志中标记当前策略（embedding 或 string）。
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
| Embedding API 异常导致流程中断 | 无法生成关系 | 在 service 中捕获异常并回退到字符串算法，同时记录警告 |
| 大量字段触发频繁 API 请求 | 成本/时延上升 | 缓存向量；在候选阶段预批量算常见字段名；支持手动关闭 embedding |
| 依赖 numpy/dashscope 版本 | 运行失败 | 在 MetaWeave README 中记录依赖，CI 添加 import/self test |
| 未来切换 provider | 影响代码结构 | 在配置和 service 中保持 provider 抽象，`if provider == "dashscope"` 结构易扩展 |

## 9. 后续可选项
1. 支持局部词向量缓存落盘，在多次运行间复用。
2. 引入简单的字段名“规范化词典”与 embedding 组合。
3. 在决策环节记录名称相似度明细，便于诊断 embedding 开关效果。

