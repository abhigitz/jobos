"""Telegram Bot API integration service."""
import httpx
from app.config import get_settings

settings = get_settings()


async def send_telegram_message(chat_id: int, text: str) -> bool:
    """
    Send a message to Telegram. Auto-splits if >4096 chars.
    
    Args:
        chat_id: Telegram chat ID
        text: Message text to send
        
    Returns:
        True if successful, False otherwise
    """
    MAX_LEN = 4096
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    
    try:
        if len(text) <= MAX_LEN:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                )
                return response.status_code == 200
        else:
            # Split at paragraph boundaries
            chunks = []
            current = ""
            for para in text.split("\n\n"):
                if len(current) + len(para) + 2 > MAX_LEN:
                    if current.strip():
                        chunks.append(current.strip())
                    current = para
                else:
                    if current:
                        current += "\n\n" + para
                    else:
                        current = para
            
            if current.strip():
                chunks.append(current.strip())
            
            async with httpx.AsyncClient() as client:
                for chunk in chunks:
                    response = await client.post(
                        url,
                        json={
                            "chat_id": chat_id,
                            "text": chunk,
                            "parse_mode": "Markdown",
                        },
                    )
                    if response.status_code != 200:
                        return False
                return True
    except Exception as e:
        import logging
        logging.error(f"Failed to send Telegram message: {e}")
        return False


async def register_webhook(webhook_url: str, secret_token: str) -> bool:
    """
    Register webhook with Telegram Bot API.
    
    Args:
        webhook_url: Full URL where Telegram should send updates
        secret_token: Secret token for webhook verification
        
    Returns:
        True if successful, False otherwise
    """
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/setWebhook"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={
                    "url": webhook_url,
                    "secret_token": secret_token,
                    "allowed_updates": ["message"],
                },
            )
            return response.status_code == 200
    except Exception as e:
        import logging
        logging.error(f"Failed to register Telegram webhook: {e}")
        return False
