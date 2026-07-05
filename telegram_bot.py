"""Telegram bot: listens for channel posts from sources, and posts to destination channels."""
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from scraper import telegram_buffer

load_dotenv()

logger = logging.getLogger("telebot.bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

_application: Application | None = None


def _buffer_message(chat, text: str):
    if not text:
        return
    keys = set()
    if chat.username:
        keys.add(chat.username)
    keys.add(str(chat.id))
    for key in keys:
        telegram_buffer.add_message(key, text)
    logger.info("Received a message from chat '%s' (type: %s, id: %s) — buffered under keys: %s", chat.title or chat.username or chat.id, chat.type, chat.id, keys)


async def _on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buffer incoming posts from any Telegram Channel the bot is a member of."""
    msg = update.channel_post
    if not msg:
        return
    _buffer_message(msg.chat, msg.text or msg.caption or "")


async def _on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buffer incoming messages from any Telegram Group/Supergroup the bot is
    a member of. Groups send regular `message` updates, not `channel_post` —
    this is a different update type from Channels, so it needs its own
    handler even though both are valid "source" types in the admin panel."""
    msg = update.message
    if not msg:
        return
    _buffer_message(msg.chat, msg.text or msg.caption or "")


def build_application() -> Application:
    global _application
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in the environment.")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, _on_channel_post))
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & (filters.TEXT | filters.CAPTION), _on_group_message)
    )
    _application = application
    return application


def get_application() -> Application | None:
    return _application


def get_bot_username() -> str | None:
    """Returns the connected bot's @username, or None if not yet initialized."""
    if _application is None or _application.bot is None:
        return None
    return _application.bot.username


async def send_message(chat_id: str, text: str) -> tuple[bool, str | None]:
    """Send `text` to a destination channel. Returns (success, error_message)."""
    if _application is None:
        return False, "Telegram application is not initialized."
    try:
        await _application.bot.send_message(chat_id=_normalize_chat_id(chat_id), text=text)
        return True, None
    except TelegramError as exc:
        logger.error("Failed to send message to %s: %s", chat_id, exc)
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - never let a send failure crash the pipeline
        logger.error("Unexpected error sending message to %s: %s", chat_id, exc)
        return False, str(exc)


def _normalize_chat_id(chat_id: str):
    """Accepts '@handle', 'handle', a full t.me URL, or a numeric chat ID
    (e.g. '-1001234567890') and returns whatever python-telegram-bot expects."""
    from scraper import _normalize_channel_key

    raw = chat_id.strip()
    if raw.lstrip("-").isdigit():
        return int(raw)

    normalized = _normalize_channel_key(raw)
    if normalized.lstrip("-").isdigit():
        return int(normalized)
    return f"@{normalized}"
