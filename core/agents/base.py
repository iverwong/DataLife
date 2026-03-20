"""Agent 抽象基类和运行器。

管理 PydanticAI Agent 的创建、配置和 HTTP 客户端生命周期。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.settings import ModelSettings

T_IN = TypeVar("T_IN")
T_OUT = TypeVar("T_OUT")


@dataclass(frozen=True)
class AgentConfig(ABC, Generic[T_IN, T_OUT]):
    """Agent 配置抽象基类。

    子类实现具体的 instructions、output_type、
    以及可选的 output_validator 注册。
    """

    model: str = "deepseek-chat"
    temperature: float = 0.3
    max_tokens: int = 4096
    retries: int = 3
    timeout: int = 60

    @abstractmethod
    def get_output_type(self) -> type[T_OUT]:
        """返回 Agent 的 output_type。"""
        ...

    @abstractmethod
    def get_instructions(self) -> str:
        """返回 Agent instructions 字符串。"""
        ...

    def get_deps_type(self) -> type[T_IN] | None:
        """返回 Agent 的 deps_type，默认为 None。"""
        return None

    def configure_agent(self, agent: Agent[T_IN, T_OUT]) -> None:  # pyright: ignore[reportUnusedParameter]
        """子类可重写以注册 output_validator 等装饰器。"""
        ...

    def get_model_settings(self) -> ModelSettings:
        """构建 ModelSettings。"""
        return ModelSettings(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


class AgentRunner(Generic[T_IN, T_OUT]):
    """Agent 运行器，管理 HTTP 客户端生命周期。

    用法：
        async with AgentRunner(config, api_key) as runner:
            result = await runner.run(prompt, deps=deps)
    """

    _config: AgentConfig[T_IN, T_OUT]
    _api_key: str
    _http_client: httpx.AsyncClient | None
    _agent: Agent[T_IN, T_OUT] | None

    def __init__(self, config: AgentConfig[T_IN, T_OUT], api_key: str) -> None:
        self._config = config
        self._api_key = api_key
        self._http_client = None
        self._agent = None

    async def __aenter__(self) -> "AgentRunner[T_IN, T_OUT]":
        self._http_client = httpx.AsyncClient(timeout=self._config.timeout)
        model_instance = OpenAIChatModel(
            self._config.model,
            provider=DeepSeekProvider(
                api_key=self._api_key,
                http_client=self._http_client,
            ),
        )
        agent_kwargs: dict[str, Any] = {  # pyright: ignore[reportExplicitAny]
            "output_type": self._config.get_output_type(),
            "retries": self._config.retries,
            "model_settings": self._config.get_model_settings(),
        }

        instructions = self._config.get_instructions()
        if instructions:
            agent_kwargs["instructions"] = instructions

        deps_type = self._config.get_deps_type()
        if deps_type is not None:
            agent_kwargs["deps_type"] = deps_type

        self._agent = Agent(model_instance, **agent_kwargs)  # pyright: ignore[reportAny]

        # 子类自定义配置（如 @agent.output_validator）
        self._config.configure_agent(self._agent)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        self._agent = None

    async def run(
        self,
        prompt: str,
        *,
        deps: T_IN = None,
        model_settings: ModelSettings | None = None,
    ) -> T_OUT:
        """运行 Agent 并返回结构化输出。"""
        assert self._agent is not None, "AgentRunner 未进入上下文"
        result = await self._agent.run(prompt, deps=deps, model_settings=model_settings)
        return result.output
