"""Session-based auth using signed cookies (itsdangerous)."""
import os
import time

from dotenv import load_dotenv
from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SESSION_SECRET = os.getenv("SESSION_SECRET", "insecure-dev-secret-change-me")
SESSION_COOKIE_NAME = "telebot_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 12  # 12 hours

_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="telebot-auth")


def verify_credentials(username: str, password: str) -> bool:
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD


def create_session_token(username: str) -> str:
    return _serializer.dumps({"username": username, "ts": time.time()})


def read_session_token(token: str):
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
        return data
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    data = read_session_token(token)
    if not data:
        return None
    return data.get("username")


async def require_login(request: Request):
    """Dependency: redirect to /login if not authenticated.

    Returns either the username (str) or a RedirectResponse that the caller
    should return directly if authentication failed.
    """
    user = get_current_user(request)
    if not user:
        return None
    return user


def login_required_or_redirect(request: Request):
    """Use in routes: raises via return of RedirectResponse if not logged in."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return None
