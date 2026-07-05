from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import login_required_or_redirect
from database import get_db
from models import Post

router = APIRouter()
templates = Jinja2Templates(directory="templates")

PAGE_SIZE = 25


@router.get("/posts")
def list_posts(request: Request, page: int = 1, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    page = max(page, 1)
    total = db.query(Post).count()
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(page, total_pages)

    posts = (
        db.query(Post)
        .order_by(Post.created_at.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    return templates.TemplateResponse(
        "posts.html",
        {
            "request": request,
            "active_page": "posts",
            "posts": posts,
            "page": page,
            "total_pages": total_pages,
        },
    )
