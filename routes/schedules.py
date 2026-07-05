from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import login_required_or_redirect
from database import get_db
from models import Channel, Schedule, Source

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/schedules")
def list_schedules(request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    schedules = db.query(Schedule).order_by(Schedule.id).all()
    sources = db.query(Source).order_by(Source.name).all()
    channels = db.query(Channel).order_by(Channel.name).all()
    return templates.TemplateResponse(
        "schedules.html",
        {
            "request": request,
            "active_page": "schedules",
            "schedules": schedules,
            "sources": sources,
            "channels": channels,
        },
    )


@router.post("/schedules")
def create_schedule(
    request: Request,
    source_id: int = Form(...),
    channel_id: int = Form(...),
    cron_expression: str = Form(...),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    schedule = Schedule(
        source_id=source_id,
        channel_id=channel_id,
        cron_expression=cron_expression.strip(),
        is_active=is_active,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    from scheduler import add_or_update_job

    add_or_update_job(schedule)

    return RedirectResponse(url="/schedules", status_code=302)


@router.post("/schedules/{schedule_id}/delete")
def delete_schedule(schedule_id: int, request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    from scheduler import remove_job

    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if schedule:
        db.delete(schedule)
        db.commit()
        remove_job(schedule_id)
    return RedirectResponse(url="/schedules", status_code=302)


@router.post("/schedules/{schedule_id}/toggle")
def toggle_schedule(schedule_id: int, request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect

    from scheduler import add_or_update_job

    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if schedule:
        schedule.is_active = not schedule.is_active
        db.commit()
        add_or_update_job(schedule)

    wants_json = request.headers.get("x-requested-with") == "fetch"
    if wants_json:
        return JSONResponse({"id": schedule_id, "is_active": schedule.is_active if schedule else None})
    return RedirectResponse(url="/schedules", status_code=302)
