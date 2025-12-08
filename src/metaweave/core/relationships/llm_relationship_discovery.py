"""LLM 辅助关联关系发现。

数据来源：
- LLM 调用：从 json_llm 文件读取，不查询数据库
- 评分阶段：复用 RelationshipScorer，需要数据库连接
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Set, Tuple

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.core.relationships.models import Relation
from src.metaweave.core.relationships.repository import MetadataRepository
from src.metaweave.core.relationships.scorer import RelationshipScorer
from src.metaweave.core.relationships.name_similarity import NameSimilarityService
from src.metaweave.services.llm_service import LLMService
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.llm_discovery")


# LLM 提示词
RELATIONSHIP_DISCOVERY_PROMPT = """
你是一个数据库关系分析专家。请分析以下两个表以及表中的采样数据，判断它们之间是否存在关联关系。

## 表 1: {table1_name}
```json
{table1_json}
```

## 表 2: {table2_name}
```json
{table2_json}
```

## 任务
分析这两个表之间可能的关联关系（外键关系）。考虑以下因素：
1. 字段名相同或相似
2. 数据类型兼容
3. 字段注释的语义关联
4. 样例数据的值域匹配
5. 复合键的可能性（多个字段组合）

## 输出格式
返回 JSON 格式。如果存在关联，返回关联信息；如果没有关联，返回空数组。

### 单列关联示例
```json
{{
  "relationships": [
    {{
      "type": "single_column",
      "from_table": {{"schema": "public", "table": "dim_region"}},
      "to_table": {{"schema": "public", "table": "dim_store"}},
      "from_column": "region_id",
      "to_column": "region_id"
    }}
  ]
}}
```

### 多列关联示例（type 为 composite，字段用数组）
```json
{{
  "relationships": [
    {{
      "type": "composite",
      "from_table": {{"schema": "public", "table": "equipment_config"}},
      "to_table": {{"schema": "public", "table": "maintenance_work_order"}},
      "from_columns": ["equipment_id", "config_version"],
      "to_columns": ["equipment_id", "config_version"]
    }}
  ]
}}
```

### 无关联
```json
{{
  "relationships": []
}}
```

