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
    """构建单条 RichTextInput 列表"""
    return [RichTextInput(text=TextContent(content=text))]


class NotionContentBuilder:
    """Notion页面content构建器"""

    def __init__(self):
        self.blocks: list[Block] = []

    def add_heading(self, text: str, level: int = 1) -> Self:
        """添加标题

        Args:
            text: 标题文本
            level: 1, 2, 或 3 (对应#, ##, ###)
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
        """添加段落"""
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
        """从 DataFrame 构建表格 block"""
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
        """添加分隔线"""
        self.blocks.append(DividerBlock(divider=DividerContent()))
        return self

    def add_callout(self, text: str, icon: str = "💡") -> Self:
        """添加callout"""
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
        """返回构建好的blocks数组"""
        return self.blocks
