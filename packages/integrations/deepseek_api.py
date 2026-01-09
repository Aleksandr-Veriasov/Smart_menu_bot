from __future__ import annotations

from collections.abc import Iterable

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from packages.common_settings.settings import settings


class DeepSeekClient:
    """Тонкая обёртка над OpenAI SDK с базовым URL DeepSeek."""

    def __init__(self):
        self.model = settings.deepseek.model
        self.client = OpenAI(
            api_key=settings.deepseek.api_key.get_secret_value(),
            base_url=settings.deepseek.base_url,
        )

    def chat(
        self,
        messages: Iterable[ChatCompletionMessageParam],
        *,
        temperature: float = 0.2,
        timeout: float | None = None,
    ) -> str:
        """Возвращает content первой choice как сырой текст."""
        responce = self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            temperature=temperature,
            stream=False,
            **({"timeout": timeout} if timeout is not None else {}),
        )
        return (responce.choices[0].message.content or "").strip()
