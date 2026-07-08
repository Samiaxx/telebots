"""APScheduler setup: cron jobs per Schedule row, running the fetch -> filter ->
rewrite -> post -> log pipeline."""
import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import SessionLocal
from gemini import rewrite_content
from models import BotSettings, Channel, Post, Schedule, Source
from scraper import fetch_source_content
from telegram_bot import send_message, send_photo, send_video

logger = logging.getLogger("telebot.scheduler")

scheduler = AsyncIOScheduler()

JOB_PREFIX = "schedule_"


def _get_settings(db) -> BotSettings:
    settings = db.query(BotSettings).first()
    if not settings:
        settings = BotSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _posts_in_last_hour(db) -> int:
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    return db.query(Post).filter(Post.created_at >= one_hour_ago).count()


def _matches_keywords(content: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    lowered = content.lower()
    return any(kw.lower() in lowered for kw in keywords)


async def run_schedule_job(schedule_id: int):
    """The actual pipeline: fetch -> filter -> rewrite -> post -> log, for one schedule."""
    db = SessionLocal()
    try:
        settings = _get_settings(db)
        if not settings.bot_enabled:
            logger.info("Bot is disabled globally; skipping schedule %s", schedule_id)
            return

        schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
        if not schedule or not schedule.is_active:
            logger.info("Schedule %s: not found or inactive, skipping.", schedule_id)
            return

        source: Source = schedule.source
        channel: Channel = schedule.channel
        if not source or not channel or not source.is_active:
            logger.info("Schedule %s: source or channel missing/inactive, skipping.", schedule_id)
            return

        if _posts_in_last_hour(db) >= settings.max_posts_per_hour:
            logger.info("Schedule %s: hourly post limit reached, skipping.", schedule_id)
            return

        logger.info("Schedule %s: fetching from source '%s' (%s)...", schedule_id, source.name, source.type)

        source.last_fetched_at = datetime.utcnow()
        try:
            # fetch_source_content does blocking network I/O (httpx, BeautifulSoup
            # parsing) — run it off the event loop so it doesn't stall the
            # Telegram bot's own polling or the web server while it runs.
            contents = await asyncio.to_thread(fetch_source_content, source)
            source.last_error = None
        except Exception as exc:  # noqa: BLE001
            source.last_error = str(exc)[:500]
            db.commit()
            logger.error("Schedule %s: fetch raised an exception: %s", schedule_id, exc)
            return
        db.commit()

        logger.info("Schedule %s: fetched %d item(s) from '%s'.", schedule_id, len(contents), source.name)

        if not contents:
            logger.info(
                "Schedule %s: nothing to post. For a website source, this usually means the page returned no "
                "extractable text. For a Telegram source, it means the bot hasn't received any new channel posts "
                "yet since the last run — the bot must be added to that channel first, and Telegram only pushes "
                "*new* posts made after it joins, not history.",
                schedule_id,
            )
            return

        keywords = source.keyword_list()

        for i, item in enumerate(contents):
            raw_text = item.get("text") or ""
            photo = item.get("photo")
            video = item.get("video")

            if raw_text:
                if not _matches_keywords(raw_text, keywords):
                    logger.info(
                        "Schedule %s: item %d skipped — didn't match keywords %s.", schedule_id, i, keywords
                    )
                    continue
            elif keywords:
                # A caption-less media item can't be judged against a topic
                # filter — skip rather than guess when keywords are set.
                logger.info(
                    "Schedule %s: item %d skipped — media-only post with no caption to match keywords %s.",
                    schedule_id, i, keywords,
                )
                continue

            final_text = raw_text
            if raw_text and settings.rewrite_enabled and source.rewrite_style != "none":
                model_name = settings.gemini_model
                logger.info("Schedule %s: item %d sent to Gemini (%s)...", schedule_id, i, model_name)
                rewritten = await asyncio.to_thread(
                    rewrite_content,
                    content=raw_text,
                    language=source.language,
                    keywords=keywords,
                    style=source.rewrite_style,
                    model_name=model_name,
                    persona=source.persona,
                )
                if rewritten is None:
                    logger.info(
                        "Schedule %s: item %d — Gemini returned SKIP (didn't match the topic) or the call failed. "
                        "Check for a Gemini error above this line, or that GEMINI_API_KEY is set correctly.",
                        schedule_id, i,
                    )
                    continue
                final_text = rewritten
                logger.info("Schedule %s: item %d rewritten successfully.", schedule_id, i)

            include_images = settings.include_images
            logger.info(
                "Schedule %s: item %d sending to channel '%s' (photo=%s, video=%s, include_images=%s)...",
                schedule_id, i, channel.name, bool(photo), bool(video), include_images,
            )

            if include_images and video:
                success, error = await send_video(channel.telegram_id, video, final_text)
            elif include_images and photo:
                success, error = await send_photo(channel.telegram_id, photo, final_text)
            else:
                if not final_text:
                    # Media-only item but images are switched off in Settings
                    # (or there's no media at all) — nothing sendable, skip.
                    logger.info(
                        "Schedule %s: item %d skipped — no text to send and images are disabled in Settings.",
                        schedule_id, i,
                    )
                    continue
                success, error = await send_message(channel.telegram_id, final_text)

            if success:
                logger.info("Schedule %s: item %d posted successfully.", schedule_id, i)
            else:
                logger.error("Schedule %s: item %d failed to send: %s", schedule_id, i, error)

            post = Post(
                source_id=source.id,
                channel_id=channel.id,
                original_text=raw_text or None,
                rewritten_text=(final_text if final_text != raw_text else None) or None,
                status="success" if success else "failed",
                error_message=error,
            )
            db.add(post)
            db.commit()

            if _posts_in_last_hour(db) >= settings.max_posts_per_hour:
                break
    except Exception:
        logger.exception("Unhandled error running schedule %s", schedule_id)
    finally:
        db.close()


def _job_id(schedule_id: int) -> str:
    return f"{JOB_PREFIX}{schedule_id}"


def add_or_update_job(schedule: Schedule):
    job_id = _job_id(schedule.id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    if not schedule.is_active:
        return
    try:
        trigger = CronTrigger.from_crontab(schedule.cron_expression)
    except ValueError as exc:
        logger.error("Invalid cron expression '%s' for schedule %s: %s", schedule.cron_expression, schedule.id, exc)
        return
    scheduler.add_job(run_schedule_job, trigger=trigger, args=[schedule.id], id=job_id, replace_existing=True)


def remove_job(schedule_id: int):
    job_id = _job_id(schedule_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def load_all_jobs():
    """Called at startup to (re)register every active schedule as a cron job."""
    db = SessionLocal()
    try:
        schedules = db.query(Schedule).all()
        for schedule in schedules:
            add_or_update_job(schedule)
    finally:
        db.close()


def trigger_all_now() -> int:
    """Manual trigger: run every active schedule immediately.

    We hand this off to APScheduler (via add_job with no trigger, which runs
    once as soon as possible) rather than asyncio.create_task, because this
    function is called from a synchronous FastAPI route running in a worker
    thread — there is no running event loop in that thread to attach a task
    to. APScheduler's AsyncIOScheduler is already bound to the real event
    loop, so handing it a one-off job is thread-safe and actually runs.

    Returns the number of schedules queued, so the caller can show real
    feedback instead of a silent redirect.
    """
    db = SessionLocal()
    try:
        schedules = db.query(Schedule).filter(Schedule.is_active == True).all()  # noqa: E712
        for schedule in schedules:
            scheduler.add_job(run_schedule_job, args=[schedule.id], id=f"manual_{schedule.id}_{datetime.utcnow().timestamp()}")
        return len(schedules)
    finally:
        db.close()


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
    load_all_jobs()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
