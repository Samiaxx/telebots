from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import login_required_or_redirect
from database import get_db
from models import BotSettings

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _get_or_create_settings(db: Session) -> BotSettings:
    settings = db.query(BotSettings).first()
    if not settings:
        settings = BotSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("/settings")
def view_settings(request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    settings = _get_or_create_settings(db)
    return templates.TemplateResponse(
        "settings.html", {"request": request, "active_page": "settings", "settings": settings}
    )


@router.post("/settings")
def update_settings(
    request: Request,
    bot_enabled: bool = Form(False),
    rewrite_enabled: bool = Form(False),
    default_rewrite_style: str = Form("light"),
    gemini_model: str = Form("gemini-flash-latest"),
    max_posts_per_hour: int = Form(20),
    include_images: bool = Form(False),
    db: Session = Depends(get_db),
):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    settings = _get_or_create_settings(db)
    settings.bot_enabled = bot_enabled
    settings.rewrite_enabled = rewrite_enabled
    settings.default_rewrite_style = default_rewrite_style
    settings.gemini_model = gemini_model
    settings.max_posts_per_hour = max_posts_per_hour
    settings.include_images = include_images
    db.commit()

    return RedirectResponse(url="/settings", status_code=302)
