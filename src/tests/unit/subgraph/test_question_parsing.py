"""问题解析节点单元测试"""

import pytest
from unittest.mock import MagicMock, patch

from src.modules.sql_generation.subgraph.nodes.question_parsing import (
    QuestionParsingAgent,
    _format_dependencies_for_parsing,
    question_parsing_node,
)


def _mock_get_llm_return(content: str = "", side_effect=None):
    """构造 get_llm 的 Mock 返回值（LLMWithMeta 结构）。"""
    mock_llm = MagicMock()
    if side_effect:
        mock_llm.invoke.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.content = content
        mock_llm.invoke.return_value = mock_response

    mock_meta = MagicMock()
    mock_meta.llm = mock_llm
    mock_meta.provider = "dashscope"
    mock_meta.model = "qwen-plus"
    return mock_meta


class TestQuestionParsingAgent:
    """测试 QuestionParsingAgent 类"""

    @pytest.fixture
    def mock_config(self):
        """Mock 配置"""
        return {
            "llm_profile": "qwen_plus",
            "temperature": 0,
            "max_tokens": 1500,
        }

    @pytest.fixture
    def agent(self, mock_config):
        """创建 Agent 实例"""
        with patch(
            "src.modules.sql_generation.subgraph.nodes.question_parsing.get_llm"
        ) as mock_get_llm:
            mock_get_llm.return_value = _mock_get_llm_return()
            return QuestionParsingAgent(mock_config)

    def test_parse_success(self, agent):
        """测试解析成功"""
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

        result = agent.parse("查询2024年的销售额")

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

    def test_parse_with_rewrite_includes_dependencies(self, agent):
        """测试 parse_with_rewrite 支持依赖结果上下文"""
        mock_response = MagicMock()
        mock_response.content = """{
            "rewritten_query": "查询服务区ID为 BJ001 的订单总额",
            "parse_result": {
                "keywords": ["服务区ID", "订单总额"],
                "time": null,
                "metric": {"text": "订单总额", "is_aggregate_candidate": true},
                "dimensions": [{"text": "BJ001", "role": "value", "evidence": "依赖结果"}],
                "intent": {"task": "plain_agg", "topn": null},
                "signals": []
            }
        }"""
        agent._llm.invoke = MagicMock(return_value=mock_response)

        dependencies_results = {
            "sq1": {
                "question": "查询北京门店",
                "execution_result": {
                    "columns": ["store_id", "store_name"],
                    "rows": [["BJ001", "北京朝阳店"]],
                },
            }
        }

        rewritten_query, parse_result = agent.parse_with_rewrite(
            "查询这些门店的订单总额",
            dependencies_results=dependencies_results,
        )

        assert rewritten_query == "查询服务区ID为 BJ001 的订单总额"
        assert parse_result["dimensions"][0]["text"] == "BJ001"
        messages = agent._llm.invoke.call_args.args[0]
        user_prompt = messages[1].content
        assert "Dependency results" in user_prompt
        assert "store_id" in user_prompt
        assert "BJ001" in user_prompt


