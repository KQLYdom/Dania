from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from notification_service import send_push

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request):
    from main import get_current_user
    return get_current_user(request)


@router.get("/shopping")
async def shopping(
    request: Request,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    items = db.query(models.ShoppingItem).order_by(
        models.ShoppingItem.completed.asc(),
        models.ShoppingItem.id.desc()
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="shopping.html",
        context={
            "user": user,
            "items": items
        }
    )


@router.post("/shopping/add")
async def add_item(
    name: str = Form(...),
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    db.add(
        models.ShoppingItem(
            name=name,
            added_by=user
        )
    )
    db.commit()
    send_push(
        db,
        "New shopping item",
        f"{user} added: {name}",
        "/shopping",
    )

    return RedirectResponse("/shopping", status_code=303)


@router.post("/shopping/toggle/{item_id}")
async def toggle_item(
    item_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    item = db.get(models.ShoppingItem, item_id)

    if item:
        item.completed = not item.completed
        db.commit()

    return RedirectResponse("/shopping", status_code=303)


@router.post("/shopping/delete/{item_id}")
async def delete_item(
    item_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    item = db.get(models.ShoppingItem, item_id)

    if item:
        db.delete(item)
        db.commit()

    return RedirectResponse("/shopping", status_code=303)
