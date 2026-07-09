from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import (
    SESSION_COOKIE_NAME,
    get_or_seed_admin_credentials,
    hash_password,
    login_required_or_redirect,
    verify_password,
)
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
def view_settings(request: Request, db: Session = Depends(get_db), cred_error: str | None = None, cred_success: int | None = None):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    settings = _get_or_create_settings(db)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "active_page": "settings",
            "settings": settings,
            "cred_error": cred_error,
            "cred_success": cred_success,
        },
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


@router.post("/settings/credentials")
def change_credentials(
    request: Request,
    current_password: str = Form(...),
    new_username: str = Form(...),
    new_password: str = Form(""),
    confirm_new_password: str = Form(""),
    db: Session = Depends(get_db),
):
    """Change the admin login username and/or password. Requires the current
    password to confirm it's really the logged-in admin making the change —
    an active session cookie alone isn't treated as sufficient for this."""
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    settings = get_or_seed_admin_credentials(db)

    if not verify_password(current_password, settings.admin_password_hash, settings.admin_password_salt):
        return RedirectResponse(url="/settings?cred_error=Current+password+is+incorrect.", status_code=302)

    new_username = new_username.strip()
    if not new_username:
        return RedirectResponse(url="/settings?cred_error=Username+cannot+be+empty.", status_code=302)

    if new_password:
        if len(new_password) < 6:
            return RedirectResponse(
                url="/settings?cred_error=New+password+must+be+at+least+6+characters.", status_code=302
            )
        if new_password != confirm_new_password:
            return RedirectResponse(url="/settings?cred_error=New+passwords+don't+match.", status_code=302)
        pw_hash, salt = hash_password(new_password)
        settings.admin_password_hash = pw_hash
        settings.admin_password_salt = salt

    settings.admin_username = new_username
    db.commit()

    # Changing the username/password invalidates the current session (it was
    # signed with the old username), so log the admin out and make them sign
    # back in with the new credentials — confirms the change actually took.
    response = RedirectResponse(url="/login?cred_success=1", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
