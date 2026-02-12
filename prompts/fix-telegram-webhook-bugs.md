# Fix Dead Telegram Webhook (Two Bugs) — Claude Code Prompt

You are working on **JobOS**, a FastAPI backend deployed on Railway. The Telegram bot webhook is broken due to two bugs. Make minimal, targeted edits — do NOT rewrite entire files.

---

## Files you MUST read before editing

| File | What to look for |
|---|---|
| `app/config.py` | `app_url: str = ""` (line 12) — the domain/URL field. `telegram_webhook_secret: str = ""` (line 11) — the secret field. |
| `app/main.py` | Lines 19-23 — lifespan webhook registration. `webhook_url = f"{settings.app_url}/api/telegram/webhook"` (line 21). |
| `app/routers/telegram.py` | Line 38 — secret validation: `if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret`. Lines 291-308 — manual `/register-webhook` endpoint with same URL construction at line 302. |
| `app/services/telegram_service.py` | `register_webhook()` (line 71) — correctly passes `secret_token` to Telegram API at line 90. This file needs NO changes. |

---

## Bug 1: Webhook URL missing `https://`

**Root cause:** `app/main.py` line 21 builds the webhook URL as:
```python
webhook_url = f"{settings.app_url}/api/telegram/webhook"
```
On Railway, the `APP_URL` env var is set to just the domain: `jobos-production-99c6.up.railway.app` (no protocol). The resulting URL `jobos-production-99c6.up.railway.app/api/telegram/webhook` has no `https://`, so Telegram rejects it.

The same bug exists in `app/routers/telegram.py` line 302 (manual registration endpoint).

**Fix locations:** Two places construct the webhook URL — both must be fixed.

---

## Bug 2: Webhook secret mismatch

**Root cause:** The code is structurally correct — `register_webhook()` passes `secret_token` and the handler checks `x_telegram_bot_api_secret_token`. Both use `settings.telegram_webhook_secret`. However, if someone manually re-registered the webhook via curl WITHOUT the `secret_token` param, Telegram stops sending the header, causing 403 rejections.

**Fix:** The startup registration already passes the secret correctly. The real fix is Bug 1 — once the URL is correct, every deploy will re-register with the correct secret. Add defensive logging so we can verify.

---

## Task A — Create a helper to normalize the webhook URL

### File: `app/main.py`

**Find** (lines 19-23):
```python
    settings = get_settings()
    if settings.telegram_bot_token and settings.app_url:
        webhook_url = f"{settings.app_url}/api/telegram/webhook"
        await register_webhook(webhook_url, settings.telegram_webhook_secret)
        logger.info(f"Telegram webhook registered: {webhook_url}")
```

**Replace with:**
```python
    settings = get_settings()
    if settings.telegram_bot_token and settings.app_url:
        base = settings.app_url.rstrip("/")
        if not base.startswith("https://") and not base.startswith("http://"):
            base = f"https://{base}"
        webhook_url = f"{base}/api/telegram/webhook"
        success = await register_webhook(webhook_url, settings.telegram_webhook_secret)
        logger.info(
            f"Telegram webhook {'registered' if success else 'FAILED'}: {webhook_url}"
        )
```

**Why:** Strips trailing slash, prepends `https://` if missing, and logs success/failure.

---

## Task B — Fix the manual registration endpoint

### File: `app/routers/telegram.py`

**Find** (line 302):
```python
    webhook_url = f"{settings.app_url}/api/telegram/webhook"
```

**Replace with:**
```python
    base = settings.app_url.rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://"):
        base = f"https://{base}"
    webhook_url = f"{base}/api/telegram/webhook"
```

This is the same normalization logic applied to the `/register-webhook` endpoint so it stays consistent.

---

## Task C — Add webhook secret logging (defensive)

### File: `app/services/telegram_service.py`

**Find** (lines 82-94):
```python
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
```

**Replace with:**
```python
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/setWebhook"
    
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "url": webhook_url,
                "secret_token": secret_token,
                "allowed_updates": ["message"],
            }
            response = await client.post(url, json=payload)
            import logging
            _logger = logging.getLogger(__name__)
            _logger.info(
                f"setWebhook response: status={response.status_code}, "
                f"url={webhook_url}, secret_present={bool(secret_token)}, "
                f"body={response.text}"
            )
            return response.status_code == 200
```

**Why:** Logs the full Telegram API response so we can see in Railway logs whether the webhook was accepted, and confirms the secret was included.

---

## DO NOT CHANGE

- `app/services/telegram_service.py` — EXCEPT for the logging addition in Task C. Do not change the `send_telegram_message()` function, the `register_webhook()` signature, or the payload structure.
- `app/routers/telegram.py` — EXCEPT for the URL construction in the `/register-webhook` endpoint (Task B). Do NOT touch the webhook handler, command handlers, or secret validation logic at line 38.
- `app/main.py` — EXCEPT for the webhook registration block in lifespan (Task A). Do NOT touch middleware, router imports, or `app` creation.
- `app/config.py` — No changes needed. The `app_url` and `telegram_webhook_secret` fields are fine as-is.
- Do NOT touch scheduler code, AI service, models, schemas, or any other files.

---

## Execution Order

1. **A** — Fix `app/main.py` webhook URL construction
2. **B** — Fix `app/routers/telegram.py` manual endpoint URL construction
3. **C** — Add logging to `app/services/telegram_service.py`

All three are independent — order doesn't matter technically, but A is the critical fix.

---

## Testing Verification

After deploying the fix, verify the webhook is correctly registered:

```bash
# 1. Check webhook info from Telegram
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo" | python3 -m json.tool
```

**Expected response should show:**
- `"url": "https://jobos-production-99c6.up.railway.app/api/telegram/webhook"` — starts with `https://`
- `"has_custom_certificate": false`
- `"pending_update_count"` — should decrease after sending a test message
- `"last_error_message"` — should be empty or absent

```bash
# 2. Check Railway logs for the startup message
# Should see: "Telegram webhook registered: https://jobos-production-99c6.up.railway.app/api/telegram/webhook"
# Should see: "setWebhook response: status=200, url=https://..., secret_present=True, body=..."
```

```bash
# 3. Send a test message to the bot in Telegram
# Type: /help
# Should get the help menu back instead of silence/403
```

---

## SUMMARY OF EDITS

| File | Lines | Change |
|---|---|---|
| `app/main.py` | 19-23 | Normalize `app_url` → prepend `https://` if missing, log success/failure |
| `app/routers/telegram.py` | 302 | Same URL normalization in manual `/register-webhook` endpoint |
| `app/services/telegram_service.py` | 82-94 | Add response logging to `setWebhook` call |
