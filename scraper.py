"""Content fetching: website scraping + Telegram channel message buffering.

Every fetched item is a dict: {"text": str, "photo": str | None, "video": str | None}.
"photo"/"video" are either a direct HTTP URL (public web-preview scraping) or
a Telegram file_id (content pushed to the bot via a channel/group it's an
actual member of) — python-telegram-bot's send_photo/send_video accept both
forms transparently, so downstream code doesn't need to care which one it is.

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


def _extract_bg_url(style_attr: str | None) -> str | None:
    """Pull a URL out of an inline style="background-image: url('...')" attribute."""
    if not style_attr:
        return None
    match = re.search(r"background-image:\s*url\(['\"]?(.*?)['\"]?\)", style_attr)
    return match.group(1) if match else None


def fetch_website_content(url: str) -> dict | None:
    """Fetch a URL and return {"text": ..., "photo": og:image or None, "video": None}."""
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Grab the article's representative image (og:image) before stripping tags.
    photo_url = None
    og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if og_image and og_image.get("content"):
        photo_url = og_image["content"].strip()

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()

    # Prefer <article>, fall back to <main>, then <body>
    container = soup.find("article") or soup.find("main") or soup.body or soup

    text = container.get_text(separator="\n")
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = text[:MAX_ARTICLE_CHARS]

    if not text and not photo_url:
        return None

    return {"text": text, "photo": photo_url, "video": None}


def fetch_website_text(url: str) -> str | None:
    """Back-compat wrapper: text only, no media. Used by the rewrite-preview endpoint."""
    content = fetch_website_content(url)
    return content["text"] if content and content.get("text") else None


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
# TelegramMessageBuffer below instead, since they have no public preview page.
#
# Media note: the public preview page exposes a direct image URL for photo
# posts, and a direct video URL for *short* videos/animations. Larger videos
# only expose a thumbnail image in this preview (Telegram doesn't serve the
# full file outside the app for those), so those will come through with a
# thumbnail photo but no re-postable video — this is a platform limitation,
# not a bug here.
#
# Because this is a stateless page scrape (not a push subscription like
# channel_post updates), we track the highest Telegram message ID we've
# already seen per channel, in memory, so repeated fetches only return
# genuinely new posts instead of reposting the same recent messages forever.

_web_seen_lock = Lock()
_web_seen_ids: dict[str, int] = {}


def fetch_telegram_channel_web(channel_key: str) -> list[dict]:
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

    parsed: list[tuple[int, dict]] = []
    for post in posts:
        data_post = post.get("data-post", "")
        try:
            msg_id = int(data_post.split("/")[-1])
        except (ValueError, IndexError):
            continue

        text_div = post.find("div", class_="tgme_widget_message_text")
        text = text_div.get_text(separator="\n").strip() if text_div else ""

        photo_url = None
        photo_wrap = post.find("a", class_="tgme_widget_message_photo_wrap")
        if photo_wrap:
            photo_url = _extract_bg_url(photo_wrap.get("style"))

        video_url = None
        video_tag = post.find("video", class_="tgme_widget_message_video")
        if video_tag and video_tag.get("src"):
            video_url = video_tag["src"]
        elif not photo_url:
            # Larger videos only expose a thumbnail (no playable src) in this
            # preview — use that thumbnail as the photo so at least an image
            # goes out, rather than posting nothing visual at all.
            thumb = post.find("i", class_="tgme_widget_message_video_thumb")
            if thumb:
                photo_url = _extract_bg_url(thumb.get("style"))

        if not text and not photo_url and not video_url:
            continue  # nothing usable at all

        parsed.append((msg_id, {"text": text, "photo": photo_url, "video": video_url}))

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
            newest_id, newest_item = parsed[-1]
            logger.info(
                "Telegram channel '%s': first fetch, posting latest item (message %d) and baselining there.",
                key, newest_id,
            )
            return [newest_item]
        _web_seen_ids[key] = max_id_on_page

    new_items = [item for msg_id, item in parsed if msg_id > last_seen]
    return new_items


class TelegramMessageBuffer:
    """Thread-safe buffer of incoming channel/group messages, keyed by chat username/id."""

    def __init__(self):
        self._lock = Lock()
        self._messages: dict[str, list[dict]] = defaultdict(list)

    def add_message(self, channel_key: str, item: dict):
        if not item or not (item.get("text") or item.get("photo") or item.get("video")):
            return
        with self._lock:
            self._messages[_normalize_channel_key(channel_key)].append(item)

    def drain(self, channel_key: str) -> list[dict]:
        """Return and clear all buffered items for a given channel key."""
        key = _normalize_channel_key(channel_key)
        with self._lock:
            msgs = self._messages.get(key, [])
            self._messages[key] = []
            return msgs


# Singleton buffer shared between the Telegram bot listener and the scheduler.
telegram_buffer = TelegramMessageBuffer()


def fetch_source_content(source) -> list[dict]:
    """Return a list of {"text", "photo", "video"} dicts ready for filtering/rewriting."""
    if source.type == "website":
        content = fetch_website_content(source.url)
        return [content] if content else []
    elif source.type == "telegram_channel":
        # Try the public web preview first (works for any public channel,
        # even ones you don't administer), then also drain anything the bot
        # itself received directly (for private groups/channels the bot has
        # actually been added to, which have no public preview page).
        web_items = fetch_telegram_channel_web(source.url)
        buffered_items = telegram_buffer.drain(source.url)
        return web_items + buffered_items
    return []
