"""Use-case слой для извлечения рецепта из текста через LLM.

LLMRecipeExtractor принимает любой ChatClient (Protocol), что позволяет подменять
провайдера в тестах без реальных API-вызовов.
"""

import asyncio
import logging
from functools import partial
from typing import Protocol

from packages.recipes_core.deepseek_parsers import (
    RecipeExtraction,
    parse_llm_answer,
    parse_structured_answer,
)
from packages.recipes_core.promts import SYSTEM_PROMPT_STRUCTURED

logger = logging.getLogger(__name__)


class ChatClient(Protocol):
    """Протокол синхронного LLM-клиента. Реализуется адаптером конкретного провайдера."""

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        timeout: float | None = 30.0,
    ) -> str: ...


class LLMRecipeExtractor:
    """
    Use-case: отправить два текста в LLM и распарсить ответ в доменную модель.
    """

    def __init__(self, chat_client: ChatClient):
        self.chat = chat_client

    def extract_sync(self, *, description: str, recognized_text: str) -> RecipeExtraction:
        """Синхронный вызов LLM. Блокирует поток — используй extract() в async-контексте."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_STRUCTURED},
            {"role": "user", "content": f"Description: {description}"},
            {"role": "user", "content": f"Recognized Text: {recognized_text}"},
        ]
        logger.debug("LLM: отправка запроса...")
        raw = self.chat.chat(messages, temperature=0.0)
        logger.debug("LLM: ответ получен, длина=%s", len(raw))

        result = parse_structured_answer(raw)
        if result is None:
            logger.warning("LLM: не удалось распарсить JSON, фолбэк на легаси-парсер")
            result = parse_llm_answer(raw)
        return result

    async def extract(self, *, description: str, recognized_text: str) -> RecipeExtraction:
        """Асинхронная обёртка над extract_sync() через run_in_executor."""
        loop = asyncio.get_running_loop()
        fn = partial(
            self.extract_sync,
            description=description,
            recognized_text=recognized_text,
        )
        return await loop.run_in_executor(None, fn)
