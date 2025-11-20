from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class InlineKB:
    def __init__(self) -> None:
        self._buttons: list[InlineKeyboardButton] = []

    def button(
        self,
        *,
        text: str,
        callback_data: str | None = None,
        url: str | None = None,
    ) -> InlineKB:
        self._buttons.append(
            InlineKeyboardButton(
                text=text, callback_data=callback_data, url=url
            )
        )
        return self

    def adjust(self, *widths: int) -> InlineKeyboardMarkup:
        rows, i = [], 0
        if not widths:
            widths = (1,)
        for w in widths:
            if w <= 0:
                continue
            rows.append(self._buttons[i : i + w])
            i += w
        # остаток — по одному в ряд
        while i < len(self._buttons):
            rows.append([self._buttons[i]])
            i += 1
        return InlineKeyboardMarkup(rows)
