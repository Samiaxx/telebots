"""Entry point: starts FastAPI, the Telegram bot (polling), and APScheduler together."""
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from auth import get_or_seed_admin_credentials
from database import Base, SessionLocal, engine
from models import BotSettings
from routes import channels, dashboard, login, posts, schedules, settings, sources
from scheduler import start_scheduler, stop_scheduler
from telegram_bot import build_application

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("telebot.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables if they don't exist yet (alembic is the source of truth for
    # schema changes going forward; this is a safety net for first run).
    Base.metadata.create_all(bind=engine)

    # Seed admin login credentials and the Gemini API key into the database
    # from .env the very first time this runs. After this, both are stored
    # (hashed, for the password) in the database and changeable from the
    # Settings page, without needing shell access or a restart.
    db = SessionLocal()
    try:
        get_or_seed_admin_credentials(db)
        bot_settings = db.query(BotSettings).first()
        if not bot_settings:
            bot_settings = BotSettings()
            db.add(bot_settings)
            db.commit()
            db.refresh(bot_settings)
        if not bot_settings.gemini_api_key:
            bot_settings.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
            db.commit()
    finally:
        db.close()

    # Start the Telegram bot in polling mode so it can receive channel_post
    # updates from source channels and be ready to send to destination channels.
    application = build_application()
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=["channel_post", "message"])
    logger.info("Telegram bot started (polling).")

    live_username = application.bot.username
    expected_username = (os.getenv("TELEGRAM_BOT_USERNAME") or "").strip().lstrip("@")
    if expected_username and live_username and expected_username.lower() != live_username.lower():
        logger.warning(
            "TELEGRAM_BOT_USERNAME in .env says '@%s' but the token actually connects as '@%s'. "
            "If this is unexpected, double-check TELEGRAM_BOT_TOKEN — you may have the wrong bot's token.",
            expected_username, live_username,
        )
    elif live_username:
        logger.info("Connected as @%s.", live_username)

    # Start the cron scheduler that drives the fetch -> rewrite -> post pipeline.
    start_scheduler()
    logger.info("Scheduler started.")

    try:
        yield
    finally:
        stop_scheduler()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Shut down cleanly.")


app = FastAPI(title="Telegram Content Automation Bot", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(login.router)
app.include_router(dashboard.router)
app.include_router(sources.router)
app.include_router(channels.router)
app.include_router(schedules.router)
app.include_router(posts.router)
app.include_router(settings.router)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
