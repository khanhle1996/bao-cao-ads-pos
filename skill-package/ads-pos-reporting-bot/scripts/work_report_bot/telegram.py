from __future__ import annotations

from .config import Settings
from .http import post_form


def send_messages(settings: Settings, messages: list[str]) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    for message in messages:
        post_form(
            url,
            {
                "chat_id": settings.telegram_chat_id,
                "text": message,
                "disable_web_page_preview": "true",
                "parse_mode": "HTML",
            },
            timeout=settings.http_timeout_seconds,
        )
