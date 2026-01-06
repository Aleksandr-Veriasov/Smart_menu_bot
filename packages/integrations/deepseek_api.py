from __future__ import annotations

from collections.abc import Iterable

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from packages.common_settings.settings import settings


class DeepSeekClient:
    """Тонкая обёртка над OpenAI SDK с базовым URL DeepSeek."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
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
        timeout: float | None = 30.0,
    ) -> str:
        """Возвращает content первой choice как сырой текст."""
        # timeout прокидывается через transport опционально;
        # для простоты rely on SDK defaults
        responce = self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            temperature=temperature,
            stream=False,
        )
        return (responce.choices[0].message.content or "").strip()