请只返回 JSON，不要包含其他内容。
"""


class LLMRelationshipDiscovery:
    """LLM 辅助关联关系发现
    
    数据来源：
    - LLM 调用：从 json_llm 文件读取，不查询数据库
    - 评分阶段：复用 RelationshipScorer，需要数据库连接
    """
    
    def __init__(self, config: Dict, connector: DatabaseConnector):
        self.config = config
        self.connector = connector  # 仅用于评分阶段

        # 构造关系配置（兼容混合结构）
        self.rel_config = config.get("relationships", {}).copy()
        for key in ["single_column", "composite", "decision", "weights"]:
            if key in config and key not in self.rel_config:
                self.rel_config[key] = config[key]

        # 初始化名称相似度服务
        embedding_config = config.get("embedding", {})
        name_sim_config = self.rel_config.get("name_similarity", {})
        if (name_sim_config.get("method") or "string").lower() != "string":
            self.name_similarity_service = NameSimilarityService(name_sim_config, embedding_config)
        else:
            self.name_similarity_service = None

        self.scorer = RelationshipScorer(self.rel_config, connector, self.name_similarity_service)

        llm_config = config.get("llm", {})
        self.llm_service = LLMService(llm_config)

        output_config = config.get("output", {})
        json_llm_dir = output_config.get("json_llm_directory", "output/metaweave/metadata/json_llm")
        self.json_llm_dir = Path(json_llm_dir)
        
        # 读取 rel_id_salt 配置（与现有管道保持一致）
        rel_id_salt = output_config.get("rel_id_salt", "")
        
        # 复用 MetadataRepository 提取物理外键（包含 cardinality、relationship_id）
        self.repo = MetadataRepository(self.json_llm_dir, rel_id_salt=rel_id_salt)
        
        # 读取决策阈值配置
        decision_config = self.rel_config.get("decision", {})
        self.accept_threshold = decision_config.get("accept_threshold", 0.65)
        self.high_confidence_threshold = decision_config.get("high_confidence_threshold", 0.90)
        self.medium_confidence_threshold = decision_config.get("medium_confidence_threshold", 0.80)
        
        # 读取 LLM 重试配置
        self.llm_max_retries = llm_config.get("retry_times", 2)
        self.llm_retry_delay = llm_config.get("retry_delay", 1)  # 重试延迟（秒）

        langchain_config = llm_config.get("langchain_config", {})
        self.use_async = langchain_config.get("use_async", False)
        self.batch_size = max(1, int(langchain_config.get("batch_size", 50) or 50))

        logger.info(
            f"阈值配置: accept={self.accept_threshold}, "
            f"high={self.high_confidence_threshold}, "
            f"medium={self.medium_confidence_threshold}"
        )
        logger.info(
            "LLM 异步配置: use_async=%s, batch_size=%s",
            self.use_async,
            self.batch_size,
        )
        logger.info(
            f"LLM 重试配置: max_retries={self.llm_max_retries}, "
            f"retry_delay={self.llm_retry_delay}s"
        )
        
    def discover(self) -> Dict:
        """同步入口：发现关联关系。"""

        start_time = time.time()
        logger.info("=" * 60)
        logger.info("开始 LLM 辅助关联关系发现")
        logger.info("=" * 60)

        tables, fk_relation_objects, fk_relationship_ids = self._load_tables_and_foreign_keys()

        logger.info("阶段3: 两两组合调用 LLM")
        table_pairs = list(combinations(tables.keys(), 2))
        total_pairs = len(table_pairs)
        logger.info(f"共 {total_pairs} 个表对需要处理")

        if self.use_async:
            logger.info(f"阶段3: 异步并发调用 LLM (分批大小={self.batch_size})")
            llm_candidates = self._run_async(
                self._discover_llm_candidates_async(tables, table_pairs)
            )
        else:
            logger.info("阶段3: 同步串行调用 LLM")
            llm_candidates = self._discover_llm_candidates_sync(tables, table_pairs)

        logger.info(f"LLM 返回候选: {len(llm_candidates)} 个")

        return self._finalize_relations(
            tables,
            fk_relation_objects,
            fk_relationship_ids,
            llm_candidates,
            start_time,
        )

    async def discover_async(self) -> Dict:
        """异步入口，适用于已有事件循环的环境。"""

        start_time = time.time()
        logger.info("=" * 60)
        logger.info("开始 LLM 辅助关联关系发现 (async)")
        logger.info("=" * 60)

        tables, fk_relation_objects, fk_relationship_ids = self._load_tables_and_foreign_keys()

        logger.info("阶段3: 两两组合调用 LLM")
        table_pairs = list(combinations(tables.keys(), 2))
        total_pairs = len(table_pairs)
        logger.info(f"共 {total_pairs} 个表对需要处理")

        if self.use_async:
            logger.info(f"阶段3: 异步并发调用 LLM (分批大小={self.batch_size})")
            llm_candidates = await self._discover_llm_candidates_async(tables, table_pairs)
        else:
            logger.info("阶段3: 同步串行调用 LLM")
            llm_candidates = self._discover_llm_candidates_sync(tables, table_pairs)

        logger.info(f"LLM 返回候选: {len(llm_candidates)} 个")

        return self._finalize_relations(
            tables,
            fk_relation_objects,
            fk_relationship_ids,
            llm_candidates,
            start_time,
        )
    
    def _load_tables_and_foreign_keys(self):
        logger.info(f"阶段1: 加载 json_llm 文件，目录: {self.json_llm_dir}")
        tables = self._load_all_tables()
        logger.info(f"已加载 {len(tables)} 张表的元数据")

        logger.info("阶段2: 提取物理外键")
        fk_relation_objects, fk_relationship_ids = self.repo.collect_foreign_keys(tables)
        logger.info(f"物理外键直通: {len(fk_relation_objects)} 个")
        return tables, fk_relation_objects, fk_relationship_ids

    def _discover_llm_candidates_sync(
        self,
        tables: Dict[str, Dict],
        table_pairs: List[Tuple[str, str]],
    ) -> List[Dict]:
        llm_candidates: List[Dict] = []
        for i, (table1_name, table2_name) in enumerate(table_pairs):
            logger.debug(
                "处理表对 [%s/%s]: %s <-> %s",
                i + 1,
                len(table_pairs),
                table1_name,
                table2_name,
            )

            candidates = self._call_llm(tables[table1_name], tables[table2_name])
            llm_candidates.extend(candidates)

            if (i + 1) % 10 == 0:
                logger.info(f"LLM 调用进度: {i + 1}/{len(table_pairs)}")

        return llm_candidates

    async def _discover_llm_candidates_async(
        self,
        tables: Dict[str, Dict],
        table_pairs: List[Tuple[str, str]],
    ) -> List[Dict]:
        total_pairs = len(table_pairs)
        if total_pairs == 0:
            return []

        llm_candidates: List[Dict] = []
        progress_step = max(1, total_pairs // 5)

        for batch_start in range(0, total_pairs, self.batch_size):
            batch_end = min(batch_start + self.batch_size, total_pairs)
            batch_pairs = table_pairs[batch_start:batch_end]
            batch_num = batch_start // self.batch_size + 1
            logger.info(
                "处理批次 %s: 表对 %s-%s/%s",
                batch_num,
                batch_start + 1,
                batch_end,
                total_pairs,
            )

            batch_prompts = [
                self._build_prompt(tables[t1], tables[t2])
                for t1, t2 in batch_pairs
            ]

            def on_progress(completed: int, total: int):
                global_completed = batch_start + completed
                if completed == total or global_completed % progress_step == 0:
                    logger.info(
                        "LLM 调用进度: %s/%s",
                        global_completed,
                        total_pairs,
                    )
                else:
                    logger.debug(
                        "LLM 调用完成: %s/%s",
                        global_completed,
                        total_pairs,
                    )

            results = await self.llm_service.batch_call_llm_async(
                batch_prompts,
                on_progress=on_progress,
            )

            pair_by_idx = dict(enumerate(batch_pairs))
            for idx, response in results:
                t1, t2 = pair_by_idx[idx]
                if response:
                    candidates = self._parse_llm_response(response)
                    llm_candidates.extend(candidates)
                else:
                    logger.warning(f"表对 {t1} <-> {t2} 无响应")

            del batch_prompts
            del pair_by_idx

        return llm_candidates

    def _build_prompt(self, table1: Dict, table2: Dict) -> str:
        table1_info = table1.get("table_info", {})
        table2_info = table2.get("table_info", {})
        table1_name = f"{table1_info['schema_name']}.{table1_info['table_name']}"
        table2_name = f"{table2_info['schema_name']}.{table2_info['table_name']}"

        return RELATIONSHIP_DISCOVERY_PROMPT.format(
            table1_name=table1_name,
            table1_json=json.dumps(table1, ensure_ascii=False, indent=2),
            table2_name=table2_name,
            table2_json=json.dumps(table2, ensure_ascii=False, indent=2),
        )

    def _run_async(self, coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "检测到已存在运行中的事件循环。"
            "请改用 await discovery.discover_async() 或在 CLI 层调用 asyncio.run()."
        )

    def _finalize_relations(
        self,
        tables: Dict[str, Dict],
        fk_relation_objects: List[Relation],
        fk_relationship_ids: Set[str],
        llm_candidates: List[Dict],
        start_time: float,
    ) -> Dict:
        logger.info("阶段4: 过滤已有物理外键（基于 relationship_id）")
        filtered_candidates = self._filter_existing_fks(llm_candidates, fk_relationship_ids)
        skipped_fk_count = len(llm_candidates) - len(filtered_candidates)
        logger.info(
            "过滤后候选: %s 个 (已跳过 %s 个物理外键)",
            len(filtered_candidates),
            skipped_fk_count,
        )

        score_start = time.time()
        logger.info("阶段5: 对候选关联进行评分")
        scored_relations = self._score_candidates(filtered_candidates, tables)
        score_duration = time.time() - score_start
        logger.info(
            "评分后关系: %s 个 (耗时: %.2f秒, 节省了 %s 个物理外键的评分计算)",
            len(scored_relations),
            score_duration,
            skipped_fk_count,
        )

        logger.info(f"阶段6: 阈值过滤 (threshold={self.accept_threshold})")
        accepted_relations, rejected_relations = self._filter_by_threshold(scored_relations)
        logger.info(f"过滤后接受: {len(accepted_relations)} 个")

        logger.info("阶段7: 合并物理外键和推断关系")
        fk_relations = [self._relation_to_dict(rel) for rel in fk_relation_objects]
        before_dedup_count = len(fk_relations) + len(accepted_relations)
        all_relations = self._deduplicate_by_relationship_id(fk_relations, accepted_relations)

        if before_dedup_count > len(all_relations):
            dup_count = before_dedup_count - len(all_relations)
            logger.warning(
                "⚠️ 阶段7发现 %s 个重复关系（阶段4可能遗漏），已去重。",
                dup_count,
            )
        else:
            logger.debug("✓ 阶段7未发现重复，阶段4去重有效")

        logger.info(f"最终关系总数: {len(all_relations)}")
        total_duration = time.time() - start_time
        logger.info(f"✓ 关系发现总耗时: {total_duration:.2f}秒")

        return self._build_output(all_relations, rejected_relations)

    def _load_all_tables(self) -> Dict[str, Dict]:
        """加载所有 json_llm 文件"""
        tables = {}
        for json_file in self.json_llm_dir.glob("*.json"):
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            table_info = data.get("table_info", {})
            full_name = f"{table_info['schema_name']}.{table_info['table_name']}"
            tables[full_name] = data
            logger.debug(f"已加载: {full_name}")
        return tables
    
    def _relation_to_dict(self, rel: Relation) -> Dict:
        """将 Relation 对象转换为 rel JSON 格式的字典
        
        注意语义转换：
        - Relation 对象：source=外键表, target=主键表
        - rel JSON 约定：from=主键表, to=外键表
        - 因此需要交换 source/target
        """
        rel_type = "composite" if len(rel.source_columns) > 1 else "single_column"
        
        # 交换 source/target 以符合 rel JSON 约定（from=主键表, to=外键表）
        result = {
            "relationship_id": rel.relationship_id,
            "type": rel_type,
            "from_table": {"schema": rel.target_schema, "table": rel.target_table},  # 主键表
            "to_table": {"schema": rel.source_schema, "table": rel.source_table},    # 外键表
            "discovery_method": "foreign_key_constraint",
            "cardinality": self._flip_cardinality(rel.cardinality)  # 方向翻转，基数也要翻转
        }
        
        if rel_type == "single_column":
            result["from_column"] = rel.target_columns[0]   # 主键列
            result["to_column"] = rel.source_columns[0]     # 外键列
        else:
            result["from_columns"] = rel.target_columns     # 主键列
            result["to_columns"] = rel.source_columns       # 外键列
        
        return result
    
    def _flip_cardinality(self, cardinality: str) -> str:
        """翻转基数方向"""
        flip_map = {"1:N": "N:1", "N:1": "1:N", "1:1": "1:1", "M:N": "M:N"}
        return flip_map.get(cardinality, cardinality)
    
    def _call_llm(self, table1: Dict, table2: Dict) -> List[Dict]:
        """调用 LLM 获取候选关联（带重试）
        
        注意：table1/table2 来自 json_llm 文件，不查询数据库
        """
        table1_info = table1.get("table_info", {})
        table2_info = table2.get("table_info", {})
        
        table1_name = f"{table1_info['schema_name']}.{table1_info['table_name']}"
        table2_name = f"{table2_info['schema_name']}.{table2_info['table_name']}"
        
        prompt = RELATIONSHIP_DISCOVERY_PROMPT.format(
            table1_name=table1_name,
            table1_json=json.dumps(table1, ensure_ascii=False, indent=2),
            table2_name=table2_name,
            table2_json=json.dumps(table2, ensure_ascii=False, indent=2),
        )
        
        # 添加调试日志：输出提示词长度
        logger.debug(f"LLM 提示词长度: {len(prompt)} 字符, 表对: {table1_name} <-> {table2_name}")
        
        # 重试逻辑
        for attempt in range(self.llm_max_retries + 1):
            try:
                response = self.llm_service._call_llm(prompt)
                candidates = self._parse_llm_response(response)
                
                # 如果之前有重试，记录成功信息
                if attempt > 0:
                    logger.info(
                        f"✓ LLM 调用成功（重试 {attempt} 次后）: {table1_name} <-> {table2_name}"
                    )
                
                logger.debug(f"LLM 返回 {len(candidates)} 个候选: {table1_name} <-> {table2_name}")
                return candidates
                
            except Exception as e:
                if attempt < self.llm_max_retries:
                    # 还有重试机会
                    logger.warning(
                        f"LLM 调用失败 (尝试 {attempt + 1}/{self.llm_max_retries + 1}): "
                        f"{table1_name} <-> {table2_name}, 错误: {e}, "
                        f"{self.llm_retry_delay}秒后重试..."
                    )
                    time.sleep(self.llm_retry_delay)
                else:
                    # 已达最大重试次数
                    logger.error(
                        f"✗ LLM 调用失败（已重试 {self.llm_max_retries} 次）: "
                        f"{table1_name} <-> {table2_name}, 最终错误: {e}"
                    )
                    logger.debug(f"调用失败时的提示词（前1000字符）: {prompt[:1000]}")
                    return []
    
    def _parse_llm_response(self, response: str) -> List[Dict]:
        """解析 LLM 返回"""
        try:
            # 添加调试日志：输出原始返回内容
            logger.debug(f"LLM 原始返回（前500字符）: {response[:500] if response else '(空响应)'}")
            
            # 清理 Markdown 代码块标记（使用正则表达式）
            import re
            cleaned_response = response.strip()
            
            # 移除开头的 ```json 或 ```
            cleaned_response = re.sub(r'^```(?:json)?\s*', '', cleaned_response, flags=re.MULTILINE)
            
            # 移除结尾的 ```
            cleaned_response = re.sub(r'\s*```\s*$', '', cleaned_response, flags=re.MULTILINE)
            
            cleaned_response = cleaned_response.strip()
            
            # 尝试提取第一个完整的 JSON 对象
            # 找到第一个 { 和对应的 }
            start_idx = cleaned_response.find('{')
            if start_idx == -1:
                logger.warning("LLM 返回中未找到 JSON 对象")
                return []
            
            # 从第一个 { 开始，找到匹配的 }
            brace_count = 0
            end_idx = start_idx
            for i in range(start_idx, len(cleaned_response)):
                if cleaned_response[i] == '{':
                    brace_count += 1
                elif cleaned_response[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            
            if brace_count != 0:
                logger.warning("LLM 返回的 JSON 括号不匹配")
                return []
            
            cleaned_response = cleaned_response[start_idx:end_idx]
            
            logger.debug(f"提取的 JSON（前200字符）: {cleaned_response[:200]}")
            
            data = json.loads(cleaned_response)
            relationships = data.get("relationships", [])
            
            if not isinstance(relationships, list):
                logger.warning(f"LLM 返回格式错误: relationships 不是数组")
                return []
            
            logger.debug(f"成功解析 {len(relationships)} 个关系")
            return relationships
        except json.JSONDecodeError as e:
            logger.warning(f"LLM 返回 JSON 解析失败: {e}")
            logger.debug(f"无法解析的响应: {response[:1000] if response else '(空)'}")
            return []
        except Exception as e:
            logger.error(f"解析 LLM 响应时发生异常: {e}")
            return []
    
    def _score_candidates(self, candidates: List[Dict], tables: Dict[str, Dict]) -> List[Dict]:
        """对候选关联进行评分
        
        复用 RelationshipScorer._calculate_scores 方法
        """
        scored_relations = []
        rel_id_salt = self.config.get("output", {}).get("rel_id_salt", "")
        
        for candidate in candidates:
            from_table_info = candidate["from_table"]
            to_table_info = candidate["to_table"]
            
            from_full_name = f"{from_table_info['schema']}.{from_table_info['table']}"
            to_full_name = f"{to_table_info['schema']}.{to_table_info['table']}"
            
            # 获取表元数据
            from_table = tables.get(from_full_name)
            to_table = tables.get(to_full_name)
            
            if not from_table or not to_table:
                logger.warning(f"找不到表元数据: {from_full_name} 或 {to_full_name}")
                continue
            
            # 提取列名
            if candidate["type"] == "single_column":
                from_columns = [candidate["from_column"]]
                to_columns = [candidate["to_column"]]
            else:
                from_columns = candidate["from_columns"]
                to_columns = candidate["to_columns"]
            
            # 调用评分方法
            logger.debug(f"评分: {from_full_name}{from_columns} -> {to_full_name}{to_columns}")
            
            score_details, cardinality = self.scorer._calculate_scores(
                from_table, from_columns,
                to_table, to_columns
            )
            
            # 计算综合评分
            composite_score = sum(
                score_details[dim] * self.scorer.weights[dim]
                for dim in score_details
            )
            
            logger.debug(f"评分结果: composite={composite_score:.4f}, cardinality={cardinality}")
            
            # 生成 relationship_id（复用 MetadataRepository.compute_relationship_id）
            relationship_id = MetadataRepository.compute_relationship_id(
                source_schema=from_table_info["schema"],
                source_table=from_table_info["table"],
                source_columns=from_columns,
                target_schema=to_table_info["schema"],
                target_table=to_table_info["table"],
                target_columns=to_columns,
                rel_id_salt=rel_id_salt
            )
            
            # 构建关系对象（包含完整字段，与现有格式一致）
            relation = {
                "relationship_id": relationship_id,
                **candidate,
                "discovery_method": "llm_assisted",
                "target_source_type": "llm_inferred",  # 关系发现来源标记
                "source_constraint": None,             # LLM 推断，无源约束
                "composite_score": round(composite_score, 4),
                "confidence_level": self._get_confidence_level(composite_score),
                "metrics": {k: round(v, 4) for k, v in score_details.items()},
                "cardinality": cardinality
            }
            
            scored_relations.append(relation)
        
        return scored_relations
    
    def _filter_by_threshold(
        self, 
        scored_relations: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """根据阈值过滤关系
        
        Args:
            scored_relations: 评分后的关系列表
            
        Returns:
            (accepted_relations, rejected_relations)
        """
        accepted = []
        rejected = []
        
        for relation in scored_relations:
            composite_score = relation.get("composite_score", 0)
            
            from_table = relation.get("from_table", {})
            to_table = relation.get("to_table", {})
            from_schema = from_table.get("schema", "")
            from_name = from_table.get("table", "")
            to_schema = to_table.get("schema", "")
            to_name = to_table.get("table", "")
            
            rel_desc = f"{from_schema}.{from_name} -> {to_schema}.{to_name}"
            
            if composite_score >= self.accept_threshold:
                accepted.append(relation)
                logger.debug(
                    f"✓ 通过阈值: {rel_desc} (score={composite_score:.4f})"
                )
            else:
                rejected.append(relation)
                logger.info(
                    f"✗ 低于阈值: {rel_desc} "
                    f"(score={composite_score:.4f} < {self.accept_threshold})"
                )
        
        logger.info(
            f"阈值过滤结果: {len(accepted)} 个通过, {len(rejected)} 个被拒绝"
        )
        return accepted, rejected
    
    def _get_confidence_level(self, score: float) -> str:
        """根据评分确定置信度等级"""
        if score >= 0.8:
            return "high"
        elif score >= 0.6:
            return "medium"
        else:
            return "low"
    
    def _make_signature(self, src_schema, src_table, src_cols, tgt_schema, tgt_table, tgt_cols) -> str:
        """生成关系签名用于去重"""
        src_cols_str = ",".join(sorted(src_cols))
        tgt_cols_str = ",".join(sorted(tgt_cols))
        return f"{src_schema}.{src_table}[{src_cols_str}]->{tgt_schema}.{tgt_table}[{tgt_cols_str}]"
    
    def _filter_existing_fks(self, candidates: List[Dict], fk_relationship_ids: Set[str]) -> List[Dict]:
        """过滤已有的物理外键（使用 relationship_id 去重，双向一致）
        
        优化说明：
        - 使用 relationship_id 而非签名，避免方向性问题
        - 在评分前就排除物理外键，节省数据库查询和计算资源
        - relationship_id 是双向的，不受 LLM 返回方向影响
        
        Args:
            candidates: LLM 返回的候选关系
            fk_relationship_ids: 物理外键的 relationship_id 集合
            
        Returns:
            过滤后的候选关系（排除了物理外键）
        """
        filtered = []
        skipped_count = 0
        
        for candidate in candidates:
            from_info = candidate["from_table"]
            to_info = candidate["to_table"]
            
            if candidate["type"] == "single_column":
                from_cols = [candidate["from_column"]]
                to_cols = [candidate["to_column"]]
            else:
                from_cols = candidate["from_columns"]
                to_cols = candidate["to_columns"]
            
            # 生成候选的 relationship_id（双向一致，与物理外键的 ID 可比较）
            candidate_rel_id = MetadataRepository.compute_relationship_id(
                source_schema=from_info["schema"],
                source_table=from_info["table"],
                source_columns=from_cols,
                target_schema=to_info["schema"],
                target_table=to_info["table"],
                target_columns=to_cols,
                rel_id_salt=self.repo.rel_id_salt
            )
            
            # 基于 relationship_id 匹配（不受方向影响）
            if candidate_rel_id not in fk_relationship_ids:
                filtered.append(candidate)
            else:
                skipped_count += 1
                logger.debug(
                    f"跳过物理外键: {from_info['schema']}.{from_info['table']} <-> "
                    f"{to_info['schema']}.{to_info['table']} "
                    f"(relationship_id={candidate_rel_id})"
                )
        
        if skipped_count > 0:
            logger.info(f"✓ 阶段4去重: 跳过 {skipped_count} 个物理外键，避免重复评分")
        
        return filtered
    
    def _deduplicate_by_relationship_id(
        self, 
        fk_relations: List[Dict], 
        llm_relations: List[Dict]
    ) -> List[Dict]:
        """根据 relationship_id 去重，优先保留物理外键
        
        Args:
            fk_relations: 物理外键关系列表
            llm_relations: LLM 推断关系列表
            
        Returns:
            去重后的关系列表
        """
        # 建立 relationship_id -> 物理外键 的映射
        fk_id_map = {rel["relationship_id"]: rel for rel in fk_relations}
        
        # 过滤 LLM 关系：如果 relationship_id 与物理外键重复，跳过
        filtered_llm_relations = []
        for llm_rel in llm_relations:
            rel_id = llm_rel["relationship_id"]
            if rel_id in fk_id_map:
                # 记录被去重的关系
                from_table = llm_rel.get("from_table", {})
                to_table = llm_rel.get("to_table", {})
                logger.debug(
                    f"去重：跳过 LLM 推断关系 {from_table.get('schema')}.{from_table.get('table')} -> "
                    f"{to_table.get('schema')}.{to_table.get('table')} "
                    f"(relationship_id={rel_id}，物理外键已存在)"
                )
            else:
                filtered_llm_relations.append(llm_rel)
        
        # 合并：物理外键 + 去重后的 LLM 关系
        all_relations = fk_relations + filtered_llm_relations
        
        if len(llm_relations) > len(filtered_llm_relations):
            dedup_count = len(llm_relations) - len(filtered_llm_relations)
            logger.info(f"去重：移除 {dedup_count} 个与物理外键重复的 LLM 推断关系")
        
        return all_relations
    
    def _build_output(self, relations: List[Dict], rejected: List[Dict] = None) -> Dict:
        """构建输出 JSON（与现有 rel JSON 格式一致）
        
        Args:
            relations: 接受的关系列表
            rejected: 被拒绝的关系列表（可选）
            
        Returns:
            输出 JSON 字典
        """
        stats = {
            "total_relationships_found": len(relations),
            "foreign_key_relationships": sum(
                1 for r in relations if r.get("discovery_method") == "foreign_key_constraint"
            ),
            "llm_assisted_relationships": sum(
                1 for r in relations if r.get("discovery_method") == "llm_assisted"
            )
        }
        
        # 记录被拒绝的关系统计
        if rejected:
            stats["rejected_low_confidence"] = len(rejected)
            logger.info(f"被拒绝的低置信度关系: {len(rejected)} 个")
        
        return {
            "metadata_source": "json_llm_files",
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            "statistics": stats,
            "relationships": relations
        }

