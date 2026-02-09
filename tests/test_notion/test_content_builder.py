import pandas as pd

from core.notion.content_builder import NotionContentBuilder


class TestAddHeading:
    def test_heading_1(self):
        builder = NotionContentBuilder()
        builder.add_heading("标题一", level=1)
        blocks = builder.build()
        assert len(blocks) == 1
        block = blocks[0]
        assert block["type"] == "heading_1"
        assert block["heading_1"]["rich_text"][0]["text"]["content"] == "标题一"

    def test_heading_2(self):
        builder = NotionContentBuilder()
        builder.add_heading("标题二", level=2)
        block = builder.build()[0]
        assert block["type"] == "heading_2"

    def test_heading_3(self):
        builder = NotionContentBuilder()
        builder.add_heading("标题三", level=3)
        block = builder.build()[0]
        assert block["type"] == "heading_3"

    def test_invalid_level_defaults_to_heading_3(self):
        builder = NotionContentBuilder()
        builder.add_heading("标题", level=99)
        block = builder.build()[0]
        assert block["type"] == "heading_3"

    def test_returns_self_for_chaining(self):
        builder = NotionContentBuilder()
        result = builder.add_heading("test")
        assert result is builder


class TestAddParagraph:
    def test_basic(self):
        builder = NotionContentBuilder()
        builder.add_paragraph("段落内容")
        block = builder.build()[0]
        assert block["type"] == "paragraph"
        assert block["paragraph"]["rich_text"][0]["text"]["content"] == "段落内容"

    def test_empty_text(self):
        builder = NotionContentBuilder()
        builder.add_paragraph("")
        block = builder.build()[0]
        assert block["paragraph"]["rich_text"][0]["text"]["content"] == ""

    def test_returns_self(self):
        builder = NotionContentBuilder()
        assert builder.add_paragraph("x") is builder


class TestAddTableFromDataframe:
    def test_with_column_header(self):
        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        builder = NotionContentBuilder()
        builder.add_table_from_dataframe(df, has_column_header=True)
        block = builder.build()[0]
        assert block["type"] == "table"
        table = block["table"]
        assert table["table_width"] == 2
        assert table["has_column_header"] is True
        # 1 header row + 2 data rows
        assert len(table["children"]) == 3
        # 验证表头
        header_cells = table["children"][0]["table_row"]["cells"]
        assert header_cells[0][0]["text"]["content"] == "A"
        assert header_cells[1][0]["text"]["content"] == "B"

    def test_without_column_header(self):
        df = pd.DataFrame({"X": [10]})
        builder = NotionContentBuilder()
        builder.add_table_from_dataframe(df, has_column_header=False)
        table = builder.build()[0]["table"]
        assert table["has_column_header"] is False
        # 无表头，只有 1 条数据行
        assert len(table["children"]) == 1

    def test_nan_value_shows_missing(self):
        df = pd.DataFrame({"col": [None]})
        builder = NotionContentBuilder()
        builder.add_table_from_dataframe(df)
        table = builder.build()[0]["table"]
        # 数据行（跳过表头行）
        data_row = table["children"][1]["table_row"]["cells"]
        assert data_row[0][0]["text"]["content"] == "缺失"

    def test_has_row_header(self):
        df = pd.DataFrame({"A": [1]})
        builder = NotionContentBuilder()
        builder.add_table_from_dataframe(df, has_row_header=True)
        table = builder.build()[0]["table"]
        assert table["has_row_header"] is True

    def test_returns_self(self):
        df = pd.DataFrame({"A": [1]})
        builder = NotionContentBuilder()
        assert builder.add_table_from_dataframe(df) is builder


class TestAddDivider:
    def test_basic(self):
        builder = NotionContentBuilder()
        builder.add_divider()
        block = builder.build()[0]
        assert block["type"] == "divider"
        assert block["divider"] == {}

    def test_returns_self(self):
        builder = NotionContentBuilder()
        assert builder.add_divider() is builder


class TestAddCallout:
    def test_default_icon(self):
        builder = NotionContentBuilder()
        builder.add_callout("提示内容")
        block = builder.build()[0]
        assert block["type"] == "callout"
        assert block["callout"]["rich_text"][0]["text"]["content"] == "提示内容"
        assert block["callout"]["icon"]["emoji"] == "\U0001f4a1"

    def test_custom_icon(self):
        builder = NotionContentBuilder()
        builder.add_callout("警告", icon="⚠️")
        block = builder.build()[0]
        assert block["callout"]["icon"]["emoji"] == "⚠️"

    def test_returns_self(self):
        builder = NotionContentBuilder()
        assert builder.add_callout("x") is builder


class TestBuild:
    def test_empty_builder(self):
        builder = NotionContentBuilder()
        assert builder.build() == []

    def test_chaining_multiple_blocks(self):
        builder = NotionContentBuilder()
        blocks = (
            builder.add_heading("H1", level=1)
            .add_paragraph("段落")
            .add_divider()
            .add_callout("提示")
            .build()
        )
        assert len(blocks) == 4
        assert blocks[0]["type"] == "heading_1"
        assert blocks[1]["type"] == "paragraph"
        assert blocks[2]["type"] == "divider"
        assert blocks[3]["type"] == "callout"

    def test_all_blocks_have_object_key(self):
        builder = NotionContentBuilder()
        builder.add_heading("h").add_paragraph("p").add_divider().add_callout("c")
        for block in builder.build():
            assert block["object"] == "block"
