from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import login_required_or_redirect
from database import get_db
from models import BotSettings, Post

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
def dashboard(request: Request, triggered: int | None = None, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    posts_today = db.query(func.count(Post.id)).filter(Post.created_at >= today_start).scalar() or 0
    posts_week = db.query(func.count(Post.id)).filter(Post.created_at >= week_start).scalar() or 0
    posts_all_time = db.query(func.count(Post.id)).scalar() or 0

    recent_posts = db.query(Post).order_by(Post.created_at.desc()).limit(15).all()

    settings = db.query(BotSettings).first()
    bot_enabled = settings.bot_enabled if settings else True

    from telegram_bot import get_bot_username

    bot_username = get_bot_username()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "active_page": "dashboard",
            "bot_enabled": bot_enabled,
            "bot_username": bot_username,
            "triggered": triggered,
            "posts_today": posts_today,
            "posts_week": posts_week,
            "posts_all_time": posts_all_time,
            "recent_posts": recent_posts,
        },
    )


@router.post("/dashboard/trigger")
def manual_trigger(request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    from scheduler import trigger_all_now

    count = trigger_all_now()
    return RedirectResponse(url=f"/?triggered={count}", status_code=302)
