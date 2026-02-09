import os

from notion_client import AsyncClient

notion = AsyncClient(auth=os.getenv("NOTION_TOKEN"))
