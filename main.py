# 测试 announcement_analyst 智能体的简单脚本

import asyncio

from dotenv import load_dotenv

_ = load_dotenv()

import logfire  # noqa: E402
from langchain_anthropic import ChatAnthropic  # noqa: E402

from core.agents.announcement_analyst import (  # noqa: E402
    build_announcement_analyst_graph,  # noqa: E402
)
from core.logs import setup_logging  # noqa: E402


async def main() -> None:
    setup_logging()
    logfire.info("开始测试 announcement_analyst 智能体")

    model = ChatAnthropic(model="MiniMax-M2.7", max_retries=9, timeout=None)  # pyright: ignore[reportCallIssue]

    graph = build_announcement_analyst_graph(model)

    question = "阳光电源港股上市进展如何了"
    logfire.info(f"问题: {question}")

    result = await graph.ainvoke({"question": question})  # pyright: ignore[reportArgumentType, reportUnknownMemberType]
    logfire.info(f"最终结果 keys: {result.keys()}")
    logfire.info(f"迭代次数: {result.get('iteration')}")
    logfire.info(f"笔记内容:\n{result.get('notes')}")


if __name__ == "__main__":
    asyncio.run(main())
