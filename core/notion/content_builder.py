class NotionContentBuilder:
    """Notion页面content构建器"""

    def __init__(self):
        self.blocks = []

    def add_heading(self, text, level=1):
        """
        添加标题
        level: 1, 2, 或 3 (对应#, ##, ###)
        """
        heading_types = {1: "heading_1", 2: "heading_2", 3: "heading_3"}
        heading_type = heading_types.get(level, "heading_3")

        self.blocks.append(
            {
                "object": "block",
                "type": heading_type,
                heading_type: {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            }
        )
        return self

    def add_paragraph(self, text):
        """添加段落"""
        self.blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            }
        )
        return self

    def add_table_from_dataframe(
        self, df, has_column_header=True, has_row_header=False
    ):
        """从DataFrame添加表格"""
        import pandas as pd

        rows = []

        # 列标题行
        if has_column_header:
            header_cells = [
                [{"type": "text", "text": {"content": str(col)}}] for col in df.columns
            ]
            rows.append({"type": "table_row", "table_row": {"cells": header_cells}})

        # 数据行
        for _, row in df.iterrows():
            cells = [
                [
                    {
                        "type": "text",
                        "text": {"content": str(val) if pd.notna(val) else "缺失"},
                    }
                ]
                for val in row
            ]
            rows.append({"type": "table_row", "table_row": {"cells": cells}})

        self.blocks.append(
            {
                "object": "block",
                "type": "table",
                "table": {
                    "table_width": len(df.columns),
                    "has_column_header": has_column_header,
                    "has_row_header": has_row_header,
                    "children": rows,
                },
            }
        )
        return self

    def add_divider(self):
        """添加分隔线"""
        self.blocks.append({"object": "block", "type": "divider", "divider": {}})
        return self

    def add_callout(self, text, icon="💡"):
        """添加callout"""
        self.blocks.append(
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": text}}],
                    "icon": {"type": "emoji", "emoji": icon},
                },
            }
        )
        return self

    def build(self) -> list[dict]:
        """返回构建好的blocks数组"""
        return self.blocks
