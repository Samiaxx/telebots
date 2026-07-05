"""Content fetching: website scraping + Telegram channel message buffering.

Note on Telegram sources: the Bot API does not allow a bot to pull the
historical message list of an arbitrary channel. Instead, the bot must be
added as a member/admin of the *source* channel, and Telegram will push new
posts to it as `channel_post` updates in real time. `TelegramMessageBuffer`
below collects those pushed messages per-channel-username so the scheduler
can "fetch" (drain) whatever has arrived since the last run, keeping the
cron-based scheduling model consistent for both source types.
"""
import logging
import re
from collections import defaultdict
from threading import Lock

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("telebot.scraper")

MAX_ARTICLE_CHARS = 6000
REQUEST_TIMEOUT = 20.0
USER_AGENT = "Mozilla/5.0 (compatible; ContentBot/1.0; +https://example.com/bot)"


def fetch_website_text(url: str) -> str | None:
    """Fetch a URL and return cleaned, human-readable text extracted from it."""
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()

    # Prefer <article>, fall back to <main>, then <body>
    container = soup.find("article") or soup.find("main") or soup.body or soup

    text = container.get_text(separator="\n")
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()

    if not text:
        return None

    return text[:MAX_ARTICLE_CHARS]


def _normalize_channel_key(raw: str) -> str:
    """Turn any of these into a bare, lowercase username for matching:
    'https://t.me/cointelegraph', 't.me/cointelegraph', '@cointelegraph',
    'cointelegraph' -> 'cointelegraph'. Numeric chat IDs (e.g. '-100123...')
    pass through unchanged aside from whitespace trimming.
    """
    key = raw.strip()
    for prefix in ("https://t.me/", "http://t.me/", "https://telegram.me/", "http://telegram.me/", "t.me/", "telegram.me/"):
        if key.lower().startswith(prefix):
            key = key[len(prefix):]
            break
    key = key.lstrip("@").rstrip("/")
    return key.lower()


# --- Public channel scraping (no bot membership required) ---
#
# For a public Telegram Channel the operator doesn't administer (e.g. a news
# outlet's official channel), the Bot API is a dead end — a bot can only see
# content in channels it has been added to, and you generally can't add your
# own bot to someone else's channel. Telegram does, however, expose a public,
# login-free HTML preview of any public channel's recent posts at
# https://t.me/s/<username> — this is the same technique many public
# aggregators use, and it works for *any* public channel regardless of bot
# membership. Private groups/channels the bot *is* a member of still use the
# TelegramMessageBuffer above instead, since they have no public preview page.
#
# Because this is a stateless page scrape (not a push subscription like
# channel_post updates), we track the highest Telegram message ID we've
# already seen per channel, in memory, so repeated fetches only return
# genuinely new posts instead of reposting the same recent messages forever.
# On first-ever fetch for a channel we record the current baseline without
# returning anything, matching the "only new content going forward" behavior
# used everywhere else in this app — so a source doesn't dump its whole
# recent backlog the moment it's turned on.

_web_seen_lock = Lock()
_web_seen_ids: dict[str, int] = {}


def fetch_telegram_channel_web(channel_key: str) -> list[str]:
    key = _normalize_channel_key(channel_key)
    url = f"https://t.me/s/{key}"

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch Telegram preview for '%s': %s", key, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    posts = soup.find_all("div", class_="tgme_widget_message", attrs={"data-post": True})

    parsed: list[tuple[int, str]] = []
    for post in posts:
        data_post = post.get("data-post", "")
        try:
            msg_id = int(data_post.split("/")[-1])
        except (ValueError, IndexError):
            continue

        text_div = post.find("div", class_="tgme_widget_message_text")
        if not text_div:
            continue  # media-only post with no caption text, skip
        text = text_div.get_text(separator="\n").strip()
        if not text:
            continue

        parsed.append((msg_id, text))

    if not parsed:
        return []

    parsed.sort(key=lambda pair: pair[0])
    max_id_on_page = parsed[-1][0]

    with _web_seen_lock:
        last_seen = _web_seen_ids.get(key)
        if last_seen is None:
            # First time seeing this channel: post just the single most
            # recent item now (so there's something real to verify delivery
            # with immediately) rather than the whole backlog, then baseline
            # from there for every run after this.
            _web_seen_ids[key] = max_id_on_page
            newest_id, newest_text = parsed[-1]
            logger.info(
                "Telegram channel '%s': first fetch, posting latest item (message %d) and baselining there.",
                key, newest_id,
            )
            return [newest_text]
        _web_seen_ids[key] = max_id_on_page

    new_items = [text for msg_id, text in parsed if msg_id > last_seen]
    return new_items


class TelegramMessageBuffer:
    """Thread-safe buffer of incoming channel posts, keyed by channel username/id."""

    def __init__(self):
        self._lock = Lock()
        self._messages: dict[str, list[str]] = defaultdict(list)

    def add_message(self, channel_key: str, text: str):
        if not text:
            return
        with self._lock:
            self._messages[_normalize_channel_key(channel_key)].append(text)

    def drain(self, channel_key: str) -> list[str]:
        """Return and clear all buffered messages for a given channel key."""
        key = _normalize_channel_key(channel_key)
        with self._lock:
            msgs = self._messages.get(key, [])
            self._messages[key] = []
            return msgs


# Singleton buffer shared between the Telegram bot listener and the scheduler.
telegram_buffer = TelegramMessageBuffer()


def fetch_source_content(source) -> list[str]:
    """Return a list of raw content strings ready for filtering/rewriting."""
    if source.type == "website":
        text = fetch_website_text(source.url)
        return [text] if text else []
    elif source.type == "telegram_channel":
        # Try the public web preview first (works for any public channel,
        # even ones you don't administer), then also drain anything the bot
        # itself received directly (for private groups/channels the bot has
        # actually been added to, which have no public preview page).
        web_items = fetch_telegram_channel_web(source.url)
        buffered_items = telegram_buffer.drain(source.url)
        return web_items + buffered_items
    return []
