"""Notion 页面内容构建器。

提供链式 API 构建 Notion Block 列表，支持标题、段落、表格、分隔线和 Callout 等块类型。
"""

from typing import Self

import pandas as pd

from .models import (
    Block,
    CalloutBlock,
    CalloutContent,
    DividerBlock,
    DividerContent,
    EmojiIcon,
    Heading1Block,
    Heading2Block,
    Heading3Block,
    ParagraphBlock,
    RichTextBlockContent,
    RichTextInput,
    TableBlock,
    TableContent,
    TableRowBlock,
    TableRowContent,
    TextContent,
)


def _rich_text(text: str) -> list[RichTextInput]:
    """构建单条 RichTextInput 列表。"""
    return [RichTextInput(text=TextContent(content=text))]


class NotionContentBuilder:
    """Notion 页面 content 构建器，支持链式调用。

    Example:
        >>> content = (
        ...     NotionContentBuilder()
        ...     .add_heading("标题", level=2)
        ...     .add_paragraph("正文内容")
        ...     .add_divider()
        ...     .build()
        ... )
    """

    def __init__(self) -> None:
        self.blocks: list[Block] = []

    def add_heading(self, text: str, level: int = 1) -> Self:
        """添加标题块。

        Args:
            text: 标题文本。
            level: 标题级别（1/2/3），对应 heading_1/2/3。
        """
        content = RichTextBlockContent(rich_text=_rich_text(text))
        block: Block
        if level == 1:
            block = Heading1Block(heading_1=content)
        elif level == 2:
            block = Heading2Block(heading_2=content)
        else:
            block = Heading3Block(heading_3=content)
        self.blocks.append(block)
        return self

    def add_paragraph(self, text: str) -> Self:
        """添加段落块。

        Args:
            text: 段落文本。
        """
        self.blocks.append(
            ParagraphBlock(paragraph=RichTextBlockContent(rich_text=_rich_text(text)))
        )
        return self

    def add_table_from_dataframe(
        self,
        df: pd.DataFrame,
        has_column_header: bool = True,
        has_row_header: bool = False,
    ) -> Self:
        """从 pandas DataFrame 构建表格块。

        Args:
            df: 数据源 DataFrame。
            has_column_header: 是否包含列标题行。
            has_row_header: 是否包含行标题列。
        """
        rows: list[TableRowBlock] = []

        # 列标题行
        if has_column_header:
            header_cells = [_rich_text(str(col)) for col in df.columns]
            rows.append(TableRowBlock(table_row=TableRowContent(cells=header_cells)))

        # 数据行
        for _, row in df.iterrows():
            cells = [
                _rich_text(str(val) if pd.notna(val) else "缺失")  # pyright: ignore[reportAny]
                for val in row  # pyright: ignore[reportAny]
            ]
            rows.append(TableRowBlock(table_row=TableRowContent(cells=cells)))

        self.blocks.append(
            TableBlock(
                table=TableContent(
                    table_width=len(df.columns),
                    has_column_header=has_column_header,
                    has_row_header=has_row_header,
                    children=rows,
                )
            )
        )
        return self

    def add_divider(self) -> Self:
        """添加分隔线块。"""
        self.blocks.append(DividerBlock(divider=DividerContent()))
        return self

    def add_callout(self, text: str, icon: str = "\U0001f4a1") -> Self:
        """添加 Callout 提示框块。

        Args:
            text: 提示内容文本。
            icon: Emoji 图标，默认为灯泡。
        """
        self.blocks.append(
            CalloutBlock(
                callout=CalloutContent(
                    rich_text=_rich_text(text),
                    icon=EmojiIcon(emoji=icon),
                )
            )
        )
        return self

    def build(self) -> list[Block]:
        """返回构建好的 Block 列表。"""
        return self.blocks
