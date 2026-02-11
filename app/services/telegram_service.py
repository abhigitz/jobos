import logging

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BOT_TOKEN = settings.telegram_bot_token
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def _send_single(chat_id: int, text: str) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
            if response.status_code != 200:
                logger.error(f"Telegram send failed: {response.text}")
                return False
            return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"Telegram error: {e}")
        return False


async def send_message(chat_id: int, text: str) -> bool:
    if len(text) <= 4096:
        return await _send_single(chat_id, text)

    chunks: list[str] = []
    while text:
        if len(text) <= 4096:
            chunks.append(text)
            break
        split_point = text.rfind("\n\n", 0, 4096)
        if split_point == -1:
            split_point = text.rfind("\n", 0, 4096)
        if split_point == -1:
            split_point = 4096
        chunks.append(text[:split_point])
        text = text[split_point:].lstrip()

    success = True
    for chunk in chunks:
        if not await _send_single(chat_id, chunk):
            success = False
    return success


async def register_webhook(app_url: str, secret: str) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/setWebhook",
                json={
                    "url": f"{app_url}/api/telegram/webhook",
                    "secret_token": secret,
                },
            )
            logger.info("Webhook registration: %s", response.json())
            return response.status_code == 200
    except Exception as e:  # noqa: BLE001
        logger.error(f"Webhook registration failed: {e}")
        return False
