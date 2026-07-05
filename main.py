"""Entry point: starts FastAPI, the Telegram bot (polling), and APScheduler together."""
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import Base, engine
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

    # Start the Telegram bot in polling mode so it can receive channel_post
    # updates from source channels and be ready to send to destination channels.
    application = build_application()
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=["channel_post", "message"])
    logger.info("Telegram bot started (polling).")

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
