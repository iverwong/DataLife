"""数据库 JSON 类型转换器单元测试。

测试 core/db/types.py 中定义的 4 个 TypeDecorator：
- JsonStringList: 处理 list[str]
- JsonChunkMetaList: 处理 list[ChunkMeta]
- JsonKeyDataItemList: 处理 list[KeyDataItem]
- JsonPydanticModel: 处理 ChunkSummaryOutput
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import sqlite

from core.data.models import ChunkMeta
from core.data.summary_models import ChunkSummaryOutput, KeyDataItem, PeriodInfo


class TestJsonChunkMetaList:
    """测试 JsonChunkMetaList TypeDecorator。"""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "input_value,expected",
        [
            # 正常值：包含 page_range 的 ChunkMeta 列表
            (
                [
                    ChunkMeta(title="第一章", level=1, page_range=(1, 5)),
                    ChunkMeta(title="第二章", level=1, page_range=(6, 10)),
                ],
                [
                    ChunkMeta(title="第一章", level=1, page_range=(1, 5)),
                    ChunkMeta(title="第二章", level=1, page_range=(6, 10)),
                ],
            ),
            # 单个元素
            (
                [ChunkMeta(title="第一节", level=2, page_range=(3, 4))],
                [ChunkMeta(title="第一节", level=2, page_range=(3, 4))],
            ),
            # 空列表
            ([], []),
            # None
            (None, None),
        ],
    )
    def test_round_trip(
        self, input_value: list[ChunkMeta] | None, expected: list[ChunkMeta] | None
    ) -> None:
        """测试 ChunkMeta 列表的 round-trip，验证 page_range 从 list 转 tuple。"""
        from core.db.types import json_dataclass

        type_adapter = json_dataclass(list[ChunkMeta])

        # process_bind_param: Python → DB
        db_value = type_adapter.process_bind_param(input_value, sqlite.dialect())
        # process_result_value: DB → Python
        result = type_adapter.process_result_value(db_value, sqlite.dialect())

        assert result == expected
        # 额外验证：page_range 应该是 tuple 类型
        if result is not None:
            for item in result:
                assert isinstance(item, ChunkMeta)
                assert isinstance(item.page_range, tuple)

    @pytest.mark.unit
    def test_page_range_type_conversion(self) -> None:
        """测试 page_range 从 list 到 tuple 的类型转换。"""
        from core.db.types import json_dataclass

        type_adapter = json_dataclass(list[ChunkMeta])

        # 输入：ChunkMeta 的 page_range 是 tuple
        input_data = [ChunkMeta(title="测试", level=1, page_range=(1, 10))]

        # DB 值应该是 JSON 字符串，page_range 在 JSON 中是 list
        db_value = type_adapter.process_bind_param(input_data, sqlite.dialect())
        # 从 DB 读取后，page_range 应该恢复为 tuple
        result = type_adapter.process_result_value(db_value, sqlite.dialect())

        assert result is not None
        assert len(result) == 1
        assert result[0].page_range == (1, 10)
        assert isinstance(result[0].page_range, tuple)


class TestJsonKeyDataItemList:
    """测试 JsonKeyDataItemList TypeDecorator。"""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "input_value,expected",
        [
            # 正常值：包含嵌套 PeriodInfo 的 KeyDataItem 列表
            (
                [
                    KeyDataItem(
                        label="营业收入",
                        value=1000000.0,
                        unit="元",
                        period=PeriodInfo(
                            start_date="2024-01-01",
                            end_date="2024-12-31",
                            description="2024年度",
                        ),
                        remark="经审计",
                    ),
                    KeyDataItem(
                        label="净利润",
                        value=500000.0,
                        unit="元",
                        period=PeriodInfo(
                            start_date="2024-01-01",
                            end_date="2024-12-31",
                            description="2024年度",
                        ),
                    ),
                ],
                [
                    KeyDataItem(
                        label="营业收入",
                        value=1000000.0,
                        unit="元",
                        period=PeriodInfo(
                            start_date="2024-01-01",
                            end_date="2024-12-31",
                            description="2024年度",
                        ),
                        remark="经审计",
                    ),
                    KeyDataItem(
                        label="净利润",
                        value=500000.0,
                        unit="元",
                        period=PeriodInfo(
                            start_date="2024-01-01",
                            end_date="2024-12-31",
                            description="2024年度",
                        ),
                    ),
                ],
            ),
            # 无 period 的 KeyDataItem
            (
                [KeyDataItem(label="测试", value=123.45, unit="个")],
                [KeyDataItem(label="测试", value=123.45, unit="个")],
            ),
            # 空列表
            ([], []),
            # None
            (None, None),
        ],
    )
    def test_round_trip(
        self, input_value: list[KeyDataItem] | None, expected: list[KeyDataItem] | None
    ) -> None:
        """测试 KeyDataItem 列表的 round-trip，验证嵌套 PeriodInfo。"""
        from core.db.types import json_pydantic

        type_adapter = json_pydantic(list[KeyDataItem])

        # process_bind_param: Python → DB
        db_value = type_adapter.process_bind_param(input_value, sqlite.dialect())
        # process_result_value: DB → Python
        result = type_adapter.process_result_value(db_value, sqlite.dialect())

        assert result == expected

    @pytest.mark.unit
    def test_nested_period_info(self) -> None:
        """测试嵌套 PeriodInfo 对象的序列化与反序列化。"""
        from core.db.types import json_pydantic

        type_adapter = json_pydantic(list[KeyDataItem])

        input_data = [
            KeyDataItem(
                label="营业收入",
                value=1000000.0,
                unit="元",
                period=PeriodInfo(
                    start_date="2024-01-01",
                    end_date="2024-12-31",
                    description="2024年度",
                ),
            )
        ]

        db_value = type_adapter.process_bind_param(input_data, sqlite.dialect())
        result = type_adapter.process_result_value(db_value, sqlite.dialect())

        assert result is not None
        assert len(result) == 1
        assert result[0].label == "营业收入"
        assert result[0].value == 1000000.0
        assert result[0].period is not None
        assert result[0].period.start_date == "2024-01-01"
        assert result[0].period.end_date == "2024-12-31"
        assert result[0].period.description == "2024年度"


class TestJsonPydanticModel:
    """测试 JsonPydanticModel TypeDecorator。"""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "input_value,expected",
        [
            # 正常值：完整的 ChunkSummaryOutput
            (
                ChunkSummaryOutput(
                    chapter_title="第三章 管理层讨论与分析",
                    chapter_path=["第三节 管理层讨论与分析", "3.1 主营业务"],
                    key_points=["要点1", "要点2", "要点3"],
                    detailed_summary="这是详细的摘要内容。",
                    key_data=[
                        KeyDataItem(
                            label="营业收入",
                            value=1000000.0,
                            unit="元",
                            period=PeriodInfo(
                                start_date="2024-01-01", description="2024年度"
                            ),
                        )
                    ],
                    context_brief="上下文提示信息。",
                ),
                ChunkSummaryOutput(
                    chapter_title="第三章 管理层讨论与分析",
                    chapter_path=["第三节 管理层讨论与分析", "3.1 主营业务"],
                    key_points=["要点1", "要点2", "要点3"],
                    detailed_summary="这是详细的摘要内容。",
                    key_data=[
                        KeyDataItem(
                            label="营业收入",
                            value=1000000.0,
                            unit="元",
                            period=PeriodInfo(
                                start_date="2024-01-01", description="2024年度"
                            ),
                        )
                    ],
                    context_brief="上下文提示信息。",
                ),
            ),
            # 无 key_data 的 ChunkSummaryOutput
            (
                ChunkSummaryOutput(
                    chapter_title="测试章节",
                    chapter_path=["第一章"],
                    key_points=[],
                    detailed_summary="摘要",
                    key_data=[],
                    context_brief="",
                ),
                ChunkSummaryOutput(
                    chapter_title="测试章节",
                    chapter_path=["第一章"],
                    key_points=[],
                    detailed_summary="摘要",
                    key_data=[],
                    context_brief="",
                ),
            ),
            # None
            (None, None),
        ],
    )
    def test_round_trip(
        self,
        input_value: ChunkSummaryOutput | None,
        expected: ChunkSummaryOutput | None,
    ) -> None:
        """测试 ChunkSummaryOutput 的 round-trip。"""
        from core.db.types import JsonPydanticModel

        type_adapter = JsonPydanticModel(ChunkSummaryOutput)

        # process_bind_param: Python → DB
        db_value = type_adapter.process_bind_param(input_value, sqlite.dialect())
        # process_result_value: DB → Python
        result = type_adapter.process_result_value(db_value, sqlite.dialect())

        assert result == expected

    @pytest.mark.unit
    def test_nested_key_data(self) -> None:
        """测试 ChunkSummaryOutput 中嵌套的 key_data 字段。"""
        from core.db.types import JsonPydanticModel

        type_adapter = JsonPydanticModel(ChunkSummaryOutput)

        input_data = ChunkSummaryOutput(
            chapter_title="测试",
            chapter_path=["第一章"],
            key_points=["要点1"],
            detailed_summary="摘要内容",
            key_data=[
                KeyDataItem(
                    label="营收",
                    value=500000.0,
                    unit="元",
                    period=PeriodInfo(description="2024年"),
                )
            ],
            context_brief="上下文",
        )

        db_value = type_adapter.process_bind_param(input_data, sqlite.dialect())
        result = type_adapter.process_result_value(db_value, sqlite.dialect())

        assert result is not None
        assert result.chapter_title == "测试"
        assert len(result.key_data) == 1
        assert result.key_data[0].label == "营收"
        assert result.key_data[0].value == 500000.0
