"""问题解析节点单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.sql_generation.subgraph.nodes.question_parsing import (
    QuestionParsingAgent,
    question_parsing_node,
)


class TestQuestionParsingAgent:
    """测试 QuestionParsingAgent 类"""

    @pytest.fixture
    def mock_config(self):
        """Mock 配置"""
        return {
            "parser_model": "qwen-plus",
            "api_key": "test-api-key",
            "temperature": 0,
            "max_tokens": 1500,
            "timeout": 20,
        }

    @pytest.fixture
    def agent(self, mock_config):
        """创建 Agent 实例"""
        with patch("src.modules.sql_generation.subgraph.nodes.question_parsing.ChatTongyi"):
            return QuestionParsingAgent(mock_config)

    def test_parse_success(self, agent):
        """测试解析成功"""
        # Mock LLM 响应
        mock_response = MagicMock()
        mock_response.content = """{
            "rewritten_query": "查询2024年的销售额",
            "parse_result": {
                "keywords": ["销售额", "2024年"],
                "time": {"start": "2024-01-01", "end": "2024-12-31", "grain_inferred": "year", "is_full_period": true},
                "metric": {"text": "销售额", "is_aggregate_candidate": true},
                "dimensions": [{"text": "2024年", "role": "value", "evidence": "时间维度"}],
                "intent": {"task": "plain_agg", "topn": null},
                "signals": []
            }
        }"""
        agent._llm.invoke = MagicMock(return_value=mock_response)

        # 执行解析
        result = agent.parse("查询2024年的销售额")

        # 验证结果
        assert result["keywords"] == ["销售额", "2024年"]
        assert result["time"]["start"] == "2024-01-01"
        assert result["metric"]["text"] == "销售额"
        assert len(result["dimensions"]) == 1

    def test_parse_empty_query(self, agent):
        """测试空查询"""
        with pytest.raises(ValueError, match="问题内容为空"):
            agent.parse("")

    def test_parse_invalid_json(self, agent):
        """测试无效 JSON 响应"""
        # Mock LLM 返回无效 JSON
        mock_response = MagicMock()
        mock_response.content = "这不是有效的 JSON"
        agent._llm.invoke = MagicMock(return_value=mock_response)

        with pytest.raises(ValueError, match="解析 LLM 响应失败"):
            agent.parse("查询销售额")

    def test_parse_with_null_time(self, agent):
        """测试无时间约束的查询"""
        mock_response = MagicMock()
        mock_response.content = """{
            "rewritten_query": "查询销售额",
            "parse_result": {
                "keywords": ["销售额"],
                "time": null,
                "metric": {"text": "销售额", "is_aggregate_candidate": true},
                "dimensions": [],
                "intent": {"task": "plain_agg", "topn": null},
                "signals": []
            }
        }"""
        agent._llm.invoke = MagicMock(return_value=mock_response)

        result = agent.parse("查询销售额")

        assert result["time"] is None


class TestQuestionParsingNode:
    """测试 question_parsing_node 节点函数"""

    @pytest.fixture
    def mock_config(self):
        """Mock 配置加载"""
        with patch("src.modules.sql_generation.subgraph.nodes.question_parsing.load_subgraph_config") as mock:
            mock.return_value = {
                "question_parsing": {
                    "parser_model": "qwen-plus",
                    "api_key": "test-key",
                    "temperature": 0,
                    "max_tokens": 1500,
                    "timeout": 20,
                    "enable_internal_parser": True,
                    "fallback_to_empty": True,
                }
            }
            yield mock

    def test_use_external_parse_hints(self, mock_config):
        """测试使用外部传入的 parse_hints"""
        state = {
            "query_id": "test-001",
            "query": "查询销售额",
            "parse_hints": {
                "keywords": ["销售额"],
                "metric": {"text": "销售额"},
            },
        }

        result = question_parsing_node(state)

        assert result["parse_result"] == state["parse_hints"]
        assert result["parsing_source"] == "external"
        assert result["rewritten_query"] == state["query"]

    def test_internal_parsing_success(self, mock_config):
        """测试内部解析成功"""
        state = {
            "query_id": "test-002",
            "query": "查询销售额",
        }

        # Mock Agent
        with patch("src.modules.sql_generation.subgraph.nodes.question_parsing.QuestionParsingAgent") as mock_agent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.parse_with_rewrite.return_value = (
                "查询销售额",
                {
                    "keywords": ["销售额"],
                    "time": None,
                    "metric": {"text": "销售额"},
                    "dimensions": [],
                    "intent": {"task": "plain_agg"},
                    "signals": [],
                },
            )
            mock_agent.return_value = mock_agent_instance

            result = question_parsing_node(state)

            assert result["parse_result"]["keywords"] == ["销售额"]
            assert result["parsing_source"] == "llm"
            assert result["rewritten_query"] == "查询销售额"

    def test_internal_parser_disabled(self, mock_config):
        """测试禁用内部解析"""
        # 修改配置禁用解析
        mock_config.return_value = {
            "question_parsing": {
                "enable_internal_parser": False,
            }
        }

        state = {
            "query_id": "test-003",
            "query": "查询销售额",
        }

        result = question_parsing_node(state)

        assert result["parse_result"] == {}
        assert result["parsing_source"] == "disabled"
        assert result["rewritten_query"] == state["query"]

    def test_parsing_failure_with_fallback(self, mock_config):
        """测试解析失败时回退到空结构"""
        state = {
            "query_id": "test-004",
            "query": "查询销售额",
        }

        # Mock Agent 抛出异常
        with patch("src.modules.sql_generation.subgraph.nodes.question_parsing.QuestionParsingAgent") as mock_agent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.parse_with_rewrite.side_effect = Exception("LLM 调用失败")
            mock_agent.return_value = mock_agent_instance

            result = question_parsing_node(state)

            assert result["parse_result"] == {}
            assert result["parsing_source"] == "fallback"
            assert "parsing_error" in result
            assert result["rewritten_query"] == state["query"]

    def test_parsing_failure_without_fallback(self, mock_config):
        """测试解析失败时不回退（严格模式）"""
        # 修改配置禁用回退
        mock_config.return_value = {
            "question_parsing": {
                "parser_model": "qwen-plus",
                "api_key": "test-key",
                "enable_internal_parser": True,
                "fallback_to_empty": False,
            }
        }

        state = {
            "query_id": "test-005",
            "query": "查询销售额",
        }

        # Mock Agent 抛出异常
        with patch("src.modules.sql_generation.subgraph.nodes.question_parsing.QuestionParsingAgent") as mock_agent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.parse_with_rewrite.side_effect = Exception("LLM 调用失败")
            mock_agent.return_value = mock_agent_instance

            result = question_parsing_node(state)

            assert result["parse_result"] is None
            assert "error" in result
            assert result["error_type"] == "parsing_failed"
            assert result["rewritten_query"] == state["query"]


class TestDimensionTableOptimization:
    """测试维度表优化逻辑"""

    def test_should_use_dimension_only_with_time(self):
        """测试有时间约束时不使用维度表优化"""
        from src.tools.schema_retrieval.retriever import SchemaRetriever

        retriever = SchemaRetriever()

        parse_result = {"time": {"start": "2024-01-01", "end": "2024-12-31"}}
        fact_tables = []
        dim_tables = ["public.dim_store"]
        table_similarities = {}

        should_use, table = retriever._should_use_dimension_only(
            parse_result, fact_tables, dim_tables, table_similarities
        )

        assert should_use is False
        assert table is None

    def test_should_use_dimension_only_single_dim_no_time(self):
        """测试单维度表无时间约束时使用优化"""
        from src.tools.schema_retrieval.retriever import SchemaRetriever

        retriever = SchemaRetriever()

        parse_result = {}
        fact_tables = []
        dim_tables = ["public.dim_store"]
        table_similarities = {"public.dim_store": 0.9}

        should_use, table = retriever._should_use_dimension_only(
            parse_result, fact_tables, dim_tables, table_similarities
        )

        assert should_use is True
        assert table == "public.dim_store"

    def test_should_use_dimension_only_similarity_gap(self):
        """测试相似度差距判断"""
        from src.tools.schema_retrieval.retriever import SchemaRetriever

        retriever = SchemaRetriever({"schema_retrieval": {"similarity_gap_threshold": 0.05}})

        parse_result = {}
        fact_tables = ["public.fact_sales"]
        dim_tables = ["public.dim_store"]
        table_similarities = {
            "public.fact_sales": 0.70,
            "public.dim_store": 0.85,  # 差距 0.15 > 0.05
        }

        should_use, table = retriever._should_use_dimension_only(
            parse_result, fact_tables, dim_tables, table_similarities
        )

        assert should_use is True
        assert table == "public.dim_store"

    def test_select_best_dim_base_single_table(self):
        """测试单表时直接返回"""
        from src.tools.schema_retrieval.retriever import SchemaRetriever

        retriever = SchemaRetriever()

        dim_tables = ["public.dim_store"]
        table_similarities = {"public.dim_store": 0.9}

        result = retriever._select_best_dim_base(dim_tables, table_similarities)

        assert result == ["public.dim_store"]

    def test_select_best_dim_base_multiple_tables(self):
        """测试多表时按连通性选择"""
        from src.tools.schema_retrieval.retriever import SchemaRetriever
        from unittest.mock import MagicMock

        # Mock Neo4j 客户端
        with patch("src.tools.schema_retrieval.retriever.get_neo4j_client") as mock_neo4j:
            mock_client = MagicMock()
            mock_neo4j.return_value = mock_client

            # 模拟连通性：dim_store 可以连接到 dim_product，反之不行
            def mock_plan_join_paths(base_tables, target_tables, **kwargs):
                if base_tables[0] == "public.dim_store":
                    return [{"base": "public.dim_store", "edges": [{"src_table": "public.dim_store"}]}]
                else:
                    return []

            mock_client.plan_join_paths = mock_plan_join_paths

            retriever = SchemaRetriever()
            dim_tables = ["public.dim_store", "public.dim_product"]
            table_similarities = {
                "public.dim_store": 0.8,
                "public.dim_product": 0.7,
            }

            result = retriever._select_best_dim_base(dim_tables, table_similarities)

            # 应该选择连通性更好的 dim_store
            assert result == ["public.dim_store"]
