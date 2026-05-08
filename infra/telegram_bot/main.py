"""Telegram bot: forwards user messages to the Datacyber brain ``POST /agent/chat`` (same as the UI)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s %(levelname)s [telegram-bot] %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO"),
)
log = logging.getLogger(__name__)

BRAIN_URL = (os.environ.get("BRAIN_BASE_URL") or "http://brain:8000").rstrip("/")
LOCALE_RAW = (os.environ.get("TELEGRAM_REPLY_LOCALE") or "en").strip().lower()
LOCALE = "es" if LOCALE_RAW.startswith("es") else "en"
TIMEOUT = float(os.environ.get("BRAIN_HTTP_TIMEOUT_SECONDS") or "600")
_TELEGRAM_CHUNK = 4000  # stay under 4096 limit with margin


def _allowed_user_ids() -> set[int] | None:
    raw = (os.environ.get("TELEGRAM_ALLOWED_USER_IDS") or "").strip()
    if not raw:
        return None
    out: set[int] = set()
    for part in raw.split(","):
        p = part.strip()
        if p.isdigit():
            out.add(int(p))
    return out or None


def _split_telegram(text: str, limit: int = _TELEGRAM_CHUNK) -> list[str]:
    t = (text or "").strip()
    if not t:
        return ["(empty reply)"]
    if len(t) <= limit:
        return [t]
    parts: list[str] = []
    rest = t
    while rest:
        if len(rest) <= limit:
            parts.append(rest)
            break
        chunk = rest[:limit]
        break_at = max(chunk.rfind("\n\n"), chunk.rfind("\n"), chunk.rfind(" "))
        if break_at < limit // 2:
            break_at = limit
        parts.append(rest[:break_at].rstrip())
        rest = rest[break_at:].lstrip()
    return parts


async def _brain_chat(message: str) -> str:
    url = f"{BRAIN_URL}/agent/chat"
    payload: dict[str, Any] = {"message": message, "locale": LOCALE}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code >= 400:
            detail: str
            try:
                body = r.json()
                detail = str(body.get("detail", body))
            except Exception:
                detail = r.text or r.reason_phrase
            raise RuntimeError(f"brain HTTP {r.status_code}: {detail[:2500]}")
        data = r.json()
        return str(data.get("reply", ""))


def _unauthorized_message() -> str:
    return (
        "This bot is restricted. Ask the admin to add your Telegram user ID to "
        "TELEGRAM_ALLOWED_USER_IDS."
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    allowed = _allowed_user_ids()
    if allowed is not None and update.effective_user.id not in allowed:
        await update.message.reply_text(_unauthorized_message())
        return
    await update.message.reply_text(
        "Send a message and I will forward it to the Datacyber warehouse agent "
        "(same engine as the web UI). Ask about DuckDB, datasets, SQL, or pipelines.\n\n"
        f"Reply locale: {LOCALE} (set TELEGRAM_REPLY_LOCALE=en or es in the bot env)."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    u = update.effective_user
    await update.message.reply_text(
        f"Your Telegram user id: {u.id}\n"
        f"Username: @{u.username or '—'}\n\n"
        "Share the id with the admin if access is restricted."
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None or not update.message.text:
        return
    allowed = _allowed_user_ids()
    if allowed is not None and update.effective_user.id not in allowed:
        await update.message.reply_text(_unauthorized_message())
        return

    text = update.message.text.strip()
    if not text:
        return

    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        reply = await _brain_chat(text)
    except Exception as exc:
        log.exception("brain chat failed")
        reply = f"Request failed: {type(exc).__name__}: {exc}"

    for i, chunk in enumerate(_split_telegram(reply)):
        await update.message.reply_text(chunk)
        if i == 0 and len(reply) > _TELEGRAM_CHUNK:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


def main() -> None:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    log.info("brain=%s locale=%s timeout=%ss", BRAIN_URL, LOCALE, TIMEOUT)
    if _allowed_user_ids() is not None:
        log.info("allowlist enabled for %s user(s)", len(_allowed_user_ids() or ()))

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
