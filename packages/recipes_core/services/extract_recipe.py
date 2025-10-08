from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Protocol

from packages.recipes_core.deepseek_parsers import (
    RecipeExtraction,
    parse_llm_answer,
)
from packages.recipes_core.promts import SYSTEM_PROMPT_RU

logger = logging.getLogger(__name__)


class ChatClient(Protocol):
    def chat(
            self, messages: list[dict], *, temperature: float = 0.2,
            timeout: float | None = 30.0
    ) -> str: ...


class LLMRecipeExtractor:
    """
    Use-case: отправить два текста в LLM и распарсить ответ в доменную модель.
    """
    def __init__(self, chat_client: ChatClient):
        self.chat = chat_client

    def extract_sync(
            self, *, description: str, recognized_text: str
    ) -> RecipeExtraction:
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT_RU},
            {'role': 'user', 'content': f'Description: {description}'},
            {'role': 'user', 'content': f'Recognized Text: {recognized_text}'},
        ]
        logger.debug('LLM: отправка запроса...')
        raw = self.chat.chat(messages, temperature=0.0)
        logger.debug('LLM: ответ получен, длина=%s', len(raw))
        return parse_llm_answer(raw)

    async def extract(
            self, *, description: str, recognized_text: str
    ) -> RecipeExtraction:
        loop = asyncio.get_running_loop()
        fn = partial(
            self.extract_sync,
            description=description,
            recognized_text=recognized_text)
        return await loop.run_in_executor(None, fn)