class TestQuestionParsingNode:
    """测试 question_parsing_node 节点函数"""

    @pytest.fixture
    def mock_config(self):
        """Mock 配置加载"""
        with patch(
            "src.modules.sql_generation.subgraph.nodes.question_parsing.load_subgraph_config"
        ) as mock:
            mock.return_value = {
                "question_parsing": {
                    "llm_profile": "qwen_plus",
                    "temperature": 0,
                    "max_tokens": 1500,
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

        with patch(
            "src.modules.sql_generation.subgraph.nodes.question_parsing.QuestionParsingAgent"
        ) as mock_agent:
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
            assert mock_agent_instance.parse_with_rewrite.call_args.kwargs["dependencies_results"] == {}

    def test_internal_parsing_passes_dependencies_results(self, mock_config):
        """测试内部解析会透传 dependencies_results"""
        state = {
            "query_id": "test-002-deps",
            "query": "查询这些门店的订单总额",
            "dependencies_results": {
                "sq1": {
                    "question": "查询北京门店",
                    "execution_result": {
                        "columns": ["store_id"],
                        "rows": [["BJ001"]],
                    },
                }
            },
        }

        with patch(
            "src.modules.sql_generation.subgraph.nodes.question_parsing.QuestionParsingAgent"
        ) as mock_agent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.parse_with_rewrite.return_value = (
                "查询门店ID为 BJ001 的订单总额",
                {
                    "keywords": ["订单总额"],
                    "time": None,
                    "metric": {"text": "订单总额"},
                    "dimensions": [],
                    "intent": {"task": "plain_agg"},
                    "signals": [],
                },
            )
            mock_agent.return_value = mock_agent_instance

            result = question_parsing_node(state)

            assert result["rewritten_query"] == "查询门店ID为 BJ001 的订单总额"
            assert (
                mock_agent_instance.parse_with_rewrite.call_args.kwargs["dependencies_results"]
                == state["dependencies_results"]
            )

    def test_internal_parser_disabled(self, mock_config):
        """测试禁用内部解析"""
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

        with patch(
            "src.modules.sql_generation.subgraph.nodes.question_parsing.QuestionParsingAgent"
        ) as mock_agent:
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
        mock_config.return_value = {
            "question_parsing": {
                "llm_profile": "qwen_plus",
                "enable_internal_parser": True,
                "fallback_to_empty": False,
            }
        }

        state = {
            "query_id": "test-005",
            "query": "查询销售额",
        }

        with patch(
            "src.modules.sql_generation.subgraph.nodes.question_parsing.QuestionParsingAgent"
        ) as mock_agent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.parse_with_rewrite.side_effect = Exception("LLM 调用失败")
            mock_agent.return_value = mock_agent_instance

            result = question_parsing_node(state)

            assert result["parse_result"] is None
            assert "error" in result
            assert result["error_type"] == "parsing_failed"
            assert result["rewritten_query"] == state["query"]


class TestDependencyFormatter:
    """测试依赖结果格式化"""

    def test_format_dependencies_empty(self):
        """测试空依赖返回空字符串"""
        assert _format_dependencies_for_parsing({}) == ""
        assert _format_dependencies_for_parsing(None) == ""

    def test_format_dependencies_empty_rows(self):
        """测试空结果会明确标记为空"""
        text = _format_dependencies_for_parsing(
            {
                "sq1": {
                    "question": "查询门店",
                    "execution_result": {
                        "columns": ["store_id"],
                        "rows": [],
                    },
                }
            }
        )
        assert "result: empty" in text

    def test_format_dependencies_truncates_long_values(self):
        """测试长文本会被截断"""
        long_value = "x" * 200
        text = _format_dependencies_for_parsing(
            {
                "sq1": {
                    "question": long_value,
                    "execution_result": {
                        "columns": ["description"],
                        "rows": [[long_value]],
                    },
                }
            },
            max_cell_len=20,
        )
        assert "..." in text

    def test_format_dependencies_limits_rows(self):
        """测试最多只保留指定行数"""
        text = _format_dependencies_for_parsing(
            {
                "sq1": {
                    "question": "查询门店",
                    "execution_result": {
                        "columns": ["store_id"],
                        "rows": [["A"], ["B"], ["C"], ["D"]],
                    },
                }
            },
            max_rows=2,
        )
        assert "    - [A]" in text
        assert "    - [B]" in text
        assert "    - [C]" not in text
        assert "showing_first=2" in text


_RETRIEVER_MODULE = "src.tools.schema_retrieval.retriever"

_MINIMAL_RETRIEVER_CONFIG = {
    "schema_retrieval": {
        "table_category_mapping": {
            "fact": ["fact"],
            "dimension": ["dim", "dimension"],
            "bridge": ["bridge"],
        }
    }
}


def _make_retriever(extra_config: dict = None):
    """在 mock 外部客户端的上下文中创建 SchemaRetriever。"""
    from src.tools.schema_retrieval.retriever import SchemaRetriever

    config = _MINIMAL_RETRIEVER_CONFIG.copy()
    if extra_config:
        sr = config["schema_retrieval"].copy()
        sr.update(extra_config.get("schema_retrieval", {}))
        config["schema_retrieval"] = sr

    with (
        patch(f"{_RETRIEVER_MODULE}.get_pg_client"),
        patch(f"{_RETRIEVER_MODULE}.get_neo4j_client"),
        patch(f"{_RETRIEVER_MODULE}.get_embedding_client"),
        patch(f"{_RETRIEVER_MODULE}.create_vector_search_adapter"),
    ):
        return SchemaRetriever(config)


class TestDimensionTableOptimization:
    """测试维度表优化逻辑"""

    def test_should_use_dimension_only_with_time(self):
        """测试有时间约束时不使用维度表优化"""
        retriever = _make_retriever()

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
        retriever = _make_retriever()

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
        retriever = _make_retriever(
            {"schema_retrieval": {"similarity_gap_threshold": 0.05}}
        )

        parse_result = {}
        fact_tables = ["public.fact_sales"]
        dim_tables = ["public.dim_store"]
        table_similarities = {
            "public.fact_sales": 0.70,
            "public.dim_store": 0.85,
        }

        should_use, table = retriever._should_use_dimension_only(
            parse_result, fact_tables, dim_tables, table_similarities
        )

        assert should_use is True
        assert table == "public.dim_store"

    def test_select_best_dim_base_single_table(self):
        """测试单表时直接返回"""
        retriever = _make_retriever()

        dim_tables = ["public.dim_store"]
        table_similarities = {"public.dim_store": 0.9}

        result = retriever._select_best_dim_base(dim_tables, table_similarities)

        assert result == ["public.dim_store"]

    def test_select_best_dim_base_multiple_tables(self):
        """测试多表时按连通性选择"""
        retriever = _make_retriever()

        def mock_plan_join_paths(base_tables, target_tables, **kwargs):
            if base_tables[0] == "public.dim_store":
                return [{"base": "public.dim_store", "edges": [{"src_table": "public.dim_store"}]}]
            else:
                return []

        retriever.neo4j_client.plan_join_paths = mock_plan_join_paths

        dim_tables = ["public.dim_store", "public.dim_product"]
        table_similarities = {
            "public.dim_store": 0.8,
            "public.dim_product": 0.7,
        }

        result = retriever._select_best_dim_base(dim_tables, table_similarities)

        assert result == ["public.dim_store"]
