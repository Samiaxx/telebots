from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import login_required_or_redirect
from database import get_db
from models import Channel

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/channels")
def list_channels(request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    channels = db.query(Channel).order_by(Channel.id).all()
    return templates.TemplateResponse(
        "channels.html", {"request": request, "active_page": "channels", "channels": channels, "edit_channel": None}
    )


@router.get("/channels/{channel_id}/edit")
def edit_channel_form(channel_id: int, request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    channels = db.query(Channel).order_by(Channel.id).all()
    edit_channel = db.query(Channel).filter(Channel.id == channel_id).first()
    return templates.TemplateResponse(
        "channels.html",
        {"request": request, "active_page": "channels", "channels": channels, "edit_channel": edit_channel},
    )


@router.post("/channels")
def create_channel(
    request: Request,
    name: str = Form(...),
    telegram_id: str = Form(...),
    db: Session = Depends(get_db),
):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    channel = Channel(name=name, telegram_id=telegram_id)
    db.add(channel)
    db.commit()
    return RedirectResponse(url="/channels", status_code=302)


@router.post("/channels/{channel_id}")
def update_channel(
    channel_id: int,
    request: Request,
    name: str = Form(...),
    telegram_id: str = Form(...),
    db: Session = Depends(get_db),
):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if channel:
        channel.name = name
        channel.telegram_id = telegram_id
        db.commit()
    return RedirectResponse(url="/channels", status_code=302)


@router.post("/channels/{channel_id}/delete")
def delete_channel(channel_id: int, request: Request, db: Session = Depends(get_db)):
    redirect = login_required_or_redirect(request)
    if redirect:
        return redirect
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if channel:
        db.delete(channel)
        db.commit()
    return RedirectResponse(url="/channels", status_code=302)
