"""LLM 辅助关联关系发现

数据来源：
- LLM 调用：从 json_llm 文件读取，不查询数据库
- 评分阶段：复用 RelationshipScorer，需要数据库连接
"""

from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Set, Tuple
import json

from src.metaweave.core.metadata.connector import DatabaseConnector
from src.metaweave.core.relationships.models import Relation
from src.metaweave.core.relationships.repository import MetadataRepository
from src.metaweave.core.relationships.scorer import RelationshipScorer
from src.metaweave.services.llm_service import LLMService
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("relationships.llm_discovery")


# LLM 提示词
RELATIONSHIP_DISCOVERY_PROMPT = """
你是一个数据库关系分析专家。请分析以下两个表，判断它们之间是否存在关联关系。

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
        self.scorer = RelationshipScorer(config.get("relationships", {}), connector)
        self.llm_service = LLMService(config.get("llm", {}))
        
        output_config = config.get("output", {})
        json_llm_dir = output_config.get("json_llm_directory", "output/metaweave/metadata/json_llm")
        self.json_llm_dir = Path(json_llm_dir)
        
        # 读取 rel_id_salt 配置（与现有管道保持一致）
        rel_id_salt = output_config.get("rel_id_salt", "")
        
        # 复用 MetadataRepository 提取物理外键（包含 cardinality、relationship_id）
        self.repo = MetadataRepository(self.json_llm_dir, rel_id_salt=rel_id_salt)
        
    def discover(self) -> Dict:
        """发现关联关系，返回 rel JSON 格式的结果"""
        logger.info("=" * 60)
        logger.info("开始 LLM 辅助关联关系发现")
        logger.info("=" * 60)
        
        # 1. 加载所有 json_llm 文件
        logger.info(f"阶段1: 加载 json_llm 文件，目录: {self.json_llm_dir}")
        tables = self._load_all_tables()
        logger.info(f"已加载 {len(tables)} 张表的元数据")
        
        # 2. 提取物理外键（复用 MetadataRepository，包含 cardinality、relationship_id）
        logger.info("阶段2: 提取物理外键")
        fk_relation_objects, fk_signatures = self.repo.collect_foreign_keys(tables)
        logger.info(f"物理外键直通: {len(fk_relation_objects)} 个")
        
        # 3. 两两组合调用 LLM
        logger.info("阶段3: 两两组合调用 LLM")
        table_pairs = list(combinations(tables.keys(), 2))
        logger.info(f"共 {len(table_pairs)} 个表对需要处理")
        
        llm_candidates = []
        for i, (table1_name, table2_name) in enumerate(table_pairs):
            logger.debug(f"处理表对 [{i+1}/{len(table_pairs)}]: {table1_name} <-> {table2_name}")
            
            candidates = self._call_llm(tables[table1_name], tables[table2_name])
            llm_candidates.extend(candidates)
            
            if (i + 1) % 10 == 0:
                logger.info(f"LLM 调用进度: {i+1}/{len(table_pairs)}")
        
        logger.info(f"LLM 返回候选: {len(llm_candidates)} 个")
        
        # 4. 过滤已有物理外键
        logger.info("阶段4: 过滤已有物理外键")
        filtered_candidates = self._filter_existing_fks(llm_candidates, fk_signatures)
        logger.info(f"过滤后候选: {len(filtered_candidates)} 个")
        
        # 5. 评分
        logger.info("阶段5: 对候选关联进行评分")
        scored_relations = self._score_candidates(filtered_candidates, tables)
        logger.info(f"评分后关系: {len(scored_relations)} 个")
        
        # 6. 合并结果（将 Relation 对象转换为字典）
        logger.info("阶段6: 合并物理外键和推断关系")
        fk_relations = [self._relation_to_dict(rel) for rel in fk_relation_objects]
        all_relations = fk_relations + scored_relations
        logger.info(f"最终关系总数: {len(all_relations)}")
        
        return self._build_output(all_relations)
    
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
        """调用 LLM 获取候选关联
        
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
        
        try:
            response = self.llm_service._call_llm(prompt)
            candidates = self._parse_llm_response(response)
            logger.debug(f"LLM 返回 {len(candidates)} 个候选: {table1_name} <-> {table2_name}")
            return candidates
        except Exception as e:
            logger.warning(f"LLM 调用失败: {table1_name} <-> {table2_name}, 错误: {e}")
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
    
    def _filter_existing_fks(self, candidates: List[Dict], fk_signatures: Set[str]) -> List[Dict]:
        """过滤已有的物理外键
        
        注意签名方向：
        - fk_signatures 来自 MetadataRepository，方向是 外键表->主键表
        - LLM 候选的 from/to 方向是 主键表->外键表
        - 因此需要翻转 LLM 候选的方向再生成签名
        """
        filtered = []
        for candidate in candidates:
            from_info = candidate["from_table"]  # 主键表
            to_info = candidate["to_table"]      # 外键表
            
            if candidate["type"] == "single_column":
                from_cols = [candidate["from_column"]]  # 主键列
                to_cols = [candidate["to_column"]]      # 外键列
            else:
                from_cols = candidate["from_columns"]
                to_cols = candidate["to_columns"]
            
            # 翻转方向：外键表->主键表，与 fk_signatures 一致
            sig = self._make_signature(
                to_info["schema"], to_info["table"], to_cols,      # 外键表、外键列
                from_info["schema"], from_info["table"], from_cols  # 主键表、主键列
            )
            
            if sig not in fk_signatures:
                filtered.append(candidate)
            else:
                logger.debug(f"跳过已有物理外键: {sig}")
        
        return filtered
    
    def _build_output(self, relations: List[Dict]) -> Dict:
        """构建输出 JSON（与现有 rel JSON 格式一致）"""
        return {
            "metadata_source": "json_llm_files",
            "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
            "statistics": {
                "total_relationships_found": len(relations),
                "foreign_key_relationships": sum(1 for r in relations if r.get("discovery_method") == "foreign_key_constraint"),
                "llm_assisted_relationships": sum(1 for r in relations if r.get("discovery_method") == "llm_assisted")
            },
            "relationships": relations
        }

