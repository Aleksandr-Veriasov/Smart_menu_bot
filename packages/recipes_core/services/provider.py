"""Фабрика LLMRecipeExtractor с кешированием singleton-экземпляра.

get_default_extractor() возвращает один и тот же экземпляр на весь процесс (lru_cache).
_DeepSeekChatAdapter адаптирует DeepSeekClient к протоколу ChatClient.
"""

from collections.abc import Iterable
from functools import lru_cache
from typing import cast

from openai.types.chat import ChatCompletionMessageParam

from packages.integrations.deepseek_api import DeepSeekClient

from .extract_recipe import ChatClient, LLMRecipeExtractor


class _DeepSeekChatAdapter(ChatClient):
    def __init__(self, client: DeepSeekClient) -> None:
        self._client = client

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        timeout: float | None = 30.0,
    ) -> str:
        typed_messages = cast(Iterable[ChatCompletionMessageParam], messages)
        return self._client.chat(
            typed_messages,
            temperature=temperature,
            timeout=timeout,
        )


@lru_cache(maxsize=1)
def get_default_extractor() -> LLMRecipeExtractor:
    """Возвращает singleton LLMRecipeExtractor с DeepSeek-провайдером."""
    client = DeepSeekClient()
    adapter = _DeepSeekChatAdapter(client)
    return LLMRecipeExtractor(chat_client=adapter)
