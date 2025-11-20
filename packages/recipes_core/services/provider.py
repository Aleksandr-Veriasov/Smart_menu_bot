from __future__ import annotations

from typing import Iterable, cast

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


def get_default_extractor() -> LLMRecipeExtractor:
    client = DeepSeekClient()
    adapter = _DeepSeekChatAdapter(client)
    return LLMRecipeExtractor(chat_client=adapter)
