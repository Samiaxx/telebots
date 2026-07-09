from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session_token,
    get_current_user,
    verify_credentials,
)
from database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login")
def login_form(request: Request, cred_success: int | None = None):
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    message = "Your login credentials were updated. Please sign in with your new username/password." if cred_success else None
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "message": message})


@router.post("/login")
async def login_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")

    if not verify_credentials(db, username, password):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid username or password."}, status_code=401
        )

    token = create_session_token(username)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
