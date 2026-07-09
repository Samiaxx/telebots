"""Session-based auth using signed cookies (itsdangerous), with admin
credentials stored in the database (hashed) so they can be changed from the
Settings page instead of requiring shell access to edit .env."""
import hashlib
import os
import secrets
import time

from dotenv import load_dotenv
from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

load_dotenv()

# Used only to seed the database the very first time the app runs — after
# that, the DB-stored (hashed) credentials are the source of truth and can
# be changed from Settings without touching .env or restarting anything.
ENV_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ENV_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

SESSION_SECRET = os.getenv("SESSION_SECRET", "insecure-dev-secret-change-me")
SESSION_COOKIE_NAME = "telebot_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 12  # 12 hours

_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="telebot-auth")

PBKDF2_ITERATIONS = 100_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Returns (hash_hex, salt_hex). Generates a new random salt if none given."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    if not stored_hash or not salt:
        return False
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, stored_hash)


def get_or_seed_admin_credentials(db):
    """Returns the BotSettings row, seeding admin_username/password_hash from
    .env the very first time this runs (so existing deployments keep working
    without any manual migration step)."""
    from models import BotSettings

    settings = db.query(BotSettings).first()
    if not settings:
        settings = BotSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)

    if not settings.admin_username or not settings.admin_password_hash:
        pw_hash, salt = hash_password(ENV_ADMIN_PASSWORD)
        settings.admin_username = ENV_ADMIN_USERNAME
        settings.admin_password_hash = pw_hash
        settings.admin_password_salt = salt
        db.commit()
        db.refresh(settings)

    return settings


def verify_credentials(db, username: str, password: str) -> bool:
    settings = get_or_seed_admin_credentials(db)
    if username != settings.admin_username:
        return False
    return verify_password(password, settings.admin_password_hash, settings.admin_password_salt)


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


def login_required_or_redirect(request: Request):
    """Use in routes: returns a RedirectResponse if not logged in, else None."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return None
