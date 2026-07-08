"""Telegram bot: listens for channel/group posts from sources, and posts to
destination channels — including photos and videos, not just text."""
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

# Telegram caption limit for photo/video messages (plain text messages allow
# up to 4096, but a caption attached to media is capped much lower).
MAX_CAPTION_LEN = 1024

_application: Application | None = None


def _buffer_message(chat, msg):
    """Buffer any usable content from an incoming message: text/caption plus
    a photo or video file_id if present. Using the Telegram file_id (rather
    than downloading the file ourselves) lets us re-send it later via the
    Bot API directly — the most reliable way to repost media from a chat the
    bot is actually a member of."""
    text = msg.text or msg.caption or ""
    photo_file_id = msg.photo[-1].file_id if msg.photo else None
    video_file_id = msg.video.file_id if msg.video else None

    if not text and not photo_file_id and not video_file_id:
        return

    item = {"text": text, "photo": photo_file_id, "video": video_file_id}

    keys = set()
    if chat.username:
        keys.add(chat.username)
    keys.add(str(chat.id))
    for key in keys:
        telegram_buffer.add_message(key, item)
    logger.info(
        "Received a message from chat '%s' (type: %s, id: %s, has_photo: %s, has_video: %s) — buffered under keys: %s",
        chat.title or chat.username or chat.id, chat.type, chat.id, bool(photo_file_id), bool(video_file_id), keys,
    )


async def _on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buffer incoming posts from any Telegram Channel the bot is a member of."""
    msg = update.channel_post
    if not msg:
        return
    _buffer_message(msg.chat, msg)


async def _on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buffer incoming messages from any Telegram Group/Supergroup the bot is
    a member of. Groups send regular `message` updates, not `channel_post` —
    this is a different update type from Channels, so it needs its own
    handler even though both are valid "source" types in the admin panel."""
    msg = update.message
    if not msg:
        return
    _buffer_message(msg.chat, msg)


def build_application() -> Application:
    global _application
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in the environment.")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, _on_channel_post))
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & (filters.TEXT | filters.CAPTION | filters.PHOTO | filters.VIDEO),
            _on_group_message,
        )
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


def _truncate_caption(text: str | None) -> str | None:
    if not text:
        return None
    if len(text) <= MAX_CAPTION_LEN:
        return text
    return text[: MAX_CAPTION_LEN - 1].rstrip() + "…"


async def send_message(chat_id: str, text: str) -> tuple[bool, str | None]:
    """Send a plain text message. Returns (success, error_message)."""
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


async def send_photo(chat_id: str, photo: str, caption: str | None = None) -> tuple[bool, str | None]:
    """Send a photo (URL or Telegram file_id) with an optional caption."""
    if _application is None:
        return False, "Telegram application is not initialized."
    try:
        await _application.bot.send_photo(
            chat_id=_normalize_chat_id(chat_id), photo=photo, caption=_truncate_caption(caption)
        )
        return True, None
    except TelegramError as exc:
        logger.error("Failed to send photo to %s: %s", chat_id, exc)
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error sending photo to %s: %s", chat_id, exc)
        return False, str(exc)


async def send_video(chat_id: str, video: str, caption: str | None = None) -> tuple[bool, str | None]:
    """Send a video (URL or Telegram file_id) with an optional caption."""
    if _application is None:
        return False, "Telegram application is not initialized."
    try:
        await _application.bot.send_video(
            chat_id=_normalize_chat_id(chat_id), video=video, caption=_truncate_caption(caption)
        )
        return True, None
    except TelegramError as exc:
        logger.error("Failed to send video to %s: %s", chat_id, exc)
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error sending video to %s: %s", chat_id, exc)
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
