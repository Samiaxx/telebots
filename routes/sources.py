from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import login_required_or_redirect
from database import get_db
from gemini import rewrite_content
from models import BotSettings, Source
from scraper import fetch_source_content

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _wants_json(request: Request) -> bool:
    return request.headers.get("x-requested-with") == "fetch" or "application/json" in request.headers.get("accept", "")


@router.get("/sources")
def list_sources(request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    sources = db.query(Source).order_by(Source.priority.desc(), Source.id).all()
    return templates.TemplateResponse(
        "sources.html", {"request": request, "active_page": "sources", "sources": sources, "edit_source": None}
    )


@router.get("/sources/{source_id}/edit")
def edit_source_form(source_id: int, request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    sources = db.query(Source).order_by(Source.priority.desc(), Source.id).all()
    edit_source = db.query(Source).filter(Source.id == source_id).first()
    return templates.TemplateResponse(
        "sources.html",
        {"request": request, "active_page": "sources", "sources": sources, "edit_source": edit_source},
    )


@router.post("/sources")
def create_source(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    url: str = Form(...),
    fetch_interval_minutes: int = Form(60),
    rewrite_style: str = Form("light"),
    language: str = Form("English"),
    topic_keywords: str = Form(""),
    persona: str = Form(""),
    priority: int = Form(5),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    source = Source(
        name=name,
        type=type,
        url=url,
        fetch_interval_minutes=fetch_interval_minutes,
        rewrite_style=rewrite_style,
        language=language,
        topic_keywords=topic_keywords,
        persona=persona,
        priority=priority,
        is_active=is_active,
    )
    db.add(source)
    db.commit()
    return RedirectResponse(url="/sources", status_code=302)


@router.post("/sources/{source_id}")
def update_source(
    source_id: int,
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    url: str = Form(...),
    fetch_interval_minutes: int = Form(60),
    rewrite_style: str = Form("light"),
    language: str = Form("English"),
    topic_keywords: str = Form(""),
    persona: str = Form(""),
    priority: int = Form(5),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    source = db.query(Source).filter(Source.id == source_id).first()
    if source:
        source.name = name
        source.type = type
        source.url = url
        source.fetch_interval_minutes = fetch_interval_minutes
        source.rewrite_style = rewrite_style
        source.language = language
        source.topic_keywords = topic_keywords
        source.persona = persona
        source.priority = priority
        source.is_active = is_active
        db.commit()
    return RedirectResponse(url="/sources", status_code=302)


@router.post("/sources/{source_id}/delete")
def delete_source(source_id: int, request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    source = db.query(Source).filter(Source.id == source_id).first()
    if source:
        db.delete(source)
        db.commit()
    return RedirectResponse(url="/sources", status_code=302)


@router.post("/sources/{source_id}/quick-toggle")
def quick_toggle_source(source_id: int, request: Request, db: Session = Depends(get_db)):
    """AJAX-friendly toggle: flips is_active and returns JSON instantly, no page reload."""
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        return JSONResponse({"error": "not found"}, status_code=404)
    source.is_active = not source.is_active
    db.commit()
    return JSONResponse({"id": source.id, "is_active": source.is_active})


@router.post("/sources/preview-rewrite")
async def preview_rewrite(request: Request, db: Session = Depends(get_db)):
    """Fetch a live sample from the source and run it through Gemini once,
    so the admin can hear the voice before turning a source on for real."""
    redirect = login_required_or_redirect(request)
    if redirect:
        return JSONResponse({"error": "Your session expired — please refresh the page and log in again."}, status_code=200)

    try:
        form = await request.form()
        source_id = form.get("source_id")

        sample_text = None
        language = form.get("language") or "English"
        keywords_raw = form.get("topic_keywords") or ""
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        persona = form.get("persona") or ""
        style = form.get("rewrite_style") or "light"
        url = (form.get("url") or "").strip()
        source_type = form.get("type") or "website"

        if source_id:
            source = db.query(Source).filter(Source.id == int(source_id)).first()
            if source:
                samples = fetch_source_content(source)
                sample_text = samples[0] if samples else None

        if not sample_text and source_type == "website" and url:
            from scraper import fetch_website_text

            sample_text = fetch_website_text(url)
        elif not sample_text and source_type == "telegram_channel" and url:
            from scraper import fetch_telegram_channel_web

            samples = fetch_telegram_channel_web(url)
            sample_text = samples[0] if samples else None

        if not sample_text:
            hint = (
                "Couldn't fetch a live sample. If this is a new Telegram channel, the first fetch always "
                "returns nothing (it's establishing a baseline) — try again in a minute. For a website, "
                "double check the URL is correct, reachable, and filled in above."
            )
            return JSONResponse({"error": hint}, status_code=200)

        settings = db.query(BotSettings).first()
        model_name = settings.gemini_model if settings else "gemini-flash-latest"

        rewritten = rewrite_content(
            content=sample_text[:3000],
            language=language,
            keywords=keywords,
            style=style,
            model_name=model_name,
            persona=persona,
        )

        return JSONResponse(
            {
                "original_preview": sample_text[:400],
                "rewritten": rewritten or "(Gemini returned SKIP for this sample — it didn't match the keywords/topic.)",
            }
        )
    except Exception as exc:  # noqa: BLE001 - always return a readable message, never a raw 500
        return JSONResponse({"error": f"Preview failed: {exc}"}, status_code=200)
