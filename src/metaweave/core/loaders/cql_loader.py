"""Neo4j CQL 加载器

加载 Step 4 生成的 import_all.cypher 文件到 Neo4j 图数据库。
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import re
import time
import logging

from src.metaweave.core.loaders.base import BaseLoader
from src.services.db.neo4j_connection import Neo4jConnectionManager
from src.services.config_loader import get_config
from neo4j.exceptions import Neo4jError

logger = logging.getLogger(__name__)


class CQLLoader(BaseLoader):
    """Neo4j CQL 加载器

    加载 Step 4 生成的 import_all.cypher 文件到 Neo4j 图数据库。

    特性:
    - 支持全局配置和自定义配置两种方式
    - 按章节拆分执行，便于错误定位
    - 支持单事务和分段事务两种模式
    - 幂等性保证（使用 MERGE 和 IF NOT EXISTS）
    - 可选的加载后验证
    - 支持清空数据库后加载
    """

    def __init__(self, config: Dict[str, Any]):
        """初始化 CQL 加载器

        Args:
            config: 配置字典，必须包含 cql_loader 字段
        """
        super().__init__(config)
        self.neo4j_config = self._get_neo4j_config()
        self.neo4j_manager: Optional[Neo4jConnectionManager] = None

        # 获取输入文件路径
        cql_config = self.config.get("cql_loader", {})
        input_file_str = cql_config.get("input_file", "output/metaweave/metadata/cql/import_all.cypher")
        self.input_file = Path(input_file_str)

        # 如果不是绝对路径，则相对于项目根目录
        if not self.input_file.is_absolute():
            from src.metaweave.utils.file_utils import get_project_root
            self.input_file = get_project_root() / input_file_str

    def _get_neo4j_config(self) -> Dict[str, Any]:
        """获取 Neo4j 配置（全局配置或自定义配置）

        Returns:
            Dict[str, Any]: Neo4j 配置字典
        """
        neo4j_section = self.config.get("cql_loader", {}).get("neo4j", {})

        if neo4j_section.get("use_global_config", True):
            # 使用全局配置
            global_config = get_config()
            return global_config["neo4j"]
        else:
            # 使用自定义配置
            return {
                "uri": neo4j_section["uri"],
                "user": neo4j_section["user"],
                "password": neo4j_section["password"],
                "database": neo4j_section.get("database", "neo4j"),
            }

    def validate(self) -> bool:
        """验证配置和数据源

        验证步骤:
        1. 检查配置是否包含 cql_loader 字段
        2. 检查 CQL 文件是否存在
        3. 测试 Neo4j 连接

        Returns:
            bool: 验证是否通过
        """
        # 1. 检查配置
        if "cql_loader" not in self.config:
            logger.error("配置缺少 cql_loader 字段")
            return False

        # 2. 检查文件
        if not self.input_file.exists():
            logger.error(f"CQL 文件不存在: {self.input_file}")
            return False

        # 3. 测试连接
        try:
            self.neo4j_manager = Neo4jConnectionManager(self.neo4j_config)
            self.neo4j_manager.initialize()
            if not self.neo4j_manager.test_connection():
                logger.error("Neo4j 连接测试失败")
                return False
        except Exception as e:
            logger.error(f"Neo4j 连接失败: {e}")
            return False

        logger.info("✅ 配置验证通过")
        logger.info(f"✅ CQL 文件存在: {self.input_file}")
        logger.info(f"✅ Neo4j 连接成功: {self.neo4j_config['uri']}")

        return True

    def load(self, clean: bool = False) -> Dict[str, Any]:
        """执行 CQL 加载

        Args:
            clean: 是否在加载前清空数据库

        Returns:
            Dict[str, Any]: 加载结果字典
        """
        start_time = time.time()

        # 1. 清空数据库（如果需要）
        if clean:
            logger.info("⚠️  执行清空数据库操作...")
            self._clean_database()

        # 2. 解析 CQL 文件
        logger.info("正在解析 CQL 文件...")
        sections = self._parse_cql_file(self.input_file)
        logger.info(f"解析完成，共 {len(sections)} 个章节")

        # 3. 执行加载
        options = self.config.get("cql_loader", {}).get("options", {})
        transaction_mode = options.get("transaction_mode", "by_section")
        logger.info(f"开始加载（事务模式: {transaction_mode}）...")

        if transaction_mode == "single":
            result = self._load_single_transaction(sections)
        else:
            result = self._load_by_section(sections)

        # 4. 验证结果（可选）
        validate_after_load = options.get("validate_after_load", True)
        if validate_after_load and result.get("success"):
            logger.info("验证加载结果...")
            expected_stats = self._extract_expected_stats(self.input_file)
            if expected_stats:
                self._validate_result(expected_stats)

        # 5. 统计执行时间
        execution_time = time.time() - start_time
        result["execution_time"] = round(execution_time, 2)

        return result

    def _clean_database(self) -> None:
        """清空 Neo4j 数据库

        删除所有节点和关系。谨慎使用！
        """
        try:
            query = "MATCH (n) DETACH DELETE n"
            self.neo4j_manager.execute_write_transaction(query)
            logger.info("✅ 数据库已清空")
        except Exception as e:
            logger.error(f"清空数据库失败: {e}")
            raise

    def _parse_cql_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """解析 CQL 文件，按章节拆分

        Args:
            file_path: CQL 文件路径

        Returns:
            List[Dict]: 章节列表，每个元素包含：
                - order: 执行顺序
                - section_name: 章节名称
                - cypher: Cypher 语句
        """
        content = file_path.read_text(encoding="utf-8")

        # 章节分隔符正则：// ===... \n // 1. ... \n // ===...
        section_pattern = r"// ={50,}\n// (\d+)\. (.+?)\n// ={50,}\n"

        sections = []
        matches = list(re.finditer(section_pattern, content))

        for i, match in enumerate(matches):
            section_number = match.group(1)
            section_title = match.group(2)

            # 提取章节内容（从当前分隔符到下一个分隔符）
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_content = content[start:end].strip()

            # 移除注释行
            cypher = "\n".join(
                line for line in section_content.split("\n")
                if not line.strip().startswith("//")
            ).strip()

            if cypher:
                sections.append({
                    "order": int(section_number),
                    "section_name": section_title,
                    "cypher": cypher,
                })

        return sections

    def _load_by_section(self, sections: List[Dict]) -> Dict[str, Any]:
        """按章节分段执行（推荐）

        每个章节作为一个独立的事务执行，便于错误定位。
        对于包含多条语句的章节（如约束创建），会按分号分隔并逐条执行。

        Args:
            sections: 章节列表

        Returns:
            Dict[str, Any]: 加载结果
        """
        stats = {
            "success": True,
            "message": "加载成功",
            "sections": [],
            "errors": [],
        }

        for section in sections:
            try:
                logger.info(f"  [{section['order']}/{len(sections)}] {section['section_name']}...")

                cypher_text = section["cypher"]
                logger.debug(f"    章节内容前100字符: {cypher_text[:100]}")

                # 修复 JSON 中的双引号问题（Cypher 语法要求）
                cypher_text = self._fix_json_quotes(cypher_text)

                # 修复嵌套数组问题（Neo4j 不支持嵌套集合）
                cypher_text = self._fix_nested_arrays(cypher_text)

                # 只对约束创建章节进行语句分隔（因为可能包含多条 CREATE CONSTRAINT）
                # 其他章节都是单条完整的 UNWIND ... 语句
                if "约束" in section["section_name"] or "CONSTRAINT" in cypher_text.upper()[:100]:
                    logger.debug("    检测到约束章节，按分号分隔语句")
                    # 将章节中的语句按分号分隔（支持多条语句）
                    statements = self._split_statements(cypher_text)
                    # 逐条执行语句
                    for i, stmt in enumerate(statements, 1):
                        if stmt.strip():
                            logger.debug(f"    执行语句 {i}/{len(statements)}: {stmt[:50]}...")
                            self.neo4j_manager.execute_write_transaction(stmt)
                else:
                    logger.debug("    整体执行章节")
                    # 其他章节整体执行
                    self.neo4j_manager.execute_write_transaction(cypher_text)

                stats["sections"].append({
                    "name": section["section_name"],
                    "success": True,
                })
                logger.info(f"    ✅ {section['section_name']} 完成")

            except Neo4jError as e:
                error_msg = f"{section['section_name']} 失败: {e.message}"
                logger.error(f"    ❌ {error_msg}")

                stats["success"] = False
                stats["message"] = error_msg
                stats["errors"].append({
                    "section": section["section_name"],
                    "error_type": "Neo4jError",
                    "error_message": e.message,
                    "error_code": getattr(e, "code", "N/A"),
                })
                break  # 中断后续章节

            except Exception as e:
                error_msg = f"{section['section_name']} 失败: {str(e)}"
                logger.error(f"    ❌ {error_msg}")

                stats["success"] = False
                stats["message"] = error_msg
                stats["errors"].append({
                    "section": section["section_name"],
                    "error_type": "UnknownError",
                    "error_message": str(e),
                })
                break

        return stats

    def _split_statements(self, cypher_text: str) -> List[str]:
        """将多条 Cypher 语句按分号分隔

        处理规则：
        - 按分号分隔
        - 移除空语句
        - 保留语句完整性（不分隔字符串内的分号）

        Args:
            cypher_text: Cypher 文本

        Returns:
            List[str]: 语句列表
        """
        # 简单实现：按分号分隔
        # 注意：这里假设 CQL 文件中没有字符串内的分号
        statements = cypher_text.split(";")
        return [stmt.strip() for stmt in statements if stmt.strip()]

    def _fix_json_quotes(self, cypher_text: str) -> str:
        """修复 JSON 格式中的双引号问题

        在 Cypher 中，双引号用于转义标识符，不能用于 JSON 的字段名。
        此方法将 JSON 对象中的双引号字段名转换为不带引号的格式。

        例如：
            {"full_name": "value"} => {full_name: "value"}

        Args:
            cypher_text: 原始 Cypher 文本

        Returns:
            str: 修复后的 Cypher 文本
        """
        # 正则：匹配 JSON 对象中的双引号字段名（如 "field_name": ）
        # 替换为不带引号的字段名（如 field_name: ）
        import re
        # 匹配模式："field_name":
        # 注意：只替换冒号前的双引号字段名，保留值中的双引号
        pattern = r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:'
        replacement = r'\1:'

        return re.sub(pattern, replacement, cypher_text)

    def _fix_nested_arrays(self, cypher_text: str) -> str:
        """修复嵌套数组问题（Neo4j 技术限制）

        **问题背景：**
        Neo4j 不支持在属性中存储嵌套集合（collection of collections）。
        如果尝试存储 [["col1"]]，会报错：
            Neo.ClientError.Statement.TypeError: Collections containing collections
            can not be stored in properties.

        **解决方案：**
        将嵌套数组字段转换为 JSON 字符串，保留原始数据结构。

        **转换示例：**
            原始: logic_pk: [["company_id"], ["code", "type"]]
            转换: logic_pk: '[["company_id"], ["code", "type"]]'

        **优点：**
        - 准确保留嵌套结构（能看出有几组复合键）
        - 语义清晰（相比平铺格式 ["col1,col2", "col3"]）

        **后续使用：**
        查询时需要用 json.loads() 解析：
            >>> import json
            >>> logic_pk_str = result[0]["logic_pk"]  # '[["company_id"]]'
            >>> logic_pk = json.loads(logic_pk_str)   # [["company_id"]]

        推荐使用辅助函数（见文档 2.4.3 节）：
            >>> from src.metaweave.utils.neo4j_helpers import parse_nested_array_field
            >>> logic_pk = parse_nested_array_field(logic_pk_str)

        **影响字段：**
        - uk, fk (物理唯一键和外键，支持多个)
        - logic_pk, logic_fk, logic_uk (逻辑键，支持多个候选)
        - indexes (索引)

        **不转换的字段：**
        - pk (物理主键) - Step 4 生成的是一维数组，Neo4j 原生支持

        Args:
            cypher_text: Cypher 文本

        Returns:
            str: 修复后的 Cypher 文本（嵌套数组已转为 JSON 字符串）
        """
        import re
        import json

        # 匹配嵌套数组的字段（如 logic_pk, logic_fk, logic_uk）
        # 这些字段包含二维数组
        # 注意：pk 是一维数组（Neo4j 原生支持），不需要转换
        nested_array_fields = ['uk', 'fk', 'logic_pk', 'logic_fk', 'logic_uk', 'indexes']

        for field in nested_array_fields:
            # 匹配模式：field: [[...]]
            # 使用非贪婪匹配，并考虑多行
            pattern = rf'{field}:\s*(\[\s*\[[\s\S]*?\]\s*\])'

            def replace_nested_array(match):
                """替换函数：将嵌套数组转换为 JSON 字符串"""
                array_str = match.group(1)
                try:
                    # 解析为 Python 对象
                    array_obj = eval(array_str)
                    # 转换为 JSON 字符串
                    json_str = json.dumps(array_obj)
                    # 使用单引号包裹 JSON 字符串（避免双引号转义问题）
                    # Cypher 支持单引号字符串
                    return f"{field}: '{json_str}'"
                except:
                    # 如果解析失败，保持原样
                    logger.warning(f"无法解析嵌套数组字段 {field}: {array_str[:50]}...")
                    return match.group(0)

            cypher_text = re.sub(pattern, replace_nested_array, cypher_text)

        return cypher_text

    def _load_single_transaction(self, sections: List[Dict]) -> Dict[str, Any]:
        """单事务执行（备选）

        将所有章节合并为一个大的事务执行。

        Args:
            sections: 章节列表

        Returns:
            Dict[str, Any]: 加载结果
        """
        stats = {
            "success": True,
            "message": "加载成功",
            "sections": [],
            "errors": [],
        }

        try:
            # 合并所有章节的 Cypher 语句
            all_cypher = "\n\n".join(s["cypher"] for s in sections)

            logger.info("  执行单事务加载...")
            self.neo4j_manager.execute_write_transaction(all_cypher)

            stats["sections"] = [{"name": "所有章节", "success": True}]
            logger.info("    ✅ 单事务加载完成")

        except Neo4jError as e:
            error_msg = f"单事务加载失败: {e.message}"
            logger.error(f"    ❌ {error_msg}")

            stats["success"] = False
            stats["message"] = error_msg
            stats["errors"].append({
                "section": "single_transaction",
                "error_type": "Neo4jError",
                "error_message": e.message,
                "error_code": getattr(e, "code", "N/A"),
            })

        except Exception as e:
            error_msg = f"单事务加载失败: {str(e)}"
            logger.error(f"    ❌ {error_msg}")

            stats["success"] = False
            stats["message"] = error_msg
            stats["errors"].append({
                "section": "single_transaction",
                "error_type": "UnknownError",
                "error_message": str(e),
            })

        return stats

    def _extract_expected_stats(self, file_path: Path) -> Dict[str, int]:
        """从 CQL 文件头部提取期望的统计信息

        文件头部格式：
            // 统计: 6 张表, 22 个列, 6 个关系

        Args:
            file_path: CQL 文件路径

        Returns:
            Dict[str, int]: 统计信息字典，包含 table_count, column_count, relationship_count
        """
        content = file_path.read_text(encoding="utf-8")

        # 正则提取统计信息
        match = re.search(
            r"// 统计:\s*(\d+)\s*张表,\s*(\d+)\s*个列,\s*(\d+)\s*个关系",
            content
        )

        if match:
            return {
                "table_count": int(match.group(1)),
                "column_count": int(match.group(2)),
                "relationship_count": int(match.group(3)),
            }
        else:
            logger.warning("无法从 CQL 文件提取统计信息，跳过验证")
            return {}

    def _validate_result(self, expected_stats: Dict[str, int]) -> None:
        """验证加载结果

        对比实际加载的节点/关系数量与期望值。

        Args:
            expected_stats: 期望的统计信息
        """
        actual_stats = self._get_graph_stats()

        # 对比表数量
        if actual_stats["table_count"] != expected_stats["table_count"]:
            logger.warning(
                f"表数量不匹配: 期望 {expected_stats['table_count']}, "
                f"实际 {actual_stats['table_count']}"
            )
        else:
            logger.info(f"✅ 表数量正确: {actual_stats['table_count']}")

        # 对比列数量
        if actual_stats["column_count"] != expected_stats["column_count"]:
            logger.warning(
                f"列数量不匹配: 期望 {expected_stats['column_count']}, "
                f"实际 {actual_stats['column_count']}"
            )
        else:
            logger.info(f"✅ 列数量正确: {actual_stats['column_count']}")

        # 对比关系数量
        if actual_stats["relationship_count"] != expected_stats["relationship_count"]:
            logger.warning(
                f"关系数量不匹配: 期望 {expected_stats['relationship_count']}, "
                f"实际 {actual_stats['relationship_count']}"
            )
        else:
            logger.info(f"✅ 关系数量正确: {actual_stats['relationship_count']}")

    def _get_graph_stats(self) -> Dict[str, int]:
        """查询 Neo4j 中的统计信息

        使用 WITH 分段统计，避免笛卡尔积导致的错误计数。

        Returns:
            Dict[str, int]: 统计信息，包含 table_count, column_count, relationship_count
        """
        query = """
            MATCH (t:Table)
            WITH count(t) AS table_count
            MATCH (c:Column)
            WITH table_count, count(c) AS column_count
            MATCH ()-[r:JOIN_ON]->()
            RETURN table_count, column_count, count(r) AS relationship_count
        """

        result = self.neo4j_manager.execute_query(query)

        if result:
            record = result[0]
            return {
                "table_count": record["table_count"],
                "column_count": record["column_count"],
                "relationship_count": record["relationship_count"],
            }
        else:
            return {
                "table_count": 0,
                "column_count": 0,
                "relationship_count": 0,
            }
