# Telegram Content Automation Bot

Scrapes websites and Telegram channels, rewrites content with Google Gemini,
and auto-posts to destination Telegram channels on a schedule — all managed
from a web admin panel.

## Stack
FastAPI + Uvicorn, PostgreSQL + SQLAlchemy + Alembic, python-telegram-bot,
httpx + BeautifulSoup4, APScheduler, Google Gemini, Jinja2 templates.

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a Postgres database**, then copy the env template and fill it in:
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   - `ADMIN_USERNAME` / `ADMIN_PASSWORD` — admin panel login
   - `TELEGRAM_BOT_TOKEN` — from @BotFather
   - `GEMINI_API_KEY` — from Google AI Studio
   - `SESSION_SECRET` — any long random string
   - `DATABASE_URL` — e.g. `postgresql+psycopg://user:password@localhost:5432/telebot`

3. **Run migrations**
   ```bash
   alembic upgrade head
   ```

4. **Start the app** (web server + Telegram bot + scheduler, all in one process)
   ```bash
   python main.py
   ```
   Visit `http://localhost:5000` and log in with your admin credentials.

## Important: how Telegram source channels work

The Telegram Bot API does not let a bot pull the historical message list of
an arbitrary channel. Instead:

- **For source channels you want to scrape**, add your bot as a member (admin
  is safest) of that channel. Telegram will then push every new post to the
  bot in real time as a `channel_post` update, which this app buffers per
  channel and "fetches" on the next scheduled run.
- **For destination channels**, add your bot as an **admin with post
  permissions** — the bot needs that to publish messages there.

If you need to pull full historical backlogs from channels the bot cannot
join (e.g. very large public channels where you only want to observe), that
requires a full MTProto user-account client (e.g. Telethon/Pyrogram) instead
of the Bot API, which is a materially different integration and is not
included here.

## Adding a source
- **Website**: type = `website`, URL = the page/article-listing URL to scrape.
- **Telegram channel**: type = `telegram_channel`, URL field = the channel's
  `@username` (must match how you want it buffered).
- **Voice / persona**: describe who's "writing" for this source (e.g. *"a
  crypto trader who's been in the space since 2017 — casual, a bit skeptical
  of hype"*). This is fed directly into the Gemini prompt so the rewritten
  text sounds like a real person who follows that specific beat, not a
  generic summary. Use the **Preview rewrite** button on the source form to
  see a live sample before turning the source on.

## Scheduling
Pick a plain-language frequency (every 15 min, hourly, daily at a set time,
etc.) — Relay converts it to the correct cron expression for you. An
"advanced" toggle is available if you need a custom cron expression.

## Project structure
See the file tree in this repo — `main.py` is the entry point, `routes/`
holds each admin panel page, `scheduler.py` drives the fetch → filter →
rewrite → post pipeline, `gemini.py` handles AI rewriting, `scraper.py`
handles website scraping + the Telegram message buffer, and `telegram_bot.py`
wraps python-telegram-bot for both listening and posting.

## Notes on scraping
Only scrape sites you have the right to reuse content from, and check each
site's terms of service / robots.txt before adding it as a source — this is
your responsibility as the operator of the bot.
