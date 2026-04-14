"""图结构测试。

覆盖范围：图编译成功、包含预期节点。
外部依赖 mock：BaseChatModel。
"""

from unittest.mock import MagicMock

from core.agents.announcement_analyst import build_announcement_analyst_graph

class TestGraphStructure:
    """build_announcement_analyst_graph 图结构测试。

    验证图能成功编译，且包含设计文档定义的 4 个节点。
    """

    def _build_graph(self):
        """构建测试用图，mock LLM。"""
        mock_model = MagicMock()
        mock_model.bind_tools = MagicMock(return_value=mock_model)
        return build_announcement_analyst_graph(mock_model)

    def test_graph_compiles_successfully(self):
        """Given: mock BaseChatModel
        When: 调用 build_announcement_analyst_graph
        Then: 返回非 None 的编译图"""
        graph = self._build_graph()
        assert graph is not None

    def test_graph_has_four_nodes(self):
        """Given: mock BaseChatModel
        When: 调用 build_announcement_analyst_graph 并获取图结构
        Then: 节点集合包含 plan, research, evaluate, synthesize"""
        graph = self._build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        expected = {"plan", "research", "evaluate", "synthesize"}
        assert expected.issubset(node_names)

    def test_bind_tools_called(self):
        """Given: mock BaseChatModel
        When: 调用 build_announcement_analyst_graph
        Then: model.bind_tools 被调用一次（绑定公告工具）"""
        mock_model = MagicMock()
        mock_model.bind_tools = MagicMock(return_value=mock_model)
        _ = build_announcement_analyst_graph(mock_model)
        mock_model.bind_tools.assert_called_once()
